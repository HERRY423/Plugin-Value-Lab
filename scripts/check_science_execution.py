"""Required real sandbox + PyDESeq2 covariate refit acceptance; never a mock pass."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.artifacts import sha
from value_lab.core import load_json, suite_digest, write_json
from value_lab.native_session import run_offline
from value_lab.science_execution import capture_runtime, command, execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--runtime', required=True)
    args = parser.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    receipt = {'status': 'STARTED', 'synthetic': True, 'real_backend_fits': 0,
               'independent_expert_validation': 'NOT_ESTABLISHED', 'cross_host_reconstruction': 'NOT_ESTABLISHED'}
    write_json(root / 'acceptance.json', receipt)
    try:
        public, spec, submitted = [root / n for n in ('public', 'spec', 'submitted')]
        for p in (public, spec, submitted):
            p.mkdir()
        for file in (ROOT / 'value_lab').glob('*.py'):
            target = public / 'value_lab' / file.name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(file.read_bytes())
        rng = random.Random(29092026)
        design = {'format': 'pvl-pseudobulk-design-2', 'task_mode': 'fixed_method', 'cell_type': 'synthetic',
                  'control': 'control', 'treatment': 'treated', 'min_cells': 3, 'min_total_count': 10,
                  'backend_version': '0.5.4', 'reference_workflow': 'Synthetic software acceptance only',
                  'covariates': {'dose': {'kind': 'continuous'}, 'batch': {'kind': 'categorical', 'levels': ['A', 'B']}}}
        data = {'format': 'pvl-cell-counts-1', 'genes': ['g' + str(i) for i in range(80)],
                'cells': [], 'sample_covariates': {}, 'provenance': {'synthetic': True, 'seed': 29092026}}
        bases = [rng.randint(20, 100) for _ in data['genes']]
        for donor in range(6):
            for condition in ('control', 'treated'):
                sample = f'd{donor}-{condition}'
                data['sample_covariates'][sample] = {'dose': rng.uniform(0, 10), 'batch': 'A' if (donor + (condition == 'treated')) % 2 else 'B'}
                for cell in range(3):
                    counts = [[i, max(1, int(v * rng.lognormvariate(0, .25) * (1.8 if condition == 'treated' and i < 15 else 1)))] for i, v in enumerate(bases)]
                    data['cells'].append({'id': sample + '-' + str(cell), 'sample': sample, 'donor': 'd' + str(donor),
                                          'condition': condition, 'cell_type': 'synthetic', 'counts': counts})
        write_json(public / 'design.json', design)
        write_json(public / 'data.json', data)
        script = ('import sys,json\nfrom pathlib import Path\nsys.path.insert(0,"/inputs")\n'
                  'from value_lab.pseudobulk import fit_reference\n'
                  'd=json.loads(Path("/inputs/design.json").read_text())\n'
                  'x=json.loads(Path("/inputs/data.json").read_text())\n'
                  'r=fit_reference(d,x)\n'
                  'Path("/output/result.json").write_text(json.dumps(r,allow_nan=False),encoding="utf-8")\n')
        (public / 'pipeline.py').write_text(script, encoding='utf-8')
        lock = capture_runtime(['pydeseq2'], root / 'freeze', runtime=args.runtime)
        write_json(spec / 'environment.json', lock)
        files = {p.relative_to(public).as_posix(): sha(p) for p in public.rglob('*') if p.is_file()}
        first = run_offline(public, list(files), command('/runtime/bin/python', '/inputs/pipeline.py'), root / 'initial-fit',
                            runtime=args.runtime, memory_mb=4096, timeout_seconds=300)
        if first['status'] != 'COMPLETED':
            raise RuntimeError('Initial PyDESeq2 fit failed; inspect retained logs')
        receipt['real_backend_fits'] += 1
        (submitted / 'result.json').write_bytes((root / 'initial-fit/artifacts/result.json').read_bytes())
        manifest = {'format': 'pvl-science-execution-1', 'files': files, 'entrypoint': 'pipeline.py', 'arguments': [],
                    'environment': {'path': 'environment.json', 'sha256': sha(spec / 'environment.json')},
                    'timeout_seconds': 300, 'memory_mb': 4096,
                    'outputs': [{'path': 'result.json', 'submitted': {'path': 'result.json', 'sha256': sha(submitted / 'result.json')},
                                 'comparison': 'pseudobulk', 'absolute': 1e-7, 'relative': 1e-6}]}
        def run(name, m):
            write_json(spec / (name + '.json'), m)
            return execute(spec / (name + '.json'), suite_digest(m), public, submitted, root / name, runtime=args.runtime)
        agreed = run('matched', manifest)
        if agreed['status'] != 'REPRODUCED':
            raise RuntimeError('Locked recomputation did not reproduce: ' + agreed['status'])
        receipt['real_backend_fits'] += 1
        # A changed submitted answer must not be repaired by copying it into the guest.
        altered = load_json(submitted / 'result.json')
        altered['results'][0]['effect'] += 1
        write_json(submitted / 'altered.json', altered)
        wrong = deepcopy(manifest)
        wrong['outputs'][0]['submitted'] = {'path': 'altered.json', 'sha256': sha(submitted / 'altered.json')}
        mismatch = run('mismatch', wrong)
        if mismatch['status'] != 'RESULT_MISMATCH':
            raise RuntimeError('Altered submitted answer was not detected')
        receipt['real_backend_fits'] += 1
        failed = deepcopy(manifest)
        (public / 'failure.py').write_text('raise RuntimeError("intentional failure")\n')
        failed['files']['failure.py'] = sha(public / 'failure.py')
        failed['entrypoint'] = 'failure.py'
        failure = run('failed-program', failed)
        if failure['status'] != 'EXECUTION_FAILED' or failure['passed'] is not None:
            raise RuntimeError('Execution failure incorrectly classified')
        receipt.update(status='PASS', matched=agreed['status'], altered_submission=mismatch['status'],
                       failed_program=failure['status'], environment_check=agreed['environment_check'],
                       covariates=['dose', 'batch'], independent_donors=6, samples=12, genes=80,
                       environment_sha256=suite_digest(lock), manifest_sha256=suite_digest(manifest),
                       same_host_only=True, no_model_calls=True)
    except Exception as exc:
        receipt.update(status='FAILED', error=str(exc))
        write_json(root / 'acceptance.json', receipt)
        raise
    write_json(root / 'acceptance.json', receipt)
    print(json.dumps(receipt, ensure_ascii=True))


if __name__ == '__main__':
    main()
