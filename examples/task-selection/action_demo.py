"""Four-candidate synthetic planning demo; example losses are not user preferences."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from value_lab.core import suite_digest, write_json
from value_lab.task_selection import select_task_plan
from value_lab.workflow import plan_plugin_use, write_plan
from scripts.check_risk_acquisition import protocol


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('action_demo_source', Path(__file__).with_name('acquisition_demo.py'))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    original, *_ = fixture.fixture(output / 'source')
    selection = original['task_selection']
    catalog = select_task_plan(selection)
    baseline = next(p for p in catalog['plans'] if all(c['kind'] == 'native' for c in p['manifest']['components']))
    candidates = [baseline] + [p for p in catalog['plans'] if any(c['kind'] == 'plugin' for c in p['manifest']['components'])][:3]
    design = protocol(4, 'round_robin')
    design.update(format='pvl-risk-acquisition-2', catalog_sha256=catalog['catalog_sha256'],
                  task_sha256=suite_digest(selection['task']), rotation_seed=42, batch_units=4,
                  max_units_per_candidate=32, budget_micros=1000000)
    design['assumptions']['no_order_or_carryover'] = True
    design['utility_contract'] = {'measure': 'equal_family_quality', 'scale': [0, 1], 'failure': 0,
                                  'note': 'Synthetic independent-family utility illustration, no execution'}
    for candidate, plan in zip(design['candidates'], candidates):
        candidate['plan_sha256'] = plan['plan_sha256']
    design['decision_policy'] = json.loads((ROOT / 'examples/action-policy.json').read_text(encoding='utf-8'))
    context = {'schema_version': 1, 'intent': 'choose', 'task_selection': selection,
               'risk_acquisition': {'protocol': design, 'protocol_sha256': suite_digest(design), 'batches': []}}
    write_json(output / 'context.json', context)
    write_json(output / 'protocol.json', design)
    write_plan(plan_plugin_use(context), output / 'plan')
    return {'output': str(output), 'candidate_count': 4, 'evidence': 'SIMULATION_ONLY', 'execution_authorized': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    print(json.dumps(run(parser.parse_args().output), ensure_ascii=False, indent=2))
