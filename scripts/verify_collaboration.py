"""Exercise real CLI processes on a supplied retained study, without model calls.

This is historical evidence replay and engineering integration, never new native
host execution or human acceptance. Source inputs are read but never modified.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.artifacts import read_only_verification
from value_lab.collaboration import capture_inputs, encode, implementation_identity
from value_lab.core import evaluate, load_json, load_records, suite_digest
from value_lab.decision_store import DecisionStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, help="Retained study with suite.json, runs.jsonl and artifacts/")
    parser.add_argument("--output", required=True, help="New directory; refuses to overwrite an earlier run")
    args = parser.parse_args()
    study = Path(args.study).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = {name: hashlib.sha256((study / name).read_bytes()).hexdigest()
              for name in ("suite.json", "runs.jsonl", "protocol.lock.json")}
    suite = load_json(study / "suite.json")
    records = load_records(study / "runs.jsonl")
    lock = load_json(study / "protocol.lock.json")
    # The missing input is deliberately withheld for this integration scenario;
    # it is not represented as a defect in the original historical study.
    incomplete = capture_inputs(suite, records, lock)
    complete = capture_inputs(suite, records, lock, artifact_root=study / "artifacts")
    state = {"sequence": 0}
    task = "historical-study"
    index = 0
    transcript = []
    def call(action, arguments=None, *, actor="executor-agent", target=None, sequence=None, key=None):
        nonlocal state, index
        index += 1
        request = {"task_id": target or task, "action": action, "arguments": arguments or {},
                   "key": key or "verification-" + str(index),
                   "expected_sequence": state["sequence"] if sequence is None else sequence}
        path = output / f"{index:02d}-{action}.request.json"
        path.write_bytes(encode(request))
        result = subprocess.run([sys.executable, "-B", "-m", "value_lab.collaboration",
            "--root", str(output), "--actor", actor, "--request", str(path)], cwd=ROOT,
            capture_output=True, text=True, timeout=60)
        (output / f"{index:02d}-{action}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        (output / f"{index:02d}-{action}.response.json").write_text(result.stdout, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"CLI {action} failed; retained output {path}")
        data = json.loads(result.stdout)
        transcript.append({"step": index, "action": action, "actor": actor, "exit_code": result.returncode,
                           "sequence": data.get("sequence"), "stage": data.get("status", {}).get("stage")})
        if "sequence" in data:
            state = data
        return data
    call("open", {"inputs": incomplete})
    first = call("execute", {"attempt_id": "a1", "reason": "Historical replay with deliberately absent artifact bytes"})
    call("handoff", {"handoff_id": "review-handoff", "recipient": {"id": "review-agent", "kind": "agent"},
                     "note": "Agent review of missing artifact receipts; no human acceptance"})
    call("receive", {"handoff_id": "review-handoff"}, actor="review-agent")
    call("review", {"review_id": "missing-artifacts", "attempt_id": "a1",
        "result_sha256": first["result_sha256"], "verdict": "request_changes",
        "notes": "Retain the exact hash-bound source artifacts so another process can reproduce scoring. Keep all six observations, the failure, original suite and lock."}, actor="review-agent")
    call("correct", {"review_id": "missing-artifacts", "inputs": complete,
                    "reason": "Attach original retained artifact bytes; no changes to records or frozen criteria"}, actor="review-agent")
    start_seq = state["sequence"]
    run_args = {"attempt_id": "a2", "reason": "Explicit reevaluation after restoring input artifact availability"}
    final = call("execute", run_args, actor="review-agent", key="corrected-execution")
    repeated = call("execute", run_args, actor="review-agent", key="corrected-execution", sequence=start_seq)
    assert repeated["replayed"] and not repeated["execution_performed"]
    assert final["result_sha256"] == repeated["result_sha256"]
    full_result = call("result", actor="review-agent")
    call("review", {"review_id": "agent-check", "attempt_id": "a2", "result_sha256": final["result_sha256"],
        "verdict": "accept", "notes": "Agent engineering review only. Insufficient scientific evidence and human review remain."}, actor="review-agent")
    assert state["status"]["stage"] == "AWAITING_HUMAN_REVIEW"
    call("handoff", {"handoff_id": "recovery", "recipient": {"id": "recovery-agent", "kind": "agent"},
                     "note": "Recover the bundle in a fresh process; no reexecution"}, actor="review-agent")
    exported = call("export", {"directory": "recovery-bundle"}, actor="review-agent")
    (output / "separate-checkpoint.json").write_bytes(encode(exported["checkpoint"]))
    restored = call("restore", {"directory": "recovery-bundle", "checkpoint": exported["checkpoint"]},
                    target="recovered-study", actor="recovery-agent")
    assert not restored["execution_performed"] and restored["result_sha256"] == final["result_sha256"]
    task = "recovered-study"
    call("receive", {"handoff_id": "recovery"}, actor="recovery-agent")
    call("handoff", {"handoff_id": "human-review", "recipient": {"id": "researcher", "kind": "human"},
                    "note": "Await a real researcher; no human acceptance has been performed."}, actor="recovery-agent")
    human_bundle = call("export", {"directory": "human-review-bundle"}, actor="recovery-agent")
    # Copy editable requests OUTSIDE the immutable recovery bundle. Do not
    # silently fill a review rationale or declare a researcher has accepted.
    for source_name, output_name in (("RECEIVE.request.json", "HUMAN-RECEIVE.request.json"),
                                     ("REVIEW.template.json", "HUMAN-REVIEW.template.json")):
        request = load_json(output / "human-review-bundle" / source_name)
        request["task_id"] = task
        (output / output_name).write_bytes(encode(request))
    with read_only_verification():
        baseline = evaluate(suite, records, lock, artifact_root=study / "artifacts")
    assert full_result["result"]["report"] == baseline, "Recovered scoring disagrees with direct source evaluation"
    snapshot = DecisionStore(output / "recovered-study.sqlite").snapshot()
    assert all(rev["inputs"]["records"] == records and rev["inputs"]["suite"] == suite
               and rev["inputs"]["lock"] == lock for rev in snapshot["collaboration"]["revisions"])
    assert all(hashlib.sha256((study / name).read_bytes()).hexdigest() == digest for name, digest in source.items())
    summary = {"format": "pvl-collaboration-verification-1", "status": "PASS_LOCAL_HISTORICAL_REPLAY",
        "implementation": implementation_identity(), "source_file_sha256": source,
        "source_evidence_type": suite["evidence_type"], "source_records": len(records),
        "source_status_counts": dict(Counter(r["status"] for r in records)),
        "retained_artifact_files": len(complete["artifact_files"]),
        "retained_artifact_sha256": suite_digest(complete["artifact_files"]),
        "source_records_and_criteria_unchanged": True, "source_files_unchanged": True,
        "corrected_report_equals_direct_evaluation": True, "duplicate_execute_dispatched": False,
        "restore_executed": False, "new_model_runs": 0, "new_scientific_observations": 0,
        "scenario": "Deliberately omitted artifact bytes, then restored original bytes after agent review",
        "human_participants": 0, "human_acceptance_verified": False,
        "native_host_acceptance": "NOT_RUN", "independent_researcher_handoff": "NOT_RUN",
        "cost_for_new_paid_calls_usd": 0, "real_collaboration_benefit": "NOT_ASSESSED",
        "final_status": state["status"], "human_bundle_checkpoint": human_bundle["checkpoint"],
        "steps": transcript, "report": baseline}
    (output / "verification.json").write_bytes(encode(summary))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("report", "steps")}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
