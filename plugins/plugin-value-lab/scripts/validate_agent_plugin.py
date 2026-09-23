"""Offline official-schema and package checks for this plugin; not client certification."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas/agent-plugins/1.0.0"


def validate(root):
    from jsonschema import Draft202012Validator
    root = Path(root).resolve()
    source = json.loads((SCHEMAS / "SOURCES.json").read_text(encoding="utf-8"))
    for entry in source["schemas"]:
        data = (SCHEMAS / entry["url"].rsplit("/", 1)[1]).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("Vendored schema checksum mismatch")
    objects = {}
    for name in ("plugin", "mcp"):
        path = root / (name + ".json")
        if not path.resolve().is_relative_to(root):
            raise ValueError("Manifest escapes plugin root")
        objects[name] = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads((SCHEMAS / (name + ".schema.json")).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(objects[name])
    manifest, mcp = objects["plugin"], objects["mcp"]
    package_version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    python_version = re.sub(r"-alpha\.", "a", manifest["version"])
    python_version = re.sub(r"-beta\.", "b", python_version)
    python_version = re.sub(r"-rc\.", "rc", python_version)
    runtime = (root / "value_lab/__init__.py").read_text(encoding="utf-8")
    if package_version != python_version or not re.search(r'^__version__ = "' + re.escape(manifest["version"]) + r'"$', runtime, re.M):
        raise ValueError("Python package/runtime and plugin version drift")
    skills = []
    for directory in sorted((root / "skills").iterdir()):
        path = directory / "SKILL.md"
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(root):
            raise ValueError("Skill escapes plugin root")
        text = path.read_text(encoding="utf-8")
        front = text.split("---", 2)
        if not text.startswith("---\n") or len(front) != 3:
            raise ValueError(f"Missing skill frontmatter: {directory.name}")
        if not re.search(r"^name: " + re.escape(directory.name) + r"\s*$", front[1], re.M):
            raise ValueError("Skill directory and name differ")
        if not re.search(r"^description: .+", front[1], re.M):
            raise ValueError("Skill description missing")
        skills.append(directory.name)
    if set(skills) != {"assess-value", "use-plugin-well"}:
        raise ValueError("Expected only evaluation and plugin-use skills in default discovery")
    for server in mcp["mcpServers"].values():
        if server["type"] != "stdio":
            raise ValueError("This release expects local stdio only")
        if server["command"] != "python" or server.get("args") != ["-B", "${PLUGIN_ROOT}/scripts/value_lab.py", "serve"]:
            raise ValueError("MCP must launch the bundled source via host Python")
        if server.get("cwd") != "./":
            raise ValueError("Working directory must stay at plugin root")
        if any(key.upper() in ("PLUGIN_ROOT", "PLUGIN_DATA") for key in server.get("env", {})):
            raise ValueError("Reserved environment key")
        launcher = root / "scripts/value_lab.py"
        if not launcher.is_file() or not launcher.resolve().is_relative_to(root):
            raise ValueError("Bundled launcher missing or outside plugin root")
    # Validate every bundled path, including links not seen during fixed discovery.
    for directory in ("skills", "extensions", "scripts", "value_lab", "com.openai"):
        for path in (root / directory).rglob("*"):
            if not path.resolve().is_relative_to(root):
                raise ValueError(f"Path escapes plugin root: {path}")
    for legacy in (".codex-plugin/plugin.json", ".claude-plugin/plugin.json"):
        path = root / legacy
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            if any(old[key] != manifest[key] for key in ("name", "version")):
                raise ValueError("Compatibility manifest identity/version drift")
    return {"valid": True, "specification": "Agent Plugins 1.0.0", "name": manifest["name"],
            "version": manifest["version"], "skills": skills, "mcp_servers": list(mcp["mcpServers"]),
            "schemas_loaded_offline": True, "client_certification": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.root), indent=2))
    except Exception as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
