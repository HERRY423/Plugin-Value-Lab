"""Interop tests use manufactured data, never live model calls."""

from copy import deepcopy
import json
from pathlib import Path
import re
import tempfile
import unittest

from value_lab.core import ValidationError
from value_lab.native import build_command, export_claude, import_claude, native_report


def suite_fixture():
    return {
        "schema_version": 1, "id": "native-test", "plugin": {"name": "fixture", "version": "0.1.0"},
        "evidence_type": "synthetic", "runs_per_case": 1,
        "conditions": {"model": "explicit-model", "host": "fixture-host", "tools": ["Read", "Skill"],
                       "environment": "fixture-env", "budget": {"max_cost_usd": 0.1, "max_turns": 5}},
        "policy": {"min_quality_delta": 0.1, "quality_floor": 0.8, "max_case_regression": 0.1,
                   "min_clusters": 2, "require_cost_saving": False, "human_hourly_usd": 30},
        "cases": [{"id": "alpha", "cluster": "cluster-a", "kind": "task", "prompt": "Return the exact marker.",
                   "graders": [{"id": "literal", "type": "contains", "value": "A[0].*+$^?(x)\\中文",
                                "weight": 1, "critical": True, "dimension": "outcome"}]}],
    }


def result_fixture():
    return {"schemaVersion": 1, "claudeVersion": "2.1.278", "partial": False,
            "costUsd": 0.08, "durationSeconds": 5,
            "aggregates": {"overallScore": 1.0, "meanDelta": 1.0},
            "cases": [{"name": "alpha", "aggregates": {"score": 1.0, "delta": 1.0},
                       "arms": {"with": [{"error": None}], "without": [{"error": None}]}}]}


def frontmatter(path):
    result = {}
    for line in path.read_text(encoding="utf-8").split("---", 2)[1].strip().splitlines():
        key, value = line.split(":", 1)
        result[key] = json.loads(value)
    return result


class NativeTests(unittest.TestCase):
    def test_literal_and_process_export(self):
        suite = suite_fixture()
        suite["cases"][0]["graders"].append({"id": "activation", "type": "not_contains", "value": "BAD[.]+",
                                              "weight": 1, "critical": False, "dimension": "process"})
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "export"
            plan = export_claude(suite, output, Path(temporary) / "plugin")
            grader = frontmatter(output / "evals/alpha/graders/literal.md")
            self.assertIsNotNone(re.search(grader["pattern"], suite["cases"][0]["graders"][0]["value"]))
            self.assertIsNone(re.search(grader["pattern"], "A0whatever"))
            self.assertEqual(grader["arm"], "both")
            process = frontmatter(output / "evals/alpha/graders/activation.md")
            self.assertEqual(process["arm"], "with-only")
            self.assertEqual(process["match"], "not_contains")
            self.assertFalse(plan["executed"])
            self.assertFalse((Path(temporary) / "plugin").exists())
            self.assertIn("--no-publish", plan["command"])

    def test_human_rubric_stays_judge_diagnostic(self):
        suite = suite_fixture()
        suite["cases"][0]["graders"] = [{"id": "expert", "type": "human", "rubric": "PASS if accurate. FAIL if invented.",
                                          "weight": 1, "critical": True, "dimension": "outcome"}]
        with tempfile.TemporaryDirectory() as temporary:
            plan = export_claude(suite, Path(temporary) / "export", Path(temporary) / "plugin")
            self.assertEqual(plan["mappings"][0]["native_type"], "llm")
            self.assertFalse(plan["mappings"][0]["human_review_satisfied"])
            self.assertTrue(any("not human review" in item for item in plan["warnings"]))

    def test_json_equality_refuses_before_writing(self):
        suite = suite_fixture()
        suite["cases"][0]["graders"][0].update(type="json_equals", path="answer", value=4)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "export"
            with self.assertRaises(ValidationError):
                export_claude(suite, output, Path(temporary) / "plugin")
            self.assertFalse(output.exists())

    def test_export_refuses_overwrite_and_unsafe_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "export"
            export_claude(suite_fixture(), output, "plugin")
            original = (output / "suite.json").read_bytes()
            with self.assertRaises(ValidationError):
                export_claude(suite_fixture(), output, "plugin")
            self.assertEqual(original, (output / "suite.json").read_bytes())
            for name in ("../escape", "NUL", "a/child", "trailing."):
                suite = suite_fixture()
                suite["cases"][0]["id"] = name
                with self.assertRaises(ValidationError):
                    export_claude(suite, Path(temporary) / "other", "plugin")

    def test_missing_budget_does_not_invent_authorization(self):
        suite = suite_fixture()
        suite["conditions"]["budget"] = {"max_turns": 5}
        with tempfile.TemporaryDirectory() as temporary:
            plan = export_claude(suite, Path(temporary) / "export", "plugin")
            self.assertIsNone(plan["command"])

    def test_command_has_explicit_controls_without_side_effect_grants(self):
        command = build_command("plugin with spaces", "results", "pinned-model", 0.1, 3)
        self.assertEqual(command[:3], ["claude", "plugin", "eval"])
        for required in ("--ablation", "with-without", "--mocks", "record", "--no-publish", "--no-scaffold"):
            self.assertIn(required, command)
        for forbidden in ("--trust-plugin", "--allow-real-servers", "--allow-tools", "--scaffold", "--publish-report"):
            self.assertNotIn(forbidden, command)
        for invalid in (None, True, 0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValidationError):
                build_command("plugin", "results", "model", invalid)
        for runs in (True, 0, 51, 1.5):
            with self.assertRaises(ValidationError):
                build_command("plugin", "results", "model", 1, runs)

    def test_import_does_not_invent_observations(self):
        result = result_fixture()
        result["cases"][0]["arms"]["with"][0].update(score=1, finalOutput="not a documented mapped field", sessionId="unknown-shape")
        records = import_claude(result, suite_fixture())
        self.assertEqual(len(records), 2)
        for record in records:
            for field in ("session_id", "conditions", "plugin_loaded", "suite_sha256", "duration_seconds"):
                self.assertIsNone(record[field])
            self.assertNotIn("output", record)
            self.assertEqual(record["grades"], {})
            self.assertTrue(record["import_issues"])
            self.assertTrue(all(value is None for value in record["cost"].values()))
        self.assertEqual(records[0]["native"]["run"]["score"], 1)
        self.assertEqual(records[0]["native"]["total_estimated_cost_usd"], 0.08)

    def test_partial_failure_abort_skipped_grader_are_all_retained(self):
        result = result_fixture()
        result.update(partial=True, partialReason="cost_ceiling")
        result["cases"][0]["arms"]["with"] = [
            {"error": "timed out after 300s", "skippedPaidGraders": True},
            {"error": None, "aborted": {"server": "mock", "tool": "tool", "reason": "bad input"}},
        ]
        records = import_claude(result, suite_fixture())
        self.assertEqual([r["status"] for r in records], ["error", "aborted", "completed"])
        self.assertTrue(any("skipped paid graders" in s for s in records[0]["import_issues"]))
        self.assertTrue(all(any("partial" in s for s in r["import_issues"]) for r in records))

    def test_malformed_documented_shapes_and_unmapped_cases_refused(self):
        mutations = [
            lambda r: r.update(schemaVersion=True), lambda r: r.update(schemaVersion=2),
            lambda r: r.update(cases={}), lambda r: r.update(partial="false"),
            lambda r: r.update(costUsd=-1),
            lambda r: r["cases"][0].update(name="unknown"),
            lambda r: r["cases"][0].update(arms={"with": {}}),
            lambda r: r["cases"][0]["arms"].update(treatment=[]),
            lambda r: r["cases"][0]["arms"]["with"][0].pop("error"),
            lambda r: r["cases"][0]["arms"]["with"][0].update(skippedPaidGraders="false"),
            lambda r: r["cases"][0]["arms"]["with"][0].update(aborted={"reason": "bad"}),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result = result_fixture()
                mutation(result)
                with self.assertRaises(ValidationError):
                    import_claude(result, suite_fixture())

    def test_missing_baseline_and_unknown_fields_remain_visible(self):
        result = result_fixture()
        result["futureMetadata"] = {"preserve": True}
        del result["cases"][0]["arms"]["without"]
        before = deepcopy(result)
        report = native_report(result)
        self.assertEqual(report["verdict"], "insufficient_evidence")
        self.assertEqual(report["summary"]["observed_runs"], 1)
        self.assertEqual(report["summary"]["complete_pairs"], 0)
        self.assertIsNone(report["summary"]["without_score"])
        self.assertTrue(any("no native baseline" in item for item in report["blockers"]))
        self.assertEqual(report["provenance"]["native_result"], before)
        self.assertEqual(result, before)


if __name__ == "__main__":
    unittest.main()
