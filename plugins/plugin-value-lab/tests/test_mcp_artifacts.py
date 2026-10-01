"""Real stdio acceptance for the host-authorized scientific file handoff."""
from copy import deepcopy
from contextlib import asynccontextmanager
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from value_lab.artifacts import grade_artifact, read_only_verification, sha
from value_lab.core import ValidationError, demo_records, demo_suite, suite_digest, write_json
from value_lab.server import _configured_root, _material_root, create_server


class MaterialBoundaryTests(unittest.TestCase):
    def test_unconfigured_roots_cannot_be_authorized_by_tool_arguments(self):
        self.assertIsNone(_material_root(None, None, "artifact_root"))
        with self.assertRaisesRegex(ValidationError, "not authorized"):
            _material_root(None, str(Path.cwd()), "artifact_root")
        with self.assertRaises(ValidationError):
            _configured_root(".")

    def test_paths_links_and_replaced_roots_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            child = root / "child"
            child.mkdir()
            for selection in ("child", str(child)):
                self.assertEqual(_material_root(root, selection, "artifact_root"), child)
            for selection in ("../outside", "child/../child", str(root.parent), "absent", ""):
                with self.subTest(selection=selection), self.assertRaises(ValidationError):
                    _material_root(root, selection, "artifact_root")
            original = Path.is_symlink
            with patch.object(Path, "is_symlink", lambda p: p == child or original(p)):
                with self.assertRaisesRegex(ValidationError, "Linked"):
                    _material_root(root, "child", "artifact_root")
            with patch.object(Path, "resolve", return_value=root.parent):
                with self.assertRaisesRegex(ValidationError, "changed"):
                    _material_root(root, None, "artifact_root")

    def test_read_only_policy_blocks_both_execution_types_and_restores_local_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "artifact.json").write_text("{}", encoding="utf-8")
            program = root / "check.py"
            program.write_text('print(\'{"passed":true,"rationale":"local fixture"}\')', encoding="utf-8")
            rule = {"id": "check", "type": "executable", "artifact": "result",
                    "verifier": {"path": program.name, "sha256": sha(program), "timeout_seconds": 5}}
            record = {"artifacts": {"result": {"path": "artifact.json", "sha256": sha(root / "artifact.json")}}}
            with read_only_verification(), patch("subprocess.Popen", side_effect=AssertionError("Must not execute")):
                for kind in ("executable", "exec"):
                    passed, reason, _ = grade_artifact({**rule, "type": kind}, record, root, root)
                    self.assertIsNone(passed)
                    self.assertIn("read-only", reason)
            self.assertTrue(grade_artifact(rule, record, root, root)[0])


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Optional MCP SDK not installed")
class MCPArtifactTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.artifacts = self.root / "artifacts"
        self.scorers = self.root / "scorers"
        self.artifacts.mkdir()
        self.scorers.mkdir()
        self.output = self.artifacts / "result.csv"
        self.output.write_text("gene,p,q,effect\na,0.01,0.03,2\nb,0.04,0.06,-1\nc,0.2,0.2,0\n", encoding="utf-8")
        self.truth = self.scorers / "family.json"
        write_json(self.truth, {"ids": ["a", "b", "c"]})
        self.rule = {"id": "check", "type": "artifact", "artifact": "result", "dimension": "outcome",
                     "weight": 1, "critical": True, "verifier": {"kind": "de_table", "id_column": "gene",
                     "p_column": "p", "q_column": "q", "effect_column": "effect", "min_rows": 3,
                     "bh_tolerance": 1e-9, "testing_family": {"path": "family.json", "sha256": sha(self.truth)}}}

    def inputs(self, rule=None):
        suite = demo_suite()
        suite["cases"] = suite["cases"][:1]
        suite["cases"][0]["graders"] = [deepcopy(rule or self.rule)]
        records = demo_records(suite)
        for record in records:
            record["artifacts"] = {"result": {"path": self.output.name, "sha256": sha(self.output)}}
            record["output"] = "Everything passed (untrusted model assertion)"
        return {"suite": suite, "records": records}

    @asynccontextmanager
    async def start(self, artifacts=True, scorers=True):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        env = {**os.environ, "PYTHONUTF8": "1"}
        for key in ("PVL_ARTIFACT_ROOT", "PVL_VERIFIER_ROOT"):
            env.pop(key, None)
        if artifacts:
            env["PVL_ARTIFACT_ROOT"] = str(self.artifacts)
        if scorers:
            env["PVL_VERIFIER_ROOT"] = str(self.scorers)
        params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).resolve().parents[1] / "scripts/value_lab.py"), "serve"], env=env)
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                yield session

    async def call(self, session, tool, inputs):
        result = await session.call_tool(tool, inputs)
        self.assertFalse(result.isError, result)
        value = json.loads(result.content[0].text)
        if result.structuredContent is not None:
            self.assertEqual(result.structuredContent, value)
        return value

    @staticmethod
    def grades(value, tool):
        if tool == "build_plugin_usage_card":
            return [g for g in value["source"]["verification_receipts"] if g["grade_id"] == "check"]
        return value["cases"][0]["runs"][0]["grades"]

    async def test_both_tools_recompute_files_and_return_bound_receipts(self):
        async with self.start() as session:
            available = {t.name: t.inputSchema for t in (await session.list_tools()).tools}
            for tool in ("evaluate_plugin_value", "build_plugin_usage_card"):
                self.assertIn("artifact_root", available[tool]["properties"])
                self.assertIn("verifier_root", available[tool]["properties"])
                inputs = self.inputs()
                inputs.update(artifact_root=str(self.artifacts), verifier_root=str(self.scorers))
                value = await self.call(session, tool, inputs)
                grade = self.grades(value, tool)[0]
                self.assertTrue(grade["passed"])
                self.assertEqual(grade["verification"]["artifact_sha256"], sha(self.output))
                self.assertEqual(grade["verification"]["rule_sha256"], suite_digest(self.rule))
                self.assertEqual(grade["verification"]["testing_family_sha256"], sha(self.truth))
                self.assertEqual(value["verdict"], "SIMULATION_ONLY")
                self.assertNotIn(str(self.scorers), json.dumps(value))
                provenance = value["provenance"] if tool == "evaluate_plugin_value" else value["source"]["provenance"]
                self.assertEqual(provenance["suite_sha256"], suite_digest(inputs["suite"]))
            # A second call reads bytes again, not an earlier positive receipt.
            self.output.write_text("gene,p,q,effect\na,0.01,0.01,2\nb,0.04,0.04,-1\nc,0.2,0.2,0\n", encoding="utf-8")
            for tool in ("evaluate_plugin_value", "build_plugin_usage_card"):
                stale = await self.call(session, tool, inputs)
                self.assertIsNone(self.grades(stale, tool)[0]["passed"])
                invalid = await self.call(session, tool, self.inputs())
                self.assertFalse(self.grades(invalid, tool)[0]["passed"])

    async def test_missing_tampered_and_escaping_materials_never_pass(self):
        async with self.start() as session:
            inputs = self.inputs()
            for tool in ("evaluate_plugin_value", "build_plugin_usage_card"):
                for root in (str(self.root), "../scorers"):
                    result = await session.call_tool(tool, {**inputs, "artifact_root": root})
                    self.assertTrue(result.isError)
                escaped = deepcopy(inputs)
                for record in escaped["records"]:
                    record["artifacts"]["result"]["path"] = "../scorers/family.json"
                value = await self.call(session, tool, escaped)
                self.assertIsNot(self.grades(value, tool)[0]["passed"], True)
            write_json(self.truth, {"ids": ["changed"]})
            for tool in ("evaluate_plugin_value", "build_plugin_usage_card"):
                value = await self.call(session, tool, inputs)
                self.assertIsNone(self.grades(value, tool)[0]["passed"])
            self.output.unlink()
            for tool in ("evaluate_plugin_value", "build_plugin_usage_card"):
                value = await self.call(session, tool, inputs)
                self.assertIsNone(self.grades(value, tool)[0]["passed"])

    async def test_unconfigured_legacy_and_artifact_only_hosts(self):
        for artifacts in (False, True):
            async with self.start(artifacts=artifacts, scorers=False) as session:
                for tool in ("evaluate_plugin_value", "build_plugin_usage_card"):
                    inputs = self.inputs()
                    value = await self.call(session, tool, inputs)
                    self.assertIsNone(self.grades(value, tool)[0]["passed"])
                    result = await session.call_tool(tool, {**inputs, "verifier_root": str(self.scorers)})
                    self.assertTrue(result.isError)
                    if not artifacts:
                        result = await session.call_tool(tool, {**inputs, "artifact_root": str(self.artifacts)})
                        self.assertTrue(result.isError)

    async def test_mcp_never_runs_supplied_verifier_program(self):
        async with self.start() as session:
            marker = self.scorers / "MUST_NOT_EXIST"
            program = self.scorers / "verify.py"
            program.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8")
            rule = {**self.rule, "type": "executable", "verifier": {"path": program.name, "sha256": sha(program), "timeout_seconds": 5}}
            for tool in ("evaluate_plugin_value", "build_plugin_usage_card"):
                value = await self.call(session, tool, self.inputs(rule))
                grade = self.grades(value, tool)[0]
                self.assertIsNone(grade["passed"])
                self.assertIn("read-only", grade["rationale"])
            self.assertFalse(marker.exists())

    async def test_private_scenario_receipts_and_nested_execution_denial(self):
        async with self.start() as session:
            case_id = demo_suite()["cases"][0]["id"]
            private = {"type": "ScorerOnlyGroundTruth", "case_id": case_id, "evidence_type": "synthetic",
                       "nonce": "a" * 64, "rationale": "Manufactured transport fixture",
                       "graders": [{k: self.rule[k] for k in ("id", "type", "artifact", "verifier")}]}
            path = self.scorers / "private.json"
            write_json(path, private)
            rule = {**self.rule, "type": "scenario", "verifier": {
                "path": path.name, "sha256": sha(path), "case_id": case_id, "evidence_type": "synthetic"}}
            rule.pop("artifact")
            for tool in ("evaluate_plugin_value", "build_plugin_usage_card"):
                value = await self.call(session, tool, self.inputs(rule))
                grade = self.grades(value, tool)[0]
                self.assertTrue(grade["passed"])
                self.assertEqual(grade["verification"]["grades"][0]["verification"]["artifact_sha256"], sha(self.output))
            # The exec grader normally launches a container; nested use must also stay unknown.
            private["graders"] = [{"id": "exec-child", "type": "exec", "artifact": "result", "verifier": {
                "program": {"path": "never.py", "sha256": "b" * 64},
                "image": "python@sha256:" + "1" * 64, "timeout_seconds": 1}}]
            write_json(path, private)
            rule["verifier"]["sha256"] = sha(path)
            for tool in ("evaluate_plugin_value", "build_plugin_usage_card"):
                value = await self.call(session, tool, self.inputs(rule))
                grade = self.grades(value, tool)[0]
                self.assertIsNone(grade["passed"])
                self.assertIn("read-only", grade["verification"]["grades"][0]["rationale"])

    def test_scorer_root_cannot_be_exposed_as_artifact_subdirectory(self):
        with self.assertRaisesRegex(ValidationError, "non-overlapping"):
            create_server(artifact_root=self.root, verifier_root=self.scorers)


if __name__ == "__main__":
    unittest.main()
