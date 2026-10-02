"""Manufactured evidence-review workflow; no models, plugins or literature calls."""
import argparse
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from value_lab.core import demo_suite, demo_records, suite_digest, write_json
from value_lab.plugin_combinations import plan, BURDEN
from value_lab.workflow import plan_plugin_use, write_plan


def specification(compare_orders=True):
    suite = demo_suite()
    suite['cases'] = suite['cases'][:2]
    suite['policy']['min_clusters'] = 2
    for case in suite['cases']:
        case['prompt'] = 'Manufactured evidence review: recover the fixed fixture source and check its identifier. No scientific claim.'
        case['graders'] = [{'id': 'checked', 'type': 'json_equals', 'path': 'source_and_identifier_checked',
                           'value': True, 'weight': 1, 'dimension': 'outcome', 'critical': False}]
    return {'suite': suite, 'stage': {'id': 'evidence-review', 'summary': '制造案例：检索后核对来源标识，观察重复工作和错误传播。'},
            'inputs': {'public_fixture': suite_digest('manufactured source snapshot')},
            'plugins': [{'id': 'retriever', 'version': 'fixture-1', 'sha256': 'a' * 64, 'capabilities': ['retrieve source']},
                        {'id': 'checker', 'version': 'fixture-1', 'sha256': 'b' * 64, 'capabilities': ['check source identifier']}],
            'rationale': '检索结果传给核对步骤，存在交接依赖；只测试这一对，不枚举其他插件。',
            'policy': {'quality_floor': .8, 'success_floor': 1, 'max_mean_cost_usd': .1,
                       'max_mean_duration_seconds': 30, 'interaction_margin': .05},
            'compare_orders': compare_orders, 'seed': 20261001}


def observations(design, mode='complementary'):
    rules = {'complementary': {'AB', 'BA'}, 'substitutes': {'A', 'B', 'AB', 'BA'},
             'interference': {'A', 'B'}, 'order': {'AB'},
             'baseline': {'BASELINE', 'A', 'B', 'AB', 'BA'}}
    template = demo_records(design['spec']['suite'])[0]
    arms = {a['id']: a for a in design['arms']}
    rows = []
    for assignment in design['assignments']:
        arm = assignment['arm']
        record = deepcopy(template)
        record.update(case_id=assignment['case_id'], repetition=assignment['repetition'],
                      arm='without' if arm == 'BASELINE' else 'with', plugin_loaded=arm != 'BASELINE',
                      session_id='SYNTHETIC-combination-' + str(assignment['execution_index']),
                      output='{"source_and_identifier_checked":' + ('true' if arm in rules[mode] else 'false') + '}',
                      human_intervals=[], cost={'model_usd': .01 * (1 + len(arms[arm]['exposure']['plugins'])),
                                                'tool_usd': 0, 'human_minutes': 0})
        rows.append({**assignment, 'exposure': deepcopy(arms[arm]['exposure']), 'record': record,
                     'additional_cost_usd': {k: 0 for k in BURDEN}, 'diagnostics': {'assessed': [], 'events': []}})
    return {'format': 'pvl-plugin-combination-observations-1', 'design_sha256': suite_digest(design), 'runs': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    design = plan(specification())
    planning = {'schema_version': 1, 'intent': 'choose', 'plugin_combination': {'action': 'plan', 'spec': design['spec']}}
    write_json(root / 'plan-context.json', planning)
    write_json(root / 'design.json', design)
    write_json(root / 'commitment.json', {'design_sha256': suite_digest(design)})
    for mode in ('complementary', 'substitutes', 'interference', 'order', 'baseline', 'missing'):
        obs = observations(design, 'complementary' if mode == 'missing' else mode)
        if mode == 'missing':
            obs['runs'].pop()
        context = {'schema_version': 1, 'intent': 'choose', 'plugin_combination': {
            'action': 'analyze', 'design': design, 'expected_id': suite_digest(design), 'observations': obs}}
        write_json(root / (mode + '-context.json'), context)
        write_plan(plan_plugin_use(context), root / mode)
    print('SIMULATION_ONLY: six scenarios written; real observations=0; model calls=0')


if __name__ == '__main__':
    main()
