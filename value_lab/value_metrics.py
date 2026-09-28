"""Outcome benefit indicators and prospective planning, never efficacy certification."""
import math
from collections import defaultdict
from statistics import NormalDist, mean


def validate_power_plan(policy):
    from .core import ValidationError, _number
    if policy.get('quality_weighting', 'case') not in ('case', 'family'):
        raise ValidationError('quality_weighting must be case or family; choose before freezing')
    if "require_settled_costs" in policy and type(policy["require_settled_costs"]) is not bool:
        raise ValidationError("require_settled_costs must be boolean")
    plan = policy.get("power_plan")
    if plan is None:
        return
    fields = {"expected_family_sd", "minimum_detectable_delta", "alpha", "power"}
    if not isinstance(plan, dict) or set(plan) != fields:
        raise ValidationError("power_plan requires expected_family_sd, minimum_detectable_delta, alpha and power")
    _number(plan["expected_family_sd"], "expected_family_sd", 0.000001, 1)
    _number(plan["minimum_detectable_delta"], "minimum_detectable_delta", 0.000001, 1)
    _number(plan["alpha"], "alpha", 0.000001, 0.2)
    _number(plan["power"], "power", 0.5, 0.999999)


def power_plan(suite):
    plan = suite["policy"].get("power_plan")
    families = len({c["cluster"] for c in suite["cases"]})
    base = {"planned_families": families, "repetitions_per_case": suite["runs_per_case"],
            "aligned_with_primary_quality_gate": suite['policy'].get('quality_weighting', 'case') == 'family',
            "unit": "Independent task-family mean paired quality difference; equal family weight",
            "limitations": "Prospective normal approximation, not observed power or a significance test. "
            "Requires representative independent families and a justified external/pilot SD; "
            "small samples and estimated variance require a refined design. Repeats are not independent families."}
    if plan is None:
        return {**base, "status": "NOT_PLANNED", "required_families": None,
                "additional_families": None, "minimum_detectable_delta": None}
    z = NormalDist().inv_cdf(1 - plan["alpha"] / 2) + NormalDist().inv_cdf(plan["power"])
    required = max(2, math.ceil((z * plan["expected_family_sd"] / plan["minimum_detectable_delta"]) ** 2))
    return {**base, **plan, "status": "PLANNING_TARGET_MET" if families >= required else "MORE_FAMILIES_NEEDED",
            "required_families": required, "additional_families": max(0, required - families),
            "approximate_detectable_delta_at_planned_n": z * plan["expected_family_sd"] / math.sqrt(families),
            "method": "Two-sided normal mean-shift approximation; ceil((z(1-alpha/2)+z(power))^2 * SD^2 / delta^2)",
            "source": "https://www.itl.nist.gov/div898/handbook/prc/section2/prc222.htm"}


def _success(run, floor):
    from .scoring import run_success
    return run_success(run, floor)


def quality_summary(cases, weighting='case'):
    """Use one frozen estimand for the headline and its gate; keep both visible."""
    groups = defaultdict(list)
    for case in cases:
        groups[case['cluster']].append(case)
    def complete_mean(values):
        return mean(values) if values and None not in values else None
    summaries = {}
    for mode in ('case', 'family'):
        row = {}
        for arm in ('with', 'without'):
            values = ([c[arm + '_score'] for c in cases] if mode == 'case' else
                      [complete_mean([c[arm + '_score'] for c in group]) for group in groups.values()])
            row[arm + '_score'] = complete_mean(values)
        row['quality_delta'] = (row['with_score'] - row['without_score']
                                if None not in row.values() else None)
        summaries[mode] = row
    return {'weighting': weighting, 'selection': 'FROZEN_POLICY_OR_LEGACY_CASE_DEFAULT',
            'primary': summaries[weighting], 'sensitivity': summaries,
            'family_case_counts': {name: len(group) for name, group in groups.items()},
            'scope': 'Outcome quality score only. Success, cash and interpretation endpoints are separate; do not select a favorable weighting after observation.'}


def decision_review(report):
    """Explain current gates; never invent a relaxed failure budget or adoption."""
    counts = {}
    for arm in ('with', 'without'):
        states = [_success(r, report['policy']['quality_floor']) for c in report['cases']
                  for r in c['runs'] if r['arm'] == arm]
        counts[arm] = {'planned': len(states), 'passed': states.count(True),
                       'failed': states.count(False), 'unknown': states.count(None)}
    return {
        'single_run': {'arms': counts, 'scope': 'Passed means the configured task contract, never biological validity or general usability.'},
        'controlled_trial': {'status': 'LOCAL_SIGNAL_FOR_REVIEW' if report['verdict'] == 'PROMISING_LOCAL_SIGNAL'
                             else 'SIMULATION_ONLY' if report['evidence_type'] == 'synthetic' else 'NO_POSITIVE_RECOMMENDATION',
            'success_policy': 'ALL_PLANNED_WITH_RUNS_MUST_PASS',
            'allowed_failed_or_unknown_with_runs': 0,
            'all_with_success_gate_met': report['summary']['task_success_gate_met'],
            'scope': 'Review for a bounded new trial under the same conditions; not execution authorization. Any nonzero failure budget needs a separately justified prospective protocol.'},
        'broader_use': {'status': 'NOT_ESTABLISHED',
                       'requires': ['independent users and task coverage', 'natural-use evidence', 'complete burden and reviewed outcomes']}}


def _rates(cases, repetitions, floor):
    planned = len(cases) * repetitions
    counts = {a: {"successes": 0, "unknown": 0} for a in ("with", "without")}
    rescued = harmed = both_pass = both_fail = unknown = 0
    for case in cases:
        index = {(r["repetition"], r["arm"]): r for r in case["runs"]}
        for rep in range(1, repetitions + 1):
            states = {a: _success(index.get((rep, a)), floor) for a in counts}
            for arm, success in states.items():
                counts[arm]["unknown"] += success is None
                counts[arm]["successes"] += success is True
            w, b = states["with"], states["without"]
            if w is None or b is None:
                unknown += 1
            else:
                rescued += w and not b
                harmed += b and not w
                both_pass += w and b
                both_fail += not w and not b
    for row in counts.values():
        row["rate"] = row["successes"] / planned if planned and not row["unknown"] else None
        row["lower_bound"] = row["successes"] / planned if planned else None
        row["upper_bound"] = (row["successes"] + row["unknown"]) / planned if planned else None
    complete = planned and not unknown
    return {"planned_pairs": planned, "arms": counts, "rescued": rescued, "harmed": harmed,
            "both_succeed": both_pass, "both_fail": both_fail, "unknown_pairs": unknown,
            "success_rate_delta": (rescued - harmed) / planned if complete else None,
            "net_additional_successes_per_100": 100 * (rescued - harmed) / planned if complete else None,
            "rescue_rate": rescued / (rescued + both_fail) if complete and rescued + both_fail else None,
            "harm_rate": harmed / (harmed + both_pass) if complete and harmed + both_pass else None}


def build_value_metrics(suite, report):
    cases, costs = report["cases"], report["cost_analysis"]
    rates = _rates(cases, suite["runs_per_case"], suite["policy"]["quality_floor"])
    groups = defaultdict(list)
    for case in cases:
        groups[case["cluster"]].append(case["delta"])
    family_deltas = {k: mean(v) if None not in v else None for k, v in groups.items()}
    comparable = report["summary"]["comparison_eligible"]
    arms = {}
    for arm in ("with", "without"):
        rows = [r for c in cases for r in c["runs"] if r["arm"] == arm]
        times = [r.get("duration_seconds") for r in rows]
        valid_times = all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in times)
        info = costs["arms"][arm]
        arms[arm] = {"mean_duration_seconds": mean(times) if times and valid_times and comparable else None,
                     "human_minutes_per_run": info["declared_human_minutes"] / len(rows)
                     if rows and info["human_time_complete"] and comparable else None,
                     "cost_per_success_usd": info['cost_per_success_usd']}
    def saved(key):
        w, b = arms["with"][key], arms["without"][key]
        return b - w if comparable and w is not None and b is not None else None
    return {"schema_version": 1, "status": "SIMULATION_ONLY" if report["evidence_type"] == "synthetic"
            else "DESCRIPTIVE_LOCAL" if comparable else "INCOMPLETE_OR_CONFOUNDED",
            "benefit_claim_eligible": report["verdict"] == "PROMISING_LOCAL_SIGNAL",
            "success": rates,
            "by_kind": {kind: _rates([c for c in cases if c["kind"] == kind], suite["runs_per_case"], suite["policy"]["quality_floor"])
                        for kind in ("task", "negative", "abstention")},
            "families": {"deltas": family_deltas,
                         "equal_weight_quality_delta": mean(family_deltas.values()) if None not in family_deltas.values() else None,
                         "improved": sum(v is not None and v > 1e-12 for v in family_deltas.values()),
                         "regressed": sum(v is not None and v < -1e-12 for v in family_deltas.values())},
            "arms": arms, "human_minutes_saved_per_run": saved("human_minutes_per_run"),
            "duration_seconds_saved_per_run": saved("mean_duration_seconds"),
            "cost_per_success_saved_usd": saved("cost_per_success_usd"),
            "power_plan": power_plan(suite),
            "limitations": ["Success uses the shared task outcome gate: required decision/delivery/correctness evidence, completion, quality floor and critical checks. Text-only legacy suites measure configured checks only. Missing pairs remain in planned denominators; bounds are not confidence intervals.",
                            "Rescue rate is rescued / baseline failures; harm rate is harmed / baseline successes. Pairing must be justified by the frozen design.",
                            "Task, negative-control and abstention strata are separate: refusing everything is not productive task benefit.",
                            "Human time is submitted run-level timer time; supplemental setup/review time belongs to the full cost ledger. Waiting is not labor.",
                            "Local indicators do not establish statistical significance, independent replication, commercial ROI or scientific validity."]}
