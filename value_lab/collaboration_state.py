"""Replayable local collaboration transitions; actor names are declarations."""
from copy import deepcopy
import base64
import json
from pathlib import PurePosixPath

from .core import ValidationError, suite_digest, validate_suite

FORMAT = "pvl-decision-store-4"
FIELDS = {
    "collab_open": {"actor", "inputs", "require_human_review"},
    "collab_start": {"actor", "attempt_id", "reason", "implementation"},
    "collab_finish": {"actor", "attempt_id", "status", "receipt", "artifacts"},
    "collab_resolve": {"actor", "attempt_id", "reason"},
    "collab_review": {"actor", "review_id", "attempt_id", "result_sha256", "verdict", "notes"},
    "collab_correct": {"actor", "review_id", "inputs", "reason"},
    "collab_handoff": {"actor", "handoff_id", "recipient", "note"},
    "collab_receive": {"actor", "handoff_id"},
    "collab_cancel_handoff": {"actor", "handoff_id", "reason"},
}


def require(ok, message):
    if not ok:
        raise ValidationError(message)


def actor(value):
    require(isinstance(value, dict) and set(value) == {"id", "kind"}
            and isinstance(value["id"], str) and 0 < len(value["id"].strip()) <= 200
            and value["kind"] in ("agent", "human"), "Declare an actor id and kind")
    return deepcopy(value)


def inputs(value):
    required = {"suite", "records", "lock", "cost_ledger"}
    require(isinstance(value, dict) and required <= set(value) <= required | {"artifact_files"},
            "Inputs require suite, records, lock and cost_ledger (null if unknown)")
    validate_suite(value["suite"])
    require(isinstance(value["records"], list) and all(isinstance(r, dict) for r in value["records"])
            and (value["lock"] is None or isinstance(value["lock"], dict))
            and (value["cost_ledger"] is None or isinstance(value["cost_ledger"], dict)), "Invalid evaluation inputs")
    # Evidence is submitted in-band. No implicit file roots or executable graders.
    require(len(json.dumps(value, allow_nan=False).encode()) <= 8 * 1024**2,
            "Collaboration inputs exceed 8 MiB")
    files = value.get("artifact_files", {})
    require(isinstance(files, dict) and len(files) <= 256, "At most 256 small retained artifact files")
    for name, encoded in files.items():
        require(isinstance(name, str) and name and "\\" not in name and ":" not in name
                and not PurePosixPath(name).is_absolute()
                and all(p not in ("", ".", "..") for p in name.split("/"))
                and isinstance(encoded, str), "Retained artifact paths must be safe relative POSIX paths")
        try:
            base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValidationError("Retained artifacts require valid base64 bytes") from exc
    return deepcopy(value)


def apply_revision(state, kind, p, base):
    require(kind in FIELDS and isinstance(p, dict) and set(p) == FIELDS[kind],
            "Invalid collaboration event fields")
    who = actor(p["actor"])
    if kind == "collab_open":
        require(state is None and type(p["require_human_review"]) is bool, "Task already exists or invalid review policy")
        material = inputs(p["inputs"])
        state = base(None, "initialize", {"plan": material, "plan_sha256": suite_digest(material),
            "required_evidence": ["evaluation"], "dependencies": {}, "budget_micros": 0})
        state["sequence"] = 0  # The outer collaboration event is one atomic commit.
        state["collaboration"] = {
            "owner": who, "require_human_review": p["require_human_review"],
            "revisions": [{"id": "r1", "inputs": material, "inputs_sha256": suite_digest(material),
                           "reason": "Initial submitted inputs", "review_id": None}],
            "runs": {}, "reviews": [], "handoffs": [], "pending_handoff": None,
        }
        return state
    require(state is not None and "collaboration" in state, "Open a collaboration task first")
    c = state["collaboration"]
    pending = c["pending_handoff"]
    if kind == "collab_receive":
        require(pending is not None and p["handoff_id"] == pending["id"] and who == pending["recipient"],
                "Receive the exact pending handoff as its declared recipient")
        c["owner"] = who
        c["handoffs"].append({**deepcopy(pending), "state": "RECEIVED",
                               "received_sequence": state["sequence"] + 1})
        c["pending_handoff"] = None
        return state
    require(who == c["owner"], "Only the declared current owner may change this local task")
    if kind == "collab_cancel_handoff":
        require(pending is not None and p["handoff_id"] == pending["id"] and text(p["reason"]),
                "Cancel the exact pending handoff with a reason")
        c["handoffs"].append({**deepcopy(pending), "state": "CANCELLED", "reason": p["reason"]})
        c["pending_handoff"] = None
        return state
    require(pending is None, "Handoff pending: recipient must receive it or owner must cancel it")
    revision = c["revisions"][-1]
    active = [a for a, run in c["runs"].items() if run["revision"] == revision["id"]]
    unresolved = [a for a in c["runs"] if state["attempts"][a]["status"] in ("PENDING", "OUTCOME_UNKNOWN", "RESULT_AVAILABLE")]

    def transition(event, payload):
        sequence = state["sequence"]
        base(state, event, payload)
        state["sequence"] = sequence

    if kind == "collab_start":
        require(not unresolved and text(p["reason"]) and text(p["implementation"]), "Resolve pending execution first; retain reason and implementation")
        require(not active or state["attempts"][active[-1]]["status"] in ("FAILED", "CANCELLED"),
                "A completed revision cannot run again; review and create an explicit correction")
        previous = list(state["attempts"])
        payload = {"attempt_id": p["attempt_id"], "requirement": "evaluation", "mode": "local_execution",
                   "operation": "pvl-local-evaluate:" + revision["inputs_sha256"],
                   "external_key": p["attempt_id"], "max_cost_micros": 0}
        if previous:
            payload.update(retry_of=previous[-1], reason=p["reason"])
        transition("start", payload)
        c["runs"][p["attempt_id"]] = {"revision": revision["id"], "actor": who,
            "implementation": p["implementation"], "inputs_sha256": revision["inputs_sha256"],
            "reason": p["reason"], "review_required": True}
    elif kind == "collab_finish":
        require(p["attempt_id"] in c["runs"] and c["runs"][p["attempt_id"]]["actor"] == who,
                "Unknown execution or different submitting actor")
        transition("finish", {k: deepcopy(p[k]) for k in ("attempt_id", "status", "receipt", "artifacts")})
        transition("settle", {"attempt_id": p["attempt_id"], "cost_micros": 0,
                             "basis": "PVL local object-only evaluator; no model/tool dispatch"})
    elif kind == "collab_resolve":
        require(p["attempt_id"] in unresolved and text(p["reason"]), "Resolve an unfinished local attempt with an explicit reason")
        transition("finish", {"attempt_id": p["attempt_id"], "status": "FAILED", "artifacts": {},
            "receipt": {"basis": "OPERATOR_DECLARED_NO_RETAINED_RESULT", "reason": p["reason"],
                        "execution_outcome": "UNKNOWN", "actor": who}})
        transition("settle", {"attempt_id": p["attempt_id"], "cost_micros": 0,
                             "basis": "Local object-only operation; compute outcome remains unknown"})
    elif kind == "collab_review":
        require(not unresolved and active and p["attempt_id"] == active[-1], "Review the latest terminal execution of the current revision")
        attempt = state["attempts"][p["attempt_id"]]
        require(p["result_sha256"] == attempt["artifacts"].get("result") and p["result_sha256"] is not None,
                "Review must bind the retained result digest")
        require(text(p["review_id"]) and not any(r["id"] == p["review_id"] for r in c["reviews"])
                and p["verdict"] in ("accept", "request_changes", "reject") and text(p["notes"]),
                "Supply a unique review, explicit verdict and rationale")
        require(p["verdict"] != "accept" or attempt["status"] == "COLLECTED", "A failed execution cannot be accepted")
        c["reviews"].append({"id": p["review_id"], "revision": revision["id"], **deepcopy(p),
            "identity_assurance": "DECLARED_NOT_AUTHENTICATED", "sequence": state["sequence"] + 1})
    elif kind == "collab_correct":
        require(not unresolved and c["reviews"] and p["review_id"] == c["reviews"][-1]["id"]
                and c["reviews"][-1]["revision"] == revision["id"] and text(p["reason"]),
                "Correction requires the latest review and a reason")
        material = inputs(p["inputs"])
        require(suite_digest(material) != revision["inputs_sha256"], "Unchanged inputs are replay, not correction")
        c["revisions"].append({"id": "r" + str(len(c["revisions"]) + 1), "inputs": material,
            "inputs_sha256": suite_digest(material), "reason": p["reason"], "review_id": p["review_id"],
            "origin": "POST_REVIEW_REVISION_NOT_PREREGISTRATION"})
    elif kind == "collab_handoff":
        require(not unresolved, "Resolve the original execution before handing over ownership")
        recipient = actor(p["recipient"])
        require(recipient != who and text(p["handoff_id"]) and text(p["note"])
                and not any(h["id"] == p["handoff_id"] for h in c["handoffs"]), "Declare a new recipient, handoff id and note")
        c["pending_handoff"] = {"id": p["handoff_id"], "sender": who, "recipient": recipient,
            "note": p["note"], "revision": revision["id"], "sequence": state["sequence"] + 1}
    return state


def text(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 10000


def view(state):
    c = state.get("collaboration")
    if c is None:
        return None
    revision = c["revisions"][-1]
    runs = [a for a, r in c["runs"].items() if r["revision"] == revision["id"]]
    latest = runs[-1] if runs else None
    reviews = [r for r in c["reviews"] if r["revision"] == revision["id"] and r["attempt_id"] == latest]
    review = reviews[-1] if reviews else None
    unfinished = [a for a in c["runs"] if state["attempts"][a]["status"] in ("PENDING", "OUTCOME_UNKNOWN", "RESULT_AVAILABLE")]
    if c["pending_handoff"]:
        stage, action = "HANDOFF_PENDING", "receive"
    elif unfinished:
        stage, action = "EXECUTION_UNRESOLVED", "resolve"
    elif not latest:
        stage, action = "READY_TO_EXECUTE", "execute"
    elif state["attempts"][latest]["status"] != "COLLECTED":
        stage, action = "EXECUTION_FAILED", "execute"
    elif review is None:
        stage, action = "AWAITING_REVIEW", "review"
    elif review["verdict"] != "accept":
        stage, action = "CHANGES_REQUESTED" if review["verdict"] == "request_changes" else "REJECTED", "correct"
    elif c["require_human_review"] and review["actor"]["kind"] != "human":
        stage, action = "AWAITING_HUMAN_REVIEW", "handoff"
    else:
        stage, action = "ACCEPTED_AS_DECLARED", "handoff"
    return {"stage": stage, "next_action": action, "owner": c["owner"], "revision": revision["id"],
            "inputs_sha256": revision["inputs_sha256"], "latest_attempt": latest, "latest_review": review,
            "pending_handoff": c["pending_handoff"], "unresolved_attempts": unfinished,
            "post_review_revision": len(c["revisions"]) > 1,
            "human_identity_authenticated": False, "human_acceptance_verified": False,
            "live_host_accepted": False, "scientific_validity": "NOT_ESTABLISHED",
            "source_evidence_type": revision["inputs"]["suite"].get("evidence_type"),
            "review_is_execution_authority": False}
