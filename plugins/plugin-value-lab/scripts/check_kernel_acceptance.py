"""Run both real kernel gates and retain portable evidence, including failures.

Only manufactured local fixtures are used. This wrapper does not change kernel
policy, run as root, weaken a boundary, skip a gate, or contact a model service.
"""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.core import write_json


def environment():
    result = {'platform': sys.platform, 'kernel': platform.release(),
              'observed_at': datetime.now(timezone.utc).isoformat(),
              'node': platform.node(), 'machine': platform.machine(),
              'python': platform.python_version(), 'uid': os.getuid() if hasattr(os, 'getuid') else None,
              'bubblewrap': shutil.which('bwrap'), 'runner_image': os.environ.get('ImageOS'),
              'runner_image_version': os.environ.get('ImageVersion')}
    # Explicit scheduler identifiers only; never dump the job environment (it
    # may contain credentials). Login-node success is not compute-node evidence.
    result['scheduler'] = {key: os.environ[key] for key in (
        'SLURM_JOB_ID', 'SLURM_JOB_PARTITION', 'SLURM_CLUSTER_NAME',
        'PBS_JOBID', 'PBS_QUEUE', 'LSB_JOBID', 'LSB_QUEUE') if key in os.environ}
    for path in ('/etc/os-release', '/proc/sys/kernel/unprivileged_userns_clone',
                 '/proc/sys/kernel/apparmor_restrict_unprivileged_userns',
                 '/proc/sys/user/max_user_namespaces', '/proc/self/limits',
                 '/proc/self/attr/current', '/proc/self/cgroup'):
        try:
            result[path] = Path(path).read_text(encoding='utf-8')[:8192]
        except OSError:
            result[path] = None
    if result['bubblewrap']:
        try:
            proc = subprocess.run([result['bubblewrap'], '--version'], capture_output=True, timeout=10)
            result['bubblewrap_version'] = proc.stdout.decode('utf-8', errors='replace').strip()
            result['bubblewrap_version_exit_code'] = proc.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            result['bubblewrap_version_error'] = str(exc)
    return result


def run(output):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    receipt = {'format': 'pvl-kernel-acceptance-1', 'status': 'FAIL', 'environment': environment(),
               'gates': {}, 'model_calls': 0, 'provider_calls': 0,
               'scope': 'Manufactured real kernel/protocol acceptance; not independent security review'}
    for name in ('offline', 'online'):
        gate = root / name
        out, err = root / (name + '-stdout.txt'), root / (name + '-stderr.txt')
        command = [sys.executable, '-S', str(ROOT / 'scripts' / ('check_' + name + '_boundary.py')),
                   '--output', str(gate)]
        with out.open('wb') as stdout, err.open('wb') as stderr:
            try:
                proc = subprocess.run(command, stdout=stdout, stderr=stderr, cwd=ROOT, check=False)
                code, error = proc.returncode, None
            except OSError as exc:
                code, error = None, str(exc)
        acceptance = None
        try:
            acceptance = json.loads((gate / 'acceptance.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        # Exit zero alone is not an acceptance receipt. Both gates must pass.
        success = code == 0 and isinstance(acceptance, dict) and acceptance.get('status') == 'PASS'
        logs = {p.relative_to(root).as_posix(): p.read_bytes()[:8192].decode('utf-8', errors='replace')
                for p in sorted(gate.rglob('stderr.txt')) if p.is_file() and not p.is_symlink()}
        result = {'status': 'PASS' if success else 'FAIL', 'exit_code': code, 'launcher_error': error,
                  'acceptance': acceptance, 'stderr': err.read_bytes()[:8192].decode('utf-8', errors='replace'),
                  'boundary_stderr': logs}
        receipt['gates'][name] = result
        # Emit the actual namespace/probe error even if artifact upload fails.
        print(json.dumps({'gate': name, **result}, ensure_ascii=True), flush=True)
        write_json(root / 'acceptance.json', receipt)
    receipt['status'] = 'PASS' if all(g['status'] == 'PASS' for g in receipt['gates'].values()) else 'FAIL'
    write_json(root / 'acceptance.json', receipt)
    files = [p for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()]
    write_json(root / 'manifest.json', {'algorithm': 'sha256', 'files': {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}})
    # tar retains hostile canary names and hidden cassettes. Uploading those
    # raw names fails the portable artifact service's path validation.
    archive = root.with_suffix('.tar.gz')
    with tarfile.open(archive, 'x:gz') as bundle:
        bundle.add(root, arcname=root.name)
    print(json.dumps({'status': receipt['status'], 'archive': str(archive),
                      'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}, ensure_ascii=True))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.output)['status'] == 'PASS' else 1)
