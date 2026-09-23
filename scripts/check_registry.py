"""Offline synthetic registry acceptance and preview; no model calls or reviewers."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import demo_suite, demo_records, freeze, write_json
from value_lab.registry import register_study, export_review_packet, verify_submission, replay_bundle, write_view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    study = root / "study"
    study.mkdir()
    suite = demo_suite()
    suite["id"] = "synthetic-evidence-revision-demo"
    write_json(study / "suite.json", suite)
    freeze(suite, study / "protocol.lock.json")
    records = demo_records(suite)

    def write_runs():
        (study / "runs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")

    original = records[0]["cost"]["model_usd"]
    records[0]["cost"]["model_usd"] = None
    write_runs()
    metadata = {"observed_at": "2026-09-23T00:00:00Z",
        "authors": [{"id": "Synthetic fixture author", "organization": "Synthetic fixture only"}],
        "plugin_sha256": "a" * 64,
        "limitations": "Synthetic software demonstration; no real runs, external reviews, or settled costs."}
    registry = root / "registry"
    first = register_study(study, metadata, registry)
    records[0]["cost"]["model_usd"] = original
    write_runs()
    second = register_study(study, metadata, registry, parent=first["entry_id"],
        revision_reason="Synthetic demonstration: restore a fixture cost field; no real spending observed.")
    packet = export_review_packet(registry, second["entry_id"], root / "review-packet")
    verify_submission(root / "review-packet", packet["packet_id"])
    replay = replay_bundle(root / "review-packet")
    view = write_view(registry, root / "view")
    assert first["blockers"] and not second["blockers"]
    assert replay["status"] == "REPRODUCED"
    assert packet["review_status"] == "UNREVIEWED"
    assert view["counts"]["study_lineages"] == view["counts"]["evidence_revisions"] == 1
    receipt = {"first": first, "revision": second, "packet": packet, "view": view,
               "replay_status": replay["status"], "model_calls": 0, "real_reviews": 0,
               "evidence_type": "synthetic", "benefit_established": False}
    write_json(root / "receipt.json", receipt)
    print(json.dumps({"view": str((root / "view/index.html").resolve()), "counts": view["counts"],
                      "replay_status": replay["status"], "synthetic": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
