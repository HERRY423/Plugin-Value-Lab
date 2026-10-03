"""Immutable judgment and policy revisions, separate from observations and views.

This module validates submitted records. It does not run a grader, authenticate
an author, approve science, or choose a plugin. Lifecycle is a replayed projection
of append-only events; original judgments and decisions are never rewritten.
"""
from copy import deepcopy
import re

from .core import ValidationError, suite_digest

FORMAT = "pvl-decision-store-3"
FIELDS = {
    "judge": {"judgment_id", "mode", "parent", "attempt_ids", "contract", "implementation", "result", "reason", "artifacts"},
    "decide": {"decision_id", "judgment_id", "policy", "scope", "recommendation", "reason", "replaces", "status"},
    "review": {"decision_id", "status", "reason"},
    "present": {"presentation_id", "target_kind", "target_id", "renderer", "artifacts"},
}


def require(ok, message):
    if not ok:
        raise ValidationError(message)


def ident(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value) is not None


def text(value):
    return isinstance(value, str) and bool(value.strip())


def observation_identity(state, ids):
    return suite_digest({i: {k: state["attempts"][i][k] for k in
        ("requirement", "mode", "operation", "external_key", "status", "receipt", "artifacts")}
        for i in sorted(ids)})


def _transition(layer, decision_id, status, reason, sequence, *, successor=None):
    entry = {"decision_id": decision_id, "status": status, "reason": reason, "sequence": sequence,
             "superseded_by": successor}
    layer["lifecycle"].append(entry)
    layer["decision_states"][decision_id] = entry


def invalidate(state, reason, *, judgment_id=None, requirement=None):
    """Conservatively mark applicable active guidance; never alter its source."""
    layer = state.get("explanations")
    if layer is None:
        return
    for decision_id, decision in layer["decisions"].items():
        judgment = layer["judgments"][decision["judgment_id"]]
        if judgment_id is not None and judgment["judgment_id"] != judgment_id:
            continue
        if requirement is not None and requirement not in {
                state["attempts"][i]["requirement"] for i in judgment["attempt_ids"]}:
            continue
        if layer["decision_states"][decision_id]["status"] == "current":
            _transition(layer, decision_id, "review_required", reason, state["sequence"] + 1)


def apply_revision(state, kind, p):
    require(isinstance(p, dict) and set(p) == FIELDS[kind], "Invalid explanation event fields")
    if "artifacts" in p:
        require(isinstance(p["artifacts"], dict) and all(ident(k) and isinstance(v, str)
                and re.fullmatch(r"[a-f0-9]{64}", v) for k, v in p["artifacts"].items()), "Invalid explanation artifact bindings")
    layer = state.setdefault("explanations", {"judgments": {}, "decisions": {}, "presentations": {},
                                               "decision_states": {}, "lifecycle": []})
    sequence = state["sequence"] + 1
    if kind == "judge":
        jid, parent, ids = p["judgment_id"], p["parent"], p["attempt_ids"]
        require(ident(jid) and jid not in layer["judgments"], "Invalid or duplicate judgment ID")
        require(p["mode"] in ("evaluation", "rescore") and text(p["reason"]), "Declare judgment mode and reason")
        require(isinstance(ids, list) and ids and all(ident(i) for i in ids) and len(ids) == len(set(ids))
                and all(i in state["attempts"] and state["attempts"][i]["status"] not in
                        ("PENDING", "OUTCOME_UNKNOWN", "RESULT_AVAILABLE") for i in ids), "Judgment requires terminal observations")
        contract = p["contract"]
        require(isinstance(contract, dict) and set(contract) == {"grader", "reference", "domain"}
                and all(isinstance(v, dict) and v for v in contract.values()),
                "Bind grader, reference and domain contracts; explicitly describe absent references")
        require(p["implementation"] is None or text(p["implementation"]), "Implementation identity must be text or unknown")
        result = p["result"]
        require(isinstance(result, dict) and set(result) == {"checks", "pending_checks"}
                and isinstance(result["checks"], dict) and result["checks"]
                and all(ident(k) and isinstance(v, dict) and set(v) == {"status", "reason"}
                        and v["status"] in ("PASSED", "FAILED", "UNKNOWN") and text(v["reason"])
                        for k, v in result["checks"].items())
                and isinstance(result["pending_checks"], list) and all(text(x) for x in result["pending_checks"]),
                "Bind structured checks and unresolved work")
        observations = observation_identity(state, ids)
        identity = suite_digest({"contract": contract, "implementation": p["implementation"]})
        require(parent is None or (ident(parent) and parent in layer["judgments"]), "Unknown judgment parent")
        if parent is not None:
            prior = layer["judgments"][parent]
            require(not any(j["parent"] == parent for j in layer["judgments"].values()), "Use the latest judgment in this lineage")
            if p["mode"] == "rescore":
                require(observations == prior["observation_sha256"], "Rescore must retain exactly the same observations")
                require(identity != prior["judgment_sha256"], "Unchanged judgment contract is replay; explain a changed rule or implementation")
            else:
                require(set(prior["attempt_ids"]) <= set(ids), "Evaluation revision cannot discard earlier failures or observations")
            invalidate(state, "Judgment revised: " + jid + "; " + p["reason"], judgment_id=parent)
        else:
            require(p["mode"] == "evaluation", "Rescore needs a parent judgment")
        layer["judgments"][jid] = {**deepcopy(p), "observation_sha256": observations,
            "judgment_sha256": identity, "result_sha256": suite_digest(result),
            "validation_basis": "SUBMITTED_STRUCTURED_CHECKS_NOT_INDEPENDENTLY_VERIFIED"}
    elif kind == "decide":
        did, jid, previous = p["decision_id"], p["judgment_id"], p["replaces"]
        require(ident(did) and did not in layer["decisions"], "Invalid or duplicate decision ID")
        require(ident(jid) and jid in layer["judgments"], "Decision must bind an existing judgment")
        require(isinstance(p["scope"], dict) and p["scope"] and text(p["recommendation"]) and text(p["reason"]),
                "Declare bounded scope, recommendation and revision reason")
        policy = p["policy"]
        require(isinstance(policy, dict) and set(policy) == {"purpose", "quality_thresholds", "budget_micros"}
                and text(policy["purpose"]) and isinstance(policy["quality_thresholds"], dict) and policy["quality_thresholds"]
                and (policy["budget_micros"] is None or type(policy["budget_micros"]) is int and policy["budget_micros"] >= 0),
                "Bind purpose, quality thresholds and budget policy separately from grading")
        require(p["status"] in ("current", "review_required", "not_applicable"), "Invalid initial guidance status")
        scope = suite_digest(p["scope"])
        matches = [i for i, d in layer["decisions"].items() if d["scope_sha256"] == scope
                   and layer["decision_states"][i]["status"] != "superseded"]
        require(previous is None and not matches or ident(previous) and matches == [previous],
                "Replace the latest decision for this exact scope explicitly")
        judgment = layer["judgments"][jid]
        status = p["status"]
        causes = []
        if judgment["implementation"] is None:
            causes.append("JUDGMENT_IMPLEMENTATION_UNKNOWN")
        causes.extend("PENDING_CHECK:" + c for c in judgment["result"]["pending_checks"])
        causes.extend("UNKNOWN_CHECK:" + k for k, c in judgment["result"]["checks"].items() if c["status"] == "UNKNOWN")
        if policy["budget_micros"] is None:
            causes.append("BUDGET_POLICY_UNKNOWN")
        if any(j["parent"] == jid for j in layer["judgments"].values()):
            causes.append("SUPERSEDED_JUDGMENT:" + jid)
        causes.extend("UNSETTLED_COST:" + i for i, a in state["attempts"].items() if not a["settled"])
        dependencies = dict(state["dependencies"])
        for legacy in state["interpretations"]:
            dependencies.update(legacy["dependencies"])
        causes.extend("UNKNOWN_DEPENDENCY:" + k for k, v in dependencies.items() if v is None)
        if (policy["budget_micros"] is not None and
                sum(a["cost_micros"] for a in state["attempts"].values() if a["settled"]) > policy["budget_micros"]):
            causes.append("DECISION_BUDGET_EXCEEDED")
        # A later attempt in the same evidence group cannot be omitted to revive
        # an earlier decision. It must first be reconciled and evaluated.
        requirements = {state["attempts"][i]["requirement"] for i in judgment["attempt_ids"]}
        causes.extend("UNREVIEWED_ATTEMPT:" + i for i, a in state["attempts"].items()
                      if i not in judgment["attempt_ids"] and a["requirement"] in requirements)
        if status == "current" and causes:
            status = "review_required"
        layer["decisions"][did] = {**deepcopy(p), "scope_sha256": scope,
            "decision_sha256": suite_digest({"judgment_id": jid, "result_sha256": judgment["result_sha256"],
                                             "policy": policy, "scope": p["scope"], "recommendation": p["recommendation"]}),
            "policy_sha256": suite_digest(policy), "review_causes_at_creation": causes,
            "validation_basis": "RECORDED_GUIDANCE_NOT_SCIENTIFIC_AUTHORIZATION"}
        if previous is not None:
            _transition(layer, previous, "superseded", p["reason"], sequence, successor=did)
        _transition(layer, did, status, ("; ".join(causes) + "; " if causes else "") + p["reason"], sequence)
    elif kind == "review":
        did = p["decision_id"]
        require(ident(did) and did in layer["decisions"] and text(p["reason"]), "Review needs an existing decision and reason")
        require(p["status"] in ("review_required", "not_applicable")
                and layer["decision_states"][did]["status"] in ("current", "review_required"),
                "Cannot reactivate or overwrite terminal guidance; create an explicit replacement")
        _transition(layer, did, p["status"], p["reason"], sequence)
    else:
        pid, target = p["presentation_id"], p["target_kind"]
        require(ident(pid) and pid not in layer["presentations"], "Invalid or duplicate presentation ID")
        require(target in ("judgment", "decision") and ident(p["target_id"])
                and p["target_id"] in layer[target + "s"], "Presentation must bind retained source material")
        require(isinstance(p["renderer"], dict) and p["renderer"] and p["artifacts"], "Retain renderer identity and actual report bytes")
        source = layer[target + "s"][p["target_id"]]
        layer["presentations"][pid] = {**deepcopy(p), "source_sha256": suite_digest(source),
            "presentation_sha256": suite_digest({"renderer": p["renderer"], "artifacts": p["artifacts"]}),
            "lifecycle_at_render": deepcopy(layer["decision_states"].get(p["target_id"])) if target == "decision" else None,
            "rendered_at_sequence": sequence}
    return state


def revision_view(state):
    layer = state.get("explanations", {})
    states = layer.get("decision_states", {})
    return {"current_decisions": [i for i, s in states.items() if s["status"] == "current"],
            "guidance_review_required": [i for i, s in states.items() if s["status"] == "review_required"],
            "stale_presentations": [i for i, p in layer.get("presentations", {}).items()
                if p["target_kind"] == "decision" and p["lifecycle_at_render"] != states[p["target_id"]]],
            "legacy_interpretations_without_lifecycle": [i["interpretation_id"] for i in state["interpretations"]],
            "legacy_interpretations_promoted": False,
            "presentation_is_current_guidance": False}
