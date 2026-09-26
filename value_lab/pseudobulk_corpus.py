"""Metamorphic verifier evaluation on a frozen real or synthetic reference.

Labels describe controlled transformations, not expert-adjudicated scientific
validity. Do not report these rates as accuracy on a representative population.
"""
from copy import deepcopy
from pathlib import Path
from .core import ValidationError, load_json, write_json
from .science import reference_json
from .pseudobulk import check, validate_spec
from .artifacts import sha


def variants(reference):
    yield "exact_reference", True, deepcopy(reference), "Same frozen computation"
    obj = deepcopy(reference)
    obj["results"].reverse()
    obj["testing_family"].reverse()
    obj["pseudobulk"]["samples"].reverse()
    yield "reordered_rows", True, obj, "Order does not change identity or measurements"
    obj = deepcopy(reference)
    obj["pseudobulk"]["genes"].reverse()
    for row in obj["pseudobulk"]["samples"]:
        row["counts"].reverse()
    yield "reordered_gene_columns", True, obj, "Columns and counts permuted together"
    obj = deepcopy(reference)
    for row in obj["results"]:
        for field, value in row.items():
            if type(value) is float:
                row[field] = float(format(value, ".12g"))
    yield "twelve_digit_serialization", True, obj, "Precision loss below frozen tolerances"
    mutations = {
        "cell_pseudoreplication": lambda o: o["pseudobulk"].update(analysis_unit="cell"),
        "donor_removed": lambda o: o["pseudobulk"]["samples"][0].update(donor="unknown"),
        "wrong_aggregation": lambda o: o["pseudobulk"]["samples"][0]["counts"].__setitem__(0, o["pseudobulk"]["samples"][0]["counts"][0] + 1),
        "dropped_gene": lambda o: o["results"].pop(),
        "duplicate_gene": lambda o: o["results"].append(deepcopy(o["results"][0])),
        "selected_testing_family": lambda o: o["testing_family"].pop(),
        "wrong_normalization": lambda o: o["normalization"].update({next(iter(o["normalization"])): 999.0}),
        "donor_omitted_design": lambda o: o["method"].update(formula="~condition"),
        "reversed_contrast": lambda o: o["method"]["contrast"].reverse(),
        "wrong_backend_version": lambda o: o["method"].update(version="unobserved"),
        "wrong_adjusted_p": lambda o: o["results"][0].update(q_value=0.123456789),
        "wrong_uncertainty": lambda o: o["results"][0].update(ci95_lower=-9999.0),
        "unsupported_generalization": lambda o: o.update(conclusion_scope="all_patients"),
    }
    for name, mutate in mutations.items():
        obj = deepcopy(reference)
        mutate(obj)
        yield name, False, obj, "Controlled violation of frozen fixed-method contract: " + name


def evaluate_corpus(spec_path, root, output):
    spec = load_json(spec_path)
    validate_spec(spec)
    reference = reference_json(root, spec["truth"])
    design = reference_json(root, spec["design"])
    if design["task_mode"] != "fixed_method":
        raise ValidationError("Controlled binary corpus requires fixed-method mode")
    output = Path(output)
    if output.exists():
        raise ValidationError("Preserve existing corpus runs; choose a new directory")
    output.mkdir(parents=True)
    rows = []
    for name, expected, artifact, rationale in variants(reference):
        path = output / (name + ".json")
        write_json(path, artifact)
        observed, detail = check(path, spec, root)
        rows.append({"id": name, "expected": expected, "observed": observed, "rationale": rationale,
                     "artifact": {"path": path.name, "sha256": sha(path)}, "diagnosis": detail})
    positives = [r for r in rows if r["expected"]]
    negatives = [r for r in rows if not r["expected"]]
    false_accepts = sum(r["observed"] is True for r in negatives)
    false_rejects = sum(r["observed"] is False for r in positives)
    summary = {"format": "pvl-verifier-corpus-1", "spec": spec, "cases": rows,
               "positive_cases": len(positives), "negative_cases": len(negatives),
               "false_accepts": false_accepts, "false_rejects": false_rejects,
               "unresolved": sum(r["observed"] is None for r in rows),
               "controlled_false_accept_rate": false_accepts / len(negatives),
               "controlled_false_reject_rate": false_rejects / len(positives),
               "independent_expert_review": "PENDING", "representative_accuracy": "NOT_ESTABLISHED",
               "scope": "Controlled mutations and valid serialization/order variants; not independent scientific adjudication"}
    write_json(output / "corpus-report.json", summary)
    return summary


def scenario_pack(spec_path, root, output):
    """Create public task inputs and separately stored scorers for existing hosts."""
    import secrets
    from .science import read_reference
    from .scenarios import validate_pack
    spec = load_json(spec_path)
    validate_spec(spec)
    design = reference_json(root, spec["design"])
    data = reference_json(root, spec["data"])
    output = Path(output)
    if output.exists():
        raise ValidationError("Use a new scenario directory")
    inputs, scorers = output / "inputs", output / "scorers"
    inputs.mkdir(parents=True)
    scorers.mkdir()
    local_spec = deepcopy(spec)
    for field in ("design", "data", "truth"):
        name = field + ".json"
        raw = read_reference(root, spec[field])
        (scorers / name).write_bytes(raw)
        if field != "truth":
            (inputs / name).write_bytes(raw)
        local_spec[field]["path"] = name
    case_id = "donor-pseudobulk"
    private = {"type": "ScorerOnlyGroundTruth", "case_id": case_id, "evidence_type": "local",
               "nonce": secrets.token_hex(32), "rationale": "Fixed reference computation; expert review pending. Collector evidence is separate from artifact agreement.",
               "graders": [{"id": "analysis-chain", "type": "pseudobulk_chain", "artifact": "analysis", "verifier": local_spec},
                           {"id": "observed-backend", "type": "backend_identity", "artifact": "analysis",
                            "verifier": {"backend": "pydeseq2", "version": design["backend_version"], "entrypoint": "DeseqDataSet.deseq2/DeseqStats.summary"}}]}
    write_json(scorers / "scorer.json", private)
    # This public schema comes from the implementation, never from hidden values.
    public_contract = {"format": "pvl-pseudobulk-result-1", "required_fields": ["format", "pseudobulk", "method", "normalization", "design_matrix", "testing_family", "results", "conclusion_scope", "uncertainty"],
                       "implementation": "value_lab.pseudobulk.fit_reference defines serialization; source and local reference runner are permitted tools",
                       "documentation": "docs/history/PSEUDOBULK.zh-CN.md", "scorer_values_included": False}
    write_json(inputs / "output-contract.json", public_contract)
    pack = {"format": "pvl-scenario-pack-1", "id": "donor-pseudobulk-development", "evidence_type": "local",
            "sources": [{"url": data["provenance"].get("source", design["reference_workflow"]),
                         "license": "Dataset-specific terms require review before redistribution; local evaluation package only",
                         "provenance": "Frozen supplied counts; provenance claims are not authenticated by hashes"}],
            "scenarios": [{"type": "AgentVisibleScenario", "id": case_id, "family": "donor-aware-de", "split": "development",
                           "prompt": "Analyze data.json under design.json. Preserve all donors and the full prefiltered testing family. Use raw count sums, donor-adjusted PyDESeq2, declared normalization and contrast. Produce result.json conforming to output-contract.json and the documented pvl-pseudobulk-result-1 format. Report internal fitting changes and limit conclusions to the supplied donors and cell type. Do not invent a backend receipt: the host collector must retain actual execution evidence separately.",
                           "inputs": {p.name: sha(p) for p in inputs.iterdir()}, "outputs": {"analysis": "result.json"},
                           "scorer": {"path": "scorer.json", "sha256": sha(scorers / "scorer.json")}}]}
    validate_pack(pack, inputs, scorers)
    write_json(output / "pack.json", pack)
    return {"output": str(output.resolve()), "case": case_id, "split": "development",
            "expert_review": "PENDING", "scorer_isolation": "SEPARATE_DIRECTORIES_ONLY"}
