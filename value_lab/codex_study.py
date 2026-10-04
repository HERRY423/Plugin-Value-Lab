"""Prospective Codex study coordinator; no model or browser dispatch.

This is a local control and review path, not a Codex execution API. Normalized
operator captures cannot authenticate the host's complete effective context.
Until that transport is qualified, live host acceptance remains blocked.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from functools import wraps
import json
import math
import os
from pathlib import Path
import re
import shutil

from .core import ValidationError, _grade, _number, _stamp, evaluate, freeze, load_json, suite_digest, validate_suite
from .artifacts import confined, sha
from .attempt_journal import AttemptJournal, _TRANSITIONS, _RETRYABLE
from .codex_evidence import inspect_observation
from .codex import schedule


FORMAT = "pvl-codex-study-plan-1"
LIMIT = 16 * 1024 * 1024


def _save(path, value):
    """Exclusive writes: a later observation never replaces an earlier one."""
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def _read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT:
        raise ValidationError("Missing, linked or oversized study evidence")
    return load_json(path)


def _hex(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _tools(items):
    if not isinstance(items, list):
        return False
    names = []
    for item in items:
        if (not isinstance(item, dict) or set(item) != {"name", "definition_sha256"}
                or not _text(item["name"]) or not _hex(item["definition_sha256"])):
            return False
        names.append(item["name"])
    return len(names) == len(set(names))


def _validate(suite, contract):
    validate_suite(suite)
    keys = {"host", "plugin", "common_tools", "candidate_tools", "context_sha256", "max_attempts_per_slot"}
    if not isinstance(contract, dict) or set(contract) != keys:
        raise ValidationError("Explicit host, plugin, tool definitions, context and retry limit required")
    host = contract["host"]
    if (not isinstance(host, dict) or set(host) != {"product", "surface", "build", "model"}
            or host["product"] != "codex" or host["surface"] != "desktop"
            or any(not _text(host[k]) or host[k].lower() in {"unknown", "latest", "auto"} for k in ("build", "model"))):
        raise ValidationError("Codex desktop requires product=codex, surface=desktop and an explicit build/model; unknown/latest is not a version")
    conditions = suite["conditions"]
    if (conditions["host"] != "codex" or conditions.get("host_version") != host["build"]
            or conditions["model"] != host["model"]):
        raise ValidationError("Suite and host contract must name the same Codex build and model")
    plugin = contract["plugin"]
    if (not isinstance(plugin, dict) or set(plugin) != {"id", "version", "sha256"}
            or plugin["id"] != suite["plugin"]["name"] or plugin["version"] != suite["plugin"]["version"]
            or not _hex(plugin["sha256"])):
        raise ValidationError("Candidate identity/version/content digest must match suite")
    if not all(_tools(contract[k]) for k in ("common_tools", "candidate_tools")):
        raise ValidationError("Tool inventories require unique names and definition digests")
    common = {t["name"] for t in contract["common_tools"]}
    candidate = {t["name"] for t in contract["candidate_tools"]}
    if common & candidate or sorted(common) != sorted(conditions["tools"]):
        raise ValidationError("Common tools must match suite; candidate tools must be separate")
    if not _hex(contract["context_sha256"]):
        raise ValidationError("Shared instruction/context digest required")
    if type(contract["max_attempts_per_slot"]) is not int or not 1 <= contract["max_attempts_per_slot"] <= 5:
        raise ValidationError("Freeze a retry limit in 1..5")
    # First host path deliberately supports raw textual/JSON outputs only.
    # Unsupported graders cannot silently become operator-supplied pass flags.
    for case in suite["cases"]:
        if suite["policy"].get("power_plan", {}).get("version") == 3:
            if case.get("input_sha256") != hashlib.sha256(case["prompt"].encode("utf-8")).hexdigest():
                raise ValidationError("Confirmation input_sha256 must bind the exact inline prompt bytes")
        if case.get("inputs"):
            raise ValidationError("First Codex path requires all public task input inline in the frozen prompt")
        if any(g["type"] not in {"contains", "not_contains", "json_equals"} for g in case["graders"]):
            raise ValidationError("This host path supports frozen literal/JSON graders on raw output only")


def prepare(suite, contract, output):
    """Freeze a prospective protocol and balanced slots, without starting a host."""
    suite, contract = deepcopy(suite), deepcopy(contract)
    _validate(suite, contract)
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    _save(root / "suite.json", suite)
    _save(root / "contract.json", contract)
    lock = freeze(suite, root / "protocol.lock.json")
    slots = []
    for index, item in enumerate(schedule(suite)):
        case = next(c for c in suite["cases"] if c["id"] == item["case_id"])
        slots.append({**item, "slot_id": f"slot-{index + 1:04d}", "prompt": case["prompt"],
                      "input_sha256": hashlib.sha256(case["prompt"].encode("utf-8")).hexdigest()})
    plan = {"format": FORMAT, **contract, "suite_sha256": suite_digest(suite),
            "lock_sha256": sha(root / "protocol.lock.json"), "frozen_at": lock["frozen_at"],
            "schedule": slots, "primary_attempt_rule": "first_registered_attempt",
            "retry_rule": "diagnostic_only_never_replace_primary", "sampling": "independent_samples_not_controlled_seeds",
            "live_dispatch_available": False, "host_transport": "NOT_QUALIFIED"}
    _save(root / "plan.json", plan)
    pin = sha(root / "plan.json")
    AttemptJournal(root / "attempts.sqlite", pin)
    (root / ".control.lock").write_bytes(b"0")
    (root / "captures").mkdir()
    (root / "submissions").mkdir()
    return {"plan_sha256": pin, "slots": len(slots), "model_calls": 0, "live_dispatch_available": False}


def _load(root, expected_plan_sha256):
    root = Path(root).resolve()
    plan = _read(root / "plan.json")
    if not _hex(expected_plan_sha256) or sha(root / "plan.json") != expected_plan_sha256:
        raise ValidationError("Frozen plan digest mismatch")
    suite, contract = _read(root / "suite.json"), _read(root / "contract.json")
    _validate(suite, contract)
    if (plan.get("format") != FORMAT or plan.get("suite_sha256") != suite_digest(suite)
            or plan.get("lock_sha256") != sha(root / "protocol.lock.json")
            or _read(root / "protocol.lock.json").get("suite_sha256") != suite_digest(suite)
            or any(plan.get(key) != value for key, value in contract.items())):
        raise ValidationError("Frozen study changed")
    expected = []
    for index, item in enumerate(schedule(suite)):
        case = next(c for c in suite["cases"] if c["id"] == item["case_id"])
        expected.append({**item, "slot_id": f"slot-{index + 1:04d}", "prompt": case["prompt"],
                         "input_sha256": hashlib.sha256(case["prompt"].encode("utf-8")).hexdigest()})
    if (plan["schedule"] != expected or plan["frozen_at"] != _read(root / "protocol.lock.json")["frozen_at"]
            or plan["primary_attempt_rule"] != "first_registered_attempt"
            or plan["retry_rule"] != "diagnostic_only_never_replace_primary"):
        raise ValidationError("Schedule or primary-attempt rule changed")
    return root, suite, {**plan, "plan_sha256": expected_plan_sha256}


def _journal(root, pin):
    path = root / "attempts.sqlite"
    if not path.is_file() or path.is_symlink():
        raise ValidationError("Attempt journal missing or linked; never recreate an existing study's history")
    return AttemptJournal(path, pin, create=False)


def _captures(root):
    path = root / "captures"
    if path.is_symlink() or not path.is_dir() or path.resolve().parent != root:
        raise ValidationError("Capture directory missing or outside the study boundary")
    return path


def _submissions(root):
    path = root / "submissions"
    if path.is_symlink() or not path.is_dir() or path.resolve().parent != root:
        raise ValidationError("Submission archive missing or outside the study boundary")
    return path


@contextmanager
def _study_lock(directory):
    """Serialize controller admission/capture/export; OS releases on crash."""
    path = Path(directory).resolve() / ".control.lock"
    if path.is_symlink() or not path.is_file() or path.stat().st_size != 1:
        raise ValidationError("Study coordinator lock missing or invalid")
    with path.open("r+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValidationError("Another controller owns this study; inspect original state before retrying") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _exclusive(function):
    @wraps(function)
    def wrapped(directory, *args, **kwargs):
        with _study_lock(directory):
            return function(directory, *args, **kwargs)
    return wrapped


@_exclusive
def reserve(directory, pin, slot_id, key, *, retry_of=None):
    """Reserve locally before a manual send; this receipt never authorizes spend."""
    root, _, plan = _load(directory, pin)
    slots = [s["slot_id"] for s in plan["schedule"]]
    if slot_id not in slots:
        raise ValidationError("Unknown frozen slot")
    journal = _journal(root, pin)
    attempts = journal.snapshot()["attempts"]
    if any(a["idempotency_key"] == key for a in attempts):
        return journal.reserve(slot_id, key, retry_of=retry_of)
    if any(a["state"] in {"prepared", "dispatched", "running", "unknown"} for a in attempts):
        raise ValidationError("Resolve the existing pending attempt before any further reservation")
    existing = [a for a in attempts if a["slot_id"] == slot_id]
    if len(existing) >= plan["max_attempts_per_slot"]:
        raise ValidationError("Frozen retry limit reached")
    if not existing:
        earlier = set(slots[:slots.index(slot_id)])
        terminal = {a["slot_id"] for a in attempts if a["state"] in {"completed", "failed", "cancelled", "not_dispatched"}}
        if earlier - terminal:
            raise ValidationError("Earlier scheduled slot is missing or unresolved")
    return journal.reserve(slot_id, key, retry_of=retry_of)


@_exclusive
def record_state(directory, pin, attempt_id, state, evidence):
    root, _, _ = _load(directory, pin)
    return _journal(root, pin).transition(attempt_id, state, evidence)


@_exclusive
def capture(directory, pin, packet_path):
    """Retain exact supplied capture bytes before recording its terminal state.

    Even malformed evidence is retained as a rejected capture. It cannot make
    a completed observation or erase a previously dispatched/unknown attempt.
    """
    root, _, plan = _load(directory, pin)
    source = Path(packet_path)
    packet = _read(source)
    if not isinstance(packet, dict) or not _text(packet.get("attempt_id")):
        raise ValidationError("Capture requires an existing attempt_id")
    journal = _journal(root, pin)
    attempts = journal.snapshot()["attempts"]
    attempt = next((a for a in attempts if a["attempt_id"] == packet["attempt_id"]), None)
    if attempt is None:
        raise ValidationError("Capture was not registered before execution")
    target = confined(_captures(root), attempt["attempt_id"] + ".json")
    raw = source.read_bytes()
    if target.exists():
        if target.read_bytes() != raw:
            raise ValidationError("Capture already sealed; conflicting bytes cannot replace it")
    submission_name = attempt["attempt_id"] + "-" + hashlib.sha256(raw).hexdigest() + ".json"
    submission = confined(_submissions(root), submission_name)
    if not submission.exists():
        with submission.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    receipt = {"kind": "capture_received", "source_ref": "submissions/" + submission_name, "sha256": sha(submission)}
    if not any(e["attempt_id"] == attempt["attempt_id"] and e["payload"] == receipt for e in journal.snapshot()["events"]):
        journal.note(attempt["attempt_id"], receipt)
    slot = next(s for s in plan["schedule"] if s["slot_id"] == attempt["slot_id"])
    result = inspect_observation(packet, plan=plan, slot=slot)
    if attempt["state"] not in {"dispatched", "running", "unknown", "completed", "failed", "cancelled"}:
        result["issues"].append("ATTEMPT_NOT_DISPATCHED")
    issues = result["issues"] + _sources(packet)
    if not issues and result["status"] in {"completed", "failed", "cancelled"}:
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        journal.transition(attempt["attempt_id"], result["status"], {"source_ref": "captures/" + target.name, "sha256": sha(target)})
    return {"capture_sha256": sha(submission), "retained_submission": receipt["source_ref"], "issues": issues, "model_calls": 0}


def _sources(packet):
    sources = packet.get("sources")
    refs = [packet.get("host_source_ref")]
    for key in ("context", "exposure"):
        value = packet.get(key)
        refs.append(value.get("source_ref") if isinstance(value, dict) else None)
    for event in packet.get("events", []) if isinstance(packet.get("events"), list) else []:
        if isinstance(event, dict) and event.get("kind") == "inventory":
            exposure = event.get("exposure")
            refs.append(exposure.get("source_ref") if isinstance(exposure, dict) else None)
    if (not isinstance(sources, dict) or not sources
            or any(not _text(k) or not _text(v) for k, v in sources.items())
            or any(not isinstance(ref, str) or ref not in sources for ref in refs)):
        return ["RAW_SOURCE_REFERENCE_MISSING"]
    return []


def _score(case, output, status):
    rows = []
    for grader in case["graders"]:
        try:
            passed, reason = _grade(grader, {"output": output}) if status == "completed" else (None, "Attempt not completed")
        except (RecursionError, UnicodeError):
            passed, reason = False, "Raw output cannot be parsed as bounded UTF-8 JSON"
        rows.append({"id": grader["id"], "dimension": grader["dimension"], "weight": grader["weight"],
                     "passed": passed, "reason": reason})
    outcomes = [r for r in rows if r["dimension"] == "outcome"]
    quality = (sum(r["weight"] * r["passed"] for r in outcomes) / sum(r["weight"] for r in outcomes)
               if all(type(r["passed"]) is bool for r in outcomes) else None)
    return {"graders": rows, "quality": quality}


def _validate_snapshot(snapshot, pin):
    """Recheck history structure during offline replay, not just file hashes."""
    try:
        if snapshot["format"] != "pvl-attempt-journal-1" or snapshot["plan_sha256"] != pin:
            raise ValueError("journal identity")
        attempts = snapshot["attempts"]
        rows = {a["attempt_id"]: a for a in attempts}
        if len(rows) != len(attempts) or len({a["idempotency_key"] for a in attempts}) != len(attempts):
            raise ValueError("duplicate attempt or key")
        state, last_event, by_slot, first_ids = {}, {}, {}, []
        previous_time = None
        for index, event in enumerate(snapshot["events"], 1):
            if type(event["seq"]) is not int or event["seq"] != index:
                raise ValueError("event sequence gap")
            aid, current, evidence = event["attempt_id"], event["state"], event["payload"]
            if aid not in rows or not isinstance(evidence, dict) or not evidence:
                raise ValueError("orphan event or absent evidence")
            when = datetime.fromisoformat(event["occurred_at"])
            if when.tzinfo is None or (previous_time and when < previous_time):
                raise ValueError("event timestamp")
            previous_time = when
            row = rows[aid]
            if aid not in state:
                if current != "prepared" or evidence != {"slot_id": row["slot_id"], "idempotency_key": row["idempotency_key"], "retry_of": row["retry_of"]}:
                    raise ValueError("missing reservation event")
                previous = by_slot.get(row["slot_id"])
                if row["retry_of"] != previous or (previous and state[previous] not in _RETRYABLE):
                    raise ValueError("invalid retry chain")
                if row["created_at"] != event["occurred_at"]:
                    raise ValueError("attempt creation timestamp")
                by_slot[row["slot_id"]] = aid
                first_ids.append(aid)
            elif evidence.get("kind") == "capture_received":
                if current != state[aid] or current not in {"prepared", "dispatched", "running", "unknown"}:
                    raise ValueError("capture receipt changed terminal state")
            else:
                if current not in _TRANSITIONS[state[aid]]:
                    raise ValueError("invalid state transition")
                if (state[aid] == "unknown" or current == "not_dispatched") and not _text(evidence.get("source_ref")):
                    raise ValueError("missing reconciliation evidence")
            state[aid], last_event[aid] = current, event
        if first_ids != list(rows) or snapshot["last_seq"] != len(snapshot["events"]):
            raise ValueError("attempt inventory or journal suffix mismatch")
        for aid, row in rows.items():
            last = last_event[aid]
            if (row["state"] != state[aid] or row["last_seq"] != last["seq"] or row["updated_at"] != last["occurred_at"]):
                raise ValueError("attempt summary differs from events")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("Invalid attempt history: " + str(exc)) from exc


def _assess(root, suite, plan, snapshot, settlement=None):
    if settlement is not None and suite["policy"].get("power_plan", {}).get("version") != 3:
        raise ValidationError("Settlement integration requires a prospectively frozen v3 confirmation plan")
    _validate_snapshot(snapshot, plan["plan_sha256"])
    issues, rows, sessions, requests = [], [], set(), set()
    attempts = snapshot["attempts"]
    if snapshot.get("plan_sha256") != plan["plan_sha256"]:
        raise ValidationError("Journal belongs to another frozen study")
    known = {s["slot_id"]: s for s in plan["schedule"]}
    retained_submissions = []
    note_paths = set()
    attempt_map = {a["attempt_id"]: a for a in attempts}
    for event in snapshot["events"]:
        evidence = event.get("payload", {})
        if evidence.get("kind") != "capture_received":
            continue
        name = evidence.get("source_ref")
        path = confined(root, name)
        note_paths.add(name)
        if not path.is_file() or path.is_symlink() or sha(path) != evidence.get("sha256"):
            issues.append("SUBMISSION_MISSING_OR_CHANGED:" + str(name))
            continue
        packet = _read(path)
        attempt = attempt_map.get(event["attempt_id"])
        local = []
        if attempt is None or attempt["slot_id"] not in known:
            local.append("SUBMISSION_ATTEMPT_UNKNOWN")
        else:
            result = inspect_observation(packet, plan=plan, slot=known[attempt["slot_id"]])
            local += result["issues"] + _sources(packet)
        retained_submissions.append({"path": name, "sha256": evidence["sha256"], "issues": local})
        issues.extend("RETAINED_SUBMISSION:" + str(name) + ":" + issue for issue in local)
    actual_submissions = {p.relative_to(root).as_posix() for p in _submissions(root).iterdir()}
    if actual_submissions != note_paths:
        issues.append("SUBMISSION_ARCHIVE_JOURNAL_MISMATCH")
    seen_slots, synthetic = set(), suite["evidence_type"] == "synthetic"
    for attempt in attempts:
        aid, slot_id = attempt["attempt_id"], attempt["slot_id"]
        if slot_id not in known:
            issues.append("UNPLANNED_ATTEMPT:" + aid)
            continue
        slot = known[slot_id]
        primary = slot_id not in seen_slots
        seen_slots.add(slot_id)
        path = confined(_captures(root), aid + ".json")
        local = []
        packet = _read(path) if path.exists() else None
        output, observed = None, "unknown"
        if packet is None:
            local.append("CAPTURE_MISSING")
        else:
            result = inspect_observation(packet, plan=plan, slot=slot, seen_sessions=sessions, seen_requests=requests)
            local += result["issues"] + _sources(packet)
            output, observed = result["output"], result["status"]
            if packet.get("attempt_id") != aid:
                local.append("ATTEMPT_ID_MISMATCH")
            synthetic |= packet.get("origin") == "synthetic"
            for key, seen in (("session_id", sessions), ("request_id", requests)):
                if _text(packet.get(key)):
                    seen.add(packet[key])
            # Captures are bound to the journal's terminal event, not just a file
            # named after an attempt. A crash before the event remains unresolved.
            event = next((e for e in reversed(snapshot["events"]) if e.get("attempt_id") == aid), {})
            evidence = event.get("payload", {})
            if (attempt["state"] != observed or evidence.get("sha256") != sha(path)
                    or evidence.get("source_ref") != "captures/" + path.name):
                local.append("CAPTURE_NOT_RECONCILED_WITH_JOURNAL")
            dispatched = [e for e in snapshot["events"] if e.get("attempt_id") == aid and e.get("state") == "dispatched"]
            if not dispatched:
                local.append("DISPATCH_RECORD_MISSING")
            else:
                try:
                    start = datetime.fromisoformat(packet["started_at"])
                    finish = datetime.fromisoformat(packet["finished_at"])
                    dispatch = datetime.fromisoformat(dispatched[0]["occurred_at"])
                    terminal = datetime.fromisoformat(event["occurred_at"])
                    if start < dispatch or finish > terminal:
                        local.append("OBSERVATION_OUTSIDE_JOURNALED_DISPATCH_INTERVAL")
                except (KeyError, ValueError, TypeError):
                    local.append("OBSERVATION_DISPATCH_TIME_UNVERIFIABLE")
            if not any(item["sha256"] == sha(path) for item in retained_submissions):
                local.append("CANONICAL_CAPTURE_WITHOUT_RECEIPT")
        if attempt["state"] not in {"completed", "failed", "cancelled", "not_dispatched"}:
            local.append("ATTEMPT_OUTCOME_UNRESOLVED")
        if primary and attempt["state"] != "completed":
            local.append("PRIMARY_ATTEMPT_DID_NOT_COMPLETE")
        case = next(c for c in suite["cases"] if c["id"] == slot["case_id"])
        try:
            output_digest = hashlib.sha256(output.encode("utf-8")).hexdigest() if isinstance(output, str) else None
        except UnicodeError:
            output_digest = None
        rows.append({"attempt_id": aid, "slot_id": slot_id, "case_id": slot["case_id"], "repetition": slot["repetition"],
                     "arm": slot["arm"], "primary": primary, "state": attempt["state"], "issues": local,
                     "raw_output_sha256": output_digest,
                     "score": _score(case, output, observed)})
        issues.extend(aid + ":" + item for item in local)
    missing = [s for s in known if s not in seen_slots]
    issues.extend("SCHEDULE_SLOT_MISSING:" + slot for slot in missing)
    expected_files = {a["attempt_id"] + ".json" for a in attempts}
    for path in _captures(root).iterdir():
        if path.name not in expected_files or path.is_symlink():
            issues.append("UNREGISTERED_OR_LINKED_CAPTURE:" + path.name)
    pairs = []
    primary_rows = [r for r in rows if r["primary"]]
    for case in suite["cases"]:
        for rep in range(1, suite["runs_per_case"] + 1):
            pair = {r["arm"]: r for r in primary_rows if r["case_id"] == case["id"] and r["repetition"] == rep}
            good = len(pair) == 2 and all(not r["issues"] and r["score"]["quality"] is not None for r in pair.values())
            pairs.append({"case_id": case["id"], "repetition": rep,
                          "delta": pair["with"]["score"]["quality"] - pair["without"]["score"]["quality"] if good else None})
    review = {"format": "pvl-codex-study-review-1", "plan_sha256": plan["plan_sha256"],
            "status": "SIMULATION_ONLY" if synthetic else "LIVE_HOST_ACCEPTANCE_BLOCKED",
            "local_contract_complete": not issues, "issues": issues, "planned_slots": len(known),
            "attempts_retained": len(attempts), "primary_attempts": len(primary_rows), "attempts": rows, "pairs": pairs,
            "retained_submissions": retained_submissions,
            "host_transport_qualified": False, "live_host_accepted": False, "benefit_claim_supported": False,
            "confirmed_decision": "NOT_EVALUATED", "third_person_recomputed": False, "model_calls": 0,
            "cost": {"actual_settled_usd": None, "unsettled_upper_usd": None, "status": "UNKNOWN"},
            "remaining_requirements": ["Qualified Codex transport and version evidence",
                                       "Complete host-effective inventory and context isolation evidence",
                                       "All-attempt cost reconciliation", "Independent human replay receipt"],
            "scope": "Offline scoring of retained normalized captures; integrity is not host authenticity, independence or benefit."}
    if suite["policy"].get("power_plan", {}).get("version") == 3:
        review["evaluation"] = _evaluate_confirmation(root, suite, plan, snapshot, review, settlement)
        decision = review["evaluation"]["report"]["confirmatory_analysis"]
        review["confirmed_decision"] = decision["status"]
        review["cost"] = review["evaluation"]["cost_reconciliation"]
    return review


def _settlement_rows(settlement, plan, snapshot, packets):
    """Bind late cost evidence to all attempts; never infer zero or authenticate bills."""
    issues, rows, ledger, sources = [], {}, None, {}
    if settlement is None:
        return rows, ledger, ["SETTLEMENT_MISSING"], None
    if (not isinstance(settlement, dict) or set(settlement) !=
            {"format", "plan_sha256", "journal_sha256", "attempts", "cost_ledger", "sources"}
            or settlement.get("format") != "pvl-codex-settlement-1"
            or not isinstance(settlement.get("attempts"), list)
            or not isinstance(settlement.get("sources"), dict)):
        raise ValidationError("Explicit Codex settlement envelope, all attempts, ledger and raw sources required")
    if (settlement["plan_sha256"] != plan["plan_sha256"]
            or settlement["journal_sha256"] != suite_digest(snapshot)):
        raise ValidationError("Settlement does not match frozen plan and exact attempt journal snapshot")
    sources = settlement["sources"]
    if any(not _text(k) or not _text(v) for k, v in sources.items()):
        raise ValidationError("Settlement source references must resolve to retained nonempty text")
    ledger = deepcopy(settlement["cost_ledger"])
    if not isinstance(ledger, dict) or not isinstance(ledger.get("entries"), list):
        raise ValidationError("Settlement requires the existing explicit cost ledger contract")
    known = {a["attempt_id"]: a for a in snapshot["attempts"]}
    refs, cash, timers = set(), 0., []
    for entry in settlement["attempts"]:
        if (not isinstance(entry, dict) or set(entry) != {"attempt_id", "request_id", "cost", "human_intervals"}
                or not _text(entry.get("attempt_id")) or entry["attempt_id"] not in known
                or entry["attempt_id"] in rows):
            raise ValidationError("Settlement contains unknown, duplicate or malformed attempt identity")
        aid = entry["attempt_id"]
        rows[aid] = deepcopy(entry)
        packet = packets.get(aid)
        expected_request = packet.get("request_id") if packet else None
        if (entry["request_id"] != expected_request or
                (expected_request is None and known[aid]["state"] != "not_dispatched")):
            issues.append("SETTLEMENT_REQUEST_MISMATCH:" + aid)
        if known[aid]["state"] not in {"completed", "failed", "cancelled", "not_dispatched"}:
            issues.append("SETTLEMENT_ATTEMPT_UNRESOLVED:" + aid)
        cost, intervals = entry["cost"], entry["human_intervals"]
        if not isinstance(cost, dict) or set(cost) != {"model_usd", "tool_usd", "human_minutes", "basis", "evidence_ref"}:
            raise ValidationError("Attempt cost needs amounts, basis and settlement line reference")
        try:
            values = [_number(cost[k], k) for k in ("model_usd", "tool_usd", "human_minutes")]
            if not math.isfinite(sum(values)):
                raise ValidationError("Attempt cost sum is not finite")
            cash += values[0] + values[1]
        except ValidationError:
            issues.append("SETTLEMENT_AMOUNT_UNKNOWN:" + aid)
        ref = cost["evidence_ref"]
        if cost["basis"] != "settled" or not _text(ref) or ref not in sources:
            issues.append("SETTLEMENT_REFERENCE_MISSING_OR_ESTIMATED:" + aid)
        elif ref in refs:
            issues.append("SETTLEMENT_REFERENCE_REUSED:" + aid)
        else:
            refs.add(ref)
        if not isinstance(intervals, list):
            issues.append("HUMAN_TIMERS_MISSING:" + aid)
            continue
        try:
            minutes = 0.
            for timer in intervals:
                if not isinstance(timer, dict) or not _text(timer.get("actor")):
                    raise ValueError("Timer actor missing")
                start, end = _stamp(timer.get("start")), _stamp(timer.get("end"))
                if end < start:
                    raise ValueError("Timer reversed")
                minutes += (end-start).total_seconds()/60
                timers.append((timer["actor"], start, end))
            if not math.isclose(minutes, _number(cost["human_minutes"], "human_minutes"), abs_tol=1e-6):
                raise ValueError("Timer total mismatch")
        except (ValueError, TypeError, KeyError):
            issues.append("HUMAN_TIMERS_INVALID:" + aid)
    for aid in known.keys()-rows.keys():
        issues.append("SETTLEMENT_ATTEMPT_MISSING:" + aid)
    last = {}
    for actor, start, end in sorted(timers):
        if actor in last and start < last[actor]:
            issues.append("HUMAN_TIMERS_OVERLAP:" + actor)
        last[actor] = max(end, last.get(actor, end))
    for item in ledger["entries"]:
        if not isinstance(item, dict) or not _text(item.get("evidence_ref")) or item["evidence_ref"] not in sources:
            issues.append("SUPPLEMENTAL_SOURCE_MISSING")
        elif item["evidence_ref"] in refs:
            issues.append("SUPPLEMENTAL_REUSES_ATTEMPT_REFERENCE")
        if isinstance(item, dict) and item.get("category") == "retry":
            raise ValidationError("Retry costs come from attempt rows; do not also enter them in cost_ledger")
        if isinstance(item, dict) and item.get("category") != "human" and item.get("treatment") == "additional":
            try:
                cash += _number(item.get("amount_usd"), "amount_usd")
            except ValidationError:
                issues.append("SUPPLEMENTAL_AMOUNT_UNKNOWN")
    if not math.isfinite(cash):
        issues.append("SETTLEMENT_TOTAL_NOT_FINITE")
    return rows, ledger, sorted(set(issues)), cash if not issues else None


def _evaluate_confirmation(root, suite, plan, snapshot, review, settlement):
    """Translate retained bytes into core.evaluate inputs, retaining every gate."""
    packets = {row["attempt_id"]: _read(_captures(root)/(row["attempt_id"]+".json"))
               for row in review["attempts"] if (_captures(root)/(row["attempt_id"]+".json")).exists()}
    costs, ledger, cost_gaps, cash = _settlement_rows(settlement, plan, snapshot, packets)
    gaps = list(review["issues"]) + cost_gaps
    records, execution_ids = [], []
    for row in review["attempts"]:
        aid = row["attempt_id"]
        packet, paid = packets.get(aid, {}), costs.get(aid, {})
        execution_ids.append({"run_id": packet.get("request_id"), "session_id": packet.get("session_id")})
        if not row["primary"]:
            if ledger is not None:
                cost = paid.get("cost", {})
                try:
                    amount = _number(cost.get("model_usd"), "model_usd") + _number(cost.get("tool_usd"), "tool_usd")
                except ValidationError:
                    amount = None
                ledger["entries"].append({"id": "attempt-"+aid, "category": "retry", "arm": row["arm"],
                    "case_id": row["case_id"], "repetition": row["repetition"], "amount_usd": amount,
                    "basis": cost.get("basis", "declared"), "evidence_ref": cost.get("evidence_ref") or "missing-"+aid,
                    "treatment": "additional"})
                intervals = paid.get("human_intervals")
                if isinstance(intervals, list) and intervals:
                    ledger["entries"].append({"id": "human-"+aid, "category": "human", "arm": row["arm"],
                        "case_id": row["case_id"], "repetition": row["repetition"], "amount_usd": None,
                        "basis": "declared", "evidence_ref": "timer-"+aid, "treatment": "additional", "human_intervals": intervals})
                    # Existing ledger validation recomputes the valuation from these exact timers.
                    try:
                        minutes = sum((_stamp(t["end"])-_stamp(t["start"])).total_seconds()/60 for t in intervals)
                        ledger["entries"][-1]["amount_usd"] = minutes*suite["policy"]["human_hourly_usd"]/60
                    except (ValueError, TypeError, KeyError):
                        pass
            continue
        imported = list(row["issues"])
        if packet.get("origin") != "synthetic":
            imported.append("HOST_TRANSPORT_NOT_QUALIFIED: operator capture is not native authentication")
        record = {"case_id": row["case_id"], "repetition": row["repetition"], "arm": row["arm"],
            "source": "synthetic" if packet.get("origin") == "synthetic" else "manual",
            "suite_sha256": plan["suite_sha256"], "conditions": deepcopy(suite["conditions"]),
            "plugin_loaded": (row["arm"] == "with") if packet and not row["issues"] else None,
            "session_id": packet.get("session_id"), "run_id": packet.get("request_id"), "attempt_id": aid,
            "input_sha256": packet.get("input_sha256"), "started_at": packet.get("started_at"),
            "status": {"completed": "completed", "failed": "error", "cancelled": "aborted", "not_dispatched": "skipped"}.get(row["state"], "skipped"),
            "output": packet.get("raw_output"), "cost": deepcopy(paid.get("cost", {})),
            "human_intervals": deepcopy(paid.get("human_intervals")), "import_issues": imported}
        records.append(record)
    if ledger is not None:
        retries = any(not row["primary"] for row in review["attempts"])
        declared = ledger.get("coverage", {}).get("retry")
        if retries and declared != "itemized":
            gaps.append("RETRY_COVERAGE_MUST_BE_ITEMIZED")
            cost_gaps.append("RETRY_COVERAGE_MUST_BE_ITEMIZED")
            ledger.setdefault("coverage", {})["retry"] = "itemized"
    from .pilot import validate_disjoint
    gaps.extend(validate_disjoint(suite["policy"]["power_plan"]["pilot"], suite, execution_ids))
    gaps = sorted(set(gaps))
    if records:
        records[0]["import_issues"].extend(gaps)
    report = evaluate(suite, records, _read(root/"protocol.lock.json"), ledger)
    cost_analysis = report["cost_analysis"]
    reconciled = (not cost_gaps and cash is not None and cost_analysis["complete_category_coverage"]
                  and cost_analysis["cash_evidence"]["settlement_references_complete"])
    return {"route": "core.evaluate -> confirmatory.assess", "records": records, "cost_ledger": ledger,
            "report": report, "bridge_issues": gaps,
            "journal_sha256": suite_digest(snapshot), "settlement_sha256": suite_digest(settlement) if settlement is not None else None,
            "cost_reconciliation": {"status": "SETTLEMENT_REFERENCES_PRESENT" if reconciled else "UNKNOWN",
                "actual_settled_usd": cash if reconciled else None, "unsettled_upper_usd": None,
                "scope": "Submitted cash settlement references, not invoice authentication; labor valued separately."},
            "scope": "Original first-attempt outputs only; retries remain diagnostic and are charged. Conditions are normalized from the frozen contract, not independently authenticated."}


@_exclusive
def review(directory, pin, *, settlement_path=None):
    root, suite, plan = _load(directory, pin)
    snapshot = _journal(root, pin).snapshot()
    return _assess(root, suite, plan, snapshot, _read(settlement_path) if settlement_path is not None else None)


@_exclusive
def export_review(directory, pin, output, *, settlement_path=None):
    """Seal a portable directory, with an externally retained manifest pin."""
    root, suite, plan = _load(directory, pin)
    snapshot = _journal(root, pin).snapshot()
    settlement = _read(settlement_path) if settlement_path is not None else None
    result = _assess(root, suite, plan, snapshot, settlement)
    out = Path(output).resolve()
    if out == root or out.is_relative_to(root):
        raise ValidationError("Export must be outside the mutable study directory")
    out.mkdir(parents=True, exist_ok=False)
    (out / "captures").mkdir()
    (out / "submissions").mkdir()
    for name in ("suite.json", "contract.json", "protocol.lock.json", "plan.json"):
        shutil.copyfile(root / name, out / name)
    for path in _captures(root).iterdir():
        if path.is_symlink() or not path.is_file():
            raise ValidationError("Only regular evidence files can be exported")
        shutil.copyfile(path, out / "captures" / path.name)
    for path in _submissions(root).iterdir():
        if path.is_symlink() or not path.is_file():
            raise ValidationError("Only regular submission files can be exported")
        shutil.copyfile(path, out / "submissions" / path.name)
    _save(out / "journal.json", snapshot)
    if settlement_path is not None:
        raw = Path(settlement_path).read_bytes()
        if json.loads(raw) != settlement:
            raise ValidationError("Settlement changed during export")
        (out / "settlement.json").write_bytes(raw)
    _save(out / "review.json", result)
    files = {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob("*")) if p.is_file()}
    scorer_files = sorted(p.name for p in Path(__file__).parent.glob("*.py"))
    _save(out / "manifest.json", {"format": "pvl-codex-study-review-bundle-1", "plan_sha256": pin,
                                 "files": files, "scorer_sources": {n: sha(Path(__file__).parent / n) for n in scorer_files},
                                 "scope": "Local byte commitment; keep this manifest digest outside the bundle"})
    return {"plan_sha256": pin, "manifest_sha256": sha(out / "manifest.json"), "model_calls": 0}


def verify_review(directory, manifest_sha256):
    """Recompute from retained raw output; never execute bundled code or tools."""
    root = Path(directory).resolve()
    if not _hex(manifest_sha256) or sha(root / "manifest.json") != manifest_sha256:
        raise ValidationError("External review manifest pin missing or changed")
    manifest = _read(root / "manifest.json")
    if manifest.get("format") != "pvl-codex-study-review-bundle-1":
        raise ValidationError("Unsupported review bundle")
    if any(p.is_symlink() for p in root.rglob("*")):
        raise ValidationError("Linked files or directories are not portable review evidence")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(manifest["files"]) | {"manifest.json"}:
        raise ValidationError("Review bundle has missing or extra files")
    for name, digest in manifest["files"].items():
        path = confined(root, name)
        if path.is_symlink() or sha(path) != digest:
            raise ValidationError("Review evidence changed: " + name)
    for name, digest in manifest["scorer_sources"].items():
        if sha(confined(Path(__file__).parent, name)) != digest:
            raise ValidationError("Scoring implementation differs; use the recorded source revision")
    _, suite, plan = _load(root, manifest["plan_sha256"])
    snapshot = _read(root / "journal.json")
    result = _assess(root, suite, plan, snapshot, _read(root/"settlement.json") if (root/"settlement.json").exists() else None)
    if result != _read(root / "review.json"):
        raise ValidationError("Recomputed review differs from bundled review")
    return {"format": "pvl-codex-study-recompute-1", "status": "RECOMPUTED_LOCALLY",
            "manifest_sha256": manifest_sha256, "review_sha256": suite_digest(result),
            "live_host_accepted": False, "third_person_identity_verified": False, "model_calls": 0,
            "scope": "Recalculation succeeded with local source; no human independence or live host acceptance is inferred."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("suite"); p.add_argument("contract"); p.add_argument("output")
    for name in ("reserve", "state", "capture", "review", "export"):
        p = commands.add_parser(name)
        p.add_argument("study"); p.add_argument("--plan-sha256", required=True)
        if name == "reserve":
            p.add_argument("slot"); p.add_argument("key"); p.add_argument("--retry-of")
        elif name == "state":
            p.add_argument("attempt"); p.add_argument("state"); p.add_argument("evidence")
        elif name == "capture":
            p.add_argument("packet")
        elif name == "export":
            p.add_argument("output")
        if name in {"review", "export"}:
            p.add_argument("--settlement", help="All-attempt costs bound to the frozen plan and exact journal snapshot")
    p = commands.add_parser("verify")
    p.add_argument("bundle"); p.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(_read(args.suite), _read(args.contract), args.output)
        elif args.command == "verify":
            result = verify_review(args.bundle, args.manifest_sha256)
        elif args.command == "reserve":
            result = reserve(args.study, args.plan_sha256, args.slot, args.key, retry_of=args.retry_of)
        elif args.command == "state":
            result = record_state(args.study, args.plan_sha256, args.attempt, args.state, _read(args.evidence))
        elif args.command == "capture":
            result = capture(args.study, args.plan_sha256, args.packet)
        elif args.command == "export":
            result = export_review(args.study, args.plan_sha256, args.output, settlement_path=args.settlement)
        else:
            result = review(args.study, args.plan_sha256, settlement_path=args.settlement)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    except (ValidationError, OSError, KeyError, TypeError, ValueError) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
