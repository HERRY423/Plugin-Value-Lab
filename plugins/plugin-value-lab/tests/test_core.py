import copy
import json
import tempfile
import unittest
from pathlib import Path

from value_lab.core import (ValidationError, demo_records, demo_suite, evaluate, freeze,
                            load_json, load_records, suite_digest, validate_suite)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.suite = demo_suite()
        self.suite["evidence_type"] = "local"
        self.records = demo_records(self.suite)
        # Test input only: this relabelling is deliberately limited to unit tests.
        for record in self.records:
            record["source"] = "manual"
        self.lock = {"suite_sha256": suite_digest(self.suite)}

    def report(self):
        return evaluate(self.suite, self.records, self.lock)

    def test_positive_is_local_only(self):
        report = self.report()
        self.assertEqual(report["verdict"], "PROMISING_LOCAL_SIGNAL")
        self.assertEqual(report["claim_limits"]["external_validation"], "NOT_ESTABLISHED")
        self.assertEqual(report["summary"]["complete_pairs"], 9)

    def test_simulation_never_proves_value(self):
        self.records[0]["source"] = "synthetic"
        self.assertEqual(self.report()["verdict"], "SIMULATION_ONLY")

    def test_perfect_both_arms_has_no_incremental_gain(self):
        for i in range(0, len(self.records), 2):
            self.records[i + 1]["output"] = self.records[i]["output"]
        self.assertEqual(self.report()["verdict"], "NO_DEMONSTRATED_GAIN")

    def test_efficiency_objective_accepts_equal_quality_lower_cost(self):
        self.suite["policy"]["objective"] = "efficiency"
        digest = suite_digest(self.suite)
        self.lock["suite_sha256"] = digest
        for record in self.records:
            record["suite_sha256"] = digest
        for i in range(0, len(self.records), 2):
            self.records[i + 1]["output"] = self.records[i]["output"]
        book = {"schema_version": 1, "coverage": {k: "included" for k in ("judge", "setup", "retry", "other")}, "entries": []}
        self.assertEqual(evaluate(self.suite, self.records, self.lock, book)["verdict"], "PROMISING_LOCAL_SIGNAL")
        for record in self.records:
            if record["arm"] == "with":
                record["cost"]["model_usd"] = 10
        self.assertEqual(evaluate(self.suite, self.records, self.lock, book)["verdict"], "NO_DEMONSTRATED_GAIN")

    def test_cost_dependent_verdict_requires_full_coverage_even_without_explicit_flag(self):
        for changes in ({"objective": "efficiency"}, {"require_cost_saving": True}):
            suite = copy.deepcopy(self.suite)
            suite["policy"].update(changes)
            records = demo_records(suite)
            for r in records:
                r["source"] = "manual"
            result = evaluate(suite, records, {"suite_sha256": suite_digest(suite)})
            self.assertEqual(result["verdict"], "INSUFFICIENT_EVIDENCE")
            self.assertFalse(result["cost_analysis"]["saving_claim_eligible"])
            self.assertTrue(any("Cost-dependent" in b for b in result["blockers"]))

    def test_missing_baseline_is_not_zero(self):
        self.records = [r for r in self.records if r["arm"] == "with"]
        result = self.report()
        self.assertEqual(result["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(result["summary"]["without_score"])
        self.assertEqual(result["summary"]["expected_runs"], 18)

    def test_unknown_cost_is_not_zero(self):
        self.records[0]["cost"]["tool_usd"] = None
        self.assertIsNone(self.report()["summary"]["with_cost_usd"])
        self.assertEqual(self.report()["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_machine_duration_cannot_replace_human_minutes(self):
        self.records[0].pop("human_intervals")
        self.assertEqual(self.report()["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_overlapping_human_timer_blocks(self):
        self.records[2]["human_intervals"] = copy.deepcopy(self.records[0]["human_intervals"])
        self.assertTrue(any("Overlapping" in b for b in self.report()["blockers"]))

    def test_conditions_mismatch_blocks(self):
        self.records[0]["conditions"] = dict(self.suite["conditions"], model="different")
        self.assertEqual(self.report()["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_reused_session_blocks(self):
        self.records[1]["session_id"] = self.records[0]["session_id"]
        self.assertEqual(self.report()["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_baseline_contamination_blocks(self):
        self.records[1]["plugin_loaded"] = True
        self.assertEqual(self.report()["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_duplicate_run_blocks(self):
        self.records.append(copy.deepcopy(self.records[0]))
        self.assertEqual(self.report()["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_changed_protocol_blocks(self):
        self.suite["policy"]["quality_floor"] = 0.4
        self.assertEqual(self.report()["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_critical_failure_overrides_average(self):
        self.records[6]["output"] = "4 AUDIT:"
        self.assertEqual(self.report()["verdict"], "REGRESSION_DETECTED")

    def test_error_retained_in_denominator(self):
        self.records[0]["status"] = "timeout"
        result = self.report()
        self.assertEqual(result["cases"][0]["runs"][0]["score"], 0)
        self.assertEqual(result["summary"]["observed_runs"], 18)

    def test_skipped_is_incomplete(self):
        self.records[0]["status"] = "skipped"
        self.assertEqual(self.report()["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_process_does_not_inflate_quality(self):
        report = self.report()
        self.assertEqual(report["cases"][2]["with_score"], 1)
        self.assertEqual(report["cases"][2]["without_score"], 1 / 3)

    def test_only_process_grading_rejected(self):
        self.suite["cases"][0]["graders"][0]["dimension"] = "process"
        self.suite["cases"][0]["graders"][1]["dimension"] = "process"
        with self.assertRaises(ValidationError):
            validate_suite(self.suite)

    def test_grading_weights_cannot_be_zero_nan_or_bool(self):
        for invalid in (0, float("nan"), True):
            self.suite["cases"][0]["graders"][0]["weight"] = invalid
            with self.assertRaises(ValidationError):
                validate_suite(self.suite)

    def test_duplicate_json_keys_and_nan_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "input.json"
            for content in ('{"x":1,"x":2}', '{"x":NaN}'):
                p.write_text(content, encoding="utf-8")
                with self.assertRaises(ValidationError):
                    load_json(p)

    def test_freeze_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "lock.json"
            freeze(self.suite, p)
            with self.assertRaises(ValidationError):
                freeze(self.suite, p)

    def test_repetitions_not_independent_families(self):
        result = self.report()
        self.assertEqual(result["uncertainty"]["clusters"], 3)
        self.assertEqual(result["uncertainty"]["status"], "DESCRIPTIVE_ONLY")

    def test_human_missing_is_unresolved(self):
        self.suite["cases"][0]["graders"][0].update(type="human", rubric="A real reference supports output")
        for record in self.records:
            record["suite_sha256"] = suite_digest(self.suite)
        self.lock["suite_sha256"] = suite_digest(self.suite)
        self.assertEqual(self.report()["verdict"], "INSUFFICIENT_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
