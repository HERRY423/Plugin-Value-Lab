"""Deterministic paired evaluation. No model calls.

Default object-only evaluation performs no file I/O. Explicit artifact/verifier
roots opt into local file inspection and reviewed executable verification.

A hash binds bytes, not authenticity. All decisions here are descriptive and
conditional on the submitted protocol, observations and declared costs.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from . import __version__

FILE_GRADERS = {"pseudobulk_chain", "artifact", "executable", "artifact_schema", "numeric_tolerance",
                "abstention_correct", "over_refusal", "backend_identity", "exec", "replicate_effect"}


class ValidationError(ValueError):
    """The input does not satisfy the evaluation contract."""


def _constant(value):
    raise ValidationError(f"Non-finite JSON number: {value}")


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValidationError(f"Duplicate JSON key: {key}")
        obj[key] = value
    return obj


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                          parse_constant=_constant, object_pairs_hook=_unique_object)
    except (ValueError, OSError) as exc:
        raise ValidationError(f"Cannot read JSON {path}: {exc}") from exc


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def load_records(path):
    records = []
    try:
        for line_number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.strip():
                record = json.loads(line, parse_constant=_constant, object_pairs_hook=_unique_object)
                if not isinstance(record, dict):
                    raise ValidationError("Record must be an object")
                records.append(record)
    except (OSError, ValueError) as exc:
        raise ValidationError(f"Cannot read records (line {locals().get('line_number', '?')}): {exc}") from exc
    return records


def suite_digest(suite):
    data = json.dumps(suite, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _number(value, name, low=0, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValidationError(f"{name} must be a finite number")
    if value < low or (high is not None and value > high):
        raise ValidationError(f"{name} is out of range")
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a nonempty string")
    return value


def _identifier(value, name):
    _text(value, name)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}", value):
        raise ValidationError(f"{name} must be a safe identifier")


def validate_suite(suite):
    if not isinstance(suite, dict) or type(suite.get("schema_version")) is not int or suite["schema_version"] != 1:
        raise ValidationError("suite.schema_version must be 1")
    _identifier(suite.get("id"), "suite.id")
    plugin = suite.get("plugin")
    if not isinstance(plugin, dict):
        raise ValidationError("plugin must be an object")
    _text(plugin.get("name"), "plugin.name")
    _text(plugin.get("version"), "plugin.version")
    if suite.get("evidence_type") not in ("synthetic", "local", "external"):
        raise ValidationError("evidence_type must be synthetic, local, or external")
    n = suite.get("runs_per_case")
    if type(n) is not int or not 1 <= n <= 50:
        raise ValidationError("runs_per_case must be an integer in 1..50")
    conditions = suite.get("conditions")
    if not isinstance(conditions, dict):
        raise ValidationError("conditions must be an object")
    for key in ("model", "host", "environment"):
        _text(conditions.get(key), f"conditions.{key}")
    if not isinstance(conditions.get("tools"), list) or any(not isinstance(x, str) or not x.strip() for x in conditions["tools"]):
        raise ValidationError("conditions.tools must be a list of tool names")
    if not isinstance(conditions.get("budget"), dict) or not conditions["budget"]:
        raise ValidationError("conditions.budget must explicitly describe resource limits")
    policy = suite.get("policy")
    if not isinstance(policy, dict):
        raise ValidationError("policy must be an object")
    _number(policy.get("min_quality_delta"), "min_quality_delta", 0, 1)
    _number(policy.get("quality_floor"), "quality_floor", 0, 1)
    _number(policy.get("max_case_regression"), "max_case_regression", 0, 1)
    _number(policy.get("human_hourly_usd"), "human_hourly_usd")
    if policy.get("objective", "quality") not in ("quality", "efficiency"):
        raise ValidationError("policy.objective must be quality or efficiency")
    if type(policy.get("require_cost_saving")) is not bool:
        raise ValidationError("require_cost_saving must be boolean")
    if "require_cost_categories" in policy and type(policy["require_cost_categories"]) is not bool:
        raise ValidationError("require_cost_categories must be boolean")
    if type(policy.get("min_clusters")) is not int or policy["min_clusters"] < 2:
        raise ValidationError("min_clusters must be an integer >= 2")
    from .value_metrics import validate_power_plan
    validate_power_plan(policy)
    from .interpretation import validate_policy
    validate_policy(policy)
    from .guidance import validate_decision_policy
    validate_decision_policy(policy)
    from .methodology import validate_limits
    validate_limits(policy)
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValidationError("cases must be a nonempty list")
    ids = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValidationError("case must be an object")
        _identifier(case.get("id"), "case.id")
        if case["id"] in ids:
            raise ValidationError(f"Duplicate case: {case['id']}")
        ids.add(case["id"])
        _text(case.get("cluster"), "case.cluster")
        _text(case.get("prompt"), "case.prompt")
        if case.get("kind") not in ("task", "negative", "abstention"):
            raise ValidationError("case.kind must be task, negative, or abstention")
        graders = case.get("graders")
        if not isinstance(graders, list) or not graders:
            raise ValidationError("Every case needs graders")
        grade_ids = set()
        for g in graders:
            if not isinstance(g, dict):
                raise ValidationError("grader must be an object")
            _identifier(g.get("id"), "grader.id")
            if g["id"] in grade_ids:
                raise ValidationError("Duplicate grader id")
            grade_ids.add(g["id"])
            if g.get("dimension") not in ("outcome", "process"):
                raise ValidationError("grader.dimension must be outcome or process")
            if g.get("type") not in FILE_GRADERS | {"contains", "not_contains", "json_equals", "human", "sealed", "scenario"}:
                raise ValidationError("Unsupported grader type")
            if g["type"] == "scenario":
                from .scenarios import validate_scenario_grader
                validate_scenario_grader(g)
                if g["verifier"]["case_id"] != case["id"]:
                    raise ValidationError("Scenario grader must bind its case")
            if g["type"] == "sealed":
                from .corpus import validate_grader
                validate_grader(g)
                if (g["verifier"]["case_id"] != case["id"] or
                        suite.get("corpus") != {k: g["verifier"][k] for k in ("release_sha256", "truth_sha256")}):
                    raise ValidationError("Sealed grader must bind its case and suite corpus")
            if g["type"] in FILE_GRADERS:
                from .artifacts import validate_verifier
                validate_verifier(g)
            if g["type"] in ("contains", "not_contains"):
                _text(g.get("value"), "grader.value")
            if g["type"] == "json_equals":
                _text(g.get("path"), "grader.path")
                if "value" not in g:
                    raise ValidationError("json_equals requires value")
            if g["type"] == "human":
                _text(g.get("rubric"), "grader.rubric")
            if _number(g.get("weight"), "grader.weight") <= 0:
                raise ValidationError("grader.weight must be positive")
            if type(g.get("critical")) is not bool:
                raise ValidationError("grader.critical must be boolean")
        if not any(g["dimension"] == "outcome" for g in graders):
            raise ValidationError("Every case needs an outcome grader; activation alone is not value")
        from .scoring import validate_rules
        validate_rules(case)
    return suite


def freeze(suite, path):
    validate_suite(suite)
    lock = {"schema_version": 1, "suite_sha256": suite_digest(suite),
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "expected_runs": len(suite["cases"]) * suite["runs_per_case"] * 2,
            "attestation": "LOCAL_CONSISTENCY_ONLY"}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(lock, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise ValidationError("Lock already exists; create a new study revision rather than overwriting") from exc
    return lock


def _stamp(value):
    _text(value, "interval timestamp")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValidationError("Human timer timestamps must include a timezone")
    return stamp.astimezone(timezone.utc)


def _grade(g, record):
    """Return pass/fail/unknown plus rationale; imported grades never imply human review."""
    kind = g["type"]
    if kind in FILE_GRADERS | {"sealed", "scenario"}:
        return None, "Artifact verification requires an explicit local evidence root"
    if kind == "human":
        review = record.get("reviews", {}).get(g["id"], {})
        if (type(review.get("passed")) is bool and
                isinstance(review.get("reviewer"), str) and review["reviewer"].strip() and
                isinstance(review.get("rationale"), str) and review["rationale"].strip()):
            return review["passed"], review["rationale"]
        return None, "Human review missing, disputed, or incomplete"
    output = record.get("output")
    if not isinstance(output, str):
        grade = record.get("grades", {}).get(g["id"], {})
        if type(grade.get("passed")) is bool:
            return grade["passed"], grade.get("rationale", "Imported grader result; output unavailable")
        return None, "Output or mapped grader result unavailable"
    if kind == "contains":
        return g["value"] in output, "Literal content check (not semantic truth verification)"
    if kind == "not_contains":
        return g["value"] not in output, "Literal absence check (not semantic truth verification)"
    try:
        obj = json.loads(output, parse_constant=_constant, object_pairs_hook=_unique_object)
        for key in g["path"].split("."):
            obj = obj[int(key)] if isinstance(obj, list) else obj[key]
        # Python considers True == 1; JSON booleans and numbers must remain distinct.
        return suite_digest(obj) == suite_digest(g["value"]), "Exact typed JSON field check"
    except (ValueError, TypeError, KeyError, IndexError):
        return False, "Invalid JSON or absent field"


def _bootstrap(cases, seed=20260922):
    groups = defaultdict(list)
    for case in cases:
        if case["delta"] is None:
            return {"status": "UNAVAILABLE", "reason": "Incomplete or non-comparable cases"}
        groups[case["cluster"]].append(case["delta"])
    if len(groups) < 2:
        return {"status": "UNAVAILABLE", "reason": "Fewer than two independent task-family labels"}
    # Resample whole families, retaining all their cases. Repetitions are not
    # treated as independent tasks. Labels do not verify actual independence.
    clusters = list(groups.values())
    rng = random.Random(seed)
    draws = sorted(mean([v for group in rng.choices(clusters, k=len(clusters)) for v in group])
                   for _ in range(2000))
    return {"status": "DESCRIPTIVE_ONLY", "method": "task-family cluster bootstrap, percentile 95%",
            "low": draws[49], "high": draws[1949], "resamples": 2000, "seed": seed,
            "clusters": len(clusters),
            "caution": "Exploratory interval, unstable with few families; family independence is declared, not verified. No causal test."}


def evaluate(suite, records, lock=None, cost_ledger=None, *, artifact_root=None, verifier_root=None, corpus_root=None):
    validate_suite(suite)
    if not isinstance(records, list) or any(not isinstance(x, dict) for x in records):
        raise ValidationError("records must be a list of objects")
    digest = suite_digest(suite)
    blockers, warnings = [], []
    corpus_errors = None
    corpus_material = None
    if suite.get("corpus") is not None:
        if corpus_root is None:
            blockers.append("Sealed corpus answer key not supplied")
        else:
            from .corpus import error_rates, load_material
            try:
                corpus_material = load_material(corpus_root)
                corpus_errors = error_rates(suite, records, corpus_root, corpus_material)
            except (ValidationError, OSError) as exc:
                blockers.append(f"Corpus binding failed: {exc}")
    from .costs import allocation, analyze_costs
    cost_plan = allocation(suite, cost_ledger)
    blockers.extend(cost_plan["issues"])
    cost_required = (suite["policy"].get("require_cost_categories") or
                     suite["policy"]["require_cost_saving"] or
                     suite["policy"].get("objective") == "efficiency")
    if cost_required and not cost_plan["coverage_complete"]:
        blockers.append("Cost-dependent verdict requires explicit judge/setup/retry/other cost coverage")
    if not isinstance(lock, dict) or lock.get("suite_sha256") != digest:
        blockers.append("Protocol lock absent or changed: freeze and retain the exact suite before observation")
    expected = {(c["id"], rep, arm) for c in suite["cases"]
                for rep in range(1, suite["runs_per_case"] + 1) for arm in ("with", "without")}
    indexed = {}
    sessions = set()
    all_intervals = defaultdict(list)
    synthetic = suite["evidence_type"] == "synthetic" or any(
        g["type"] == "scenario" and g["verifier"]["evidence_type"] == "synthetic"
        for c in suite["cases"] for g in c["graders"])
    for index, record in enumerate(records):
        case_id, repetition, arm = record.get("case_id"), record.get("repetition"), record.get("arm")
        if not isinstance(case_id, str) or type(repetition) is not int or not isinstance(arm, str):
            blockers.append(f"Malformed execution key at record {index + 1}")
            continue
        key = (case_id, repetition, arm)
        if key not in expected:
            blockers.append(f"Unexpected execution {key}; original plan is unchanged")
            continue
        if key in indexed:
            blockers.append(f"Duplicate execution {key}; repeated attempts cannot replace a failed planned run")
            if "value_interpretation" in suite["policy"]:
                indexed[key]["observation_issues"].append("Duplicate execution identity; ambiguous observation")
            continue
        issues = []
        if record.get("source") == "synthetic":
            synthetic = True
        if record.get("source") not in ("synthetic", "manual", "claude", "codex"):
            issues.append("Source unknown")
        if record.get("suite_sha256") != digest:
            issues.append("Suite digest mismatch or missing")
        if suite_digest(record.get("conditions")) != suite_digest(suite["conditions"]):
            issues.append("Observed model, host, tools, environment or budget does not match protocol")
        if record.get("plugin_loaded") is not (arm == "with"):
            issues.append("Plugin load state missing or contaminated baseline")
        sid = record.get("session_id")
        if not isinstance(sid, str) or not sid.strip() or sid in sessions:
            issues.append("Missing or reused session identity")
        else:
            sessions.add(sid)
        status = record.get("status")
        if status not in ("completed", "error", "timeout", "aborted", "skipped"):
            issues.append("Unknown execution status")
        if record.get("error") and status == "completed":
            issues.append("Completed status contradicts recorded error")
        if status == "completed" and not isinstance(record.get("output"), str):
            issues.append("Original output unavailable; imported Boolean grades remain diagnostic only")
        if status in ("error", "aborted") and record.get("failure_kind") != "task":
            issues.append("Failure is infrastructure-related or unclassified; do not attribute it to plugin value")
        imported_issues = record.get("import_issues", [])
        if not isinstance(imported_issues, list) or any(not isinstance(i, str) for i in imported_issues):
            issues.append("Malformed import issues")
        else:
            issues.extend(imported_issues)
        observation_issues = [i for i in issues if i != "Failure is infrastructure-related or unclassified; do not attribute it to plugin value"]
        if "value_interpretation" in suite["policy"]:
            from .interpretation import validate_failure
            validate_failure(record)
        for mapping in ("reviews", "grades"):
            if not isinstance(record.get(mapping, {}), dict) or any(not isinstance(x, dict) for x in record.get(mapping, {}).values()):
                raise ValidationError(f"{mapping} must map grader IDs to objects")
        cost = record.get("cost", {})
        if not isinstance(cost, dict):
            cost = {}
        if cost.get("basis", "declared") not in ("estimate", "settled", "declared"):
            issues.append("Cost basis must be estimate, settled or declared")
        costs = []
        for field in ("model_usd", "tool_usd", "human_minutes"):
            try:
                costs.append(_number(cost.get(field), f"cost.{field}"))
            except ValidationError:
                costs.append(None)
                issues.append(f"Cost {field} missing or invalid; it is not zero")
        duration = record.get("duration_seconds")
        if duration is not None:
            try:
                _number(duration, "duration_seconds")
            except ValidationError:
                issues.append("Invalid machine duration")
        intervals = record.get("human_intervals")
        if not isinstance(intervals, list):
            issues.append("Raw human time intervals unavailable")
        else:
            minutes = 0.0
            for interval in intervals:
                try:
                    if not isinstance(interval, dict):
                        raise ValidationError("Timer interval must be an object")
                    actor = _text(interval.get("actor"), "actor")
                    start, end = _stamp(interval.get("start")), _stamp(interval.get("end"))
                    if end < start:
                        raise ValidationError("Timer ends before it starts")
                    minutes += (end - start).total_seconds() / 60
                    all_intervals[actor].append((start, end, key))
                except (ValueError, TypeError) as exc:
                    issues.append(f"Invalid human timer: {exc}")
            if costs[2] is not None and not math.isclose(minutes, costs[2], abs_tol=1e-6):
                issues.append("Human minutes do not reconcile to raw intervals")
        total_cost = None if None in costs else costs[0] + costs[1] + costs[2] * suite["policy"]["human_hourly_usd"] / 60
        extra_cost = cost_plan["extras"][key]
        total_cost = total_cost + extra_cost if total_cost is not None and extra_cost is not None else None
        if extra_cost is None:
            issues.append("Additional allocated cost unknown")
        # Failures are retained with quality zero for operational effectiveness;
        # missing/skipped measurements block complete comparison.
        if status == "skipped":
            issues.append("Execution was skipped")
        indexed[key] = {"record": record, "issues": issues, "cost_usd": total_cost,
                        "observation_issues": observation_issues}
    for actor, intervals in all_intervals.items():
        intervals.sort(key=lambda item: item[0])
        latest_end = None
        latest_key = None
        for start, end, key in intervals:
            if latest_end is not None and start < latest_end:
                blockers.append(f"Overlapping human intervals for {actor}: {latest_key} / {key}")
            if latest_end is None or end > latest_end:
                latest_end, latest_key = end, key
    missing = sorted(expected - indexed.keys())
    if missing:
        blockers.append(f"Missing {len(missing)} planned executions; denominator remains {len(expected)}")
    cases_out, complete_pairs, critical_failures = [], 0, []
    total_costs = {"with": [], "without": []}
    for case in suite["cases"]:
        arm_scores = {"with": [], "without": []}
        rows = []
        for rep in range(1, suite["runs_per_case"] + 1):
            comparable_pair = True
            for arm in ("with", "without"):
                key = (case["id"], rep, arm)
                item = indexed.get(key)
                if item is None:
                    rows.append({"arm": arm, "repetition": rep, "status": "missing", "score": None,
                                 "grades": [], "cost_usd": None, "issues": ["Planned execution missing"]})
                    arm_scores[arm].append(None)
                    total_costs[arm].append(None)
                    comparable_pair = False
                    continue
                record, issues = item["record"], list(item["issues"])
                grades = []
                earned = total_weight = 0.0
                unresolved = False
                for g in case["graders"]:
                    verification = None
                    if g["type"] == "sealed":
                        from .corpus import grade_sealed
                        passed, rationale, verification = grade_sealed(g, record, corpus_root, corpus_material)
                        if verification.get("corpus_evidence_type") == "synthetic":
                            synthetic = True
                    elif g["type"] == "scenario":
                        from .scenarios import grade_scenario
                        passed, rationale, verification = grade_scenario(g, record, artifact_root, verifier_root)
                    elif g["type"] in FILE_GRADERS:
                        from .artifacts import grade_artifact
                        passed, rationale, verification = grade_artifact(g, record, artifact_root, verifier_root)
                    else:
                        passed, rationale = _grade(g, record)
                    scored = g["dimension"] == "outcome"
                    if not scored and g["critical"] and passed is not True:
                        issues.append(f"Critical verification {g['id']} failed or is unresolved")
                    grades.append({"id": g["id"], "passed": passed, "rationale": rationale,
                                   "scored": scored, "critical": g["critical"], "weight": g["weight"]})
                    if verification is not None:
                        grades[-1]["verification"] = verification
                    if scored:
                        total_weight += g["weight"]
                        if passed is None and record.get("status") == "completed":
                            unresolved = True
                        if passed is True:
                            earned += g["weight"]
                        if g["critical"] and passed is False and arm == "with":
                            critical_failures.append(f"{case['id']}/{rep}/{g['id']}")
                status = record.get("status", "unknown")
                if unresolved:
                    issues.append("Outcome review unresolved")
                if status in ("error", "timeout", "aborted"):
                    score = 0.0
                    warnings.append(f"{key}: {status} retained as operational failure with score zero")
                elif status != "completed" or unresolved:
                    score = None
                else:
                    score = earned / total_weight
                if issues:
                    blockers.extend(f"{case['id']}/{rep}/{arm}: {issue}" for issue in issues)
                    comparable_pair = False
                if score is None:
                    comparable_pair = False
                arm_scores[arm].append(score)
                total_costs[arm].append(item["cost_usd"])
                rows.append({"arm": arm, "repetition": rep, "status": status, "score": score,
                             "grades": grades, "cost_usd": item["cost_usd"], "issues": issues,
                             "duration_seconds": record.get("duration_seconds"), "error": record.get("error")})
                if "value_interpretation" in suite["policy"]:
                    rows[-1].update(observation_issues=item["observation_issues"],
                                    failure_observation=record.get("failure_observation"))
            complete_pairs += int(comparable_pair)
        def full_mean(values):
            return None if not values or None in values else mean(values)
        with_score, without_score = full_mean(arm_scores["with"]), full_mean(arm_scores["without"])
        delta = None if with_score is None or without_score is None else with_score - without_score
        cases_out.append({"id": case["id"], "kind": case["kind"], "cluster": case["cluster"],
                          "with_score": with_score, "without_score": without_score, "delta": delta, "runs": rows})
    with_score = full_mean([c["with_score"] for c in cases_out])
    without_score = full_mean([c["without_score"] for c in cases_out])
    quality_delta = None if with_score is None or without_score is None else with_score - without_score
    with_cost = full_mean(total_costs["with"])
    without_cost = full_mean(total_costs["without"])
    cost_delta = None if with_cost is None or without_cost is None else with_cost - without_cost
    clusters = len(set(c["cluster"] for c in cases_out))
    policy = suite["policy"]
    scientific_errors = None
    if any(g["type"] in ("scenario", "abstention_correct", "over_refusal") for c in suite["cases"] for g in c["graders"]):
        from .scenarios import decision_metrics
        scientific_errors = decision_metrics(suite, records, verifier_root, artifact_root)
    from .methodology import assess_limits
    methodology = assess_limits(policy, {"corpus": corpus_errors, "scientific": scientific_errors})
    blockers.extend(methodology["blockers"])
    cost_analysis = analyze_costs(suite, records, cost_ledger, {
        "cases": cases_out, "summary": {"comparison_eligible": False},
        "evidence_type": "synthetic" if synthetic else suite["evidence_type"]})
    blockers.extend(cost_analysis["issues"])
    if policy.get("require_settled_costs") and (not cost_analysis["complete_category_coverage"] or
                                               not cost_analysis["cash_evidence"]["settlement_references_complete"]):
        blockers.append("Settled-cost policy requires complete categories and unique settlement references; estimates cannot pass")
    if clusters < policy["min_clusters"]:
        blockers.append(f"Only {clusters} task families; protocol requires {policy['min_clusters']}")
    if not any(c["kind"] == "negative" for c in suite["cases"]):
        warnings.append("No negative-control case: over-triggering has not been assessed")
    if not any(c["kind"] == "abstention" for c in suite["cases"]):
        warnings.append("No abstention case: appropriate refusal has not been assessed")
    blockers = list(dict.fromkeys(blockers))
    regression = any(c["delta"] is not None and c["delta"] < -policy["max_case_regression"] - 1e-12 for c in cases_out)
    objective = policy.get("objective", "quality")
    if objective == "efficiency":
        quality_ok = quality_delta is not None and quality_delta >= -1e-12 and with_score + 1e-12 >= policy["quality_floor"]
    else:
        quality_ok = quality_delta is not None and quality_delta > 1e-12 and quality_delta + 1e-12 >= policy["min_quality_delta"] and with_score + 1e-12 >= policy["quality_floor"]
    cost_ok = cost_delta is not None and (not (policy["require_cost_saving"] or objective == "efficiency") or cost_delta < -1e-12)
    if blockers:
        verdict = "INSUFFICIENT_EVIDENCE"
    elif critical_failures or regression or methodology["violations"]:
        verdict = "REGRESSION_DETECTED"
    elif quality_ok and cost_ok:
        verdict = "PROMISING_LOCAL_SIGNAL"
    else:
        verdict = "NO_DEMONSTRATED_GAIN"
    measured_verdict = verdict
    cost_analysis["saving_claim_eligible"] = (not blockers and not synthetic and cost_analysis["complete_category_coverage"])
    cost_analysis["settled_saving_claim_eligible"] = (cost_analysis["saving_claim_eligible"] and
        cost_analysis["cash_evidence"]["settlement_references_complete"] and cost_delta is not None and cost_delta < -1e-12)
    cost_analysis["saving_claim_basis"] = ("SETTLEMENT_REFERENCED_CASH_PLUS_TIMER_VALUED_LABOR"
        if cost_analysis["cash_evidence"]["settlement_references_complete"] else "CONDITIONAL_ON_SUBMITTED_ESTIMATES_OR_DECLARATIONS")
    if synthetic:
        verdict = "SIMULATION_ONLY"
    if suite["evidence_type"] == "external":
        warnings.append("External provenance is user-declared; this software cannot authenticate independent participants or real-world benefit")
    warnings.append("Costs must include retries, model judges, setup, correction and review allocated consistently; omitted categories cannot be inferred")
    if not cost_analysis["complete_category_coverage"]:
        warnings.append("Detailed cost category coverage is incomplete; legacy mean costs are recorded amounts, not verified full expenditure")
    if not cost_analysis["cash_evidence"]["settlement_references_complete"]:
        warnings.append("Cost savings are conditional on submitted estimates/declarations; settled savings are not established")
    report = {
        "schema_version": 1, "study_id": suite["id"], "plugin": suite["plugin"],
        "evidence_type": "synthetic" if synthetic else suite["evidence_type"], "verdict": verdict,
        "measured_verdict": measured_verdict,
        "summary": {"with_score": with_score, "without_score": without_score,
                    "quality_delta": quality_delta, "expected_runs": len(expected),
                    "observed_runs": len(indexed), "submitted_records": len(records),
                    "complete_pairs": complete_pairs, "clusters": clusters,
                    "cost_delta_usd": cost_delta, "with_cost_usd": with_cost, "without_cost_usd": without_cost,
                    "cost_unit": "mean per planned arm execution; positive delta costs more",
                    "quality_gate_met": quality_ok, "cost_gate_met": cost_ok,
                    "objective": objective,
                    "critical_failures": critical_failures, "comparison_eligible": not blockers},
        "policy": policy, "blockers": blockers, "warnings": warnings, "cases": cases_out,
        "cost_analysis": cost_analysis, "methodology": methodology,
        "uncertainty": _bootstrap(cases_out) if not blockers else {"status": "UNAVAILABLE", "reason": "Incomplete or confounded evidence"},
        "claim_limits": {"causal_benefit": "NOT_ESTABLISHED", "external_validation": "NOT_ESTABLISHED",
                         "scientific_authorization": "NONE", "independence": "DECLARED_NOT_VERIFIED",
                         "decision_scope": "Descriptive within the frozen submitted task suite only",
                         "human_time": "Declared timer records; authenticity not independently verified",
                         "costs": "Submitted USD values; estimates are not settled charges"},
        "provenance": {"suite_sha256": digest, "records_sha256": suite_digest(records), "cost_ledger_sha256": suite_digest(cost_ledger) if cost_ledger is not None else None,
                       "engine": f"plugin-value-lab/{__version__}", "local_lock": lock,
                       "hash_scope": "Byte consistency only; no proof of execution, authorship, or preregistration time"}}
    if suite.get("corpus") is not None:
        report["corpus_errors"] = corpus_errors
    if scientific_errors is not None:
        report["scientific_errors"] = scientific_errors
    from .value_metrics import build_value_metrics
    report["value_metrics"] = build_value_metrics(suite, report)
    if "value_interpretation" in policy:
        from .interpretation import build_interpretation
        report["value_interpretation"] = build_interpretation(suite, report)
    return report


def demo_suite():
    def grader(gid, value, kind="contains", critical=False, dimension="outcome"):
        return {"id": gid, "type": kind, "value": value, "weight": 1,
                "critical": critical, "dimension": dimension}
    return {"schema_version": 1, "id": "tutorial-value-study", "plugin": {"name": "example-plugin", "version": "0.0.0-demo"},
            "evidence_type": "synthetic", "runs_per_case": 3,
            "conditions": {"model": "SIMULATED-NO-MODEL", "host": "offline-tutorial", "tools": [],
                           "environment": "synthetic-fixture-v1", "budget": {"max_turns": 10}},
            "policy": {"min_quality_delta": 0.1, "quality_floor": 0.8, "max_case_regression": 0,
                       "min_clusters": 3, "require_cost_saving": False, "human_hourly_usd": 60},
            "cases": [
                {"id": "structured-delivery", "cluster": "delivery", "kind": "task",
                 "prompt": "Deliver a task result with a source reference and explicit limitations.",
                 "graders": [grader("source", "SOURCE:"), grader("limits", "LIMITS:")]},
                {"id": "unrelated-request", "cluster": "negative-control", "kind": "negative",
                 "prompt": "What is 2 + 2? Give only the number.",
                 "graders": [grader("answer", "4"), grader("over-trigger", "AUDIT:", "not_contains", True)]},
                {"id": "insufficient-science", "cluster": "evidence-boundary", "kind": "abstention",
                 "prompt": "Do passing local software tests prove clinical effectiveness? Explain the evidence limit.",
                 "graders": [grader("limit", "NOT_ESTABLISHED", critical=True),
                             grader("activation", "SKILL_USED", dimension="process")]}]}


def demo_records(suite):
    """Explicit fixtures, never a claim that any model or person did this work."""
    records = []
    digest = suite_digest(suite)
    for ci, case in enumerate(suite["cases"]):
        for rep in range(1, suite["runs_per_case"] + 1):
            for arm in ("with", "without"):
                output = {"structured-delivery": "SOURCE: example LIMITS: simulated",
                          "unrelated-request": "4", "insufficient-science": "NOT_ESTABLISHED SKILL_USED"}[case["id"]]
                if arm == "without" and case["id"] == "structured-delivery":
                    output = "SOURCE: example" if rep == 1 else "An answer without traceable support."
                if arm == "without" and case["id"] == "insufficient-science":
                    output = "NOT_ESTABLISHED" if rep == 1 else "Testing proves value."
                minutes = 1 if arm == "with" else 2
                hour = ci * 6 + (rep - 1) * 2 + (arm == "without")
                start = f"2026-01-01T{hour:02d}:00:00+00:00"
                end = f"2026-01-01T{hour:02d}:{minutes:02d}:00+00:00"
                records.append({"case_id": case["id"], "repetition": rep, "arm": arm,
                                "suite_sha256": digest, "session_id": f"SYNTHETIC-{ci}-{rep}-{arm}",
                                "conditions": suite["conditions"], "plugin_loaded": arm == "with",
                                "status": "completed", "output": output, "source": "synthetic",
                                "cost": {"model_usd": 0.02 if arm == "with" else 0.01,
                                         "tool_usd": 0, "human_minutes": minutes},
                                "human_intervals": [{"actor": "SYNTHETIC-NO-PERSON", "start": start, "end": end}],
                                "duration_seconds": 10 if arm == "with" else 8})
    return records
