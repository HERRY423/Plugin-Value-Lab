"""Small manufactured contracts, independent aggregation arithmetic and mutation attacks."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from value_lab.artifacts import grade_artifact, sha, validate_verifier
from value_lab.core import ValidationError, write_json
from value_lab.pseudobulk import aggregate, check
from value_lab.pseudobulk_corpus import evaluate_corpus


def fixture():
    design = {"format": "pvl-pseudobulk-design-1", "task_mode": "fixed_method", "cell_type": "B cells",
              "control": "ctrl", "treatment": "stim", "min_cells": 2, "min_total_count": 10,
              "backend_version": "0.5.4", "reference_workflow": "manufactured unit-test fixture; not backend execution"}
    data = {"format": "pvl-cell-counts-1", "genes": ["g1", "g2", "low"], "cells": [], "provenance": {"synthetic": True}}
    for donor in ("a", "b", "c"):
        for condition in ("ctrl", "stim"):
            for i in range(2):
                data["cells"].append({"id": donor + condition + str(i), "sample": donor + condition, "donor": donor,
                    "condition": condition, "cell_type": "B cells", "counts": [[0, i+1], [1, i+3]]})
    pb = aggregate(design, data)
    reference = {"format": "pvl-pseudobulk-result-1", "pseudobulk": pb,
                 "method": {"backend": "pydeseq2", "version": "0.5.4", "formula": "~donor + condition", "contrast": ["condition", "stim", "ctrl"]},
                 "normalization": {s["id"]: 1.0 for s in pb["samples"]}, "design_matrix": {"columns": ["test"], "rows": {}},
                 "testing_family": pb["genes"], "results": [{"gene": g, "effect": 1.0, "standard_error": .2, "ci95_lower": .6,
                 "ci95_upper": 1.4, "p_value": .01, "q_value": .01} for g in pb["genes"]],
                 "conclusion_scope": "within_supplied_donors_and_cell_type", "uncertainty": "manufactured"}
    return design, data, reference


class PseudobulkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.design, self.data, self.truth = fixture()

    def material(self):
        spec = {"absolute": 1e-7, "relative": 1e-6}
        for key, obj in (("design", self.design), ("data", self.data), ("truth", self.truth)):
            path = self.root / (key + ".json")
            write_json(path, obj)
            spec[key] = {"path": path.name, "sha256": sha(path)}
        write_json(self.root / "spec.json", spec)
        return spec

    def test_exact_aggregation_not_cell_replication(self):
        pb = aggregate(self.design, self.data)
        self.assertEqual(pb["independent_units"], 3)
        self.assertEqual(pb["excluded_genes"], ["low"])
        self.assertTrue(all(s["counts"] == [3, 7] and s["cells"] == 2 for s in pb["samples"]))

    def test_frozen_ratio_normalization_cannot_silently_switch(self):
        from value_lab.pseudobulk import ratio_supported
        pb = aggregate(self.design, self.data)
        self.assertTrue(ratio_supported(pb))
        pb["samples"][0]["counts"] = [0, 0]
        self.assertFalse(ratio_supported(pb))

    def test_reference_method_conflict_is_measurement_failure(self):
        self.truth["method"]["formula"] = "~condition"
        spec = self.material()
        write_json(self.root / "result.json", self.truth)
        with self.assertRaises(OSError):
            check(self.root / "result.json", spec, self.root)

    def test_missing_donor_duplicate_cell_and_noninteger_counts_rejected(self):
        for mutate in (lambda d: d["cells"][0].update(donor=""), lambda d: d["cells"].append(d["cells"][0]),
                       lambda d: d["cells"][0].update(counts=[[0, .5]]), lambda d: d["cells"][0].update(counts=[[0, -1]]),
                       lambda d: d["cells"][0].update(counts=[[0, True]]), lambda d: d["cells"][0].update(counts=[[0, 1], [0, 2]])):
            data = deepcopy(self.data)
            mutate(data)
            with self.assertRaises(ValidationError):
                aggregate(self.design, data)

    def test_sample_donor_conflict_and_missing_pair(self):
        self.data["cells"][0]["donor"] = "another"
        with self.assertRaises(ValidationError):
            aggregate(self.design, self.data)
        self.design, self.data, _ = fixture()
        self.data["cells"] = [c for c in self.data["cells"] if c["sample"] != "astim"]
        with self.assertRaises(ValidationError):
            aggregate(self.design, self.data)

    def test_technical_split_not_independent_donor(self):
        self.data["cells"][0]["sample"] = "technical_split"
        with self.assertRaises(ValidationError):
            aggregate(self.design, self.data)

    def test_controlled_corpus_checks_valid_and_invalid_variants(self):
        self.material()
        report = evaluate_corpus(self.root / "spec.json", self.root, self.root / "corpus")
        self.assertEqual((report["positive_cases"], report["negative_cases"]), (4, 13))
        self.assertEqual((report["false_accepts"], report["false_rejects"], report["unresolved"]), (0, 0, 0))

    def test_acceptable_solution_does_not_reject_alternative_backend(self):
        self.design["task_mode"] = "acceptable_solution"
        self.truth["pseudobulk"] = aggregate(self.design, self.data)
        spec = self.material()
        result = deepcopy(self.truth)
        result["method"]["backend"] = "edgeR"
        write_json(self.root / "result.json", result)
        passed, detail = check(self.root / "result.json", spec, self.root)
        self.assertIsNone(passed)
        self.assertTrue(detail["review_required"])
        result["pseudobulk"]["independent_units"] = 12
        write_json(self.root / "result.json", result)
        self.assertFalse(check(self.root / "result.json", spec, self.root)[0])

    def test_bad_reference_is_measurement_failure_not_bad_submission(self):
        spec = self.material()
        write_json(self.root / "result.json", self.truth)
        (self.root / "truth.json").write_text("{}")
        grader = {"id": "chain", "type": "pseudobulk_chain", "artifact": "result", "verifier": spec}
        validate_verifier(grader)
        result = grade_artifact(grader, {"artifacts": {"result": {"path": "result.json", "sha256": sha(self.root / "result.json")}}}, self.root, self.root)
        self.assertIsNone(result[0])

    def test_frozen_reference_must_cover_entire_family(self):
        self.truth["results"].pop()
        spec = self.material()
        write_json(self.root / "result.json", self.truth)
        with self.assertRaises(OSError):
            check(self.root / "result.json", spec, self.root)

    def test_malformed_submission_fails_without_crashing(self):
        spec = self.material()
        for obj in ({}, [], {"pseudobulk": None}):
            write_json(self.root / "result.json", obj)
            self.assertFalse(check(self.root / "result.json", spec, self.root)[0])

    def test_scenario_export_and_stage_keep_answers_separate(self):
        from value_lab.core import load_json
        from value_lab.pseudobulk_corpus import scenario_pack
        from value_lab.scenarios import validate_pack, stage_case
        self.material()
        out = self.root / "scenario"
        scenario_pack(self.root / "spec.json", self.root, out)
        pack = load_json(out / "pack.json")
        validate_pack(pack, out / "inputs", out / "scorers")
        stage = self.root / "agent"
        stage_case(pack, "donor-pseudobulk", out / "inputs", stage, out / "scorers")
        self.assertFalse((stage / "truth.json").exists())
        self.assertEqual(pack["scenarios"][0]["split"], "development")
        self.assertNotIn("results", load_json(stage / "output-contract.json"))


if __name__ == "__main__":
    unittest.main()
