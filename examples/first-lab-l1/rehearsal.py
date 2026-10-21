"""Offline installed-wheel walkthrough using synthetic receipts, not plugin runs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    import value_lab
    if not Path(value_lab.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise SystemExit('Use the packet virtual environment; source-tree imports are not an install test.')
    fixture = root / 'synthetic-identity.txt'
    fixture.write_text('SYNTHETIC ONLY. No plugin executed. No participant data.', encoding='utf-8')
    plugins = [{'id': 'SYNTHETIC_REHEARSAL_ONLY', 'version': 'fixture-v1',
        'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(),
        'checks': {key: {'status': 'pass', 'evidence_ref': 'SYNTHETIC_ASSERTION_ONLY'}
                   for key in ('declaration', 'permissions', 'egress', 'license', 'identity')}}]
    tasks = [{'id': f'T{i+1}', 'kind': kind, 'input': 'SYNTHETIC_INPUT', 'rubric': 'SYNTHETIC_SCORE',
              'baseline': 'SYNTHETIC_NO_MODEL_OR_PLUGIN'} for i, kind in enumerate(('positive', 'failure', 'boundary', 'positive'))]
    save(root / 'plugins.json', plugins)
    save(root / 'tasks.json', tasks)
    commands = []
    def cli(*parts):
        command = [sys.executable, '-I', '-m', 'value_lab.easy_cli', 'screen', '--plugins', str(root / 'plugins.json'),
                   '--tasks', str(root / 'tasks.json'), *map(str, parts), '--json']
        process = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        commands.append({'command': ['python', '-I', '-m', 'value_lab.easy_cli', 'screen'], 'exit_code': process.returncode})
        if process.returncode != 0:
            raise RuntimeError(process.stderr or process.stdout)
        return json.loads(process.stdout)
    initial = cli('--output', root / 'frozen')
    assert initial['status'] == 'INSUFFICIENT_EVIDENCE' and initial['observed_runs'] == 0
    helper = Path(__file__).resolve().parent / 'make_record.py'
    subprocess.run([sys.executable, '-I', str(helper), str(root / 'frozen/frozen-plan.json'), str(root / 'paired.json')], check=True)
    paired = json.loads((root / 'paired.json').read_text(encoding='utf-8'))
    assert len(paired['runs']) == 16 and all(row['status'] == 'not_run' and row['score'] is None for row in paired['runs'])
    unfilled = cli('--frozen', root / 'frozen/frozen-plan.json', '--results', root / 'paired.json', '--output', root / 'unfilled')
    assert unfilled['status'] == 'INSUFFICIENT_EVIDENCE'
    # Simulated receipts only: deliberately no advantage, with failed attempts retained.
    for row in paired['runs']:
        failed = row['task_id'] == 'T2' and row['repeat'] == 0
        row.update(status='failed' if failed else 'completed', score=0 if failed else .5,
                   critical_failure=False, evidence_ref='SYNTHETIC_OUTPUT_NOT_A_REAL_RUN',
                   scoring_ref='SYNTHETIC_PREDEFINED_SCORE', cost_micros=0,
                   cost_ref='NO_API_CALLS_IN_REHEARSAL', correction_seconds=0)
    save(root / 'synthetic-complete.json', paired)
    complete = cli('--frozen', root / 'frozen/frozen-plan.json', '--results', root / 'synthetic-complete.json', '--output', root / 'complete')
    assert complete['status'] == 'STOP' and complete['observed_runs'] == 16
    retained = json.loads((root / 'complete/runs.json').read_text(encoding='utf-8'))
    assert sum(r['status'] == 'failed' for r in retained['runs']) == 2
    paired['runs'][0]['cost_micros'] = None
    save(root / 'synthetic-unknown-cost.json', paired)
    unknown = cli('--frozen', root / 'frozen/frozen-plan.json', '--results', root / 'synthetic-unknown-cost.json', '--output', root / 'unknown-cost')
    assert unknown['status'] == 'INSUFFICIENT_EVIDENCE' and unknown['total_cost_micros'] is None
    report = {'status': 'REHEARSAL_PASS', 'evidence': 'LOCAL_SYNTHETIC_INSTALLED_WHEEL_ONLY',
              'python_version': sys.version.split()[0], 'source_tree_import': False,
              'model_calls': 0, 'api_cost_micros': 0, 'real_plugin_runs': 0,
              'external_laboratories_completed': 0, 'human_first_use_measured': False,
              'simulated_receipts': 16, 'retained_simulated_failures': 2,
              'outcomes': [r['status'] for r in (initial, unfilled, complete, unknown)],
              'commands': commands}
    save(root / 'walkthrough.json', report)
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
