"""Synthetic prospective evidence acquisition. No models, plugins or paid calls."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("selection_demo", Path(__file__).with_name("demo.py"))
selection_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection_demo)
from value_lab.core import suite_digest, write_json
from value_lab.evidence_acquisition import FORMAT, RULE, STOP
from value_lab.workflow import plan_plugin_use, write_plan


def fixture(root, *, synthetic=True):
    context, artifacts, scorers = selection_demo.fixture(root, synthetic=synthetic)
    original = context["task_selection"]["studies"]
    checks = []
    for index, study in enumerate(original):
        suite = deepcopy(study["suite"])
        checks.append({"id": f"confirm-{index}", "phase": "confirmation", "suite": suite,
                       "inputs": deepcopy(context["task_selection"]["task"]["inputs"]),
                       "decision_case_ids": [c["id"] for c in suite["cases"]], "cost_upper_bound_usd": 2})
        screen = deepcopy(suite)
        screen["id"] = f"screen-fixture-{index}"
        screen["cases"] = [
            {"id": "paired-boundary", "cluster": "paired-design", "kind": "task", "prompt": "Manufactured screening input: paired design boundary.",
             "graders": [{"id": "paired", "type": "contains", "value": "PAIRED_OK", "dimension": "outcome", "weight": 1, "critical": True}]},
            {"id": "screen-negative", "cluster": "negative-control", "kind": "negative", "prompt": "Manufactured screening input: retain the no-inference control.",
             "graders": [{"id": "control", "type": "contains", "value": "CONTROL_OK", "dimension": "outcome", "weight": 1, "critical": True}]}]
        checks.append({"id": f"screen-{index}", "phase": "screening", "suite": screen,
                       "inputs": {"screening_dataset": "a" * 64}, "decision_case_ids": [c["id"] for c in screen["cases"]],
                       "cost_upper_bound_usd": 0.1})
    context["task_selection"]["studies"] = []
    protocol = {"format": FORMAT, "catalog_sha256": original[0]["suite"]["task_selection"]["catalog_sha256"],
                "selection_rule": RULE, "stopping_rule": STOP, "budget": {"max_usd": 10, "max_batches": 10}, "checks": checks}
    context["evidence_acquisition"] = {"protocol": protocol, "protocol_sha256": suite_digest(protocol), "batches": []}
    return context, artifacts, scorers, original


def manufactured_result(batch, original, context):
    """Only a fixture recorder. Production observations must come from actual runs."""
    phase, index = batch["check_id"].split("-")
    index = int(index)
    source = original[index]
    check = next(c for c in context["evidence_acquisition"]["protocol"]["checks"] if c["id"] == batch["check_id"])
    records = []
    if phase == "confirm":
        records = deepcopy(source["records"])
    else:
        for arm in ("with", "without"):
            template = next(r for r in source["records"] if r["arm"] == arm)
            # Only the manufactured partial-plugin plan survives the design gate.
            passed = index == 1 and arm == "with"
            for case in batch["suite"]["cases"]:
                record = deepcopy(template)
                record.pop("artifacts", None)
                record.update(case_id=case["id"], output=("PAIRED_OK CONTROL_OK" if passed else "CONTROL_OK"))
                records.append(record)
    for r in records:
        r.update(suite_sha256=batch["lock"]["suite_sha256"], input_snapshot=deepcopy(check["inputs"]),
                 session_id=f"fixture-{batch['check_id']}-{r['arm']}-{r['case_id']}")
    return {"records": records, "cost_ledger": deepcopy(source["cost_ledger"])}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    output = Path(parser.parse_args().output)
    if output.exists():
        parser.error("Keep earlier evidence; choose an absent output directory")
    context, artifacts, scorers, original = fixture(output)
    trajectory = []
    for step in range(12):
        plan = plan_plugin_use(context, artifact_root=artifacts, verifier_root=scorers)
        result = plan["acquisition"]
        trajectory.append({"step": step, "state": result["state"], "next_choices": [b["check_id"] for b in result["next_batch_options"]]})
        if not result["next_batch_options"]:
            break
        batch = result["next_batch_options"][0]  # Explicit fixture choice among equally ranked options.
        context["evidence_acquisition"]["batches"].append({"plan": batch, "result": manufactured_result(batch, original, context)})
    write_json(output / "context.json", context)
    write_json(output / "trajectory.json", trajectory)
    write_plan(plan, output / "plan")
    print(result["state"], result["evidence_status"], result["planned_runs_started"])
