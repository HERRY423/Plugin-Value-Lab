"""Scoring, comparison and full-cost edge cases. All observations manufactured."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from value_lab.core import ValidationError, demo_suite, demo_records, evaluate, suite_digest, validate_suite
from value_lab.scoring import inspect_rules
from value_lab.costs import allocation, analyze_costs
from value_lab.comparison import compare_studies
from value_lab.execution import Engine, digest
from value_lab.usage import build_usage_card


def fixture(tag="a", version="1", model="fixed", synthetic=False):
    suite = demo_suite()
    suite["evidence_type"] = "synthetic" if synthetic else "local"
    suite["plugin"]["version"] = version
    suite["conditions"]["model"] = model
    records = demo_records(suite)
    for record in records:
        # Unit-test-only labels exercise strict gates; not actual human observations.
        record["source"] = "synthetic" if synthetic else "manual"
        record["session_id"] = tag + record["session_id"]
    return {"suite": suite, "records": records, "lock": {"suite_sha256": suite_digest(suite)},
            "context": {"plugin_sha256": "a" * 64, "claude_version": "fixed"}}


def ledger(entries=None):
    return {"schema_version": 1, "coverage": {k: "included" for k in ("judge", "setup", "retry", "other")}, "entries": entries or []}


def expense(**changes):
    return {"id": "fee1", "category": "judge", "arm": "with", "amount_usd": 9,
            "basis": "estimate", "evidence_ref": "fixture-invoice:line1", "treatment": "additional", **changes}


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.suite = demo_suite()
        self.case = self.suite["cases"][0]
        self.rule = self.case["graders"][0]

    def test_contradictory_substring_requirements_rejected(self):
        self.rule.update(value="REFERENCE")
        other = {**self.rule, "id": "forbidden", "type": "not_contains", "value": "REF"}
        self.case["graders"].append(other)
        with self.assertRaises(ValidationError):
            validate_suite(self.suite)

    def test_same_rule_with_new_id_or_weight_cannot_double_count(self):
        self.case["graders"].append({**self.rule, "id": "duplicate", "weight": 5})
        self.assertFalse(inspect_rules(self.suite)["valid"])

    def test_calibration_mismatch_blocks_freeze(self):
        self.rule["examples"] = [{"output": self.rule["value"], "passed": False}]
        self.assertFalse(inspect_rules(self.suite)["valid"])

    def test_good_calibration_and_critical_failure_are_visible(self):
        self.rule.update(value="XYZ", critical=True, examples=[{"output": "XYZ", "passed": True}, {"output": "abc", "passed": False}])
        result = inspect_rules(self.suite, {self.case["id"]: ["abc"]})
        self.assertTrue(result["valid"])
        self.assertIn(self.rule["id"], result["cases"][0]["samples"][0]["critical_failures"])
        self.assertIn("not study", result["sample_scope"])

    def test_json_path_and_boolean_number_conflicts(self):
        self.case["graders"] = [{"id": "one", "type": "json_equals", "path": "answer", "value": True,
                                 "weight": 1, "critical": True, "dimension": "outcome"}]
        self.case["graders"].append({**self.case["graders"][0], "id": "two", "value": 1})
        self.assertFalse(inspect_rules(self.suite)["valid"])
        self.case["graders"].pop()
        self.case["graders"][0]["path"] = "items.-1"
        self.assertFalse(inspect_rules(self.suite)["valid"])

    def test_human_calibration_is_not_human_review(self):
        self.case["graders"] = [{"id": "human", "type": "human", "rubric": "Check correctness", "weight": 1, "critical": True, "dimension": "outcome"}]
        result = inspect_rules(self.suite, {self.case["id"]: ["looks good"]})
        self.assertIsNone(result["cases"][0]["samples"][0]["score"])

    def test_unknown_field_rejected(self):
        self.rule["weigth"] = 3
        self.assertFalse(inspect_rules(self.suite)["valid"])

    def test_invalid_sample_shape_is_not_scored_character_by_character(self):
        with self.assertRaises(ValidationError):
            inspect_rules(self.suite, {self.case["id"]: "not a list"})

    def test_weight_sum_overflow_rejected(self):
        for g in self.case["graders"]:
            g["weight"] = 1e308
        self.assertFalse(inspect_rules(self.suite)["valid"])


class CostTests(unittest.TestCase):
    def setUp(self):
        self.study = fixture()
        self.s = self.study["suite"]
        self.r = self.study["records"]
        self.lock = self.study["lock"]

    def report(self, book):
        return evaluate(self.s, self.r, self.lock, book)

    def test_legacy_records_do_not_imply_all_categories_complete(self):
        costs = self.report(None)["cost_analysis"]
        self.assertFalse(costs["complete_category_coverage"])
        self.assertIsNone(costs["arms"]["with"]["total_usd"])
        self.assertGreater(costs["arms"]["with"]["known_subtotal_usd"], 0)

    def test_additional_cost_enters_core_gates_and_usage_card(self):
        self.s["policy"]["require_cost_saving"] = True
        self.lock["suite_sha256"] = suite_digest(self.s)
        for record in self.r:
            record["suite_sha256"] = suite_digest(self.s)
        base = self.report(ledger())
        book = ledger([expense(amount_usd=900)])
        book["coverage"]["judge"] = "itemized"
        result = self.report(book)
        self.assertAlmostEqual(result["summary"]["with_cost_usd"] - base["summary"]["with_cost_usd"], 100)
        self.assertEqual(result["verdict"], "NO_DEMONSTRATED_GAIN")
        card = build_usage_card(self.s, self.r, self.lock, book)
        self.assertFalse(card["use_when"])
        self.assertEqual(card["scope"]["cost_ledger_sha256"], suite_digest(book))

    def test_shared_cost_conserves_total_and_explicit_split(self):
        book = ledger([expense(arm="shared", with_fraction=.25, amount_usd=40)])
        book["coverage"]["judge"] = "itemized"
        plan = allocation(self.s, book)
        self.assertAlmostEqual(sum(v for k, v in plan["extras"].items() if k[2] == "with"), 10)
        self.assertAlmostEqual(sum(plan["extras"].values()), 40)

    def test_unknown_amount_never_becomes_zero(self):
        book = ledger([expense(amount_usd=None)])
        book["coverage"]["judge"] = "itemized"
        result = self.report(book)
        self.assertEqual(result["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(result["summary"]["with_cost_usd"])
        self.assertIsNone(result["cost_analysis"]["arms"]["with"]["total_usd"])

    def test_included_native_or_judge_total_is_not_added_twice(self):
        book = ledger([expense(treatment="included", amount_usd=9)])
        self.assertEqual(self.report(book)["summary"]["with_cost_usd"], self.report(ledger())["summary"]["with_cost_usd"])
        costs = analyze_costs(self.s, self.r, book, self.report(book), native_estimate=88)
        self.assertFalse(costs["native_estimate_added_to_total"])
        self.assertEqual(costs["native_estimate_usd"], 88)

    def test_duplicate_receipt_and_contradictory_coverage_refused(self):
        book = ledger([expense(), expense(id="two")])
        book["coverage"]["judge"] = "itemized"
        with self.assertRaises(ValidationError):
            allocation(self.s, book)
        with self.assertRaises(ValidationError):
            allocation(self.s, ledger([expense()]))

    def test_failed_runs_stay_in_cost_per_success_numerator(self):
        before = self.report(ledger())["cost_analysis"]["arms"]["with"]
        self.r[0].update(status="timeout")
        after = self.report(ledger())["cost_analysis"]["arms"]["with"]
        self.assertEqual(after["total_usd"], before["total_usd"])
        self.assertEqual(after["failed_runs"], 1)
        self.assertGreater(after["cost_per_success_usd"], before["cost_per_success_usd"])

    def test_missing_execution_does_not_shrink_denominator(self):
        self.r.pop(0)
        costs = self.report(ledger())["cost_analysis"]["arms"]["with"]
        self.assertEqual(costs["planned_runs"], 9)
        self.assertIsNone(costs["total_usd"])

    def test_human_timer_overlap_against_raw_runs_blocks(self):
        timer = deepcopy(self.r[0]["human_intervals"])
        amount = self.r[0]["cost"]["human_minutes"] * self.s["policy"]["human_hourly_usd"] / 60
        book = ledger([expense(category="human", amount_usd=amount, human_intervals=timer)])
        result = self.report(book)
        self.assertEqual(result["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertFalse(result["cost_analysis"]["saving_claim_eligible"])

    def test_bad_human_reconciliation_and_shared_allocation_refused(self):
        with self.assertRaises(ValidationError):
            allocation(self.s, ledger([expense(category="human", human_intervals=self.r[0]["human_intervals"], amount_usd=100)]))
        with self.assertRaises(ValidationError):
            allocation(self.s, ledger([expense(arm="shared", with_fraction=1.2, treatment="included")]))

    def test_zero_denominator_and_simulation_never_support_savings(self):
        for record in self.r:
            record["cost"] = {"model_usd": 0, "tool_usd": 0, "human_minutes": 0}
            record["human_intervals"] = []
            record["source"] = "synthetic"
        costs = self.report(ledger())["cost_analysis"]
        self.assertIsNone(costs["saving_fraction"])
        self.assertFalse(costs["saving_claim_eligible"])

    def test_basis_split_never_turns_estimates_into_settled_charges(self):
        for record in self.r:
            record["cost"]["basis"] = "estimate"
        costs = self.report(ledger())["cost_analysis"]["arms"]["with"]
        self.assertGreater(costs["known_amounts_by_basis_usd"]["estimate"], 0)
        self.assertEqual(costs["known_amounts_by_basis_usd"]["settled"], 0)
        self.assertGreater(costs["known_amounts_by_basis_usd"]["declared"], 0)


class ComparisonTests(unittest.TestCase):
    def compare(self, old, new):
        return compare_studies(old, new)

    def test_single_plugin_revision_keeps_baseline_change_separate(self):
        old, new = fixture("old"), fixture("new", version="2")
        new["context"]["plugin_sha256"] = "b"*64
        result = self.compare(old, new)
        self.assertEqual(result["axis"], "plugin_revision")
        self.assertTrue(result["comparison_eligible"])
        self.assertEqual(result["metrics"]["plugin_gain_change"], 0)
        self.assertEqual(result["metrics"]["baseline_quality_change"], 0)

    def test_model_only_and_combined_change(self):
        old, new = fixture("old"), fixture("new", model="new-model")
        result = self.compare(old, new)
        self.assertEqual(result["axis"], "model")
        self.assertTrue(result["comparison_eligible"])
        new = fixture("new", model="new-model", version="2")
        self.assertFalse(self.compare(old, new)["comparison_eligible"])
        self.assertEqual(self.compare(old, new)["axis"], "combined")

    def test_same_version_changed_content_detected(self):
        old, new = fixture("old"), fixture("new")
        new["context"]["plugin_sha256"] = "b"*64
        self.assertEqual(self.compare(old, new)["axis"], "plugin_revision")

    def test_estimate_and_settlement_are_not_comparable_savings(self):
        old, new = fixture("old"), fixture("new", version="2")
        old["cost_ledger"], new["cost_ledger"] = ledger(), ledger()
        for record in old["records"]:
            record["cost"]["basis"] = "estimate"
        for record in new["records"]:
            record["cost"]["basis"] = "settled"
        compared = self.compare(old, new)
        self.assertTrue(compared["comparison_eligible"])
        self.assertFalse(compared["cost_comparison_eligible"])

    def test_changed_rules_budget_or_missing_task_blocks(self):
        old = fixture("old")
        for change in ("rules", "budget", "removed"):
            new = fixture("new", version="2")
            if change == "rules":
                new["suite"]["cases"][0]["graders"][0]["weight"] = 5
            elif change == "budget":
                new["suite"]["conditions"]["budget"]["max_turns"] = 20
            else:
                new["suite"]["cases"].pop()
            result = self.compare(old, new)
            self.assertFalse(result["comparison_eligible"])

    def test_missing_content_identity_reused_sessions_and_synthetic(self):
        old, new = fixture("old"), fixture("new", version="2")
        new["context"].pop("plugin_sha256")
        self.assertFalse(self.compare(old, new)["comparison_eligible"])
        self.assertFalse(self.compare(old, old)["comparison_eligible"])
        self.assertEqual(self.compare(fixture("x", synthetic=True), fixture("y", version="2", synthetic=True))["status"], "SIMULATION_ONLY")


class RevisionTests(unittest.TestCase):
    def test_cost_revision_preserves_source_and_rebinds_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(Path(directory)/"studies")
            try:
                detail = engine.demo()
                job = detail["state"]["id"]
                path = engine.directory(job)
                original = digest(path/"runs.jsonl")
                updated = engine.revise_costs(job, ledger())
                self.assertEqual(original, digest(path/"runs.jsonl"))
                self.assertEqual(updated["integrity"]["mismatches"], [])
                self.assertEqual(updated["analysis_integrity_issues"], [])
                self.assertEqual(updated["analysis"]["report"]["verdict"], "SIMULATION_ONLY")
                revision = updated["analysis"]["id"]
                (path/"analyses"/revision/"cost-ledger.json").write_text("{}")
                with self.assertRaises(ValidationError):
                    engine.revise_costs(job, ledger())
            finally:
                engine.close()


if __name__ == "__main__":
    unittest.main()
