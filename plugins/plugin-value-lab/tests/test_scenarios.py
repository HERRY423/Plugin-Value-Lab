from copy import deepcopy
import json
import importlib.util
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest

from value_lab.artifacts import sha
from value_lab.core import ValidationError, demo_suite, evaluate, suite_digest, write_json
from value_lab.scenarios import validate_pack, prepare_suite, stage_case, grade_scenario
from value_lab.report import write_reports
from value_lab.native import export_claude
from value_lab.registry import register_study, export_entry, replay_bundle


def fixture(root):
    """Public teaching fixture; not a scientific dataset or a secret benchmark."""
    inputs, scorers = root / "inputs", root / "scorers"
    inputs.mkdir()
    scorers.mkdir()
    (inputs / "cells.csv").write_text("cell,value\nc1,1\nc2,2", encoding="utf-8")
    cases = []
    for case_id, expected in (("sufficient", "allow"), ("insufficient", "withhold")):
        truth = scorers / (case_id + "-decision.json")
        write_json(truth, {"decision": expected, "rationale": "Synthetic criterion for transport tests only"})
        private = {"type": "ScorerOnlyGroundTruth", "case_id": case_id, "evidence_type": "synthetic",
            "nonce": secrets.token_hex(32), "rationale": "Teaching example; not expert-validated",
            "graders": [{"id": "decision", "type": "over_refusal" if expected == "allow" else "abstention_correct",
                "artifact": "decision", "verifier": {"truth": {"path": truth.name, "sha256": sha(truth)}}}]}
        path = scorers / (case_id + ".json")
        write_json(path, private)
        cases.append({"type": "AgentVisibleScenario", "id": case_id, "family": case_id,
            "split": "development" if expected == "allow" else "heldout", "prompt": "Synthetic task " + case_id,
            "inputs": {"cells.csv": sha(inputs / "cells.csv")}, "outputs": {"decision": "decision.json"},
            "scorer": {"path": path.name, "sha256": sha(path)}})
    pack = {"format": "pvl-scenario-pack-1", "id": "fixture", "evidence_type": "synthetic",
        "sources": [{"url": "synthetic:local-fixture", "license": "MIT", "provenance": "Manufactured test data"}],
        "scenarios": cases}
    return pack, inputs, scorers


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pack, self.inputs, self.scorers = fixture(self.root)
        self.suite = prepare_suite(self.pack, demo_suite())

    def records(self):
        records = []
        for case in self.suite["cases"]:
            path = self.root / (case["id"] + "-output.json")
            write_json(path, {"decision": "allow"})
            for arm in ("with", "without"):
                for rep in range(1, 4):
                    records.append({"case_id": case["id"], "arm": arm, "repetition": rep, "status": "completed",
                        "source": "synthetic", "suite_sha256": suite_digest(self.suite), "conditions": self.suite["conditions"],
                        "session_id": f'{case["id"]}-{arm}-{rep}', "plugin_loaded": arm == "with", "output": "claimed success",
                        "artifacts": {"decision": {"path": path.name, "sha256": sha(path)}},
                        "cost": {"model_usd": 0, "tool_usd": 0, "human_minutes": 0}, "duration_seconds": 1, "human_intervals": []})
        return records

    def report(self, records):
        lock = {"suite_sha256": suite_digest(self.suite)}
        return evaluate(self.suite, records, lock, artifact_root=self.root, verifier_root=self.scorers)

    def test_public_staging_has_no_answers_or_private_rules(self):
        checked = validate_pack(self.pack, self.inputs, self.scorers)
        self.assertTrue(checked["scorers_checked"])
        dest = self.root / "agent"
        stage_case(self.pack, "sufficient", self.inputs, dest, self.scorers)
        self.assertEqual({p.name for p in dest.iterdir()}, {"cells.csv", "scenario.json"})
        text = (dest / "scenario.json").read_text()
        self.assertNotIn("scorer", text)
        self.assertNotIn("over_refusal", json.dumps(self.suite))
        with self.assertRaises(ValidationError):
            stage_case(self.pack, "sufficient", self.inputs, dest, self.scorers)

    def test_family_leakage_duplicates_and_private_bytes_are_rejected(self):
        bad = deepcopy(self.pack)
        bad["scenarios"][1]["family"] = bad["scenarios"][0]["family"]
        with self.assertRaises(ValidationError):
            validate_pack(bad)
        bad = deepcopy(self.pack)
        bad["scenarios"][1]["prompt"] = bad["scenarios"][0]["prompt"]
        with self.assertRaises(ValidationError):
            validate_pack(bad)
        bad = deepcopy(self.pack)
        bad["scenarios"][0]["inputs"]["disguised.csv"] = sha(self.scorers / "sufficient-decision.json")
        with self.assertRaises(ValidationError):
            validate_pack(bad, scorer_root=self.scorers)

    def test_tampered_input_never_leaves_partial_agent_directory(self):
        (self.inputs / "cells.csv").write_text("tampered")
        dest = self.root / "agent"
        with self.assertRaises(OSError):
            stage_case(self.pack, "sufficient", self.inputs, dest, self.scorers)
        self.assertFalse(dest.exists())

    def test_nested_or_linked_output_paths_rejected(self):
        with self.assertRaises(ValidationError):
            stage_case(self.pack, "sufficient", self.inputs, self.inputs / "stage", self.scorers)
        bad = deepcopy(self.pack)
        bad["scenarios"][0]["outputs"]["decision"] = "../leak.json"
        with self.assertRaises(ValidationError):
            validate_pack(bad)

    def test_unknowns_and_errors_keep_full_denominators_and_render(self):
        records = self.records()
        records.pop()
        records.append(deepcopy(records[0]))
        report = self.report(records)
        metrics = report["scientific_errors"]["metrics"]
        heldout = next(m for m in metrics if m["split"] == "heldout" and m["arm"] == "without")
        self.assertEqual((heldout["planned"], heldout["errors"], heldout["unknown"]), (3, 2, 1))
        self.assertIsNone(heldout["rate"])
        dev = next(m for m in metrics if m["split"] == "development" and m["arm"] == "with")
        self.assertEqual(dev["unknown"], 1)
        write_reports(report, self.root / "report")
        self.assertIn("误拒", (self.root / "report/report.html").read_text(encoding="utf-8"))
        self.assertEqual(report["verdict"], "SIMULATION_ONLY")

    def test_missing_or_tampered_private_key_is_unknown_not_success(self):
        g = self.suite["cases"][0]["graders"][0]
        record = self.records()[0]
        self.assertIsNone(grade_scenario(g, record, self.root, None)[0])
        (self.scorers / "sufficient.json").write_text("tampered")
        self.assertIsNone(grade_scenario(g, record, self.root, self.scorers)[0])
        report = self.report([record])
        self.assertTrue(report["scientific_errors"]["unavailable_cases"])

    def test_synthetic_scorer_cannot_be_laundered_by_suite_declaration(self):
        self.suite["evidence_type"] = "local"
        self.assertEqual(self.report([])["verdict"], "SIMULATION_ONLY")

    def test_claude_does_not_silently_replace_scientific_checks(self):
        with self.assertRaises(ValidationError):
            export_claude(self.suite, self.root / "native", self.root / "plugin")

    def test_cli_validation_preparation_and_staging(self):
        write_json(self.root / "pack.json", self.pack)
        write_json(self.root / "template.json", demo_suite())
        cli = Path(__file__).resolve().parents[1] / "scripts/value_lab.py"
        for args in [
            ["scenario-validate", "pack.json", "--inputs", "inputs", "--scorers", "scorers"],
            ["scenario-prepare", "pack.json", "--template", "template.json", "--output", "suite.json"],
            ["scenario-stage", "pack.json", "--case", "sufficient", "--inputs", "inputs", "--output", "agent", "--scorers", "scorers"]]:
            result = subprocess.run([sys.executable, str(cli), *args], cwd=self.root, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "agent/sufficient.json").exists())

    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "optional schema dependency")
    def test_exchange_schema_accepts_public_contract_only(self):
        from jsonschema import Draft202012Validator, ValidationError as SchemaError
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/science/scenario-pack.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        validator.validate(self.pack)
        bad = deepcopy(self.pack)
        bad["scenarios"][0]["answer"] = "allow"
        with self.assertRaises(SchemaError):
            validator.validate(bad)

    def test_registry_replay_requires_separate_scorers_and_does_not_export_them(self):
        study = self.root / "study"
        study.mkdir()
        records = self.records()
        write_json(study / "suite.json", self.suite)
        write_json(study / "protocol.lock.json", {"suite_sha256": suite_digest(self.suite)})
        (study / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
        metadata = {"observed_at": "2026-09-23T00:00:00Z", "authors": [{"id": "Synthetic tester", "organization": "Fixture"}],
                    "plugin_sha256": "a" * 64, "limitations": "Synthetic only"}
        registry, bundle = self.root / "registry", self.root / "bundle"
        entry = register_study(study, metadata, registry, artifact_root=self.root, verifier_root=self.scorers)
        export_entry(registry, entry["entry_id"], bundle)
        scorer_hashes = {sha(p) for p in self.scorers.iterdir()}
        self.assertFalse(scorer_hashes & {sha(p) for p in bundle.rglob("*") if p.is_file()})
        self.assertEqual(replay_bundle(bundle, verifier_root=self.scorers)["status"], "REPRODUCED")
        self.assertNotEqual(replay_bundle(bundle)["status"], "REPRODUCED")


if __name__ == "__main__":
    unittest.main()
