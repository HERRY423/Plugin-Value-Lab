import importlib.util
import sys
import unittest
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Optional MCP SDK not installed")
class MCPSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_initialize_list_and_call(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        root = Path(__file__).resolve().parents[1]
        params = StdioServerParameters(command=sys.executable, args=[str(root / "scripts" / "value_lab.py"), "serve"])
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                initialized = await session.initialize()
                self.assertEqual(initialized.serverInfo.name, "Plugin Value Lab")
                available = await session.list_tools()
                self.assertEqual({t.name for t in available.tools}, {"validate_value_suite", "evaluate_plugin_value",
                                                                   "inspect_claude_eval", "example_value_suite",
                                                                   "plan_plugin_use", "build_plugin_usage_card", "research_direction_advisor"})
                result = await session.call_tool("example_value_suite", {})
                self.assertFalse(result.isError)
                import json
                data = json.loads(result.content[0].text)
                self.assertEqual(data["real_observations"], 0)
                checked = await session.call_tool("validate_value_suite", {"suite": data["suite"]})
                self.assertFalse(checked.isError)
                assessed = await session.call_tool("evaluate_plugin_value", {"suite": data["suite"], "records": []})
                self.assertFalse(assessed.isError)
                self.assertEqual(json.loads(assessed.content[0].text)["verdict"], "SIMULATION_ONLY")
                planned = await session.call_tool("plan_plugin_use", {"context": {
                    "schema_version": 1, "intent": "choose", "task": {"summary": "Summarize a public page", "capability": "web reading"},
                    "native_fit": "sufficient", "connected_fit": "unknown", "plugin_management_available": False}})
                self.assertFalse(planned.isError)
                self.assertEqual(json.loads(planned.content[0].text)["route"], "USE_NATIVE")
                card = await session.call_tool("build_plugin_usage_card", {"suite": data["suite"], "records": []})
                self.assertFalse(card.isError)
                card_data = json.loads(card.content[0].text)
                self.assertEqual(card_data["use_when"], [])
                bad = await session.call_tool("validate_value_suite", {"suite": {"schema_version": 2}})
                self.assertTrue(bad.isError)
                example = await session.call_tool("research_direction_advisor", {"action": "example"})
                self.assertFalse(example.isError)
                research_context = json.loads(example.content[0].text)
                diagnosed = await session.call_tool("research_direction_advisor", {"action": "diagnose", "context": research_context})
                self.assertFalse(diagnosed.isError)
                self.assertEqual(json.loads(diagnosed.content[0].text)["status"], "RESEARCH_DIAGNOSIS_ONLY")
                compared = await session.call_tool("research_direction_advisor", {"action": "compare", "before": research_context, "after": research_context})
                self.assertFalse(compared.isError)
                invalid = await session.call_tool("research_direction_advisor", {"action": "example", "context": research_context})
                self.assertTrue(invalid.isError)


if __name__ == "__main__":
    unittest.main()
