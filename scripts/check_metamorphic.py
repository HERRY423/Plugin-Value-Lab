"""Inspectable stdlib calibration: correct, order-sensitive and constant-output programs."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.core import demo_suite, demo_records, evaluate, load_json, write_json, suite_digest
from value_lab.artifacts import sha
from value_lab.declarative import dump_evals
from value_lab.metamorphic import prepare, collect
from value_lab.report import write_reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    design = load_json(ROOT / 'examples/metamorphic/column-sum.design.json')
    write_json(root / 'private/design.json', design)
    manifest = prepare(design, root / 'inputs')
    collected = {}
    for fault in ('none', 'first-row', 'constant-zero'):
        results = root / fault / 'results'
        results.mkdir(parents=True)
        for identity, entry in manifest['inputs'].items():
            subprocess.run([sys.executable, '-S', str(ROOT / 'examples/metamorphic/column-sum.py'),
                str(root / 'inputs' / entry['path']), str(results / (identity + '.result.json')),
                '--fault', fault], check=True, capture_output=True, timeout=15)
        collected[fault] = collect(design, results, root / fault / 'collected')
    assert collected['none']['passed'] is True
    assert collected['first-row']['passed'] is False
    assert collected['constant-zero']['passed'] is True  # demonstrate the oracle limitation
    grader = {'id': 'metamorphic', 'type': 'metamorphic', 'artifact': 'result', 'dimension': 'outcome',
              'critical': True, 'weight': 1, 'verifier': {'design': {'path': 'design.json', 'sha256': sha(root / 'private/design.json')}}}
    anchor = {'id': 'baseline-oracle', 'type': 'artifact', 'artifact': 'result', 'dimension': 'outcome',
              'critical': True, 'weight': 1, 'verifier': {'kind': 'json_fields',
              'expected': {'runs.0.output': {'row_ids': ['sum'], 'columns': ['gene-x', 'gene-y'], 'values': [[12, 21]]}}}}
    suite = demo_suite()
    suite.update(id='metamorphic-calibration', runs_per_case=1)
    suite['cases'] = [{'id': fault, 'cluster': 'column-sum', 'kind': 'task',
                       'prompt': 'Synthetic adapter calibration: ' + fault,
                       'graders': [deepcopy(grader), deepcopy(anchor)]} for fault in collected]
    templates = demo_records(demo_suite())[:2]
    records = []
    for case in suite['cases']:
        for template in templates:
            record = deepcopy(template)
            record.update(case_id=case['id'], suite_sha256=suite_digest(suite),
                          session_id='SYNTHETIC-' + case['id'] + '-' + record['arm'])
            records.append(record)
    for record in records:
        fault = record['case_id'] if record['arm'] == 'with' else 'none'
        relative = fault + '/collected/observations.json'
        record['artifacts'] = {'result': {'path': relative, 'sha256': sha(root / relative)}}
    report = evaluate(suite, records, artifact_root=root, verifier_root=root / 'private')
    states = {case['id']: next(run['task_outcome']['passed'] for run in case['runs'] if run['arm'] == 'with')
              for case in report['cases']}
    assert states == {'none': True, 'first-row': False, 'constant-zero': False}, states
    write_json(root / 'suite.json', suite)
    dump_evals(suite, root / 'evals')
    write_json(root / 'assessment.json', report)
    reports = write_reports(report, root / 'report')
    receipt = {'status': 'PASS', 'synthetic': True, 'model_calls': 0, 'adapter_executions': 12,
               'task_correctness': states, 'relations': {k: v['passed'] for k, v in collected.items()},
               'reports': reports, 'independent_validation': False}
    write_json(root / 'acceptance.json', receipt)
    print(json.dumps(receipt, ensure_ascii=True))


if __name__ == '__main__':
    main()
