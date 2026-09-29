"""Offline acceptance of a built wheel, outside the source checkout.

Core uses a clean venv. Science inherits explicitly installed host dependencies.
Notebook acceptance starts a real kernel; workflow engines remain separate gates.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import venv

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    cases = []

    def call(name, command, *, cwd=output, expected=0, env=None):
        start = time.perf_counter()
        result = subprocess.run([str(x) for x in command], cwd=cwd, env=env,
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
        (output / (name + '.stdout')).write_text(result.stdout, encoding='utf-8')
        (output / (name + '.stderr')).write_text(result.stderr, encoding='utf-8')
        cases.append({'name': name, 'exit_code': result.returncode, 'expected': expected,
                      'seconds': round(time.perf_counter() - start, 3)})
        if result.returncode != expected:
            raise RuntimeError(f'{name}: exit {result.returncode}; see retained logs in {output}')
        return result.stdout

    receipt = {'format': 'pvl-usability-acceptance-1', 'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
               'tests': cases, 'non_author_participants': 0, 'human_first_use_time': None,
               'scientific_validity': 'NOT_ESTABLISHED',
               'native_nextflow': 'NOT_RUN', 'native_snakemake': 'NOT_RUN',
               'science_dependencies': 'Inherited from host; not a clean dependency-resolution test'}
    try:
        for name, inherited in [('core', False), ('science', True)]:
            directory = output / name
            venv.EnvBuilder(with_pip=True, system_site_packages=inherited).create(directory)
            binary = directory / ('Scripts' if os.name == 'nt' else 'bin')
            python = binary / ('python.exe' if os.name == 'nt' else 'python')
            pvl = binary / ('pvl.exe' if os.name == 'nt' else 'pvl')
            call(name + '-install', [python, '-m', 'pip', 'install', '--no-index', '--no-deps', '--force-reinstall', wheel])
            identity = json.loads(call(name + '-identity', [python, '-I', '-c',
                'import value_lab,json; print(json.dumps({"path":value_lab.__file__}))']))
            assert Path(identity['path']).is_relative_to(directory), identity
            if name == 'core':
                data = json.loads(call('installed-demo', [pvl, 'demo', '--output', output / 'demo', '--json']))
                assert data['status'] == 'DEMO_COMPLETE'
                json.loads(call('installed-module-verify', [python, '-I', '-m', 'value_lab', 'verify', output / 'demo', '--json']))
                missing = json.loads(call('missing-science', [pvl, 'inspect', 'missing.h5ad', '--json'], expected=2))
                assert missing['code'] == 'MISSING_DEPENDENCY'
            else:
                example = output / 'research workspace'
                shutil.copytree(ROOT / 'examples/workflow-integration', example)
                call('generate-fixture', [python, '-I', example / 'generate_fixture.py', '--output', example / 'counts.h5ad'], cwd=example)
                command = [pvl, 'aggregate', 'counts.h5ad', '--config', 'settings.json', '--output', 'cli-result', '--json']
                answer = json.loads(call('installed-aggregate', command, cwd=example))
                assert answer['status'] == 'COMPLETE'
                reused = json.loads(call('installed-reuse', command + ['--reuse'], cwd=example))
                assert reused['reused'] and answer['commitment'] == reused['commitment']
                call('expected-counts', [python, '-I', '-c',
                     'import anndata as a,numpy as n; x=a.read_h5ad("cli-result/aggregation/counts.h5ad"); '
                     'assert x.shape==(6,2); n.testing.assert_array_equal(x.X,n.tile([78,36],(6,1))); print("6 x 2 counts match")'], cwd=example)
                # Isolated kernel points to the installed wheel, not cwd/PYTHONPATH.
                kernels = output / 'jupyter/kernels/pvl-installed'
                kernels.mkdir(parents=True)
                (kernels / 'kernel.json').write_text(json.dumps({'argv': [str(python), '-I', '-m', 'ipykernel_launcher', '-f', '{connection_file}'],
                    'display_name': 'PVL installed wheel', 'language': 'python'}), encoding='utf-8')
                env = {**os.environ, 'JUPYTER_PATH': str(output / 'jupyter'), 'JUPYTER_RUNTIME_DIR': str(output / 'runtime'),
                       'IPYTHONDIR': str(output / 'ipython'), 'PYTHONIOENCODING': 'utf-8'}
                call('notebook-kernel', [python, '-I', '-c',
                    'import nbformat; from nbclient import NotebookClient; '
                    'n=nbformat.read("notebook.ipynb",as_version=4); nbformat.validate(n); '
                    'NotebookClient(n,timeout=120,kernel_name="pvl-installed").execute(); '
                    'assert all(c.execution_count is not None for c in n.cells if c.cell_type=="code"); '
                    'nbformat.write(n,"executed.ipynb"); print("All four cells executed in installed-wheel kernel")'], cwd=example, env=env)
                call('notebook-verify', [pvl, 'verify', 'notebook-result', '--json'], cwd=example)
                call('notebook-counts', [python, '-I', '-c',
                     'import anndata as a,numpy as n; x=a.read_h5ad("notebook-result/aggregation/counts.h5ad"); '
                     'assert x.shape==(6,2); n.testing.assert_array_equal(x.X,n.tile([78,36],(6,1)))'], cwd=example)
        receipt['status'] = 'PASS'
    except Exception as exc:
        receipt.update(status='FAIL', error=str(exc))
        raise
    finally:
        (output / 'acceptance.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
