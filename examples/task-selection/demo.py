"""Manufactured selection walkthrough: no real plugin, model or scientific execution."""
from copy import deepcopy
from itertools import product
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from value_lab.artifacts import sha
from value_lab.core import demo_suite, suite_digest, write_json
from value_lab.task_selection import FORMAT, _manifest
from value_lab.workflow import plan_plugin_use, write_plan


def fixture(root, *, synthetic=True):
    """Non-synthetic labels cover unit-test gates only, never a saved example."""
    root = Path(root)
    artifacts, scorers = root / "artifacts", root / "scorers"
    artifacts.mkdir(parents=True)
    scorers.mkdir()
    write_json(scorers / "family.json", {"ids": ["g1", "g2", "g3"]})
    expected_counts = {"counts": [[4, 2], [3, 7]], "sample_ids": ["d1_control", "d1_treated"], "paired": True}
    expected_chain = {"paired": True, "input_snapshot": "manufactured-counts-v1", "genes": ["g1", "g2", "g3"], "scope": "computational_only"}
    specs = [{"kind": "json_fields", "expected": expected_counts},
             {"kind": "de_table", "id_column": "gene", "p_column": "p", "q_column": "q", "effect_column": "effect",
              "min_rows": 3, "bh_tolerance": 1e-9, "testing_family": {"path": "family.json", "sha256": sha(scorers / "family.json")}},
             {"kind": "json_fields", "expected": expected_chain}]
    cases = [{"id": cid, "cluster": cid, "kind": "task", "prompt": prompt,
              "graders": [{"id": "correct", "type": "artifact", "artifact": "result", "dimension": "outcome",
                           "weight": 1, "critical": True, "verifier": spec}]} for cid, prompt, spec in zip(
        ("prepare-check", "table-check", "integration-check"),
        ("Preserve paired sample identities and raw counts in the manufactured fixture.",
         "Check complete testing-family membership and BH arithmetic in the manufactured DE table.",
         "Check the full fixture workflow preserves paired scope, source identity and tested genes."), specs)]
    conditions = {"model": "fixture-model", "model_version": "fixture-revision-1", "host": "fixture-host",
                  "host_version": "fixture-host-1", "tools": [], "environment": "manufactured", "budget": {"max_turns": 5}}
    facts = {"paired": True, "input_kind": "raw_counts", "goal": "computational_audit"}
    task = {"id": "paired-table-task", "summary": "配对材料整理、差异表核对与完整交付（合成演示，非真实拟合）",
            "facts": facts, "inputs": {"counts": "c" * 64}, "conditions": conditions,
            "stages": [
                {"id": "prepare", "summary": "整理样本与原始计数", "depends_on": [], "decision_factors": list(facts),
                 "case_ids": ["prepare-check"], "required_reviews": ["研究者核对供者身份和配对设计。"]},
                {"id": "check", "summary": "核对完整差异表", "depends_on": ["prepare"], "decision_factors": list(facts),
                 "case_ids": ["table-check"], "required_reviews": ["研究者复核统计方法和结论范围；BH 一致不证明科学有效。"]}],
            "cases": cases, "integration_case_ids": ["integration-check"]}
    components = [{"id": cid, "name": name, "kind": kind, "version": "fixture-1", "sha256": digit * 64,
                   "installed": cid != "plugin"} for cid, name, kind, digit in (
        ("native", "Existing native tools", "native", "1"), ("script", "Existing reference script", "script", "2"),
        ("plugin", "Manufactured candidate A", "plugin", "3"))]
    options = [{"id": f"{c['id']}-{s['id']}", "stage_id": s["id"], "component_id": c["id"], "capability": s["summary"],
                "requires": {k: [v] for k, v in facts.items()}, "required_reviews": []} for s in task["stages"] for c in components]
    selection = {"format": FORMAT, "task": task, "components": components, "options": options,
                 "policy": {"objective": "fewest_new_plugins_then_total_plugins", "max_new_plugins": 1, "quality_floor": 1}, "studies": []}
    catalog_hash = suite_digest({k: v for k, v in selection.items() if k != "studies"})
    manifests = {key: _manifest([next(o for o in options if o["id"] == f"{c}-{s}") for c, s in zip(key, ("prepare", "check"))],
                               {c["id"]: c for c in components}) for key in product(("native", "script", "plugin"), repeat=2)}
    pairs = [(("plugin", "plugin"), ("native", "native")), (("plugin", "script"), ("script", "script")),
             (("plugin", "native"), ("script", "native")), (("native", "plugin"), ("native", "script")),
             (("script", "plugin"), ("script", "script"))]
    for index, pair in enumerate(pairs):
        suite = demo_suite()
        suite.update(id=f"fixture-comparison-{index}", cases=deepcopy(cases), conditions=deepcopy(conditions), runs_per_case=1,
                     evidence_type="synthetic" if synthetic else "local", plugin={k: components[2][k] for k in ("name", "version", "sha256")})
        suite["policy"].update(quality_floor=1, min_clusters=2)
        suite["task_selection"] = {"catalog_sha256": catalog_hash, "treatment_component": "plugin",
                                   "arms": {arm: suite_digest(manifests[key]) for arm, key in zip(("with", "without"), pair)}}
        digest, records = suite_digest(suite), []
        for arm, key in zip(("with", "without"), pair):
            for case in cases:
                path = artifacts / f"study-{index}" / arm / (case["id"] + (".csv" if case["id"] == "table-check" else ".json"))
                path.parent.mkdir(parents=True, exist_ok=True)
                if case["id"] == "prepare-check":
                    write_json(path, {**expected_counts, "counts": expected_counts["counts"] if key[0] == "plugin" else [[7, 9]]})
                elif case["id"] == "table-check":
                    path.write_text("gene,p,q,effect\ng1,0.01," + ("0.03" if key[1] == "script" else "0.01") + ",2\ng2,0.04,0.06,-1\ng3,0.2,0.2,0\n", encoding="utf-8")
                else:
                    write_json(path, {**expected_chain, "paired": key == ("plugin", "script")})
                records.append({"case_id": case["id"], "repetition": 1, "arm": arm, "suite_sha256": digest,
                    "session_id": f"fixture-{index}-{arm}-{case['id']}", "conditions": deepcopy(conditions), "plugin_loaded": arm == "with",
                    "status": "completed", "output": "Manufactured test output, not a scientific run.", "source": "synthetic" if synthetic else "manual",
                    "cost": {"model_usd": 0, "tool_usd": 0, "human_minutes": 0}, "human_intervals": [],
                    "artifacts": {"result": {"path": path.relative_to(artifacts).as_posix(), "sha256": sha(path)}},
                    "selection_plan_sha256": suite["task_selection"]["arms"][arm],
                    "observed_components": {c["id"]: c["sha256"] for c in manifests[key]["components"]}, "input_snapshot": deepcopy(task["inputs"])})
        selection["studies"].append({"suite": suite, "records": records, "lock": {"suite_sha256": digest},
            "cost_ledger": {"schema_version": 1, "entries": [], "coverage": {k: "not_applicable" for k in ("setup", "retry", "judge", "other")}}})
    return {"schema_version": 1, "intent": "choose", "task_selection": selection}, artifacts, scorers


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    output = Path(parser.parse_args().output)
    if output.exists():
        parser.error("Preserve prior examples; choose an absent output directory")
    context, artifacts, scorers = fixture(output)
    write_json(output / "context.json", context)
    plan = plan_plugin_use(context, artifact_root=artifacts, verifier_root=scorers)
    paths = write_plan(plan, output / "plan")
    print(plan["evidence_status"])
    print(paths["md"])
