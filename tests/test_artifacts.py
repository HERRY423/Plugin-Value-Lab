from copy import deepcopy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from value_lab.artifacts import grade_artifact, sha
from value_lab.core import ValidationError, demo_suite, demo_records, evaluate, validate_suite


class ArtifactTests(unittest.TestCase):
    def test_frozen_testing_family_rejects_selective_reporting_even_with_correct_bh(self):
        from value_lab.core import write_json
        truth = self.root / "scorer"
        truth.mkdir()
        write_json(truth / "family.json", {"ids": ["a", "b", "c", "d"]})
        self.rule["verifier"]["testing_family"] = {"path": "family.json", "sha256": sha(truth / "family.json")}
        record = self.record("gene,p,q,effect\na,0.01,0.03,2\nb,0.04,0.06,-1\nc,0.2,0.2,0")
        self.assertFalse(self.grade(record, truth)[0])
        record = self.record("gene,p,q,effect\na,0.01,0.04,2\nb,0.04,0.08,-1\nc,0.2,0.2666666666666667,0\nd,0.9,0.9,0")
        passed, _, receipt = self.grade(record, truth)
        self.assertTrue(passed)
        self.assertEqual(receipt["testing_family_scope"], "FROZEN_REFERENCE")
        self.assertIsNone(self.grade(record)[0])
        write_json(truth / "family.json", {"ids": ["a", "b", "c"]})
        self.assertIsNone(self.grade(record, truth)[0])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rule = {"id": "check", "type": "artifact", "artifact": "result", "dimension": "outcome",
                     "weight": 1, "critical": True, "verifier": {"kind": "de_table", "id_column": "gene",
                     "p_column": "p", "q_column": "q", "effect_column": "effect", "min_rows": 3, "bh_tolerance": 1e-9}}

    def record(self, text, filename="result.csv"):
        path = self.root / filename
        path.write_text(text, encoding="utf-8")
        return {"output": "Everything passed", "artifacts": {"result": {"path": filename, "sha256": sha(path)}}}

    def grade(self, record, verifier_root=None):
        return grade_artifact(self.rule, record, self.root, verifier_root)

    def test_bh_math_and_entity_integrity(self):
        for rows, expected in [
            ("a,0.01,0.03,2\nb,0.04,0.06,-1\nc,0.2,0.2,0", True),
            ("a,0.01,0.01,2\nb,0.04,0.04,-1\nc,0.2,0.2,0", False),
            ("a,0.01,0.03,2\na,0.04,0.06,-1\nc,0.2,0.2,0", False),
            ("a,0.01,0.03,nan\nb,0.04,0.06,-1\nc,0.2,0.2,0", False)]:
            with self.subTest(rows=rows):
                self.assertIs(self.grade(self.record("gene,p,q,effect\n" + rows))[0], expected)

    def test_missing_tampered_traversal_and_text_forgery(self):
        record = self.record("gene,p,q,effect\na,0.01,0.03,2\nb,0.04,0.06,-1\nc,0.2,0.2,0")
        (self.root / "result.csv").write_text("changed")
        self.assertIsNone(self.grade(record)[0])
        record["grades"] = {"check": {"passed": True}}
        self.assertIsNone(grade_artifact(self.rule, record, None)[0])
        record["artifacts"]["result"]["path"] = "../outside.csv"
        self.assertIsNot(self.grade(record)[0], True)

    def test_labels_require_exact_ids_and_coverage(self):
        self.rule["verifier"] = {"kind": "labels", "id_column": "cell", "label_column": "type",
                                 "expected": {"c1": "T", "c2": "B"}}
        self.assertTrue(self.grade(self.record("cell,type\nc2,B\nc1,T"))[0])
        self.assertFalse(self.grade(self.record("cell,type\nc1,T\nc2,T"))[0])
        self.assertFalse(self.grade(self.record("cell,type\nc1,T"))[0])

    def test_json_typed_equality_and_invalid_numbers(self):
        self.rule["verifier"] = {"kind": "json_fields", "expected": {"result": True}}
        self.assertFalse(self.grade(self.record('{"result":1}', "result.json"))[0])
        self.assertTrue(self.grade(self.record('{"result":true}', "result.json"))[0])
        self.assertFalse(self.grade(self.record('{"result":NaN}', "result.json"))[0])

    def test_invalid_json_diagnostic_replays_after_relocation(self):
        self.rule["verifier"] = {"kind": "json_fields", "expected": {"result": True}}
        record = self.record("API Error: output token maximum", "result.json")
        first = self.grade(record)
        relocated = self.root / "relocated"
        relocated.mkdir()
        (relocated / "result.json").write_bytes((self.root / "result.json").read_bytes())
        self.assertFalse(first[0])
        self.assertEqual(first, grade_artifact(self.rule, record, relocated))
        self.assertNotIn(str(self.root), first[1])

    def test_registry_replays_invalid_json_artifacts_without_rewriting_failure(self):
        import json
        from value_lab.core import freeze, write_json
        from value_lab.registry import register_study, export_entry, replay_bundle
        self.rule["verifier"] = {"kind": "json_fields", "expected": {"result": True}}
        material = self.record("API Error: output token maximum", "result.json")
        suite = demo_suite()
        suite["cases"][0]["graders"] = [self.rule]
        records = demo_records(suite)
        for record in records:
            record["artifacts"] = deepcopy(material["artifacts"])
        study = self.root / "study"
        write_json(study / "suite.json", suite)
        freeze(suite, study / "protocol.lock.json")
        (study / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        meta = {"observed_at": "2026-09-23T07:00:00Z", "authors": [{"id": "fixture", "organization": "fixture"}],
                "plugin_sha256": "a" * 64, "limitations": "Synthetic relocation regression fixture"}
        registry = self.root / "registry"
        receipt = register_study(study, meta, registry, artifact_root=self.root)
        bundle = self.root / "export"
        export_entry(registry, receipt["entry_id"], bundle)
        replay = replay_bundle(bundle)
        self.assertEqual(replay["status"], "REPRODUCED")
        self.assertFalse(replay["report"]["cases"][0]["runs"][0]["grades"][0]["passed"])

    def test_executable_pinned_code_timeout_crash_and_protocol(self):
        record = self.record("input")
        program = self.root / "verify.py"
        self.rule.update(type="executable", verifier={"path": "verify.py", "sha256": "0" * 64, "timeout_seconds": 1})
        for code, expected in [
            ('print(\'{"passed": true, "rationale": "checked"}\')', True),
            ('print(\'{"passed": false, "rationale": "bad artifact"}\')', False),
            ('print(\'{"passed": 1, "rationale": "invalid"}\')', None),
            ('raise RuntimeError("broken checker")', None),
            ('import time; time.sleep(5)', None)]:
            with self.subTest(code=code):
                program.write_text(code, encoding="utf-8")
                self.rule["verifier"]["sha256"] = sha(program)
                self.assertIs(self.grade(record, self.root)[0], expected)
        self.assertIsNone(self.grade(record)[0])
        program.write_text("print('changed')")
        self.assertIsNone(self.grade(record, self.root)[0])

    def test_evaluate_requires_bytes_and_keeps_receipt(self):
        suite = demo_suite()
        suite["cases"][0]["graders"] = [self.rule]
        validate_suite(suite)
        records = demo_records(suite)
        material = self.record("gene,p,q,effect\na,0.01,0.03,2\nb,0.04,0.06,-1\nc,0.2,0.2,0")
        for record in records:
            record["artifacts"] = deepcopy(material["artifacts"])
        missing = evaluate(suite, records)
        self.assertIsNone(missing["cases"][0]["with_score"])
        report = evaluate(suite, records, artifact_root=self.root)
        self.assertEqual(report["cases"][0]["with_score"], 1)
        self.assertEqual(report["verdict"], "SIMULATION_ONLY")
        self.assertIn("artifact_sha256", report["cases"][0]["runs"][0]["grades"][0]["verification"])

    def test_validation_refuses_unknown_contract_and_duplicate_rules(self):
        suite = demo_suite()
        suite["cases"][0]["graders"] = [self.rule, dict(self.rule, id="duplicate")]
        with self.assertRaises(ValidationError):
            validate_suite(suite)
        suite["cases"][0]["graders"] = [self.rule]
        self.rule["verifier"]["bh_tolerance"] = float("nan")
        with self.assertRaises(ValidationError):
            validate_suite(suite)

    @unittest.skipUnless(importlib.util.find_spec("anndata"), "optional science dependency")
    def test_h5ad_reads_real_file_structure(self):
        import anndata
        import numpy as np
        data = anndata.AnnData(np.zeros((2, 3)))
        data.obs["cell_type"] = ["T", "B"]
        path = self.root / "test.h5ad"
        data.write_h5ad(path)
        self.rule["verifier"] = {"kind": "h5ad", "n_obs": 2, "n_vars": 3, "obs_columns": ["cell_type"], "var_names_unique": True}
        record = {"artifacts": {"result": {"path": "test.h5ad", "sha256": sha(path)}}}
        self.assertTrue(self.grade(record)[0])
        self.rule["verifier"]["n_obs"] = 3
        self.assertFalse(self.grade(record)[0])
