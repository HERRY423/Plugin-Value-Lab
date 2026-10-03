"""Fixed-risk, bounded-horizon experiment allocation over a frozen candidate set.

Hoeffding + a union bound over candidates and local sample sizes, not an
optimal-bandit implementation. Utility and sampling assumptions are submitted
evidence. A statistical candidate never replaces full task/scientific acceptance.
"""
from copy import deepcopy
import math

from .core import ValidationError, suite_digest
from .task_selection import _keys, _id, _sha, _text, select_task_plan

FORMAT = "pvl-risk-acquisition-1"
RULE = "epsilon_optimal_above_floor_v1"
BOUND = "hoeffding_candidate_horizon_union_v1"
ASSUMPTIONS = ("bounded_utility", "independent_units", "stationary_population", "predictable_assignment")


def _number(x, low, high):
    if type(x) not in (int, float) or not math.isfinite(x) or not low <= x <= high:
        raise ValidationError("Risk parameters and utility must be finite numbers in their declared range")


def _integer(x, low, high):
    if type(x) is not int or not low <= x <= high:
        raise ValidationError("Expected a bounded nonnegative integer")


def validate_protocol(protocol):
    _keys(protocol, ("format", "catalog_sha256", "task_sha256", "objective", "bound", "alpha", "epsilon", "quality_floor",
                     "allocation", "candidates", "baseline_id", "max_units_per_candidate", "batch_units", "runs_per_unit",
                     "budget_micros", "max_total_units", "population", "utility_contract", "assumptions", "evidence_type"))
    if protocol["format"] != FORMAT or protocol["objective"] != RULE or protocol["bound"] != BOUND:
        raise ValidationError("Unsupported risk contract")
    for key in ("catalog_sha256", "task_sha256"):
        _sha(protocol[key])
    _number(protocol["alpha"], 1e-8, 0.25)
    _number(protocol["epsilon"], 0, 1)
    _number(protocol["quality_floor"], 0, 1)
    if protocol["allocation"] not in ("adaptive_frontier", "uniform_all"):
        raise ValidationError("Choose a frozen adaptive or uniform allocation")
    _integer(protocol["max_units_per_candidate"], 1, 100000)
    _integer(protocol["batch_units"], 1, min(256, protocol["max_units_per_candidate"]))
    _integer(protocol["runs_per_unit"], 1, 10000)
    _integer(protocol["max_total_units"], 0, 3200000)
    _integer(protocol["budget_micros"], 0, 10**15)
    if protocol["evidence_type"] not in ("synthetic", "submitted_observations"):
        raise ValidationError("Declare synthetic or submitted observations")
    _keys(protocol["population"], ("id", "sampling_unit", "sampling_rule", "distribution_sha256"))
    for name in ("id", "sampling_unit", "sampling_rule"):
        _text(protocol["population"][name])
    _sha(protocol["population"]["distribution_sha256"])
    if not isinstance(protocol["utility_contract"], dict) or not protocol["utility_contract"]:
        raise ValidationError("Freeze a utility rubric; utility is not inferred from plugin counts")
    _keys(protocol["assumptions"], ASSUMPTIONS)
    if any(x is not None and type(x) is not bool for x in protocol["assumptions"].values()):
        raise ValidationError("Sampling assumptions are true, false or unknown")
    candidates = protocol["candidates"]
    if not isinstance(candidates, list) or not 2 <= len(candidates) <= 32:
        raise ValidationError("Freeze 2..32 candidates including the baseline")
    ids, plans = set(), set()
    for candidate in candidates:
        _keys(candidate, ("id", "plan_sha256", "unit_cost_cap_micros"))
        _id(candidate["id"])
        _sha(candidate["plan_sha256"])
        _integer(candidate["unit_cost_cap_micros"], 0, 10**12)
        if candidate["id"] in ids or candidate["plan_sha256"] in plans:
            raise ValidationError("Candidate IDs and full plans must be unique")
        ids.add(candidate["id"])
        plans.add(candidate["plan_sha256"])
    _id(protocol["baseline_id"])
    if protocol["baseline_id"] not in ids:
        raise ValidationError("Retain an explicit baseline")
    return protocol


def risk_identity(protocol):
    """Allocation may vary in a comparison; the loss/risk/task/budget may not."""
    return suite_digest({k: v for k, v in protocol.items() if k != "allocation"})


def empty_stats(protocol):
    return {c["id"]: {"n": 0, "sum": 0.0} for c in protocol["candidates"]}


def intervals(protocol, stats):
    k, horizon = len(stats), protocol["max_units_per_candidate"]
    result = {}
    for ident, value in stats.items():
        n = value["n"]
        # At each local n, two-tail error <= alpha/(K*H). Adaptive assignment
        # and stopping are covered by the same finite union of K*H events.
        radius = math.sqrt(math.log(2 * k * horizon / protocol["alpha"]) / (2 * n)) if n else None
        mean = value["sum"] / n if n else None
        result[ident] = {"n": n, "mean": mean, "radius": radius,
                         "lower": max(0.0, mean - radius) if n else 0.0,
                         "upper": min(1.0, mean + radius) if n else 1.0}
    return result


def decision(protocol, stats):
    rows = intervals(protocol, stats)
    certified = [i for i, r in rows.items() if r["n"] and r["lower"] >= protocol["quality_floor"]
                 and r["lower"] >= max(s["upper"] for j, s in rows.items() if j != i) - protocol["epsilon"]]
    # Candidate order is frozen before outcomes; never prefer a plugin implicitly.
    chosen = next((c["id"] for c in protocol["candidates"] if c["id"] in certified), None)
    if chosen is not None:
        return "CERTIFIED_CANDIDATE", chosen, rows
    if all(r["upper"] < protocol["quality_floor"] for r in rows.values()):
        return "CERTIFIED_NO_ACCEPTABLE_CANDIDATE", None, rows
    return "UNRESOLVED", None, rows


def allocation(protocol, stats):
    rows = intervals(protocol, stats)
    best_lower = max(r["lower"] for r in rows.values())
    ids = [c["id"] for c in protocol["candidates"] if
           protocol["allocation"] == "uniform_all" or rows[c["id"]]["upper"] >= best_lower]
    # The entire next block is fixed before its outcomes are seen. A stopped
    # candidate may re-enter if bounds change; there is no unchecked screen prune.
    ids = [i for i in ids if stats[i]["n"] < protocol["max_units_per_candidate"]]
    units = min([protocol["batch_units"], *[protocol["max_units_per_candidate"] - stats[i]["n"] for i in ids]]) if ids else 0
    return ids, units


def _next(protocol, stats, digest, history_hash, index, blocks, spent, started):
    state, chosen, rows = decision(protocol, stats)
    if state != "UNRESOLVED":
        return state, chosen, rows, None
    ids, units = allocation(protocol, stats)
    if not ids:
        return "STOP_HORIZON_UNRESOLVED", None, rows, None
    caps = {c["id"]: c["unit_cost_cap_micros"] for c in protocol["candidates"]}
    reserve = units * sum(caps[i] for i in ids)
    if spent + reserve > protocol["budget_micros"] or started + units * len(ids) > protocol["max_total_units"]:
        return "STOP_BUDGET_UNRESOLVED", None, rows, None
    plan = {"protocol_sha256": digest, "history_sha256": history_hash, "index": index,
            "candidate_ids": ids, "unit_ids": [f"unit-{blocks + n + 1}" for n in range(units)],
            "planned_candidate_units": units * len(ids), "planned_runs": units * len(ids) * protocol["runs_per_unit"],
            "reserved_micros": reserve}
    return "NEXT_BLOCK", None, rows, plan


def analyze(request):
    _keys(request, ("protocol", "protocol_sha256", "batches"), ("assumption_violations",))
    violations = request.get("assumption_violations", [])
    if not isinstance(violations, list) or any(not isinstance(v, str) or not v.strip() for v in violations):
        raise ValidationError("Retain explicit sampling-assumption violation reasons")
    protocol = validate_protocol(request["protocol"])
    digest = suite_digest(protocol)
    if digest != request["protocol_sha256"]:
        raise ValidationError("Frozen risk protocol changed")
    batches = request["batches"]
    if not isinstance(batches, list) or len(batches) > 10000:
        raise ValidationError("Bounded append-only block history required")
    assumptions = all(v is True for v in protocol["assumptions"].values())
    stats, history_hash = empty_stats(protocol), suite_digest([])
    caps = {c["id"]: c["unit_cost_cap_micros"] for c in protocol["candidates"]}
    started = blocks = spent = completed = failed = reported_runs = 0
    costs_complete = True
    sessions, old_inputs, seen_units = set(), set(), set()
    blocker = None if assumptions else "REVIEW_SAMPLING_ASSUMPTIONS"
    observations, issues = [], []
    for index, batch in enumerate(batches, 1):
        _keys(batch, ("plan", "result"))
        state, _, _, expected = _next(protocol, stats, digest, history_hash, index, blocks, spent, started)
        if blocker or state != "NEXT_BLOCK":
            raise ValidationError("History continued after a statistical, budget or unresolved-evidence stop")
        if suite_digest(batch["plan"]) != suite_digest(expected):
            raise ValidationError("Block assignment, budget or prior history changed")
        started += expected["planned_candidate_units"]
        blocks += len(expected["unit_ids"])
        history_hash = suite_digest({"parent": history_hash, "batch": batch})
        if batch["result"] is None:
            spent += expected["reserved_micros"]
            costs_complete = False
            blocker = "WAIT_FOR_ORIGINAL_BLOCK"
            continue
        records = batch["result"]
        if not isinstance(records, list):
            raise ValidationError("Block results must retain individual experimental units")
        expected_cells = {(i, u) for i in expected["candidate_ids"] for u in expected["unit_ids"]}
        cells, input_by_unit, block_cost, local = set(), {}, 0, []
        for record in records:
            _keys(record, ("candidate_id", "unit_id", "input_sha256", "session_id", "assessment_sha256",
                           "utility_contract_sha256", "status", "utility", "cost_micros", "runs_started"))
            _id(record["candidate_id"])
            _id(record["unit_id"])
            cell = (record["candidate_id"], record["unit_id"])
            if cell not in expected_cells or cell in cells:
                raise ValidationError("Duplicate or unassigned observation")
            cells.add(cell)
            for name in ("input_sha256", "assessment_sha256", "utility_contract_sha256"):
                _sha(record[name])
            if record["utility_contract_sha256"] != suite_digest(protocol["utility_contract"]):
                raise ValidationError("Utility rule changed after seeing outcomes")
            _id(record["session_id"])
            if record["session_id"] in sessions:
                raise ValidationError("Execution session reused as independent evidence")
            sessions.add(record["session_id"])
            unit, input_hash = record["unit_id"], record["input_sha256"]
            if input_hash in old_inputs or unit in seen_units:
                raise ValidationError("Prior experimental unit reused; within-task repeats are not fresh units")
            if unit in input_by_unit and input_by_unit[unit] != input_hash:
                raise ValidationError("Matched block candidates must use the same input unit")
            if unit not in input_by_unit and input_hash in input_by_unit.values():
                raise ValidationError("Renamed input is not an independent experimental unit")
            input_by_unit[unit] = input_hash
            if record["status"] not in ("observed", "failed", "unknown"):
                raise ValidationError("Unknown observation status")
            value = record["utility"]
            if record["status"] == "unknown":
                if value is not None:
                    raise ValidationError("Unknown result cannot carry an imputed score")
                local.append("UNKNOWN_OUTCOME:" + unit + ":" + record["candidate_id"])
            else:
                _number(value, 0, 1)
                if record["status"] == "failed" and value != 0:
                    raise ValidationError("Failed executions retain zero utility under this frozen contract")
            _integer(record["runs_started"], 0, protocol["runs_per_unit"])
            if record["status"] == "observed" and record["runs_started"] != protocol["runs_per_unit"]:
                local.append("INCOMPLETE_UNIT_RUNS:" + unit)
            reported_runs += record["runs_started"]
            cost = record["cost_micros"]
            if cost is None:
                costs_complete = False
                block_cost += caps[record["candidate_id"]]
                local.append("UNKNOWN_COST:" + unit + ":" + record["candidate_id"])
            else:
                _integer(cost, 0, 10**15)
                block_cost += cost
                if cost > caps[record["candidate_id"]]:
                    local.append("UNIT_COST_OVERRUN:" + unit + ":" + record["candidate_id"])
        missing = expected_cells - cells
        if missing:
            costs_complete = False
            local.append("MISSING_PLANNED_OBSERVATIONS")
            block_cost += sum(caps[i] for i, _ in missing)
        spent += block_cost
        old_inputs.update(input_by_unit.values())
        seen_units.update(input_by_unit)
        failed += sum(r["status"] == "failed" for r in records)
        completed += sum(r["status"] in ("observed", "failed") for r in records)
        observations.append({"index": index, "planned": len(expected_cells), "received": len(records),
                             "missing": len(missing), "spent_or_reserved_micros": block_cost, "issues": local})
        if local:
            issues.extend(local)
            blocker = "REPAIR_EVIDENCE"
            continue
        for record in records:
            row = stats[record["candidate_id"]]
            row["n"] += 1
            row["sum"] += record["utility"]
    state, chosen, rows, plan = _next(protocol, stats, digest, history_hash, len(batches) + 1, blocks, spent, started)
    if blocker:
        state, chosen, plan = blocker, None, None
    if violations:
        state, chosen, plan = "REVIEW_SAMPLING_ASSUMPTIONS", None, None
    synthetic = protocol["evidence_type"] == "synthetic"
    return {"format": FORMAT, "state": state, "protocol_sha256": digest, "risk_identity": risk_identity(protocol),
            "history_sha256": history_hash, "evidence_status": "SIMULATION_ONLY" if synthetic else "SUBMITTED_OBSERVATIONS" if observations else "NO_OBSERVATIONS",
            "intervals": rows, "next_block": plan, "certified_candidate_id": chosen,
            "candidate_for_confirmation": chosen if not synthetic else None, "selected_plan_sha256": None,
            "decision_contract": {k: protocol[k] for k in ("objective", "alpha", "epsilon", "quality_floor", "max_units_per_candidate")},
            "statistical_guarantee": {"status": "CONDITIONAL_FINITE_HORIZON" if assumptions and not violations else "UNAVAILABLE",
                "family_error_upper_bound": protocol["alpha"] if assumptions and not violations else None, "assumptions_verified": False,
                "scope": "Probability of any issued epsilon-inferior/below-floor candidate or false no-acceptable declaration; not conditional error among issued decisions",
                "method": BOUND},
            "candidate_units_started": started, "candidate_units_received": sum(o["received"] for o in observations),
            "candidate_units_resolved": completed,
            "independent_input_blocks_started": blocks, "planned_runs_started": started * protocol["runs_per_unit"],
            "reported_runs_started": reported_runs, "failed_units": failed, "observations": observations, "issues": issues,
            "budget": {"limit_micros": protocol["budget_micros"], "spent_or_reserved_micros": spent,
                       "total_cost_micros": spent if costs_complete else None},
            "allocation": protocol["allocation"], "efficiency_gain_established": False, "assumption_violations": violations,
            "utility_evidence_basis": "SUBMITTED_UTILITY_WITH_HASH_BINDINGS_NOT_INDEPENDENTLY_REGRADED",
            "automatic_execution": False, "execution_authorized": False,
            "limits": ["Same risk ceiling does not mean identical actual error probabilities or equally useful decisions.",
                "Independent units, stable target population, bounded utility and predictable assignments are declarations, not authenticated facts.",
                "Reported utility and source hashes do not independently establish scientific correctness.",
                "Within-task repeats are aggregated in one unit; no experimental-unit or population expansion is inferred.",
                "Budget/horizon stops without a certificate are abstentions, not successful efficient decisions.",
                "Statistical candidates still require full-stage/integration confirmation and existing scientific gates.",
                "No global plugin ranking, catalog-wide minimum, optimal allocation or real-world savings claim."]}


def plan_risk_acquisition(selection, request, *, artifact_root=None, verifier_root=None):
    base = select_task_plan(selection, artifact_root=artifact_root, verifier_root=verifier_root)
    result = analyze(request)
    protocol = request["protocol"]
    if selection["studies"] or protocol["catalog_sha256"] != base["catalog_sha256"] or protocol["task_sha256"] != suite_digest(selection["task"]):
        raise ValidationError("Freeze a prospective risk study against the exact task and catalog; do not retrofit past studies")
    plans = {p["plan_sha256"]: p for p in base["plans"]}
    for candidate in protocol["candidates"]:
        if candidate["plan_sha256"] not in plans:
            raise ValidationError("Risk candidate must bind a complete catalog plan")
    baseline = next(c for c in protocol["candidates"] if c["id"] == protocol["baseline_id"])
    if any(c["kind"] == "plugin" for c in plans[baseline["plan_sha256"]]["manifest"]["components"]):
        raise ValidationError("Retain the non-plugin baseline, not a relabeled treatment")
    if base["baseline_coverage_gaps"] or any(plans[c["plan_sha256"]]["applicability_blockers"] or
            plans[c["plan_sha256"]]["status"] == "INAPPLICABLE" for c in protocol["candidates"]):
        result.update(state="REVIEW_TASK_APPLICABILITY", next_block=None, certified_candidate_id=None, candidate_for_confirmation=None)
    result.update(candidate_plans=[{"id": c["id"], "plan_sha256": c["plan_sha256"],
                                   "manifest": deepcopy(plans[c["plan_sha256"]]["manifest"])} for c in protocol["candidates"]],
                  required_reviews=base["required_reviews"])
    return result
