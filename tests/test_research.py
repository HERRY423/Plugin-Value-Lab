"""Research diagnosis validation; every context here is a manufactured fixture."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from value_lab.core import ValidationError, suite_digest
from value_lab.research import DIMENSIONS, compare_research, diagnose_research, research_example, write_research


def context():
    return {"schema_version": 1, "evidence_type": "synthetic", "task": {"question": "Fixture question?", "background": "Manufactured context; no observations.", "decision": "Choose the next discriminating test."}}


def direction(ident="first", **changes):
    return {"id": ident, "title": "Fixture direction", "gap": "Unresolved fixture assumption", "kind": "evidence", "dimension": "design",
            "why_now": "A check could change the next planned step.", "evidence_ids": [],
            "alternative_explanation": "Fixture confounding", "next_test": "Inspect fixture design",
            "success_signal": "Fixture comparison identifiable", "stop_signal": "Fixture confounding cannot be separated",
            "depends_on": [], "impact": 5, "uncertainty": 4, "effort": 2, "cost_usd": 1, "hours": 1, **changes}


class ResearchValidationTests(unittest.TestCase):
    def test_minimal_context_keeps_all_unassessed_dimensions_unknown(self):
        c = context()
        plan = diagnose_research(c)
        self.assertEqual(len(plan["gaps"]), len(DIMENSIONS))
        self.assertTrue(all(row["effective_status"] == "unknown" for row in plan["gaps"]))
        self.assertEqual(plan["next_actions"], [])
        self.assertEqual(plan["questions"].__len__(), 3)
        self.assertEqual(plan["context_sha256"], suite_digest(c))
        self.assertEqual(plan["scientific_authorization"], "NONE")

    def test_example_is_explicitly_synthetic_and_does_not_create_observations(self):
        c = research_example()
        original = deepcopy(c)
        plan = diagnose_research(c)
        self.assertEqual(c, original)
        self.assertEqual(plan["evidence_type"], "synthetic")
        self.assertTrue(all(row["status"] == "hypothesis" for row in plan["context"]["evidence"]))
        self.assertFalse(plan["handoff"]["automatic_install"])
        self.assertEqual(plan["status"], "RESEARCH_DIAGNOSIS_ONLY")
        c["task"]["question"] = "Renamed demonstration"
        self.assertEqual(diagnose_research(c)["evidence_type"], "synthetic")

    def test_unknown_fields_at_every_level_rejected(self):
        cases = []
        c = context(); c["schem_version"] = 1; cases.append(c)
        c = context(); c["task"]["decison"] = "typo"; cases.append(c)
        c = context(); c["dimensions"] = {"invalid": {}}; cases.append(c)
        c = context(); c["constraints"] = {"budjet": 1}; cases.append(c)
        c = context(); c["directions"] = [direction(affort=4)]; cases.append(c)
        for c in cases:
            with self.subTest(context=c), self.assertRaises(ValidationError):
                diagnose_research(c)

    def test_bad_evidence_id_reference_status_and_duplicate_rejected(self):
        source = {"id": "e1", "summary": "Fixture", "source": "fixture-only", "status": "reported"}
        cases = []
        c = context(); c["evidence"] = [source, deepcopy(source)]; cases.append(c)
        c = context(); c["evidence"] = [{**source, "status": "verified"}]; cases.append(c)
        c = context(); c["evidence"] = [{**source, "id": "../unsafe"}]; cases.append(c)
        c = context(); c["directions"] = [direction(evidence_ids=["missing"])]; cases.append(c)
        c = context(); c["evidence"] = [source]; c["directions"] = [direction(evidence_ids=["e1", "e1"])]; cases.append(c)
        for c in cases:
            with self.subTest(context=c), self.assertRaises(ValidationError):
                diagnose_research(c)

    def test_covered_requires_declared_evidence_not_merely_hypotheses(self):
        c = context()
        c["evidence"] = [{"id": "e1", "summary": "Fixture", "source": "fixture-only", "status": "hypothesis"}]
        c["dimensions"] = {"design": {"status": "covered", "rationale": "A submitted assertion", "evidence_ids": ["e1"]}}
        plan = diagnose_research(c)
        self.assertEqual(next(row for row in plan["dimensions"] if row["dimension"] == "design")["effective_status"], "unsupported")
        c["evidence"][0]["status"] = "reported"
        plan = diagnose_research(c)
        row = next(row for row in plan["dimensions"] if row["dimension"] == "design")
        self.assertEqual(row["effective_status"], "covered")
        self.assertEqual(row["support_status"], "declared_support")
        self.assertEqual(plan["scientific_authorization"], "NONE")

    def test_contradicted_evidence_keeps_dimension_contested(self):
        c = context()
        c["evidence"] = [{"id": "e1", "summary": "Fixture", "source": "fixture-only", "status": "contradicted"}]
        c["dimensions"] = {"design": {"status": "covered", "rationale": "Submitted", "evidence_ids": ["e1"]}}
        plan = diagnose_research(c)
        self.assertEqual(next(row for row in plan["gaps"] if row["dimension"] == "design")["effective_status"], "contested")

    def test_inapplicability_needs_rationale_and_is_not_coverage(self):
        c = context(); c["dimensions"] = {"design": {"status": "not_applicable", "rationale": "", "evidence_ids": []}}
        with self.assertRaises(ValidationError):
            diagnose_research(c)
        c["dimensions"]["design"]["rationale"] = "Fixture is descriptive only; applicability remains a supplied declaration."
        plan = diagnose_research(c)
        row = next(row for row in plan["dimensions"] if row["dimension"] == "design")
        self.assertEqual(row["effective_status"], "not_applicable")
        self.assertEqual(row["support_status"], "unsupported")

    def test_required_direction_fields_cannot_be_omitted(self):
        for key in ("alternative_explanation", "next_test", "success_signal", "stop_signal", "why_now", "cost_usd"):
            c = context(); c["directions"] = [direction()]; del c["directions"][0][key]
            with self.subTest(key=key), self.assertRaises(ValidationError):
                diagnose_research(c)

    def test_type_boundaries_and_nonfinite_numbers(self):
        cases = []
        for key, value in (("impact", True), ("uncertainty", 0), ("effort", 2.5), ("cost_usd", -1), ("hours", float("nan")), ("hours", float("inf")), ("cost_usd", False), ("cost_usd", 10 ** 400)):
            c = context(); c["directions"] = [direction(**{key: value})]; cases.append(c)
        for key, value in (("max_next_actions", 0), ("max_next_actions", 6), ("max_next_actions", True), ("budget_usd", float("inf")), ("hours_available", -1)):
            c = context(); c["constraints"] = {key: value}; cases.append(c)
        c = context(); c["schema_version"] = True; cases.append(c)
        c = context(); c["evidence_type"] = "external_certified"; cases.append(c)
        for c in cases:
            with self.subTest(context=c), self.assertRaises(ValidationError):
                diagnose_research(c)

    def test_dependency_cycles_missing_duplicates_and_self_refs_rejected(self):
        for directions in ([direction(depends_on=["missing"])], [direction(depends_on=["first"])],
                           [direction("a", depends_on=["b"]), direction("b", depends_on=["a"])],
                           [direction("a"), direction("a")],
                           [direction("a"), direction("b", depends_on=["a", "a"])]):
            c = context(); c["directions"] = directions
            with self.subTest(directions=directions), self.assertRaises(ValidationError):
                diagnose_research(c)

    def test_capability_queries_only_on_capability_directions(self):
        c = context(); c["directions"] = [direction(capability_query="public format reader")]
        with self.assertRaises(ValidationError):
            diagnose_research(c)
        c["directions"][0]["kind"] = "capability"
        plan = diagnose_research(c)
        handoff = plan["handoff"]["requests"][0]
        self.assertEqual(handoff["authority"], "DISCOVERY_PROPOSAL_ONLY")
        self.assertTrue(handoff["check_existing_capabilities_first"])
        self.assertFalse(plan["handoff"]["automatic_install"])
        self.assertFalse(plan["handoff"]["automatic_transmission"])
        self.assertTrue(plan["handoff"]["requires_host_redaction_review"])
        self.assertNotIn("gap", handoff)
        self.assertNotIn("evidence_ids", handoff)

    def test_capability_query_cannot_smuggle_full_context_or_paths(self):
        for query in ("x" * 161, "reader\nprivate background", r"reader C:\private\study.csv", "reader https://example.com", "/private/study.csv reader"):
            c = context(); c["directions"] = [direction(kind="capability", capability_query=query)]
            with self.subTest(query=query), self.assertRaises(ValidationError):
                diagnose_research(c)


class ResearchPlanningTests(unittest.TestCase):
    def plan(self, directions, constraints=None):
        c = context(); c["directions"] = directions
        if constraints is not None:
            c["constraints"] = constraints
        return diagnose_research(c)

    def test_visible_ranking_is_deterministic_and_not_probability(self):
        plan = self.plan([direction("z", impact=5, uncertainty=5, effort=1), direction("a", impact=5, uncertainty=5, effort=1)])
        self.assertEqual([row["id"] for row in plan["directions"]], ["a", "z"])
        self.assertEqual(plan["directions"][0]["priority_score"], 25)
        self.assertIn("Uncalibrated", plan["priority_policy"]["meaning"])

    def test_cumulative_budget_cannot_select_all_individually_affordable_directions(self):
        plan = self.plan([direction("a", cost_usd=6), direction("b", cost_usd=6), direction("c", cost_usd=4)], {"budget_usd": 10})
        self.assertEqual([row["id"] for row in plan["next_actions"]], ["a", "c"])
        self.assertEqual(plan["resource_plan"]["total_cost_usd"], 10)
        self.assertEqual(next(row for row in plan["directions"] if row["id"] == "b")["disposition"], "over_budget")

    def test_exact_decimal_budget_not_rejected_by_float_rounding(self):
        plan = self.plan([direction("a", cost_usd=0.1), direction("b", cost_usd=0.2)], {"budget_usd": 0.3})
        self.assertEqual(len(plan["next_actions"]), 2)
        self.assertEqual(plan["resource_plan"]["total_cost_usd"], 0.3)

    def test_large_finite_number_cannot_round_away_overspend(self):
        plan = self.plan([direction(cost_usd=10 ** 100 + 1)], {"budget_usd": 10 ** 100})
        self.assertEqual(plan["next_actions"], [])
        self.assertEqual(plan["directions"][0]["disposition"], "over_budget")

    def test_zero_limits_and_zero_estimates_remain_zero(self):
        plan = self.plan([direction("a", cost_usd=0, hours=0), direction("b", cost_usd=1, hours=0)], {"budget_usd": 0, "hours_available": 0})
        self.assertEqual([row["id"] for row in plan["next_actions"]], ["a"])
        self.assertEqual(plan["resource_plan"]["budget_usd"], 0)
        self.assertEqual(plan["resource_plan"]["total_cost_usd"], 0)

    def test_unknown_cost_blocks_constrained_plan_but_is_not_zero_without_cap(self):
        plan = self.plan([direction(cost_usd=None)], {"budget_usd": 10})
        self.assertEqual(plan["next_actions"], [])
        self.assertEqual(plan["directions"][0]["disposition"], "needs_estimate")
        plan = self.plan([direction(cost_usd=None)])
        self.assertIsNone(plan["resource_plan"]["total_cost_usd"])
        self.assertTrue(plan["resource_plan"]["unknown_cost"])
        self.assertEqual(plan["resource_plan"]["known_cost_usd"], 0)
        self.assertFalse(plan["resource_plan"]["budget_verified"])

    def test_cumulative_hours_and_unknown_hours_respected(self):
        plan = self.plan([direction("a", hours=2), direction("b", hours=2), direction("c", hours=None)], {"hours_available": 3})
        self.assertEqual(len(plan["next_actions"]), 1)
        self.assertEqual(plan["resource_plan"]["total_hours"], 2)
        self.assertEqual(next(row for row in plan["directions"] if row["id"] == "c")["disposition"], "needs_estimate")

    def test_rejected_or_deferred_prerequisite_blocks_descendants(self):
        for state in ("rejected", "deferred"):
            plan = self.plan([direction("a", status=state), direction("b", depends_on=["a"]), direction("c", depends_on=["b"])])
            self.assertEqual(plan["next_actions"], [])
            self.assertTrue(all(row["disposition"] == "blocked_dependency" for row in plan["directions"] if row["id"] != "a"))

    def test_selected_dependencies_are_ordered_but_not_declared_complete(self):
        plan = self.plan([direction("a", impact=1, uncertainty=1, status="accepted"), direction("b", depends_on=["a"], impact=5, uncertainty=5)])
        self.assertEqual([row["id"] for row in plan["next_actions"]], ["a", "b"])
        self.assertEqual(plan["next_actions"][1]["readiness"], "after_dependency_verification")
        self.assertFalse(any(row["execution_authorized"] for row in plan["next_actions"]))

    def test_newly_unlocked_high_priority_child_precedes_lower_root(self):
        plan = self.plan([direction("a", impact=4, uncertainty=4), direction("b", depends_on=["a"], impact=5, uncertainty=5), direction("c", impact=1, uncertainty=1)], {"max_next_actions": 2})
        self.assertEqual([row["id"] for row in plan["next_actions"]], ["a", "b"])

    def test_resource_blocked_parent_does_not_unlock_child(self):
        plan = self.plan([direction("a", cost_usd=None), direction("b", depends_on=["a"], cost_usd=0)], {"budget_usd": 1})
        self.assertEqual(plan["next_actions"], [])
        self.assertEqual(next(row for row in plan["directions"] if row["id"] == "b")["disposition"], "waiting_dependency")

    def test_overflow_totals_cannot_be_exported_as_infinity(self):
        with self.assertRaises(ValidationError):
            self.plan([direction("a", cost_usd=1e308), direction("b", cost_usd=1e308)])


class ResearchRevisionTests(unittest.TestCase):
    def test_dropped_topic_or_unsupported_coverage_does_not_verify_closure(self):
        before = research_example(); after = deepcopy(before)
        after["dimensions"]["design"]["status"] = "covered"
        after["dimensions"]["measurement"]["status"] = "not_applicable"
        after["dimensions"]["measurement"]["rationale"] = "Dropped from scope in fixture."
        result = compare_research(before, after)
        self.assertFalse(result["closure_verified"])
        self.assertFalse(result["new_evidence_independently_verified"])
        self.assertEqual(next(row for row in result["remaining_gaps"] if row["dimension"] == "design")["effective_status"], "unsupported")
        self.assertTrue(result["dimension_changes"])

    def test_changed_task_is_explicitly_nonequivalent(self):
        before = context(); after = deepcopy(before); after["task"]["question"] = "Another fixture question?"
        result = compare_research(before, after)
        self.assertTrue(result["task_changed"])
        self.assertEqual(result["comparability"], "CONTEXT_CHANGED")

    def test_evidence_and_direction_revision_changes_are_tracked(self):
        before = research_example(); after = deepcopy(before)
        after["evidence"][0]["status"] = "reported"
        after["evidence"].append({"id": "e-new", "source": "fixture only", "summary": "Manufactured revision", "status": "reported"})
        after["directions"][0]["status"] = "deferred"
        result = compare_research(before, after)
        self.assertEqual(result["evidence_changes"]["added"], ["e-new"])
        self.assertEqual(result["evidence_changes"]["changed"], ["demo-pattern"])
        self.assertIn("check-confounding", result["direction_changes"]["changed"])
        self.assertTrue(result["priority_changes"])
        self.assertFalse(result["new_evidence_independently_verified"])

    def test_evidence_type_reclassification_is_visible(self):
        before = research_example(); after = deepcopy(before); after["evidence_type"] = "local"
        result = compare_research(before, after)
        self.assertTrue(result["evidence_type_changed"])
        self.assertEqual(result["before_evidence_type"], "synthetic")
        self.assertEqual(result["after_evidence_type"], "local")
        self.assertFalse(result["closure_verified"])

    def test_export_recomputes_plan_refuses_tamper_and_overwrite(self):
        plan = diagnose_research(research_example())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "report"
            paths = write_research(plan, root)
            self.assertEqual(json.loads(Path(paths["json"]).read_text(encoding="utf-8")), plan)
            self.assertIn("研究方向诊断", Path(paths["md"]).read_text(encoding="utf-8"))
            self.assertIn("证据类型声明：synthetic", Path(paths["md"]).read_text(encoding="utf-8"))
            with self.assertRaises(ValidationError):
                write_research(plan, root)
            bad = deepcopy(plan); bad["next_actions"][0]["execution_authorized"] = 0
            with self.assertRaises(ValidationError):
                write_research(bad, Path(folder) / "tampered")
            self.assertFalse((Path(folder) / "tampered").exists())

    def test_export_escapes_untrusted_markup(self):
        c = context(); c["task"]["question"] = '<script>alert(1)</script> [remote](https://example.invalid)'
        plan = diagnose_research(c)
        with tempfile.TemporaryDirectory() as folder:
            paths = write_research(plan, Path(folder) / "report")
            content = Path(paths["md"]).read_text(encoding="utf-8")
            self.assertNotIn("<script>", content)
            self.assertIn("&lt;script&gt;", content)
            self.assertIn("\\[remote\\]", content)


if __name__ == "__main__":
    unittest.main()
