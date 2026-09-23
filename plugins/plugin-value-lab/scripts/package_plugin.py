"""Build a portable source plugin archive with file hashes; never publishes it."""
import hashlib
import json
from pathlib import Path
import zipfile
from distribution import inventory


ROOT = Path(__file__).resolve().parents[1]
INCLUDE_DIRS = (".codex-plugin", ".claude-plugin", "value_lab", "scripts", "skills", "docs", "examples", "evals", "tests")
INCLUDE_FILES = (".mcp.json", ".gitignore", "README.md", "CHANGELOG.md", "CONTRACT.md", "pyproject.toml", "VERIFICATION.json")


def main():
    files = [ROOT / name for name in inventory()]
    files.sort(key=lambda p: p.relative_to(ROOT).as_posix())
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    version = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8-sig"))["version"]
    out = ROOT / "dist" / f"plugin-value-lab-{version}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, "plugin-value-lab/" + path.relative_to(ROOT).as_posix())
        archive.writestr("plugin-value-lab/SHA256SUMS.json", json.dumps(hashes, indent=2) + "\n")
    with zipfile.ZipFile(out) as archive:
        assert archive.testzip() is None
        for name, expected in hashes.items():
            assert hashlib.sha256(archive.read("plugin-value-lab/" + name)).hexdigest() == expected
    print(json.dumps({"archive": str(out), "files": len(files), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                      "member_hashes_verified": True, "published": False}, indent=2))


if __name__ == "__main__":
    main()
