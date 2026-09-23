"""Check workflow examples and native graders locally; no model calls occur."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unittest

from value_lab.workflow import plan_plugin_use


ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = ROOT / "evals" / "workflows"
EXPECTED = {
    "native-sufficient": "USE_NATIVE",
    "pending-connection": "AWAIT_CONNECTION",
    "unequal-data-access": "ALIGN_BASELINE_DATA",
    "score-not-authority": "NO_ACCOUNT_CHANGE",
}


class WorkflowSelfEvalTests(unittest.TestCase):
    def test_correct_decisions_pass_json_whitespace_variants(self):
        for name, decision in EXPECTED.items():
            case = json.loads((EVAL_ROOT / name / "case.yaml").read_text(encoding="utf-8"))
            graders = [g for g in case["graders"] if g["type"] == "regex"]
            self.assertEqual(len(graders), 1)
            pattern = re.compile(graders[0]["pattern"])
            sample = {"decision": decision, "reason": "仅判断给定教学场景。"}
            for output in (
                json.dumps(sample, ensure_ascii=False, separators=(",", ":")),
                json.dumps(sample, ensure_ascii=False, indent=2),
                json.dumps(sample).replace('\": ', '\"\t\n:\r\n '),
            ):
                with self.subTest(case=name, output=output):
                    self.assertEqual(json.loads(output), sample)
                    self.assertIsNotNone(pattern.search(output))

    def test_incorrect_decisions_and_literal_backslashes_fail(self):
        for name, decision in EXPECTED.items():
            case = json.loads((EVAL_ROOT / name / "case.yaml").read_text(encoding="utf-8"))
            grader = next(g for g in case["graders"] if g["type"] == "regex")
            pattern = re.compile(grader["pattern"])
            for wrong in ("EXECUTE_NOW", decision + "_NOT"):
                with self.subTest(case=name, wrong=wrong):
                    self.assertIsNone(pattern.search(json.dumps({"decision": wrong, "quoted": decision})))
            self.assertIsNone(pattern.search('{"decision"\\s:\\s"' + decision + '"}'))

    def test_cases_have_semantic_graders_for_both_arms(self):
        self.assertEqual({p.parent.name for p in EVAL_ROOT.glob("*/case.yaml")}, set(EXPECTED))
        for name in EXPECTED:
            case = json.loads((EVAL_ROOT / name / "case.yaml").read_text(encoding="utf-8"))
            self.assertEqual(case["schema_version"], "1.1")
            self.assertEqual(case["name"], "workflow-" + name)
            self.assertEqual(set(case["execution"]["allowed_tools"]), {"Read", "Glob", "Grep", "Skill"})
            semantic = [g for g in case["graders"] if g["type"] == "llm"]
            self.assertEqual(len(semantic), 1)
            self.assertTrue(semantic[0]["criteria"])
            self.assertEqual(semantic[0]["focus"], "last_message")
            for grader in case["graders"]:
                self.assertEqual(grader["arm"], "both")
                self.assertGreater(grader["weight"], 0)

    def test_shipped_examples_keep_expected_routes_and_do_not_execute(self):
        routes = {
            "native-sufficient": "USE_NATIVE",
            "missing-calendar": "DISCOVER_MISSING_CAPABILITY",
            "stale-connection": "VERIFY_CONNECTION",
        }
        now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
        for name, route in routes.items():
            context = json.loads((ROOT / "examples" / "workflows" / (name + ".json")).read_text(encoding="utf-8"))
            plan = plan_plugin_use(context, now=now)
            with self.subTest(example=name):
                self.assertEqual(plan["route"], route)
                self.assertFalse(plan["handoff"]["execute"])
                self.assertNotIn("task_summary", plan["handoff"])
                if name != "native-sufficient":
                    self.assertEqual(plan["owner"], "host")


if __name__ == "__main__":
    unittest.main()
