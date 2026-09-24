"""Donor-aware pseudobulk chain. Reference fitting is an explicit optional action.

The offline verifier never fits a model or executes a submitted program. PyDESeq2
is the reference backend, not a newly implemented differential-expression model.
"""
from collections import defaultdict
from pathlib import Path
import math

from .core import ValidationError, load_json, suite_digest, write_json
from .science import keys, reference, reference_json, number


def validate_spec(spec):
    keys(spec, "design data truth absolute relative")
    for field in ("design", "data", "truth"):
        reference(spec[field])
    for field in ("absolute", "relative"):
        if not 0 <= number(spec[field]) <= 0.0001:
            raise ValidationError("Pseudobulk tolerances must be between zero and 1e-4")


def validate_design(design):
    keys(design, "format task_mode cell_type control treatment min_cells min_total_count backend_version reference_workflow")
    if design["format"] != "pvl-pseudobulk-design-1" or design["task_mode"] not in ("fixed_method", "acceptable_solution"):
        raise ValidationError("Unknown pseudobulk task mode")
    for field in ("cell_type", "control", "treatment", "backend_version", "reference_workflow"):
        if not isinstance(design[field], str) or not design[field].strip():
            raise ValidationError("Pseudobulk design fields must be nonempty strings")
    if design["control"] == design["treatment"]:
        raise ValidationError("Contrast needs two distinct conditions")
    for field in ("min_cells", "min_total_count"):
        if type(design[field]) is not int or design[field] < 1:
            raise ValidationError("Filtering thresholds must be positive integers")


def aggregate(design, data):
    """Validate complete sparse cell counts, then sum by declared donor/condition.

No automatic row dropping, donor imputation, rounding, or pooled-cell inference.
Raw counts and identities are still supplied measurements, not authenticated facts.
"""
    validate_design(design)
    keys(data, "format genes cells provenance")
    if data["format"] != "pvl-cell-counts-1" or not isinstance(data["provenance"], dict):
        raise ValidationError("Expected sparse raw-cell-count input and provenance")
    genes = data["genes"]
    if not isinstance(genes, list) or not genes or len(genes) > 100000 or any(not isinstance(g, str) or not g.strip() for g in genes) or len(set(genes)) != len(genes):
        raise ValidationError("Genes must be unique nonempty identifiers")
    cells = data["cells"]
    if not isinstance(cells, list) or not cells or len(cells) > 100000:
        raise ValidationError("Expected 1..100000 cells")
    ids, groups, metadata, pairs = set(), {}, {}, defaultdict(dict)
    for cell in cells:
        keys(cell, "id sample donor condition cell_type counts")
        for field in ("id", "sample", "donor", "condition", "cell_type"):
            if not isinstance(cell[field], str) or not cell[field].strip():
                raise ValidationError("Missing cell/sample/donor identity")
        if cell["id"] in ids:
            raise ValidationError("Duplicate cell identity")
        ids.add(cell["id"])
        if cell["cell_type"] != design["cell_type"] or cell["condition"] not in (design["control"], design["treatment"]):
            raise ValidationError("Unexpected cell type or condition; preselect explicitly before freezing")
        sample, donor, condition = cell["sample"], cell["donor"], cell["condition"]
        if sample in metadata and metadata[sample][:2] != [donor, condition]:
            raise ValidationError("A sample maps to conflicting donors/conditions")
        if condition in pairs[donor] and pairs[donor][condition] != sample:
            raise ValidationError("Multiple samples per donor-condition require a separate technical-replicate contract")
        pairs[donor][condition] = sample
        if sample not in groups:
            if (len(groups) + 1) * len(genes) > 2000000:
                raise ValidationError("Pseudobulk matrix exceeds bounded budget")
            groups[sample], metadata[sample] = [0] * len(genes), [donor, condition, 0]
        metadata[sample][2] += 1
        seen = set()
        if not isinstance(cell["counts"], list):
            raise ValidationError("Sparse counts must be index/count pairs")
        for entry in cell["counts"]:
            if not isinstance(entry, list) or len(entry) != 2:
                raise ValidationError("Invalid sparse count entry")
            i, value = entry
            if type(i) is not int or not 0 <= i < len(genes) or i in seen or type(value) is not int or not 0 <= value <= 2**31 - 1:
                raise ValidationError("Counts require unique gene indices and nonnegative raw integers")
            seen.add(i)
            groups[sample][i] += value
    if len(pairs) < 3 or any(set(v) != {design["control"], design["treatment"]} for v in pairs.values()):
        raise ValidationError("At least three complete donor pairs required; missing pairs cannot be silently dropped")
    if any(m[2] < design["min_cells"] for m in metadata.values()):
        raise ValidationError("Sample below frozen minimum cell count; revise prospectively, do not drop it silently")
    kept = sorted((i for i in range(len(genes)) if sum(v[i] for v in groups.values()) >= design["min_total_count"]), key=lambda i: genes[i])
    if not kept:
        raise ValidationError("No genes pass the frozen filter")
    samples = [{"id": s, "donor": metadata[s][0], "condition": metadata[s][1], "cells": metadata[s][2],
                "counts": [groups[s][i] for i in kept]} for s in sorted(groups)]
    if any(sum(s["counts"]) == 0 for s in samples):
        raise ValidationError("Zero-library pseudobulk sample")
    return {"genes": [genes[i] for i in kept], "samples": samples,
            "excluded_genes": sorted(set(genes) - {genes[i] for i in kept}),
            "raw_input_sha256": suite_digest(data), "design_sha256": suite_digest(design),
            "aggregation": "sum_raw_integer_counts_by_sample", "analysis_unit": "declared_donor",
            "independent_units": len(pairs), "donor_identity": "DECLARED_NOT_AUTHENTICATED"}


def fit_reference(design, data):
    """Explicit local reference execution using the installed, version-pinned backend."""
    import importlib.metadata
    try:
        import pandas as pd
        from pydeseq2.dds import DeseqDataSet
        from pydeseq2.ds import DeseqStats
    except ImportError as exc:
        raise ValidationError("Reference fitting requires the optional pseudobulk dependencies; offline verification does not") from exc
    version = importlib.metadata.version("pydeseq2")
    if version != design["backend_version"]:
        raise ValidationError("Installed PyDESeq2 version differs from frozen design")
    pb = aggregate(design, data)
    metadata = pd.DataFrame([{k: row[k] for k in ("id", "donor", "condition")} for row in pb["samples"]]).set_index("id")
    counts = pd.DataFrame([row["counts"] for row in pb["samples"]], index=metadata.index, columns=pb["genes"])
    if not ratio_supported(pb):
        raise ValidationError("Frozen ratio normalization is unavailable: every gene contains a zero; choose and freeze a different method instead of silently switching")
    dds = DeseqDataSet(counts=counts, metadata=metadata, design="~donor + condition", n_cpus=1,
                      refit_cooks=True, size_factors_fit_type="ratio", quiet=True)
    dds.deseq2()
    stats = DeseqStats(dds, contrast=["condition", design["treatment"], design["control"]],
                      alpha=0.05, independent_filter=False, cooks_filter=True, n_cpus=1, quiet=True)
    stats.summary()
    def finite(value):
        return float(value) if math.isfinite(float(value)) else None
    results = []
    for gene, row in stats.results_df.iterrows():
        effect, se = finite(row["log2FoldChange"]), finite(row["lfcSE"])
        results.append({"gene": str(gene), "effect": effect, "standard_error": se,
                        "ci95_lower": effect - 1.959963984540054 * se if effect is not None and se is not None else None,
                        "ci95_upper": effect + 1.959963984540054 * se if effect is not None and se is not None else None,
                        "p_value": finite(row["pvalue"]), "q_value": finite(row["padj"])})
    matrix = dds.obsm["design_matrix"]
    return {"format": "pvl-pseudobulk-result-1", "pseudobulk": pb,
            "method": {"backend": "pydeseq2", "version": version, "formula": "~donor + condition",
                       "contrast": ["condition", design["treatment"], design["control"]],
                       "normalization": "median_of_ratios", "independent_filter": False,
                       "cooks_filter": True, "refit_cooks": True, "alpha": 0.05,
                       "requested_dispersion_trend": "parametric", "observed_dispersion_trend": str(dds.uns["disp_function_type"])},
            "normalization": {str(i): float(v) for i, v in dds.obs["size_factors"].items()},
            "design_matrix": {"columns": list(map(str, matrix.columns)),
                              "rows": {str(i): [float(x) for x in row] for i, row in matrix.iterrows()}},
            "testing_family": list(pb["genes"]), "results": results,
            "conclusion_scope": "within_supplied_donors_and_cell_type",
            "uncertainty": "unshrunk_log2_fold_change_Wald_95_percent; not simultaneous intervals"}


def ratio_supported(pb):
    return any(all(s["counts"][i] > 0 for s in pb["samples"]) for i in range(len(pb["genes"])))


def _canonical(result):
    """Permit ordering changes without permitting omissions, duplicates or relabeling."""
    from copy import deepcopy
    result = deepcopy(result)
    pb = result["pseudobulk"]
    genes = pb["genes"]
    if len(set(genes)) != len(genes) or len({s["id"] for s in pb["samples"]}) != len(pb["samples"]):
        raise ValidationError("Duplicate genes or samples")
    order = sorted(range(len(genes)), key=genes.__getitem__)
    for sample in pb["samples"]:
        if len(sample["counts"]) != len(genes) or any(type(v) is not int or v < 0 for v in sample["counts"]):
            raise ValidationError("Invalid submitted raw aggregate counts")
        sample["counts"] = [sample["counts"][i] for i in order]
    pb["genes"] = sorted(genes)
    pb["samples"].sort(key=lambda s: s["id"])
    pb["excluded_genes"].sort()
    if len(set(result["testing_family"])) != len(result["testing_family"]) or len({r["gene"] for r in result["results"]}) != len(result["results"]):
        raise ValidationError("Duplicate testing family or result gene")
    result["testing_family"].sort()
    result["results"].sort(key=lambda r: r["gene"])
    return result


def _equal(a, b, absolute, relative):
    if type(b) is float:
        return type(a) in (int, float) and math.isfinite(a) and math.isclose(a, b, abs_tol=absolute, rel_tol=relative)
    if type(a) is not type(b):
        return False
    if isinstance(b, dict):
        return set(a) == set(b) and all(_equal(a[k], v, absolute, relative) for k, v in b.items())
    if isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y, absolute, relative) for x, y in zip(a, b))
    return a == b


def check(path, spec, root):
    try:
        design, data, truth = (reference_json(root, spec[k]) for k in ("design", "data", "truth"))
        pb = aggregate(design, data)
        expected = _canonical(truth)
        keys(expected, "format pseudobulk method normalization design_matrix testing_family results conclusion_scope uncertainty")
        if (expected["format"] != "pvl-pseudobulk-result-1" or expected["method"].get("backend") != "pydeseq2"
                or expected["method"].get("version") != design["backend_version"]
                or expected["method"].get("formula") != "~donor + condition"
                or expected["method"].get("contrast") != ["condition", design["treatment"], design["control"]]):
            raise ValidationError("Frozen reference method differs from design")
        if (set(expected["normalization"]) != {s["id"] for s in pb["samples"]}
                or any(number(v) <= 0 for v in expected["normalization"].values())):
            raise ValidationError("Reference needs positive size factors for every sample")
        if expected["pseudobulk"] != pb or expected["testing_family"] != pb["genes"] or [r["gene"] for r in expected["results"]] != pb["genes"]:
            raise ValidationError("Reference does not cover frozen aggregation and full testing family")
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        raise OSError("Invalid frozen pseudobulk reference: " + str(exc)) from exc
    detail = {"task_mode": design["task_mode"], "mismatches": [], "stages": {},
              "independent_units": pb["independent_units"], "testing_family_size": len(pb["genes"]),
              "donor_identity": "DECLARED_NOT_AUTHENTICATED", "backend_execution": "REQUIRES_SEPARATE_COLLECTOR_RECEIPT",
              "reference_review": "NOT_ESTABLISHED_BY_HASH", "biological_generalization": "NOT_TESTED"}
    try:
        submitted = _canonical(load_json(path))
        for name in expected:
            passed = name in submitted and _equal(submitted[name], expected[name], spec["absolute"], spec["relative"])
            detail["stages"][name] = "PASS" if passed else "MISMATCH"
            if not passed:
                detail["mismatches"].append(name)
        if set(submitted) != set(expected):
            detail["mismatches"].append("result_contract")
        if design["task_mode"] == "acceptable_solution":
            # A different valid scientific method needs a reviewer, not reference equality.
            detail["review_required"] = True
            detail["scope"] = "Reference similarity is diagnostic only in acceptable-solution mode"
            if "pseudobulk" in detail["mismatches"]:
                return False, detail
            return None, detail
        detail["scope"] = "Fixed-method computational agreement only; no biological validation"
        return not detail["mismatches"], detail
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        detail["mismatches"].append("malformed_result: " + str(exc))
        return False, detail


def create_reference(design_path, data_path, output):
    """A new, portable scorer package and local execution receipt; never overwrite."""
    from .artifacts import sha
    import shutil
    import uuid
    import warnings
    import importlib.metadata
    output = Path(output)
    if output.exists():
        raise ValidationError("Reference output already exists")
    design, data = load_json(design_path), load_json(data_path)
    aggregate(design, data)  # validate before any expensive fitting
    output.mkdir(parents=True)
    (output / "reference-runner.py").write_bytes(Path(__file__).read_bytes())
    for source, name in ((design_path, "design.json"), (data_path, "data.json")):
        shutil.copyfile(source, output / name)
    write_json(output / "execution.json", {"status": "STARTED", "backend": "pydeseq2", "settlement": "no_model_calls"})
    try:
        with warnings.catch_warnings(record=True) as observed_warnings:
            warnings.simplefilter("always")
            result = fit_reference(design, data)
        if sha(__file__) != sha(output / "reference-runner.py"):
            raise ValidationError("Reference runner changed during execution; preserve this failed attempt")
        write_json(output / "reference.json", result)
        session = "pseudobulk-" + uuid.uuid4().hex
        receipt = {"backend": "pydeseq2", "version": design["backend_version"], "entrypoint": "DeseqDataSet.deseq2/DeseqStats.summary",
                   "fallback": False, "session_id": session, "artifact_sha256": sha(output / "reference.json"),
                   "collector": "pvl-local-reference-runner", "basis": "runtime_observation"}
        write_json(output / "backend-receipt.json", receipt)
        spec = {k: {"path": filename, "sha256": sha(output / filename)} for k, filename in (("design", "design.json"), ("data", "data.json"), ("truth", "reference.json"))}
        spec.update(absolute=1e-7, relative=1e-6)
        write_json(output / "verifier.json", spec)
        write_json(output / "execution.json", {"status": "COMPLETED", "session_id": session,
                   "independent_expert_review": "PENDING", "scope": "local reference computation, not plugin benefit",
                   "spec_sha256": suite_digest(spec), "runner_sha256": sha(output / "reference-runner.py"),
                   "libraries": {name: importlib.metadata.version(name) for name in ("pydeseq2", "numpy", "scipy", "pandas", "anndata", "formulaic")},
                   "warnings": [str(w.message) for w in observed_warnings],
                   "observed_method": result["method"],
                   "fallback_scope": "Receipt fallback=false means no substitute backend; internal fitting changes are retained in observed_method and warnings",
                   "backend_receipt": {"path": "backend-receipt.json", "sha256": sha(output / "backend-receipt.json")}})
        return {"output": str(output.resolve()), "spec_sha256": suite_digest(spec), "session_id": session}
    except Exception as exc:
        write_json(output / "execution.json", {"status": "FAILED", "error": str(exc), "independent_expert_review": "PENDING"})
        raise
