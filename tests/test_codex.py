import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import patch

from value_lab.codex import parse_events, prepare, run, _command, verify_collection
from value_lab.core import ValidationError, demo_suite, write_json, load_records
from value_lab.execution import digest


class CodexTests(unittest.TestCase):
    def test_offline_verifier_rejects_promoted_identity_costs_and_forged_output(self):
        from copy import deepcopy
        plan, auth = self.study()
        self.execute_fixture(plan, auth)
        root = Path(plan["study"])
        original = load_records(root / "runs.jsonl")
        for field, value in (("output", "forged passing answer"), ("token_usage", {"output_tokens": 0}),
                             ("conditions", {"model": "invented"}), ("plugin_loaded", True),
                             ("import_issues", []), ("cost", {"model_usd": 0}), ("duration_seconds", 0)):
            with self.subTest(field=field):
                records = deepcopy(original)
                records[0][field] = value
                (root / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
                with self.assertRaises(ValidationError):
                    verify_collection(root)
        (root / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in original), encoding="utf-8")
        self.assertTrue(verify_collection(root)["complete"])
        from value_lab.hosts import verify_host_study
        from value_lab.registry import register_study
        from value_lab.core import load_json
        checked = verify_host_study(root)
        self.assertEqual(checked["host"], "codex-cli")
        self.assertEqual(checked["observed_condition_records"], 0)
        meta = {"observed_at": "2026-09-23T00:00:00Z", "authors": [{"id": "Fixture", "organization": "Fixture"}],
                "plugin_sha256": checked["plugin_files_sha256"], "limitations": "Synthetic subprocess only"}
        registered = register_study(root, meta, self.root / "registry")
        native = load_json(self.root / "registry/entries" / registered["entry_id"] / "native-verification.json")
        self.assertEqual(native["records_sha256"], checked["records_sha256"])
        bad_meta = {**meta, "plugin_sha256": "f" * 64}
        with self.assertRaisesRegex(ValidationError, "inventory digest"):
            register_study(root, bad_meta, self.root / "bad-registry")

    def test_offline_verifier_rechecks_executed_inputs_and_plugin(self):
        plan, auth = self.study(inputs=True)
        self.execute_fixture(plan, auth)
        root = Path(plan["study"])
        path = next((root / "runs").rglob("cells.csv"))
        saved = path.read_bytes()
        path.write_text("substituted input", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "workspace input"):
            verify_collection(root)
        path.write_bytes(saved)
        (root / "plugin/plugin.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "plugin snapshot"):
            verify_collection(root)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def events(self, data):
        path = self.root / "events.jsonl"
        path.write_text("\n".join(json.dumps(d) for d in data), encoding="utf-8")
        return parse_events(path)

    def test_actual_event_shapes_and_failure_retention(self):
        rows = [{"type": "thread.started", "thread_id": "session-1"},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "answer"}},
                {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 10}}]
        value = self.events(rows)
        self.assertTrue(value["completed"])
        self.assertEqual(value["output"], "answer")
        self.assertEqual(value["session_id"], "session-1")
        rows.append({"type": "turn.failed", "error": {"message": "interrupted"}})
        self.assertFalse(self.events(rows)["completed"])

    def test_partial_and_malformed_events_do_not_complete(self):
        self.assertFalse(self.events([{"type": "thread.started", "thread_id": "x"}])["completed"])
        path = self.root / "bad"
        path.write_text('{"incomplete"')
        self.assertFalse(parse_events(path)["completed"])

    def test_safe_command_retains_model_as_argument(self):
        command = _command("codex", "model-name", self.root, self.root / "answer")
        self.assertIn("read-only", command)
        self.assertIn("--ephemeral", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)

    def test_prepare_refuses_wrong_host_and_unenforceable_cost_cap(self):
        suite = demo_suite()
        with self.assertRaises(ValidationError):
            prepare(suite, self.root, self.root / "out")
        suite["conditions"]["host"] = "codex-cli"
        suite["conditions"]["budget"] = {"timeout_seconds": 30, "max_model_runs": 18, "max_cost_usd": 1}
        with self.assertRaisesRegex(ValidationError, "dollar cap"):
            prepare(suite, self.root, self.root / "out")

    def study(self, fail=False, inputs=False):
        plugin = self.root / "candidate"
        plugin.mkdir()
        suite = demo_suite()
        write_json(plugin / "plugin.json", suite["plugin"])
        suite["conditions"]["host"] = "codex-cli"
        suite["conditions"]["budget"] = {"timeout_seconds": 10, "max_model_runs": 6}
        suite["runs_per_case"] = 1
        if fail:
            suite["cases"][0]["prompt"] = "FAIL_INFRASTRUCTURE"
        input_root = self.root / "input-source"
        if inputs:
            input_root.mkdir()
            (input_root / "cells.csv").write_text("cell,label\nc1,T\nc2,B\n", encoding="utf-8")
            suite["cases"][0]["inputs"] = {"cells.csv": digest(input_root / "cells.csv")}
        with patch("value_lab.codex.preflight", return_value={"version": "SYNTHETIC", "executable_sha256": digest(sys.executable)}):
            result = prepare(suite, plugin, self.root / "study", sys.executable, input_root if inputs else None)
        auth = self.root / "fake-auth"
        auth.mkdir()
        write_json(auth / "auth.json", {"fixture": "NOT-A-CREDENTIAL"})
        return result, auth

    def execute_fixture(self, plan, auth):
        setup = subprocess.CompletedProcess([], 0, stdout='{"fixture":true}', stderr="")
        fixture = str(Path(__file__).with_name("fixture_codex_process.py"))
        with patch("value_lab.codex.subprocess.run", return_value=setup), patch("value_lab.codex._command", return_value=[sys.executable, fixture]):
            return run(plan["study"], plan["plan_sha256"], auth)

    def test_full_local_subprocess_collection_counterbalances_and_never_fabricates_provenance(self):
        plan, auth = self.study()
        result = self.execute_fixture(plan, auth)
        records = load_records(Path(plan["study"]) / "runs.jsonl")
        self.assertEqual(result["completed_model_runs"], 6)  # Parser count in a synthetic fixture only.
        self.assertEqual(result["verdict"], "SIMULATION_ONLY")
        self.assertEqual([r["arm"] for r in records], ["with", "without", "without", "with", "with", "without"])
        self.assertEqual(len({r["session_id"] for r in records}), 6)
        self.assertTrue(all(r["plugin_loaded"] is None and r["conditions"] is None for r in records))
        self.assertTrue(all(r["cost"]["model_usd"] is None for r in records))
        self.assertFalse(list((Path(plan["study"]) / "runs").rglob("auth.json")))
        with self.assertRaises(FileExistsError):
            self.execute_fixture(plan, auth)

    def test_infrastructure_failure_stops_and_retains_missing_denominator(self):
        plan, auth = self.study(fail=True)
        result = self.execute_fixture(plan, auth)
        self.assertEqual(result["recorded_runs"], 1)
        self.assertEqual(result["completed_model_runs"], 0)
        self.assertEqual(result["expected_runs"], 6)
        self.assertFalse(list((Path(plan["study"]) / "runs").rglob("auth.json")))

    def test_changed_snapshot_refuses_before_credential_copy_or_launch(self):
        plan, auth = self.study()
        (Path(plan["study"]) / "plugin" / "changed.txt").write_text("tampered")
        with self.assertRaisesRegex(ValidationError, "plugin or executable"):
            self.execute_fixture(plan, auth)
        self.assertFalse((Path(plan["study"]) / "execution-started.json").exists())

    def test_setup_timeout_is_preserved_without_starting_model_or_copying_credentials(self):
        plan, auth = self.study()
        with patch("value_lab.codex.subprocess.run", side_effect=subprocess.TimeoutExpired("fixture-install", 60)), patch("value_lab.codex._run") as launch:
            result = run(plan["study"], plan["plan_sha256"], auth)
        launch.assert_not_called()
        self.assertEqual(result["recorded_runs"], 1)
        self.assertEqual(result["completed_model_runs"], 0)
        record = load_records(Path(plan["study"]) / "runs.jsonl")[0]
        self.assertEqual(record["failure_kind"], "infrastructure")
        self.assertFalse(list((Path(plan["study"]) / "runs").rglob("auth.json")))

    def test_both_arms_receive_identical_frozen_task_inputs(self):
        plan, auth = self.study(inputs=True)
        self.execute_fixture(plan, auth)
        root = Path(plan["study"])
        records = load_records(root / "runs.jsonl")
        self.assertEqual(records[0]["input_sha256"], records[1]["input_sha256"])
        files = list((root / "runs").rglob("cells.csv"))
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0].read_bytes(), files[1].read_bytes())

    def test_changed_input_snapshot_refuses_before_launch(self):
        plan, auth = self.study(inputs=True)
        (Path(plan["study"]) / "inputs/cells.csv").write_text("changed")
        with self.assertRaisesRegex(ValidationError, "input bytes"):
            self.execute_fixture(plan, auth)
        self.assertFalse((Path(plan["study"]) / "execution-started.json").exists())

    def test_receipts_verify_and_detect_native_log_tampering(self):
        plan, auth = self.study()
        self.execute_fixture(plan, auth)
        root = Path(plan["study"])
        checked = verify_collection(root)
        self.assertTrue(checked["complete"])
        self.assertFalse(checked["observed_identity_authenticated"])
        log = next((root / "runs").rglob("events.jsonl"))
        log.write_text("changed")
        with self.assertRaisesRegex(ValidationError, "evidence changed"):
            verify_collection(root)

    def test_rehashed_plan_cannot_duplicate_work_or_expand_limits(self):
        plan, auth = self.study()
        root = Path(plan["study"])
        manifest = json.loads((root / "plan.json").read_text())
        manifest["schedule"].append(manifest["schedule"][0])
        write_json(root / "plan.json", manifest)
        with self.assertRaisesRegex(ValidationError, "schedule/limits"):
            run(root, digest(root / "plan.json"), auth)
        self.assertFalse((root / "execution-started.json").exists())

    def test_completion_without_identity_or_answer_is_not_success(self):
        for events in ([{"type": "turn.completed"}],
                       [{"type": "thread.started", "thread_id": "x"}, {"type": "turn.completed"}],
                       [{"type": "thread.started", "thread_id": []}, {"type": "turn.completed"}],
                       [{"type": "thread.started", "thread_id": "x"}, {"type": "item.completed", "item": []}, {"type": "turn.completed"}]):
            self.assertFalse(self.events(events)["completed"])
