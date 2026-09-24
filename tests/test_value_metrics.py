"""Manufactured observations test metric arithmetic and evidence ceilings only."""
import copy
import tempfile
import unittest
from pathlib import Path

from value_lab.core import ValidationError, demo_records, demo_suite, evaluate, suite_digest, validate_suite
from value_lab.report import write_reports


class ValueMetricsTests(unittest.TestCase):
    def setUp(self):
        self.suite = demo_suite()
        self.suite["evidence_type"] = "local"
        self.records = demo_records(self.suite)
        for r in self.records:
            r["source"] = "manual"  # unit-test labels; no real execution
        self.ledger = {"schema_version": 1, "entries": [],
                       "coverage": {k: "not_applicable" for k in ("judge", "setup", "retry", "other")}}

    def report(self):
        digest = suite_digest(self.suite)
        for r in self.records:
            r["suite_sha256"] = digest
        return evaluate(self.suite, self.records, {"suite_sha256": digest}, self.ledger)

    def test_rescue_and_net_success_have_fixed_denominators(self):
        v = self.report()["value_metrics"]
        s = v["success"]
        self.assertEqual(s["planned_pairs"], 9)
        self.assertEqual(s["arms"]["with"]["successes"], 9)
        self.assertEqual(s["arms"]["without"]["successes"], 4)
        self.assertEqual((s["rescued"], s["harmed"]), (5, 0))
        self.assertAlmostEqual(s["net_additional_successes_per_100"], 500 / 9)
        self.assertEqual(v["by_kind"]["task"]["arms"]["with"]["rate"], 1)

    def test_missing_baseline_never_becomes_a_rescue(self):
        self.records = [r for r in self.records if r["arm"] == "with"]
        v = self.report()["value_metrics"]
        self.assertEqual(v["success"]["unknown_pairs"], 9)
        self.assertEqual(v["success"]["rescued"], 0)
        self.assertIsNone(v["success"]["success_rate_delta"])
        self.assertFalse(v["benefit_claim_eligible"])

    def test_timeout_is_retained_as_failed_outcome(self):
        self.records[0]["status"] = "timeout"
        s = self.report()["value_metrics"]["success"]
        self.assertEqual(s["planned_pairs"], 9)
        self.assertEqual(s["arms"]["with"]["successes"], 8)
        self.assertEqual(s["unknown_pairs"], 0)

    def test_harm_and_critical_failure_prevent_positive_claim(self):
        self.records[6]["output"] = "4 AUDIT:"
        v = self.report()["value_metrics"]
        self.assertGreater(v["success"]["harmed"], 0)
        self.assertFalse(v["benefit_claim_eligible"])

    def test_zero_success_has_no_cost_per_success(self):
        for r in self.records:
            if r["arm"] == "with":
                r["output"] = ""
        self.assertIsNone(self.report()["value_metrics"]["arms"]["with"]["cost_per_success_usd"])

    def test_cost_per_success_includes_all_failures(self):
        r = self.report()
        v = r["value_metrics"]
        for arm in ("with", "without"):
            self.assertEqual(v["arms"][arm]["cost_per_success_usd"],
                             r["cost_analysis"]["arms"][arm]["total_usd"] / v["success"]["arms"][arm]["successes"])

    def test_missing_duration_is_not_zero_and_synthetic_is_labeled(self):
        self.records[0].pop("duration_seconds", None)
        self.records[0]["source"] = "synthetic"
        v = self.report()["value_metrics"]
        self.assertIsNone(v["duration_seconds_saved_per_run"])
        self.assertEqual(v["status"], "SIMULATION_ONLY")
        self.assertFalse(v["benefit_claim_eligible"])

    def test_duplicate_or_confounded_records_cannot_claim_benefit(self):
        self.records.append(copy.deepcopy(self.records[0]))
        v = self.report()["value_metrics"]
        self.assertFalse(v["benefit_claim_eligible"])
        self.assertIsNone(v["cost_per_success_saved_usd"])

    def test_sample_size_planning_known_example_and_repetition_invariance(self):
        self.suite["policy"]["power_plan"] = {"expected_family_sd": .2, "minimum_detectable_delta": .1, "alpha": .05, "power": .8}
        plan = self.report()["value_metrics"]["power_plan"]
        self.assertEqual((plan["required_families"], plan["additional_families"]), (32, 29))
        self.suite["runs_per_case"] = 30
        self.assertEqual(self.report()["value_metrics"]["power_plan"]["additional_families"], 29)

    def test_invalid_planning_parameters_rejected(self):
        for value in (True, 0, float("nan"), -1):
            self.suite["policy"]["power_plan"] = {"expected_family_sd": value, "minimum_detectable_delta": .1, "alpha": .05, "power": .8}
            with self.assertRaises(ValidationError):
                validate_suite(self.suite)

    def test_estimates_do_not_become_settled_savings(self):
        for r in self.records:
            r["cost"]["basis"] = "estimate"
        result = self.report()
        self.assertTrue(result["cost_analysis"]["complete_category_coverage"])
        self.assertFalse(result["cost_analysis"]["settled_saving_claim_eligible"])
        self.suite["policy"]["require_settled_costs"] = True
        self.assertEqual(self.report()["verdict"], "INSUFFICIENT_EVIDENCE")

    def settle(self):
        self.suite["policy"]["require_settled_costs"] = True
        for i, r in enumerate(self.records):
            r["cost"].update(basis="settled", evidence_ref=f"test-fixture-only:line-{i}")

    def test_settlement_refs_enable_only_conditional_local_savings(self):
        self.settle()
        r = self.report()
        self.assertTrue(r["cost_analysis"]["settled_saving_claim_eligible"])
        self.assertEqual(r["claim_limits"]["causal_benefit"], "NOT_ESTABLISHED")
        self.records[1]["cost"]["evidence_ref"] = self.records[0]["cost"]["evidence_ref"]
        self.assertFalse(self.report()["cost_analysis"]["settled_saving_claim_eligible"])

    def test_included_overhead_cannot_masquerade_as_settled(self):
        self.settle()
        self.ledger["coverage"]["judge"] = "included"
        self.assertEqual(self.report()["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_rendered_reports_expose_metrics_and_planning(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_reports(self.report(), directory)
            for kind in ("html", "md"):
                content = Path(paths[kind]).read_text(encoding="utf-8")
                for term in ("插件带来了什么收益", "观察到的配对改善", "样本量规划", "结算引用"):
                    self.assertIn(term, content)


if __name__ == "__main__":
    unittest.main()
