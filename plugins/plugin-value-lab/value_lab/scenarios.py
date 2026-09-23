"""Proposed Scenario Pack interchange, with allowlisted host staging.

No automatic claim of Arena compatibility, private-data secrecy or task validity.
"""
from copy import deepcopy
from pathlib import Path
import re
import tempfile

from .artifacts import confined, grade_artifact, validate_verifier
from .core import ValidationError, _identifier, _text, suite_digest, validate_suite, write_json
from .science import KINDS, REFERENCE_FIELDS, keys, read_reference, reference, reference_json


def validate_pack(pack, input_root=None, scorer_root=None):
    keys(pack, "format id evidence_type sources scenarios")
    if pack["format"] != "pvl-scenario-pack-1" or pack["evidence_type"] not in ("synthetic", "local", "external"):
        raise ValidationError("Unsupported Scenario Pack format or evidence type")
    _identifier(pack["id"], "pack.id")
    if not isinstance(pack["sources"], list) or not pack["sources"]:
        raise ValidationError("Pack requires source and licensing declarations")
    for source in pack["sources"]:
        keys(source, "url license provenance")
        for key in source:
            _text(source[key], key)
    if not isinstance(pack["scenarios"], list) or not pack["scenarios"]:
        raise ValidationError("Pack requires scenarios")
    ids, families, prompts = set(), {}, set()
    private_hashes, public_hashes = set(), set()
    for case in pack["scenarios"]:
        keys(case, "type id family split prompt inputs outputs scorer")
        if case["type"] != "AgentVisibleScenario":
            raise ValidationError("Public scenario type required")
        _identifier(case["id"], "case.id")
        _text(case["family"], "family")
        _text(case["prompt"], "prompt")
        prompt = " ".join(case["prompt"].split()).casefold()
        if case["id"] in ids or prompt in prompts:
            raise ValidationError("Duplicate scenario identity or prompt")
        ids.add(case["id"])
        prompts.add(prompt)
        if case["split"] not in ("development", "heldout") or families.get(case["family"], case["split"]) != case["split"]:
            raise ValidationError("Families cannot cross development/heldout splits")
        families[case["family"]] = case["split"]
        reference(case["scorer"])
        private_hashes.add(case["scorer"]["sha256"])
        if not isinstance(case["inputs"], dict) or not isinstance(case["outputs"], dict) or not case["outputs"]:
            raise ValidationError("Inputs and nonempty outputs must be mappings")
        paths = set()
        for name, digest in case["inputs"].items():
            ref = {"path": name, "sha256": digest}
            reference(ref)
            public_hashes.add(digest)
            if input_root is not None:
                read_reference(input_root, ref)
            if name.casefold() in paths:
                raise ValidationError("Input names collide on case-insensitive filesystems")
            paths.add(name.casefold())
        output_paths = set()
        for artifact, path in case["outputs"].items():
            _identifier(artifact, "artifact")
            confined(Path.cwd(), path)
            if path.casefold() in paths | output_paths:
                raise ValidationError("Output paths must be distinct from inputs and other outputs")
            output_paths.add(path.casefold())
        if scorer_root is not None:
            private = reference_json(scorer_root, case["scorer"])
            validate_private(private, case["id"], pack["evidence_type"])
            for grader in private["graders"]:
                if grader["artifact"] not in case["outputs"]:
                    raise ValidationError("Scorer references an undeclared output")
                for field in REFERENCE_FIELDS:
                    ref = grader["verifier"].get(field)
                    if ref is not None:
                        read_reference(scorer_root, ref)
                        # Design and measurements may be the task's public inputs.
                        # Answers, executable scorers and decision truth remain private.
                        if field not in ("design", "data"):
                            private_hashes.add(ref["sha256"])
    if private_hashes & public_hashes:
        raise ValidationError("Scorer-only bytes also supplied as agent inputs")
    return {"pack_sha256": suite_digest(pack), "cases": len(ids), "families": len(families),
            "inputs_checked": input_root is not None, "scorers_checked": scorer_root is not None,
            "scope": "Structural isolation; task validity and prior exposure require independent review"}


def validate_private(private, case_id, evidence_type):
    keys(private, "type case_id evidence_type nonce rationale graders")
    if private["type"] != "ScorerOnlyGroundTruth" or private["case_id"] != case_id or private["evidence_type"] != evidence_type:
        raise ValidationError("Scorer identity or evidence type mismatch")
    if not isinstance(private["nonce"], str) or not re.fullmatch(r"[a-f0-9]{64}", private["nonce"]):
        raise ValidationError("Scorer requires a private random 32-byte nonce against answer enumeration")
    _text(private["rationale"], "scorer rationale")
    if not isinstance(private["graders"], list) or not private["graders"]:
        raise ValidationError("Scorer needs graders")
    ids, decisions = set(), 0
    for grader in private["graders"]:
        keys(grader, "id type artifact verifier")
        _identifier(grader["id"], "grader.id")
        if grader["id"] in ids or grader["type"] not in KINDS | {"artifact"}:
            raise ValidationError("Unsupported/duplicate private grader; arbitrary local execution is excluded")
        ids.add(grader["id"])
        validate_verifier(grader)
        decisions += grader["type"] in ("abstention_correct", "over_refusal")
    if decisions > 1:
        raise ValidationError("One decision denominator per scenario is allowed")


def validate_scenario_grader(grader):
    keys(grader.get("verifier"), "path sha256 case_id evidence_type")
    spec = grader["verifier"]
    reference({k: spec[k] for k in ("path", "sha256")})
    _identifier(spec["case_id"], "case_id")
    if spec["evidence_type"] not in ("synthetic", "local", "external"):
        raise ValidationError("Scorer evidence type required")


def prepare_suite(pack, template):
    validate_pack(pack)
    validate_suite(template)
    suite = deepcopy(template)
    if "corpus" in suite:
        raise ValidationError("Use a template without an existing sealed corpus")
    suite["evidence_type"] = pack["evidence_type"] if template["evidence_type"] != "synthetic" else "synthetic"
    suite["scenario_pack"] = {"sha256": suite_digest(pack), "format": pack["format"]}
    suite["cases"] = [{"id": c["id"], "cluster": c["family"], "kind": "task", "prompt": c["prompt"],
        "split": c["split"], "inputs": c["inputs"], "output_artifacts": c["outputs"],
        "graders": [{"id": "scientific-outcome", "type": "scenario", "dimension": "outcome", "critical": True,
                     "weight": 1, "verifier": {**c["scorer"], "case_id": c["id"], "evidence_type": pack["evidence_type"]}}]}
        for c in pack["scenarios"]]
    return validate_suite(suite)


def stage_case(pack, case_id, input_root, output, scorer_root=None):
    if scorer_root is None:
        raise ValidationError("Scorer root is required to check for private-byte input leakage before staging")
    validate_pack(pack, input_root=input_root, scorer_root=scorer_root)
    cases = [c for c in pack["scenarios"] if c["id"] == case_id]
    if len(cases) != 1:
        raise ValidationError("Unknown scenario")
    case = cases[0]
    output = Path(output).resolve()
    inputs = Path(input_root).resolve()
    scorers = Path(scorer_root).resolve()
    if any(output == root or output.is_relative_to(root) or root.is_relative_to(output) for root in (inputs, scorers)):
        raise ValidationError("Agent staging and source inputs must be disjoint directories")
    if output.exists():
        raise ValidationError("Stage destination already exists")
    # Validate and stage atomically. Do not copy any directory recursively.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".scenario-", dir=output.parent) as temp:
        stage = Path(temp) / "stage"
        stage.mkdir()
        for name, digest in case["inputs"].items():
            path = confined(stage, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(read_reference(input_root, {"path": name, "sha256": digest}))
        if (stage / "scenario.json").exists() or "scenario.json" in case["outputs"].values():
            raise ValidationError("scenario.json is reserved for the public task")
        visible = {k: case[k] for k in ("type", "id", "prompt", "inputs", "outputs")}
        write_json(stage / "scenario.json", visible)
        stage.rename(output)
    return {"case_id": case_id, "output": str(output), "input_files": len(case["inputs"]), "scorer_material_staged": False}


def grade_scenario(g, record, artifact_root, scorer_root):
    receipt = {"rule_sha256": suite_digest(g), "scope": "SCORER_ONLY_SCIENTIFIC_CONTRACT",
               "evidence_type": g["verifier"]["evidence_type"]}
    try:
        spec = g["verifier"]
        private = reference_json(scorer_root, {k: spec[k] for k in ("path", "sha256")})
        validate_private(private, spec["case_id"], spec["evidence_type"])
        grades = []
        for child in private["graders"]:
            passed, rationale, verification = grade_artifact(child, record, artifact_root, scorer_root)
            if child["type"] in ("abstention_correct", "over_refusal"):
                verification.setdefault("metric", "unsupported_acceptance" if child["type"] == "abstention_correct" else "over_refusal")
                verification.setdefault("error", None)
            grades.append({"id": child["id"], "passed": passed, "rationale": rationale, "verification": verification})
        receipt["grades"] = grades
        passed = None if any(g["passed"] is None for g in grades) else all(g["passed"] for g in grades)
        return passed, "All private scientific criteria are required; missing evidence stays unresolved", receipt
    except (OSError, ValueError) as exc:
        return None, f"Scenario scoring unavailable: {exc}", receipt


def decision_metrics(suite, records, scorer_root, artifact_root):
    """Keep the full planned denominator, including missing and duplicate runs."""
    indexed, groups, unavailable = {}, {}, []
    for record in records:
        key = (record.get("case_id"), record.get("arm"), record.get("repetition"))
        if all(isinstance(k, (str, int)) for k in key):
            indexed.setdefault(key, []).append(record)
    for case in suite["cases"]:
        rules = []
        for g in case["graders"]:
            if g["type"] == "scenario":
                try:
                    spec = g["verifier"]
                    private = reference_json(scorer_root, {k: spec[k] for k in ("path", "sha256")})
                    validate_private(private, case["id"], spec["evidence_type"])
                    rules.extend(private["graders"])
                except (OSError, ValueError) as exc:
                    unavailable.append({"case_id": case["id"], "reason": str(exc)})
            else:
                rules.append(g)
        for kind in ("abstention_correct", "over_refusal"):
            matching_rules = [rule for rule in rules if rule["type"] == kind]
            if not matching_rules:
                continue
            if len(matching_rules) != 1:
                unavailable.append({"case_id": case["id"], "reason": "Ambiguous repeated decision metric: " + kind})
            rule = matching_rules[0]
            metric = "unsupported_acceptance" if kind == "abstention_correct" else "over_refusal"
            for arm in ("with", "without"):
                group = groups.setdefault((case.get("split", "unspecified"), arm, metric), {"planned": 0, "errors": 0, "unknown": 0})
                for rep in range(1, suite["runs_per_case"] + 1):
                    group["planned"] += 1
                    matches = indexed.get((case["id"], arm, rep), [])
                    error = None
                    if len(matching_rules) == 1 and len(matches) == 1 and matches[0].get("status") == "completed":
                        _, _, checked = grade_artifact(rule, matches[0], artifact_root, scorer_root)
                        error = checked.get("error")
                    group["unknown"] += error is None
                    group["errors"] += error is True
    metrics = []
    for (split, arm, metric), counts in sorted(groups.items()):
        n, errors, unknown = (counts[k] for k in ("planned", "errors", "unknown"))
        metrics.append({"split": split, "arm": arm, "metric": metric, **counts, "resolved": n - unknown,
                        "rate": errors / n if not unknown else None, "lower_bound": errors / n,
                        "upper_bound": (errors + unknown) / n})
    return {"metrics": metrics, "unavailable_cases": unavailable,
            "scope": "Planned case repetitions; missingness bounds, not confidence intervals or independent samples"}
