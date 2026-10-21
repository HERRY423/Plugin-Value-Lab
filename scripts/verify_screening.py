"""Retain a zero-network synthetic L0/L1 demonstration; not real plugin evidence."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import load_json
from value_lab.request_budget import RequestBudget
from value_lab.screening import CHECKS, screen


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    plugins = [{'id': 'SYNTHETIC_FIXTURE_ONLY', 'version': 'fixture-v1', 'sha256': 'a' * 64,
                'checks': {k: {'status': 'pass', 'evidence_ref': 'SYNTHETIC_CHECK_ONLY'} for k in CHECKS}}]
    tasks = [{'id': f'synthetic-{i}', 'kind': kind, 'input': 'synthetic input',
              'baseline': 'fixture without plugin', 'rubric': 'synthetic fixture score'}
             for i, kind in enumerate(('positive', 'failure', 'boundary'))]
    write(root / 'plugins.json', plugins)
    write(root / 'tasks.json', tasks)
    unknown = screen(root / 'plugins.json', root / 'tasks.json', root / 'insufficient')
    adapter = root / 'offline_adapter.py'
    adapter.write_text('''import json,sys
r=json.load(sys.stdin)
print(json.dumps(dict(status='completed', score=.8 if r['arm']=='with' else .5,
critical_failure=False, evidence_ref='SYNTHETIC_OUTPUT_ONLY', scoring_ref='SYNTHETIC_SCORE',
cost_micros=0, cost_ref='OFFLINE_ZERO_API_COST', correction_seconds=0)))
''', encoding='utf-8')
    ledger = root / 'fixture-budget.sqlite'
    RequestBudget.create(ledger, 'offline-fixture-only', 100000, 1000000,
                         history=[], coverage_ref='new offline synthetic demonstration with no prior calls')
    write(root / 'settings.json', {'runner': {'argv': [sys.executable, str(adapter)],
        'files': [str(adapter)], 'timeout_seconds': 5, 'upper_micros': 0, 'bound_ref': 'OFFLINE_FIXTURE_ONLY',
        'ledger': str(ledger), 'task_id': 'offline-fixture-only'}})
    advance = screen(root / 'plugins.json', root / 'tasks.json', root / 'advance', settings_path=root / 'settings.json')
    bundle = load_json(root / 'advance/runs.json')
    for row in bundle['runs']:
        row['score'] = .5
    write(root / 'synthetic-no-gain.json', bundle)
    stop = screen(root / 'plugins.json', root / 'tasks.json', root / 'stop',
                  frozen_path=root / 'advance/frozen-plan.json', results_path=root / 'synthetic-no-gain.json')
    summary = {'evidence': 'SYNTHETIC_ENGINEERING_ONLY', 'model_calls': 0, 'api_cost_micros': 0,
               'native_host_acceptance': 'NOT_RUN', 'real_plugin_value': 'NOT_ASSESSED',
               'statuses': [unknown['status'], advance['status'], stop['status']],
               'actual_local_adapter_processes': advance['observed_runs'],
               'cards': [r['use_card'] for r in (unknown, advance, stop)]}
    assert summary['statuses'] == ['INSUFFICIENT_EVIDENCE', 'ADVANCE_PILOT', 'STOP']
    assert summary['actual_local_adapter_processes'] == 12
    write(root / 'verification.json', summary)
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
