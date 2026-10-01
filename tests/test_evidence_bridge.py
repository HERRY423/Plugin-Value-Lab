"""Bridge mutation tests use manufactured files and observations only."""
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
from value_lab.evidence_bridge import plan_bridge
from value_lab.workflow import plan_plugin_use

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bridge_fixture", ROOT / "examples/task-selection/bridge_demo.py")
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.context, self.artifacts, self.scorers = example.fixture(self.root, synthetic=False)
        self.request = self.context["evidence_bridge"]
        self.source = self.request["source_selection"]
        self.target = self.context["task_selection"]

    def result(self):
        return plan_bridge(self.target, self.request, artifact_root=self.artifacts, verifier_root=self.scorers)

    def collect(self, fail=False):
        self.request["bridge_study"] = example.manufactured_bridge(self.context, self.artifacts, self.result(), fail=fail)
        return self.request["bridge_study"]

    def set_target_input(self, value):
        write_json(self.artifacts / "new-input.json", value)
        digest = sha(self.artifacts / "new-input.json")
        self.target["task"]["inputs"]["counts"] = digest
        self.request["target_material"]["sha256"] = digest
        self.target["task"]["facts"]["data_scale"] = len(value["matrix"]["row_ids"])
        self.target["task"]["cases"][0]["graders"][0]["verifier"]["expected"].update(counts=value["matrix"]["values"], sample_ids=value["matrix"]["row_ids"])
        self.target["task"]["cases"][2]["graders"][0]["verifier"]["expected"]["input_snapshot"] = digest

    def test_changed_dataset_generates_one_frozen_target_pair_without_mutating_source(self):
        original = deepcopy(self.context)
        result = self.result()
        self.assertEqual(result["state"], "BRIDGE_REQUIRED")
        self.assertEqual(result["input_check"]["status"], "NEW_DATA_BRIDGE_REQUIRED")
        self.assertEqual(result["proposed_protocol"]["planned_runs"], 6)
        self.assertEqual(result["source_regrading_new_observations"], 0)
        self.assertTrue(result["retained_source_evidence"][0]["verification_receipts"])
        self.assertEqual(self.context, original)
        self.assertTrue(any(c["path"] == "/task/cases" and c["classification"] == "BRIDGE_REQUIRED" for c in result["changes"]))

    def test_new_target_observations_get_new_scope_and_do_not_claim_catalog_minimum(self):
        digest = self.request["source_sha256"]
        self.collect()
        result = self.result()
        self.assertEqual(result["state"], "TARGET_OBSERVATION_SUPPORTED")
        self.assertTrue(result["target_plan_supported"])
        self.assertFalse(result["minimum_established"])
        self.assertFalse(result["old_adoption_claim_transferred"])
        self.assertEqual(suite_digest(self.source), digest)
        self.assertTrue(result["target_selection"]["evidence_gaps"])

    def test_failed_bridge_does_not_inherit_source_success(self):
        self.collect(fail=True)
        result = self.result()
        self.assertEqual(result["state"], "BRIDGE_REJECTED")
        self.assertFalse(result["target_plan_supported"])
        self.assertTrue(result["source_evidence_eligible"])

    def test_synthetic_bridge_never_supports_real_adoption(self):
        with tempfile.TemporaryDirectory() as directory:
            context, artifacts, scorers = example.fixture(Path(directory))
            prepared = plan_plugin_use(context, artifact_root=artifacts, verifier_root=scorers)["bridge"]
            context["evidence_bridge"]["bridge_study"] = example.manufactured_bridge(context, artifacts, prepared)
            result = plan_plugin_use(context, artifact_root=artifacts, verifier_root=scorers)["bridge"]
            self.assertEqual(result["evidence_status"], "SIMULATION_ONLY")
            self.assertFalse(result["target_plan_supported"])
            self.assertIsNone(result["target_selection"]["selected_plan_sha256"])

    def test_missing_or_tampered_input_stays_unknown_not_new_design(self):
        result = plan_bridge(self.target, self.request)
        self.assertEqual(result["state"], "INPUT_EVIDENCE_REQUIRED")
        self.assertIsNone(result["proposed_protocol"])
        (self.artifacts / "new-input.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.result()["input_check"]["status"], "UNKNOWN")

    def test_same_scope_replay_adds_no_observation(self):
        self.context["task_selection"] = self.target = deepcopy(self.source)
        self.target["studies"] = []
        self.target["task"]["summary"] = "Same contract, clearer description"
        self.request["target_material"] = deepcopy(self.request["source_material"])
        result = self.result()
        self.assertEqual(result["state"], "SAME_SCOPE_REPLAY")
        self.assertIsNone(result["proposed_protocol"])
        self.assertFalse(result["target_plan_supported"])

    def test_row_permutation_verifies_inputs_not_arbitrary_producer_invariance(self):
        value = json.loads((self.artifacts / "old-input.json").read_text(encoding="utf-8"))
        value["matrix"]["row_ids"].reverse()
        value["matrix"]["values"].reverse()
        self.set_target_input(value)
        result = self.result()
        self.assertEqual(result["input_check"]["status"], "ROW_PERMUTATION_EQUIVALENT")
        self.assertEqual(result["state"], "BRIDGE_REQUIRED")
        self.assertFalse(result["target_plan_supported"])

    def test_encoding_equivalence_is_not_a_new_execution(self):
        value = json.loads((self.artifacts / "old-input.json").read_text(encoding="utf-8"))
        self.set_target_input(value)
        path = self.artifacts / "new-input.json"
        path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
        digest = sha(path)
        self.target["task"]["inputs"]["counts"] = digest
        self.request["target_material"]["sha256"] = digest
        self.target["task"]["cases"][2]["graders"][0]["verifier"]["expected"]["input_snapshot"] = digest
        self.assertEqual(self.result()["input_check"]["status"], "ENCODING_EQUIVALENT")

    def test_row_ids_without_matching_values_are_not_invariant(self):
        value = json.loads((self.artifacts / "old-input.json").read_text(encoding="utf-8"))
        value["matrix"]["row_ids"].reverse()
        self.set_target_input(value)
        self.assertEqual(self.result()["input_check"]["status"], "NEW_DATA_BRIDGE_REQUIRED")

    def test_design_goal_and_input_kind_changes_force_new_study(self):
        original = deepcopy(self.target)
        for key, value in (("paired", False), ("goal", "causal_inference"), ("input_kind", "transformed"), ("unknown_factor", 1)):
            self.context["task_selection"] = self.target = deepcopy(original)
            self.target["task"]["facts"][key] = value
            result = self.result()
            self.assertEqual(result["state"], "NEW_STUDY_REQUIRED")
            self.assertIsNone(result["proposed_protocol"])

    def test_model_host_tool_and_plugin_changes_force_new_study(self):
        original = deepcopy(self.target)
        changes = [lambda s: s["task"]["conditions"].update(model_version="new-model"),
                   lambda s: s["task"]["conditions"].update(host_version="new-host"),
                   lambda s: s["task"]["conditions"].update(tools=["new-tool"]),
                   lambda s: s["components"][2].update(sha256="f" * 64)]
        for change in changes:
            self.context["task_selection"] = self.target = deepcopy(original)
            change(self.target)
            self.assertEqual(self.result()["state"], "NEW_STUDY_REQUIRED")

    def test_hidden_input_context_and_feature_schema_changes_force_new_study(self):
        original = json.loads((self.artifacts / "new-input.json").read_text(encoding="utf-8"))
        for kind in ("context", "columns"):
            value = deepcopy(original)
            if kind == "context":
                value["context"]["unrecorded_design"] = "changed"
            else:
                value["matrix"]["columns"][0] = "other-gene"
            self.set_target_input(value)
            self.assertEqual(self.result()["state"], "NEW_STUDY_REQUIRED")

    def test_scale_and_sparsity_are_measured_from_actual_input(self):
        self.target["task"]["facts"]["data_scale"] = 40000
        self.assertEqual(self.result()["state"], "INPUT_EVIDENCE_REQUIRED")
        self.target["task"]["facts"]["data_scale"] = 4
        self.target["task"]["facts"]["sparsity"] = 0.999
        self.assertEqual(self.result()["state"], "INPUT_EVIDENCE_REQUIRED")

    def test_environment_change_generates_bound_fresh_protocol(self):
        self.target["task"]["conditions"]["environment"] = "fixture-environment-2"
        proposal = self.result()
        self.assertEqual(proposal["state"], "BRIDGE_REQUIRED")
        self.assertEqual(proposal["proposed_protocol"]["suite"]["conditions"]["environment"], "fixture-environment-2")
        self.collect()
        self.assertEqual(self.result()["state"], "TARGET_OBSERVATION_SUPPORTED")

    def test_arbitrary_new_expected_answers_cannot_be_waived_as_reference_updates(self):
        self.target["task"]["cases"][0]["graders"][0]["verifier"]["expected"]["counts"] = [[999]]
        self.assertEqual(self.result()["state"], "NEW_STUDY_REQUIRED")

    def test_target_scale_outside_either_arm_applicability_requires_new_study(self):
        # Freeze manufactured source evidence with its original scale constraint.
        for component in ("plugin", "script"):
            with self.subTest(component=component), tempfile.TemporaryDirectory() as directory:
                context, artifacts, scorers = example.fixture(Path(directory), synthetic=False)
                request = context["evidence_bridge"]
                source, target = request["source_selection"], context["task_selection"]
                from value_lab.task_selection import select_task_plan
                original_plans = select_task_plan({**source, "studies": []})["plans"]
                for selection in (source, target):
                    for stage in selection["task"]["stages"]:
                        stage["decision_factors"].append("data_scale")
                    for option in selection["options"]:
                        option["requires"]["data_scale"] = [2] if option["component_id"] == component else [2, 4]
                catalog = suite_digest({k: v for k, v in source.items() if k != "studies"})
                plan_ids = {}
                for original in original_plans:
                    manifest = deepcopy(original["manifest"])
                    for step in manifest["steps"]:
                        step["requires"]["data_scale"] = [2] if step["component_id"] == component else [2, 4]
                    plan_ids[original["plan_sha256"]] = suite_digest(manifest)
                for study in source["studies"]:
                    study["suite"]["task_selection"]["catalog_sha256"] = catalog
                    arms = study["suite"]["task_selection"]["arms"]
                    for arm in arms:
                        arms[arm] = plan_ids[arms[arm]]
                    digest = suite_digest(study["suite"])
                    study["lock"]["suite_sha256"] = digest
                    for record in study["records"]:
                        record["suite_sha256"] = digest
                        record["selection_plan_sha256"] = plan_ids[record["selection_plan_sha256"]]
                request["source_sha256"] = suite_digest(source)
                request["source_study_sha256"] = suite_digest(source["studies"][1]["suite"])
                request["source_plan_sha256"] = plan_ids[request["source_plan_sha256"]]
                result = plan_bridge(target, request, artifact_root=artifacts, verifier_root=scorers)
                self.assertTrue(result["source_evidence_eligible"])
                self.assertEqual(result["state"], "NEW_STUDY_REQUIRED")
                self.assertTrue(result["target_applicability_issues"])
                self.assertIsNone(result["proposed_protocol"])
                self.assertFalse(result["target_plan_supported"])

    def test_unchanged_old_counts_reference_cannot_pass_new_dataset(self):
        old = self.source["task"]["cases"][0]["graders"][0]["verifier"]["expected"]["counts"]
        self.target["task"]["cases"][0]["graders"][0]["verifier"]["expected"]["counts"] = deepcopy(old)
        result = self.result()
        self.assertEqual(result["state"], "INPUT_EVIDENCE_REQUIRED")
        self.assertTrue(result["input_reference_issues"]["target"])
        self.assertIsNone(result["proposed_protocol"])

    def test_thresholds_weights_and_stage_changes_cannot_be_called_bridge(self):
        original = deepcopy(self.target)
        for change in (lambda t: t["task"]["cases"][1]["graders"][0]["verifier"].update(bh_tolerance=0.01),
                       lambda t: t["task"]["cases"][0]["graders"][0].update(weight=2),
                       lambda t: t["task"]["stages"][0].update(summary="Changed deliverable")):
            self.context["task_selection"] = self.target = deepcopy(original)
            change(self.target)
            self.assertEqual(self.result()["state"], "NEW_STUDY_REQUIRED")

    def test_source_commitment_and_contract_cannot_be_rewritten(self):
        self.source["studies"][1]["records"][0]["output"] += "changed"
        with self.assertRaisesRegex(ValidationError, "Source evidence"):
            self.result()

    def test_unsupported_contract_is_rejected_even_with_new_hash(self):
        self.request["contract"]["format"] = "semantic-similarity-0.9"
        self.request["contract_sha256"] = suite_digest(self.request["contract"])
        with self.assertRaisesRegex(ValidationError, "reviewed bridge"):
            self.result()

    def test_bad_source_files_cannot_be_rescued_by_success_summary(self):
        record = self.source["studies"][1]["records"][0]
        (self.artifacts / record["artifacts"]["result"]["path"]).write_text("bad", encoding="utf-8")
        self.assertEqual(self.result()["state"], "SOURCE_EVIDENCE_REQUIRED")

    def test_protocol_and_target_changes_after_preparation_rejected(self):
        self.collect()
        self.target["task"]["summary"] += " revised"
        with self.assertRaisesRegex(ValidationError, "protocol changed"):
            self.result()

    def test_old_sessions_and_old_producer_files_cannot_become_new_observations(self):
        bridge = self.collect()
        source = self.source["studies"][1]["records"][0]
        bridge["records"][0]["session_id"] = source["session_id"]
        bridge["records"][0]["artifacts"] = deepcopy(source["artifacts"])
        result = self.result()
        self.assertEqual(result["state"], "BRIDGE_EVIDENCE_REQUIRED")
        self.assertIsNone(result["target_selection"])
        self.assertEqual(len(result["bridge_result"]["issues"]), 2)

    def test_target_missing_rows_unknown_cost_and_missing_observed_bindings_remain_unknown(self):
        original = deepcopy(self.collect())
        for change in (lambda b: b["records"].pop(), lambda b: b["records"][0]["cost"].update(model_usd=None),
                       lambda b: b["records"][0].pop("input_snapshot")):
            bridge = self.request["bridge_study"] = deepcopy(original)
            change(bridge)
            self.assertEqual(self.result()["state"], "BRIDGE_EVIDENCE_REQUIRED")

    def test_target_artifact_tamper_stays_unknown(self):
        bridge = self.collect()
        path = self.artifacts / bridge["records"][0]["artifacts"]["result"]["path"]
        path.write_text("tampered", encoding="utf-8")
        self.assertEqual(self.result()["state"], "BRIDGE_EVIDENCE_REQUIRED")

    def test_unsafe_paths_and_duplicate_json_keys_fail_closed(self):
        self.request["target_material"]["path"] = "../outside.json"
        self.assertEqual(self.result()["input_check"]["status"], "UNKNOWN")
        self.request["target_material"]["path"] = "new-input.json"
        path = self.artifacts / "new-input.json"
        path.write_text('{"matrix":{},"matrix":{},"context":{}}', encoding="utf-8")
        self.request["target_material"]["sha256"] = self.target["task"]["inputs"]["counts"] = sha(path)
        self.assertEqual(self.result()["input_check"]["status"], "UNKNOWN")

    def test_modes_are_explicit_and_program_execution_remains_disabled(self):
        self.context["evidence_acquisition"] = {}
        with self.assertRaisesRegex(ValidationError, "separate mode"):
            plan_plugin_use(self.context)
        self.context.pop("evidence_acquisition")
        from value_lab.artifacts import grade_artifact
        def probe(*a, **kw):
            self.assertIn("read-only", grade_artifact({"type": "executable"}, {}, None)[1])
            raise ValidationError("policy probe")
        with patch("value_lab.task_selection.evaluate", side_effect=probe), self.assertRaisesRegex(ValidationError, "policy probe"):
            self.result()

    def test_cli_returns_bridge_document_using_existing_entry(self):
        write_json(self.root / "context.json", self.context)
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/value_lab.py"), "plan-use", str(self.root / "context.json"),
                               "--artifacts", str(self.artifacts), "--verifiers", str(self.scorers), "--output", str(self.root / "plan")],
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("证据迁移与桥接", (self.root / "plan/PLAN.md").read_text(encoding="utf-8"))


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Optional MCP SDK not installed")
class BridgeMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_stdio_preparation_and_target_file_confirmation(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as directory:
            context, artifacts, scorers = example.fixture(Path(directory))
            env = {**os.environ, "PYTHONUTF8": "1", "PVL_ARTIFACT_ROOT": str(artifacts), "PVL_VERIFIER_ROOT": str(scorers)}
            params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "scripts/value_lab.py"), "serve"], env=env)
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    self.assertEqual(len((await session.list_tools()).tools), 6)
                    result = await session.call_tool("plan_plugin_use", {"context": context})
                    self.assertFalse(result.isError, result)
                    prepared = json.loads(result.content[0].text)["bridge"]
                    self.assertEqual(prepared["state"], "BRIDGE_REQUIRED")
                    context["evidence_bridge"]["bridge_study"] = example.manufactured_bridge(context, artifacts, prepared)
                    result = await session.call_tool("plan_plugin_use", {"context": context})
                    self.assertFalse(result.isError, result)
                    observed = json.loads(result.content[0].text)["bridge"]
                    self.assertEqual(observed["state"], "TARGET_OBSERVATION_SUPPORTED")
                    self.assertEqual(observed["evidence_status"], "SIMULATION_ONLY")
                    self.assertFalse(observed["target_plan_supported"])
                    denied = await session.call_tool("plan_plugin_use", {"context": context, "artifact_root": str(Path(directory))})
                    self.assertTrue(denied.isError)


if __name__ == "__main__":
    unittest.main()
