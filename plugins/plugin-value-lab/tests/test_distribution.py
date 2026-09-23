import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from distribution import inventory
from validate_agent_plugin import validate


@unittest.skipUnless(importlib.util.find_spec("jsonschema"), "Developer schema dependency not installed")
class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "portable plugin"
        for name, data in inventory(portable=True).items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def edit(self, name, transform):
        path = self.root / name
        data = json.loads(path.read_text(encoding="utf-8"))
        transform(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_official_schemas_and_fixed_discovery(self):
        result = validate(self.root)
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["skills"]), 2)
        self.assertFalse((self.root / ".codex-plugin").exists())
        self.assertFalse((self.root / ".mcp.json").exists())

    def test_unknown_top_level_not_promoted_to_standard(self):
        self.edit("plugin.json", lambda data: data.update(skills="./skills"))
        with self.assertRaises(Exception):
            validate(self.root)

    def test_wrong_schema_version_rejected(self):
        self.edit("mcp.json", lambda data: data.update({"$schema": "https://agent-plugins.org/schemas/2.0.0/mcp.schema.json"}))
        with self.assertRaises(Exception):
            validate(self.root)

    def test_reserved_environment_is_rejected(self):
        self.edit("mcp.json", lambda data: data["mcpServers"]["plugin-value-lab"]["env"].update(PLUGIN_ROOT="private"))
        with self.assertRaises(Exception):
            validate(self.root)

    def test_missing_bundled_launcher_rejected(self):
        (self.root / "scripts/value_lab.py").unlink()
        with self.assertRaisesRegex(ValueError, "launcher"):
            validate(self.root)

    def test_shell_command_or_parent_cwd_rejected(self):
        self.edit("mcp.json", lambda data: data["mcpServers"]["plugin-value-lab"].update(command="python script.py", cwd="../"))
        with self.assertRaises(Exception):
            validate(self.root)

    def test_private_work_and_nested_mirror_are_never_packaged(self):
        paths = inventory()
        self.assertTrue(all(name.split("/")[0] not in ("work", "dist", "plugins", "build") for name in paths))
        self.assertFalse(any("__pycache__" in name for name in paths))

    def test_python_package_version_drift_rejected(self):
        path = self.root / "pyproject.toml"
        import tomllib
        current = tomllib.loads(path.read_text())["project"]["version"]
        path.write_text(path.read_text().replace('version = "' + current + '"', 'version = "99.0.0"'), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "version drift"):
            validate(self.root)

    def test_runtime_version_drift_rejected(self):
        (self.root / "value_lab/__init__.py").write_text('__version__ = "99.0.0"\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "version drift"):
            validate(self.root)

    @unittest.skipUnless((ROOT / ".codex-plugin/plugin.json").exists(), "Legacy overlays are omitted from the portable archive")
    def test_claude_and_codex_use_their_own_root_variable(self):
        claude = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        codex = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))["mcpServers"]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", str(claude))
        self.assertIn("${PLUGIN_ROOT}", str(codex))
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", str(codex))


@unittest.skipUnless(importlib.util.find_spec("mcp"), "MCP SDK not installed")
class RelocatedMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_portable_manifest_launches_from_relocated_unicode_cache(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "缓存 plugin with spaces"
            for name, data in inventory(portable=True).items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            config = json.loads((root / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["plugin-value-lab"]
            params = StdioServerParameters(command=shutil.which(config["command"]) or config["command"],
                args=[arg.replace("${PLUGIN_ROOT}", str(root)) for arg in config["args"]],
                cwd=str(root), env=config["env"])
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self.assertEqual(len(listed.tools), 6)
                    response = await session.call_tool("example_value_suite", {})
                    self.assertFalse(response.isError)
                    self.assertEqual(json.loads(response.content[0].text)["real_observations"], 0)
            self.assertFalse(any(root.rglob("__pycache__")))


if __name__ == "__main__":
    unittest.main()
