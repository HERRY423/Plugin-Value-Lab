"""Report checks focus on evidence fidelity and hostile evidence handling."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from value_lab.report import write_reports


def example_report():
    return {
        "schema_version": 1,
        "study_id": "paired-demo",
        "plugin": {"name": "Example plugin", "version": "0.1.0"},
        "evidence_type": "synthetic",
        "verdict": "simulation_only",
        "summary": {
            "with_score": 0.75, "without_score": 0.5, "quality_delta": 0.25,
            "expected_runs": 4, "observed_runs": 3, "complete_pairs": 1,
            "clusters": 2, "cost_delta_usd": None,
            "with_cost_usd": None, "without_cost_usd": 0.25,
        },
        "blockers": ["missing one run"],
        "warnings": ["small sample"],
        "cases": [
            {"id": "regression-case", "kind": "negative", "cluster": "a",
             "with_score": 0.5, "without_score": 1.0, "delta": -0.5,
             "runs": [
                 {"arm": "with", "repetition": 1, "status": "completed", "score": 0.5,
                  "grades": {"g1": {"passed": False}}, "cost_usd": None, "issues": []},
                 {"arm": "without", "repetition": 1, "status": "completed", "score": 1,
                  "grades": {}, "cost_usd": 0.25, "issues": []},
             ]},
            {"id": "missing-case", "kind": "task", "cluster": "b",
             "with_score": None, "without_score": 0.0, "delta": None, "runs": [
                 {"arm": "with", "repetition": 1, "status": "timeout", "score": None,
                  "grades": {}, "cost_usd": None, "issues": ["timeout"]},
             ]},
        ],
        "uncertainty": {"method": "cluster bootstrap", "quality_delta_ci95": [-0.5, 0.75]},
        "claim_limits": ["Synthetic runs do not demonstrate benefit."],
        "provenance": {"suite_sha256": "a" * 64},
        "exclusions": {"excluded_pairs": 1, "reason": "missing"},
    }


class ReportTests(unittest.TestCase):
    def render(self, report=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        report = example_report() if report is None else report
        paths = write_reports(report, temporary.name)
        return {kind: Path(path).read_text(encoding="utf-8") for kind, path in paths.items()}

    def test_all_artifacts_preserve_evidence_and_extensions(self):
        report = example_report()
        report["future_extension"] = {"review": ["保留扩展字段", 7]}
        artifacts = self.render(report)
        self.assertEqual(set(artifacts), {"json", "md", "html"})
        self.assertEqual(json.loads(artifacts["json"]), report)
        self.assertIn("future_extension", artifacts["html"])
        self.assertIn("保留扩展字段", artifacts["html"])

    def test_unknown_cost_is_never_rendered_as_zero(self):
        report = example_report()
        for key in ("cost_delta_usd", "with_cost_usd", "without_cost_usd"):
            report["summary"][key] = None
        for case in report["cases"]:
            for run in case["runs"]:
                run["cost_usd"] = None
        artifacts = self.render(report)
        self.assertIn("| 成本 | 未知 | 未知 | 未知 |", artifacts["md"])
        self.assertNotIn("0.0000 USD", artifacts["html"])
        self.assertNotIn("0.0000 USD", artifacts["md"])
        self.assertIn('class="bar-track', artifacts["html"])

    def test_zero_score_and_cost_remain_known(self):
        report = example_report()
        report["summary"].update(with_score=0, quality_delta=0, with_cost_usd=0)
        artifacts = self.render(report)
        self.assertIn("0.0000 USD", artifacts["md"])
        self.assertIn("+0.0 个百分点", artifacts["html"])
        self.assertIn("0.0%", artifacts["html"])

    def test_synthetic_warning_and_claim_limits_are_prominent(self):
        artifacts = self.render()
        for kind in ("md", "html"):
            self.assertIn("合成演示 · 不代表真实收益", artifacts[kind])
            self.assertIn("Synthetic runs do not demonstrate benefit.", artifacts[kind])
            self.assertIn("不构成独立见证的预注册", artifacts[kind])
        self.assertLess(artifacts["html"].index("合成演示 · 不代表真实收益"), artifacts["html"].index('class="metrics"'))

    def test_untrusted_content_cannot_break_html_or_script(self):
        report = example_report()
        attack = '</script><script>alert("x")</script><img src=x onerror="alert(1)">'
        report["study_id"] = attack
        report["plugin"]["name"] = attack
        report["verdict"] = attack
        report["blockers"] = [attack]
        report["warnings"] = [attack]
        report["claim_limits"] = [attack]
        report["provenance"] = {attack: attack}
        report["uncertainty"] = {attack: attack}
        report["exclusions"] = {attack: attack}
        report["cases"][0]["id"] = attack
        report["cases"][0]["cluster"] = attack
        report["cases"][0]["kind"] = attack
        report["cases"][0]["runs"][0]["grades"] = {attack: attack}
        report["cases"][0]["runs"][0]["output"] = attack
        artifacts = self.render(report)
        self.assertNotIn(attack, artifacts["html"])
        self.assertNotIn("<img", artifacts["html"])
        self.assertEqual(artifacts["html"].count("<script>"), 1)
        self.assertEqual(artifacts["html"].count("</script>"), 1)
        self.assertIn("&lt;/script&gt;&lt;script&gt;", artifacts["html"])
        self.assertNotIn("innerHTML", artifacts["html"])
        self.assertNotIn("<script>", artifacts["md"])
        self.assertEqual(json.loads(artifacts["json"])["study_id"], attack)

    def test_markdown_table_content_cannot_inject_a_new_row(self):
        report = example_report()
        report["cases"][0]["id"] = 'a|b\n| injected | [link](https://invalid.example)'
        markdown = self.render(report)["md"]
        self.assertIn(r"a\|b<br>\| injected \| \[link\]", markdown)
        self.assertNotIn("\n| injected |", markdown)

    def test_filters_retain_failures_and_regressions(self):
        html = self.render()["html"]
        self.assertIn('data-state="regression"', html)
        self.assertIn('data-state="blocked"', html)
        self.assertIn("timeout", html)
        self.assertIn("regression-case", html)
        self.assertIn("missing-case", html)
        self.assertIn("count.textContent", html)
        self.assertNotIn('src="http', html)
        self.assertNotIn('href="http', html)

    def test_minimal_report_has_unknown_values_and_no_invented_claim(self):
        artifacts = self.render({"schema_version": 1})
        self.assertIn("未提供案例记录", artifacts["md"])
        self.assertIn("未提供区间或不确定性估计", artifacts["html"])
        self.assertIn("未知", artifacts["html"])
        self.assertNotIn("合成演示 · 不代表真实收益", artifacts["html"])

    def test_input_not_mutated(self):
        report = example_report()
        before = copy.deepcopy(report)
        self.render(report)
        self.assertEqual(report, before)

    def test_native_diagnostics_never_claim_recomputed_quality(self):
        report = example_report()
        report["evidence_type"] = "unverified_native"
        report["verdict"] = "insufficient_evidence"
        report["summary"]["native_total_estimated_cost_usd"] = 1.2345
        artifacts = self.render(report)
        for kind in ("html", "md"):
            self.assertIn("原生结果诊断 · 不能证明插件增益", artifacts[kind])
            self.assertIn("未重新计算或核验其评分语义", artifacts[kind])
            self.assertIn("原生总估算费用", artifacts[kind])
            self.assertIn("1.2345 USD", artifacts[kind])
            self.assertIn("原生 score", artifacts[kind])
        self.assertNotIn("只汇总结果评分；过程检查单独保留", artifacts["html"])

    def test_invalid_json_fails_before_creating_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = example_report()
            report["summary"]["with_score"] = float("nan")
            with self.assertRaises(ValueError):
                write_reports(report, temporary)
            self.assertEqual(list(Path(temporary).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
