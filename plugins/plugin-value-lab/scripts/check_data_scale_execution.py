"""Required real Linux sandbox replay of a separately checked large h5ad fixture."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.artifacts import sha
from value_lab.core import load_json, suite_digest, write_json
from value_lab.science_execution import capture_runtime, execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scale-directory', required=True)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root, scale = Path(args.output).resolve(), Path(args.scale_directory).resolve()
    root.mkdir(parents=True, exist_ok=False)
    receipt = {'status': 'STARTED', 'synthetic': True, 'real_os_execution': False,
               'scientific_validity': 'NOT_ESTABLISHED'}
    write_json(root / 'acceptance.json', receipt)
    try:
        accepted = load_json(scale / 'acceptance.json')
        if accepted['status'] != 'PASS' or sha(scale / 'input.h5ad') != accepted['source_sha256']:
            raise ValueError('Scale oracle receipt or source changed')
        public, spec, submitted = (root / k for k in ('public', 'spec', 'submitted'))
        for directory in (public, spec, submitted):
            directory.mkdir()
        for file in (ROOT / 'value_lab').glob('*.py'):
            target = public / 'value_lab' / file.name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(file, target)
        for name in ('input.h5ad', 'design.json', 'plan.json'):
            shutil.copyfile(scale / name, public / name)
        shutil.copyfile(scale / 'result/counts.h5ad', submitted / 'counts.h5ad')
        pipeline = ('import sys\nsys.path.insert(0,"/inputs")\n'
                    'from value_lab.core import load_json\n'
                    'from value_lab.pseudobulk_backed import aggregate_h5ad\n'
                    'p=load_json("/inputs/plan.json")\n'
                    'r=aggregate_h5ad(load_json("/inputs/design.json"),"/inputs/input.h5ad","/output/result",'
                    'expected_sha256=p["data"]["sha256"],matrix="X",metadata_mb=64,'
                    'max_disk_bytes=268435456,reserve_bytes=0)\n')
        (public / 'pipeline.py').write_text(pipeline, encoding='utf-8')
        lock = capture_runtime(['h5py'], root / 'freeze', runtime=args.runtime)
        write_json(spec / 'environment.json', lock)
        manifest = {'format': 'pvl-science-execution-2', 'files': {p.relative_to(public).as_posix(): sha(p) for p in public.rglob('*') if p.is_file()},
                    'entrypoint': 'pipeline.py', 'arguments': [],
                    'environment': {'path': 'environment.json', 'sha256': sha(spec / 'environment.json')},
                    'timeout_seconds': 180, 'memory_mb': 1024,
                    'resources': {'input_bytes': 128*1048576, 'output_bytes': 128*1048576,
                                  'file_bytes': 96*1048576, 'reserve_bytes': 64*1048576},
                    'outputs': [{'path': 'result/counts.h5ad', 'submitted': {'path': 'counts.h5ad', 'sha256': sha(submitted / 'counts.h5ad')},
                                 'comparison': 'h5ad_counts', 'absolute': 0, 'relative': 0}]}
        write_json(spec / 'execution.json', manifest)
        result = execute(spec / 'execution.json', suite_digest(manifest), public, submitted, root / 'execution', runtime=args.runtime)
        if result['status'] != 'REPRODUCED':
            raise RuntimeError('Large sandbox recomputation failed: ' + result['status'])
        receipt.update(status='PASS', real_os_execution=True, result=result,
                       scale_source_sha256=accepted['source_sha256'], shape=accepted['input_shape'])
    except Exception as exc:
        receipt.update(status='FAILED', error=type(exc).__name__ + ': ' + str(exc))
        write_json(root / 'acceptance.json', receipt)
        raise
    write_json(root / 'acceptance.json', receipt)
    print(json.dumps(receipt, ensure_ascii=True, allow_nan=False))


if __name__ == '__main__':
    main()
