"""Synthetic phase-two acceptance. No model, external reviewer, message or publication."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import demo_suite, demo_records, freeze, load_json, write_json
from value_lab.hosts import prepare_matrix
from value_lab.registry import register_study
from value_lab.publication import build_public, verify_public
from value_lab.signatures import public_identity


def main():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    root = Path(parser.parse_args().output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    # Demonstration publisher key exists only in memory. No reviewer is invented.
    publisher = Ed25519PrivateKey.generate()
    trust = {"keys": [{**public_identity(publisher.public_key()), "identity": "SYNTHETIC DEMO PUBLISHER",
                       "organization": "Software acceptance fixture", "roles": ["publisher"], "revoked": False}]}
    write_json(root / "demo-trust.json", trust)
    template = demo_suite()
    template["conditions"].update(host_version="SYNTHETIC-HOST-VERSION", model_version="SIMULATED-NO-MODEL")
    for case in template["cases"]:
        case["split"] = "heldout"
    matrix = prepare_matrix(template, [{"host": "codex-cli", "host_version": "SYNTHETIC-HOST-VERSION"},
                                      {"host": "claude-code", "host_version": "SYNTHETIC-HOST-VERSION"}], root / "matrix")
    registry = root / "registry"
    for i, host in enumerate(("codex-cli", "claude-code", "codex-cli")):
        study = root / f"study-{i+1}"
        study.mkdir()
        suite = load_json(root / "matrix" / host / "suite.json")
        suite["id"] = f"SYNTHETIC-host-study-{i+1}"
        if i == 2:
            suite["plugin"]["version"] = "0.0.0-SYNTHETIC-next"
        write_json(study / "suite.json", suite)
        freeze(suite, study / "protocol.lock.json")
        records = demo_records(suite)
        for record in records:
            record["session_id"] = f"fixture-{i}-" + record["session_id"]
            if i == 2 and record["arm"] == "with":
                record["output"] = "Synthetic failed result"
        (study / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        meta = {"observed_at": f"2026-09-{i+1:02d}T00:00:00Z",
                "authors": [{"id": "SYNTHETIC-NO-PERSON", "organization": "Software test fixture"}],
                "plugin_sha256": ("a" if i < 2 else "b")*64,
                "limitations": "Manufactured teaching records; no model, human reviewer or scientific data"}
        register_study(study, meta, registry)
        if i == 1:
            first = build_public(registry, root / "previous-site", publisher, trust)
    final = build_public(registry, root / "site", publisher, trust, previous=root / "previous-site")
    checked = verify_public(root / "site", trust, final["snapshot_sha256"])
    assert final["positive_cards"] == 0 and final["cards"] == 3
    assert final["previous_snapshot_sha256"] == first["snapshot_sha256"]
    receipt = {"evidence_type": "synthetic", "model_calls": 0, "actual_reviews": 0, "external_messages": 0,
               "published": False, "version_changed": False, "matrix": matrix, "public_snapshot": checked,
               "private_key_written": False, "preview": str(root / "site/index.html")}
    write_json(root / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
