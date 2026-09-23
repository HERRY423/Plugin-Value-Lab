"""Manufactured event fixtures; these tests make no model calls."""
import json
from pathlib import Path
import tempfile
import unittest

from value_lab.claude_collection import parse_events, verify_collection, _continuation_records
from value_lab.core import demo_suite, write_json, suite_digest, ValidationError
from value_lab.artifacts import sha
from value_lab.codex import schedule


class NativeCollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "events.jsonl"
        self.suite = demo_suite()
        self.suite["conditions"].update(model="fixture-model", tools=["Read", "Skill"])
        self.events = [
            {"type": "system", "subtype": "init", "session_id": "fixture-session", "model": "fixture-model",
             "tools": ["Read", "Skill"], "plugins": [{"name": self.suite["plugin"]["name"]}]},
            {"type": "assistant", "message": {"model": "fixture-model", "content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "fixture"}}]}},
            {"type": "result", "subtype": "success", "is_error": False, "session_id": "fixture-session", "result": '{"value": 1}', "total_cost_usd": .02}]

    def parse(self, arm="with"):
        self.path.write_text("".join(json.dumps(e) + "\n" for e in self.events), encoding="utf-8")
        return parse_events(self.path, self.suite, arm)

    def test_native_identity_output_skill_and_estimate_collected(self):
        result = self.parse()
        self.assertEqual(result["issues"], [])
        self.assertTrue(result["plugin_loaded"])
        self.assertEqual(result["skill_calls"], [{"skill": "fixture"}])
        self.assertEqual(result["model_usd"], .02)

    def test_baseline_exposure_is_observed_not_assumed(self):
        self.assertIsNone(self.parse("without")["plugin_loaded"])
        self.events[0]["plugins"] = []
        self.assertFalse(self.parse("without")["plugin_loaded"])
        self.assertEqual(self.parse("without")["issues"], [])

    def test_unknown_cost_model_or_plugin_blocks_conditions(self):
        for field in ("model", "plugins", "tools"):
            value = self.events[0].pop(field)
            self.assertIsNone(self.parse()["conditions"])
            self.events[0][field] = value
        self.events[-1].pop("total_cost_usd")
        self.assertIsNone(self.parse()["model_usd"])

    def test_duplicate_result_or_session_mismatch_stays_unresolved(self):
        self.events.append(dict(self.events[-1]))
        self.assertFalse(self.parse()["completed"])
        self.events.pop()
        self.events[-1]["session_id"] = "other-session"
        self.assertIsNone(self.parse()["conditions"])

    def test_fallback_extra_tools_or_denials_not_silently_matched(self):
        self.events[1]["message"]["model"] = "another-model"
        self.events[0]["tools"].append("Bash")
        self.events[-1]["permission_denials"] = [{"tool_name": "Read"}]
        self.assertEqual(len(self.parse()["issues"]), 3)

    def test_error_and_missing_result_never_count_as_success(self):
        self.events[-1]["is_error"] = True
        self.assertFalse(self.parse()["completed"])
        self.events.pop()
        self.assertFalse(self.parse()["completed"])

    def test_provider_price_uses_complete_native_token_envelope(self):
        self.suite["pricing"] = {"input_miss_usd_per_million": .3, "input_hit_usd_per_million": .006, "output_usd_per_million": 1.2}
        self.events[-1].update(usage={"input_tokens": 5104, "cache_read_input_tokens": 4480, "output_tokens": 1660},
                              modelUsage={"fixture-model": {"inputTokens": 5258, "cacheCreationInputTokens": 0, "cacheReadInputTokens": 9600, "outputTokens": 2872}})
        self.assertAlmostEqual(self.parse()["model_usd"], .0050814)
        self.events[-1]["modelUsage"] = {}
        self.assertIsNone(self.parse()["model_usd"])

    def fixture_collection(self):
        root = Path(self.tmp.name) / "collection"
        root.mkdir()
        (root / "plugin").mkdir()
        (root / "inputs").mkdir()
        source = root / "inputs/data.csv"
        source.write_text("public fixture\n", encoding="utf-8")
        self.suite["cases"] = self.suite["cases"][:1]
        self.suite["cases"][0]["inputs"] = {"data.csv": sha(source)}
        plan = {"suite_sha256": suite_digest(self.suite), "schedule": schedule(self.suite), "plugin_files": {}, "inputs": {"data.csv": sha(source)}}
        for name, value in (("suite.json", self.suite), ("plan.json", plan), ("protocol.lock.json", {"suite_sha256": plan["suite_sha256"]})):
            write_json(root / name, value)
        write_json(root / "execution-started.json", {"plan_sha256": sha(root / "plan.json")})
        planned = plan["schedule"][0]
        run = root / "runs" / ("0001-" + planned["case_id"] + "-" + planned["arm"])
        (run / "workspace").mkdir(parents=True)
        (run / "workspace/data.csv").write_bytes(source.read_bytes())
        self.path = run / "events.jsonl"
        native = self.parse(planned["arm"])
        (run / "answer.json").write_text(native["output"], encoding="utf-8")
        record = {**planned, "suite_sha256": plan["suite_sha256"], **{k: native[k] for k in ("session_id", "output", "conditions", "plugin_loaded")},
                  "cost": {"model_usd": native["model_usd"]}, "import_issues": native["issues"], "status": "completed", "duration_seconds": 1,
                  "artifacts": {"answer": {"path": (run / "answer.json").relative_to(root).as_posix(), "sha256": sha(run / "answer.json")}}}
        write_json(run / "receipt.json", {"native": native, "events_sha256": sha(self.path), "timed_out": False, "exit_code": 0, "duration_seconds": 1})
        write_json(run / "launch.json", {"input_sha256": plan["inputs"]})
        (root / "runs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        return root, run, record

    def test_offline_verifier_preserves_partial_schedule(self):
        root, _, _ = self.fixture_collection()
        result = verify_collection(root)
        self.assertEqual(result["verified_records"], 1)
        self.assertEqual(result["successful_runs"], 1)
        self.assertFalse(result["schedule_fully_observed"])
        self.assertFalse(result["complete"])

    def test_unified_host_contract_keeps_partial_claude_coverage_explicit(self):
        from value_lab.hosts import verify_host_study
        from value_lab.core import load_json
        self.suite["conditions"]["host"] = "claude-code"
        root, _, _ = self.fixture_collection()
        plan = load_json(root / "plan.json")
        plan["format"] = "pvl-claude-collection-1"
        write_json(root / "plan.json", plan)
        write_json(root / "execution-started.json", {"plan_sha256": sha(root / "plan.json")})
        result = verify_host_study(root)
        self.assertEqual(result["format"], "pvl-host-evidence-1")
        self.assertEqual(result["recorded_runs"], 1)
        self.assertEqual(result["planned_runs"], 6)
        self.assertFalse(result["schedule_fully_observed"])
        self.assertFalse(result["provider_identity_authenticated"])

    def test_offline_verifier_rejects_status_rewrite(self):
        root, _, record = self.fixture_collection()
        record["status"] = "timeout"
        (root / "runs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "completion"):
            verify_collection(root)

    def test_offline_verifier_rejects_workspace_input_change(self):
        root, run, _ = self.fixture_collection()
        (run / "workspace/data.csv").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "workspace input"):
            verify_collection(root)

    def test_offline_verifier_rejects_rehashed_substitute_answer(self):
        root, run, record = self.fixture_collection()
        (run / "answer.json").write_text('{"value": 2}', encoding="utf-8")
        record["artifacts"]["answer"]["sha256"] = sha(run / "answer.json")
        (root / "runs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "native output"):
            verify_collection(root)

    def test_continuation_only_accepts_known_prefix_and_unstarted_suffix(self):
        root, _, _ = self.fixture_collection()
        plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
        records, _ = _continuation_records(root, plan)
        self.assertEqual(len(records), 1)
        item = plan["schedule"][1]
        (root / "runs" / ("0002-" + item["case_id"] + "-" + item["arm"])).mkdir()
        with self.assertRaisesRegex(ValidationError, "unknown"):
            _continuation_records(root, plan)

    def test_continuation_rejects_unknown_process_even_with_native_result(self):
        root, run, record = self.fixture_collection()
        plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
        receipt = json.loads((run / "receipt.json").read_text(encoding="utf-8"))
        receipt["exit_code"] = None
        write_json(run / "receipt.json", receipt)
        record["status"] = "error"
        (root / "runs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "Unresolved process"):
            _continuation_records(root, plan)
