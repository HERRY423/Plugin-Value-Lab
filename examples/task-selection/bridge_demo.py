"""Manufactured old/new matrix bridge; never real scientific execution."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("selection_fixture", Path(__file__).with_name("demo.py"))
selection_fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection_fixture)
from value_lab.artifacts import sha
from value_lab.core import suite_digest, write_json
from value_lab.evidence_bridge import CONTRACT
from value_lab.workflow import plan_plugin_use, write_plan


def fixture(root, *, synthetic=True):
    """Construct both original fixture observations and their new target prospectively."""
    context, artifacts, scorers = selection_fixture.fixture(root, synthetic=synthetic)
    source = context["task_selection"]
    design = {k: source["task"]["facts"][k] for k in ("paired", "input_kind", "goal")}
    old = {"matrix": {"row_ids": ["d1_control", "d1_treated"], "columns": ["g1", "g2", "g3"], "values": [[4, 2, 1], [3, 7, 0]]}, "context": design}
    new = deepcopy(old)
    new["matrix"]["row_ids"] += ["d2_control", "d2_treated"]
    new["matrix"]["values"] += [[0, 3, 1], [2, 8, 1]]
    write_json(artifacts / "old-input.json", old)
    write_json(artifacts / "new-input.json", new)
    source["task"]["inputs"] = {"counts": sha(artifacts / "old-input.json")}
    source["task"]["facts"]["data_scale"] = 2
    # These are newly manufactured original fixtures, not retrofitted real evidence.
    source["task"]["cases"][0]["graders"][0]["verifier"]["expected"].update(counts=old["matrix"]["values"], sample_ids=old["matrix"]["row_ids"])
    source["task"]["cases"][2]["graders"][0]["verifier"]["expected"]["input_snapshot"] = source["task"]["inputs"]["counts"]
    catalog = suite_digest({k: v for k, v in source.items() if k != "studies"})
    for study in source["studies"]:
        study["suite"]["cases"] = deepcopy(source["task"]["cases"])
        study["suite"]["task_selection"]["catalog_sha256"] = catalog
        digest = suite_digest(study["suite"])
        study["lock"] = {"suite_sha256": digest}
        for record in study["records"]:
            record.update(suite_sha256=digest, input_snapshot=deepcopy(source["task"]["inputs"]))
            path = artifacts / record["artifacts"]["result"]["path"]
            if record["case_id"] == "prepare-check":
                import json
                value = json.loads(path.read_text(encoding="utf-8"))
                if value["counts"] == [[4, 2], [3, 7]]:
                    value["counts"] = old["matrix"]["values"]
                write_json(path, value)
            elif record["case_id"] == "integration-check":
                import json
                value = json.loads(path.read_text(encoding="utf-8"))
                value["input_snapshot"] = source["task"]["inputs"]["counts"]
                write_json(path, value)
            record["artifacts"]["result"]["sha256"] = sha(path)
    target = deepcopy(source)
    target["studies"] = []
    target["task"]["id"] = "new-matrix-task"
    target["task"]["summary"] = "新矩阵上的配对材料整理与表核对（合成桥接，不是真实科研验证）"
    target["task"]["facts"]["data_scale"] = 4
    target["task"]["inputs"] = {"counts": sha(artifacts / "new-input.json")}
    target["task"]["cases"][0]["graders"][0]["verifier"]["expected"].update(counts=new["matrix"]["values"], sample_ids=new["matrix"]["row_ids"])
    target["task"]["cases"][2]["graders"][0]["verifier"]["expected"]["input_snapshot"] = target["task"]["inputs"]["counts"]
    contract = {"format": CONTRACT, "input_key": "counts"}
    request = {"source_selection": source, "source_sha256": suite_digest(source),
               "source_study_sha256": suite_digest(source["studies"][1]["suite"]),
               "source_plan_sha256": source["studies"][1]["suite"]["task_selection"]["arms"]["with"],
               "contract": contract, "contract_sha256": suite_digest(contract),
               "source_material": {"path": "old-input.json", "sha256": source["task"]["inputs"]["counts"]},
               "target_material": {"path": "new-input.json", "sha256": target["task"]["inputs"]["counts"]}}
    return {"schema_version": 1, "intent": "choose", "task_selection": target, "evidence_bridge": request}, artifacts, scorers


def manufactured_bridge(context, artifacts, proposal, *, fail=False):
    """Fixture observations only. Real hosts must collect original target runs."""
    source = context["evidence_bridge"]["source_selection"]["studies"][1]
    protocol = proposal["proposed_protocol"]
    records = deepcopy(source["records"])
    for record in records:
        old = artifacts / record["artifacts"]["result"]["path"]
        path = artifacts / "target-bridge" / record["arm"] / old.name
        path.parent.mkdir(parents=True, exist_ok=True)
        case = next(c for c in protocol["suite"]["cases"] if c["id"] == record["case_id"])
        if record["arm"] == "with" and case["graders"][0]["verifier"]["kind"] == "json_fields":
            expected = deepcopy(case["graders"][0]["verifier"]["expected"])
            if fail:
                expected["paired"] = False
            write_json(path, expected)
        else:
            path.write_bytes(old.read_bytes())
        record.update(suite_sha256=protocol["lock"]["suite_sha256"], session_id="target-" + record["session_id"],
                      conditions=deepcopy(protocol["suite"]["conditions"]),
                      input_snapshot=deepcopy(protocol["required_input_snapshot"]))
        record["artifacts"]["result"] = {"path": path.relative_to(artifacts).as_posix(), "sha256": sha(path)}
    return {"protocol": deepcopy(protocol), "protocol_sha256": proposal["proposed_protocol_sha256"],
            "records": records, "cost_ledger": deepcopy(source["cost_ledger"])}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    output = Path(parser.parse_args().output)
    if output.exists():
        parser.error("Choose an absent directory; preserve original evidence")
    context, artifacts, scorers = fixture(output)
    prepared = plan_plugin_use(context, artifact_root=artifacts, verifier_root=scorers)
    write_plan(prepared, output / "proposal")
    write_json(output / "source-commitment.json", {"source_sha256": context["evidence_bridge"]["source_sha256"]})
    context["evidence_bridge"]["bridge_study"] = manufactured_bridge(context, artifacts, prepared["bridge"])
    observed = plan_plugin_use(context, artifact_root=artifacts, verifier_root=scorers)
    write_plan(observed, output / "observed")
    write_json(output / "context.json", context)
    print(observed["bridge"]["state"], observed["evidence_status"])
