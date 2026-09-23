"""Generate/check a byte-identical marketplace copy and build two offline archives."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from distribution import ROOT, inventory

NAME = "plugin-value-lab"
MARKET = "plugin-value-lab-marketplace"


def catalog(root=ROOT):
    value = json.loads((root / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
    if value["name"] != MARKET or len(value["plugins"]) != 1:
        raise ValueError("Unexpected marketplace identity or membership")
    item = value["plugins"][0]
    if item["name"] != NAME or item["source"] != {"source": "local", "path": f"./plugins/{NAME}"}:
        raise ValueError("Marketplace must reference its contained plugin")
    if item["policy"] != {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}:
        raise ValueError("Unexpected marketplace policy")
    return value


def claude_catalog():
    return {"name": MARKET, "owner": {"name": "Local developer"},
            "plugins": [{"name": NAME, "source": f"./plugins/{NAME}",
                         "description": "Measure and register the marginal value of scientific agent plugins under matched conditions."}]}


def sync(root=ROOT, check=False):
    root = Path(root).resolve()
    catalog(root)
    payload = inventory(root)
    destination = root / "plugins" / NAME
    if not destination.resolve().is_relative_to(root):
        raise ValueError("Generated plugin must remain inside the repository")
    observed = {p.relative_to(destination).as_posix(): p for p in destination.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo")}
    extras = set(observed) - set(payload)
    if extras:
        raise ValueError(f"Unexpected files in generated plugin; preserve/review them: {sorted(extras)}")
    differences = [name for name, data in payload.items() if name not in observed or observed[name].read_bytes() != data]
    claude_file = root / ".claude-plugin/marketplace.json"
    claude_data = (json.dumps(claude_catalog(), indent=2) + "\n").encode()
    if check:
        if differences or not claude_file.is_file() or claude_file.read_bytes() != claude_data:
            raise ValueError(f"Generated marketplace is stale: {differences}; run --generate")
    else:
        for name in differences:
            path = destination / name
            if not path.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Generated destination escapes plugin")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload[name])
        claude_file.parent.mkdir(parents=True, exist_ok=True)
        claude_file.write_bytes(claude_data)
    return payload


def archive(path, prefix, payload):
    sums = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        for name, data in sorted(payload.items()):
            out.writestr(prefix + "/" + name, data)
        out.writestr(prefix + "/SHA256SUMS.json", json.dumps(sums, indent=2) + "\n")
    with zipfile.ZipFile(path) as zipped:
        assert zipped.testzip() is None
        for name, expected in sums.items():
            assert hashlib.sha256(zipped.read(prefix + "/" + name)).hexdigest() == expected
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "files": len(payload), "member_hashes_verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--package", action="store_true")
    args = parser.parse_args()
    if not (args.generate or args.check or args.package):
        parser.error("Choose --generate, --check, or --package")
    payload = sync(check=not args.generate)
    result = {"marketplace": MARKET, "plugin_files": len(payload), "mirror_verified": True, "published": False}
    if args.package:
        from validate_agent_plugin import validate
        validate(ROOT)
        version = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["version"]
        market_payload = {f"plugins/{NAME}/{name}": data for name, data in payload.items()}
        for name in (".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json"):
            market_payload[name] = (ROOT / name).read_bytes()
        market_payload["INSTALL.zh-CN.md"] = (ROOT / "docs/INSTALL.zh-CN.md").read_bytes()
        result["archives"] = [
            archive(ROOT / "dist" / f"{MARKET}-{version}.zip", MARKET, market_payload),
            archive(ROOT / "dist" / f"{NAME}-agent-plugins-{version}.zip", NAME, inventory(portable=True)),
        ]
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
