"""Independent array/BH/metadata cross-checks for a local Kang reference run."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.artifacts import sha
from value_lab.core import load_json, write_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("reference")
    p.add_argument("--h5ad", required=True)
    p.add_argument("--geo-metadata", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    import anndata
    import numpy as np
    import pandas as pd
    from scipy.stats import false_discovery_control, norm
    root = Path(args.reference)
    result = load_json(root / "reference.json")
    data = load_json(root / "data.json")
    if Path(args.output).exists():
        raise ValueError("Preserve previous cross-checks")
    source = anndata.read_h5ad(args.h5ad)
    geo = pd.read_csv(args.geo_metadata, sep="\t", index_col=0)
    matched = 0
    for cell in data["cells"]:
        # The supplied SeuratData derivative changes GEO barcode '-' to '.'.
        barcode = cell["id"].replace(".", "-")
        row = geo.loc[barcode]
        assert str(row["ind"]) == cell["donor"] and row["stim"] == cell["condition"] and row["cell"] == cell["cell_type"]
        matched += 1
    pb = result["pseudobulk"]
    for sample in pb["samples"]:
        mask = ((source.obs.donor.astype(str) == sample["donor"]) & (source.obs.condition.astype(str) == sample["condition"]) &
                (source.obs.geo_cell_type.astype(str) == "B cells"))
        expected = np.asarray(source[mask, pb["genes"]].X.sum(axis=0)).ravel()
        assert np.array_equal(expected, sample["counts"])
        assert int(mask.sum()) == sample["cells"]
    values = [(r["p_value"], r["q_value"]) for r in result["results"] if r["p_value"] is not None]
    actual = np.array([v[1] for v in values], dtype=float)
    expected = false_discovery_control(np.array([v[0] for v in values]), method="bh")
    assert np.allclose(actual, expected, rtol=1e-12, atol=1e-14)
    ci = 0
    for row in result["results"]:
        if row["effect"] is not None and row["standard_error"] is not None:
            assert np.isclose(row["ci95_lower"], row["effect"] - norm.ppf(.975)*row["standard_error"], rtol=1e-12, atol=1e-14)
            assert np.isclose(row["ci95_upper"], row["effect"] + norm.ppf(.975)*row["standard_error"], rtol=1e-12, atol=1e-14)
            ci += 1
    report = {"status": "PASSED", "geo_metadata_cells_matched": matched, "pseudobulk_samples_reaggregated": len(pb["samples"]),
              "bh_values_crosschecked": len(values), "wald_intervals_crosschecked": ci,
              "source_h5ad_sha256": sha(args.h5ad), "geo_metadata_sha256": sha(args.geo_metadata),
              "reference_sha256": sha(root / "reference.json"), "scope": "Independent implementations of aggregation/BH/interval arithmetic on local public caches; no independent count-model fit or expert review"}
    write_json(args.output, report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
