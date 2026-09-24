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


def _namespace(command, private_roots, empty, bwrap, writable=()):
    # A private PID/proc namespace prevents following the parent's /proc/PID/root.
    argv = [bwrap, '--ro-bind', '/', '/', '--unshare-pid', '--proc', '/proc', '--dev', '/dev',
            '--die-with-parent', '--cap-drop', 'ALL', '--unsetenv', 'WSL_INTEROP']
    for root in writable:
        argv.extend(['--bind', str(root), str(root)])
    for root in private_roots:
        argv.extend(['--ro-bind', str(empty / 'directory'), str(root)])
    # WSL's interop interpreter could escape a Linux mount namespace.
    if Path('/init').exists():
        argv.extend(['--ro-bind', str(empty / 'file'), '/init'])
    if Path('/run/WSL').is_dir():
        argv.extend(['--ro-bind', str(empty / 'directory'), '/run/WSL'])
    return [*argv, '--', *command]


PROBE = r'''import json,os,subprocess,sys
rows=[]
for path in json.loads(sys.argv[1]):
    row={'path':path}
    for mode,label in [('rb','readable'),('r+b','writable_existing')]:
        try:
            with open(path,mode): pass
            row[label]=True
        except OSError: row[label]=False
    target=os.path.join(os.path.dirname(path),'._pvl_namespace_probe')
    try:
        with open(target,'xb'): pass
        row['replacement_creatable']=True
    except OSError: row['replacement_creatable']=False
    rows.append(row)
interop=None
if os.path.exists('/mnt/c/Windows/System32/cmd.exe'):
    try:
        result=subprocess.run(['/mnt/c/Windows/System32/cmd.exe','/c','exit','0'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
        interop=result.returncode==0
    except (OSError,subprocess.SubprocessError): interop=False
print(json.dumps({'files':rows,'windows_interop_succeeded':interop}))
'''


def probe_namespace(private_roots, targets, scratch, bwrap, writable=()):
    import json
    scratch = _fresh(scratch)
    for root in private_roots:
        _separate(root, scratch)
    if any(not Path(path).is_file() for path in targets):
        raise ValidationError('Isolation probe needs existing host-readable targets')
    before = {str(path): sha(path) for path in targets}
    (scratch / 'directory').mkdir(parents=True)
    (scratch / 'file').write_bytes(b'')
    command = _namespace([sys.executable, '-B', '-c', PROBE, json.dumps([str(p) for p in targets])], private_roots, scratch, bwrap, writable)
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, shell=False)
    if result.returncode:
        raise ValidationError('Reference namespace unavailable; model was not launched: ' + result.stderr[:300])
    observation = json.loads(result.stdout)
    allowed = (len(observation['files']) == len(targets) and observation['windows_interop_succeeded'] is not True
               and all(not any(row[k] for k in ('readable', 'writable_existing', 'replacement_creatable')) for row in observation['files'])
               and before == {str(path): sha(path) for path in targets})
    receipt = {'passed': allowed, 'observations': observation, 'host_bytes_unchanged': before == {str(p): sha(p) for p in targets},
               'scope': 'These named roots denied read/write/replacement in the tested namespace; no assertion about undisclosed copies, prior exposure or independent scientific blinding.'}
    write_json(scratch / 'probe.json', receipt)
    if not allowed:
        raise ValidationError('Reference isolation probe failed; model execution prohibited')
    return receipt


def prepare_native_session(directory, plan_digest, plugin, invocation, output, *, references=None, timeout_seconds=1800):
    if sys.platform != 'linux':
        raise ValidationError('Integrated isolated collection requires Linux/WSL; offline capture remains available on other platforms')
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 86400:
        raise ValidationError('Explicit session timeout must be 1..86400 seconds')
    output, plugin, directory = _fresh(output), Path(plugin).resolve(), Path(directory).resolve()
    references = Path(references).resolve() if references is not None else None
    if references is not None:
        _separate(directory, references)
    private = [directory] + ([references] if references is not None else [])
    for a in (output, plugin):
        for b in private:
            _separate(a, b)
    _separate(plugin, output)
    plan = _sources(directory, plan_digest, plugin, references)
    argv, price = _invocation(invocation, plugin, output, plan)
    executable = shutil.which(argv[0])
    bwrap = shutil.which('bwrap')
    if not executable or not bwrap:
        raise ValidationError('Existing Claude executable and bubblewrap required; nothing is installed automatically')
    executable, bwrap = str(Path(executable).resolve()), str(Path(bwrap).resolve())
    for root in private:
        if any(Path(path).is_relative_to(root) for path in (executable, bwrap, sys.executable)):
            raise ValidationError('A private reference root contains a required executable')
    version = subprocess.run([executable, '--version'], stdin=subprocess.DEVNULL, capture_output=True,
                             text=True, timeout=20, shell=False)
    if version.returncode or version.stdout.strip() != '2.1.278 (Claude Code)':
        raise ValidationError('Automatic binding profile is limited to observed Claude Code 2.1.278; use offline capture for other versions')
    argv[0] = executable
    output.mkdir(parents=True)
    writable = [output / 'native', output / 'retained']
    for path in writable:
        path.mkdir()
    config = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))).resolve()
    if config.is_dir():
        for other in (*private, plugin, output, Path(__file__).resolve().parent):
            _separate(config, other)
        writable.append(config)
    targets = [directory / 'plan.json'] + [confined(references, name) for name in plan['references']]
    isolation = probe_namespace(private, targets, output / 'isolation-preflight', bwrap, writable)
    # Host-side --version can succeed via WSL interop while the isolated launch
    # correctly denies that escape. Verify the real namespace before authorization.
    isolated_version = subprocess.run(
        _namespace([executable, '--version'], private, output / 'isolation-preflight', bwrap, writable),
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20, shell=False)
    if isolated_version.returncode or isolated_version.stdout.strip() != '2.1.278 (Claude Code)':
        raise ValidationError('Claude cannot start inside the reference-isolation namespace; use a compatible Linux executable. Model was not launched')
    frozen = {'schema_version': 1, 'evidence_plan': str(directory), 'evidence_plan_sha256': plan_digest,
              'plugin': str(plugin), 'references': str(references) if references else None, 'argv': argv,
              'private_roots': [str(p) for p in private], 'probe_targets': [str(p) for p in targets],
              'writable_roots': [str(p) for p in writable],
              'bwrap': bwrap, 'bwrap_sha256': sha(bwrap), 'executable_sha256': sha(executable),
              'python': sys.executable, 'python_sha256': sha(sys.executable),
              'timeout_seconds': timeout_seconds, 'estimated_ceiling_usd': price,
              'expected_sessions': sum(c['repetitions'] * 2 for c in plan['contract']['cases']),
              'isolation_preflight': isolation, 'isolated_cli_version': isolated_version.stdout.strip(),
              'automatic_retry': False, 'model_calls': 0}
    write_json(output / 'session-plan.json', frozen)
    disclosure = {'collected': ['selected case/plugin bytes and versions', 'available native session/load/Skill/tool events',
                                'declared input and output files with hashes', 'original native result, errors and partial runs'],
                  'purpose': 'Link the existing native execution to independent offline scientific checks without rewriting cases',
                  'invocation': argv, 'expected_sessions': frozen['expected_sessions'],
                  'reference_roots': frozen['private_roots'], 'host_profile': frozen['isolated_cli_version'],
                  'cost': {'native_estimate_ceiling_usd': price, 'can_overrun_in_flight': True, 'settled_usd': None,
                           'offline_grading_model_calls': 0}, 'authorization': 'Running requires --execute and this exact session digest',
                  'limitations': ['No new observations are fabricated for old results', 'Local namespace checks are not independent review or full blinding',
                                  'Native tools retain their original grants; no real MCP startup or publication is enabled'],
                  'writable_roots': frozen['writable_roots']}
    write_json(output / 'COLLECTION.json', disclosure)
    (output / 'COLLECTION.md').write_text('# 原生附加采集\n\n沿用已有用例；采集范围与费用见 COLLECTION.json。\n\n'
        '执行将使用既有 Claude 账户与配置，发送原任务和选定插件给其模型提供方；本工具不自动购买、重试或发布。\n'
        '评分参考与冻结计划在执行子进程的挂载命名空间中隐藏；运行退出后父进程才收集、评分。\n'
        '原始 stdout/stderr、失败和残缺结果保留；崩溃后使用 finish-native-session，不再次启动模型。\n', encoding='utf-8')
    return {'output': str(output), 'session_sha256': suite_digest(frozen), 'model_calls': 0, 'disclosure': disclosure}


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
    if sys.platform != 'linux' or (root / 'started.json').exists():
        raise ValidationError('This frozen Linux/WSL session can be attempted only once; inspect or finish existing evidence')
    if sys.executable != frozen['python'] or sha(sys.executable) != frozen['python_sha256']:
        raise ValidationError('Collector Python changed after freeze')
    for path, digest in ((frozen['argv'][0], frozen['executable_sha256']), (frozen['bwrap'], frozen['bwrap_sha256'])):
        if sha(path) != digest:
            raise ValidationError('Native executable or isolation backend changed')
    _sources(frozen['evidence_plan'], frozen['evidence_plan_sha256'], frozen['plugin'], frozen['references'])
    # Exclusive marker protects against concurrent execution and uncertain-result retries.
    with (root / 'started.json').open('x', encoding='utf-8') as stream:
        import json
        json.dump({'session_sha256': pin, 'execute': True, 'automatic_retry': False}, stream)
    probe_namespace(frozen['private_roots'], frozen['probe_targets'], root / 'isolation-execution', frozen['bwrap'], frozen['writable_roots'])
    retained = root / 'retained'
    command = _namespace(frozen['argv'], frozen['private_roots'], root / 'isolation-execution', frozen['bwrap'], frozen['writable_roots'])
    env = dict(os.environ, TMPDIR=str(retained), TMP=str(retained), TEMP=str(retained))
    from .codex import _run
    try:
        process = _run(command, env, frozen['plugin'], '', root / 'native-process', frozen['timeout_seconds'])
    except (OSError, subprocess.SubprocessError) as exc:
        # A launcher exception need not prove all descendants have terminated.
        write_json(root / 'interrupted.json', {'error': str(exc), 'process_state': 'UNKNOWN', 'settled_usd': None})
        raise
    write_json(root / 'process.json', process)
    return finish_native_session(root, pin)
