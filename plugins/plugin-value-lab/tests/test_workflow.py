from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from value_lab.core import ValidationError
from value_lab.workflow import plan_plugin_use, write_plan


NOW = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


def context():
    return {"schema_version": 1, "intent": "choose", "task": {"summary": "Private project Alpha: summarize account files", "capability": "documents"},
            "native_fit": "insufficient", "connected_fit": "insufficient", "plugin_management_available": True,
            "evaluation_goal": "quality", "baseline_data_access": "same"}


def selected(**changes):
    result = {"reference": "example-docs@sample-market", "display_name": "Example Docs", "kind": "chatgpt_plugin",
              "installed": True, "connection_state": "ready", "observed_at": NOW.isoformat(), "status_source": "host"}
    result.update(changes)
    return result


class WorkflowTests(unittest.TestCase):
    def plan(self, data):
        return plan_plugin_use(data, now=NOW)

    def test_native_sufficient_never_searches_or_requires_trial(self):
        data = context()
        data["native_fit"] = "sufficient"
        result = self.plan(data)
        self.assertEqual(result["route"], "USE_NATIVE")
        self.assertEqual(result["handoff"]["kind"], "none")
        self.assertEqual(len(result["steps"]), 1)

    def test_unknown_fit_does_not_become_missing_capability(self):
        data = context()
        data["native_fit"] = "unknown"
        self.assertEqual(self.plan(data)["route"], "CHECK_EXISTING_CAPABILITIES")

    def test_discovery_handoff_omits_private_task_and_never_executes(self):
        result = self.plan(context())
        self.assertEqual(result["route"], "DISCOVER_MISSING_CAPABILITY")
        self.assertEqual(result["handoff"]["capability_query"], "documents")
        self.assertNotIn("Alpha", json.dumps(result["handoff"]))
        self.assertFalse(result["handoff"]["execute"])
        self.assertNotIn("plugin_ids", result["handoff"])

    def test_explicit_provider_use_is_respected(self):
        data = context()
        data.update(intent="use", native_fit="sufficient", connected_fit="sufficient", selected_plugin=selected())
        self.assertEqual(self.plan(data)["route"], "USE_CONNECTED")

    def test_explicit_use_without_target_is_not_generic_native_use(self):
        data = context()
        data.update(intent="use", native_fit="sufficient")
        self.assertEqual(self.plan(data)["route"], "CHECK_EXISTING_CAPABILITIES")

    def test_private_local_path_cannot_be_outbound_chatgpt_reference(self):
        data = context()
        data.update(intent="use", selected_plugin=selected(reference="C:\\private\\patient"))
        with self.assertRaises(ValidationError):
            self.plan(data)

    def test_installation_is_not_connection(self):
        for connection in ("unknown", "not_connected"):
            data = context()
            data.update(intent="use", connected_fit="sufficient", selected_plugin=selected(connection_state=connection))
            self.assertEqual(self.plan(data)["route"], "VERIFY_CONNECTION")

    def test_pending_never_suggests_again(self):
        data = context()
        data.update(intent="use", selected_plugin=selected(connection_state="pending", installed=False))
        result = self.plan(data)
        self.assertEqual(result["route"], "AWAIT_CONNECTION")
        self.assertFalse(any("suggest" in step["action"] for step in result["steps"]))

    def test_stale_pending_does_not_claim_request_still_exists(self):
        data = context()
        data.update(intent="use", selected_plugin=selected(connection_state="pending", observed_at="2020-01-01T00:00:00Z"))
        self.assertEqual(self.plan(data)["route"], "VERIFY_CONNECTION")

    def test_local_pending_stays_with_host_even_when_manager_available(self):
        data = context()
        data.update(intent="use", selected_plugin=selected(
            kind="local_code_plugin", reference="C:\\Test\\example", connection_state="pending"))
        result = self.plan(data)
        self.assertEqual(result["route"], "AWAIT_CONNECTION")
        self.assertEqual(result["owner"], "host")
        self.assertTrue(all(step["owner"] == "host" for step in result["steps"]))
        self.assertNotIn("plugin_reference", result["handoff"])
        self.assertFalse(any("未声明 Plugin Management 可用" in text for text in result["limitations"]))

    def test_stale_future_or_invalid_observation_cannot_establish_readiness(self):
        for stamp in ((NOW - timedelta(days=2)).isoformat(), (NOW + timedelta(days=1)).isoformat(), "invalid", None, "2026-09-22T12:00:00"):
            data = context()
            data.update(intent="use", connected_fit="sufficient", selected_plugin=selected(observed_at=stamp))
            self.assertEqual(self.plan(data)["route"], "VERIFY_CONNECTION")

    def test_manifest_or_user_claim_does_not_establish_live_connection(self):
        for source in ("local_manifest", "user"):
            data = context()
            data.update(intent="use", connected_fit="sufficient", selected_plugin=selected(status_source=source))
            self.assertEqual(self.plan(data)["route"], "VERIFY_CONNECTION")

    def test_ready_connection_still_needs_task_fit(self):
        data = context()
        data.update(intent="use", connected_fit="unknown", selected_plugin=selected())
        self.assertEqual(self.plan(data)["route"], "CHECK_EXISTING_CAPABILITIES")

    def test_missing_manager_is_not_missing_target_service(self):
        data = context()
        data["plugin_management_available"] = False
        result = self.plan(data)
        self.assertEqual(result["owner"], "host")
        self.assertEqual(result["route"], "DISCOVER_MISSING_CAPABILITY")
        self.assertTrue(any("不能据此断言目标服务不存在" in text for text in result["limitations"]))

    def test_explicit_evaluation_not_hidden_by_native_preference(self):
        data = context()
        data.update(intent="evaluate", native_fit="sufficient")
        self.assertEqual(self.plan(data)["route"], "DESIGN_MATCHED_TRIAL")

    def test_different_or_unknown_data_access_cannot_be_quality_trial(self):
        for access in ("different", "unknown"):
            data = context()
            data.update(intent="evaluate", baseline_data_access=access)
            self.assertEqual(self.plan(data)["route"], "ALIGN_BASELINE_DATA")

    def test_access_enablement_separate_from_quality_gain(self):
        data = context()
        data.update(intent="evaluate", evaluation_goal="access", baseline_data_access="different")
        self.assertEqual(self.plan(data)["route"], "DESIGN_ACCESS_TRIAL")

    def test_permission_read_requires_exact_named_target(self):
        data = context()
        data.update(intent="manage", management={"action": "inspect_permissions", "explicit_request": True})
        self.assertEqual(self.plan(data)["route"], "CLARIFY_MANAGEMENT")
        data["selected_plugin"] = selected(reference="Google", display_name="Google")
        self.assertEqual(self.plan(data)["route"], "CLARIFY_MANAGEMENT")
        data["selected_plugin"] = selected()
        self.assertEqual(self.plan(data)["route"], "MANAGE_REQUEST")

    def test_no_permission_or_removal_authority_from_scores(self):
        data = context()
        for action in ("remove", "change_permissions"):
            data.update(intent="manage", selected_plugin=selected(), management={"action": action, "explicit_request": False})
            self.assertEqual(self.plan(data)["route"], "CLARIFY_MANAGEMENT")

    def test_requested_permission_change_still_only_handoff(self):
        data = context()
        data.update(intent="manage", selected_plugin=selected(),
                    management={"action": "change_permissions", "explicit_request": True, "permission_mode": "ask_before_writes"})
        result = self.plan(data)
        self.assertEqual(result["route"], "MANAGE_REQUEST")
        self.assertFalse(result["handoff"]["execute"])
        self.assertEqual(result["handoff"]["requested_action"], "change_permissions")
        self.assertEqual(result["handoff"]["requested_permission_mode"], "ask_before_writes")

    def test_unknown_permission_mode_needs_clarification(self):
        data = context()
        data.update(intent="manage", selected_plugin=selected(),
                    management={"action": "change_permissions", "explicit_request": True, "permission_mode": "more"})
        self.assertEqual(self.plan(data)["route"], "CLARIFY_MANAGEMENT")

    def test_local_code_plugins_never_route_to_chatgpt_account_management(self):
        data = context()
        data.update(intent="manage", selected_plugin=selected(kind="local_code_plugin", reference="C:\\Test\\example"),
                    management={"action": "remove", "explicit_request": True})
        result = self.plan(data)
        self.assertEqual(result["route"], "LOCAL_PLUGIN_MANAGEMENT")
        self.assertEqual(result["owner"], "host")
        self.assertNotIn("plugin_reference", result["handoff"])
        data["management"]["explicit_request"] = False
        self.assertEqual(self.plan(data)["route"], "CLARIFY_MANAGEMENT")

    def test_public_query_rejects_path_account_and_secret_shapes(self):
        for bad in ("C:\\Private\\patient", "C:/Private/patient", "/Users/alice/private-research.csv", "https://site.example/private", "name@example.com", "Bearer secret", "sk-secret"):
            data = context()
            data["task"]["capability"] = bad
            with self.assertRaises(ValidationError):
                self.plan(data)

    def test_malformed_states_rejected_not_coerced(self):
        data = context()
        data["selected_plugin"] = selected(installed="true")
        with self.assertRaises(ValidationError):
            self.plan(data)

    def test_plan_artifact_escapes_task_and_preserves_previous_result(self):
        data = context()
        data["task"]["summary"] = '<script>alert(1)</script> [click](https://bad.example)'
        with tempfile.TemporaryDirectory() as directory:
            paths = write_plan(self.plan(data), directory)
            markdown = Path(paths["md"]).read_text(encoding="utf-8")
            self.assertNotIn("<script>", markdown)
            self.assertIn("&lt;script&gt;", markdown)
            with self.assertRaises(ValidationError):
                write_plan(self.plan(data), directory)


if __name__ == "__main__":
    unittest.main()
