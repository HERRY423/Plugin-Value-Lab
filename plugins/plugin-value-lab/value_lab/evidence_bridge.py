"""Conservative matrix-task bridging alongside unchanged exact-scope citation.

Input equivalence is not producer invariance. Old observations stay in their
original studies; a bridge creates a separately frozen target observation set.
"""
from copy import deepcopy
import json

from .artifacts import MAX_BYTES, confined, sha
from .core import ValidationError, suite_digest
from .metamorphic import _matrix, transform
from .task_selection import _keys, _sha, select_task_plan


FORMAT = "pvl-evidence-bridge-1"
CONTRACT = "pvl-paired-matrix-bridge-1"


def _diff(a, b, path=""):
    if suite_digest(a) == suite_digest(b):
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        rows = []
        for key in sorted(set(a) | set(b)):
            pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in a or key not in b:
                rows.append({"path": pointer, "source_present": key in a, "target_present": key in b,
                             "source": deepcopy(a.get(key)), "target": deepcopy(b.get(key))})
            else:
                rows.extend(_diff(a[key], b[key], pointer))
        return rows
    return [{"path": path, "source_present": True, "target_present": True, "source": deepcopy(a), "target": deepcopy(b)}]


def _classify(row):
    path = row["path"]
    if path in ("/task/id", "/task/summary"):
        return "DESCRIPTIVE_ONLY"
    if path.startswith("/task/inputs/"):
        return "VERIFY_INPUT_DIFFERENCE"
    if path in ("/task/facts/data_scale", "/task/facts/sparsity", "/task/conditions/environment"):
        return "BRIDGE_REQUIRED"
    # Rubrics, factors, component contents, model/host and unknown changes are not
    # waived by a caller-provided similarity score or an allowlist.
    return "NEW_STUDY_REQUIRED"


def _unique_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValidationError("Duplicate JSON key in bridge input")
        obj[key] = value
    return obj


def _material(root, ref, expected):
    _keys(ref, ("path", "sha256"))
    _sha(ref["sha256"])
    if ref["sha256"] != expected:
        raise ValidationError("Material identity differs from its task input snapshot")
    if root is None:
        raise ValidationError("Authorized artifact root is required for input bridge checks")
    path = confined(root, ref["path"])
    if not path.is_file() or path.stat().st_size > MAX_BYTES or sha(path) != expected:
        raise ValidationError("Bridge input missing, oversized or hash changed")
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
    _keys(value, ("matrix", "context"))
    _matrix(value["matrix"])
    if not isinstance(value["context"], dict):
        raise ValidationError("Bridge input needs explicit scientific context")
    suite_digest(value)
    return value


def _input_check(source, target, request, root):
    key = request["contract"]["input_key"]
    try:
        before = _material(root, request["source_material"], source["task"]["inputs"][key])
        after = _material(root, request["target_material"], target["task"]["inputs"][key])
        measurements = {}
        for label, selection, value in (("source", source, before), ("target", target, after)):
            facts = selection["task"]["facts"]
            if any(value["context"].get(k) != facts[k] or type(value["context"].get(k)) is not type(facts[k])
                   for k in ("paired", "input_kind", "goal")):
                raise ValidationError("Input context disagrees with declared research design")
            matrix = value["matrix"]
            values = [v for row in matrix["values"] for v in row]
            measured = {"rows": len(matrix["row_ids"]), "columns": len(matrix["columns"]),
                        "sparsity": sum(v == 0 for v in values) / len(values)}
            measurements[label] = measured
            if "data_scale" in facts and (type(facts["data_scale"]) is not int or facts["data_scale"] != measured["rows"]):
                raise ValidationError("Declared data_scale differs from actual matrix row count")
            if "sparsity" in facts and (type(facts["sparsity"]) not in (float, int) or abs(facts["sparsity"] - measured["sparsity"]) > 1e-12):
                raise ValidationError("Declared sparsity differs from actual matrix values")
        if suite_digest(before["context"]) != suite_digest(after["context"]):
            status = "NEW_STUDY_REQUIRED"
        elif before["matrix"]["columns"] != after["matrix"]["columns"]:
            status = "NEW_STUDY_REQUIRED"
        elif source["task"]["inputs"][key] == target["task"]["inputs"][key]:
            status = "IDENTICAL_BYTES"
        elif suite_digest(before) == suite_digest(after):
            status = "ENCODING_EQUIVALENT"
        elif (set(before["matrix"]["row_ids"]) == set(after["matrix"]["row_ids"])
              and suite_digest(transform(before, {"relation": "row_permutation", "parameters": {"order": after["matrix"]["row_ids"]}})) == suite_digest(after)):
            status = "ROW_PERMUTATION_EQUIVALENT"
        else:
            status = "NEW_DATA_BRIDGE_REQUIRED"
        return {"status": status, "measurements": measurements, "input_key": key,
                "_loaded": (before, after),
                "source_sha256": request["source_material"]["sha256"], "target_sha256": request["target_material"]["sha256"],
                "method": "Existing matrix validator and deterministic row_permutation transform; exact context, columns, identities and numeric values",
                "reuse_scope": "Input content/identity checks only; not order-insensitive plugin execution or scientific validity"}
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        return {"status": "UNKNOWN", "input_key": key, "reason": str(exc), "reuse_scope": "NONE"}


def _input_derived_cases(source, target, loaded, source_sha, target_sha):
    """Only regenerate exact matrix-copy or input-identity references, not rules.

Expected counts/sample IDs are checked against the actual bound inputs before
normalizing them for comparison. Arbitrary expected answers are never waived.
"""
    a, b = deepcopy(source), deepcopy(target)
    if len(a) != len(b):
        return False
    before, after = loaded or ({"matrix": {"values": None, "row_ids": None}}, {"matrix": {"values": None, "row_ids": None}})
    values = {"counts": (before["matrix"]["values"], after["matrix"]["values"]),
              "sample_ids": (before["matrix"]["row_ids"], after["matrix"]["row_ids"]),
              "input_snapshot": (source_sha, target_sha)}
    for left, right in zip(a, b):
        if len(left["graders"]) != len(right["graders"]):
            return False
        for first, second in zip(left["graders"], right["graders"]):
            if first["type"] != "artifact" or second["type"] != "artifact":
                continue
            u, v = first["verifier"], second["verifier"]
            if u.get("kind") != "json_fields" or v.get("kind") != "json_fields":
                continue
            for field, (old, new) in values.items():
                x, y = u["expected"], v["expected"]
                if field in x and field in y and suite_digest(x[field]) != suite_digest(y[field]):
                    if loaded and (suite_digest(x[field]) != suite_digest(old) or suite_digest(y[field]) != suite_digest(new)):
                        return False
                    x[field] = y[field] = "INPUT_DERIVED_REFERENCE_ONLY"
    equal = suite_digest(a) == suite_digest(b)
    return None if equal and not loaded else equal


def _reference_mismatches(selection, value, input_sha):
    expected = {"counts": value["matrix"]["values"], "sample_ids": value["matrix"]["row_ids"], "input_snapshot": input_sha}
    failures = []
    for case in selection["task"]["cases"]:
        for grader in case["graders"]:
            if grader["type"] != "artifact" or grader["verifier"].get("kind") != "json_fields":
                continue
            for field, actual in expected.items():
                reference = grader["verifier"]["expected"]
                if field in reference and suite_digest(reference[field]) != suite_digest(actual):
                    failures.append(f"{case['id']}/{grader['id']}/{field}")
    return failures


def _protocol(source, target, request, study, source_plan, target_catalog, changes):
    suite = deepcopy(study["suite"])
    suite["id"] = "bridge-" + target_catalog[:24]
    suite["cases"] = deepcopy(target["task"]["cases"])
    suite["conditions"] = deepcopy(target["task"]["conditions"])
    suite["task_selection"]["catalog_sha256"] = target_catalog
    binding = {"source_selection_sha256": request["source_sha256"], "source_study_sha256": request["source_study_sha256"],
               "source_plan_sha256": source_plan, "target_catalog_sha256": target_catalog,
               "contract_sha256": request["contract_sha256"], "changes_sha256": suite_digest(changes)}
    suite["evidence_bridge"] = binding
    return {"format": "pvl-target-bridge-protocol-1", **binding, "suite": suite,
            "lock": {"suite_sha256": suite_digest(suite)}, "required_input_snapshot": deepcopy(target["task"]["inputs"]),
            "planned_runs": len(suite["cases"]) * suite["runs_per_case"] * 2,
            "execution": "Fresh target observations required; replay/regrading of source output is not a bridge"}


def plan_bridge(target, request, *, artifact_root=None, verifier_root=None):
    _keys(request, ("source_selection", "source_sha256", "source_study_sha256", "source_plan_sha256",
                    "contract", "contract_sha256", "source_material", "target_material"), ("bridge_study",))
    source = request["source_selection"]
    if suite_digest(source) != request["source_sha256"]:
        raise ValidationError("Source evidence commitment changed; preserve the original study")
    contract = request["contract"]
    _keys(contract, ("format", "input_key"))
    if contract["format"] != CONTRACT or suite_digest(contract) != request["contract_sha256"]:
        raise ValidationError("Unknown or changed reviewed bridge contract")
    if target["studies"]:
        raise ValidationError("Target observations belong in a separately frozen bridge_study, never by rewriting old studies")
    before = select_task_plan(source, artifact_root=artifact_root, verifier_root=verifier_root)
    after = select_task_plan(target, artifact_root=artifact_root, verifier_root=verifier_root)
    key = contract["input_key"]
    for selection in (source, target):
        if not isinstance(key, str) or set(selection["task"]["inputs"]) != {key}:
            raise ValidationError("This reviewed bridge contract supports one explicit matrix input only")
        facts = selection["task"]["facts"]
        if not {"paired", "input_kind", "goal"} <= set(facts):
            raise ValidationError("Bridge tasks must declare paired design, input kind and inference goal")
    studies = [s for s in source["studies"] if suite_digest(s["suite"]) == request["source_study_sha256"]]
    if len(studies) != 1:
        raise ValidationError("Identify one original frozen source study")
    study = studies[0]
    plan = next((p for p in before["plans"] if p["plan_sha256"] == request["source_plan_sha256"]), None)
    if plan is None or request["source_plan_sha256"] not in study["suite"].get("task_selection", {}).get("arms", {}).values():
        raise ValidationError("Source plan must be an actual arm of the selected source study")
    scope = lambda s: {k: v for k, v in s.items() if k != "studies"}
    changes = _diff(scope(source), scope(target))
    for row in changes:
        row["classification"] = _classify(row)
    material = _input_check(source, target, request, artifact_root)
    loaded = material.pop("_loaded", None)
    for row in changes:
        if row["path"] == "/task/cases":
            equivalent = _input_derived_cases(source["task"]["cases"], target["task"]["cases"], loaded,
                                             source["task"]["inputs"][key], target["task"]["inputs"][key])
            if equivalent is not False:
                row["classification"] = "BRIDGE_REQUIRED" if equivalent else "VERIFY_INPUT_DIFFERENCE"
                row["reason"] = ("Only input-derived matrix/identity references changed; actual bytes validate both references while rules remain fixed"
                                 if equivalent else "Potential input-derived reference change still needs actual source and target bytes")
    barriers = [d["path"] for d in changes if d["classification"] == "NEW_STUDY_REQUIRED"]
    target_applicability = {p["plan_sha256"]: p["applicability_blockers"] for p in after["plans"]
                            if p["plan_sha256"] in study["suite"]["task_selection"]["arms"].values()
                            and p["applicability_blockers"]}
    barriers.extend("/target_plan_applicability/" + key for key in target_applicability)
    reference_issues = {}
    if loaded:
        for side, selection, value in (("source", source, loaded[0]), ("target", target, loaded[1])):
            failures = _reference_mismatches(selection, value, selection["task"]["inputs"][key])
            if failures:
                reference_issues[side] = failures
    if material["status"] == "NEW_STUDY_REQUIRED":
        barriers.append("/actual_input/context_or_columns")
    # The source plan must pass in this exact source study, not only a different
    # study in the catalog. Synthetic successes remain demonstrations throughout.
    observations = [o for o in plan["observations"] if o["suite_sha256"] == request["source_study_sha256"]]
    source_ok = bool(observations) and all(o["computed_status"] == "SUPPORTED" for o in observations)
    source_ok &= plan["sample_outcome"] == "SUPPORTED" and not plan["applicability_blockers"]
    synthetic = any(o["status"] == "SIMULATION_ONLY" for o in plan["observations"])
    protocol, target_report, bridge_result, issues = None, None, None, []
    if barriers:
        state = "NEW_STUDY_REQUIRED"
    elif material["status"] == "UNKNOWN":
        state = "INPUT_EVIDENCE_REQUIRED"
    elif reference_issues:
        state = "INPUT_EVIDENCE_REQUIRED"
    elif not source_ok:
        state = "SOURCE_EVIDENCE_REQUIRED"
    elif all(d["classification"] == "DESCRIPTIVE_ONLY" for d in changes):
        state = "SAME_SCOPE_REPLAY"
    else:
        state = "BRIDGE_REQUIRED"
        protocol = _protocol(source, target, request, study, plan["plan_sha256"], after["catalog_sha256"], changes)
    supplied = request.get("bridge_study")
    if supplied is not None:
        if protocol is None:
            raise ValidationError("A bridge cannot bypass a new-study boundary, missing source/input evidence or same-scope replay")
        _keys(supplied, ("protocol", "protocol_sha256", "records", "cost_ledger"))
        if suite_digest(supplied["protocol"]) != suite_digest(protocol) or supplied["protocol_sha256"] != suite_digest(protocol):
            raise ValidationError("Prospective bridge protocol changed after preparation")
        if not isinstance(supplied["records"], list) or any(not isinstance(r, dict) for r in supplied["records"]):
            raise ValidationError("Bridge needs original fresh run records")
        old_sessions = {r.get("session_id") for s in source["studies"] for r in s["records"] if isinstance(r.get("session_id"), str)}
        old_paths = {ref.get("path") for s in source["studies"] for r in s["records"]
                     for refs in [r.get("artifacts", {})] if isinstance(refs, dict)
                     for ref in refs.values() if isinstance(ref, dict) and isinstance(ref.get("path"), str)}
        for record in supplied["records"]:
            if isinstance(record.get("session_id"), str) and record["session_id"] in old_sessions:
                issues.append("Source execution session reused as target evidence")
            refs = record.get("artifacts", {})
            if isinstance(refs, dict) and any(isinstance(ref, dict) and isinstance(ref.get("path"), str) and ref["path"] in old_paths for ref in refs.values()):
                issues.append("Source producer artifact reused; regrading is not a new target observation")
        bound = {"suite": protocol["suite"], "lock": protocol["lock"], "records": supplied["records"], "cost_ledger": supplied["cost_ledger"]}
        target_with_new_study = deepcopy(target)
        target_with_new_study["studies"] = [bound]
        target_report = select_task_plan(target_with_new_study, artifact_root=artifact_root, verifier_root=verifier_root)
        row = next(p for p in target_report["plans"] if p["plan_sha256"] == request["source_plan_sha256"])
        synthetic |= any(s["evidence_type"] == "synthetic" for s in target_report["studies"] if "evidence_type" in s)
        bridge_result = {"source_plan_on_target": row["status"], "sample_outcome": row["sample_outcome"],
                         "observations": deepcopy(row["observations"]), "issues": issues,
                         "study_sha256": suite_digest(bound), "new_execution": "SUBMITTED_DECLARATION_NOT_AUTHENTICATED"}
        state = ("BRIDGE_EVIDENCE_REQUIRED" if issues or row["sample_outcome"] == "UNKNOWN" else
                 "BRIDGE_REJECTED" if row["sample_outcome"] != "SUPPORTED" else "TARGET_OBSERVATION_SUPPORTED")
    inherited = [{"suite_sha256": o["suite_sha256"], "arm": o["arm"], "computed_status": o["computed_status"],
                  "verification_receipts": deepcopy(o["verification_receipts"])} for o in observations]
    return {"format": FORMAT, "state": state, "evidence_status": "SIMULATION_ONLY" if synthetic else "SUBMITTED_OBSERVATIONS",
            "source_sha256": request["source_sha256"], "target_catalog_sha256": after["catalog_sha256"],
            "changes": changes, "new_study_barriers": barriers, "input_check": material,
            "input_reference_issues": reference_issues,
            "target_applicability_issues": target_applicability,
            "retained_source_evidence": inherited, "source_regrading_new_observations": 0,
            "source_evidence_eligible": bool(source_ok), "proposed_protocol": protocol,
            "proposed_protocol_sha256": suite_digest(protocol) if protocol else None,
            "bridge_result": bridge_result,
            "target_selection": target_report if not issues else None,
            "target_plan_supported": state == "TARGET_OBSERVATION_SUPPORTED" and not synthetic,
            "old_adoption_claim_transferred": False, "minimum_established": False,
            "required_reviews": sorted(set(before["required_reviews"]) | set(after["required_reviews"])),
            "automatic_execution": False, "external_actions": 0,
            "limits": ["Old studies remain immutable and scoped; source regrading and input invariance add no target execution observations.",
                       "Row permutation or encoding equivalence only reuses input identity/content checks, not arbitrary producer behavior.",
                       "Bridge support covers this new input and exact reviewed protocol only, not other data, models, hosts or scientific truth.",
                       "Unknown design, rubric, component, model/host or unsupported changes require a new study; similarity never overrides this.",
                       "This one-pair bridge does not establish a minimum across untested target alternatives, independent execution or causal benefit."]}
