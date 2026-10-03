"""Local acceptance: same retained bytes, corrected rule, explicit new guidance.

All material is manufactured. No external calls, science execution or paid costs.
"""
import argparse
import base64
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from value_lab.artifacts import sha
from value_lab.core import suite_digest
from value_lab.decision_store import DecisionStore
from value_lab.evidence_dependencies import FORMAT, REQUIRED, recheck, write_revision


def exercise(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    historical = json.loads((ROOT / "tests/fixtures/decision-history-v2.json").read_bytes())
    bundle = output / "historical"
    bundle.mkdir()
    for name, encoded in historical["bundles"]["old-rule-error"].items():
        (bundle / name).write_bytes(base64.b64decode(encoded))
    store = DecisionStore(output / "decision.sqlite")
    before = store.restore(bundle)
    def add(kind, payload, files=None):
        sequence = store.snapshot()["sequence"]
        return store.append(kind, payload, key=f"acceptance-{sequence}", expected_sequence=sequence, files=files)
    add("settle", {"attempt_id": "first", "cost_micros": 0, "basis": "Local synthetic fixture, no external service"})
    raw = output / "raw"
    raw.mkdir()
    digest = before["attempts"]["first"]["artifacts"]["raw"]
    (raw / "retrieved.json").write_bytes((bundle / (digest + ".blob")).read_bytes())
    card = {"type": "plugin_usage_card", "status": "SIMULATION_ONLY", "verdict": "SIMULATION_ONLY",
            "envelope": {"rows": [{"guidance": "Manufactured format check only"}]}}
    nodes = [{"id": d, "kind": "dependency", "category": d, "depends_on": []} for d in sorted(REQUIRED)]
    nodes += [{"id": "raw", "kind": "artifact", "path": "retrieved.json", "sha256": sha(raw / "retrieved.json"), "depends_on": []},
              {"id": "format", "kind": "rule", "scope": "historical_artifact", "mode": "artifact_rescore",
               "basis": "Manufactured schema check; no scientific claim", "depends_on": ["raw"],
               "grader": {"id": "format", "type": "artifact", "artifact": "raw", "verifier": {"kind": "json_fields", "expected": {"format": "v1"}}}},
              {"id": "claim", "kind": "claim", "statement": "Fixture conforms to its declared format", "depends_on": ["format"]},
              {"id": "advice", "kind": "recommendation", "card_pointer": "/envelope/rows/0", "depends_on": ["claim"]}]
    graph = {"format": FORMAT, "card_sha256": suite_digest(card), "coverage": {"complete": True, "basis": "Closed synthetic fixture"}, "nodes": nodes}
    inventory = {d: "fixture-v1" for d in REQUIRED}
    first = recheck(card, graph, inventory, raw, action="rescore")
    changed = deepcopy(graph)
    next(n for n in changed["nodes"] if n["id"] == "format")["grader"]["verifier"]["expected"]["items"] = ["required"]
    second = recheck(card, changed, inventory, raw, previous=first, action="rescore")
    assert first["rules"]["format"]["status"] == "PASSED"
    assert second["rules"]["format"]["status"] == "FAILED"
    policy = {"purpose": "Demonstrate lifecycle on synthetic JSON", "quality_thresholds": {"require_all_declared_fields": True}, "budget_micros": 1000}
    for number, report in enumerate((first, second), 1):
        write_revision(report, output / f"recheck-{number}")
        view = store.record_recheck(report, card, ["first"], f"j{number}", parent="j1" if number == 2 else None,
                                   key=f"judgment-{number}", expected_sequence=store.snapshot()["sequence"])
        if number == 1:
            add("decide", {"decision_id": "d1", "judgment_id": "j1", "policy": policy, "scope": {"fixture": "JSON schema"},
                "recommendation": "Historical format check passed; simulation only", "reason": "initial declared check", "replaces": None, "status": "current"})
            original = store.snapshot()
            add("present", {"presentation_id": "display-1", "target_kind": "decision", "target_id": "d1", "renderer": {"version": "1"}},
                {"report": b"Historical fixture report; not current guidance after revision"})
        else:
            assert view["guidance_review_required"] == ["d1"] and view["current_decisions"] == []
            add("decide", {"decision_id": "d2", "judgment_id": "j2", "policy": policy, "scope": {"fixture": "JSON schema"},
                "recommendation": "Required items are absent; retain failure and review use", "reason": "Corrected rule found omitted field",
                "replaces": "d1", "status": "review_required"})
    policy2 = {**policy, "purpose": "New explicit research purpose; no new grading"}
    add("decide", {"decision_id": "d3", "judgment_id": "j2", "policy": policy2, "scope": {"fixture": "JSON schema"},
        "recommendation": "Still under review under the new purpose", "reason": "Policy-only revision", "replaces": "d2", "status": "review_required"})
    add("present", {"presentation_id": "display-2", "target_kind": "decision", "target_id": "d3", "renderer": {"version": "2"}},
        {"report": "缺少必需字段；新用途仍需复核。".encode()})
    final = store.snapshot()
    assert final["attempts"] == original["attempts"]
    assert final["interpretations"] == before["interpretations"]
    assert final["explanations"]["judgments"]["j1"]["observation_sha256"] == final["explanations"]["judgments"]["j2"]["observation_sha256"]
    assert len(final["explanations"]["judgments"]) == 2
    assert final["explanations"]["decision_states"]["d1"]["superseded_by"] == "d2"
    recovery = output / "recovery"
    store.export(recovery)
    restored = DecisionStore(output / "restored.sqlite").restore(recovery, checkpoint=final["checkpoint"])
    assert restored["explanations"] == final["explanations"]
    for name in historical["bundles"]["old-rule-error"]:
        if name.endswith(".blob"):
            assert (recovery / name).read_bytes() == (bundle / name).read_bytes()
    result = {"status": "PASS", "evidence": "SIMULATION_ONLY", "historical_wheel": historical["provenance"]["source_wheel_sha256"],
              "historical_interpretations_unchanged": True, "historical_blob_bytes_unchanged": True,
              "old_rule": first["rules"]["format"]["status"], "corrected_rule": second["rules"]["format"]["status"],
              "observation_identity_unchanged": True, "judgments": 2, "policy_decisions": 3, "presentations": 2,
              "policy_only_revision_added_judgments": 0, "guidance_review_required": final["guidance_review_required"],
              "current_decisions": final["current_decisions"], "checkpointed_restore_matches": True,
              "new_external_executions": 0, "new_scientific_samples": 0, "paid_calls": 0, "execution_authorized": False}
    (output / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    print(json.dumps(exercise(parser.parse_args().output), ensure_ascii=False, indent=2))
