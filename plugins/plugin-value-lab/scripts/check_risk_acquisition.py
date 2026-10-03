"""Matched fixed-risk allocation experiments on preregistered synthetic scenarios.

Uniform and adaptive policies share thresholds, bounds, ceilings and potential
outcome streams. This is statistical engineering calibration, not researcher benefit.
"""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import random
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.core import suite_digest
from value_lab.risk_acquisition import (ASSUMPTIONS, BOUND, FORMAT, RULE, allocation, decision, empty_stats,
                                        risk_identity, validate_protocol)


def protocol(count=6, allocation_rule="adaptive_frontier"):
    return {"format": FORMAT, "catalog_sha256": "a" * 64, "task_sha256": "b" * 64,
            "objective": RULE, "bound": BOUND, "alpha": 0.05, "epsilon": 0.12, "quality_floor": 0.5,
            "allocation": allocation_rule, "candidates": [{"id": f"c{i}", "plan_sha256": suite_digest({"candidate": i}),
                "unit_cost_cap_micros": 10} for i in range(count)], "baseline_id": "c0",
            "max_units_per_candidate": 2048, "batch_units": 32, "runs_per_unit": 1,
            "budget_micros": count * 2048 * 10, "max_total_units": count * 2048,
            "population": {"id": "synthetic-iid", "sampling_unit": "independent task instance",
                "sampling_rule": "New independent bounded utility draws, assignment precedes outcomes", "distribution_sha256": "c" * 64},
            "utility_contract": {"measure": "Bernoulli task completion utility", "failure": 0, "scale": [0, 1]},
            "assumptions": {k: True for k in ASSUMPTIONS}, "evidence_type": "synthetic"}


SCENARIOS = (
    ("separated", (0.35, 0.90, 0.25, 0.10, 0.20, 0.30), None),
    ("few_finalists", (0.90, 0.87, 0.15, 0.20, 0.10, 0.25), None),
    ("near_ties", (0.73, 0.72, 0.71, 0.72, 0.73, 0.72), None),
    ("none_acceptable", (0.10, 0.12, 0.15, 0.20, 0.18, 0.25), None),
    ("floor_boundary", (0.50, 0.49, 0.48, 0.47, 0.46, 0.45), None),
    ("budget_too_small", (0.90, 0.87, 0.15, 0.20, 0.10, 0.25), 192),
)


def simulate(spec, means, seed):
    """Use precisely the production bound, certificate and allocation functions."""
    stats = empty_stats(spec)
    # Identical candidate-specific prefixes are shared across policies, avoiding
    # policy-dependent RNG consumption. No outcome is used before assignment.
    streams = {i: random.Random(suite_digest({"seed": seed, "candidate": i})) for i in stats}
    mean_by_id = dict(zip(stats, means))
    started = spent = 0
    while True:
        state, chosen, _ = decision(spec, stats)
        if state != "UNRESOLVED":
            break
        ids, units = allocation(spec, stats)
        if not ids:
            state = "STOP_HORIZON_UNRESOLVED"
            break
        cost = units * sum(next(c["unit_cost_cap_micros"] for c in spec["candidates"] if c["id"] == i) for i in ids)
        if started + units * len(ids) > spec["max_total_units"] or spent + cost > spec["budget_micros"]:
            state = "STOP_BUDGET_UNRESOLVED"
            break
        started += units * len(ids)
        spent += cost
        for i in ids:
            stats[i]["n"] += units
            stats[i]["sum"] += sum(streams[i].random() < mean_by_id[i] for _ in range(units))
    issued = state.startswith("CERTIFIED_")
    regret = max(means) - mean_by_id[chosen] if chosen is not None else None
    wrong = (mean_by_id[chosen] < spec["quality_floor"] or regret > spec["epsilon"] + 1e-12) if chosen else (
        max(means) >= spec["quality_floor"] if state == "CERTIFIED_NO_ACCEPTABLE_CANDIDATE" else False)
    return {"risk_identity": risk_identity(spec), "allocation": spec["allocation"], "replication_id": str(seed),
            "oracle_sha256": suite_digest({"means": means}), "state": state, "chosen": chosen, "issued": issued, "wrong": wrong,
            "useful": issued and not wrong, "regret": regret, "units": started, "cost_micros": spent}


def compare(spec, adaptive, uniform, *, comparison_error=0.05, coverage_margin=0.03, minimum_coverage=0.8):
    """Require useful coverage and risk, not merely low mean run counts.

    Conservative one-sided Hoeffding bounds over independent scenario repetitions.
    Paired coverage loss is bounded using discordance Bernoullis, while sample
    savings uses bounded paired differences. Per-row five-way error split.
    """
    if not 0 < comparison_error < 1 or not 0 <= coverage_margin <= 1 or not 0 <= minimum_coverage <= 1:
        raise ValueError("Freeze valid comparison error and usefulness thresholds")
    if len(adaptive) != len(uniform) or not adaptive:
        raise ValueError("Matched nonempty scenario repetitions required")
    if len({r["replication_id"] for r in adaptive}) != len(adaptive):
        raise ValueError("Repeated simulation seeds are not independent replications")
    for a, u in zip(adaptive, uniform):
        if (a["risk_identity"] != risk_identity(spec) or u["risk_identity"] != risk_identity(spec)
                or a["allocation"] != "adaptive_frontier" or u["allocation"] != "uniform_all"
                or (a["replication_id"], a["oracle_sha256"]) != (u["replication_id"], u["oracle_sha256"])):
            raise ValueError("Comparison must preserve risk, usefulness, oracle, budgets and paired replication identity")
    n = len(adaptive)
    delta = comparison_error / 5
    radius = math.sqrt(math.log(1 / delta) / (2 * n))
    # Spend half the per-metric error on each branch; do not silently select
    # between two confidence procedures without accounting for that selection.
    def event_upper(events):
        count = sum(events)
        return 1 - (delta / 2) ** (1 / n) if count == 0 else min(1.0, count / n + math.sqrt(math.log(2 / delta) / (2 * n)))
    risk_upper = event_upper([r["wrong"] for r in adaptive])
    uniform_risk_upper = event_upper([r["wrong"] for r in uniform])
    missed_upper = event_upper([u["useful"] and not a["useful"] for a, u in zip(adaptive, uniform)])
    coverage_lower = max(0.0, statistics.mean(r["useful"] for r in adaptive) - radius)
    ceiling = spec["max_total_units"]
    savings = [u["units"] - a["units"] for a, u in zip(adaptive, uniform)]
    savings_lower = statistics.mean(savings) - 2 * ceiling * radius
    equal_contract = all(risk_identity({**spec, "allocation": x}) == risk_identity(spec) for x in ("uniform_all", "adaptive_frontier"))
    passed = equal_contract and max(risk_upper, uniform_risk_upper) <= spec["alpha"] and missed_upper <= coverage_margin and coverage_lower >= minimum_coverage and savings_lower > 0
    def summary(rows):
        issued = sum(r["issued"] for r in rows)
        return {"replications": n, "issued_decisions": issued, "wrong_decisions": sum(r["wrong"] for r in rows),
                "useful_decision_rate": statistics.mean(r["useful"] for r in rows),
                "abstention_rate": 1 - issued / n, "mean_candidate_units": statistics.mean(r["units"] for r in rows),
                "mean_cost_micros": statistics.mean(r["cost_micros"] for r in rows),
                "wrong_among_issued": sum(r["wrong"] for r in rows) / issued if issued else None,
                "mean_regret_when_candidate_issued": statistics.mean(r["regret"] for r in rows if r["regret"] is not None)
                    if any(r["regret"] is not None for r in rows) else None}
    return {"adaptive": summary(adaptive), "uniform": summary(uniform), "same_risk_contract": equal_contract,
            "risk_identity": risk_identity(spec), "comparison_error": comparison_error,
            "adaptive_wrong_probability_upper": risk_upper, "uniform_wrong_probability_upper": uniform_risk_upper, "paired_useful_decision_loss_upper": missed_upper,
            "adaptive_useful_coverage_lower": coverage_lower, "mean_paired_units_saved": statistics.mean(savings),
            "paired_savings_lower": savings_lower, "coverage_margin": coverage_margin, "minimum_useful_coverage": minimum_coverage,
            "efficiency_status": "SUPPORTED_IN_THIS_SIMULATION" if passed else "NOT_ESTABLISHED"}


def run(replications=1000, seed=20261002):
    results = []
    for name, means, cap in SCENARIOS:
        spec = protocol(len(means))
        spec["population"]["distribution_sha256"] = suite_digest({"scenario": name, "means": means})
        if cap is not None:
            spec["max_total_units"] = cap
        validate_protocol(spec)
        uniform = {**deepcopy(spec), "allocation": "uniform_all"}
        adaptive_results, uniform_results = [], []
        for index in range(replications):
            run_seed = suite_digest({"scenario": name, "seed": seed, "replication": index})
            adaptive_results.append(simulate(spec, means, run_seed))
            uniform_results.append(simulate(uniform, means, run_seed))
        # The family comparison budget covers all frozen scenarios too.
        comparison = compare(spec, adaptive_results, uniform_results, comparison_error=0.05 / len(SCENARIOS))
        results.append({"scenario": name, "true_means": means, "protocol": spec, **comparison})
    return {"format": "pvl-risk-efficiency-calibration-1", "evidence": "SIMULATION_ONLY", "seed": seed,
            "replications_per_scenario": replications, "scenario_family_error": 0.05,
            "scenarios": results, "real_researcher_benefit_established": False,
            "limitations": ["Shared error ceilings are not proof of equal true error rates.",
                "Acceptance concerns these frozen independent Bernoulli scenarios only; no real scientific correctness claim.",
                "Low-budget abstentions and hard near-boundary tasks must remain visible.",
                "No new external executions or paid calls."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--replications", type=int, default=1000)
    args = parser.parse_args()
    if not 1 <= args.replications <= 10000:
        parser.error("replications must be 1..10000")
    output = Path(args.output)
    if output.exists():
        parser.error("Preserve the prior calibration; choose a new output")
    result = run(args.replications)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "scenarios": [{k: r[k] for k in ("scenario", "efficiency_status", "mean_paired_units_saved")} for r in result["scenarios"]]}, indent=2))
