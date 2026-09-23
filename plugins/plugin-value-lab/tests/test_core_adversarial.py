"""Bounded adversarial checks against misleading positive value decisions.

Fixtures are fabricated test inputs, never observations of a real execution.
The local label is used solely to exercise the non-simulation decision branch.
"""

from copy import deepcopy
import unittest

from value_lab.core import evaluate, suite_digest


def local_fixture():
    suite = {
        "schema_version": 1, "id": "adversarial-test-only",
        "plugin": {"name": "test-fixture", "version": "0"},
        "evidence_type": "local", "runs_per_case": 1,
        "conditions": {"model": "test-model", "host": "test-host", "tools": [],
                       "environment": "unit-test-only", "budget": {"max_turns": 1}},
        "policy": {"min_quality_delta": 0.1, "quality_floor": 0.8,
                   "max_case_regression": 0, "min_clusters": 2,
                   "require_cost_saving": True, "human_hourly_usd": 60},
        "cases": [
            {"id": name, "cluster": name, "kind": "task", "prompt": "Test fixture prompt",
             "graders": [{"id": "quality", "type": "contains", "value": "PASS",
                          "weight": 1, "critical": False, "dimension": "outcome"}]}
            for name in ("case-a", "case-b")
        ],
    }
    records = []
    for case in suite["cases"]:
        for arm in ("with", "without"):
            records.append({
                "case_id": case["id"], "repetition": 1, "arm": arm,
                "suite_sha256": suite_digest(suite), "session_id": f"test-{case['id']}-{arm}",
                "conditions": deepcopy(suite["conditions"]), "plugin_loaded": arm == "with",
                "source": "manual", "status": "completed", "output": "PASS" if arm == "with" else "FAIL",
                "cost": {"model_usd": 0.1 if arm == "with" else 1.0,
                         "tool_usd": 0, "human_minutes": 0},
                "human_intervals": [], "duration_seconds": 1,
            })
    return suite, records


def run_fixture(suite, records):
    return evaluate(suite, records, {"suite_sha256": suite_digest(suite)})


def rebind(suite, records):
    for record in records:
        record["suite_sha256"] = suite_digest(suite)


class CoreAdversarialTests(unittest.TestCase):
    def test_imported_boolean_grades_without_output_stay_partial(self):
        suite, records = local_fixture()
        for record in records:
            del record["output"]
            record["grades"] = {"quality": {"passed": record["arm"] == "with",
                                              "rationale": "Unverified imported Boolean"}}
        report = run_fixture(suite, records)
        self.assertEqual(report["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_nested_json_boolean_does_not_equal_number(self):
        suite, records = local_fixture()
        for case in suite["cases"]:
            case["graders"][0].update(type="json_equals", path="result", value={"approved": True})
        rebind(suite, records)
        for record in records:
            record["output"] = '{"result":{"approved":1}}' if record["arm"] == "with" else '{}'
        report = run_fixture(suite, records)
        self.assertEqual(report["summary"]["with_score"], 0.0)
        self.assertNotEqual(report["verdict"], "PROMISING_LOCAL_SIGNAL")

    def test_observed_budget_boolean_cannot_match_integer_budget(self):
        suite, records = local_fixture()
        for record in records:
            record["conditions"]["budget"]["max_turns"] = True
        report = run_fixture(suite, records)
        self.assertEqual(report["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_contaminated_baseline_prevents_positive_result(self):
        suite, records = local_fixture()
        records[1]["plugin_loaded"] = True
        self.assertEqual(run_fixture(suite, records)["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_duplicate_retry_cannot_replace_original_failure(self):
        suite, records = local_fixture()
        records[0]["status"] = "error"
        records[0]["error"] = "first attempt failed"
        retry = deepcopy(records[0])
        retry.update(status="completed", error=None, session_id="replacement-retry")
        records.append(retry)
        report = run_fixture(suite, records)
        self.assertEqual(report["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(report["cases"][0]["runs"][0]["status"], "error")

    def test_human_grader_requires_human_review_not_imported_grade(self):
        suite, records = local_fixture()
        for case in suite["cases"]:
            case["graders"][0].update(type="human", rubric="Check task correctness independently")
        rebind(suite, records)
        for record in records:
            record["grades"] = {"quality": {"passed": record["arm"] == "with", "rationale": "model grade"}}
        report = run_fixture(suite, records)
        self.assertEqual(report["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(report["summary"]["with_score"])

    def test_zero_priced_unknown_tool_usage_is_not_inferred(self):
        suite, records = local_fixture()
        records[0]["cost"].pop("tool_usd")
        report = run_fixture(suite, records)
        self.assertIsNone(report["summary"]["with_cost_usd"])
        self.assertEqual(report["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_session_reuse_across_different_cases_is_detected(self):
        suite, records = local_fixture()
        records[2]["session_id"] = records[0]["session_id"]
        self.assertEqual(run_fixture(suite, records)["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_overlapping_time_across_arms_blocks_savings_claim(self):
        suite, records = local_fixture()
        for record in records[:2]:
            record["cost"]["human_minutes"] = 1
            record["human_intervals"] = [{"actor": "fixture-person", "start": "2026-01-01T00:00:00Z",
                                            "end": "2026-01-01T00:01:00Z"}]
        report = run_fixture(suite, records)
        self.assertEqual(report["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_high_average_cannot_mask_failed_critical_outcome(self):
        suite, records = local_fixture()
        suite["policy"]["quality_floor"] = 0.5
        suite["cases"][0]["graders"].append({
            "id": "critical-no-harm", "type": "not_contains", "value": "HARM",
            "weight": 0.001, "critical": True, "dimension": "outcome",
        })
        rebind(suite, records)
        records[0]["output"] = "PASS HARM"
        report = run_fixture(suite, records)
        self.assertGreater(report["summary"]["quality_delta"], 0.9)
        self.assertEqual(report["verdict"], "REGRESSION_DETECTED")


if __name__ == "__main__":
    unittest.main()
