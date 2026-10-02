"""Run the manufactured dependency-change example locally, without model calls."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from value_lab.core import load_json, write_json
from value_lab.evidence_dependencies import recheck, write_revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        parser.error("Choose a fresh output directory")
    source = ROOT / "examples/evidence-dependencies"
    card, graph = (load_json(source / name) for name in ("card.json", "graph.json"))
    inventory = load_json(source / "inventory-before.json")
    first = recheck(card, graph, inventory, source, action="rescore")
    paths = {"first": write_revision(first, output / "first")}
    changed = recheck(card, graph, load_json(source / "inventory-tool-changed.json"), source,
                      previous=first, action="rescore")
    paths["api_change"] = write_revision(changed, output / "api-change")
    unknown = recheck(card, graph, load_json(source / "inventory-unknown.json"), source,
                      previous=first, action="rescore")
    paths["unknown_change"] = write_revision(unknown, output / "unknown-change")
    replay = recheck(card, graph, inventory, source, action="replay")
    paths["replay"] = write_revision(replay, output / "replay")
    assert first["local_rescores"] == 1
    assert changed["local_rescores"] == 0 and changed["rules"]["format"]["action"] == "retained"
    assert changed["recommendations"][0]["review_required"] is False
    assert changed["recommendations"][1]["review_required"] is True
    assert changed["rules"]["retrieval"]["status"] == "REEXECUTION_REQUIRED"
    assert unknown["recheck_scope"] == "FULL" and unknown["local_rescores"] == 1
    assert replay["artifact_replays"] == 1 and replay["local_rescores"] == 0
    assert replay["rules"]["format"]["status"] == "REPLAYED_ONLY"
    assert all(r["source_verdict"] == "SIMULATION_ONLY" and not r["whole_card_renewed"]
               and r["new_model_executions"] == r["new_scientific_executions"] == 0
               for r in (first, changed, unknown, replay))
    receipt = {"format": "pvl-dependency-fixture-acceptance-1", "status": "PASS",
               "evidence_level": "MANUFACTURED_LOCAL_FIXTURE", "new_model_calls": 0,
               "new_scientific_executions": 0, "paid_services_invoked": False,
               "baseline_rescores": first["local_rescores"], "api_change_rescores": changed["local_rescores"],
               "unknown_change_rescores": unknown["local_rescores"], "paths": paths,
               "benefit_established": False, "installed_host_verified": False,
               "limits": "Checks routing and conservative evidence boundaries, not real dependency coverage or actual cost savings."}
    write_json(output / "acceptance.json", receipt)
    print(json.dumps(receipt, ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
