"""Prospectively selected endpoints; never rewrite the legacy verdict.

Failure labels are submitted observations with evidence references, not authenticated
root-cause determinations. Missing observations always retain their denominator.
"""
from collections import defaultdict
from statistics import mean
import random

ESTIMANDS = ("scientific_correctness", "runtime_reliability", "full_delivery")
CLASSES = ("measurement", "tested_system", "provider", "infrastructure", "unclassified")


def validate_policy(policy):
    from .core import ValidationError, _text
    plan = policy.get("value_interpretation")
    if plan is None:
        return
    fields = {"version", "primary_estimand", "pairing_rationale", "task_distribution", "failure_rules"}
    if not isinstance(plan, dict) or set(plan) != fields or type(plan["version"]) is not int or plan["version"] != 1:
        raise ValidationError("value_interpretation requires the complete version 1 prospective plan")
    if plan["primary_estimand"] not in ESTIMANDS:
        raise ValidationError("Unknown primary estimand")
    for field in ("pairing_rationale", "task_distribution"):
        _text(plan[field], field)
    rules = plan["failure_rules"]
    if not isinstance(rules, dict) or set(rules) != set(ESTIMANDS):
        raise ValidationError("Specify failure rules for all three estimands")
    for endpoint, row in rules.items():
        if not isinstance(row, dict) or set(row) != set(CLASSES) or any(v not in ("unknown", "failure") for v in row.values()):
            raise ValidationError("Each estimand requires all five failure classes")
        if row["measurement"] != "unknown" or row["unclassified"] != "unknown":
            raise ValidationError("Measurement and unclassified failures must remain unknown")
        if endpoint == "scientific_correctness" and any(row[k] != "unknown" for k in ("provider", "infrastructure")):
            raise ValidationError("External outages cannot establish scientific incorrectness")


def validate_failure(record):
    from .core import ValidationError, _text
    label = record.get("failure_observation")
    if label is None:
        return
    if not isinstance(label, dict) or set(label) != {"class", "evidence_ref", "rationale"} or label["class"] not in CLASSES:
        raise ValidationError("Invalid failure observation")
    _text(label["evidence_ref"], "failure evidence reference")
    _text(label["rationale"], "failure rationale")
    if record.get("status") == "completed" and label["class"] != "measurement":
        raise ValidationError("Completed execution contradicts a runtime failure observation")


def _state(run, floor, endpoint, rules):
    if run is None or run["status"] in ("missing", "skipped") or run.get("observation_issues"):
        return None
    label = run.get("failure_observation")
    if label:
        # A failed measurement does not erase an observed completed execution.
        if endpoint == "runtime_reliability" and run["status"] == "completed":
            return True
        return False if rules[label["class"]] == "failure" else None
    if run["status"] != "completed":
        return None
    if endpoint == "runtime_reliability":
        return True
    grades = [g for g in run["grades"] if g["scored"] or g["critical"]]
    if not grades or any(g["passed"] is None for g in grades):
        return None
    return run["score"] is not None and run["score"] + 1e-12 >= floor and all(g["passed"] for g in grades if g["critical"])


def _endpoint(cases, n, floor, endpoint, rules):
    counts = {a: {"successes": 0, "failures": 0, "unknown": 0} for a in ("with", "without")}
    transitions = {"observed_paired_improvements": 0, "observed_paired_regressions": 0, "unknown_pairs": 0}
    families = defaultdict(list)
    for case in cases:
        index = {(r["repetition"], r["arm"]): r for r in case["runs"]}
        for rep in range(1, n + 1):
            states = {a: _state(index.get((rep, a)), floor, endpoint, rules) for a in counts}
            for arm, state in states.items():
                counts[arm]["unknown" if state is None else "successes" if state else "failures"] += 1
            w, b = states["with"], states["without"]
            families[case["cluster"]].append(None if w is None or b is None else int(w) - int(b))
            transitions["unknown_pairs"] += w is None or b is None
            transitions["observed_paired_improvements"] += w is True and b is False
            transitions["observed_paired_regressions"] += w is False and b is True
    planned = len(cases) * n
    for row in counts.values():
        row.update(planned=planned, rate=row["successes"] / planned if not row["unknown"] else None,
                   lower_bound=row["successes"] / planned, upper_bound=(row["successes"] + row["unknown"]) / planned)
    w, b = counts["with"], counts["without"]
    deltas = {k: mean(v) if None not in v else None for k, v in sorted(families.items())}
    interval = {"status": "UNAVAILABLE", "reason": "Incomplete outcomes or fewer than two family labels"}
    if len(deltas) >= 2 and None not in deltas.values():
        rng, values = random.Random(20260924), list(deltas.values())
        boot = sorted(mean(rng.choices(values, k=len(values))) for _ in range(2000))
        interval = {"status": "DESCRIPTIVE_ONLY", "method": "equal-family percentile bootstrap; 2000 draws, seed 20260924",
                    "lower": boot[49], "upper": boot[1949], "independence": "DECLARED_NOT_VERIFIED"}
    return {"arms": counts, **transitions,
            "task_distribution_success_delta": w["rate"] - b["rate"] if w["rate"] is not None and b["rate"] is not None else None,
            "missingness_delta_bounds": [w["lower_bound"] - b["upper_bound"], w["upper_bound"] - b["lower_bound"]],
            "family_deltas": deltas, "equal_family_success_delta": mean(deltas.values()) if None not in deltas.values() else None,
            "family_uncertainty": interval}


def build_interpretation(suite, report):
    plan = suite["policy"]["value_interpretation"]
    endpoints = {e: _endpoint(report["cases"], suite["runs_per_case"], suite["policy"]["quality_floor"], e, plan["failure_rules"][e]) for e in ESTIMANDS}
    claims = []
    for case in report["cases"]:
        for run in case["runs"]:
            for grade in run["grades"]:
                result = grade["passed"]
                claims.append({"case": case["id"], "arm": run["arm"], "repetition": run["repetition"], "grader": grade["id"],
                               "status": "PASS" if result is True else "FAIL" if result is False else "UNRESOLVED",
                               "scope": "This check on submitted artifacts only; no global benefit or authenticity claim",
                               "observation_issues": run.get("observation_issues", []),
                               "verification": grade.get("verification"), "rationale": grade["rationale"]})
    return {"version": 1, "frozen_plan": plan, "endpoints": endpoints, "check_claims": claims,
            "status": "SIMULATION_ONLY" if report["evidence_type"] == "synthetic" else "DESCRIPTIVE_SUBMITTED_OBSERVATIONS",
            "comparison_eligible": report["summary"]["comparison_eligible"],
            "cash_savings": "SUPPORTED_WITHIN_SUBMITTED_SCOPE" if report["cost_analysis"].get("settled_saving_claim_eligible") else "INSUFFICIENT_EVIDENCE",
            "new_data_generalization": "NOT_TESTED", "donor_independence": "NOT_ESTABLISHED_BY_VALUE_METRICS",
            "legacy_verdict_unchanged": True,
            "limitations": ["Transition counts depend on repetition pairing, not individual causal rescue or harm.",
                            "Missingness bounds are not confidence intervals; bootstrap is descriptive, not a confirmatory test.",
                            "Failure classes and evidence references are submitted claims, not authenticated causes.",
                            "New frozen endpoints supplement, and never upgrade, the legacy comparison verdict."]}
