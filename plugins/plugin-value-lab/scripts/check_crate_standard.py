"""Independent pinned profile check plus a deliberately invalid negative control."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess


def check(crate, output, validator):
    root = Path(output).absolute()
    root.mkdir(parents=True, exist_ok=False)
    source = Path(crate).absolute()
    bad = root / 'missing-main-workflow'
    shutil.copytree(source, bad)
    path = bad / 'ro-crate-metadata.json'
    graph = json.loads(path.read_text(encoding='utf-8'))
    next(e for e in graph['@graph'] if e['@id'] == './').pop('mainEntity')
    path.write_text(json.dumps(graph), encoding='utf-8')
    receipts = {}
    for name, directory in [('valid', source), ('invalid', bad)]:
        report_path = root / (name + '.json')
        result = subprocess.run([validator, 'validate', '--no-auto-profile', '-p', 'workflow-run-crate-0.5',
                                 '-l', 'required', '--cache-path', str(root / 'http-cache'),
                                 '-f', 'json', '-o', str(report_path), str(directory)],
                                capture_output=True, text=True, timeout=180)
        (root / (name + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
        # Validator 0.11.2's CLI wraps long strings when rendering JSON to file.
        # Accept those literal newlines, then retain normalized machine JSON.
        report = json.loads(report_path.read_text(encoding='utf-8'), strict=False)
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        receipts[name] = {'exit_code': result.returncode, 'passed': report['passed'],
                          'statistics': report['statistics']}
        if name == 'valid':
            assert result.returncode == 0 and report['passed'] and not report['issues'], report['issues']
            assert report['statistics']['total_passed_checks'] >= 50
            assert report['statistics']['total_failed_checks'] == 0
            assert report['validation_settings']['skip_checks'] == []
        else:
            assert result.returncode != 0 and not report['passed']
            assert any('main' in i['message'].lower() and 'workflow' in i['message'].lower() for i in report['issues'])
    receipt = {'status': 'PASS', 'profile': 'workflow-run-crate-0.5', 'severity': 'REQUIRED',
               'validator': 'roc-validator==0.11.2; pyshacl==0.30.1', 'checks': receipts,
               'scientific_validity': 'NOT_ESTABLISHED'}
    (root / 'acceptance.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--crate', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--validator', default='rocrate-validator')
    args = p.parse_args()
    print(json.dumps(check(args.crate, args.output, args.validator)))
