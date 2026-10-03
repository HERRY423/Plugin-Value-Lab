"""Synthetic risk-controlled planning through the existing task-selection entry."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from value_lab.core import suite_digest
from value_lab.task_selection import select_task_plan
from value_lab.workflow import plan_plugin_use, write_plan
from scripts.check_risk_acquisition import protocol


def run(output):
    # Reuse the existing declared task/catalog example; no new executable provider.
    import importlib.util
    spec = importlib.util.spec_from_file_location("task_acquisition_example", Path(__file__).with_name("acquisition_demo.py"))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    source.mkdir()
    original, *_ = fixture.fixture(source)
    selection = original["task_selection"]
    catalog = select_task_plan(selection)
    design = protocol(3)
    design.update(catalog_sha256=catalog["catalog_sha256"], task_sha256=suite_digest(selection["task"]))
    for candidate, plan in zip(design["candidates"], catalog["plans"]):
        candidate["plan_sha256"] = plan["plan_sha256"]
    context = {"schema_version": 1, "intent": "choose", "task_selection": selection,
               "risk_acquisition": {"protocol": design, "protocol_sha256": suite_digest(design), "batches": []}}
    (output / "context.json").write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "protocol.json").write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "protocol.sha256").write_text(suite_digest(design) + "\n", encoding="utf-8")
    plan = plan_plugin_use(context)
    write_plan(plan, output / "plan")
    return {"state": plan["risk_acquisition"]["state"], "context": str(output / "context.json"), "evidence": "SIMULATION_ONLY", "execution_authorized": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    print(json.dumps(run(parser.parse_args().output), indent=2))
