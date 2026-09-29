"""Required native workflow acceptance; missing engines fail rather than skip."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
# Do not let scripts/value_lab.py shadow the installed value_lab package.
sys.path = [entry for entry in sys.path if Path(entry or '.').resolve() != ROOT / 'scripts']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', choices=['snakemake', 'nextflow', 'all'], default='all')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    root = args.output.absolute()
    root.mkdir(parents=True, exist_ok=False)
    receipt = {'synthetic': True, 'non_author_participants': 0, 'scientific_validity': 'NOT_ESTABLISHED', 'steps': []}

    def call(name, command, cwd):
        start = time.perf_counter()
        run = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=300)
        (root / (name + '.stdout')).write_text(run.stdout, encoding='utf-8')
        (root / (name + '.stderr')).write_text(run.stderr, encoding='utf-8')
        receipt['steps'].append({'name': name, 'exit_code': run.returncode, 'seconds': round(time.perf_counter()-start, 3)})
        if run.returncode:
            raise RuntimeError(f'{name} failed; see preserved logs')
        return run.stdout.strip()

    try:
        import anndata as ad
        import numpy as np
        from value_lab.sdk import verify_run
        for engine in (['snakemake', 'nextflow'] if args.engine == 'all' else [args.engine]):
            executable = shutil.which(engine)
            if not executable:
                raise RuntimeError(f'{engine} is required, but absent from PATH')
            example = root / engine
            shutil.copytree(ROOT / 'examples/workflow-integration', example)
            receipt[engine + '_version'] = call(engine + '-version', [executable, '-version' if engine == 'nextflow' else '--version'], example)
            call(engine + '-fixture', [sys.executable, str(example / 'generate_fixture.py'), '--output', str(example / 'counts.h5ad')], example)
            command = ([executable, '--snakefile', 'Snakefile', '--cores', '1', '--keep-incomplete'] if engine == 'snakemake'
                       else [executable, 'run', 'main.nf', '--input', 'counts.h5ad', '--settings', 'settings.json', '--outdir', 'nextflow-results'])
            call(engine + '-run', command, example)
            output = example / ('snakemake-result' if engine == 'snakemake' else 'nextflow-results/result')
            result = verify_run(output)
            counts = ad.read_h5ad(result.counts)
            assert counts.shape == (6, 2), counts.shape
            np.testing.assert_array_equal(counts.X, np.tile([78, 36], (6, 1)))
            call(engine + '-resume', command + (['-resume'] if engine == 'nextflow' else []), example)
            verify_run(output, expected_id=result.commitment)
            receipt[engine] = {'status': 'PASS', 'output_shape': [6, 2], 'exact_counts_match': True,
                               'rerun_preserved_commitment': True, 'commitment': result.commitment}
        receipt['status'] = 'PASS'
    except Exception as exc:
        receipt.update(status='FAIL', error=str(exc))
        raise
    finally:
        (root / 'acceptance.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
