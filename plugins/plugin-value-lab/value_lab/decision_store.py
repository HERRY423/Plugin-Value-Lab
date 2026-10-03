"""Local decision continuity outside the evaluator and read-only MCP server.

Append-only events and raw bytes commit together in SQLite. No external execution,
scientific scoring, inferred authorization, or automatic retry occurs here.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .core import ValidationError, suite_digest, validate_suite
from .delivery import publish_bundle, read_bundle
from . import interpretation_history as explanations

LEGACY_FORMAT = "pvl-decision-store-1"
FORMAT = "pvl-decision-store-2"
UNRESOLVED = ("PENDING", "OUTCOME_UNKNOWN", "RESULT_AVAILABLE")
MAX_BYTES = 64 * 1024 * 1024


def _require(ok, message):
    if not ok:
        raise ValidationError(message)


def _id(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value) is not None


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _money(value):
    return type(value) is int and value >= 0


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _observations(state, ids):
    # Billing and late invocation identification are separate from raw observations.
    return suite_digest({ident: {k: state["attempts"][ident][k] for k in
        ("requirement", "mode", "operation", "external_key", "status", "receipt", "artifacts")}
        for ident in sorted(ids)})


def _apply(state, event):
    """Validate transitions identically on write and on recovery."""
    kind, p = event["kind"], event["payload"]
    if event["format"] == explanations.FORMAT:
        _require(state is not None and isinstance(kind, str) and kind in explanations.FIELDS,
                 "Unsupported explanation event or uninitialized study")
        state = explanations.apply_revision(state, kind, p)
        state["sequence"] += 1
        return state
    strict = event["format"] == FORMAT
    fields = {
        "initialize": {"plan", "plan_sha256", "required_evidence", "dependencies", "budget_micros"},
        "start": {"attempt_id", "requirement", "mode", "operation", "external_key", "max_cost_micros"},
        "identify": {"attempt_id", "invocation_id"}, "unknown": {"attempt_id", "reason"},
        "finish": {"attempt_id", "status", "receipt", "artifacts"},
        "settle": {"attempt_id", "cost_micros", "basis"},
        "cancel_request": {"attempt_id", "reason"},
        "reconcile": {"attempt_id", "operation", "external_key", "invocation_id", "remote_status", "receipt"},
        "interpret": {"interpretation_id", "mode", "reason", "attempt_ids", "rules", "dependencies", "pending_checks", "artifacts", "parent"},
    }
    optional = {"retry_of", "reason"} if strict and kind == "start" else set()
    _require(isinstance(kind, str) and kind in fields and isinstance(p, dict)
             and fields[kind] <= set(p) <= fields[kind] | optional, "Invalid event fields")
    _require(strict or kind not in ("cancel_request", "reconcile"), "Unsupported legacy event")
    if "artifacts" in p:
        _require(isinstance(p["artifacts"], dict) and all(_id(name) and isinstance(digest, str)
                 and re.fullmatch(r"[a-f0-9]{64}", digest) for name, digest in p["artifacts"].items()), "Invalid artifact bindings")
    if kind == "initialize":
        _require(state is None, "Decision already initialized")
        _require(isinstance(p["plan"], dict) and p["plan"], "Supply the frozen plan")
        _require(p["plan_sha256"] == suite_digest(p["plan"]), "Frozen plan changed")
        req = p["required_evidence"]
        _require(isinstance(req, list) and req and all(_id(x) for x in req)
                 and len(set(req)) == len(req), "Declare unique required evidence IDs")
        deps = p["dependencies"]
        _require(isinstance(deps, dict) and all(_text(k) and (v is None or _text(v)) for k, v in deps.items()),
                 "Dependencies map identities to strings or null")
        _require(_money(p["budget_micros"]), "Declare the task budget in integer USD micros")
        return {**deepcopy(p), "format": event["format"], "attempts": {}, "interpretations": [], "sequence": 1}
    _require(state is not None, "Initialize a decision first")
    if kind == "start":
        ident, requirement = p["attempt_id"], p["requirement"]
        _require(_id(ident) and ident not in state["attempts"], "Attempt ID is invalid or already used")
        _require(requirement in state["required_evidence"], "Unknown evidence requirement")
        _require(p["mode"] in ("model_execution", "scientific_execution", "tool_execution", "local_execution"), "Unknown execution mode")
        _require(_text(p["operation"]) and _text(p["external_key"]), "Record operation and original external idempotency key before dispatch")
        _require(p["max_cost_micros"] is None or _money(p["max_cost_micros"]), "Invalid reservation")
        attempts = state["attempts"].values()
        _require(not any(a["external_key"] == p["external_key"] for a in attempts), "External key already belongs to an attempt")
        _require(not any(a["requirement"] == requirement and a["status"] in UNRESOLVED for a in attempts),
                 "Reconcile the existing attempt; do not dispatch a duplicate")
        if strict:
            predecessors = [a for a in attempts if a["requirement"] == requirement]
            if predecessors:
                _require(p.get("retry_of") == predecessors[-1]["attempt_id"] and _text(p.get("reason")),
                         "Reexecution must name the latest terminal attempt and explain why")
            else:
                _require(not optional & set(p), "First execution has no retry predecessor")
        cost = _cost(state)
        _require(cost["unknown_reservations"] == 0, "Unbounded unsettled cost blocks new attempts")
        reserve = p["max_cost_micros"]
        _require(reserve is None or cost["accounted_micros"] + reserve <= state["budget_micros"], "Task budget exhausted")
        _require(cost["accounted_micros"] <= state["budget_micros"], "Task budget exceeded")
        state["attempts"][ident] = {**deepcopy(p), "status": "PENDING", "invocation_id": None,
            "cost_micros": None, "settled": False, "receipt": None, "artifacts": {}}
    elif kind in ("identify", "unknown", "finish", "settle", "cancel_request", "reconcile"):
        _require(p["attempt_id"] in state["attempts"], "Unknown attempt")
        attempt = state["attempts"][p["attempt_id"]]
        if kind == "identify":
            _require(_text(p["invocation_id"]) and attempt["invocation_id"] in (None, p["invocation_id"]), "Invocation identity cannot change")
            _require(not any(a["attempt_id"] != p["attempt_id"] and a["operation"] == attempt["operation"]
                             and a["invocation_id"] == p["invocation_id"] for a in state["attempts"].values()), "Invocation already recorded")
            attempt["invocation_id"] = p["invocation_id"]
        elif kind == "unknown":
            _require(attempt["status"] in UNRESOLVED and _text(p["reason"]), "Only unresolved attempts can become unknown")
            attempt.update(status="OUTCOME_UNKNOWN", reason=p["reason"])
        elif kind == "cancel_request":
            _require(attempt["status"] in UNRESOLVED and _text(p["reason"]), "Cancellation request needs an unresolved attempt and reason")
            attempt["cancellation_requested"] = True
            attempt["cancellation_reason"] = p["reason"]
        elif kind == "reconcile":
            _require(attempt["status"] in UNRESOLVED, "Terminal evidence cannot be reconciled again")
            _require(p["operation"] == attempt["operation"] and p["external_key"] == attempt["external_key"]
                     and p["invocation_id"] == attempt["invocation_id"], "Reconciliation must bind the original operation, key and invocation")
            _require(p["remote_status"] in ("pending", "not_found", "completed", "failed", "cancelled")
                     and isinstance(p["receipt"], dict) and p["receipt"], "Supply a source reconciliation receipt")
            prior_remote = attempt.get("remote_confirmation", {}).get("remote_status")
            _require(prior_remote not in ("completed", "failed", "cancelled") or p["remote_status"] == prior_remote,
                     "Conflicting terminal receipts require review; cannot overwrite confirmation")
            attempt["remote_confirmation"] = deepcopy(p)
            attempt["status"] = "RESULT_AVAILABLE" if p["remote_status"] == "completed" else "OUTCOME_UNKNOWN" if p["remote_status"] == "not_found" else "PENDING"
        elif kind == "finish":
            _require(attempt["status"] in UNRESOLVED, "Terminal evidence is immutable; use a new attempt")
            _require(p["status"] in ("COLLECTED", "FAILED", "CANCELLED"), "Invalid terminal status")
            _require(isinstance(p["receipt"], dict) and p["receipt"], "Retain a source receipt even for failure/cancellation")
            _require(p["status"] != "COLLECTED" or bool(p["artifacts"]), "Collected evidence requires actual artifact bytes")
            if strict and attempt["mode"] != "local_execution":
                remote = attempt.get("remote_confirmation", {})
                expected = {"COLLECTED": "completed", "FAILED": "failed", "CANCELLED": "cancelled"}[p["status"]]
                _require(remote.get("remote_status") == expected, "External finish requires matching terminal reconciliation; timeout/cancel request is not confirmation")
            attempt.update(status=p["status"], receipt=deepcopy(p["receipt"]), artifacts=deepcopy(p["artifacts"]))
        else:
            _require(not attempt["settled"] and _money(p["cost_micros"]) and _text(p["basis"]), "Settlement needs a confirmed amount and basis; cannot overwrite it")
            attempt.update(settled=True, cost_micros=p["cost_micros"], settlement_basis=p["basis"])
    elif kind == "interpret":
        _require(_id(p["interpretation_id"]) and not any(i["interpretation_id"] == p["interpretation_id"] for i in state["interpretations"]), "Interpretation ID already used or invalid")
        _require(p["mode"] in ("evaluation", "rescore") and _text(p["reason"]), "Declare interpretation mode and reason")
        ids = p["attempt_ids"]
        _require(isinstance(ids, list) and ids and len(ids) == len(set(ids)) and all(
            a in state["attempts"] and state["attempts"][a]["status"] in ("COLLECTED", "FAILED", "CANCELLED") for a in ids), "Interpret only terminal evidence; retain failures and cancellations")
        _require(isinstance(p["rules"], dict) and p["rules"] and isinstance(p["pending_checks"], list)
                 and all(_text(c) for c in p["pending_checks"]), "Retain rules and remaining checks")
        _require(isinstance(p["dependencies"], dict) and all(_text(k) and (v is None or _text(v)) for k, v in p["dependencies"].items()), "Retain interpretation dependency identities")
        _require(bool(p["artifacts"]), "Interpretation needs a retained report")
        _require(p["parent"] == (state["interpretations"][-1]["interpretation_id"] if state["interpretations"] else None), "Interpretation parent changed")
        observations = _observations(state, ids)
        if strict and p["mode"] == "rescore":
            _require(bool(state["interpretations"]), "Rescore requires a prior interpretation")
            prior = state["interpretations"][-1]
            _require(set(ids) == set(prior["attempt_ids"]) and observations == _observations(state, prior["attempt_ids"]),
                     "Rescore must use exactly the same raw observations; new executions require evaluation")
            _require(suite_digest(p["rules"]) != suite_digest(prior["rules"]), "Unchanged rules are replay, not a new rescore")
        interpretation = deepcopy(p)
        if strict:
            interpretation.update(observations_sha256=observations, rules_sha256=suite_digest(p["rules"]),
                                  result_sha256=suite_digest(p["artifacts"]), validation_basis="SUBMITTED_REPORT_NOT_INDEPENDENTLY_SCORED")
        state["interpretations"].append(interpretation)
    else:
        raise ValidationError("Unknown decision event")
    if kind == "start":
        explanations.invalidate(state, "New unsettled execution changes the task cost basis: " + p["attempt_id"])
    elif kind == "finish":
        explanations.invalidate(state, "Evidence group changed: " + p["attempt_id"],
                                requirement=state["attempts"][p["attempt_id"]]["requirement"])
    elif kind in ("interpret", "settle"):
        explanations.invalidate(state, "Legacy interpretation or cost basis changed; impact requires review")
    state["sequence"] += 1
    return state


def _cost(state):
    attempts = state["attempts"].values()
    confirmed = sum(a["cost_micros"] for a in attempts if a["settled"])
    reserved = sum(a["max_cost_micros"] for a in attempts if not a["settled"] and a["max_cost_micros"] is not None)
    unknown = sum(not a["settled"] and a["max_cost_micros"] is None for a in attempts)
    return {"confirmed_micros": confirmed, "reserved_micros": reserved, "unknown_reservations": unknown,
            "accounted_micros": confirmed + reserved, "total_cost_micros": confirmed if all(a["settled"] for a in attempts) else None}


def recovery_view(state):
    """Describe stored material; collection never asserts scientific success."""
    result = deepcopy(state)
    collected = {a["requirement"] for a in state["attempts"].values() if a["status"] == "COLLECTED"}
    missing = [r for r in state["required_evidence"] if r not in collected]
    next_steps = []
    for ident, a in state["attempts"].items():
        if a["status"] in UNRESOLVED:
            remote = a.get("remote_confirmation", {}).get("remote_status")
            action = "COLLECT_CONFIRMED_RESULT" if remote == "completed" else "RECORD_CONFIRMED_TERMINAL" if remote in ("failed", "cancelled") else "RECONCILE_ORIGINAL_INVOCATION"
            next_steps.append({"action": action, "attempt_id": ident,
                               "invocation_id": a["invocation_id"], "external_key": a["external_key"]})
        if not a["settled"]:
            next_steps.append({"action": "CONFIRM_COST", "attempt_id": ident})
    for req in missing:
        if not any(a["requirement"] == req and a["status"] in UNRESOLVED for a in state["attempts"].values()):
            next_steps.append({"action": "COLLECT_MISSING_EVIDENCE", "requirement": req})
    latest = state["interpretations"][-1] if state["interpretations"] else None
    structured = state.get("explanations", {}).get("judgments", {})
    reviewed = {i for j in structured.values() for i in j["attempt_ids"]}
    unreviewed = sorted(a for a, row in state["attempts"].items() if row["status"] in ("COLLECTED", "FAILED", "CANCELLED")
                        and (latest is None or a not in latest["attempt_ids"]) and a not in reviewed)
    if latest is None and not structured or unreviewed:
        next_steps.append({"action": "EVALUATE_RETAINED_EVIDENCE", "attempt_ids": unreviewed})
    for check in latest["pending_checks"] if latest else []:
        next_steps.append({"action": "COMPLETE_CHECK", "check": check})
    dependencies = dict(state["dependencies"])
    for interpretation in state["interpretations"]:
        dependencies.update(interpretation["dependencies"])
    for ident, value in dependencies.items():
        if value is None:
            next_steps.append({"action": "VERIFY_DEPENDENCY_IDENTITY", "dependency": ident})
    costs = _cost(state)
    if costs["accounted_micros"] > state["budget_micros"]:
        next_steps.append({"action": "REVIEW_BUDGET_OVERRUN"})
    lifecycle = explanations.revision_view(state)
    for did in lifecycle["guidance_review_required"]:
        next_steps.append({"action": "REVIEW_GUIDANCE", "decision_id": did})
    for jid, judgment in structured.items():
        if any(j["parent"] == jid for j in structured.values()):
            continue
        for check in judgment["result"]["pending_checks"]:
            next_steps.append({"action": "COMPLETE_CHECK", "check": check})
        for name, check in judgment["result"]["checks"].items():
            if check["status"] == "UNKNOWN":
                next_steps.append({"action": "REVIEW_UNKNOWN_CHECK", "judgment_id": jid, "check": name})
        if judgment["implementation"] is None:
            next_steps.append({"action": "VERIFY_JUDGMENT_IMPLEMENTATION", "judgment_id": jid})
    result.update(lifecycle)
    result.update(missing_evidence=missing, next_steps=next_steps, costs=costs,
                  recovery_contract={"new_events": FORMAT, "legacy_history_present": state["format"] == LEGACY_FORMAT,
                      "explanation_events": explanations.FORMAT,
                      "legacy_interpretations_without_observation_binding": [i["interpretation_id"] for i in state["interpretations"] if "observations_sha256" not in i],
                      "legacy_records_upgraded": False},
                  observation_groups={r: [i for i, a in state["attempts"].items() if a["requirement"] == r] for r in state["required_evidence"]},
                  effective_dependencies=dependencies,
                  collected_attempts=sum(a["status"] == "COLLECTED" for a in state["attempts"].values()),
                  current_interpretation=latest["interpretation_id"] if latest else None,
                  unreviewed_attempts=unreviewed, budget_exceeded=costs["accounted_micros"] > state["budget_micros"],
                  scientific_sample_size=None, execution_authorized=False,
                  status="FOLLOW_UP_REQUIRED" if next_steps else "MATERIALS_RECORDED",
                  limits=["Stored receipts and dependency identities are submitted evidence, not live verification.",
                          "Recovery and rescoring add no executions or scientific samples.",
                          "Collected bytes and completed checks do not establish benefit or scientific validity."])
    return result


class DecisionStore:
    def __init__(self, path):
        self.path = Path(path).absolute()

    def record_recheck(self, report, card, attempt_ids, judgment_id, *, parent=None, key, expected_sequence):
        """Import a submitted recheck bound to retained bytes; never run a grader."""
        from .evidence_dependencies import _verify_previous
        _verify_previous(report, card)
        view = self.snapshot()
        _require(isinstance(attempt_ids, list) and all(_id(i) and i in view["attempts"] for i in attempt_ids), "Unknown recheck observations")
        retained = {digest for i in attempt_ids for digest in view["attempts"][i]["artifacts"].values()}
        _require(all(row["sha256"] is None or row["sha256"] in retained for row in report["artifacts"].values()),
                 "Recheck artifacts must bind the selected retained bytes")
        nodes = report["graph"]["nodes"]
        contract = {"grader": {n["id"]: n for n in nodes if n["kind"] == "rule"},
                    "reference": {n["id"]: {"sha256": n["sha256"]} for n in nodes if n["kind"] == "artifact"},
                    "domain": {"coverage": report["graph"]["coverage"], "inventory": report["inventory"],
                               "evidence_ceiling": "BOUNDED_LOCAL_CHECKS_ONLY"}}
        result = {"checks": {ident: {"status": row["status"] if row["status"] in ("PASSED", "FAILED") else "UNKNOWN",
                                    "reason": row["reason"]} for ident, row in report["rules"].items()},
                  "pending_checks": ["Resolve " + row["rule_id"] + ": " + row["status"] for row in report["pending_tasks"]]
                      + ["Review dependency scope: " + reason for reason in report["fallback_reasons"]]}
        result["pending_checks"].extend("Review unmapped guidance: " + pointer for pointer in report["unmapped_card_pointers"])
        return self.append("judge", {"judgment_id": judgment_id, "mode": "rescore" if parent else "evaluation",
            "parent": parent, "attempt_ids": attempt_ids, "contract": contract, "implementation": report["engine_sha256"],
            "result": result, "reason": "Import dependency revision " + report["revision_sha256"] + "; submitted result, no independent scoring"},
            key=key, expected_sequence=expected_sequence,
            files={"source_recheck": (_json(report) + "\n").encode(), "source_card": (_json(card) + "\n").encode()})

    def initialize_study(self, suite, lock, dependencies, budget_micros, *, key):
        """Bind an existing paired study, preserving its lock and full denominator."""
        validate_suite(suite)
        expected = len(suite["cases"]) * suite["runs_per_case"] * 2
        _require(isinstance(lock, dict) and lock.get("suite_sha256") == suite_digest(suite)
                 and lock.get("expected_runs") == expected, "Study lock does not match the frozen suite")
        mapping = {f'{case["id"]}--{arm}--{rep}': {"case_id": case["id"], "arm": arm, "repetition": rep}
                   for case in suite["cases"] for arm in ("with", "without")
                   for rep in range(1, suite["runs_per_case"] + 1)}
        plan = {"suite": suite, "lock": lock, "requirements": mapping}
        return self.append("initialize", {"plan": plan, "plan_sha256": suite_digest(plan),
            "required_evidence": list(mapping), "dependencies": dependencies, "budget_micros": budget_micros},
            key=key, expected_sequence=0)

    @contextmanager
    def _connect(self, *, create=False, write=False):
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        _require(create or self.path.is_file(), "Decision store does not exist")
        # Even a snapshot may need SQLite's hot-journal rollback after a killed
        # writer. This local store is deliberately outside the read-only MCP API.
        connection = sqlite3.connect(self.path.as_uri() + ("?mode=rwc" if create else "?mode=rw"), uri=True, timeout=30)
        try:
            if write:
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("BEGIN IMMEDIATE")
            if create:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                _require(tables <= {"events", "blobs"}, "Target contains unrelated database tables")
                connection.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, event TEXT NOT NULL, digest TEXT NOT NULL)")
                connection.execute("CREATE TABLE IF NOT EXISTS blobs (digest TEXT PRIMARY KEY, data BLOB NOT NULL)")
            yield connection
            if write:
                connection.commit()
        except BaseException:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    def _read(self, db):
        state, previous = None, None
        for seq, key, encoded, digest in db.execute("SELECT seq, request_key, event, digest FROM events ORDER BY seq"):
            event = json.loads(encoded)
            _require(isinstance(event, dict) and set(event) == {"format", "request_key", "parent", "kind", "payload"}, "Invalid event envelope")
            _require(event["format"] in (LEGACY_FORMAT, FORMAT, explanations.FORMAT) and event["parent"] == previous and event["request_key"] == key
                     and suite_digest(event) == digest and seq == (state["sequence"] + 1 if state else 1), "Damaged or unsupported event history")
            state = _apply(state, event)
            for blob in event["payload"].get("artifacts", {}).values():
                row = db.execute("SELECT data FROM blobs WHERE digest=?", (blob,)).fetchone()
                _require(row is not None and _sha(row[0]) == blob, "Retained artifact missing or changed")
            previous = digest
        return state, previous

    @staticmethod
    def _checkpoint(state, head):
        return {"format": "pvl-decision-checkpoint-1", "sequence": state["sequence"],
                "head_sha256": head, "plan_sha256": state["plan_sha256"]}

    @staticmethod
    def _verify_checkpoint(db, state, checkpoint):
        _require(isinstance(checkpoint, dict) and set(checkpoint) == {"format", "sequence", "head_sha256", "plan_sha256"}
                 and checkpoint["format"] == "pvl-decision-checkpoint-1"
                 and type(checkpoint["sequence"]) is int and checkpoint["sequence"] > 0, "Invalid checkpoint")
        row = db.execute("SELECT digest FROM events WHERE seq=?", (checkpoint["sequence"],)).fetchone()
        _require(state is not None and row is not None and row[0] == checkpoint["head_sha256"]
                 and state["plan_sha256"] == checkpoint["plan_sha256"], "History does not match retained checkpoint (missing tail, changed history or wrong plan)")

    def snapshot(self, *, checkpoint=None):
        with self._connect() as db:
            db.execute("BEGIN")
            state, head = self._read(db)
            _require(state is not None, "Decision is not initialized")
            if checkpoint is not None:
                self._verify_checkpoint(db, state, checkpoint)
            return {**recovery_view(state), "checkpoint": self._checkpoint(state, head),
                    "checkpoint_verified": checkpoint is not None}

    def restore(self, bundle, *, checkpoint=None):
        """Restore exact event identities and bytes atomically; never run or rescore.

        An existing compatible continuation is retained. Conflicting histories are
        refused. Pin a separately retained checkpoint to reject rolled-back bundles.
        """
        bundle = Path(bundle)
        manifest = read_bundle(bundle)
        _require({"events.json", "decision.json"} <= manifest["files"].keys(), "Not a decision recovery bundle")
        events = json.loads((bundle / "events.json").read_bytes())
        _require(isinstance(events, list) and events, "Empty event history")
        state, parent, keys, blobs = None, None, set(), {}
        for event in events:
            _require(isinstance(event, dict) and set(event) == {"format", "request_key", "parent", "kind", "payload"}
                     and event["format"] in (LEGACY_FORMAT, FORMAT, explanations.FORMAT) and event["parent"] == parent
                     and _text(event["request_key"]) and event["request_key"] not in keys, "Invalid recovery event chain")
            keys.add(event["request_key"])
            state = _apply(state, event)
            for digest in event["payload"].get("artifacts", {}).values():
                name = digest + ".blob"
                _require(name in manifest["files"] and manifest["files"][name] == digest, "Recovery artifact is missing or misbound")
                data = (bundle / name).read_bytes()
                _require(len(data) <= MAX_BYTES and _sha(data) == digest, "Recovery artifact changed")
                blobs[digest] = data
            parent = suite_digest(event)
        expected = self._checkpoint(state, parent)
        if "checkpoint.json" in manifest["files"]:
            _require(json.loads((bundle / "checkpoint.json").read_bytes()) == expected, "Bundle checkpoint changed")
        # Read the presentation as evidence too, but derive all state from the log.
        submitted = json.loads((bundle / "decision.json").read_bytes())
        for field in ("plan_sha256", "sequence", "attempts", "interpretations"):
            _require(submitted.get(field) == state[field], "Recovery presentation disagrees with event history")
        _require(submitted.get("explanations") == state.get("explanations"), "Explanation history disagrees with event history")
        if checkpoint is not None:
            seq = checkpoint.get("sequence") if isinstance(checkpoint, dict) else None
            _require(type(seq) is int and 1 <= seq <= len(events), "Recovery bundle predates the retained checkpoint")
            _require(checkpoint == self._checkpoint({**state, "sequence": seq}, suite_digest(events[seq - 1])), "Recovery checkpoint mismatch")
        # Recheck the manifest after reads to reject a mixed source snapshot.
        _require(read_bundle(bundle) == manifest, "Recovery bundle changed during import")
        with self._connect(create=True, write=True) as db:
            current, head = self._read(db)
            if current is not None:
                self._verify_checkpoint(db, current, expected)
                return {**recovery_view(current), "replayed": True, "checkpoint": self._checkpoint(current, head),
                        "checkpoint_verified": checkpoint is not None}
            for digest, data in blobs.items():
                db.execute("INSERT INTO blobs VALUES (?, ?)", (digest, data))
            for index, event in enumerate(events, 1):
                db.execute("INSERT INTO events VALUES (?, ?, ?, ?)", (index, event["request_key"], _json(event), suite_digest(event)))
            # Same validation path as ordinary recovery, still inside the transaction.
            restored, head = self._read(db)
            return {**recovery_view(restored), "replayed": False, "checkpoint": self._checkpoint(restored, head),
                    "checkpoint_verified": checkpoint is not None}

    def append(self, kind, payload, *, key, expected_sequence, files=None):
        """Atomic, idempotent append; stale writers must reread before a new action."""
        _require(_text(key) and len(key) <= 200, "Supply a stable request key")
        _require(type(expected_sequence) is int and expected_sequence >= 0, "Supply the last read sequence")
        payload = deepcopy(payload)
        if kind == "judge" and isinstance(payload, dict):
            payload.setdefault("artifacts", {})
        blobs = {}
        if files is not None:
            _require(kind in ("finish", "interpret", "judge", "present") and isinstance(files, dict), "Only evidence events carry files")
            _require(all(_id(name) and isinstance(data, bytes) and len(data) <= MAX_BYTES for name, data in files.items()), "Invalid artifact name/bytes/size")
            payload["artifacts"] = {name: _sha(data) for name, data in files.items()}
            blobs = {_sha(data): data for data in files.values()}
        _json(payload)
        with self._connect(create=kind == "initialize", write=True) as db:
            state, parent = self._read(db)
            old = db.execute("SELECT event FROM events WHERE request_key=?", (key,)).fetchone()
            if old:
                original = json.loads(old[0])
                _require(original["kind"] == kind and original["payload"] == payload, "Idempotency key reused with changed request")
                return {**recovery_view(state), "replayed": True}
            _require(expected_sequence == (state["sequence"] if state else 0), "Stale decision sequence; read current state")
            event = {"format": explanations.FORMAT if kind in explanations.FIELDS else FORMAT,
                     "request_key": key, "parent": parent, "kind": kind, "payload": payload}
            state = _apply(state, event)
            for digest, data in blobs.items():
                db.execute("INSERT OR IGNORE INTO blobs VALUES (?, ?)", (digest, data))
            for digest in payload.get("artifacts", {}).values():
                row = db.execute("SELECT data FROM blobs WHERE digest=?", (digest,)).fetchone()
                _require(row is not None and _sha(row[0]) == digest, "Artifact bytes must be committed with evidence")
            db.execute("INSERT INTO events VALUES (?, ?, ?, ?)", (state["sequence"], key, _json(event), suite_digest(event)))
            return {**recovery_view(state), "replayed": False}

    def export(self, output, *, resume=False):
        output = Path(output).absolute()
        _require(not self.path.is_relative_to(output), "Export must not contain the live store")
        with self._connect() as db:
            db.execute("BEGIN")
            state, head = self._read(db)
            _require(state is not None, "Decision is not initialized")
            view = {**recovery_view(state), "checkpoint": self._checkpoint(state, head), "checkpoint_verified": False}
            files = {"decision.json": (_json(view) + "\n").encode(),
                     "checkpoint.json": (_json(self._checkpoint(state, head)) + "\n").encode(),
                     "events.json": (_json([json.loads(row[0]) for row in db.execute("SELECT event FROM events ORDER BY seq")]) + "\n").encode()}
            for digest, data in db.execute("SELECT digest, data FROM blobs"):
                _require(_sha(data) == digest, "Damaged artifact")
                files[digest + ".blob"] = data
        from .usage import _markdown
        cost = view["costs"]
        lines = ["# 科研决策恢复", "", "状态：" + ("需要后续处理" if view["next_steps"] else "材料已记录，科学判断见原报告"),
                 "", "已收集执行尝试：" + str(view["collected_attempts"]) + "；尚缺证据项：" + str(len(view["missing_evidence"])),
                 "科学样本量：未推断。恢复记录不会增加观察数量。", "",
                 "已确认费用（USD micros）：" + str(cost["confirmed_micros"]),
                 "未结算预留（USD micros）：" + str(cost["reserved_micros"]),
                 "上限未知的未结算项：" + str(cost["unknown_reservations"]),
                 "总费用（USD micros）：" + (str(cost["total_cost_micros"]) if cost["total_cost_micros"] is not None else "未知，需对账"),
                 "1 美元 = 1000000 USD micros；登记预算不会修改外部服务的收费设置。", "", "## 下一步", ""]
        for step in view["next_steps"]:
            action = step["action"]
            if action == "RECONCILE_ORIGINAL_INVOCATION":
                message = "核实执行 " + step["attempt_id"] + " 的原调用结果。调用标识：" + str(step["invocation_id"]) + "；原请求键：" + step["external_key"] + "。不要新建请求重试。"
            elif action == "COLLECT_CONFIRMED_RESULT":
                message = "原调用已报告完成，收集执行 " + step["attempt_id"] + " 的真实产物；尚不能计为已收集或科学通过。"
            elif action == "RECORD_CONFIRMED_TERMINAL":
                message = "原调用已报告失败或取消，为执行 " + step["attempt_id"] + " 保存终态收据；费用仍须另行对账。"
            elif action == "CONFIRM_COST":
                message = "核对执行 " + step["attempt_id"] + " 的费用；未确认前保留预留。"
            elif action == "COLLECT_MISSING_EVIDENCE":
                message = "补齐计划中的证据项：" + step["requirement"]
            elif action == "EVALUATE_RETAINED_EVIDENCE":
                message = "使用原评估器检查已保留的材料，包含失败与取消记录；不能沿用旧报告视为已通过。待评估尝试：" + ", ".join(step["attempt_ids"])
            elif action == "COMPLETE_CHECK":
                message = "完成剩余检查：" + step["check"]
            elif action == "VERIFY_DEPENDENCY_IDENTITY":
                message = "确认依赖身份或版本：" + step["dependency"]
            elif action == "REVIEW_GUIDANCE":
                message = "复核建议 " + step["decision_id"] + "；旧判断和原报告已保留，新评分不会自动恢复建议。"
            elif action == "VERIFY_JUDGMENT_IMPLEMENTATION":
                message = "确认判断实现身份：" + step["judgment_id"]
            elif action == "REVIEW_UNKNOWN_CHECK":
                message = "复核判断 " + step["judgment_id"] + " 中仍未知的检查：" + step["check"]
            else:
                message = "累计费用已超过登记预算，需要核对超支记录；当前不应启动新尝试。"
            lines.append("- " + _markdown(message))
        lines += ["", "## 原方案与解释", "", "冻结方案摘要：" + view["plan_sha256"],
                  "最近记录的解释：" + _markdown(view["current_interpretation"]),
                  "完整原计划、锁文件、依赖版本、历史解释和产物绑定见 decision.json；事件历史见 events.json。", "",
                  "恢复不重新执行、不授权付费、不改变原科学判断。依赖身份与执行收据来自提交材料。"]
        if view["recovery_contract"]["legacy_history_present"]:
            lines += ["", "本研究包含旧版历史，按原有含义保留；不能声称旧记录已经满足新版重评分绑定或外部终态核实要求。"]
        lines += ["", "## 建议修订状态", "", "旧版解释不会自动提升为当前建议；展示文件只反映生成时的状态。", ""]
        for did, status in view.get("explanations", {}).get("decision_states", {}).items():
            lines.append("- " + _markdown(did + ": " + status["status"] + " — " + status["reason"]
                         + ("；替代版本：" + status["superseded_by"] if status["superseded_by"] else "")))
        lines += ["", "最近解释不等于当前建议；current 仅表示记录中的当前选择，不代表科学认可或执行授权。",
                  "需要结合新状态阅读的历史展示：" + _markdown(view["stale_presentations"]), "",
                  "| 判断版本 | 观察摘要 | 判断契约摘要 | 结构化检查 |", "| --- | --- | --- | --- |"]
        for jid, judgment in view.get("explanations", {}).get("judgments", {}).items():
            statuses = ", ".join(k + ": " + v["status"] for k, v in judgment["result"]["checks"].items())
            lines.append("| " + " | ".join(_markdown(v) for v in (jid, judgment["observation_sha256"], judgment["judgment_sha256"], statuses)) + " |")
        files["RECOVERY.md"] = ("\n".join(lines) + "\n").encode()
        return publish_bundle(output, files, resume=resume)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    show = sub.add_parser("show")
    show.add_argument("--checkpoint", help="A previously retained checkpoint; rejects history rollback")
    restore = sub.add_parser("restore", help="Restore exact events and bytes; never execute or score")
    restore.add_argument("--bundle", required=True)
    restore.add_argument("--checkpoint", help="A separately retained checkpoint")
    init = sub.add_parser("init", help="Bind an existing frozen paired study")
    for option in ("suite", "lock", "dependencies", "key"):
        init.add_argument("--" + option, required=True)
    init.add_argument("--budget-micros", type=int, required=True)
    add = sub.add_parser("append", help="Submit a local event; never dispatch an external request")
    add.add_argument("--event", required=True, help="JSON with kind, payload, key, expected_sequence")
    add.add_argument("--artifact", action="append", default=[], metavar="ID=PATH")
    recheck = sub.add_parser("record-recheck", help="Import a retained dependency recheck; no scoring or execution")
    for name in ("report", "card", "judgment-id", "key"):
        recheck.add_argument("--" + name, required=True)
    recheck.add_argument("--attempt", action="append", required=True)
    recheck.add_argument("--parent")
    recheck.add_argument("--expected-sequence", type=int, required=True)
    export = sub.add_parser("export")
    export.add_argument("--output", required=True)
    export.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        store = DecisionStore(args.store)
        if args.action == "init":
            result = store.initialize_study(*[json.loads(Path(p).read_text(encoding="utf-8"))
                for p in (args.suite, args.lock, args.dependencies)], args.budget_micros, key=args.key)
        elif args.action == "show":
            result = store.snapshot(checkpoint=json.loads(Path(args.checkpoint).read_bytes()) if args.checkpoint else None)
        elif args.action == "restore":
            result = store.restore(args.bundle, checkpoint=json.loads(Path(args.checkpoint).read_bytes()) if args.checkpoint else None)
        elif args.action == "export":
            result = store.export(args.output, resume=args.resume)
        elif args.action == "record-recheck":
            result = store.record_recheck(json.loads(Path(args.report).read_bytes()), json.loads(Path(args.card).read_bytes()),
                args.attempt, args.judgment_id, parent=args.parent, key=args.key, expected_sequence=args.expected_sequence)
        else:
            event = json.loads(Path(args.event).read_text(encoding="utf-8"))
            files = {}
            for spec in args.artifact:
                name, path = spec.split("=", 1)
                _require(name not in files, "Duplicate artifact ID")
                with Path(path).open("rb") as stream:
                    data = stream.read(MAX_BYTES + 1)
                _require(len(data) <= MAX_BYTES, "Artifact exceeds 64 MiB")
                files[name] = data
            result = store.append(**event, files=files if args.artifact else None)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 3 if result.get("status") == "INCOMPLETE" else 0
    except (ValidationError, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
