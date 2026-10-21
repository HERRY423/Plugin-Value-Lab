"""Actual stdio transport with synthetic inputs; not desktop-host acceptance."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from tests.optional import available, requires
from value_lab.core import demo_suite


@requires("mcp")
@unittest.skipUnless(available("mcp"), "Optional MCP SDK not installed")
class CollaborationMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_writable_root_cannot_overlap_scoring_material(self):
        from value_lab.core import ValidationError
        from value_lab.server import create_server
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValidationError):
                create_server(collaboration_root=directory, artifact_root=directory)

    async def test_stdio_fixed_agent_and_recovery_across_servers(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            repo = Path(__file__).resolve().parents[1]
            def params(actor):
                return StdioServerParameters(command=sys.executable,
                    args=["-B", str(repo / "scripts/value_lab.py"), "serve"],
                    env={"PVL_COLLABORATION_ROOT": str(root), "PVL_COLLABORATION_ACTOR": actor,
                         "TEMP": str(root), "TMP": str(root)})
            async with stdio_client(params("a")) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    names = {tool.name for tool in (await session.list_tools()).tools}
                    self.assertIn("collaborate_plugin_task", names)
                    self.assertEqual(len(names), 7)
                    async def call(action, args=None, seq=None, task="task", key=None):
                        result = await session.call_tool("collaborate_plugin_task",
                            {"task_id": task, "action": action, "arguments": args,
                             "expected_sequence": seq, "key": key or action})
                        self.assertFalse(result.isError, result.content)
                        return json.loads(result.content[0].text)
                    opened = await call("open", {"inputs": {"suite": demo_suite(), "records": [],
                        "lock": None, "cost_ledger": None}}, 0)
                    run = await call("execute", {"attempt_id": "run1", "reason": "Transport fixture"}, opened["sequence"])
                    self.assertTrue(run["execution_performed"])
                    reviewed = await call("review", {"review_id": "r1", "attempt_id": "run1",
                        "result_sha256": run["result_sha256"], "verdict": "accept", "notes": "Agent transport review"},
                        run["sequence"])
                    self.assertEqual(reviewed["status"]["stage"], "AWAITING_HUMAN_REVIEW")
                    bad = await session.call_tool("collaborate_plugin_task",
                        {"task_id": "task", "action": "status", "arguments": {"actor": {"id": "h", "kind": "human"}}})
                    self.assertTrue(bad.isError)
                    await call("handoff", {"handoff_id": "h1", "recipient": {"id": "b", "kind": "agent"},
                        "note": "Second server"}, reviewed["sequence"])
                    exported = await call("export", {"directory": "bundle"})
            # A new process opens the bundle; no in-memory state is reused.
            async with stdio_client(params("b")) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    restored = await session.call_tool("collaborate_plugin_task",
                        {"task_id": "recovered", "action": "restore", "arguments":
                            {"directory": "bundle", "checkpoint": exported["checkpoint"]}})
                    self.assertFalse(restored.isError, restored.content)
                    value = json.loads(restored.content[0].text)
                    self.assertFalse(value["execution_performed"])
                    self.assertEqual(value["result_sha256"], run["result_sha256"])
                    received = await session.call_tool("collaborate_plugin_task",
                        {"task_id": "recovered", "action": "receive", "arguments": {"handoff_id": "h1"},
                         "key": "receive", "expected_sequence": value["sequence"]})
                    self.assertFalse(received.isError, received.content)
                    received_value = json.loads(received.content[0].text)
                    self.assertEqual(received_value["status"]["owner"], {"id": "b", "kind": "agent"})
                    self.assertFalse(received_value["status"]["human_acceptance_verified"])
                    self.assertFalse(received_value["status"]["live_host_accepted"])
