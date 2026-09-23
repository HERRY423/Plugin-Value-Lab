"""Exercise shipped native decision graders; no models or paid evals are run.

The regexes use only quoted literals and whitespace matching, a subset shared
by Python re and the documented JavaScript regex engine. These checks validate
that a correct structured answer can pass the mechanical gate; they do not
simulate the separate model judge or establish plugin value.
"""

import json
from pathlib import Path
import re
import unittest


EVAL_ROOT = Path(__file__).resolve().parents[1] / "evals"
EXPECTED = {
    "equal-perfect-scores": {
        "decision": "NO_MEASURED_GAIN", "quality_delta": 0,
        "limitation": "仅据用户提供的汇总，未审核原始记录。",
    },
    "missing-baseline": {
        "decision": "INSUFFICIENT_EVIDENCE",
        "missing": ["匹配的无插件基线", "两侧成本"],
        "reason": "单侧成功不能证明相对增益。",
    },
    "synthetic-gain": {
        "decision": "SIMULATION_ONLY", "observed_delta": 0.45,
        "publishable_statement": "模拟案例展示评估流程，未证明真实用户收益或科学有效性。",
    },
    "process-is-not-outcome": {
        "decision": "OUTCOME_REGRESSION", "quality_delta": -0.2,
        "explanation": "根据所给汇总，流程成功不能补偿任务正确率下降。",
    },
}


def load_case(name):
    return json.loads((EVAL_ROOT / name / "case.yaml").read_text(encoding="utf-8"))


def decision_pattern(case):
    graders = [g for g in case["graders"] if g["type"] == "regex"]
    if len(graders) != 1:
        raise AssertionError("Each shipped case must have one mechanical decision grader")
    grader = graders[0]
    if grader["match"] != "contains" or grader["target"] != "last_message":
        raise AssertionError("Unexpected decision grading semantics")
    return re.compile(grader["pattern"])


class NativeSelfEvalTests(unittest.TestCase):
    def test_correct_json_decisions_pass_across_whitespace(self):
        for name, sample in EXPECTED.items():
            pattern = decision_pattern(load_case(name))
            variants = {
                "compact": json.dumps(sample, ensure_ascii=False, separators=(",", ":")),
                "spaced": json.dumps(sample, ensure_ascii=False),
                "indented": json.dumps(sample, ensure_ascii=False, indent=2),
                "colon_whitespace": json.dumps(sample, ensure_ascii=False).replace(
                    '": ', '"\t\n:\r\n  '
                ),
            }
            for formatting, output in variants.items():
                with self.subTest(case=name, formatting=formatting):
                    self.assertEqual(json.loads(output), sample)
                    self.assertIsNotNone(pattern.search(output))

    def test_incorrect_decisions_fail_even_when_expected_word_is_elsewhere(self):
        for name, sample in EXPECTED.items():
            pattern = decision_pattern(load_case(name))
            for wrong in ("POSITIVE_GAIN", "VERIFIED_VALUE", sample["decision"] + "_NOT"):
                output = {**sample, "decision": wrong, "quoted_candidate": sample["decision"]}
                with self.subTest(case=name, incorrect=wrong):
                    self.assertIsNone(pattern.search(json.dumps(output, ensure_ascii=False)))

    def test_literal_backslash_s_is_not_treated_as_json_whitespace(self):
        for name, sample in EXPECTED.items():
            pattern = decision_pattern(load_case(name))
            invalid_output = '{"decision"\\s:\\s"' + sample["decision"] + '"}'
            with self.subTest(case=name):
                self.assertIsNone(pattern.search(invalid_output))

    def test_decision_and_semantic_graders_remain_available_for_both_arms(self):
        self.assertEqual({p.parent.name for p in EVAL_ROOT.glob("*/case.yaml")}, set(EXPECTED))
        for name in EXPECTED:
            case = load_case(name)
            with self.subTest(case=name):
                self.assertEqual(case["schema_version"], "1.1")
                self.assertEqual(case["name"], name)
                self.assertIn("Skill", case["execution"]["allowed_tools"])
                self.assertNotIn("Bash", case["execution"]["allowed_tools"])
                semantic = [g for g in case["graders"] if g["type"] == "llm"]
                self.assertEqual(len(semantic), 1)
                self.assertTrue(semantic[0]["criteria"].strip())
                self.assertEqual(semantic[0]["focus"], "last_message")
                for grader in case["graders"]:
                    self.assertEqual(grader["arm"], "both")
                    self.assertGreater(grader["weight"], 0)


if __name__ == "__main__":
    unittest.main()
