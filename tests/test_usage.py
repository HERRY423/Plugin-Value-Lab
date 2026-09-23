import copy
import json
import tempfile
import unittest
from pathlib import Path

from value_lab.core import ValidationError, demo_records, demo_suite, evaluate, suite_digest
from value_lab.usage import build_usage_card, write_usage_card


class UsageCardTests(unittest.TestCase):
    def setUp(self):
        self.suite = demo_suite()
        self.suite["policy"]["require_cost_saving"] = True
        self.suite["evidence_type"] = "local"
        self.records = demo_records(self.suite)
        # This deliberate fixture relabelling exists ONLY in these unit tests.
        # It is not an observation or a demonstration of real plugin benefit.
        for record in self.records:
            record["source"] = "manual"
        self.rebind()

    def rebind(self):
        digest = suite_digest(self.suite)
        self.lock = {"suite_sha256": digest}
        for record in self.records:
            record["suite_sha256"] = digest

    def card(self):
        book = {"schema_version": 1, "coverage": {k: "included" for k in ("judge", "setup", "retry", "other")}, "entries": []}
        return build_usage_card(self.suite, self.records, self.lock, book)

    @staticmethod
    def ids(items):
        return {item["case_id"] for item in items}

    def test_positive_is_limited_to_individually_supported_tasks(self):
        card = self.card()
        self.assertEqual(card["status"], "BOUNDED_LOCAL_GUIDANCE")
        self.assertEqual(self.ids(card["use_when"]), {"structured-delivery", "insufficient-science"})
        self.assertEqual(self.ids(card["prefer_baseline_when"]), {"unrelated-request"})
        self.assertIn("效率目标", card["prefer_baseline_when"][0]["reason"])
        self.assertFalse(card["source"]["authenticity_verified"])
        self.assertEqual(card["source"]["claim_limits"]["scientific_authorization"], "NONE")

    def test_recomputes_and_ignores_injected_positive_verdict(self):
        self.suite["verdict"] = "PROMISING_LOCAL_SIGNAL"
        self.suite["summary"] = {"comparison_eligible": True}
        self.rebind()
        self.records[0]["cost"].pop("tool_usd")
        card = self.card()
        self.assertEqual(card["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(card["use_when"], [])
        self.assertEqual(card["prefer_baseline_when"], [])

    def test_precomputed_report_is_not_accepted_as_suite(self):
        report = evaluate(self.suite, self.records, self.lock)
        with self.assertRaises(ValidationError):
            build_usage_card(report, self.records, self.lock)

    def test_simulation_never_becomes_usage_guidance(self):
        for mark_suite in (False, True):
            with self.subTest(mark_suite=mark_suite):
                suite, records = copy.deepcopy(self.suite), copy.deepcopy(self.records)
                if mark_suite:
                    suite["evidence_type"] = "synthetic"
                    for record in records:
                        record["suite_sha256"] = suite_digest(suite)
                else:
                    records[0]["source"] = "synthetic"
                card = build_usage_card(suite, records, {"suite_sha256": suite_digest(suite)})
                self.assertEqual(card["status"], "TRIAL_GUIDANCE_ONLY")
                self.assertEqual(card["use_when"], [])
                self.assertEqual(card["prefer_baseline_when"], [])
                self.assertEqual(len(card["investigate"]), 3)

    def test_global_regression_prevents_cherry_picked_good_case(self):
        self.records[6]["output"] = "4 AUDIT:"
        card = self.card()
        self.assertEqual(card["verdict"], "REGRESSION_DETECTED")
        self.assertEqual(card["status"], "REVIEW_REQUIRED")
        self.assertEqual(card["use_when"], [])
        self.assertEqual(len(card["investigate"]), 3)

    def test_absent_lock_blocks_even_good_cases(self):
        card = build_usage_card(self.suite, self.records)
        self.assertEqual(card["status"], "REVIEW_REQUIRED")
        self.assertEqual(card["use_when"], [])
        self.assertTrue(card["source"]["blockers"])

    def test_case_quality_floor_cannot_hide_in_high_global_average(self):
        self.records[0]["output"] = "No grading tokens"
        card = self.card()
        self.assertEqual(card["verdict"], "PROMISING_LOCAL_SIGNAL")
        self.assertNotIn("structured-delivery", self.ids(card["use_when"]))
        self.assertIn("质量未达到下限", next(x["reason"] for x in card["investigate"] if x["case_id"] == "structured-delivery"))

    def test_critical_process_gate_is_not_ignored_for_case_recommendation(self):
        self.suite["cases"][2]["graders"][1]["critical"] = True
        for record in self.records:
            if record["case_id"] == "insufficient-science" and record["arm"] == "with":
                record["output"] = "NOT_ESTABLISHED"
        self.rebind()
        card = self.card()
        self.assertEqual(card["verdict"], "PROMISING_LOCAL_SIGNAL")
        self.assertNotIn("insufficient-science", self.ids(card["use_when"]))
        self.assertIn("insufficient-science", self.ids(card["investigate"]))

    def test_baseline_critical_failure_is_not_hidden_by_high_equal_scores(self):
        self.suite["cases"][0]["graders"][0]["critical"] = True
        self.suite["cases"][0]["graders"].append({
            "id": "common", "type": "contains", "value": "COMMON", "weight": 8,
            "critical": False, "dimension": "outcome",
        })
        for record in self.records:
            if record["case_id"] == "structured-delivery":
                record["output"] = "SOURCE: COMMON" if record["arm"] == "with" else "LIMITS: COMMON"
        self.rebind()
        card = self.card()
        self.assertEqual(card["verdict"], "PROMISING_LOCAL_SIGNAL")
        self.assertNotIn("structured-delivery", self.ids(card["prefer_baseline_when"]))
        item = next(item for item in card["investigate"] if item["case_id"] == "structured-delivery")
        self.assertEqual(item["with_score"], 0.9)
        self.assertEqual(item["without_score"], 0.9)
        self.assertIn("基线未通过关键判据", item["reason"])

    def test_baseline_critical_failure_does_not_block_supported_plugin_use(self):
        self.suite["cases"][0]["graders"][0]["critical"] = True
        for record in self.records:
            if record["case_id"] == "structured-delivery" and record["arm"] == "without":
                record["output"] = "LIMITS:"
        self.rebind()
        card = self.card()
        self.assertEqual(card["verdict"], "PROMISING_LOCAL_SIGNAL")
        self.assertIn("structured-delivery", self.ids(card["use_when"]))
        self.assertNotIn("structured-delivery", self.ids(card["prefer_baseline_when"]))

    def test_case_delta_threshold_cannot_hide_in_global_gain(self):
        self.suite["policy"]["min_quality_delta"] = 0.3
        # First case improves by only 1/6; third improves by a full point.
        for record in self.records:
            if record["arm"] == "without" and record["case_id"] == "structured-delivery":
                record["output"] = "SOURCE: LIMITS:" if record["repetition"] != 1 else "SOURCE:"
            if record["arm"] == "without" and record["case_id"] == "insufficient-science":
                record["output"] = "No evidence boundary"
        self.rebind()
        card = self.card()
        self.assertEqual(card["verdict"], "PROMISING_LOCAL_SIGNAL")
        self.assertEqual(self.ids(card["use_when"]), {"insufficient-science"})

    def test_case_cost_saving_cannot_hide_in_global_savings(self):
        for record in self.records:
            if record["arm"] == "with" and record["case_id"] == "structured-delivery":
                record["cost"]["model_usd"] = 1.1
        card = self.card()
        self.assertEqual(card["verdict"], "PROMISING_LOCAL_SIGNAL")
        self.assertNotIn("structured-delivery", self.ids(card["use_when"]))
        self.assertIn("structured-delivery", self.ids(card["investigate"]))

    def test_cost_is_mean_per_case_arm_not_sum_of_repetitions(self):
        for record in self.records:
            if record["case_id"] == "structured-delivery" and record["arm"] == "with":
                record["cost"]["model_usd"] = 0.1 * record["repetition"]
        card = self.card()
        item = next(x for x in card["use_when"] if x["case_id"] == "structured-delivery")
        self.assertAlmostEqual(item["cost_delta_usd"], 1.2 - 2.01)
        self.assertNotAlmostEqual(item["cost_delta_usd"], 3 * (1.2 - 2.01))

    def test_cost_unknown_stays_unknown_and_blocks_recommendations(self):
        self.records[0]["cost"]["human_minutes"] = None
        card = self.card()
        self.assertEqual(card["use_when"], [])
        self.assertIsNone(card["investigate"][0]["cost_delta_usd"])

    def test_quality_goal_without_savings_requirement_allows_more_cost(self):
        self.suite["policy"]["require_cost_saving"] = False
        self.rebind()
        for record in self.records:
            if record["arm"] == "with":
                record["cost"]["model_usd"] = 10
        card = self.card()
        self.assertEqual(card["verdict"], "PROMISING_LOCAL_SIGNAL")
        self.assertEqual(len(card["use_when"]), 2)
        self.assertGreater(card["use_when"][0]["cost_delta_usd"], 0)

    def test_flat_quality_can_support_efficiency_when_cheaper(self):
        self.suite["policy"]["objective"] = "efficiency"
        self.rebind()
        for i in range(0, len(self.records), 2):
            self.records[i + 1]["output"] = self.records[i]["output"]
        card = self.card()
        self.assertEqual(card["verdict"], "PROMISING_LOCAL_SIGNAL")
        self.assertEqual(len(card["use_when"]), 3)
        self.assertEqual(card["prefer_baseline_when"], [])

    def test_efficiency_case_with_added_cost_is_not_promoted(self):
        self.suite["policy"]["objective"] = "efficiency"
        self.rebind()
        for i in range(0, len(self.records), 2):
            self.records[i + 1]["output"] = self.records[i]["output"]
        for record in self.records:
            if record["arm"] == "with" and record["case_id"] == "structured-delivery":
                record["cost"]["model_usd"] = 1.1
        card = self.card()
        self.assertEqual(card["verdict"], "PROMISING_LOCAL_SIGNAL")
        self.assertNotIn("structured-delivery", self.ids(card["use_when"]))
        self.assertIn("structured-delivery", self.ids(card["prefer_baseline_when"]))

    def test_flat_quality_no_gain_does_not_recommend_uninstall(self):
        for i in range(0, len(self.records), 2):
            self.records[i + 1]["output"] = self.records[i]["output"]
        card = self.card()
        self.assertEqual(card["verdict"], "NO_DEMONSTRATED_GAIN")
        self.assertEqual(card["use_when"], [])
        self.assertEqual(len(card["prefer_baseline_when"]), 3)
        self.assertTrue(all("不是永久停用或卸载建议" in x["reason"] for x in card["prefer_baseline_when"]))

    def test_failures_and_missing_are_retained_with_planned_denominator(self):
        self.records[0]["status"] = "timeout"
        self.records.pop()
        card = self.card()
        counts = card["source"]["run_counts"]
        self.assertEqual(counts["planned_runs"], 18)
        self.assertEqual(counts["observed_runs"], 17)
        self.assertEqual(counts["failed_runs"], 1)
        self.assertEqual(counts["missing_runs"], 1)
        self.assertEqual(len(card["investigate"]), 3)
        self.assertIn("1 次失败", card["investigate"][0]["reason"])
        self.assertIn("1 次缺失", card["investigate"][2]["reason"])

    def test_scope_binds_exact_inputs_and_copies_mutable_metadata(self):
        card = self.card()
        self.assertEqual(card["scope"]["suite_sha256"], suite_digest(self.suite))
        self.assertEqual(card["scope"]["records_sha256"], suite_digest(self.records))
        self.assertEqual(card["scope"]["conditions_sha256"], suite_digest(self.suite["conditions"]))
        self.suite["conditions"]["budget"]["max_turns"] = 999
        self.suite["plugin"]["version"] = "changed"
        self.lock["suite_sha256"] = "changed"
        self.assertEqual(card["scope"]["conditions"]["budget"]["max_turns"], 10)
        self.assertEqual(card["plugin"]["version"], "0.0.0-demo")
        self.assertNotEqual(card["source"]["provenance"]["local_lock"]["suite_sha256"], "changed")

    def test_external_declaration_is_not_authentication(self):
        self.suite["evidence_type"] = "external"
        self.rebind()
        card = self.card()
        self.assertEqual(card["source"]["evidence_type"], "external")
        self.assertEqual(card["status"], "BOUNDED_LOCAL_GUIDANCE")
        self.assertFalse(card["source"]["authenticity_verified"])
        self.assertEqual(card["source"]["claim_limits"]["external_validation"], "NOT_ESTABLISHED")

    def test_markdown_escapes_untrusted_text_and_preserves_json(self):
        hostile = '<img src=x onerror="alert(1)">\n# false heading\n![remote](https://example.invalid/pixel) [click](javascript:alert(1))'
        self.suite["plugin"]["name"] = hostile
        self.suite["cases"][0]["prompt"] = hostile
        self.rebind()
        card = self.card()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_usage_card(card, directory)
            markdown = Path(paths["md"]).read_text(encoding="utf-8")
            self.assertNotIn('<img src=', markdown)
            self.assertNotIn('\n# false heading', markdown)
            self.assertNotIn('![remote](', markdown)
            self.assertNotIn('[click](', markdown)
            self.assertIn('&lt;img', markdown)
            saved = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["plugin"]["name"], hostile)

    def test_writes_only_card_artifacts_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fresh"
            paths = write_usage_card(self.card(), output)
            self.assertEqual({x.name for x in output.iterdir()}, {"card.json", "USAGE.md"})
            original = Path(paths["json"]).read_bytes()
            with self.assertRaises(ValidationError):
                write_usage_card(self.card(), output)
            self.assertEqual(Path(paths["json"]).read_bytes(), original)
            file_path = Path(directory) / "file"
            file_path.write_text("keep", encoding="utf-8")
            with self.assertRaises(ValidationError):
                write_usage_card(self.card(), file_path)
            self.assertEqual(file_path.read_text(), "keep")

    def test_nonempty_output_and_invalid_serialization_leave_files_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            keep = Path(directory) / "keep.txt"
            keep.write_text("keep", encoding="utf-8")
            with self.assertRaises(ValidationError):
                write_usage_card(self.card(), directory)
            self.assertEqual(list(Path(directory).iterdir()), [keep])
            card = self.card()
            card["invalid"] = float("nan")
            fresh = Path(directory) / "new"
            with self.assertRaises(ValueError):
                write_usage_card(card, fresh)
            self.assertFalse(fresh.exists())


if __name__ == "__main__":
    unittest.main()
