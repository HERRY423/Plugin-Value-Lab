"""Adversarial planning boundaries independent of the engine author's examples."""
from copy import deepcopy
import unittest

from value_lab.research import DIMENSIONS, compare_research, diagnose_research


def context():
    return {
        "schema_version": 1,
        "evidence_type": "local",
        "task": {
            "question": "Should we reverse a product change after reported retention declined?",
            "background": "Only the aggregate retention chart has been supplied.",
            "decision": "Choose what must be checked before deciding whether to roll back.",
        },
        "evidence": [
            {"id": "aggregate", "summary": "A supplied chart reports lower retention.",
             "source": "Authorized project memo, figure 1", "status": "reported"},
        ],
        "dimensions": {},
        "directions": [],
    }


def direction(ident, *, depends_on=(), status="proposed", cost=0, hours=0):
    return {
        "id": ident, "title": "Check the retention measurement definition",
        "gap": "The before and after metrics may not be comparable.",
        "kind": "method", "dimension": "measurement",
        "why_now": "An inconsistent metric cannot support a rollback decision.",
        "evidence_ids": ["aggregate"],
        "alternative_explanation": "Event tracking changed rather than user behavior.",
        "next_test": "Compare the event definitions and observation windows in the authorized logs.",
        "success_signal": "A consistent metric can be reconstructed for both periods.",
        "stop_signal": "If event definitions differ, pause product-effect interpretation.",
        "depends_on": list(depends_on), "impact": 4, "uncertainty": 4, "effort": 2,
        "cost_usd": cost, "hours": hours, "status": status,
    }


class ResearchAdversarialTests(unittest.TestCase):
    def test_unreferenced_covered_claim_remains_a_gap(self):
        submitted = context()
        submitted["dimensions"]["measurement"] = {
            "status": "covered", "rationale": "The author considers the metric settled.", "evidence_ids": [],
        }
        plan = diagnose_research(submitted)
        measurement = next(row for row in plan["gaps"] if row["dimension"] == "measurement")
        self.assertEqual(measurement["declared_status"], "covered")
        self.assertEqual(measurement["effective_status"], "unsupported")
        self.assertEqual(plan["scientific_authorization"], "NONE")

    def test_a_supporting_reference_does_not_hide_a_contradiction(self):
        submitted = context()
        submitted["evidence"].append({
            "id": "definition-conflict", "summary": "A later note contradicts metric consistency.",
            "source": "Authorized project memo, correction", "status": "contradicted",
        })
        submitted["dimensions"]["measurement"] = {
            "status": "covered", "rationale": "Original coverage claim retained for review.",
            "evidence_ids": ["aggregate", "definition-conflict"],
        }
        plan = diagnose_research(submitted)
        measurement = next(row for row in plan["gaps"] if row["dimension"] == "measurement")
        self.assertEqual(measurement["effective_status"], "contested")
        self.assertEqual(measurement["support_status"], "contested")

    def test_marking_dimensions_inapplicable_is_not_verified_progress(self):
        before = context()
        after = deepcopy(before)
        after["dimensions"] = {
            name: {"status": "not_applicable", "rationale": "Submitter narrowed the stated review scope.",
                   "evidence_ids": []}
            for name in DIMENSIONS
        }
        result = compare_research(before, after)
        self.assertGreater(result["before_gap_count"], result["after_gap_count"])
        self.assertEqual(result["evidence_changes"]["added"], [])
        self.assertFalse(result["closure_verified"])
        self.assertFalse(result["new_evidence_independently_verified"])

    def test_zero_budget_is_a_cap_and_unknown_cost_is_not_free(self):
        submitted = context()
        submitted["directions"] = [
            direction("paid", cost=1), direction("unknown", cost=None), direction("free"),
        ]
        submitted["constraints"] = {"budget_usd": 0, "hours_available": 0, "max_next_actions": 3}
        plan = diagnose_research(submitted)
        states = {row["id"]: row["disposition"] for row in plan["directions"]}
        self.assertEqual([row["id"] for row in plan["next_actions"]], ["free"])
        self.assertEqual(states["paid"], "over_budget")
        self.assertEqual(states["unknown"], "needs_estimate")
        self.assertFalse(plan["resource_plan"]["budget_verified"])

    def test_null_cap_does_not_replace_unknown_estimates_with_zero(self):
        submitted = context()
        submitted["directions"] = [direction("known", cost=1), direction("unknown", cost=None, hours=None)]
        submitted["constraints"] = {"budget_usd": None, "hours_available": None, "max_next_actions": 3}
        plan = diagnose_research(submitted)
        self.assertEqual(len(plan["next_actions"]), 2)
        self.assertEqual(plan["resource_plan"]["known_cost_usd"], 1)
        self.assertIsNone(plan["resource_plan"]["total_cost_usd"])
        self.assertIsNone(plan["resource_plan"]["total_hours"])
        self.assertTrue(plan["resource_plan"]["unknown_cost"])
        self.assertFalse(plan["resource_plan"]["execution_authorized"])

    def test_accepted_descendant_cannot_bypass_rejected_prerequisite(self):
        submitted = context()
        submitted["directions"] = [
            direction("root", status="rejected"),
            direction("middle", depends_on=["root"], status="accepted"),
            direction("last", depends_on=["middle"], status="accepted"),
        ]
        plan = diagnose_research(submitted)
        states = {row["id"]: row["disposition"] for row in plan["directions"]}
        self.assertEqual(plan["next_actions"], [])
        self.assertEqual(states["middle"], "blocked_dependency")
        self.assertEqual(states["last"], "blocked_dependency")

    def test_an_accepted_prerequisite_is_not_recorded_as_completed(self):
        submitted = context()
        submitted["directions"] = [
            direction("prerequisite", status="accepted"),
            direction("dependent", depends_on=["prerequisite"], status="accepted"),
        ]
        plan = diagnose_research(submitted)
        self.assertEqual([row["id"] for row in plan["next_actions"]], ["prerequisite", "dependent"])
        dependent = plan["next_actions"][1]
        self.assertEqual(dependent["readiness"], "after_dependency_verification")
        self.assertFalse(dependent["execution_authorized"])

    def test_background_change_marks_changed_context_without_question_change(self):
        before = context()
        after = deepcopy(before)
        after["task"]["background"] += " A second release occurred at the same time."
        result = compare_research(before, after)
        self.assertEqual(before["task"]["question"], after["task"]["question"])
        self.assertTrue(result["task_changed"])
        self.assertEqual(result["comparability"], "CONTEXT_CHANGED")
        self.assertFalse(result["closure_verified"])

    def test_source_replacement_is_visible_without_claiming_new_independent_evidence(self):
        before = context()
        after = deepcopy(before)
        after["evidence"][0]["source"] = "Different project memo, unverified replacement"
        result = compare_research(before, after)
        self.assertEqual(result["evidence_changes"]["changed"], ["aggregate"])
        self.assertEqual(result["evidence_changes"]["added"], [])
        self.assertFalse(result["new_evidence_independently_verified"])


if __name__ == "__main__":
    unittest.main()
