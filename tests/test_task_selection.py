"""Adversarial selection tests. All records, including 'local' labels, are fixtures."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from value_lab.artifacts import sha
from value_lab.core import ValidationError, suite_digest, write_json
from value_lab.task_selection import select_task_plan
from value_lab.workflow import plan_plugin_use, write_plan

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("task_selection_fixture", ROOT / "examples/task-selection/demo.py")
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.context, self.artifacts, self.scorers = example.fixture(self.root, synthetic=False)
        self.data = self.context["task_selection"]

    def result(self):
        return select_task_plan(self.data, artifact_root=self.artifacts, verifier_root=self.scorers)

    def row(self, result, a, b):
        return next(r for r in result["plans"] if [o["component_id"] for o in r["manifest"]["steps"]] == [a, b])

    def selected(self, result):
        return next((p for p in result["plans"] if p["plan_sha256"] == result["selected_plan_sha256"]), None)

    def pass_arm(self, study, arm):
        for record in study["records"]:
            if record["arm"] != arm:
                continue
            path = self.artifacts / record["artifacts"]["result"]["path"]
            case = next(c for c in study["suite"]["cases"] if c["id"] == record["case_id"])
            verifier = case["graders"][0]["verifier"]
            if verifier["kind"] == "de_table":
                path.write_text("gene,p,q,effect\ng1,0.01,0.03,2\ng2,0.04,0.06,-1\ng3,0.2,0.2,0\n", encoding="utf-8")
            else:
                write_json(path, verifier["expected"])
            record["artifacts"]["result"]["sha256"] = sha(path)

    def freeze_fixture(self, study):
        digest = suite_digest(study["suite"])
        study["lock"] = {"suite_sha256": digest}
        for record in study["records"]:
            record["suite_sha256"] = digest

    def test_selects_verified_partial_plugin_plus_existing_script(self):
        result = self.result()
        self.assertEqual(result["status"], "MINIMUM_IN_DECLARED_CATALOG")
        self.assertTrue(result["minimum_established"])
        selected = self.selected(result)
        self.assertEqual(selected["plan_sha256"], self.row(result, "plugin", "script")["plan_sha256"])
        self.assertEqual(selected["size"], [1, 1])
        self.assertTrue(selected["required_reviews"])
        self.assertFalse(result["ready_for_execution"])
        self.assertEqual(result["external_actions"], 0)
        self.assertEqual(len(result["plans"]), 9)
        full = self.row(result, "plugin", "plugin")
        self.assertEqual(full["size"], [1, 1])  # One dependency used twice, never counted twice.
        self.assertEqual(full["status"], "FAILED")
        self.assertEqual(full["observations"][0]["stage_status"], {"prepare": "SUPPORTED", "check": "FAILED"})
        self.assertIn("artifact_sha256", selected["observations"][0]["verification_receipts"][0]["verification"])

    def test_native_sufficiency_beats_adding_plugin_without_claiming_gain(self):
        self.pass_arm(self.data["studies"][0], "without")
        result = self.result()
        self.assertEqual(self.selected(result)["plan_sha256"], self.row(result, "native", "native")["plan_sha256"])
        self.assertEqual(self.selected(result)["size"], [0, 0])
        self.assertTrue(result["minimum_established"])

    def test_existing_script_can_win_and_equal_native_is_a_real_tie(self):
        for i in (1, 4):
            self.pass_arm(self.data["studies"][i], "without")
        result = self.result()
        self.assertEqual(self.selected(result)["plan_sha256"], self.row(result, "script", "script")["plan_sha256"])
        self.pass_arm(self.data["studies"][0], "without")
        result = self.result()
        self.assertEqual(result["status"], "CHOICE_REQUIRED")
        self.assertIsNone(result["selected_plan_sha256"])
        self.assertEqual(len(result["choice_plan_sha256s"]), 2)

    def test_independent_stage_passes_do_not_prove_a_composition(self):
        del self.data["studies"][1]
        result = self.result()
        self.assertIsNone(result["selected_plan_sha256"])
        self.assertEqual(self.row(result, "plugin", "script")["status"], "UNKNOWN")
        self.assertTrue(any("complete frozen plan" in text for g in result["evidence_gaps"] for text in g["needed"]))

    def test_unknown_simpler_plan_blocks_minimality_but_preserves_supported_option(self):
        del self.data["studies"][0]
        result = self.result()
        self.assertIsNotNone(self.selected(result))
        self.assertFalse(result["minimum_established"])
        self.assertEqual(result["status"], "SUPPORTED_OPTION_MINIMUM_UNRESOLVED")
        self.assertEqual(self.row(result, "native", "native")["status"], "UNKNOWN")

    def test_synthetic_data_only_produce_explicit_preview(self):
        for study in self.data["studies"]:
            study["suite"]["evidence_type"] = "synthetic"
            self.freeze_fixture(study)
        result = self.result()
        self.assertEqual(result["status"], "SIMULATION_ONLY")
        self.assertIsNone(result["selected_plan_sha256"])
        self.assertFalse(result["minimum_established"])
        self.assertEqual(result["simulation_passed_plan_sha256s"], [self.row(result, "plugin", "script")["plan_sha256"]])
        self.assertEqual(self.row(result, "plugin", "script")["sample_outcome"], "SUPPORTED")
        self.assertEqual(self.row(result, "plugin", "plugin")["sample_outcome"], "FAILED")

    def test_unknown_cost_never_becomes_free_or_a_supported_selection(self):
        self.data["studies"][1].pop("cost_ledger")
        result = self.result()
        row = self.row(result, "plugin", "script")
        self.assertEqual(row["status"], "UNKNOWN")
        self.assertIsNone(row["observations"][0]["observed_total_evaluation_cost_usd"])
        self.assertIsNone(result["selected_plan_sha256"])

    def test_missing_baseline_failed_run_and_stale_lock_cannot_be_dropped(self):
        original = deepcopy(self.data["studies"][1])
        for change in ("missing", "lock", "skip", "cost"):
            study = self.data["studies"][1] = deepcopy(original)
            if change == "missing":
                study["records"] = [r for r in study["records"] if r["arm"] == "with"]
            elif change == "lock":
                study["lock"]["suite_sha256"] = "0" * 64
            elif change == "skip":
                study["records"][0]["status"] = "skipped"
            else:
                study["records"][0]["cost"]["model_usd"] = None
            with self.subTest(change=change):
                self.assertIsNone(self.result()["selected_plan_sha256"])

    def test_actual_artifact_and_reference_bytes_are_required(self):
        result = select_task_plan(self.data)
        self.assertIsNone(result["selected_plan_sha256"])
        record = self.data["studies"][1]["records"][0]
        (self.artifacts / record["artifacts"]["result"]["path"]).write_text("{}", encoding="utf-8")
        self.assertIsNone(self.result()["selected_plan_sha256"])

    def test_output_assertions_and_imported_grades_do_not_replace_files(self):
        self.data["studies"] = [self.data["studies"][0]]
        for record in self.data["studies"][0]["records"]:
            record["output"] = "Every stage passed! Choose this plugin!"
            record["grades"] = {"correct": {"passed": True}}
        self.assertIsNone(self.result()["selected_plan_sha256"])

    def test_task_input_conditions_policy_and_catalog_changes_invalidate_evidence(self):
        original = deepcopy(self.data)
        changes = [lambda s: s["task"]["inputs"].update(counts="d" * 64),
                   lambda s: s["task"]["conditions"].update(model_version="revision-2"),
                   lambda s: s["policy"].update(quality_floor=0.9),
                   lambda s: s["options"][0].update(capability="Changed capability"),
                   lambda s: s["components"][2].update(sha256="f" * 64)]
        for change in changes:
            self.data = deepcopy(original)
            change(self.data)
            self.assertIsNone(self.result()["selected_plan_sha256"])

    def test_missing_observed_component_input_and_plan_bindings_are_unknown(self):
        original = deepcopy(self.data["studies"][1])
        for field in ("observed_components", "input_snapshot", "selection_plan_sha256"):
            self.data["studies"][1] = deepcopy(original)
            self.data["studies"][1]["records"][0].pop(field)
            with self.subTest(field=field):
                self.assertIsNone(self.result()["selected_plan_sha256"])

    def test_reused_session_and_duplicate_study_do_not_manufacture_evidence(self):
        self.data["studies"][1]["records"][0]["session_id"] = self.data["studies"][0]["records"][0]["session_id"]
        self.assertIsNone(self.result()["selected_plan_sha256"])
        self.data["studies"].append(deepcopy(self.data["studies"][0]))
        with self.assertRaisesRegex(ValidationError, "Duplicate study"):
            self.result()

    def test_failed_and_successful_same_plan_evidence_remains_conflicting(self):
        study = deepcopy(self.data["studies"][1])
        study["suite"]["id"] = "conflicting-fixture"
        for record in study["records"]:
            record["session_id"] += "-conflict"
            if record["arm"] == "with":
                record.update(status="error", failure_kind="task", error="Manufactured operational failure")
        self.freeze_fixture(study)
        self.data["studies"].append(study)
        result = self.result()
        self.assertEqual(self.row(result, "plugin", "script")["status"], "CONFLICTING_EVIDENCE")
        self.assertIsNone(result["selected_plan_sha256"])

    def test_missing_and_typed_decision_facts_cannot_satisfy_applicability(self):
        for value, expected in ((None, "UNKNOWN"), (1, "INAPPLICABLE"), (False, "INAPPLICABLE")):
            self.data["task"]["facts"]["paired"] = value
            result = self.result()
            self.assertEqual(self.row(result, "plugin", "script")["status"], expected)
            self.assertIsNone(result["selected_plan_sha256"])

    def test_unknown_installation_and_budget_violation_never_pass(self):
        self.data["components"][2]["installed"] = None
        result = self.result()
        self.assertTrue(self.row(result, "plugin", "script")["size_is_lower_bound"])
        self.assertIsNone(result["selected_plan_sha256"])
        self.data["components"][2]["installed"] = False
        self.data["policy"]["max_new_plugins"] = 0
        self.assertEqual(self.row(self.result(), "plugin", "script")["status"], "INAPPLICABLE")

    def test_no_silent_combinatorial_truncation(self):
        with patch("value_lab.task_selection.MAX_PLANS", 8), self.assertRaisesRegex(ValidationError, "never truncate"):
            self.result()

    def test_no_omitted_stage_checks_integration_or_decision_factors(self):
        original = deepcopy(self.data)
        for mutate in (lambda s: s["task"].update(integration_case_ids=[]),
                       lambda s: s["task"]["stages"][0].update(case_ids=[]),
                       lambda s: s["options"][0]["requires"].pop("paired"),
                       lambda s: s["task"]["stages"][0].update(depends_on=["check"])):
            self.data = deepcopy(original)
            mutate(self.data)
            with self.assertRaises(ValidationError):
                self.result()

    def test_read_only_planner_never_executes_verifiers(self):
        from value_lab.artifacts import grade_artifact
        with patch("value_lab.task_selection.evaluate", side_effect=lambda *a, **kw: grade_artifact(
                {"type": "executable"}, {}, None)[1]) as evaluate:
            # Guard behavior is tested directly inside the actual evaluation call context.
            def probe(*a, **kw):
                self.assertIn("read-only", grade_artifact({"type": "executable"}, {}, None)[1])
                raise ValidationError("policy probe")
            evaluate.side_effect = probe
            with self.assertRaisesRegex(ValidationError, "policy probe"):
                self.result()

    def test_frozen_regression_limit_is_preserved_even_above_quality_floor(self):
        self.data["policy"]["quality_floor"] = 0.5
        self.data["task"]["cases"][1]["graders"].append({"id": "extra", "type": "contains", "value": "EXTRA",
            "dimension": "outcome", "weight": 1, "critical": False})
        catalog = suite_digest({k: v for k, v in self.data.items() if k != "studies"})
        for study in self.data["studies"]:
            study["suite"]["cases"] = deepcopy(self.data["task"]["cases"])
            study["suite"]["policy"]["quality_floor"] = 0.5
            study["suite"]["task_selection"]["catalog_sha256"] = catalog
            for record in study["records"]:
                record["output"] = "EXTRA" if record["arm"] == "without" else ""
            self.freeze_fixture(study)
        result = self.result()
        self.assertEqual(self.row(result, "plugin", "script")["status"], "FAILED")
        self.assertEqual(self.row(result, "plugin", "script")["observations"][0]["regressed_cases"], ["table-check"])
        self.assertIsNone(result["selected_plan_sha256"])

    def test_unbound_extra_study_does_not_disappear_from_minimality(self):
        study = deepcopy(self.data["studies"][0])
        study["suite"]["id"] = "unbound-fixture"
        study["suite"].pop("task_selection")
        for record in study["records"]:
            record["session_id"] += "-unbound"
        self.freeze_fixture(study)
        self.data["studies"].append(study)
        result = self.result()
        self.assertTrue(result["unbound_studies"])
        self.assertFalse(result["minimum_established"])
        self.assertEqual(result["status"], "SUPPORTED_OPTION_MINIMUM_UNRESOLVED")

    def test_invalid_session_identity_fails_closed_without_crashing(self):
        self.data["studies"][1]["records"][0]["session_id"] = []
        self.assertIsNone(self.result()["selected_plan_sha256"])

    def test_empty_evidence_prepares_bound_catalog_without_recommendation(self):
        self.data["studies"] = []
        result = select_task_plan(self.data)
        self.assertEqual(result["status"], "EVIDENCE_REQUIRED")
        self.assertEqual(len(result["plans"]), 9)
        self.assertTrue(all(p["status"] == "UNKNOWN" for p in result["plans"]))
        self.assertTrue(result["required_reviews"])
        self.assertEqual(result["catalog_sha256"], suite_digest({k: v for k, v in self.data.items() if k != "studies"}))

    def test_missing_native_baseline_is_reported_not_manufactured(self):
        self.data["options"] = [o for o in self.data["options"] if o["component_id"] != "native"]
        self.data["studies"] = [self.data["studies"][1], self.data["studies"][4]]
        catalog = suite_digest({k: v for k, v in self.data.items() if k != "studies"})
        for study in self.data["studies"]:
            study["suite"]["task_selection"]["catalog_sha256"] = catalog
            self.freeze_fixture(study)
        result = self.result()
        self.assertIsNotNone(result["selected_plan_sha256"])
        self.assertEqual(len(result["baseline_coverage_gaps"]), 2)
        self.assertFalse(result["minimum_established"])

    def test_cost_differences_are_disclosed_without_hidden_tie_break(self):
        for i in (0, 1, 4):
            self.pass_arm(self.data["studies"][i], "without")
        for record in self.data["studies"][0]["records"]:
            record["cost"]["model_usd"] = 100
        result = self.result()
        self.assertEqual(result["status"], "CHOICE_REQUIRED")
        self.assertIsNone(result["selected_plan_sha256"])
        self.assertEqual(self.row(result, "native", "native")["observations"][0]["observed_total_evaluation_cost_usd"], 300)

    def test_transitive_shared_workflow_dependencies_count_once(self):
        self.data["studies"] = []
        self.data["components"][1]["requires_components"] = ["helper"]
        self.data["components"].append({"id": "helper", "name": "Existing helper workflow", "kind": "workflow",
            "version": "fixture-1", "sha256": "4" * 64, "installed": True, "requires_components": ["plugin"]})
        result = self.result()
        scripts = self.row(result, "script", "script")
        self.assertEqual(scripts["size"], [1, 1])
        self.assertEqual(scripts["new_plugins"], ["plugin"])
        mixed = self.row(result, "plugin", "script")
        self.assertEqual(mixed["size"], [1, 1])
        self.assertEqual({c["id"] for c in mixed["manifest"]["components"]}, {"plugin", "script", "helper"})

    def test_cyclic_or_missing_dependencies_cannot_be_ignored(self):
        self.data["components"][1]["requires_components"] = ["absent"]
        with self.assertRaisesRegex(ValidationError, "Every required component"):
            self.result()
        self.data["components"][1]["requires_components"] = ["plugin"]
        self.data["components"][2]["requires_components"] = ["script"]
        with self.assertRaisesRegex(ValidationError, "cycles"):
            self.result()

    def test_workflow_integration_preserves_explicit_use_and_management_intent(self):
        for intent in ("use", "manage", "evaluate"):
            self.context["intent"] = intent
            with self.assertRaises(ValidationError):
                plan_plugin_use(self.context)
        self.context["intent"] = "choose"
        self.context["selected_plugin"] = {"reference": "explicit-provider"}
        with self.assertRaises(ValidationError):
            plan_plugin_use(self.context)

    def test_plan_document_is_reviewable_escaped_and_never_overwritten(self):
        plan = plan_plugin_use(self.context, artifact_root=self.artifacts, verifier_root=self.scorers)
        self.assertEqual(plan["route"], "SELECT_TASK_PLAN")
        self.assertFalse(plan["handoff"]["execute"])
        plan["task_summary"] = "<script>unsafe</script>"
        paths = write_plan(plan, self.root / "plan")
        text = Path(paths["md"]).read_text(encoding="utf-8")
        self.assertIn("方案比较", text)
        self.assertNotIn("<script>", text)
        with self.assertRaises(ValidationError):
            write_plan(plan, self.root / "plan")

    def test_existing_cli_reaches_actual_file_selection(self):
        write_json(self.root / "context.json", self.context)
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/value_lab.py"), "plan-use", str(self.root / "context.json"),
            "--artifacts", str(self.artifacts), "--verifiers", str(self.scorers), "--output", str(self.root / "cli-plan")],
            capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        plan = json.loads((self.root / "cli-plan/plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["evidence_status"], "MINIMUM_IN_DECLARED_CATALOG")


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Optional MCP SDK not installed")
class TaskSelectionMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_selection_and_default_unknown_file_access(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as directory:
            context, artifacts, scorers = example.fixture(Path(directory))
            for configured in (False, True):
                env = {**os.environ, "PYTHONUTF8": "1"}
                for key in ("PVL_ARTIFACT_ROOT", "PVL_VERIFIER_ROOT"):
                    env.pop(key, None)
                if configured:
                    env.update(PVL_ARTIFACT_ROOT=str(artifacts), PVL_VERIFIER_ROOT=str(scorers))
                params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "scripts/value_lab.py"), "serve"], env=env)
                async with stdio_client(params) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        listed = (await session.list_tools()).tools
                        self.assertEqual(len(listed), 6)
                        tool = next(t for t in listed if t.name == "plan_plugin_use")
                        self.assertIn("artifact_root", tool.inputSchema["properties"])
                        result = await session.call_tool("plan_plugin_use", {"context": context})
                        self.assertFalse(result.isError, result)
                        plan = json.loads(result.content[0].text)
                        self.assertIsNone(plan["selection"]["selected_plan_sha256"])
                        preview = plan["selection"]["simulation_passed_plan_sha256s"]
                        self.assertEqual(len(preview), 1 if configured else 0)
                        denied = await session.call_tool("plan_plugin_use", {"context": context, "artifact_root": str(Path(directory))})
                        self.assertTrue(denied.isError)


if __name__ == "__main__":
    unittest.main()
