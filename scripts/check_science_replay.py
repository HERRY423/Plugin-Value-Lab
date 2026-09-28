"""Explicit real PyDESeq2 acceptance on synthetic counts; no download/model calls."""
import argparse
import json
import os
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.core import load_json, write_json
from value_lab.pseudobulk import _equal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    rng = random.Random(20260928)
    design = {'format': 'pvl-pseudobulk-design-1', 'task_mode': 'fixed_method',
              'cell_type': 'synthetic', 'control': 'control', 'treatment': 'treated',
              'min_cells': 3, 'min_total_count': 10, 'backend_version': '0.5.4',
              'reference_workflow': 'Synthetic local runtime acceptance; not biological evidence'}
    data = {'format': 'pvl-cell-counts-1', 'genes': ['g' + str(i) for i in range(80)],
            'cells': [], 'provenance': {'synthetic': True, 'seed': 20260928}}
    base = [rng.randint(15, 100) for _ in data['genes']]
    for donor in range(4):
        for condition in ('control', 'treated'):
            sample = f'd{donor}-{condition}'
            for cell in range(3):
                counts = [[i, max(1, int(v * rng.lognormvariate(0, .25) *
                           (1.8 if condition == 'treated' and i < 15 else 1)))] for i, v in enumerate(base)]
                data['cells'].append({'id': sample + '-' + str(cell), 'sample': sample,
                    'donor': 'd' + str(donor), 'condition': condition, 'cell_type': 'synthetic', 'counts': counts})
    write_json(output / 'design.json', design)
    write_json(output / 'data.json', data)
    env = dict(os.environ)
    env.update({key: '1' for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')})
    env['PYTHONHASHSEED'] = '0'
    def run(name, command):
        process = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', timeout=240)
        (output / (name + '.stdout.log')).write_text(process.stdout, encoding='utf-8')
        (output / (name + '.stderr.log')).write_text(process.stderr, encoding='utf-8')
        if process.returncode:
            raise RuntimeError(name + ' failed; inspect retained logs')
        return json.loads(process.stdout)
    command = [sys.executable, '-I', str(ROOT / 'scripts/value_lab.py'), 'pseudobulk-reference',
               str(output / 'design.json'), str(output / 'data.json')]
    receipt = {'status': 'STARTED', 'synthetic': True, 'external_calls': 0}
    write_json(output / 'acceptance.json', receipt)
    try:
        first = run('fit-first', command + ['--output', str(output / 'reference-first')])
        second = run('fit-locked', command + ['--output', str(output / 'reference-locked'),
            '--environment-lock', str(output / 'reference-first/environment.lock.json'),
            '--environment-id', first['environment_sha256']])
        replay = run('replay-no-site', [sys.executable, '-S', str(ROOT / 'scripts/science_env.py'),
            'replay-reference', str(output / 'reference-first'), '--expected-id', first['artifact_sha256'],
            '--output', str(output / 'playback')])
        a, b = (load_json(output / name / 'reference.json') for name in ('reference-first', 'reference-locked'))
        agreed = _equal(a, b, 1e-7, 1e-6)
        if not agreed or replay['scientific_execution'] is not False:
            raise RuntimeError('Locked fit agreement or dependency-free replay failed')
        receipt.update(status='PASS', real_pydeseq2_fits=2, absolute_tolerance=1e-7, relative_tolerance=1e-6,
                       numerical_agreement=agreed, dependency_free_replay=True,
                       environment_sha256=first['environment_sha256'], artifact_sha256=first['artifact_sha256'],
                       biological_validity='NOT_TESTED', cross_platform_recompute='NOT_TESTED')
    except Exception:
        receipt.update(status='FAILED')
        write_json(output / 'acceptance.json', receipt)
        raise
    write_json(output / 'acceptance.json', receipt)
    print(json.dumps(receipt, ensure_ascii=True))


if __name__ == '__main__':
    main()
