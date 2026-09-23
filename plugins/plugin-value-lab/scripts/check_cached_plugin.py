"""Check the runtime in an actual local install receipt, without executing models."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


async def check(receipt):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    installed = json.loads(Path(receipt).read_text(encoding="utf-8"))
    root = Path(installed["installedPath"]).resolve()
    manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == installed["name"] == "plugin-value-lab"
    assert manifest["version"] == installed["version"]
    skills = sorted(path.parent.name for path in (root / "skills").glob("*/SKILL.md"))
    assert skills == ["assess-value", "research-directions", "use-plugin-well"]
    config = json.loads((root / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["plugin-value-lab"]
    command = shutil.which(config["command"]) or config["command"]
    args = [arg.replace("${PLUGIN_ROOT}", str(root)) for arg in config["args"]]
    version = subprocess.run([command, "-B", str(root / "scripts/value_lab.py"), "--version"],
                             cwd=root, capture_output=True, text=True, encoding="utf-8", check=True)
    assert version.stdout.strip() == manifest["version"]
    parameters = StdioServerParameters(command=command, args=args, cwd=str(root), env=config["env"])
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(tool.name for tool in tools.tools)
            assert len(names) == 7
            example = await session.call_tool("example_value_suite", {})
            assert not example.isError
            assert json.loads(example.content[0].text)["real_observations"] == 0
            planned = await session.call_tool("plan_plugin_use", {"context": {
                "schema_version": 1, "intent": "choose", "task": {"summary": "Installation smoke test", "capability": "text summary"},
                "native_fit": "sufficient", "plugin_management_available": False}})
            assert not planned.isError
            assert json.loads(planned.content[0].text)["route"] == "USE_NATIVE"
            example_context = await session.call_tool("research_direction_advisor", {"action": "example"})
            assert not example_context.isError
            diagnosis = await session.call_tool("research_direction_advisor", {"action": "diagnose", "context": json.loads(example_context.content[0].text)})
            assert not diagnosis.isError
            assert json.loads(diagnosis.content[0].text)["status"] == "RESEARCH_DIAGNOSIS_ONLY"
    return {"installed_version": manifest["version"], "cached_launcher": str(root / "scripts/value_lab.py"),
            "manifest_sha256": hashlib.sha256((root / "plugin.json").read_bytes()).hexdigest(),
            "tools": names, "skill_files": skills, "mcp_initialize_list_and_calls": "passed", "cached_cli_version": "passed",
            "models_executed": 0, "desktop_new_conversation_verified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("install_receipt", help="JSON stdout from codex plugin add --json")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(check(args.install_receipt)), indent=2))
