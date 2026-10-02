"""Synthetic burden views through the unchanged planner; no external calls."""
import argparse
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from value_lab.core import suite_digest, write_json
from value_lab.plugin_combinations import plan
from value_lab.workflow import plan_plugin_use, write_plan

loader = importlib.util.spec_from_file_location('pair_example', Path(__file__).with_name('demo.py'))
example = importlib.util.module_from_spec(loader)
loader.loader.exec_module(example)


def context_samples(design, obs, fractions):
    conditions = design['spec']['suite']['conditions']
    return {'format': 'pvl-context-observations-1', 'design_sha256': suite_digest(design),
            'measurement': {'host': conditions['host'], 'model': conditions['model'],
                            'host_version': 'synthetic-fixture-1', 'source': 'manufactured; not host telemetry',
                            'sampling': 'each_main_agent_request', 'context_window_tokens': 100000},
            'runs': [{k: row[k] for k in ('case_id', 'repetition', 'arm')} | {
                'session_id': row['record']['session_id'], 'record_sha256': suite_digest(row['record']),
                'coverage': 'complete', 'expected_samples': 2,
                'samples': [{'request_index': 1, 'input_tokens': 1000},
                            {'request_index': 2, 'input_tokens': round(fractions[row['arm']] * 100000)}]}
                     for row in obs['runs']]}


def request(mode='dominance'):
    design = plan(example.specification())
    obs = example.observations(design, 'substitutes')
    metrics = {'BASELINE': (.1, .01, 5), 'A': (.2, .02, 8), 'B': (.4, .03, 12),
               'AB': (.5, .04, 15), 'BA': (.6, .05, 18)}
    if mode == 'tradeoff':
        metrics['B'] = (.1, .03, 6)
    if mode == 'equal':
        metrics['B'] = metrics['A']
    for row in obs['runs']:
        _, cost, duration = metrics[row['arm']]
        row['record']['cost']['model_usd'] = cost
        row['record']['duration_seconds'] = duration
    burden = context_samples(design, obs, {a: m[0] for a, m in metrics.items()})
    if mode == 'missing':
        burden['runs'] = [r for r in burden['runs'] if r['arm'] != 'B']
    return {'schema_version': 1, 'intent': 'choose', 'plugin_combination': {
        'action': 'analyze', 'design': design, 'expected_id': suite_digest(design),
        'observations': obs, 'burden_observations': burden}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    target = Path(args.output)
    target.mkdir(parents=True, exist_ok=False)
    for mode in ('dominance', 'tradeoff', 'equal', 'missing'):
        context = request(mode)
        write_json(target / (mode + '-context.json'), context)
        write_plan(plan_plugin_use(context), target / mode)
    print('SIMULATION_ONLY: four burden views; real host observations=0; model calls=0')


if __name__ == '__main__':
    main()
