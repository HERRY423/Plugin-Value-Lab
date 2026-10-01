"""Prospective decision-directed batches; screening never becomes confirmation.

This is a deterministic cost/relevance policy, not estimated information gain or
an anytime-valid statistical procedure. All observations remain host declarations.
"""
from copy import deepcopy
import math

from .artifacts import read_only_verification
from .core import ValidationError, evaluate, suite_digest, validate_suite
from .scoring import run_success
from .task_selection import _keys, _id, _sha, _strings, select_task_plan


FORMAT = "pvl-evidence-acquisition-1"
RULE = "frontier_gates_then_confirmation_v1"
STOP = "stable_choice_or_budget_or_no_relevant_check_v1"


def _money(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValidationError("Acquisition costs must be finite nonnegative USD amounts")


def _case_signature(case):
    return suite_digest({k: v for k, v in case.items() if k not in ("id", "cluster")})


def _validate(selection, request, base):
    _keys(request, ("protocol", "protocol_sha256", "batches"))
    protocol = request["protocol"]
    _keys(protocol, ("format", "catalog_sha256", "selection_rule", "stopping_rule", "budget", "checks"))
    if (protocol["format"] != FORMAT or protocol["selection_rule"] != RULE or protocol["stopping_rule"] != STOP
            or suite_digest(protocol) != request["protocol_sha256"] or protocol["catalog_sha256"] != base["catalog_sha256"]):
        raise ValidationError("Mother protocol, frozen rules or task catalog binding changed")
    if selection["studies"]:
        raise ValidationError("Start prospective acquisition with studies=[]; do not retrofit existing observations into a held-out protocol")
    budget = protocol["budget"]
    _keys(budget, ("max_usd", "max_batches"))
    _money(budget["max_usd"])
    if type(budget["max_batches"]) is not int or not 0 <= budget["max_batches"] <= 64:
        raise ValidationError("max_batches must be an integer in 0..64")
    if not isinstance(protocol["checks"], list) or not 1 <= len(protocol["checks"]) <= 64:
        raise ValidationError("Declare 1..64 prospective checks")
    if not isinstance(request["batches"], list) or len(request["batches"]) > 64:
        raise ValidationError("Supply a bounded append-only batch history")
    plans = {p["plan_sha256"]: p for p in base["plans"]}
    task = selection["task"]
    confirmation_ids = {c["id"] for c in task["cases"]}
    confirmation_signatures = {_case_signature(c) for c in task["cases"]}
    checks, screen_cases = {}, {}
    for check in protocol["checks"]:
        _keys(check, ("id", "phase", "suite", "inputs", "decision_case_ids", "cost_upper_bound_usd"))
        cid = _id(check["id"])
        if cid in checks or check["phase"] not in ("screening", "confirmation"):
            raise ValidationError("Check IDs must be unique and phases explicit")
        _money(check["cost_upper_bound_usd"])
        _strings(check["decision_case_ids"])
        suite = check["suite"]
        validate_suite(suite)
        if "acquisition_batch" in suite:
            raise ValidationError("Batch identity is generated only after the next experiment is selected")
        binding = suite.get("task_selection")
        if not isinstance(binding, dict):
            raise ValidationError("Every check must bind complete WITH/WITHOUT task plans")
        _keys(binding, ("catalog_sha256", "arms", "treatment_component"))
        _keys(binding["arms"], ("with", "without"))
        arms = binding["arms"]
        if any(not isinstance(p, str) or p not in plans for p in arms.values()):
            raise ValidationError("Unknown full-plan identity in acquisition check")
        if binding["catalog_sha256"] != base["catalog_sha256"] or suite_digest(suite["conditions"]) != suite_digest(task["conditions"]):
            raise ValidationError("Check conditions or catalog differ from the frozen task")
        if suite["policy"]["quality_floor"] != selection["policy"]["quality_floor"]:
            raise ValidationError("Check quality floor differs from selection")
        components = {arm: plans[p]["manifest"]["components"] for arm, p in arms.items()}
        treatment = next((c for c in components["with"] if c["id"] == binding["treatment_component"]), None)
        if (not treatment or treatment["kind"] != "plugin" or any(c["id"] == treatment["id"] for c in components["without"])
                or any(suite["plugin"].get(k) != treatment[k] for k in ("name", "version", "sha256"))):
            raise ValidationError("Check must preserve actual paired plugin load semantics")
        if not isinstance(check["inputs"], dict) or not check["inputs"]:
            raise ValidationError("Check input snapshots are required")
        for key, value in check["inputs"].items():
            _id(key)
            _sha(value)
        ids = {c["id"] for c in suite["cases"]}
        if not check["decision_case_ids"] or set(check["decision_case_ids"]) != ids:
            raise ValidationError("Every frozen batch case, including negative controls, must remain a decision gate")
        if check["phase"] == "confirmation":
            if (suite_digest(suite["cases"]) != suite_digest(task["cases"]) or check["inputs"] != task["inputs"]
                    or set(check["decision_case_ids"]) != ids):
                raise ValidationError("Confirmation must retain every task stage and integration case on reserved task inputs")
        else:
            if set(check["inputs"].values()) & set(task["inputs"].values()):
                raise ValidationError("Screening and held-out confirmation input snapshots must be disjoint")
            for case in suite["cases"]:
                signature = _case_signature(case)
                if case["id"] in confirmation_ids or signature in confirmation_signatures:
                    raise ValidationError("Confirmation cases cannot be used for screening, including renamed copies")
                if case["id"] in screen_cases and screen_cases[case["id"]] != signature:
                    raise ValidationError("Screening case identity changed across checks")
                screen_cases[case["id"]] = signature
        checks[cid] = check
    return protocol, checks, plans


def _frontier(plans, excluded, confirmed):
    survivors = [p for p in plans.values() if p["status"] != "INAPPLICABLE" and p["plan_sha256"] not in excluded]
    supported = [p for p in survivors if p["plan_sha256"] in confirmed]
    best = [p for p in supported if p["size"] == min(q["size"] for q in supported)] if supported else []
    unresolved = [p for p in survivors if p["plan_sha256"] not in confirmed and (not best or p["size"] <= best[0]["size"])]
    frontier = [p for p in unresolved if p["size"] == min(q["size"] for q in unresolved)] if unresolved else []
    return best, unresolved, {p["plan_sha256"] for p in frontier}


def _cell(check, plan, case):
    return (plan, _case_signature(case), suite_digest(check["inputs"]))


def _agenda(protocol, checks, plans, used, excluded, confirmed, cells, confirmation_started, spent):
    best, unresolved, frontier = _frontier(plans, excluded, confirmed)
    rows = []
    for check in checks.values():
        targets = set(check["suite"]["task_selection"]["arms"].values()) & frontier
        gates = [c for c in check["suite"]["cases"] if c["id"] in check["decision_case_ids"]]
        targets = {p for p in targets if check["phase"] == "confirmation" or any(_cell(check, p, c) not in cells for c in gates)}
        reason = ("already_observed" if check["id"] in used else "screening_closed" if confirmation_started and check["phase"] == "screening"
                  else "cannot_change_current_frontier" if not targets else None)
        rows.append({"check_id": check["id"], "phase": check["phase"], "affected_plans": sorted(targets),
                     "pivotal_case_ids": [c["id"] for c in gates if any(_cell(check, p, c) not in cells for p in targets)],
                     "observed_gate_outcomes": [{"plan_sha256": p, "case_id": c["id"], "status": cells[_cell(check, p, c)]}
                                                 for p in check["suite"]["task_selection"]["arms"].values() for c in gates
                                                 if _cell(check, p, c) in cells],
                     "cost_upper_bound_usd": check["cost_upper_bound_usd"],
                     "cost_per_affected_plan_usd": check["cost_upper_bound_usd"] / len(targets) if targets else None,
                     "deferred_reason": reason,
                     "outcomes": {"pass": "Retain candidates for held-out confirmation; no adoption claim" if check["phase"] == "screening" else "May confirm a whole plan within the held-out task sample",
                                  "fail": "Remove affected candidates from this screening shortlist only" if check["phase"] == "screening" else "Reject the failed full-plan observation; retain it in history",
                                  "unknown": "Stop and repair evidence; do not infer pass, failure or zero cost"}})
    relevant = [r for r in rows if r["deferred_reason"] is None]
    affordable = [r for r in relevant if spent + r["cost_upper_bound_usd"] <= protocol["budget"]["max_usd"] + 1e-12]
    if best and not unresolved:
        return "STOP_CHOICE_STABLE", [], rows
    if len(used) >= protocol["budget"]["max_batches"] or (relevant and not affordable):
        return "STOP_BUDGET", [], rows
    if not relevant:
        return "STOP_NO_RELEVANT_CHECK", [], rows
    # No invented success probabilities. Equal ratios remain explicit choices.
    score = min(r["cost_per_affected_plan_usd"] for r in affordable)
    winners = [r for r in affordable if abs(r["cost_per_affected_plan_usd"] - score) <= 1e-12]
    return "NEXT_BATCH", winners, rows


def _batch_plan(protocol_hash, history, check, index):
    suite = deepcopy(check["suite"])
    suite["acquisition_batch"] = {"protocol_sha256": protocol_hash, "history_sha256": suite_digest(history),
                                  "check_id": check["id"], "index": index, "phase": check["phase"]}
    return {"check_id": check["id"], "suite": suite, "lock": {"suite_sha256": suite_digest(suite)},
            "reserved_usd": check["cost_upper_bound_usd"], "planned_runs": len(suite["cases"]) * suite["runs_per_case"] * 2}


def _observe(check, plan, result, plans, sessions, artifacts, verifiers):
    _keys(result, ("records", "cost_ledger"))
    if not isinstance(result["records"], list) or any(not isinstance(r, dict) for r in result["records"]):
        raise ValidationError("Batch observations must contain original run objects")
    issues = []
    arms = check["suite"]["task_selection"]["arms"]
    for record in result["records"]:
        arm = record.get("arm")
        if not isinstance(arm, str) or arm not in arms:
            issues.append("Unexpected record arm")
            continue
        components = {c["id"]: c["sha256"] for c in plans[arms[arm]]["manifest"]["components"]}
        if (record.get("selection_plan_sha256") != arms[arm] or record.get("observed_components") != components
                or record.get("input_snapshot") != check["inputs"]):
            issues.append("Observed full-plan, components or input bindings missing or changed")
        sid = record.get("session_id")
        if isinstance(sid, str):
            if sid in sessions:
                issues.append("Session reused across screening/confirmation batches")
            sessions.add(sid)
    with read_only_verification():
        report = evaluate(plan["suite"], result["records"], plan["lock"], result["cost_ledger"],
                          artifact_root=artifacts, verifier_root=verifiers)
    issues.extend(report["blockers"])
    if report["methodology"]["violations"]:
        issues.append("Frozen scientific decision-error limits violated")
    totals = [report["cost_analysis"]["arms"][a]["total_usd"] for a in ("with", "without")]
    total = sum(totals) if None not in totals and report["cost_analysis"]["complete_category_coverage"] else None
    if total is not None and not math.isfinite(total):
        total = None
    if total is None:
        issues.append("Complete batch cost is unknown; reserve the full cap and stop")
    outcomes, cases = {}, []
    for arm, pid in arms.items():
        states = []
        for case in report["cases"]:
            runs = [r for r in case["runs"] if r["arm"] == arm]
            local = [run_success(r, check["suite"]["policy"]["quality_floor"]) for r in runs]
            state = "UNKNOWN" if issues or None in local or not local else "FAIL" if False in local else "PASS"
            if arm == "with" and case["delta"] is not None and case["delta"] < -check["suite"]["policy"]["max_case_regression"] - 1e-12:
                state = "UNKNOWN" if issues else "FAIL"
            cases.append({"plan_sha256": pid, "case_id": case["id"], "status": state})
            if case["id"] in check["decision_case_ids"]:
                states.append(state)
        outcomes[pid] = "UNKNOWN" if "UNKNOWN" in states else "FAIL" if "FAIL" in states else "PASS"
    return {"check_id": check["id"], "phase": check["phase"], "outcomes": outcomes, "cases": cases,
            "blockers": sorted(set(issues)), "total_cost_usd": total, "evidence_type": report["evidence_type"],
            "provenance": report["provenance"],
            "verification_receipts": [{"case_id": c["id"], "arm": r["arm"], "repetition": r["repetition"], "grade_id": g["id"],
                                       "verification": deepcopy(g["verification"])}
                                      for c in report["cases"] for r in c["runs"] for g in r["grades"] if "verification" in g]}


def plan_acquisition(selection, request, *, artifact_root=None, verifier_root=None):
    base = select_task_plan(selection, artifact_root=artifact_root, verifier_root=verifier_root)
    protocol, checks, plans = _validate(selection, request, base)
    excluded, confirmed, used, sessions, cells = set(), set(), set(), set(), {}
    observations, history, spent = [], [], 0.0
    synthetic, confirmation_started, blocking = False, False, None
    if base["baseline_coverage_gaps"] or base["unbound_studies"]:
        blocking = "REPAIR_CATALOG"
    if any(p["applicability_blockers"] for p in plans.values() if p["status"] != "INAPPLICABLE"):
        blocking = "CLARIFY_TASK"
    for index, batch in enumerate(request["batches"], 1):
        _keys(batch, ("plan", "result"))
        state, winners, _ = _agenda(protocol, checks, plans, used, excluded, confirmed, cells, confirmation_started, spent)
        if blocking or state != "NEXT_BATCH":
            raise ValidationError("History continued after a stop, pending batch or unresolved evidence")
        cid = batch["plan"].get("check_id") if isinstance(batch["plan"], dict) else None
        if cid not in {w["check_id"] for w in winners}:
            raise ValidationError("Batch was not a decision-relevant next choice under the frozen rule and budget")
        check = checks[cid]
        expected = _batch_plan(request["protocol_sha256"], history, check, index)
        if suite_digest(batch["plan"]) != suite_digest(expected):
            raise ValidationError("Batch lock, matrix, cap or prior history was changed")
        used.add(cid)
        confirmation_started |= check["phase"] == "confirmation"
        history.append(deepcopy(batch))
        if batch["result"] is None:
            spent += check["cost_upper_bound_usd"]
            blocking = "WAIT_FOR_BATCH"
            continue
        observation = _observe(check, expected, batch["result"], plans, sessions, artifact_root, verifier_root)
        observations.append(observation)
        synthetic |= observation["evidence_type"] == "synthetic"
        cost = observation["total_cost_usd"]
        spent += cost if cost is not None else check["cost_upper_bound_usd"]
        if cost is not None and cost > check["cost_upper_bound_usd"] + 1e-12:
            blocking = "STOP_BUDGET_OVERRUN"
        elif observation["blockers"] or "UNKNOWN" in observation["outcomes"].values():
            blocking = "REPAIR_EVIDENCE"
        if blocking:
            continue
        for pid, outcome in observation["outcomes"].items():
            if outcome == "FAIL":
                if pid in confirmed:
                    blocking = "REVIEW_CONFLICT"
                excluded.add(pid)
                confirmed.discard(pid)
            elif check["phase"] == "confirmation":
                if pid in excluded:
                    blocking = "REVIEW_CONFLICT"
                else:
                    confirmed.add(pid)
        for item in observation["cases"]:
            case = next(c for c in check["suite"]["cases"] if c["id"] == item["case_id"])
            key = _cell(check, item["plan_sha256"], case)
            if key in cells and cells[key] != item["status"]:
                blocking = "REVIEW_CONFLICT"
            cells[key] = item["status"]
    state, winners, agenda = _agenda(protocol, checks, plans, used, excluded, confirmed, cells, confirmation_started, spent)
    state = blocking or state
    best, unresolved, frontier = _frontier(plans, excluded, confirmed)
    next_batches = [_batch_plan(request["protocol_sha256"], history, checks[w["check_id"]], len(history) + 1)
                    for w in winners] if state == "NEXT_BATCH" else []
    return {"format": FORMAT, "state": state, "evidence_status": "SIMULATION_ONLY" if synthetic else "SUBMITTED_OBSERVATIONS" if observations else "NO_OBSERVATIONS",
            "protocol_sha256": request["protocol_sha256"], "history_sha256": suite_digest(history),
            "next_batch_options": next_batches, "agenda": agenda, "observations": observations,
            "screening_excluded_plan_sha256s": sorted({p for o in observations if o["phase"] == "screening" and not o["blockers"]
                                                       for p, status in o["outcomes"].items() if status == "FAIL"}),
            "confirmation_failed_plan_sha256s": sorted({p for o in observations if o["phase"] == "confirmation" and not o["blockers"]
                                                        for p, status in o["outcomes"].items() if status == "FAIL"}),
            "unresolved_plan_sha256s": [p["plan_sha256"] for p in unresolved],
            "candidate_plans": [{"plan_sha256": p["plan_sha256"], "manifest": deepcopy(p["manifest"]), "size": p["size"],
                                 "applicability_status": p["status"], "applicability_blockers": p["applicability_blockers"]}
                                for p in plans.values()],
            "choice_stable": state == "STOP_CHOICE_STABLE" and not synthetic,
            "required_reviews": sorted(set(base["required_reviews"]) | {r for p in best for r in p["required_reviews"]}),
            "confirmed_plan_sha256s": sorted(confirmed) if not synthetic else [],
            "choice_plan_sha256s": [p["plan_sha256"] for p in best] if not synthetic and not blocking else [],
            "selected_plan_sha256": best[0]["plan_sha256"] if len(best) == 1 and not synthetic and not blocking else None,
            "selection_scope": "Held-out observed plans among screening survivors only; screened exclusions do not prove global or catalog-wide minimum",
            "budget": {**protocol["budget"], "spent_or_reserved_usd": spent,
                       "remaining_usd": max(0, protocol["budget"]["max_usd"] - spent), "batches_started": len(history),
                       "basis": "Complete submitted full-cost totals or reserved caps; not verified billing or payment authorization"},
            "planned_runs_started": sum(b["plan"]["planned_runs"] for b in history),
            "never_started_check_ids": sorted(set(checks) - used),
            "confirmation_started": confirmation_started, "statistical_guarantee": "NONE",
            "automatic_execution": False, "external_actions": 0,
            "limits": ["Cost per decision-relevant plan is a deterministic priority, not probability or expected information gain.",
                       "Screening outcomes only change the shortlist; held-out full-stage/integration confirmation is required.",
                       "Every started batch keeps its frozen denominator, failures, unknowns, costs and provenance.",
                       "Input hashes and history chains do not authenticate preregistration time, non-exposure, independence or execution.",
                       "Stopping may leave no choice. No optional-stopping confidence guarantee, real cost savings or scientific validity is established."]}
