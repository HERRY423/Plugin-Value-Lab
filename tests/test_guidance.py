"""Manufactured observations test bounded decisions, not real user benefit."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from value_lab.core import ValidationError, suite_digest, validate_suite
from value_lab.comparison import compare_studies
from value_lab.guidance import conditional_guidance, write_guidance
from tests.test_analysis import fixture, ledger


def decision_policy():
    return {"version": 1, "scope_rationale": "Manufactured fixed tasks; no population inference",
            "minimum_gain": .1, "maximum_quality_loss": .05, "maximum_cost_increase_usd": 3,
            "maximum_failure_rate": 0, "require_settled_costs": False}


def studies(synthetic=False):
    a, b = fixture("old", synthetic=synthetic), fixture("new", synthetic=synthetic)
    for i, s in enumerate((a, b)):
        s["suite"]["conditions"].update(host_version="1.0", model_version=str(i+1))
        s["suite"]["policy"]["use_decision"] = decision_policy()
        s["context"].update(engine_sha256="e"*64, lineage_id="test-lineage-"+str(i), observed_at=f"2026-09-2{i+1}T00:00:00+00:00")
        s["cost_ledger"] = ledger()
        bind(s)
    return a, b


def bind(study):
    digest = suite_digest(study["suite"])
    study["lock"] = {"suite_sha256": digest}
    for r in study["records"]:
        r["suite_sha256"] = digest
        r["conditions"] = deepcopy(study["suite"]["conditions"])


def target(study):
    return {"plugin": deepcopy(study["suite"]["plugin"]), "plugin_sha256": study["context"]["plugin_sha256"],
            "conditions": deepcopy(study["suite"]["conditions"]), "cases": deepcopy(study["suite"]["cases"])}


class GuidanceTests(unittest.TestCase):
    def test_explicit_model_version_change_with_same_alias(self):
        a, b = studies()
        result = compare_studies(a, b, axis="model")
        self.assertTrue(result["comparison_eligible"])
        self.assertEqual(result["axis"], "model")

    def test_explicit_host_only_change(self):
        a, b = studies()
        b["suite"]["conditions"].update(model_version="1", host="another-host")
        bind(b)
        self.assertTrue(compare_studies(a, b, axis="host")["comparison_eligible"])
        b["suite"]["conditions"]["environment"] = "changed-tools-and-environment"
        bind(b)
        self.assertFalse(compare_studies(a, b, axis="host")["comparison_eligible"])

    def test_simultaneous_changes_and_missing_versions_block(self):
        a, b = studies()
        b["suite"]["plugin"]["version"] = "2"
        bind(b)
        self.assertFalse(compare_studies(a, b, axis="model")["comparison_eligible"])
        a, b = studies()
        del b["suite"]["conditions"]["model_version"]
        bind(b)
        self.assertFalse(compare_studies(a, b, axis="model")["comparison_eligible"])

    def test_replay_lineage_and_session_reuse_never_new_observations(self):
        a, b = studies()
        b["context"]["lineage_id"] = a["context"]["lineage_id"]
        self.assertFalse(compare_studies(a, b, axis="model")["comparison_eligible"])
        a, b = studies()
        b["records"][0]["session_id"] = a["records"][0]["session_id"]
        self.assertFalse(compare_studies(a, b, axis="model")["comparison_eligible"])

    def test_changed_protocol_extension_or_engine_blocks(self):
        for mutate in (lambda b: b["suite"].update(input_commitment="changed"), lambda b: b["context"].update(engine_sha256="f"*64)):
            a, b = studies()
            mutate(b)
            bind(b)
            self.assertFalse(compare_studies(a, b, axis="model")["comparison_eligible"])

    def test_bounded_scenario_guidance_without_global_score(self):
        a, b = studies()
        g = conditional_guidance(a, b, target(b), axis="model")
        self.assertEqual(g["status"], "BOUNDED_LOCAL_TRIAL_GUIDANCE")
        cases = {r["case_id"]: r for r in g["cases"]}
        self.assertEqual(cases["structured-delivery"]["status"], "PLUGIN_TRIAL_WITH_REVIEW")
        self.assertEqual(cases["unrelated-request"]["status"], "BASELINE_TRIAL_WITH_REVIEW")
        self.assertFalse(g["automatic_actions"])
        self.assertEqual(g["external_replication"], "NOT_ESTABLISHED")

    def test_baseline_improvement_separated_from_plugin_regression(self):
        a, b = studies()
        for r in b["records"]:
            if r["case_id"] == "structured-delivery" and r["arm"] == "without":
                r["output"] = "SOURCE: same LIMITS: observed"
        g = conditional_guidance(a, b, target(b), axis="model")
        self.assertEqual(g["cases"][0]["trend"], "BASELINE_IMPROVED_MARGIN_NARROWED")
        self.assertEqual(g["cases"][0]["status"], "BASELINE_TRIAL_WITH_REVIEW")
        a, b = studies()
        for r in b["records"]:
            if r["case_id"] == "structured-delivery" and r["arm"] == "with":
                r["output"] = "SOURCE: limited"
        g = conditional_guidance(a, b, target(b), axis="model")
        self.assertEqual(g["cases"][0]["trend"], "WITH_PLUGIN_OUTCOME_DECLINED")
        self.assertEqual(g["cases"][0]["status"], "REVIEW_REQUIRED")

    def test_zero_mean_gain_does_not_establish_noninferiority(self):
        a, b = studies()
        # Both arms score [1,0,1], reordered to [0,1,1]: same mean but loss of 1.
        for r in b["records"]:
            if r["case_id"] == "structured-delivery":
                passed = r["repetition"] != (2 if r["arm"] == "with" else 1)
                r["output"] = "SOURCE: x LIMITS: y" if passed else "wrong"
        g = conditional_guidance(a, b, target(b), axis="model")
        self.assertEqual(g["cases"][0]["observations"]["plugin_gain"], 0)
        self.assertEqual(g["cases"][0]["status"], "REVIEW_REQUIRED")

    def test_target_change_or_new_case_blocks_all_recommendations(self):
        a, b = studies()
        for field in ("model_version", "host_version"):
            t = target(b)
            t["conditions"][field] = "untested"
            g = conditional_guidance(a, b, t, axis="model")
            self.assertEqual(g["status"], "OUT_OF_SCOPE")
            self.assertTrue(all(c["status"] == "REVIEW_REQUIRED" for c in g["cases"]))
        t = target(b)
        t["cases"][0]["prompt"] = "Another scientific question"
        self.assertEqual(conditional_guidance(a, b, t, axis="model")["status"], "OUT_OF_SCOPE")

    def test_target_subset_does_not_hide_negative_cases(self):
        a, b = studies()
        t = target(b)
        t["cases"] = [t["cases"][0]]
        g = conditional_guidance(a, b, t, axis="model")
        self.assertEqual(len(g["cases"]), 3)
        self.assertEqual(sum(c["target_requested"] for c in g["cases"]), 1)

    def test_missing_costs_and_settlement_requirement_block_trial(self):
        a, b = studies()
        del b["records"][0]["cost"]
        self.assertEqual(conditional_guidance(a, b, target(b), axis="model")["status"], "REVIEW_REQUIRED")
        a, b = studies()
        for s in (a, b):
            s["suite"]["policy"]["use_decision"]["require_settled_costs"] = True
            bind(s)
        self.assertEqual(conditional_guidance(a, b, target(b), axis="model")["status"], "REVIEW_REQUIRED")

    def test_no_posthoc_policy_and_no_simulation_promotion(self):
        a, b = studies()
        del b["suite"]["policy"]["use_decision"]
        bind(b)
        with self.assertRaises(ValidationError):
            conditional_guidance(a, b, target(b), axis="model")
        a, b = studies(synthetic=True)
        g = conditional_guidance(a, b, target(b), axis="model")
        self.assertEqual(g["status"], "SIMULATION_ONLY")
        self.assertTrue(all(r["status"] == "REVIEW_REQUIRED" for r in g["cases"]))

    def test_policy_rejects_invalid_risk_limits(self):
        a, _ = studies()
        for field, value in (("maximum_quality_loss", -1), ("minimum_gain", 0), ("maximum_failure_rate", True)):
            suite = deepcopy(a["suite"])
            suite["policy"]["use_decision"][field] = value
            with self.assertRaises(ValidationError):
                validate_suite(suite)

    def test_guidance_rendering_preserves_scope_and_refuses_overwrite(self):
        a, b = studies()
        g = conditional_guidance(a, b, target(b), axis="model")
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "guidance"
            write_guidance(g, out)
            self.assertIn("不自动", (out / "GUIDANCE.md").read_text(encoding="utf-8"))
            with self.assertRaises(ValidationError):
                write_guidance(g, out)


if __name__ == "__main__":
    unittest.main()
