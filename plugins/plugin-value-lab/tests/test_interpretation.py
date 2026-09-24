"""Endpoint estimands, missingness and pairing sensitivity, with manufactured runs."""
from copy import deepcopy
import unittest

from value_lab.core import ValidationError, demo_suite, demo_records, evaluate, suite_digest, validate_suite
from value_lab.interpretation import CLASSES, ESTIMANDS, _endpoint


def plan():
    rules = {e: {c: "unknown" for c in CLASSES} for e in ESTIMANDS}
    for e in ESTIMANDS:
        rules[e]["tested_system"] = "failure"
    for e in ("runtime_reliability", "full_delivery"):
        rules[e].update(provider="failure", infrastructure="failure")
    return {"version": 1, "primary_estimand": "scientific_correctness", "pairing_rationale": "Same case and randomized execution block; repetitions are not individual counterfactuals",
            "task_distribution": "Three manufactured tutorial families only", "failure_rules": rules}


class InterpretationTests(unittest.TestCase):
    def setUp(self):
        self.suite = demo_suite()
        self.suite["policy"]["value_interpretation"] = plan()
        self.records = demo_records(self.suite)

    def report(self):
        digest = suite_digest(self.suite)
        for r in self.records:
            r["suite_sha256"] = digest
        return evaluate(self.suite, self.records, {"suite_sha256": digest})

    def test_cost_missing_does_not_erase_observed_checks(self):
        before = self.report()["value_interpretation"]["endpoints"]
        for row in self.records:
            row.pop("cost")
        report = self.report()
        self.assertEqual(before, report["value_interpretation"]["endpoints"])
        self.assertFalse(report["summary"]["comparison_eligible"])
        self.assertEqual(report["value_interpretation"]["cash_savings"], "INSUFFICIENT_EVIDENCE")
        self.assertTrue(any(c["status"] == "PASS" for c in report["value_interpretation"]["check_claims"]))

    def test_provider_failure_distinguished_from_correctness(self):
        row = self.records[0]
        row.update(status="error", error="provider unavailable", failure_observation={"class": "provider", "evidence_ref": "trace:1", "rationale": "Observed service error"})
        e = self.report()["value_interpretation"]["endpoints"]
        self.assertEqual(e["scientific_correctness"]["arms"][row["arm"]]["unknown"], 1)
        self.assertEqual(e["runtime_reliability"]["arms"][row["arm"]]["failures"], 1)

    def test_unknown_failure_and_absent_run_stay_unknown(self):
        self.records[0].update(status="timeout")
        self.records.pop()
        for e in self.report()["value_interpretation"]["endpoints"].values():
            self.assertEqual(sum(r["unknown"] for r in e["arms"].values()), 2)
            self.assertTrue(all(r["planned"] == 9 for r in e["arms"].values()))

    def test_completed_measurement_failure_retains_reliability(self):
        self.records[0]["failure_observation"] = {"class": "measurement", "evidence_ref": "grader-log:1", "rationale": "review unavailable"}
        e = self.report()["value_interpretation"]["endpoints"]
        self.assertEqual(e["scientific_correctness"]["unknown_pairs"], 1)
        self.assertEqual(e["runtime_reliability"]["unknown_pairs"], 0)

    def test_plan_validation_blocks_relabeling_unknown_as_failure(self):
        self.suite["policy"]["value_interpretation"]["failure_rules"]["scientific_correctness"]["provider"] = "failure"
        with self.assertRaises(ValidationError):
            validate_suite(self.suite)

    def test_pairing_changes_transitions_not_success_delta(self):
        def case(baseline):
            rows = []
            for arm, values in (("with", [True, False]), ("without", baseline)):
                for rep, passed in enumerate(values, 1):
                    rows.append({"arm": arm, "repetition": rep, "status": "completed", "score": int(passed),
                                 "grades": [{"passed": passed, "scored": True, "critical": True}]})
            return [{"cluster": "one", "runs": rows}]
        rules = plan()["failure_rules"]["scientific_correctness"]
        a = _endpoint(case([True, False]), 2, .8, "scientific_correctness", rules)
        b = _endpoint(case([False, True]), 2, .8, "scientific_correctness", rules)
        self.assertEqual(a["task_distribution_success_delta"], b["task_distribution_success_delta"])
        self.assertEqual((a["observed_paired_improvements"], a["observed_paired_regressions"]), (0, 0))
        self.assertEqual((b["observed_paired_improvements"], b["observed_paired_regressions"]), (1, 1))

    def test_legacy_report_structure_and_digest_preserved(self):
        del self.suite["policy"]["value_interpretation"]
        report = self.report()
        self.assertNotIn("value_interpretation", report)
        self.assertNotIn("observation_issues", report["cases"][0]["runs"][0])

    def test_mismatched_provenance_stays_unknown(self):
        self.records[0]["plugin_loaded"] = None
        for e in self.report()["value_interpretation"]["endpoints"].values():
            self.assertEqual(e["unknown_pairs"], 1)

    def test_failure_requires_evidence_and_no_completed_contradiction(self):
        self.records[0]["failure_observation"] = {"class": "provider", "evidence_ref": "log", "rationale": "test"}
        with self.assertRaises(ValidationError):
            self.report()

    def test_changed_plan_changes_protocol_digest(self):
        before = suite_digest(self.suite)
        self.suite["policy"]["value_interpretation"]["primary_estimand"] = "full_delivery"
        self.assertNotEqual(before, suite_digest(self.suite))


if __name__ == "__main__":
    unittest.main()
