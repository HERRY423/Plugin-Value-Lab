"""Local computational identity and artifact playback, separate from MCP replay.

An environment lock detects drift; it is not an environment installer, OS sandbox,
or proof of numerical reproducibility. Artifact playback never imports science.
"""
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import re
import sys

from .core import ValidationError, load_json, suite_digest, write_json

THREAD_ENV = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
              'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS', 'PYTHONHASHSEED')


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _name(value):
    return re.sub(r'[-_.]+', '-', value).lower()


def _dependencies(requirements, extras):
    try:
        from packaging.requirements import Requirement
    except ImportError as exc:
        raise ValidationError('Environment locking requires packaging; artifact playback does not') from exc
    for text in requirements:
        req = Requirement(text)
        if req.marker is None or any(req.marker.evaluate({'extra': extra}) for extra in ('', *sorted(extras))):
            yield _name(req.name), frozenset(req.extras)


def capture_environment(packages):
    """Hash installed dependency bytes without importing any scientific package.

    Resolves active dependency markers and explicitly requested transitive extras.
    Test/doc extras do not accidentally pull in unrelated local environments.
    External system libraries and hardware remain outside this identity.
    """
    if not packages or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', p) for p in packages):
        raise ValidationError('Specify installed distribution names')
    available = {}
    for dist in metadata.distributions():
        name = _name(dist.metadata['Name'])
        available.setdefault(name, []).append(dist)
    roots = sorted({_name(p) for p in packages})
    if any(p not in available for p in roots):
        raise ValidationError('Required scientific distribution is not installed')
    pending, seen, rows = [(name, frozenset()) for name in roots], set(), {}
    while pending:
        name, extras = pending.pop()
        if (name, extras) in seen:
            continue
        seen.add((name, extras))
        candidates = available.get(name)
        if candidates is None:
            raise ValidationError('Required scientific dependency is missing: ' + name)
        if len(candidates) != 1:
            raise ValidationError('Ambiguous installed distribution: ' + name)
        dist = candidates[0]
        direct = dist.read_text('direct_url.json')
        if direct and json.loads(direct).get('dir_info', {}).get('editable'):
            raise ValidationError('Editable scientific distributions must be built before locking')
        requirements = sorted(dist.requires or [])
        if requirements:
            pending.extend(_dependencies(requirements, extras))
        if name in rows:
            continue
        files = dist.files
        if not files:
            raise ValidationError('Installed distribution has no file inventory: ' + name)
        base, hashes, external = Path(dist.locate_file('')).resolve(), {}, []
        for item in files:
            label = item.as_posix()
            # Bytecode is an interpreter cache, not the source identity.
            if '__pycache__' in item.parts or item.suffix == '.pyc':
                continue
            path = Path(dist.locate_file(item))
            if not path.resolve().is_relative_to(base):
                external.append(label)
                continue  # installed console launchers are outside import roots
            if path.is_symlink() or not path.is_file():
                raise ValidationError('Missing or linked scientific dependency file: ' + name)
            hashes[label] = _sha(path)
        rows[name] = {'installed': True, 'version': dist.version,
                      'requirements': requirements, 'files_sha256': suite_digest(hashes),
                      'file_count': len(hashes), 'excluded_external_files': sorted(external)}
    code = {p.name: _sha(p) for p in Path(__file__).parent.glob('*.py')}
    return {'format': 'pvl-science-environment-1', 'roots': roots,
            'python': {'version': platform.python_version(), 'implementation': sys.implementation.name,
                       'cache_tag': sys.implementation.cache_tag, 'executable_sha256': _sha(sys.executable),
                       'isolated': sys.flags.isolated, 'ignore_environment': sys.flags.ignore_environment,
                       'no_user_site': sys.flags.no_user_site, 'hash_randomization': sys.flags.hash_randomization},
            'platform': {'system': platform.system(), 'release': platform.release(), 'machine': platform.machine()},
            'process_controls': {key: os.environ.get(key) for key in THREAD_ENV},
            'distributions': dict(sorted(rows.items())), 'pvl_code_sha256': suite_digest(code),
            'scope': 'installed dependency bytes; excludes OS libraries, hardware and untracked injected modules'}


def check_environment(lock, expected_id):
    if (not isinstance(lock, dict) or lock.get('format') != 'pvl-science-environment-1'
            or not isinstance(expected_id, str) or suite_digest(lock) != expected_id):
        raise ValidationError('Science environment lock commitment missing or changed')
    current = capture_environment(lock['roots'])
    from .replay import report_changes
    changes = report_changes(lock, current)
    return {'status': 'ENVIRONMENT_MATCH' if not changes['changed_field_count'] else 'ENVIRONMENT_DRIFT',
            'environment_sha256': suite_digest(current), 'changes': changes,
            'scientific_execution': False, 'numerical_reproducibility': 'NOT_ESTABLISHED'}


def require_environment(lock, expected_id):
    result = check_environment(lock, expected_id)
    if result['status'] != 'ENVIRONMENT_MATCH':
        raise ValidationError('Scientific environment drift: ' + ', '.join(result['changes']['paths'][:10]))
    return result


def seal_reference(directory):
    """Commit the completed reference bundle, including inputs and runtime lock."""
    root = Path(directory)
    names = ('design.json', 'data.json', 'reference.json', 'reference-runner.py',
             'backend-receipt.json', 'verifier.json', 'execution.json', 'environment.lock.json')
    if load_json(root / 'execution.json')['status'] != 'COMPLETED':
        raise ValidationError('Cannot seal incomplete scientific execution')
    manifest = {'format': 'pvl-science-artifact-1', 'files': {name: _sha(root / name) for name in names},
                'scientific_validity': 'REQUIRES_INDEPENDENT_REVIEW'}
    write_json(root / 'artifact-manifest.json', manifest)
    return suite_digest(manifest)


def replay_reference(directory, expected_id, output):
    """Verify then restore recorded results using only Python's standard library."""
    root, destination = Path(directory), Path(output)
    manifest = load_json(root / 'artifact-manifest.json')
    expected_names = {'design.json', 'data.json', 'reference.json', 'reference-runner.py',
                      'backend-receipt.json', 'verifier.json', 'execution.json', 'environment.lock.json'}
    if (manifest.get('format') != 'pvl-science-artifact-1' or suite_digest(manifest) != expected_id
            or not isinstance(manifest.get('files'), dict) or set(manifest['files']) != expected_names):
        raise ValidationError('Scientific artifact commitment missing or changed')
    blobs = {}
    for name, digest in manifest['files'].items():
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
            raise ValidationError('Invalid or oversized scientific artifact')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValidationError('Scientific artifact changed: ' + name)
        blobs[name] = data
    if json.loads(blobs['execution.json'])['status'] != 'COMPLETED':
        raise ValidationError('Scientific artifact was not completed')
    destination.mkdir(parents=True, exist_ok=False)
    # Keep original execution provenance nested; playback is never a new run.
    original = destination / 'recorded'
    original.mkdir()
    for name, data in blobs.items():
        (original / name).write_bytes(data)
    write_json(original / 'artifact-manifest.json', manifest)
    receipt = {'status': 'ARTIFACT_REPLAY_COMPLETE', 'mode': 'RECORDED_SCIENTIFIC_OUTPUT',
               'artifact_sha256': expected_id, 'scientific_execution': False, 'backend_calls': 0,
               'environment_required': False, 'new_observations': 0,
               'numerical_reproducibility': 'NOT_RECOMPUTED', 'scientific_validity': 'NOT_ESTABLISHED'}
    write_json(destination / 'playback.json', receipt)
    return receipt
