"""Build disposable marketplace artifacts from the canonical source tree."""
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
    if item["name"] != NAME or item["source"] != {"source": "local", "path": "./"}:
        raise ValueError("Source marketplace must reference the canonical repository root")
    if item["policy"] != {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}:
        raise ValueError("Unexpected marketplace policy")
    return value


def claude_catalog(source="./"):
    return {"name": MARKET, "owner": {"name": "Local developer"},
            "plugins": [{"name": NAME, "source": source,
                         "description": "Determine whether a plugin improves a specific task through paired comparisons, frozen plans, and recomputable results."}]}


def marketplace_inventory(root, payload):
    """Only the artifact catalog points into plugins/; Git catalogs use ./ ."""
    codex = catalog(root)
    codex['plugins'][0]['source']['path'] = f'./plugins/{NAME}'
    result = {f'plugins/{NAME}/{name}': data for name, data in payload.items()}
    result['.agents/plugins/marketplace.json'] = (json.dumps(codex, indent=2) + '\n').encode()
    result['.claude-plugin/marketplace.json'] = (json.dumps(claude_catalog(f'./plugins/{NAME}'), indent=2) + '\n').encode()
    version = json.loads(payload['plugin.json'])['version']
    result['INSTALL.zh-CN.md'] = (
        f'# Plugin Value Lab {version} — 安装 / Installation\n\n'
        '本文件由构建生成。 / This file is generated during packaging.\n\n'
        '解压完整压缩包，将包含 `.agents/plugins/marketplace.json` 和 '
        '`.claude-plugin/marketplace.json` 的市场根目录作为本地市场来源，'
        f'然后安装 `{NAME}@{MARKET}`。不要选择 ZIP 或内部插件子目录。\n\n'
        'Extract the complete archive. Add the extracted marketplace root containing both '
        'catalog files as a local marketplace, then install '
        f'`{NAME}@{MARKET}`. Select the marketplace directory, not the ZIP or nested plugin directory.\n\n'
        f'- [Operations and requirements](plugins/{NAME}/docs/OPERATIONS.md)\n'
        f'- [English methodology](plugins/{NAME}/docs/METHODOLOGY.md)\n'
        f'- [Current evidence and limitations](plugins/{NAME}/docs/EVIDENCE.md)\n\n'
        '构建成功不代表已发布或科学有效。 / A successful build does not establish publication or scientific validity.\n'
    ).encode('utf-8')
    return result


def sync(root=ROOT, check=False):
    root = Path(root).resolve()
    catalog(root)
    if json.loads((root / '.claude-plugin/marketplace.json').read_text(encoding='utf-8')) != claude_catalog():
        raise ValueError('Claude source catalog must reference the canonical repository root')
    payload = inventory(root)
    destination = root / 'build' / 'marketplace'
    if destination.resolve() != destination or not destination.resolve().is_relative_to(root):
        raise ValueError('Generated destination must be an ordinary directory inside the repository')
    # A clean checkout needs no generated tree for validation or installation.
    if check and not destination.exists():
        return payload
    expected = marketplace_inventory(root, payload)
    manifest = destination / 'BUILD.json'
    if manifest.resolve() != manifest:
        raise ValueError('Generated manifest must not be a symlink')
    prior = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    old_files = prior.get('files', {})
    if not isinstance(old_files, dict):
        raise ValueError('Invalid generated-file manifest')
    observed = {p.relative_to(destination).as_posix(): p for p in destination.rglob('*') if p.is_file() and p != manifest}
    if any(p.resolve() != p or not p.resolve().is_relative_to(destination) for p in observed.values()):
        raise ValueError('Generated member escapes build directory')
    unknown = set(observed) - set(old_files)
    if unknown:
        raise ValueError(f'Unmanaged build files; preserve/review them: {sorted(unknown)}')
    sums = {name: hashlib.sha256(data).hexdigest() for name, data in expected.items()}
    differences = [name for name, data in expected.items() if name not in observed or observed[name].read_bytes() != data]
    if check:
        if differences or set(observed) != set(expected) or old_files != sums:
            raise ValueError('Generated marketplace is stale; run --generate or --package')
        return payload
    # Only remove obsolete, manifest-owned bytes. Never delete a modified file.
    obsolete = set(observed) - set(expected)
    for name in obsolete:
        if hashlib.sha256(observed[name].read_bytes()).hexdigest() != old_files[name]:
            raise ValueError(f'Modified obsolete build file; preserve/review it: {name}')
    for name in obsolete:
        observed[name].unlink()
    for name, data in expected.items():
        path = destination / name
        if path.resolve() != path or not path.resolve().is_relative_to(destination):
            raise ValueError('Generated member escapes build directory')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest.write_text(json.dumps({'format': 'pvl-generated-marketplace-1', 'files': sums}, indent=2) + '\n', encoding='utf-8')
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
    payload = sync(check=not (args.generate or args.package))
    result = {"marketplace": MARKET, "plugin_files": len(payload), "source_catalogs_verified": True,
              "generated_tree": "build/marketplace" if (ROOT / 'build/marketplace').exists() else None, "published": False}
    if args.package:
        from validate_agent_plugin import validate
        validate(ROOT)
        version = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["version"]
        market_payload = marketplace_inventory(ROOT, payload)
        result["archives"] = [
            archive(ROOT / "dist" / f"{MARKET}-{version}.zip", MARKET, market_payload),
            archive(ROOT / "dist" / f"{NAME}-agent-plugins-{version}.zip", NAME, inventory(portable=True)),
        ]
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
