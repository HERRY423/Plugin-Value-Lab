"""Extract a frozen B-cell case from the public Kang/SeuratData count cache.

No download, model call, inferred donor, or gene selection using DE results.
Input provenance is explicitly a local cached derivative, not fresh GEO validation.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.artifacts import sha
from value_lab.core import ValidationError, write_json
from value_lab.pseudobulk import aggregate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("h5ad")
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-cells", type=int, default=20, help="Freeze before model fitting; no automatic sample dropping")
    args = parser.parse_args()
    import anndata
    import numpy as np
    import pydeseq2
    from scipy.sparse import csr_matrix
    output = Path(args.output)
    if output.exists():
        raise ValidationError("Use a new extraction directory")
    obj = anndata.read_h5ad(args.h5ad)
    required = ("donor", "condition", "geo_cell_type")
    if any(c not in obj.obs or obj.obs[c].isna().any() for c in required):
        raise ValidationError("Missing public donor/condition/cell-type metadata")
    subset = obj[obj.obs["geo_cell_type"] == "B cells"].copy()
    matrix = csr_matrix(subset.X)
    matrix.sum_duplicates()
    if not np.isfinite(matrix.data).all() or (matrix.data < 0).any() or not np.equal(matrix.data, np.floor(matrix.data)).all():
        raise ValidationError("X does not contain nonnegative integer counts")
    data = {"format": "pvl-cell-counts-1", "genes": list(map(str, subset.var_names)), "cells": [],
            "provenance": {"accession": "GSE96583", "source": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE96583",
                           "material": "local cached SeuratData/GEO derivative", "source_file_sha256": sha(args.h5ad),
                           "selected_cell_type": "B cells", "selection": "all cached B cells; all cached genes before prespecified count filter",
                           "raw_source_revalidated": False, "independent_expert_review": "PENDING"}}
    for i, (cell, row) in enumerate(subset.obs.iterrows()):
        donor, condition = str(row["donor"]), str(row["condition"])
        values = matrix.getrow(i)
        data["cells"].append({"id": str(cell), "sample": donor + "_" + condition, "donor": donor,
                              "condition": condition, "cell_type": "B cells",
                              "counts": [[int(j), int(v)] for j, v in zip(values.indices, values.data) if v]})
    design = {"format": "pvl-pseudobulk-design-1", "task_mode": "fixed_method", "cell_type": "B cells",
              "control": "ctrl", "treatment": "stim", "min_cells": args.min_cells, "min_total_count": 10,
              "backend_version": pydeseq2.__version__,
              "reference_workflow": "https://pydeseq2.readthedocs.io/en/stable/auto_examples/plot_minimal_pydeseq2_pipeline.html"}
    pb = aggregate(design, data)
    output.mkdir(parents=True)
    # Compact JSON keeps the public sparse count artifact small.
    (output / "data.json").write_text(json.dumps(data, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    write_json(output / "design.json", design)
    write_json(output / "extraction.json", {"cells": len(data["cells"]), "donors": pb["independent_units"],
               "samples": len(pb["samples"]), "input_genes": len(data["genes"]), "tested_genes": len(pb["genes"]),
               "source_sha256": sha(args.h5ad), "data_sha256": sha(output / "data.json"),
               "design_sha256": sha(output / "design.json"), "scope": "public cached data, local extraction; no independent review"})
    print(json.dumps({"output": str(output), "donors": pb["independent_units"], "tested_genes": len(pb["genes"])}))


if __name__ == "__main__":
    main()
