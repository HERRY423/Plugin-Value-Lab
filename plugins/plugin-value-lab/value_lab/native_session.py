"""Single-attempt orchestration around existing official cases and offline sidecars.

The model executor remains Claude Code. Scorers are hidden from the child mount
namespace and checked offline only after the child exits. No automatic retries.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys

from .artifacts import confined, sha
from .core import ValidationError, load_json, suite_digest, write_json
from .native_evidence import (_fresh, _plan, _separate, capture_native_evidence,
                              discover_native_bindings, verify_native_evidence)


def offline_namespace(command, inputs, outputs, bwrap):
    """Allowlisted filesystem for OFFLINE workloads, not the online model host.

    Do not bind /, HOME, /etc, /run, WSL mounts or a reference directory. A clean
    network namespace plus closed inherited FDs prevents host socket reuse.
    """
    argv = [bwrap, '--unshare-all', '--unshare-user', '--uid', '65534', '--gid', '65534',
            '--disable-userns', '--new-session',
            '--die-with-parent', '--cap-drop', 'ALL', '--clearenv',
            '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'HOME', '/tmp',
            '--setenv', 'LANG', 'C.UTF-8', '--setenv', 'PYTHONDONTWRITEBYTECODE', '1']
    for path in ('/usr', '/bin', '/lib', '/lib64'):
        if Path(path).exists():
            argv.extend(['--ro-bind', path, path])
    argv.extend(['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                 '--dir', '/etc', '--ro-bind', str(inputs), '/inputs',
                 '--bind', str(outputs), '/output', '--chdir', '/output',
                 '--remount-ro', '/', '--'])
    return [*argv, *command]


def run_offline(inputs, files, command, output, *, cassette=None, expected_id=None, timeout_seconds=30):
    """One local attempt with an optional parent-side MCP replay broker.

    The child gets only selected public inputs and a fresh output directory.
    Cassette and scorer remain in the parent; only matched responses cross the
    stdio boundary. There is no hook-only, online, or unsandboxed fallback.
    """
    import json
    import math
    import queue
    import threading
    import time
    from .processes import close_tree
    from .replay import ToolReplay, replay_message
    if sys.platform != 'linux':
        raise ValidationError('Offline OS isolation requires Linux/WSL2 with bubblewrap; no fallback')
    bwrap = shutil.which('bwrap')
    if not bwrap:
        raise ValidationError('bubblewrap unavailable; no fallback or automatic installation')
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 1 <= timeout_seconds <= 300):
        raise ValidationError('Offline timeout must be 1..300 seconds')
    if (not isinstance(command, list) or not command
            or any(not isinstance(s, str) or not s or '\x00' in s for s in command)):
        raise ValidationError('Use an explicit command argument list, not a shell string')
    if (not isinstance(files, list) or not files or any(not isinstance(s, str) for s in files)
            or len(files) != len(set(files)) or len(files) > 1000):
        raise ValidationError('Select 1..1000 unique public input files explicitly')
    source, root = Path(inputs).resolve(), _fresh(output)
    _separate(source, root)
    runtime_roots = [Path(p).resolve() for p in ('/usr', '/bin', '/lib', '/lib64') if Path(p).exists()]
    if any(root.is_relative_to(p) for p in runtime_roots):
        raise ValidationError('Keep controller evidence outside mounted runtime directories')
    replay = ToolReplay(cassette, expected_id) if cassette is not None else None
    cassette_root = Path(cassette).resolve() if cassette is not None else None
    if cassette_root is not None and any(cassette_root.is_relative_to(p) for p in runtime_roots):
        raise ValidationError('Cassette would be visible through a runtime mount')
    if cassette is None and expected_id is not None:
        raise ValidationError('A cassette commitment needs a cassette')
    selected, size = [], 0
    for name in files:
        path = confined(source, name)
        if cassette_root is not None and path.resolve().is_relative_to(cassette_root):
            raise ValidationError('Cassette cannot also be selected as a public input')
        if '.replay' in Path(name).parts or not path.is_file() or path.stat().st_nlink != 1:
            raise ValidationError('Select regular public files, not linked files or private .replay material')
        size += path.stat().st_size
        if size > 32 * 1024 * 1024:
            raise ValidationError('Public inputs exceed 32 MiB')
        selected.append((name, path))
    root.mkdir(parents=True)
    stage, artifacts = root / 'inputs', root / 'artifacts'
    stage.mkdir()
    artifacts.mkdir()
    for name, path in selected:
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    plan = {'format': 'pvl-offline-isolation-1', 'command': command,
            'inputs': {name: sha(stage / name) for name, _ in selected},
            'timeout_seconds': timeout_seconds, 'bwrap_sha256': sha(bwrap),
            'cassette_sha256': expected_id, 'network': 'DENIED',
            'host_root_mounted': False, 'inherited_environment': False,
            'model_calls': 0, 'mode': 'OFFLINE_CONTRACT_REPLAY' if replay else 'OFFLINE_EXECUTION'}
    write_json(root / 'plan.json', plan)
    # Apply resource limits before exec, in the namespace, without preexec_fn.
    limits = ('import os,resource,sys; '
              'resource.setrlimit(resource.RLIMIT_CORE,(0,0)); '
              'resource.setrlimit(resource.RLIMIT_FSIZE,(8388608,8388608)); '
              'resource.setrlimit(resource.RLIMIT_AS,(536870912,536870912)); '
              'resource.setrlimit(resource.RLIMIT_NOFILE,(64,64)); '
              'resource.setrlimit(resource.RLIMIT_NPROC,(64,64)); '
              f'resource.setrlimit(resource.RLIMIT_CPU,({math.ceil(timeout_seconds)},{math.ceil(timeout_seconds)})); '
              'os.execvp(sys.argv[1],sys.argv[1:])')
    argv = offline_namespace(['/usr/bin/python3', '-I', '-c', limits, *command], stage, artifacts, bwrap)
    started, error, returncode = time.monotonic(), None, None
    write_json(root / 'started.json', {'plan_sha256': suite_digest(plan), 'automatic_retry': False})
    with (root / 'stderr.txt').open('wb') as err, (root / 'stdout.txt').open('wb') as log:
        process = None
        stop = threading.Event()
        try:
            process = subprocess.Popen(argv, stdin=subprocess.PIPE if replay else subprocess.DEVNULL,
                stdout=subprocess.PIPE if replay else log, stderr=err, cwd=root,
                env={'PATH': '/usr/bin:/bin'}, close_fds=True, start_new_session=True, shell=False)
            if replay:
                messages = queue.Queue(maxsize=16)
                def read_lines():
                    while not stop.is_set():
                        line = process.stdout.readline(1024 * 1024 + 1)
                        while not stop.is_set():
                            try:
                                messages.put(line, timeout=.1)
                                break
                            except queue.Full:
                                pass
                        if not line or len(line) > 1024 * 1024:
                            return
                reader = threading.Thread(target=read_lines, daemon=True)
                reader.start()
                total, count = 0, 0
                while True:
                    if time.monotonic() - started > timeout_seconds:
                        raise TimeoutError('Offline replay timed out')
                    try:
                        line = messages.get(timeout=.05)
                    except queue.Empty:
                        continue
                    if not line:
                        break
                    total, count = total + len(line), count + 1
                    if len(line) > 1024 * 1024 or total > 8 * 1024 * 1024 or count > 10000 or not line.endswith(b'\n'):
                        raise ValidationError('MCP replay stream exceeds framing/resource limit')
                    log.write(line)
                    response = replay.handle(replay_message(line.decode('utf-8')))
                    if response is not None:
                        payload = (json.dumps(response, ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')
                        # Nonblocking writes ensure a child that never reads cannot
                        # hold the trusted broker beyond the same wall deadline.
                        os.set_blocking(process.stdin.fileno(), False)
                        import select
                        offset = 0
                        while offset < len(payload):
                            if time.monotonic() - started > timeout_seconds:
                                raise TimeoutError('Offline replay response timed out')
                            _, ready, _ = select.select([], [process.stdin.fileno()], [], .05)
                            if ready:
                                try:
                                    offset += os.write(process.stdin.fileno(), payload[offset:])
                                except BlockingIOError:
                                    pass
                    if replay.violations:
                        raise ValidationError('MCP replay contract mismatch; no fallback')
            remaining = max(.001, timeout_seconds - (time.monotonic() - started))
            returncode = process.wait(timeout=remaining)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            error = type(exc).__name__ + ': ' + str(exc)[:400]
        finally:
            stop.set()
            if process is not None:
                close_tree(process)
                returncode = process.returncode
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        stream.close()
    replay_receipt = replay.receipt() if replay else None
    succeeded = returncode == 0 and error is None and (not replay or replay_receipt['status'] == 'REPLAY_COMPLETE')
    receipt = {'status': 'COMPLETED' if succeeded else 'FAILED', 'returncode': returncode,
               'error': error, 'replay': replay_receipt, 'plan_sha256': suite_digest(plan),
               'isolation_requested': 'BUBBLEWRAP_OFFLINE_ALLOWLIST', 'network_policy': 'DENIED',
               'independent_isolation_verification': False,
               'new_observations': 0 if replay else None,
               'claim_limit': 'Local isolation/execution only; no scientific validation or live backend evidence'}
    write_json(root / 'receipt.json', receipt)
    return receipt


def _sources(plan_root, pin, plugin, references):
    _, plan = _plan(plan_root, pin)
    for field in ('case_files', 'plugin_files'):
        for relative, digest in plan[field].items():
            if sha(confined(plugin, relative)) != digest:
                raise ValidationError('Selected native source changed after freeze')
    inventory = {}
    for case in plan['contract']['cases']:
        for path in confined(plugin, case['case_directory']).rglob('*'):
            relative = path.relative_to(plugin).as_posix()
            if confined(plugin, relative).is_file():
                inventory[relative] = sha(path)
    if inventory != plan['case_files']:
        raise ValidationError('Native case inventory changed')
    for relative, digest in plan['references'].items():
        if references is None or sha(confined(references, relative)) != digest:
            raise ValidationError('Scientific reference missing or changed')
    return plan


def _invocation(argv, plugin, output, plan):
    if (not isinstance(argv, list) or any(not isinstance(v, str) or not v or '\x00' in v for v in argv)
            or len(argv) < 4 or argv[1:3] != ['plugin', 'eval'] or Path(argv[3]).resolve() != plugin):
        raise ValidationError('Supply the existing Claude plugin eval argument vector with its exact candidate path')
    scalar = {'--eval-dir', '--runs', '--model', '--judge-model', '--concurrency', '--mocks', '--max-cost-usd', '--threshold', '--ablation', '--output-dir'}
    flags = {'--scaffold', '--no-scaffold', '--trust-plugin', '--keep-temp', '--no-publish', '--verbose'}
    values, rebuilt, index = {}, argv[:4], 4
    while index < len(argv):
        flag = argv[index]
        if flag in values:
            raise ValidationError('Duplicate native option: ' + flag)
        if flag in scalar:
            if index + 1 >= len(argv) or argv[index + 1].startswith('--'):
                raise ValidationError('Native option needs a value: ' + flag)
            values[flag] = argv[index + 1]
            if flag != '--output-dir':
                rebuilt.extend(argv[index:index + 2])
            index += 2
        elif flag in flags:
            values[flag] = True
            rebuilt.append(flag)
            index += 1
        elif flag == '--allow-tools':
            end = index + 1
            while end < len(argv) and not argv[end].startswith('--'):
                end += 1
            grants = argv[index + 1:end]
            if not grants or any(g not in ('Write', 'Edit', 'Bash') for g in grants) or len(set(grants)) != len(grants):
                raise ValidationError('This bounded collector supports explicit Write/Edit/Bash grants only')
            values[flag] = grants
            rebuilt.extend(argv[index:end])
            index = end
        else:
            raise ValidationError('Unsupported native option; preserve your command and use offline capture: ' + flag)
    if values.get('--ablation') != 'with-without' or values.get('--mocks', 'record') != 'record':
        raise ValidationError('This collector requires both arms and mocked servers; use offline capture for other native profiles')
    if values.get('--concurrency', '1') != '1':
        raise ValidationError('This bounded collector requires native concurrency 1; it never silently changes the supplied command')
    if '--scaffold' in values and '--no-scaffold' in values:
        raise ValidationError('Conflicting scaffold options')
    try:
        runs = int(values['--runs'])
        price = float(values['--max-cost-usd'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError('Explicit native --runs and --max-cost-usd required') from exc
    import math
    if (not math.isfinite(price) or price <= 0 or any(c['repetitions'] != runs for c in plan['contract']['cases'])
            or not values.get('--model') or values['--model'].startswith('-')):
        raise ValidationError('Native run count/model/estimate ceiling does not match the frozen collection contract')
    context = plan['contract'].get('execution_context')
    if context and (values['--model'] != context['model'] or price != context['max_cost_usd']):
        raise ValidationError('Native model or ceiling differs from the frozen execution context')
    eval_dir = values.get('--eval-dir', 'evals')
    eval_root = confined(plugin, eval_dir)
    if any(not c['case_directory'].startswith(eval_dir + '/') for c in plan['contract']['cases']):
        raise ValidationError('Native eval directory differs from selected cases')
    expected_cases = {c['case_directory'] for c in plan['contract']['cases']}
    observed_cases = {path.parent.relative_to(plugin).as_posix() for path in eval_root.rglob('*')
                      if path.is_file() and path.name in ('prompt.md', 'case.yaml', 'case.yml')}
    if observed_cases != expected_cases:
        raise ValidationError('Native eval directory contains missing or unplanned cases; freeze the complete invocation before execution')
    for flag in ('--keep-temp', '--no-publish'):
        if flag not in values:
            rebuilt.append(flag)
    rebuilt.extend(['--output-dir', str(output / 'native'), '--json', str(output / 'native/result.json')])
    return rebuilt, price


def prepare_native_session(directory, plan_digest, plugin, invocation, output, *, references=None, timeout_seconds=1800, sandbox=None):
    """Prepare a networkless host; legacy root masking is no longer executable."""
    from .online_sandbox import prepare_session
    return prepare_session(directory, plan_digest, plugin, invocation, output,
                           references=references, timeout_seconds=timeout_seconds, sandbox=sandbox)


def _session(directory, pin):
    root = Path(directory).resolve()
    frozen = load_json(root / 'session-plan.json')
    if suite_digest(frozen) != pin:
        raise ValidationError('Native session plan changed')
    return root, frozen


def finish_native_session(directory, pin):
    root, frozen = _session(directory, pin)
    if (root / 'completion.json').exists():
        completed = load_json(root / 'completion.json')
        if completed.get('status') == 'COLLECTED':
            verify_native_evidence(root / 'collected', completed['receipt_sha256'])
        return completed
    if not (root / 'process.json').is_file():
        raise ValidationError('Process completion is unknown; confirm termination before offline recovery, never automatically relaunch')
    if not (root / 'native/result.json').is_file():
        result = {'status': 'NATIVE_RESULT_MISSING', 'model_relaunched': False, 'settled_usd': None,
                  'scope': 'Inspect retained process logs; no aggregate or missing runs fabricated'}
    else:
        links = discover_native_bindings(root / 'native/result.json', root / 'retained')
        write_json(root / 'bindings.json', links)
        if (root / 'collected/receipt.json').is_file():
            receipt = load_json(root / 'collected/receipt.json')
            if receipt['plan_sha256'] != frozen['evidence_plan_sha256'] or sha(root / 'native/result.json') != sha(root / 'collected/native-result.json'):
                raise ValidationError('Interrupted collection does not match this frozen native session')
            capture = {'receipt_sha256': suite_digest(receipt)}
            verify_native_evidence(root / 'collected', capture['receipt_sha256'])
        else:
            capture = capture_native_evidence(frozen['evidence_plan'], frozen['evidence_plan_sha256'], frozen['plugin'],
                                              root / 'native/result.json', links['bindings'], root / 'collected',
                                              references=frozen['references'], retained_root=root / 'retained')
        result = {'status': 'COLLECTED', 'receipt_sha256': capture['receipt_sha256'], 'missing_bindings': links['missing'],
                  'comparison_eligible': False, 'model_relaunched': False, 'settled_usd': None}
    write_json(root / 'completion.json', result)
    return result


def run_native_session(directory, pin, *, execute=False):
    root, frozen = _session(directory, pin)
    if execute is not True:
        raise ValidationError('Use --execute with the exact session digest after reviewing collection, tools, data and estimate limits')
    from .online_sandbox import run_session
    return run_session(root, frozen, pin)
