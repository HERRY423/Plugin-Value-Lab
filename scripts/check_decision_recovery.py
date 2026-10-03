"""Manufactured end-to-end recovery and real process-interruption acceptance."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from value_lab.core import demo_records, demo_suite, evaluate, freeze, suite_digest, write_json
from value_lab.decision_store import DecisionStore
from value_lab.delivery import read_bundle
from value_lab.evidence_dependencies import recheck, write_revision


def exercise_rescore(output):
    """Run the existing built-in grader twice on identical bytes under changed rules."""
    source = ROOT / "examples/evidence-dependencies"
    card, graph, inventory = [json.loads((source / name).read_bytes()) for name in
                             ("card.json", "graph.json", "inventory-before.json")]
    material = output / "rescore-material"
    material.mkdir()
    raw = (source / "retrieved.json").read_bytes()
    (material / "retrieved.json").write_bytes(raw)
    plan = {"card": card, "graph": graph}
    store = DecisionStore(output / "rescore.sqlite")

    def add(kind, payload, files=None):
        seq = store.snapshot()["sequence"] if store.path.exists() else 0
        return store.append(kind, payload, key=f"rescore-fixture-{seq}", expected_sequence=seq, files=files)

    add("initialize", {"plan": plan, "plan_sha256": suite_digest(plan), "required_evidence": ["raw-json"],
                       "dependencies": inventory, "budget_micros": 1000000})
    add("start", {"attempt_id": "original", "requirement": "raw-json", "mode": "local_execution",
                  "operation": "retain manufactured bytes", "external_key": "fixture-original", "max_cost_micros": 0})
    add("finish", {"attempt_id": "original", "status": "COLLECTED", "receipt": {"source": "synthetic fixture"}}, files={"raw": raw})
    add("settle", {"attempt_id": "original", "cost_micros": 0, "basis": "Local fixture import"})
    first = recheck(card, graph, inventory, material, action="rescore")
    changed = deepcopy(graph)
    next(n for n in changed["nodes"] if n["id"] == "format")["grader"]["verifier"]["expected"]["format"] = "v2"
    second = recheck(card, changed, inventory, material, previous=first, action="rescore")
    for index, (rules, report) in enumerate(((graph, first), (changed, second)), 1):
        write_revision(report, output / f"rule-revision-{index}")
        add("interpret", {"interpretation_id": f"rules-{index}", "mode": "evaluation" if index == 1 else "rescore",
            "reason": "Manufactured rule change from format v1 to v2" if index == 2 else "Initial built-in JSON check",
            "attempt_ids": ["original"], "rules": {"graph_sha256": suite_digest(rules), "engine_sha256": report["engine_sha256"]},
            "dependencies": inventory, "pending_checks": [row["rule_id"] for row in report["pending_tasks"]],
            "parent": "rules-1" if index == 2 else None}, files={"report": json.dumps(report, sort_keys=True).encode()})
    view = store.snapshot()
    assert first["rules"]["format"]["passed"] is True
    assert second["rules"]["format"]["passed"] is False
    assert view["interpretations"][0]["observations_sha256"] == view["interpretations"][1]["observations_sha256"]
    assert view["collected_attempts"] == 1 and view["costs"]["total_cost_micros"] == 0
    assert (material / "retrieved.json").read_bytes() == raw
    # Explicit new attempts retain a failed rerun and cumulative simulated costs.
    for ident, predecessor, status, actual_cost in (("failed-rerun", "original", "FAILED", 12000),
                                                    ("next-rerun", "failed-rerun", "COLLECTED", 23000)):
        add("start", {"attempt_id": ident, "requirement": "raw-json", "mode": "local_execution",
            "operation": "manufactured reexecution", "external_key": "fixture-" + ident, "max_cost_micros": 100000,
            "retry_of": predecessor, "reason": "Separate explicit fixture attempt"})
        add("finish", {"attempt_id": ident, "status": status, "receipt": {"source": "synthetic execution receipt"}},
            files={"raw": b'{"format":"v2"}'} if status == "COLLECTED" else {"stderr": b"manufactured failure"})
        add("settle", {"attempt_id": ident, "cost_micros": actual_cost, "basis": "Simulated fixture ledger, no payment"})
    view = store.snapshot()
    assert view["costs"]["total_cost_micros"] == 35000 and view["attempts"]["failed-rerun"]["status"] == "FAILED"
    assert view["collected_attempts"] == 2 and len(view["attempts"]) == 3
    store.export(output / "rescore-and-rerun-recovery")
    return {"same_raw_bytes": True, "old_check_passed": True, "new_check_passed": False,
            "observations_after_rescore": 1, "attempts_after_reexecution": 3,
            "collected_attempts_after_reexecution": 2, "failed_attempt_retained": True,
            "simulated_cumulative_micros": 35000, "actual_paid_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        parser.error("Choose a fresh acceptance output directory")
    output.mkdir(parents=True)
    suite = demo_suite()
    write_json(output / "suite.json", suite)
    lock = freeze(suite, output / "protocol.lock.json")
    store = DecisionStore(output / "decision.sqlite")
    view = store.initialize_study(suite, lock, {"host": "manufactured-fixture", "evaluator": "source-checkout"},
                                  1000000, key="initialize")
    original_records = demo_records(suite)
    for index, record in enumerate(original_records):
        ident = f"attempt-{index}"
        requirement = f'{record["case_id"]}--{record["arm"]}--{record["repetition"]}'
        payload = {"attempt_id": ident, "requirement": requirement, "mode": "local_execution",
                   "operation": "import manufactured demo record", "external_key": f"fixture-{index}",
                   "max_cost_micros": 100000}
        view = store.append("start", payload, key=f"start-{index}", expected_sequence=view["sequence"])
        view = store.append("finish", {"attempt_id": ident, "status": "COLLECTED",
            "receipt": {"source": "core.demo_records", "evidence_type": "synthetic"}},
            key=f"collect-{index}", expected_sequence=view["sequence"],
            files={"record": json.dumps(record, sort_keys=True).encode()})
        view = store.append("settle", {"attempt_id": ident, "cost_micros": 0,
            "basis": "Manufactured local import, no external invocation"}, key=f"cost-{index}",
            expected_sequence=view["sequence"])
    before = store.snapshot()
    store.export(output / "raw-recovery")
    read_bundle(output / "raw-recovery")
    records = [json.loads((output / "raw-recovery" / (a["artifacts"]["record"] + ".blob")).read_bytes())
               for a in before["attempts"].values()]
    assert records == original_records
    restored = DecisionStore(output / "decision.sqlite").snapshot()
    assert restored == before
    report = evaluate(restored["plan"]["suite"], records, restored["plan"]["lock"])
    assert report["verdict"] == "SIMULATION_ONLY"
    report_bytes = json.dumps(report, ensure_ascii=False, sort_keys=True).encode()
    view = store.append("interpret", {"interpretation_id": "evaluation-1", "mode": "evaluation",
        "reason": "Evaluate original synthetic records recovered from committed bytes",
        "attempt_ids": list(restored["attempts"]), "rules": {"implementation": "value_lab.core.evaluate",
        "suite_sha256": suite_digest(suite)}, "dependencies": restored["dependencies"],
        "pending_checks": ["Real-world benefit remains unestablished"], "parent": None},
        key="evaluate-1", expected_sequence=restored["sequence"], files={"report": report_bytes})
    # A pending external attempt is only a ledger fixture; nothing is dispatched.
    view = store.append("start", {"attempt_id": "pending-fixture", "requirement": view["required_evidence"][0],
        "mode": "tool_execution", "operation": "fixture provider GET /result", "external_key": "fixture-original-key",
        "max_cost_micros": 100000, "retry_of": next(i for i, a in view["attempts"].items() if a["requirement"] == view["required_evidence"][0]),
        "reason": "Separate manufactured reexecution attempt"}, key="pending", expected_sequence=view["sequence"])
    view = store.append("unknown", {"attempt_id": "pending-fixture", "reason": "Manufactured transport timeout"},
                        key="timeout", expected_sequence=view["sequence"])
    exported = store.export(output / "recovery")
    assert exported["status"] == "COMMITTED"
    assert store.snapshot()["collected_attempts"] == len(records)
    assert store.snapshot()["costs"]["reserved_micros"] == 100000
    assert store.snapshot()["costs"]["total_cost_micros"] is None
    checkpoint = store.snapshot()["checkpoint"]
    restored_store = DecisionStore(output / "restored.sqlite")
    restored_store.restore(output / "recovery", checkpoint=checkpoint)
    assert restored_store.snapshot() == store.snapshot()
    assert restored_store.restore(output / "recovery", checkpoint=checkpoint)["replayed"]
    rescore_evidence = exercise_rescore(output)
    tests = [
        "tests.test_decision_recovery.DeliveryTests.test_killed_report_write_is_not_a_result_and_resume_keeps_attempt",
        "tests.test_decision_recovery.RecoveryTests.test_killed_after_dispatch_record_recovers_original_attempt",
        "tests.test_decision_recovery.RecoveryTests.test_killed_during_evidence_commit_rolls_back_blobs_and_event",
        "tests.test_decision_contracts.DecisionContractTests.test_interrupted_restore_rolls_back_and_same_bundle_recovers",
        "tests.test_decision_contracts.DecisionContractTests.test_report_resume_uses_saved_score_without_running_scorer",
    ]
    child = subprocess.run([sys.executable, "-m", "unittest", *tests, "-v"], cwd=ROOT, capture_output=True)
    (output / "fault-tests.log").write_bytes(child.stdout + child.stderr)
    receipt = {"format": "pvl-decision-recovery-acceptance-1", "status": "PASS" if child.returncode == 0 else "FAIL",
        "evidence_level": "MANUFACTURED_LOCAL_FIXTURE", "fault_cases": tests,
        "retained_records": len(records), "recovered_verdict": report["verdict"],
        "original_record_equality": True, "state_equal_after_reopen": True,
        "exact_bundle_restore": True, "restore_idempotent": True, "checkpoint_verified": True,
        "real_builtin_rescore_on_manufactured_bytes": rescore_evidence,
        "unknown_attempt_retained": True, "reservation_micros": 100000, "simulation_costs_only": True,
        "paid_services_invoked": False, "real_external_calls": 0, "real_scientific_executions": 0,
        "benefit_established": False, "installed_host_verified": False}
    write_json(output / "acceptance.json", receipt)
    print(json.dumps(receipt, ensure_ascii=True))
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(main())

