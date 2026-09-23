"""Explicit distribution inventory; excludes local studies, caches and account data."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = (".codex-plugin", ".claude-plugin", "com.openai", "value_lab", "scripts", "skills", "extensions", "docs", "examples", "evals", "tests", "schemas")
FILES = ("plugin.json", "mcp.json", ".mcp.json", ".gitignore", "README.md", "README.zh-CN.md", "LICENSE", "CHANGELOG.md", "CONTRACT.md", "pyproject.toml", "requirements-mcp.txt", "VERIFICATION.json")


def inventory(root=ROOT, portable=False):
    root = Path(root).resolve()
    paths = [root / name for name in FILES if (root / name).is_file()]
    for directory in DIRECTORIES:
        paths.extend(path for path in (root / directory).rglob("*") if path.is_file())
    result = {}
    for path in sorted(paths):
        relative = path.relative_to(root)
        if any(part in ("__pycache__", "results") for part in relative.parts) or path.suffix in (".pyc", ".pyo"):
            continue
        if relative.name == "marketplace.json":
            continue
        if portable and relative.parts[0] in (".codex-plugin", ".claude-plugin", ".mcp.json", "com.openai"):
            continue
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"Package path escapes root: {relative}")
        result[relative.as_posix()] = path.read_bytes()
    return result
