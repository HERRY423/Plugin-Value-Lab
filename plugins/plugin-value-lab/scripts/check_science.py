"""Offline scientific-grader/Scenario-Pack acceptance. All data are synthetic."""
import argparse
import json
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.artifacts import sha
from value_lab.core import demo_suite, evaluate, freeze, suite_digest, write_json
from value_lab.registry import register_study, export_entry, replay_bundle, write_view
from value_lab.report import write_reports
from value_lab.scenarios import validate_pack, prepare_suite, stage_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    root = Path(parser.parse_args().output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    inputs, scorers, study, collected = (root / p for p in ("inputs", "scorers", "study", "collected"))
    for path in (inputs, scorers, study, collected):
        path.mkdir()
    (inputs / "data.csv").write_text("id,value\na,1\nb,1\nc,2\nd,2\n", encoding="utf-8")
    cases = []
    for case_id, split, kind in (("cluster", "development", "numeric_tolerance"), ("effect", "heldout", "numeric_tolerance"),
                                 ("justified", "development", "over_refusal"), ("insufficient", "heldout", "abstention_correct")):
        if kind == "numeric_tolerance":
            truth = scorers / (case_id + ".csv")
            truth.write_bytes((inputs / "data.csv").read_bytes() if case_id == "cluster" else b"id,value\na,0\nb,1\nc,2\nd,3\n")
            # Visible data and scorer labels must not be byte-identical, even in fixtures.
            if case_id == "cluster":
                truth.write_text("id,value\na,T\nb,T\nc,B\nd,B\n", encoding="utf-8")
            spec = {"metric": "ari" if case_id == "cluster" else "pearson", "truth": {"path": truth.name, "sha256": sha(truth)},
                    "id_column": "id", "value_column": "value", "threshold": .9, "absolute": 0, "relative": 0}
            output = "result.csv"
        else:
            truth = scorers / (case_id + "-decision.json")
            write_json(truth, {"decision": "allow" if kind == "over_refusal" else "withhold", "rationale": "Synthetic software fixture"})
            spec = {"truth": {"path": truth.name, "sha256": sha(truth)}}
            output = "result.json"
        private = {"type": "ScorerOnlyGroundTruth", "case_id": case_id, "evidence_type": "synthetic", "nonce": secrets.token_hex(32),
                   "rationale": "Public teaching fixture, not expert-validated truth", "graders": [{"id": "check", "type": kind, "artifact": "result", "verifier": spec}]}
        rule = scorers / (case_id + ".json")
        write_json(rule, private)
        cases.append({"type": "AgentVisibleScenario", "id": case_id, "family": case_id, "split": split,
                      "prompt": f"Synthetic {case_id} task: write {output}; data are manufactured teaching values.",
                      "inputs": {"data.csv": sha(inputs / "data.csv")}, "outputs": {"result": output},
                      "scorer": {"path": rule.name, "sha256": sha(rule)}})
    pack = {"format": "pvl-scenario-pack-1", "id": "science-teaching-pack", "evidence_type": "synthetic",
            "sources": [{"url": "synthetic:check_science", "license": "MIT", "provenance": "Manufactured software fixture"}], "scenarios": cases}
    write_json(root / "pack.json", pack)
    validation = validate_pack(pack, inputs, scorers)
    for case in cases:
        stage_case(pack, case["id"], inputs, root / "agent" / case["id"], scorers)
    suite = prepare_suite(pack, demo_suite())
    suite["id"] = "scientific-contract-acceptance"
    write_json(study / "suite.json", suite)
    lock = freeze(suite, study / "protocol.lock.json")
    records = []
    for case in cases:
        for arm in ("with", "without"):
            for rep in range(1, 4):
                session = f'{case["id"]}-{arm}-{rep}'
                filename = session + (".csv" if case["id"] in ("cluster", "effect") else ".json")
                path = collected / filename
                if case["id"] in ("cluster", "effect"):
                    path.write_text("id,value\na,1\nb,1\nc,2\nd,2\n", encoding="utf-8")
                else:
                    write_json(path, {"decision": "allow" if arm == "with" else "withhold"})
                records.append({"case_id": case["id"], "arm": arm, "repetition": rep, "session_id": session,
                    "suite_sha256": suite_digest(suite), "source": "synthetic", "status": "completed",
                    "conditions": suite["conditions"], "plugin_loaded": arm == "with", "output": "Synthetic output",
                    "artifacts": {"result": {"path": filename, "sha256": sha(path)}},
                    "cost": {"model_usd": 0, "tool_usd": 0, "human_minutes": 0}, "duration_seconds": 1, "human_intervals": []})
    # Keep a planned failure visible; do not silently remove its denominator.
    records[-1]["status"] = "timeout"
    (study / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    report = evaluate(suite, records, lock, artifact_root=collected, verifier_root=scorers)
    write_reports(report, root / "report")
    metadata = {"observed_at": "2026-09-23T00:00:00Z", "authors": [{"id": "Synthetic fixture", "organization": "Software testing only"}],
                "plugin_sha256": "a" * 64, "limitations": "No model executions, actual spending, expert truth or independent reviews."}
    entry = register_study(study, metadata, root / "registry", artifact_root=collected, verifier_root=scorers)
    export_entry(root / "registry", entry["entry_id"], root / "bundle")
    replay = replay_bundle(root / "bundle", verifier_root=scorers)
    if report["verdict"] != "SIMULATION_ONLY" or replay["status"] != "REPRODUCED":
        raise RuntimeError("Scientific contract acceptance failed")
    write_view(root / "registry", root / "view")
    receipt = {"evidence_type": "synthetic", "model_calls": 0, "real_research_results": 0, "version_changed": False,
               "validation": validation, "registry": entry, "replay_status": replay["status"],
               "scientific_errors": report["scientific_errors"], "live_docker_isolation_verified": False}
    write_json(root / "receipt.json", receipt)
    print(json.dumps({"report": str(root / "report/report.html"), "receipt": str(root / "receipt.json"), "replay": replay["status"], "synthetic": True}))


if __name__ == "__main__":
    main()
