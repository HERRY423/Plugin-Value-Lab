"""Manufactured fixtures only; no independent execution or efficiency evidence."""
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

from value_lab.core import ValidationError, suite_digest, write_json
from value_lab.artifacts import sha
from value_lab.evidence_acquisition import plan_acquisition
from value_lab.workflow import plan_plugin_use, write_plan

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("acquisition_fixture", ROOT / "examples/task-selection/acquisition_demo.py")
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.context, self.artifacts, self.scorers, self.original = example.fixture(self.root, synthetic=False)
        self.request = self.context["evidence_acquisition"]
        self.protocol = self.request["protocol"]

    def freeze_fixture(self):
        self.request["protocol_sha256"] = suite_digest(self.protocol)

    def result(self):
        return plan_acquisition(self.context["task_selection"], self.request, artifact_root=self.artifacts, verifier_root=self.scorers)

    def advance(self, choice=None):
        result = self.result()
        batch = next((b for b in result["next_batch_options"] if b["check_id"] == choice), None) if choice else result["next_batch_options"][0]
        self.assertIsNotNone(batch)
        observed = example.manufactured_result(batch, self.original, self.context)
        self.request["batches"].append({"plan": batch, "result": observed})
        return self.request["batches"][-1]

    def finish(self):
        for _ in range(12):
            result = self.result()
            if not result["next_batch_options"]:
                return result
            self.advance()
        self.fail("Fixture did not stop")

    def test_prospective_batches_skip_irrelevant_full_comparisons_and_confirm(self):
        result = self.finish()
        self.assertEqual(result["state"], "STOP_CHOICE_STABLE")
        self.assertIsNotNone(result["selected_plan_sha256"])
        self.assertEqual(result["planned_runs_started"], 26)
        self.assertEqual(len(result["never_started_check_ids"]), 4)
        self.assertEqual(len(result["confirmed_plan_sha256s"]), 1)
        self.assertEqual(result["statistical_guarantee"], "NONE")
        self.assertFalse(result["automatic_execution"])
        self.assertTrue(result["observations"][-1]["verification_receipts"])

    def test_passed_screen_is_not_adoption_or_confirmation(self):
        self.assertEqual(self.result()["evidence_status"], "NO_OBSERVATIONS")
        self.advance("screen-1")
        result = self.result()
        self.assertIsNone(result["selected_plan_sha256"])
        self.assertFalse(result["confirmed_plan_sha256s"])
        self.assertTrue(any("PASS" in o["outcomes"].values() for o in result["observations"]))

    def test_acquisition_without_task_catalog_cannot_silently_use_legacy_route(self):
        self.context.pop("task_selection")
        with self.assertRaisesRegex(ValidationError, "explicit task_selection"):
            plan_plugin_use(self.context)

    def test_equal_priorities_remain_choices_and_more_complex_checks_defer(self):
        result = self.result()
        self.assertGreater(len(result["next_batch_options"]), 1)
        self.assertTrue(all(b["check_id"].startswith("screen-") for b in result["next_batch_options"]))
        self.advance("screen-0")
        result = self.result()
        self.assertTrue(any(r["deferred_reason"] == "cannot_change_current_frontier" for r in result["agenda"]))

    def test_cheaper_confirmation_can_avoid_unnecessary_screening(self):
        for c in self.protocol["checks"]:
            if c["phase"] == "confirmation":
                c["cost_upper_bound_usd"] = 0.01
        self.freeze_fixture()
        result = self.result()
        self.assertTrue(all(b["check_id"].startswith("confirm-") for b in result["next_batch_options"]))
        self.advance()
        self.assertTrue(self.result()["confirmation_started"])
        self.assertFalse(any(b["check_id"].startswith("screen-") for b in self.result()["next_batch_options"]))

    def test_unknown_budget_numbers_rejected_and_budget_exhaustion_is_valid_stop(self):
        for value in (None, True, -1, float("nan"), float("inf")):
            self.protocol["budget"]["max_usd"] = value
            with self.assertRaises((ValidationError, ValueError)):
                self.freeze_fixture()
                self.result()
        self.protocol["budget"]["max_usd"] = 0.05
        self.freeze_fixture()
        result = self.result()
        self.assertEqual(result["state"], "STOP_BUDGET")
        self.assertIsNone(result["selected_plan_sha256"])
        self.assertTrue(result["unresolved_plan_sha256s"])

    def test_batch_limit_stops_without_green_result(self):
        self.protocol["budget"]["max_batches"] = 1
        self.freeze_fixture()
        self.advance()
        self.assertEqual(self.result()["state"], "STOP_BUDGET")

    def test_pending_batch_keeps_reserved_cost_and_cannot_be_bypassed(self):
        batch = self.advance()
        batch["result"] = None
        result = self.result()
        self.assertEqual(result["state"], "WAIT_FOR_BATCH")
        self.assertEqual(result["budget"]["spent_or_reserved_usd"], 0.1)
        self.assertFalse(result["next_batch_options"])
        self.request["batches"].append(deepcopy(batch))
        with self.assertRaisesRegex(ValidationError, "continued after"):
            self.result()

    def test_resolved_same_gates_are_not_repeated_to_accumulate_checks(self):
        redundant = deepcopy(self.protocol["checks"][3])
        redundant.update(id="redundant-gates", cost_upper_bound_usd=0.2)
        self.protocol["checks"].append(redundant)
        self.freeze_fixture()
        result = self.finish()
        self.assertIn("redundant-gates", result["never_started_check_ids"])
        self.assertEqual(result["planned_runs_started"], 26)
        row = next(r for r in result["agenda"] if r["check_id"] == "redundant-gates")
        self.assertTrue(row["observed_gate_outcomes"])
        self.assertFalse(row["pivotal_case_ids"])

    def test_task_conditions_and_review_requirements_survive_acquisition(self):
        self.finish()
        plan = plan_plugin_use(self.context, artifact_root=self.artifacts, verifier_root=self.scorers)
        self.assertTrue(plan["acquisition"]["required_reviews"])
        self.assertTrue(any(s["action"] == "required_review" for s in plan["steps"]))
        self.assertEqual(len(plan["acquisition"]["candidate_plans"]), 9)

    def test_unknown_cost_reserves_cap_without_new_calls(self):
        batch = self.advance()
        batch["result"]["records"][0]["cost"]["model_usd"] = None
        result = self.result()
        self.assertEqual(result["state"], "REPAIR_EVIDENCE")
        self.assertEqual(result["budget"]["spent_or_reserved_usd"], 0.1)
        self.assertIsNone(result["observations"][0]["total_cost_usd"])

    def test_overrun_is_retained_not_capped_down(self):
        batch = self.advance()
        batch["result"]["records"][0]["cost"]["model_usd"] = 1
        result = self.result()
        self.assertEqual(result["state"], "STOP_BUDGET_OVERRUN")
        self.assertEqual(result["budget"]["spent_or_reserved_usd"], 1)

    def test_next_cap_must_fit_remaining_total_budget(self):
        self.protocol["budget"]["max_usd"] = 0.15
        self.freeze_fixture()
        batch = self.advance()
        for record in batch["result"]["records"]:
            record["cost"]["model_usd"] = 0.02
        result = self.result()
        self.assertAlmostEqual(result["budget"]["spent_or_reserved_usd"], 0.08)
        self.assertEqual(result["state"], "STOP_BUDGET")

    def test_screening_failure_followed_by_confirmation_pass_requires_review(self):
        self.finish()
        batch = self.request["batches"][-1]
        for record in batch["result"]["records"]:
            if record["arm"] != "without":
                continue
            case = next(c for c in batch["plan"]["suite"]["cases"] if c["id"] == record["case_id"])
            verifier = case["graders"][0]["verifier"]
            path = self.artifacts / record["artifacts"]["result"]["path"]
            if verifier["kind"] == "de_table":
                path.write_text("gene,p,q,effect\ng1,0.01,0.03,2\ng2,0.04,0.06,-1\ng3,0.2,0.2,0\n", encoding="utf-8")
            else:
                write_json(path, verifier["expected"])
            record["artifacts"]["result"]["sha256"] = sha(path)
        result = self.result()
        self.assertEqual(result["state"], "REVIEW_CONFLICT")
        self.assertIsNone(result["selected_plan_sha256"])

    def test_continuation_after_stable_stop_is_rejected(self):
        self.finish()
        self.request["batches"].append(deepcopy(self.request["batches"][-1]))
        with self.assertRaisesRegex(ValidationError, "continued after"):
            self.result()

    def test_missing_planned_rows_and_failed_attempts_are_not_dropped(self):
        batch = self.advance()
        del batch["result"]["records"][0]
        result = self.result()
        self.assertEqual(result["state"], "REPAIR_EVIDENCE")
        self.assertTrue(any("Missing" in b for b in result["observations"][0]["blockers"]))

    def test_task_failure_counts_and_can_shrink_shortlist(self):
        batch = self.advance("screen-1")
        record = next(r for r in batch["result"]["records"] if r["arm"] == "with")
        record.update(status="error", failure_kind="task", error="Manufactured failure")
        result = self.result()
        self.assertIn(record["selection_plan_sha256"], result["screening_excluded_plan_sha256s"])

    def test_negative_control_cannot_be_removed_from_decision(self):
        self.protocol["checks"][1]["decision_case_ids"].pop()
        self.freeze_fixture()
        with self.assertRaisesRegex(ValidationError, "negative controls"):
            self.result()

    def test_original_studies_cannot_be_retrofitted_as_prospective(self):
        self.context["task_selection"]["studies"] = self.original
        with self.assertRaisesRegex(ValidationError, "retrofit"):
            self.result()

    def test_protocol_lock_catalog_budget_and_rule_drift_rejected(self):
        original = deepcopy(self.protocol)
        for change in (lambda p: p["budget"].update(max_usd=100), lambda p: p.update(selection_rule="guess"),
                       lambda p: p.update(catalog_sha256="f" * 64)):
            self.request["protocol"] = deepcopy(original)
            change(self.request["protocol"])
            with self.assertRaises(ValidationError):
                self.result()

    def test_started_matrix_cannot_be_shortened_or_relocked(self):
        batch = self.advance()
        batch["plan"]["suite"]["cases"].pop()
        batch["plan"]["lock"]["suite_sha256"] = suite_digest(batch["plan"]["suite"])
        with self.assertRaisesRegex(ValidationError, "Batch lock"):
            self.result()

    def test_prior_observations_cannot_be_changed_after_next_batch_frozen(self):
        self.advance()
        self.advance()
        self.request["batches"][0]["result"]["records"][0]["output"] += " retrospective edit"
        with self.assertRaisesRegex(ValidationError, "prior history"):
            self.result()

    def test_sessions_cannot_be_reused_across_batches(self):
        first = self.advance()
        second = self.advance()
        second["result"]["records"][0]["session_id"] = first["result"]["records"][0]["session_id"]
        result = self.result()
        self.assertEqual(result["state"], "REPAIR_EVIDENCE")

    def test_observed_input_and_component_bindings_are_required(self):
        batch = self.advance()
        batch["result"]["records"][0].pop("input_snapshot")
        self.assertEqual(self.result()["state"], "REPAIR_EVIDENCE")

    def test_holdout_cannot_leak_into_screening_by_input_or_renamed_case(self):
        screen = self.protocol["checks"][1]
        original = deepcopy(screen)
        screen["inputs"] = deepcopy(self.context["task_selection"]["task"]["inputs"])
        self.freeze_fixture()
        with self.assertRaisesRegex(ValidationError, "disjoint"):
            self.result()
        self.protocol["checks"][1] = screen = original
        case = deepcopy(self.context["task_selection"]["task"]["cases"][0])
        case["id"] = "renamed-holdout"
        screen["suite"]["cases"][0] = case
        screen["decision_case_ids"][0] = case["id"]
        self.freeze_fixture()
        with self.assertRaisesRegex(ValidationError, "renamed copies"):
            self.result()

    def test_confirmation_cannot_drop_integration_case(self):
        check = self.protocol["checks"][0]
        check["suite"]["cases"].pop()
        check["decision_case_ids"].pop()
        self.freeze_fixture()
        with self.assertRaisesRegex(ValidationError, "every task stage"):
            self.result()

    def test_synthetic_trajectory_never_yields_real_adoption(self):
        for check in self.protocol["checks"]:
            check["suite"]["evidence_type"] = "synthetic"
        self.freeze_fixture()
        result = self.finish()
        self.assertEqual(result["evidence_status"], "SIMULATION_ONLY")
        self.assertIsNone(result["selected_plan_sha256"])
        self.assertFalse(result["choice_plan_sha256s"])
        plan = plan_plugin_use(self.context, artifact_root=self.artifacts, verifier_root=self.scorers)
        self.assertTrue(plan["headline"].startswith("合成演示："))
        self.assertEqual(plan["steps"][0]["action"], "retain_stopped_decision")
        self.assertNotIn("review_next_batch", [step["action"] for step in plan["steps"]])

    def test_actual_confirmation_bytes_must_still_exist(self):
        while True:
            result = self.result()
            if any(b["check_id"].startswith("confirm-") for b in result["next_batch_options"]):
                break
            self.advance()
        batch = self.advance()
        record = next(r for r in batch["result"]["records"] if r["arm"] == "with")
        (self.artifacts / record["artifacts"]["result"]["path"]).write_text("tampered", encoding="utf-8")
        self.assertEqual(self.result()["state"], "REPAIR_EVIDENCE")

    def test_planning_execution_guard_is_retained(self):
        from value_lab.artifacts import grade_artifact
        self.advance()
        def probe(*args, **kwargs):
            self.assertIn("read-only", grade_artifact({"type": "executable"}, {}, None)[1])
            raise ValidationError("policy probe")
        with patch("value_lab.evidence_acquisition.evaluate", side_effect=probe), self.assertRaisesRegex(ValidationError, "policy probe"):
            self.result()

    def test_stopping_when_no_informative_checks_remain_is_not_success(self):
        self.protocol["checks"] = [self.protocol["checks"][1]]
        self.freeze_fixture()
        self.advance()
        result = self.result()
        self.assertEqual(result["state"], "STOP_NO_RELEVANT_CHECK")
        self.assertIsNone(result["selected_plan_sha256"])

    def test_cli_and_reviewable_plan_use_existing_entry(self):
        write_json(self.root / "context.json", self.context)
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/value_lab.py"), "plan-use", str(self.root / "context.json"),
                               "--artifacts", str(self.artifacts), "--verifiers", str(self.scorers), "--output", str(self.root / "plan")],
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        plan = json.loads((self.root / "plan/plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["route"], "ACQUIRE_DECISION_EVIDENCE")
        self.assertIn("下一批", (self.root / "plan/PLAN.md").read_text(encoding="utf-8"))


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Optional MCP SDK not installed")
class AcquisitionMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_stdio_tool_reaches_batch_protocol(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as directory:
            context, artifacts, scorers, original = example.fixture(Path(directory))
            env = {**os.environ, "PYTHONUTF8": "1", "PVL_ARTIFACT_ROOT": str(artifacts), "PVL_VERIFIER_ROOT": str(scorers)}
            params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "scripts/value_lab.py"), "serve"], env=env)
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    self.assertEqual(len((await session.list_tools()).tools), 6)
                    result = await session.call_tool("plan_plugin_use", {"context": context})
                    self.assertFalse(result.isError, result)
                    plan = json.loads(result.content[0].text)
                    self.assertEqual(plan["acquisition"]["state"], "NEXT_BATCH")
                    data = plan["acquisition"]
                    for _ in range(8):
                        if not data["next_batch_options"]:
                            break
                        batch = data["next_batch_options"][0]
                        context["evidence_acquisition"]["batches"].append({"plan": batch, "result": example.manufactured_result(batch, original, context)})
                        result = await session.call_tool("plan_plugin_use", {"context": context})
                        self.assertFalse(result.isError, result)
                        data = json.loads(result.content[0].text)["acquisition"]
                    self.assertEqual(data["state"], "STOP_CHOICE_STABLE")
                    self.assertTrue(data["observations"][-1]["verification_receipts"])
                    self.assertEqual(data["evidence_status"], "SIMULATION_ONLY")
                    self.assertIsNone(data["selected_plan_sha256"])


if __name__ == "__main__":
    unittest.main()
