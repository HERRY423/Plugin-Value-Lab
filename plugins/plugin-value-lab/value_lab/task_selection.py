"""Select a scoped task plan from recomputed paired evidence, never a plugin rank.

Catalog coverage, observed feasibility, composition and minimum size are separate
claims. Supplied identities and locks are bindings, not execution authentication.
"""
from copy import deepcopy
from itertools import product
import re

from .core import ValidationError, evaluate, suite_digest, validate_suite
from .scoring import run_success


FORMAT = "pvl-task-selection-1"
MAX_PLANS = 256
KINDS = {"native", "script", "workflow", "plugin"}


def _keys(obj, required, optional=()):
    if not isinstance(obj, dict) or set(obj) - set(required) - set(optional) or set(required) - set(obj):
        raise ValidationError("Task selection has missing or unexpected fields: " + ", ".join(required))


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", value):
        raise ValidationError("Task selection IDs must be safe, nonempty identifiers")
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise ValidationError("Task selection needs bounded nonempty text")
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValidationError("Task selection needs a SHA-256 content identity")


def _strings(values):
    if not isinstance(values, list) or len(values) > 50 or len(set(map(str, values))) != len(values):
        raise ValidationError("Expected a bounded unique list")
    for value in values:
        _text(value)


def _same(a, b):
    return suite_digest(a) == suite_digest(b)


def _validate(selection):
    _keys(selection, ("format", "task", "components", "options", "policy", "studies"))
    if selection["format"] != FORMAT:
        raise ValidationError("Unsupported task selection format")
    task = selection["task"]
    _keys(task, ("id", "summary", "facts", "inputs", "conditions", "stages", "cases", "integration_case_ids"))
    _id(task["id"])
    _text(task["summary"])
    for field in ("facts", "inputs"):
        if not isinstance(task[field], dict) or not task[field] or len(task[field]) > 50:
            raise ValidationError("Task facts and input snapshot hashes must be explicit")
        for key, value in task[field].items():
            _id(key)
            if field == "inputs":
                _sha(value)
            elif value is not None and type(value) not in (str, bool, int, float):
                raise ValidationError("Decision facts must be JSON scalars or null for unknown")
    conditions = task["conditions"]
    if not isinstance(conditions, dict):
        raise ValidationError("Explicit task conditions are required")
    for field in ("host_version", "model_version"):
        _text(conditions.get(field))
        if any(x in conditions[field].lower() for x in ("unknown", "unverified", "unspecified")):
            raise ValidationError("Task selection needs explicit host/model revisions")
    policy = selection["policy"]
    _keys(policy, ("objective", "max_new_plugins", "quality_floor"))
    if policy["objective"] != "fewest_new_plugins_then_total_plugins":
        raise ValidationError("Unsupported selection objective; cost is disclosed, never imputed or used as a hidden tie-break")
    if type(policy["max_new_plugins"]) is not int or not 0 <= policy["max_new_plugins"] <= 16:
        raise ValidationError("max_new_plugins must be an integer in 0..16")
    if type(policy["quality_floor"]) not in (int, float) or not 0 <= policy["quality_floor"] <= 1:
        raise ValidationError("Selection quality floor must be in 0..1")
    # Reuse the full existing case/rule/condition validator, without generating observations.
    probe = {"schema_version": 1, "id": task["id"], "plugin": {"name": "validation-only", "version": "0"},
             "evidence_type": "synthetic", "runs_per_case": 1, "conditions": conditions,
             "policy": {"min_quality_delta": 0.1, "quality_floor": policy["quality_floor"],
                        "max_case_regression": 0, "human_hourly_usd": 0, "require_cost_saving": False, "min_clusters": 2},
             "cases": task["cases"]}
    validate_suite(probe)
    case_ids = {c["id"] for c in task["cases"]}
    _strings(task["integration_case_ids"])
    assigned = list(task["integration_case_ids"])
    stages, seen = {}, set()
    if not isinstance(task["stages"], list) or not 1 <= len(task["stages"]) <= 8:
        raise ValidationError("Provide 1..8 ordered task stages")
    for stage in task["stages"]:
        _keys(stage, ("id", "summary", "depends_on", "decision_factors", "case_ids", "required_reviews"))
        sid = _id(stage["id"])
        _text(stage["summary"])
        for key in ("depends_on", "decision_factors", "case_ids", "required_reviews"):
            _strings(stage[key])
        if sid in seen or not set(stage["depends_on"]) <= seen:
            raise ValidationError("Stages must be unique and topologically ordered")
        if not stage["case_ids"] or not set(stage["decision_factors"]) <= set(task["facts"]):
            raise ValidationError("Every stage needs acceptance cases and declared decision factors")
        assigned.extend(stage["case_ids"])
        stages[sid] = stage
        seen.add(sid)
    if set(assigned) != case_ids or len(assigned) != len(set(assigned)):
        raise ValidationError("Every frozen case must belong to exactly one stage or integration check")
    if len(stages) > 1 and not task["integration_case_ids"]:
        raise ValidationError("Multi-stage plans require explicit end-to-end integration acceptance cases")
    components = {}
    if not isinstance(selection["components"], list) or not 1 <= len(selection["components"]) <= 16:
        raise ValidationError("Provide 1..16 candidate components")
    for component in selection["components"]:
        _keys(component, ("id", "name", "kind", "version", "sha256", "installed"), ("requires_components",))
        cid = _id(component["id"])
        if cid in components or not isinstance(component["kind"], str) or component["kind"] not in KINDS:
            raise ValidationError("Duplicate component or unsupported component kind")
        _text(component["name"])
        _text(component["version"])
        _sha(component["sha256"])
        if component["installed"] is not None and type(component["installed"]) is not bool:
            raise ValidationError("Installation must be true, false or unknown (null)")
        if component["kind"] != "plugin" and component["installed"] is not True:
            raise ValidationError("Native/script/workflow alternatives must describe existing capabilities")
        components[cid] = component
    complete, visiting = set(), set()
    def visit(cid):
        if cid in visiting:
            raise ValidationError("Component dependencies must not contain cycles")
        if cid in complete:
            return
        visiting.add(cid)
        dependencies = components[cid].get("requires_components", [])
        _strings(dependencies)
        for dependency in dependencies:
            _id(dependency)
            if dependency not in components:
                raise ValidationError("Every required component must be declared, including workflow plugin dependencies")
            visit(dependency)
        visiting.remove(cid)
        complete.add(cid)
    for cid in components:
        visit(cid)
    options = {}
    if not isinstance(selection["options"], list) or not 1 <= len(selection["options"]) <= 32:
        raise ValidationError("Provide 1..32 scoped capability options")
    for option in selection["options"]:
        _keys(option, ("id", "stage_id", "component_id", "capability", "requires", "required_reviews"))
        oid = _id(option["id"])
        _id(option["stage_id"])
        _id(option["component_id"])
        if oid in options or option["stage_id"] not in stages or option["component_id"] not in components:
            raise ValidationError("Options must have unique IDs and name declared stages/components")
        _text(option["capability"])
        _strings(option["required_reviews"])
        if not isinstance(option["requires"], dict) or set(option["requires"]) != set(stages[option["stage_id"]]["decision_factors"]):
            raise ValidationError("Each option must explicitly cover all of its stage's decision factors")
        for accepted in option["requires"].values():
            if (not isinstance(accepted, list) or not accepted or len(accepted) > 50
                    or any(type(v) not in (str, bool, int, float) for v in accepted)):
                raise ValidationError("Applicability uses explicit accepted scalar values; null is unknown, not a wildcard")
        options[oid] = option
    if not isinstance(selection["studies"], list) or len(selection["studies"]) > 32:
        raise ValidationError("At most 32 complete paired study bundles are supported")
    suite_digest(selection)  # Reject NaN and non-JSON values before reading any artifacts.
    return stages, components, options


def _manifest(choices, components):
    active = set()
    def include(cid):
        if cid in active:
            return
        active.add(cid)
        for dependency in components[cid].get("requires_components", []):
            include(dependency)
    for option in choices:
        include(option["component_id"])
    return {"steps": deepcopy(choices), "components": [
        {**{k: components[c][k] for k in ("id", "name", "kind", "version", "sha256")},
         "requires_components": sorted(components[c].get("requires_components", []))} for c in sorted(active)]}


def _catalog(selection, stages, components, options):
    groups = [[o for o in options.values() if o["stage_id"] == sid] for sid in stages]
    count = 1
    for group in groups:
        count *= len(group)
    if count > MAX_PLANS:
        raise ValidationError(f"Catalog exceeds {MAX_PLANS} plans; narrow the declared scope explicitly, never truncate search")
    rows = []
    for choices in product(*groups):
        manifest = _manifest(choices, components)
        plugins = [c for c in manifest["components"] if c["kind"] == "plugin"]
        new = [c["id"] for c in plugins if components[c["id"]]["installed"] is False]
        unknown_install = [c["id"] for c in plugins if components[c["id"]]["installed"] is None]
        mismatches, unknowns = [], []
        for option in choices:
            for key, values in option["requires"].items():
                actual = selection["task"]["facts"][key]
                if actual is None:
                    unknowns.append(f"{option['id']}: task fact {key} is unknown")
                elif not any(_same(actual, value) for value in values):
                    mismatches.append(f"{option['id']}: task fact {key} does not meet declared applicability")
        if len(new) > selection["policy"]["max_new_plugins"]:
            mismatches.append("Declared maximum number of new plugins exceeded")
        unknowns.extend(f"Installation unknown: {cid}" for cid in unknown_install)
        rows.append({"plan_sha256": suite_digest(manifest), "manifest": manifest,
                     "size": [len(new), len(plugins)], "size_is_lower_bound": bool(unknown_install),
                     "new_plugins": new, "status": "INAPPLICABLE" if mismatches else "UNKNOWN",
                     "applicability_blockers": mismatches + unknowns, "observations": [],
                     "required_reviews": sorted({r for o in choices for r in o["required_reviews"]}
                                                | {r for s in stages.values() for r in s["required_reviews"]})})
    return rows


def _assess_studies(selection, catalog, artifact_root, verifier_root):
    task = selection["task"]
    plans = {p["plan_sha256"]: p for p in catalog}
    catalog_digest = suite_digest({k: v for k, v in selection.items() if k != "studies"})
    studies, seen, sessions = [], set(), {}
    # Reused sessions across studies cannot manufacture independent alternative evidence.
    for index, bundle in enumerate(selection["studies"]):
        _keys(bundle, ("suite", "records", "lock"), ("cost_ledger",))
        if not isinstance(bundle["records"], list) or any(not isinstance(r, dict) for r in bundle["records"]):
            raise ValidationError("Study records must be original run objects")
        for record in bundle["records"]:
            if isinstance(record.get("session_id"), str):
                sessions.setdefault(record["session_id"], set()).add(index)
    for index, bundle in enumerate(selection["studies"]):
        suite = bundle["suite"]
        validate_suite(suite)
        digest = suite_digest(suite)
        if digest in seen:
            raise ValidationError("Duplicate study; preserve each frozen protocol once")
        seen.add(digest)
        binding = suite.get("task_selection")
        reasons = []
        if not isinstance(binding, dict) or set(binding) != {"catalog_sha256", "arms", "treatment_component"}:
            studies.append({"suite_sha256": digest, "status": "UNBOUND", "blockers": ["Freeze task_selection bindings before collecting a comparison"]})
            continue
        arms = binding["arms"]
        if not isinstance(arms, dict) or set(arms) != {"with", "without"} or any(v not in plans for v in arms.values() if isinstance(v, str)) or any(not isinstance(v, str) for v in arms.values()):
            studies.append({"suite_sha256": digest, "status": "UNBOUND", "blockers": ["Study arms do not identify complete plans in this catalog"]})
            continue
        if binding["catalog_sha256"] != catalog_digest:
            reasons.append("Task, candidate catalog or selection policy changed since the study was frozen")
        if not _same(suite["cases"], task["cases"]) or not _same(suite["conditions"], task["conditions"]):
            reasons.append("Task cases, criteria, input context or runtime conditions do not match")
        if suite["policy"]["quality_floor"] != selection["policy"]["quality_floor"]:
            reasons.append("Quality floor differs from the frozen selection policy")
        manifests = {arm: plans[key]["manifest"] for arm, key in arms.items()}
        treatment = next((c for c in manifests["with"]["components"] if c["id"] == binding["treatment_component"]), None)
        if (treatment is None or treatment["kind"] != "plugin"
                or any(c["id"] == binding["treatment_component"] for c in manifests["without"]["components"])
                or any(suite["plugin"].get(k) != treatment[k] for k in ("name", "version", "sha256"))):
            reasons.append("Paired plugin load semantics do not match the declared treatment and baseline plans")
        for record in bundle["records"]:
            arm = record.get("arm")
            if arm not in arms:
                reasons.append("Unexpected arm in original records")
                continue
            observed = {c["id"]: c["sha256"] for c in manifests[arm]["components"]}
            if record.get("selection_plan_sha256") != arms[arm] or not _same(record.get("observed_components"), observed):
                reasons.append("Observed plan/component binding missing or changed")
            if not _same(record.get("input_snapshot"), task["inputs"]):
                reasons.append("Observed input snapshot missing or changed")
            sid = record.get("session_id")
            if isinstance(sid, str) and len(sessions.get(sid, ())) > 1:
                reasons.append("Session reused across studies")
        # Reuse the authoritative paired engine, including costs, failures and all planned rows.
        report = evaluate(suite, bundle["records"], bundle["lock"], bundle.get("cost_ledger"),
                          artifact_root=artifact_root, verifier_root=verifier_root)
        reasons.extend(report["blockers"])
        if not report["cost_analysis"]["complete_category_coverage"]:
            reasons.append("Full setup/retry/review and other cost coverage is incomplete")
        if report["methodology"]["violations"]:
            reasons.append("Frozen scientific decision-error limits were violated")
        reasons = sorted(set(reasons))
        studies.append({"suite_sha256": digest, "provenance": report["provenance"], "arms": arms,
                        "evidence_type": report["evidence_type"], "verdict": report["verdict"],
                        "status": "BLOCKED" if reasons else "RECOMPUTED", "blockers": reasons,
                        "cost_basis": report["cost_analysis"]["saving_claim_basis"]})
        for arm, key in arms.items():
            rows = [(c, r) for c in report["cases"] for r in c["runs"] if r["arm"] == arm]
            states = [run_success(r, selection["policy"]["quality_floor"]) for _, r in rows]
            status = ("UNKNOWN" if reasons or None in states else "FAILED" if False in states else "SUPPORTED")
            regressions = [c["id"] for c in report["cases"] if arm == "with" and c["delta"] is not None
                           and c["delta"] < -suite["policy"]["max_case_regression"] - 1e-12]
            if regressions and status == "SUPPORTED":
                status = "FAILED"
            computed_status = status
            if report["evidence_type"] == "synthetic":
                status = "SIMULATION_ONLY"
            stages, stage_checks = {}, {}
            for stage in task["stages"]:
                local = [run_success(r, selection["policy"]["quality_floor"]) for c, r in rows if c["id"] in stage["case_ids"]]
                stages[stage["id"]] = ("UNKNOWN" if reasons or None in local else "FAILED" if False in local else "SUPPORTED")
                if set(regressions) & set(stage["case_ids"]) and stages[stage["id"]] == "SUPPORTED":
                    stages[stage["id"]] = "FAILED"
                stage_checks[stage["id"]] = stages[stage["id"]]
                if report["evidence_type"] == "synthetic":
                    stages[stage["id"]] = "SIMULATION_ONLY"
            costs = [r["cost_usd"] for _, r in rows]
            plans[key]["observations"].append({"suite_sha256": digest, "arm": arm, "status": status,
                "computed_status": computed_status, "stage_status": stages, "stage_computational_status": stage_checks,
                "blockers": reasons, "regressed_cases": regressions,
                "passed_in_supplied_sample": not reasons and not regressions and bool(states) and all(v is True for v in states),
                "observed_total_evaluation_cost_usd": sum(costs) if costs and None not in costs and report["cost_analysis"]["complete_category_coverage"] else None,
                "cost_unit": "All planned runs of this arm in this study; not a forecast of task execution cost",
                "verification_receipts": [{"case_id": c["id"], "repetition": r["repetition"],
                    "grade_id": g["id"], "passed": g["passed"], "verification": deepcopy(g["verification"])}
                    for c, r in rows for g in r["grades"] if "verification" in g]})
    return studies, catalog_digest


def select_task_plan(selection, *, artifact_root=None, verifier_root=None):
    """Exhaustive bounded catalog search; unknown/tied alternatives remain explicit."""
    stages, components, options = _validate(selection)
    catalog = _catalog(selection, stages, components, options)
    # A planning operation cannot acquire program-execution authority, even locally.
    from .artifacts import read_only_verification
    with read_only_verification():
        studies, catalog_digest = _assess_studies(selection, catalog, artifact_root, verifier_root)
    for row in catalog:
        computed = {o["computed_status"] for o in row["observations"]}
        row["sample_outcome"] = ("CONFLICTING_EVIDENCE" if {"FAILED", "SUPPORTED"} <= computed else
                                 "FAILED" if "FAILED" in computed else "UNKNOWN" if not computed or "UNKNOWN" in computed else "SUPPORTED")
        if row["status"] == "INAPPLICABLE" or row["applicability_blockers"]:
            continue
        states = {o["status"] for o in row["observations"]}
        row["status"] = ("CONFLICTING_EVIDENCE" if {"FAILED", "SUPPORTED"} <= states else
                         "FAILED" if "FAILED" in states else "UNKNOWN" if not states or "UNKNOWN" in states else
                         "SUPPORTED" if "SUPPORTED" in states else "SIMULATION_ONLY")
    coverage = []
    for sid in stages:
        kinds = {components[o["component_id"]]["kind"] for o in options.values() if o["stage_id"] == sid}
        if "native" not in kinds:
            coverage.append(f"{sid}: native capability alternative not represented")
        if not kinds & {"script", "workflow"}:
            coverage.append(f"{sid}: existing script/workflow alternative not represented")
    supported = [p for p in catalog if p["status"] == "SUPPORTED"]
    best = [p for p in supported if p["size"] == min(q["size"] for q in supported)] if supported else []
    unresolved = [p for p in catalog if p["status"] in ("UNKNOWN", "SIMULATION_ONLY", "CONFLICTING_EVIDENCE")
                  and (not best or p["size"] <= best[0]["size"])]
    selected = best[0] if len(best) == 1 else None
    unbound = [s["suite_sha256"] for s in studies if s["status"] == "UNBOUND"]
    minimum = bool(best) and not coverage and not unresolved and not unbound
    status = ("CHOICE_REQUIRED" if len(best) > 1 else
              "MINIMUM_IN_DECLARED_CATALOG" if selected and minimum else
              "SUPPORTED_OPTION_MINIMUM_UNRESOLVED" if selected else
              "SIMULATION_ONLY" if any(p["status"] == "SIMULATION_ONLY" for p in catalog) else "EVIDENCE_REQUIRED")
    gaps = [{"plan_sha256": p["plan_sha256"], "size": p["size"], "status": p["status"],
             "needed": p["applicability_blockers"] or sorted({b for o in p["observations"] for b in o["blockers"]})
                       or ["Collect the complete frozen plan, including stage and integration checks; do not combine independent stage passes"]}
            for p in unresolved]
    preview = [p["plan_sha256"] for p in catalog if p["status"] == "SIMULATION_ONLY"
               and any(o["passed_in_supplied_sample"] for o in p["observations"])]
    return {"format": FORMAT, "status": status, "catalog_sha256": catalog_digest,
            "task_sha256": suite_digest(selection["task"]), "selected_plan_sha256": selected["plan_sha256"] if selected else None,
            "choice_plan_sha256s": [p["plan_sha256"] for p in best], "minimum_established": minimum,
            "minimum_scope": "Declared finite catalog and exact frozen task only; not a global or future-task optimum",
            "baseline_coverage_gaps": coverage, "unbound_studies": unbound,
            "plans": catalog, "studies": studies, "evidence_gaps": gaps,
            "simulation_passed_plan_sha256s": preview,
            "required_reviews": sorted({r for s in stages.values() for r in s["required_reviews"]}
                                       | {r for p in best for r in p["required_reviews"]}),
            "ready_for_execution": False, "external_actions": 0,
            "limits": ["All fit, identity, installation and runtime observations are submitted declarations, not authenticated facts.",
                       "A whole-plan pass establishes observed computational feasibility only, not plugin causal benefit or scientific validity.",
                       "Stage evidence cannot establish an untested composition. Failed and unmeasured alternatives stay visible.",
                       "Minimum size counts distinct new plugins, then distinct total plugins; it is not minimum cash cost or time.",
                       "Required human reviews and live tool/permission checks remain with the researcher and host; no installation or execution is authorized."]}
