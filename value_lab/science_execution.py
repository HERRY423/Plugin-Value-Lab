"""Explicit, single-attempt recomputation. Never called by artifact grading.

The controller and installed runtime are trusted. Submitted Python runs only in
the existing networkless OS sandbox, without the submitted results or scorer.
Agreement proves bounded regeneration, not that the algorithm is appropriate.
"""
import json
import math
from pathlib import Path
import re
import sys

from .artifacts import confined, sha
from .core import ValidationError, load_json, suite_digest, write_json, _constant, _unique_object
from .native_evidence import _separate
from .native_session import run_offline
from .science import reference

CONTROLS = {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
            'NUMEXPR_NUM_THREADS': '1', 'VECLIB_MAXIMUM_THREADS': '1', 'PYTHONHASHSEED': '0'}


def command(python, *args):
    return ['/usr/bin/env', *[k + '=' + v for k, v in CONTROLS.items()], python, '-I', *args]


def runtime_id(runtime):
    if runtime is None:
        return None
    from .online_sandbox import runtime_inventory
    return suite_digest(runtime_inventory(runtime))


def capture_runtime(packages, output, *, runtime=None):
    """Measure in a fresh trusted sandbox process, never in submitted Python."""
    if not isinstance(packages, list) or not packages or any(
            not isinstance(p, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', p) for p in packages):
        raise ValidationError('Select installed package roots explicitly')
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    stage = root / 'probe-inputs'
    stage.mkdir()
    for file in Path(__file__).parent.glob('*.py'):
        target = stage / 'value_lab' / file.name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(file.read_bytes())
    script = ('import sys,json\nfrom pathlib import Path\n'
              'sys.path.insert(0,"/inputs")\n'
              'from value_lab.science_environment import capture_environment\n'
              'value=capture_environment(json.loads(sys.argv[1]))\n'
              'Path("/output/environment.json").write_text(json.dumps(value,allow_nan=False),encoding="utf-8")\n')
    (stage / 'probe.py').write_text(script, encoding='utf-8')
    python = '/runtime/bin/python' if runtime is not None else '/usr/bin/python3'
    before = runtime_id(runtime)
    receipt = run_offline(stage, sorted(p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()),
                          command(python, '/inputs/probe.py', json.dumps(packages)), root / 'sandbox',
                          runtime=runtime, memory_mb=4096, timeout_seconds=300)
    if receipt['status'] != 'COMPLETED' or before != runtime_id(runtime):
        raise ValidationError('Runtime measurement failed or runtime changed; inspect probe logs')
    lock = {'format': 'pvl-execution-environment-1', 'runtime_sha256': before,
            'environment': load_json(root / 'sandbox/artifacts/environment.json')}
    write_json(root / 'environment.lock.json', lock)
    return lock


def validate_manifest(value):
    required = {'format', 'files', 'entrypoint', 'arguments', 'environment', 'outputs', 'timeout_seconds', 'memory_mb'}
    large = isinstance(value, dict) and value.get('format') == 'pvl-science-execution-2'
    if large:
        required.add('resources')
        from .science_storage import validate_resources
        validate_resources(value.get('resources'))
    if not isinstance(value, dict) or set(value) != required or value['format'] not in ('pvl-science-execution-1', 'pvl-science-execution-2'):
        raise ValidationError('Expected a complete pvl-science-execution-1/2 manifest')
    if not isinstance(value['files'], dict) or not 1 <= len(value['files']) <= 1000:
        raise ValidationError('Declare all input and program files')
    for name, pin in value['files'].items():
        reference({'path': name, 'sha256': pin})
    if value['entrypoint'] not in value['files'] or not value['entrypoint'].endswith('.py'):
        raise ValidationError('Entrypoint must be a pinned Python file')
    if not isinstance(value['arguments'], list) or any(not isinstance(a, str) or '\x00' in a for a in value['arguments']):
        raise ValidationError('Arguments must be a string array')
    reference(value['environment'])
    if not isinstance(value['outputs'], list) or not 1 <= len(value['outputs']) <= 100:
        raise ValidationError('Declare 1..100 expected outputs')
    paths = set()
    for row in value['outputs']:
        if not isinstance(row, dict) or set(row) != {'path', 'submitted', 'comparison', 'absolute', 'relative'}:
            raise ValidationError('Each output needs path/submitted/comparison/absolute/relative')
        confined(Path.cwd(), row['path'])
        reference(row['submitted'])
        if row['path'] in paths or row['comparison'] not in (('json', 'pseudobulk', 'bytes', 'h5ad_counts') if large else ('json', 'pseudobulk', 'bytes')):
            raise ValidationError('Duplicate output or unsupported comparator')
        paths.add(row['path'])
        for key in ('absolute', 'relative'):
            v = row[key]
            if type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1e-4:
                raise ValidationError('Tolerances must be finite and between 0 and 1e-4')
        if row['comparison'] == 'h5ad_counts' and (row['absolute'] != 0 or row['relative'] != 0):
            raise ValidationError('Raw h5ad counts require exact comparison with zero tolerances')
    if type(value['timeout_seconds']) is not int or not 1 <= value['timeout_seconds'] <= (604800 if large else 300):
        raise ValidationError('Timeout outside selected resource profile')
    if type(value['memory_mb']) is not int or not 128 <= value['memory_mb'] <= (1048576 if large else 4096):
        raise ValidationError('Memory outside selected resource profile')


def read_pinned(root, ref):
    reference(ref)
    path = confined(root, ref['path'])
    if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > 32 * 1024 * 1024:
        raise ValidationError('Expected a bounded regular file: ' + ref['path'])
    data = path.read_bytes()
    import hashlib
    if hashlib.sha256(data).hexdigest() != ref['sha256']:
        raise ValidationError('Pinned file changed: ' + ref['path'])
    return data


def compare_json(observed, expected, absolute, relative):
    """Typed, full-shape comparison; no NaNs, omitted rows or boolean numbers."""
    differences = []
    def walk(a, b, path):
        if len(differences) >= 100:
            return
        if type(b) is int:
            equal = type(a) is int and a == b
        elif type(b) is float and type(a) in (int, float):
            try:
                equal = math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, abs_tol=absolute, rel_tol=relative)
            except OverflowError:
                equal = False
        elif type(a) is not type(b):
            equal = False
        elif isinstance(b, dict) and set(a) == set(b):
            for key in sorted(b):
                walk(a[key], b[key], path + '/' + key.replace('~', '~0').replace('/', '~1'))
            return
        elif isinstance(b, list) and len(a) == len(b):
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, path + '/' + str(i))
            return
        else:
            equal = a == b
        if not equal:
            differences.append(path or '/')
    walk(observed, expected, '')
    return differences


def execute(manifest_path, expected_id, inputs, submitted, output, *, runtime=None):
    manifest_path = Path(manifest_path).resolve()
    manifest = load_json(manifest_path)
    validate_manifest(manifest)
    if suite_digest(manifest) != expected_id:
        raise ValidationError('Execution manifest commitment changed')
    root, inputs, submitted = map(lambda p: Path(p).resolve(), (output, inputs, submitted))
    for path in (inputs, submitted, manifest_path.parent):
        _separate(root, path)
    for path in (inputs, submitted, manifest_path.parent, root):
        if sys.platform == 'linux' and any(path.is_relative_to(Path(p).resolve()) for p in ('/usr', '/bin', '/lib', '/lib64')):
            raise ValidationError('Inputs, answers and controller evidence must be outside runtime mounts')
        if runtime is not None:
            _separate(Path(runtime).resolve(), path)
    from .science_storage import inventory_pinned, stream_file, disk_preflight, regular
    large = manifest['format'] == 'pvl-science-execution-2'
    budget = manifest.get('resources', {'input_bytes': 32 * 1048576, 'output_bytes': 32 * 1048576,
                                       'file_bytes': 32 * 1048576, 'reserve_bytes': 0})
    inventory = inventory_pinned(inputs, manifest['files'], budget['input_bytes'])
    answers = []
    answer_bytes = 0
    for row in manifest['outputs']:
        path = confined(submitted, row['submitted']['path'])
        limit = budget['file_bytes'] if row['comparison'] in ('bytes', 'h5ad_counts') else 32 * 1048576
        info = stream_file(path, expected=row['submitted']['sha256'], maximum=limit)
        answer_bytes += info['bytes']
        answers.append((path, info))
    if answer_bytes > budget['output_bytes']:
        raise ValidationError('Submitted outputs exceed total output byte budget')
    lock_bytes = read_pinned(manifest_path.parent, manifest['environment'])
    lock = json.loads(lock_bytes, parse_constant=_constant, object_pairs_hook=_unique_object)
    if lock.get('format') != 'pvl-execution-environment-1' or lock.get('runtime_sha256') != runtime_id(runtime):
        raise ValidationError('Wrong or changed execution runtime')
    disk_preflight(root.parent, 2 * sum(r['bytes'] for r in inventory.values()) + answer_bytes + budget['output_bytes'], budget['reserve_bytes'])
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / 'manifest.json', manifest)
    (root / 'environment.lock.json').write_bytes(lock_bytes)
    receipt = {'format': 'pvl-science-execution-receipt-1', 'status': 'STARTED', 'passed': None,
               'manifest_sha256': expected_id, 'environment_sha256': suite_digest(lock),
               'pipeline_completed': False, 'outputs': [], 'automatic_retry': False,
               'external_environment_reconstruction': 'NOT_ESTABLISHED',
               'scientific_validity': 'NOT_ESTABLISHED', 'independent_expert_review': 'PENDING',
               'scope': 'Regeneration in a measured local runtime; same-code agreement is not independent correctness'}
    write_json(root / 'receipt.json', receipt)
    try:
        receipt['input_inventory'] = inventory
        receipt['resources'] = budget
        before = capture_runtime(lock['environment']['roots'], root / 'before', runtime=runtime)
        if before != lock:
            raise ValidationError('Environment drift before execution')
        stage = root / 'public'
        stage.mkdir()
        for name, info in inventory.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            stream_file(confined(inputs, name), expected=info['sha256'], target=path,
                        maximum=info['bytes'], reserve=budget['reserve_bytes'])
        python = '/runtime/bin/python' if runtime is not None else '/usr/bin/python3'
        result = run_offline(stage, list(inventory), command(python, '/inputs/' + manifest['entrypoint'], *manifest['arguments']),
                             root / 'run', timeout_seconds=manifest['timeout_seconds'],
                             memory_mb=manifest['memory_mb'], runtime=runtime,
                             **({'resources': budget} if large else {}))
        receipt['execution'] = result
        receipt['pipeline_completed'] = result['status'] == 'COMPLETED'
        after = capture_runtime(lock['environment']['roots'], root / 'after', runtime=runtime)
        if after != lock:
            raise ValidationError('Environment drift after execution')
        receipt['environment_check'] = 'MATCH_BEFORE_AND_AFTER'
        if not receipt['pipeline_completed']:
            receipt['status'] = 'EXECUTION_FAILED'
        else:
            retained = root / 'submitted'
            retained.mkdir()
            output_bytes = 0
            for i, (row, (answer, info)) in enumerate(zip(manifest['outputs'], answers)):
                answer_copy = retained / str(i)
                stream_file(answer, expected=info['sha256'], target=answer_copy,
                            maximum=info['bytes'], reserve=budget['reserve_bytes'])
                path = confined(root / 'run/artifacts', row['path'])
                limit = budget['file_bytes'] if row['comparison'] in ('bytes', 'h5ad_counts') else 32 * 1048576
                output_bytes += regular(path, limit).st_size
                if output_bytes > budget['output_bytes']:
                    raise ValidationError('Regenerated outputs exceed total output byte budget')
                if row['comparison'] == 'bytes':
                    differences = [] if sha(path) == info['sha256'] else ['/']
                elif row['comparison'] == 'h5ad_counts':
                    from .pseudobulk_backed import compare_counts
                    differences = compare_counts(path, answer_copy)
                else:
                    a, b = load_json(path), load_json(answer_copy)
                    if row['comparison'] == 'pseudobulk':
                        from .pseudobulk import _canonical
                        a, b = _canonical(a), _canonical(b)
                    differences = compare_json(a, b, row['absolute'], row['relative'])
                receipt['outputs'].append({'path': row['path'], 'sha256': sha(path),
                    'submitted_sha256': row['submitted']['sha256'], 'passed': not differences,
                    'difference_paths_first_100': differences})
            receipt['passed'] = all(row['passed'] for row in receipt['outputs'])
            receipt['status'] = 'REPRODUCED' if receipt['passed'] else 'RESULT_MISMATCH'
    except (OSError, ValueError, KeyError, TypeError, IndexError, RecursionError) as exc:
        receipt.update(status='UNRESOLVED', passed=None, error=type(exc).__name__ + ': ' + str(exc)[:500])
    write_json(root / 'receipt.json', receipt)
    return receipt
