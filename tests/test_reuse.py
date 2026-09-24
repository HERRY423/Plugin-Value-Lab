"""Portable offline reuse, tampering, missing evidence and honest external claims."""
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from value_lab.core import ValidationError, demo_suite, demo_records, suite_digest, write_json, load_json
from value_lab.cli import write_records
from value_lab.artifacts import sha
from value_lab.reuse import prepare_reuse, verify_reuse, replay_reuse, export_scorers, inspect_receipt


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.study = self.root / "study"
        self.study.mkdir()
        self.suite = demo_suite()
        self.records = demo_records(self.suite)
        self.scorers = self.root / "private"
        self.scorers.mkdir()
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()

    def save(self):
        digest = suite_digest(self.suite)
        write_json(self.study / "suite.json", self.suite)
        write_json(self.study / "protocol.lock.json", {"suite_sha256": digest})
        for r in self.records:
            r["suite_sha256"] = digest
        write_records(self.study / "runs.jsonl", self.records)

    def prepare(self):
        self.save()
        out = self.root / "handoff"
        result = prepare_reuse(self.study, out, artifact_root=self.artifacts, verifier_root=self.scorers)
        return out, result["package_id"]

    def artifact_case(self):
        write_json(self.scorers / "truth.json", {"decision": "withhold", "rationale": "Manufactured fixture"})
        self.suite["cases"][0]["graders"] = [{"id": "decision", "type": "abstention_correct", "artifact": "decision", "dimension": "outcome", "critical": True, "weight": 1,
            "verifier": {"truth": {"path": "truth.json", "sha256": sha(self.scorers / "truth.json")}}}]
        write_json(self.artifacts / "answer.json", {"decision": "withhold"})
        for r in self.records:
            if r["case_id"] == self.suite["cases"][0]["id"]:
                r["artifacts"] = {"decision": {"path": "answer.json", "sha256": sha(self.artifacts / "answer.json")}}

    def test_relocated_replay_is_same_observations_not_replication(self):
        package, pid = self.prepare()
        moved = self.root / "moved"
        shutil.copytree(package, moved)
        receipt = replay_reuse(moved, pid, self.root / "replayed")
        self.assertEqual(receipt["status"], "REPRODUCED")
        self.assertEqual((receipt["new_observations"], receipt["new_independent_samples"]), (0, 0))
        self.assertEqual(receipt["independent_reuse"], "NOT_ESTABLISHED")
        self.assertEqual(load_json(self.root / "replayed/report.json")["evidence_type"], "synthetic")

    def test_missing_and_failed_runs_stay_missing_and_failed(self):
        self.records[0].update(status="timeout", error="manufactured timeout")
        self.records.pop()
        package, pid = self.prepare()
        receipt = replay_reuse(package, pid, self.root / "replayed")
        self.assertEqual(receipt["status"], "REPRODUCED")
        self.assertFalse(receipt["assessment_complete"])
        report = load_json(self.root / "replayed/report.json")
        statuses = [r["status"] for c in report["cases"] for r in c["runs"]]
        self.assertIn("timeout", statuses)
        self.assertIn("missing", statuses)

    def test_wrong_pinned_id_and_modified_report_rejected(self):
        package, pid = self.prepare()
        with self.assertRaises(ValidationError):
            verify_reuse(package, "0"*64)
        write_json(package / "report.json", {})
        with self.assertRaises(ValidationError):
            verify_reuse(package, pid)

    def test_unlisted_files_rejected(self):
        package, pid = self.prepare()
        (package / "unexpected.py").write_text("raise RuntimeError('never execute')")
        with self.assertRaises(ValidationError):
            replay_reuse(package, pid, self.root / "replayed")

    def test_scorers_are_separate_and_allowlisted(self):
        self.artifact_case()
        (self.scorers / "private-unrelated.txt").write_text("do not export")
        package, pid = self.prepare()
        self.assertFalse((package / "truth.json").exists())
        output = self.root / "scorer-transfer"
        export_scorers(package, pid, self.scorers, output)
        self.assertEqual({p.name for p in output.iterdir()}, {"truth.json"})
        receipt = replay_reuse(package, pid, self.root / "replayed", verifier_root=output)
        self.assertEqual(receipt["status"], "REPRODUCED")

    def test_missing_reference_returns_materials_required_not_success(self):
        self.artifact_case()
        package, pid = self.prepare()
        receipt = replay_reuse(package, pid, self.root / "replayed")
        self.assertEqual(receipt["status"], "MATERIALS_REQUIRED")
        self.assertFalse(receipt["same_report"])

    def test_executable_grader_not_executed(self):
        self.suite["cases"][0]["graders"] = [{"id": "code", "type": "executable", "artifact": "result", "dimension": "outcome", "critical": True, "weight": 1,
                "verifier": {"path": "code.py", "sha256": "a"*64, "timeout_seconds": 1}}]
        self.save()
        with self.assertRaises(ValidationError):
            prepare_reuse(self.study, self.root / "handoff")

    def test_engine_or_runtime_change_does_not_claim_identical_replay(self):
        package, pid = self.prepare()
        with patch("value_lab.reuse.engine_digest", return_value="c"*64):
            receipt = replay_reuse(package, pid, self.root / "replayed")
        self.assertEqual(receipt["status"], "REPLAY_DIFFERS")
        self.assertTrue(receipt["same_report"])

    def test_external_declaration_is_not_independence_authentication(self):
        package, pid = self.prepare()
        declaration = {"operator": "SYNTHETIC-TEST-PARTICIPANT", "relationship": "self_reported_external", "feedback": "Manufactured test, not actual adoption"}
        replay = self.root / "replayed"
        receipt = replay_reuse(package, pid, replay, participant=declaration)
        self.assertEqual(receipt["independent_reuse"], "SELF_REPORTED_NOT_AUTHENTICATED")
        inspected = inspect_receipt(package, pid, replay)
        self.assertFalse(inspected["participant_authenticated"])
        self.assertEqual(inspected["independent_reuse"], "NOT_ESTABLISHED")
        self.assertEqual(inspected["participant"]["feedback"], declaration["feedback"])

    def test_forged_received_status_and_extra_samples_rejected(self):
        package, pid = self.prepare()
        replay = self.root / "replayed"
        receipt = replay_reuse(package, pid, replay)
        receipt["new_independent_samples"] = 1
        write_json(replay / "receipt.json", receipt)
        with self.assertRaises(ValidationError):
            inspect_receipt(package, pid, replay)

    def test_existing_output_and_nested_export_rejected(self):
        package, pid = self.prepare()
        with self.assertRaises(ValidationError):
            replay_reuse(package, pid, package)
        with self.assertRaises(ValidationError):
            replay_reuse(package, pid, package / "nested")

    def test_reference_file_cannot_be_exported_as_public_output(self):
        self.artifact_case()
        for r in self.records:
            if r.get("artifacts"):
                r["artifacts"]["decision"] = {"path": "truth.json", "sha256": sha(self.scorers / "truth.json")}
        self.save()
        with self.assertRaises(ValidationError):
            prepare_reuse(self.study, self.root / "handoff", artifact_root=self.scorers, verifier_root=self.scorers)

    def test_cli_replay_and_inspect_in_separate_processes(self):
        import subprocess
        import sys
        import json
        package, pid = self.prepare()
        replay = self.root / "process-replay"
        result = subprocess.run([sys.executable, "-B", "-m", "value_lab.cli", "reuse-replay", str(package), "--expected-id", pid, "--output", str(replay)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "REPRODUCED")
        result = subprocess.run([sys.executable, "-B", "-m", "value_lab.cli", "reuse-inspect", str(package), "--expected-id", pid, "--receipt", str(replay)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["execution_authenticated"])

    def test_nested_scenario_cannot_hide_an_executable(self):
        # A valid scenario envelope must not bypass the explicit no-code policy.
        from value_lab.scenarios import prepare_suite
        from value_lab.core import demo_suite
        private = {"type": "ScorerOnlyGroundTruth", "case_id": "code-case", "evidence_type": "synthetic", "nonce": "a"*64,
                   "rationale": "Manufactured attack", "graders": [{"id": "run", "type": "exec", "artifact": "result",
                   "verifier": {"program": {"path": "never.py", "sha256": "b"*64}, "image": "example@sha256:"+"c"*64, "timeout_seconds": 1}}]}
        write_json(self.scorers / "scenario.json", private)
        pack = {"format": "pvl-scenario-pack-1", "id": "test", "evidence_type": "synthetic",
                "sources": [{"url": "synthetic", "license": "test", "provenance": "manufactured"}],
                "scenarios": [{"type": "AgentVisibleScenario", "id": "code-case", "family": "attack", "split": "development", "prompt": "test",
                               "inputs": {}, "outputs": {"result": "result.json"}, "scorer": {"path": "scenario.json", "sha256": sha(self.scorers / "scenario.json")}}]}
        self.suite = prepare_suite(pack, demo_suite())
        self.records = []
        self.save()
        with self.assertRaises(ValidationError):
            prepare_reuse(self.study, self.root / "handoff", verifier_root=self.scorers)


if __name__ == "__main__":
    unittest.main()
