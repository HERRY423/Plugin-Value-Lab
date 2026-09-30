"""Networkless model hosts with a parent-owned, fixed-destination API broker.

The broker is a capability boundary, not a generic HTTP/CONNECT proxy. The
container image / selected runtime and this controller are trusted components.
"""
from pathlib import Path
import base64
import hashlib
import http.client
import ipaddress
import json
import os
import queue
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit

from .core import ValidationError, load_json, suite_digest, write_json
from .artifacts import confined, sha
from .native_evidence import _fresh, _separate

PROFILE = 'NETWORKLESS_HOST_WITH_MODEL_BROKER_V1'
BRIDGE = Path(__file__).resolve().parents[1] / 'scripts/model_bridge.py'
MAX_FRAME = 4 * 1024 * 1024


def validate_config(config):
    if not isinstance(config, dict) or set(config) != {'format', 'backend', 'runtime', 'executable', 'gateway'}:
        raise ValidationError('Sandbox config requires format/backend/runtime/executable/gateway')
    if config['format'] != 'pvl-online-sandbox-1' or config['backend'] not in ('bubblewrap', 'windows-hyperv'):
        raise ValidationError('Use bubblewrap or windows-hyperv; no masking/host-network fallback')
    executable = config['executable']
    if (not isinstance(executable, str) or not re.fullmatch(r'[A-Za-z0-9_.\-/]+', executable)
            or executable.startswith(('/', '-')) or '..' in executable.split('/')):
        raise ValidationError('Executable must be relative to the selected runtime')
    if not isinstance(config['runtime'], str) or not config['runtime']:
        raise ValidationError('Supply a curated runtime directory or pinned local Windows image')
    if config['backend'] == 'windows-hyperv' and not re.fullmatch(r'sha256:[0-9a-f]{64}', config['runtime']):
        raise ValidationError('Windows requires an immutable local image ID, not a mutable tag or automatic pull')
    g = config['gateway']
    required = {'endpoint', 'models', 'api_key_env', 'max_requests', 'max_output_tokens', 'request_timeout_seconds'}
    if not isinstance(g, dict) or set(g) != required:
        raise ValidationError('Gateway requires endpoint/models/api_key_env/max_requests/max_output_tokens/request_timeout_seconds')
    if not isinstance(g['endpoint'], str):
        raise ValidationError('Model endpoint must be a string')
    endpoint = urlsplit(g['endpoint'])
    if (endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username or endpoint.password
            or endpoint.port not in (None, 443) or endpoint.path not in ('', '/') or endpoint.query or endpoint.fragment
            or not re.fullmatch(r'[A-Za-z0-9.-]+', endpoint.hostname) or '.' not in endpoint.hostname):
        raise ValidationError('Gateway endpoint must be one HTTPS origin on port 443')
    try:
        address = ipaddress.ip_address(endpoint.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValidationError('Private/loopback model endpoints are not supported')
    if endpoint.hostname.endswith(('.localhost', '.local', '.internal')):
        raise ValidationError('Private model endpoint is not supported')
    if (not isinstance(g['models'], list) or not g['models'] or len(g['models']) > 8
            or any(not isinstance(m, str) or not re.fullmatch(r'[A-Za-z0-9._:/-]{1,150}', m) for m in g['models'])
            or len(set(g['models'])) != len(g['models'])):
        raise ValidationError('Select explicit unique model IDs')
    if not isinstance(g['api_key_env'], str) or not re.fullmatch(r'PVL_[A-Z0-9_]+', g['api_key_env']):
        raise ValidationError('Use a dedicated PVL_ credential environment variable')
    for key, ceiling in [('max_requests', 1000), ('max_output_tokens', 100000), ('request_timeout_seconds', 120)]:
        if type(g[key]) is not int or not 1 <= g[key] <= ceiling:
            raise ValidationError('Invalid bounded gateway setting: ' + key)
    return config


def runtime_inventory(root):
    root = Path(root).resolve()
    if not root.is_dir() or root == root.parent or str(root) in ('/usr', '/usr/bin', '/home', '/mnt', '/etc', '/run'):
        raise ValidationError('Select a curated runtime bundle, not a host/system root')
    result, size = {}, 0
    for candidate in root.rglob('*'):
        relative = candidate.relative_to(root).as_posix()
        path = confined(root, relative)
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise ValidationError('Runtime hard links are not accepted')
            size += path.stat().st_size
            if size > 1024 ** 3 or len(result) >= 10000:
                raise ValidationError('Runtime exceeds 1 GiB / 10000 files')
            result[relative] = sha(path)
    if not result:
        raise ValidationError('Runtime is empty')
    return result


def clean_environment(root):
    # No HOME, PATH wrappers, proxy settings, API credentials, Docker contexts,
    # PYTHONPATH, LD_PRELOAD, WSL interop or host CLI configuration inheritance.
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
    if os.name == 'nt':
        system = os.environ.get('SystemRoot', r'C:\Windows')
        env = {'SystemRoot': system, 'PATH': system + r'\System32', 'TEMP': str(root), 'TMP': str(root)}
    env['DOCKER_CONFIG'] = str(Path(root) / 'docker-config')
    return env


def sandbox_command(config, plugin, output, control, command, backend_path, *, name=None, public_plugin=None):
    """Only plugin, two result directories, runtime and trusted bridge are exposed.

    Keep public absolute paths identical in the guest, so tracePath/init.cwd are
    still verifiable without rewriting native evidence after execution.
    """
    plugin, output, control = map(Path, (plugin, output, control))
    public_plugin = Path(public_plugin) if public_plugin is not None else plugin
    if config['backend'] == 'bubblewrap':
        argv = [backend_path, '--unshare-all', '--unshare-user', '--uid', '65534', '--gid', '65534',
                '--disable-userns', '--new-session', '--die-with-parent', '--cap-drop', 'ALL', '--clearenv',
                '--setenv', 'PATH', '/runtime:/usr/bin:/bin', '--setenv', 'HOME', '/tmp/home',
                '--setenv', 'LANG', 'C.UTF-8', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/etc']
        for path in ('/usr/bin', '/usr/lib', '/usr/lib64', '/bin', '/lib', '/lib64'):
            if Path(path).exists():
                argv.extend(['--ro-bind', path, path])
        argv.extend(['--ro-bind', config['runtime'], '/runtime', '--ro-bind', str(public_plugin), str(plugin),
                     '--ro-bind', str(control), '/pvl-control'])
        for sub in ('native', 'retained'):
            path = str(output / sub)
            argv.extend(['--bind', path, path])
        return argv + ['--chdir', str(plugin), '--remount-ro', '/', '--', *command]
    if not name or not re.fullmatch(r'pvl-[0-9a-f]{32}', name):
        raise ValidationError('Container requires an invocation-owned random name')
    # A Windows guest kernel, not Docker Desktop's Linux/WSL backend. Never
    # mount a daemon pipe, host drive, HOME or a credential/config directory.
    argv = [backend_path, '--host', 'npipe:////./pipe/docker_engine', 'run', '--rm', '-i', '--pull=never',
            '--name', name, '--isolation=hyperv', '--network=none', '--memory=2g', '--cpu-count=2',
            '--user=ContainerUser', '--workdir', str(plugin)]
    for source, target, readonly in [(public_plugin, plugin, True), (control, Path(r'C:\pvl-control'), True),
                                     (output / 'native', output / 'native', False),
                                     (output / 'retained', output / 'retained', False)]:
        if any(c in str(source) + str(target) for c in ',\r\n'):
            raise ValidationError('Mount paths cannot contain separators')
        argv += ['--mount', f'type=bind,source={source},target={target}' + (',readonly' if readonly else '')]
    # Explicit Python image contract: C:\runtime\python.exe and a relative
    # executable in C:\runtime. The entrypoint never inherits an image launcher.
    return argv + ['--entrypoint', command[0], config['runtime'], *command[1:]]


def remove_container(backend, name, root):
    result = subprocess.run([backend, '--host', 'npipe:////./pipe/docker_engine', 'rm', '--force', name],
                   env=clean_environment(root), stdin=subprocess.DEVNULL, capture_output=True, timeout=15, shell=False)
    if result.returncode and b'No such container' not in result.stderr:
        raise ValidationError('Owned container termination is unknown; inspect it before offline recovery')


def probe_backend(config, plugin, output, control, backend_path, targets, public_plugin=None):
    windows = config['backend'] == 'windows-hyperv'
    prefix = r'C:\runtime' if windows else '/runtime'
    python = r'C:\runtime\python.exe' if windows else '/usr/bin/python3'
    bridge = r'C:\pvl-control\model_bridge.py' if windows else '/pvl-control/model_bridge.py'
    executable = prefix + ('\\' if windows else '/') + config['executable'].replace('/', '\\' if windows else '/')
    payload = {'targets': [str(p) for p in targets], 'executable': executable, 'windows': windows,
               'parent_net_ns': None if windows else os.stat('/proc/self/ns/net').st_ino}
    name = 'pvl-' + uuid.uuid4().hex
    argv = sandbox_command(config, plugin, output, control,
                           [python, '-I', bridge, '--probe', json.dumps(payload)], backend_path, name=name, public_plugin=public_plugin)
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45,
                                env=clean_environment(output), close_fds=True, shell=False)
    finally:
        if windows:
            remove_container(backend_path, name, output)
    if result.returncode:
        raise ValidationError('Networkless runtime preflight failed; model was not launched: ' + result.stderr[:300])
    try:
        receipt = json.loads(result.stdout)
        if (receipt['version'] != '2.1.278 (Claude Code)' or not receipt['checks']
                or not all(v is True for v in receipt['checks'].values())
                or len(receipt['checks']) < len(targets) + 4):
            raise ValueError('boundary or native CLI version check failed')
    except (KeyError, ValueError, TypeError) as exc:
        raise ValidationError('Sandbox boundary preflight did not pass') from exc
    return receipt


class ModelGateway:
    def __init__(self, config, secret, transport=None):
        self.config = config
        if not isinstance(secret, str) or not secret or any(c in secret for c in '\r\n'):
            raise ValidationError('Dedicated model credential unavailable or invalid')
        self._secret = secret
        self.transport = transport or self._https
        self.requests, self.events = 0, []
        self.cancelled = threading.Event()

    def request(self, message, remaining):
        # Treat even bridge messages as untrusted. A compromised sandbox cannot
        # choose another host, forward credentials, CONNECT, redirect or retry.
        if self.cancelled.is_set() or remaining <= 0:
            raise ValidationError('Model request deadline expired')
        if not isinstance(message, dict) or set(message) != {'kind', 'id', 'path', 'body', 'beta'}:
            raise ValidationError('Invalid model broker frame')
        if message['kind'] != 'request' or type(message['id']) is not int or message['id'] != self.requests + 1:
            raise ValidationError('Non-sequential/replayed model request')
        if message['path'] not in ('/v1/messages', '/v1/messages?beta=true', '/v1/messages/count_tokens', '/v1/messages/count_tokens?beta=true'):
            raise ValidationError('Model API path is not allowed')
        if self.requests >= self.config['max_requests']:
            raise ValidationError('Frozen model request ceiling exhausted')
        if not isinstance(message['beta'], str) or not re.fullmatch(r'[A-Za-z0-9,._-]{0,512}', message['beta']):
            raise ValidationError('Invalid Anthropic beta header')
        try:
            body = base64.b64decode(message['body'], validate=True)
            if len(body) > 2 * 1024 * 1024:
                raise ValueError('request exceeds 2 MiB')
            payload = json.loads(body)
            if not isinstance(payload, dict) or payload.get('model') not in self.config['models']:
                raise ValueError('model is not allowed')
            if '/count_tokens' not in message['path']:
                if type(payload.get('max_tokens')) is not int or not 1 <= payload['max_tokens'] <= self.config['max_output_tokens']:
                    raise ValueError('output token ceiling exceeded')
        except (ValueError, TypeError) as exc:
            raise ValidationError('Invalid/budget-exceeding model request') from exc
        self.requests += 1  # Reserve BEFORE transport; uncertain responses are never retried.
        event = {'id': self.requests, 'path': message['path'], 'body_sha256': hashlib.sha256(body).hexdigest(),
                 'request_bytes': len(body), 'state': 'UNKNOWN', 'settled_usd': None}
        self.events.append(event)
        try:
            status, content_type, response = self.transport(message['path'], body, message['beta'],
                min(remaining, self.config['request_timeout_seconds']))
            if status not in range(200, 300):
                event['state'] = 'HTTP_ERROR'
                event['http_status'] = status
                raise ValidationError('Provider error/redirect; no automatic retry')
            if not isinstance(response, bytes) or len(response) > 8 * 1024 * 1024:
                raise ValidationError('Provider response exceeds 8 MiB')
            event.update(state='RESPONSE_RECEIVED', http_status=status, response_bytes=len(response))
            return status, 'text/event-stream' if content_type.startswith('text/event-stream') else 'application/json', response
        except Exception:
            # Do not leak provider exceptions (URLs/headers/credentials) into logs.
            raise ValidationError('Model request failed or was refused; charge/response may be unknown; no retry') from None

    def _https(self, path, body, beta, timeout):
        started = time.monotonic()
        host = urlsplit(self.config['endpoint']).hostname
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ValidationError('Endpoint DNS includes a non-public address')
        # Pin the validated address at connect, retaining TLS hostname validation.
        address = addresses[0][4][0]
        def remaining():
            left = timeout - (time.monotonic() - started)
            if self.cancelled.is_set() or left <= 0:
                raise TimeoutError()
            return left
        connection = http.client.HTTPSConnection(host, timeout=remaining(), context=ssl.create_default_context())
        def connect():
            raw = socket.create_connection((address, 443), remaining())
            try:
                raw.settimeout(remaining())
                connection.sock = connection._context.wrap_socket(raw, server_hostname=host)
            except Exception:
                raw.close()
                raise
        connection.connect = connect
        try:
            headers = {'content-type': 'application/json', 'anthropic-version': '2023-06-01', 'x-api-key': self._secret}
            if beta:
                headers['anthropic-beta'] = beta
            remaining()
            connection.request('POST', path, body=body, headers=headers)
            response = connection.getresponse()
            data = bytearray()
            while True:
                left = remaining()
                if connection.sock:
                    connection.sock.settimeout(left)
                chunk = response.read1(32768)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > 8 * 1024 * 1024:
                    raise ValueError('response limit')
            return response.status, response.getheader('content-type', ''), bytes(data)
        finally:
            connection.close()


def run_exchange(argv, env, cwd, output, gateway, timeout, *, cleanup=None):
    """Bounded framed pipe RPC; child never receives a host socket or secret."""
    from .processes import bind_tree, close_tree
    output = Path(output)
    output.mkdir()
    deadline = time.monotonic() + timeout
    messages, errors, stop = queue.Queue(8), queue.Queue(1), threading.Event()
    process, reported_exit, failure, traffic = None, None, None, 0
    with (output / 'launcher-stderr.txt').open('wb') as stderr, (output / 'stdout.txt').open('wb') as stdout, (output / 'stderr.txt').open('wb') as logs:
        try:
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, cwd=cwd,
                env=env, shell=False, close_fds=True, start_new_session=os.name != 'nt')
            bind_tree(process)
            def read():
                try:
                    while not stop.is_set():
                        line = process.stdout.readline(MAX_FRAME + 1)
                        while not stop.is_set():
                            try:
                                messages.put(line, timeout=.1)
                                break
                            except queue.Full:
                                pass
                        if not line or len(line) > MAX_FRAME:
                            return
                except OSError:
                    pass
            threading.Thread(target=read, daemon=True).start()
            def send(frame):
                data = (json.dumps(frame, ensure_ascii=True, allow_nan=False) + '\n').encode()
                completed = threading.Event()
                def write():
                    try:
                        process.stdin.write(data)
                        process.stdin.flush()
                    except (OSError, ValueError):
                        errors.put_nowait('pipe write failed')
                    finally:
                        completed.set()
                threading.Thread(target=write, daemon=True).start()
                if not completed.wait(max(0, deadline - time.monotonic())) or not errors.empty():
                    raise ValidationError('Broker pipe stalled or closed')
            while True:
                if time.monotonic() >= deadline or stderr.tell() > 8 * 1024 * 1024:
                    raise ValidationError('Session deadline or launcher log limit exceeded')
                try:
                    line = messages.get(timeout=.1)
                except queue.Empty:
                    continue
                if not line:
                    break
                traffic += len(line)
                if len(line) > MAX_FRAME or traffic > 64 * 1024 * 1024 or not line.endswith(b'\n'):
                    raise ValidationError('Sandbox protocol resource limit exceeded')
                msg = json.loads(line)
                if not isinstance(msg, dict):
                    raise ValidationError('Sandbox frame must be an object')
                if reported_exit is not None:
                    raise ValidationError('Sandbox wrote after completion')
                if msg.get('kind') == 'log' and set(msg) == {'kind', 'stream', 'data'} and msg['stream'] in ('stdout', 'stderr'):
                    data = base64.b64decode(msg['data'], validate=True)
                    (stdout if msg['stream'] == 'stdout' else logs).write(data)
                elif msg.get('kind') == 'exit' and set(msg) == {'kind', 'code'} and type(msg['code']) is int:
                    reported_exit = msg['code']
                else:
                    response = queue.Queue(1)
                    def fetch(message=msg):
                        try:
                            response.put((True, gateway.request(message, deadline - time.monotonic())))
                        except Exception:
                            response.put((False, None))
                    threading.Thread(target=fetch, daemon=True).start()
                    try:
                        valid, value = response.get(timeout=max(.001, deadline - time.monotonic()))
                    except queue.Empty:
                        raise ValidationError('Model request exceeded session deadline; settlement remains unknown') from None
                    if not valid:
                        raise ValidationError('Model request refused or failed; no retry')
                    status, content_type, body = value
                    send({'kind': 'response', 'id': msg['id'], 'status': status, 'content_type': content_type, 'length': len(body)})
                    for offset in range(0, len(body), 32768):
                        send({'kind': 'data', 'id': msg['id'], 'data': base64.b64encode(body[offset:offset+32768]).decode('ascii')})
                    send({'kind': 'end', 'id': msg['id']})
            process.wait(timeout=max(.01, deadline - time.monotonic()))
            if process.returncode != 0 or reported_exit is None:
                raise ValidationError('Sandbox ended without a successful bridge exit')
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            failure = str(exc)[:300] if isinstance(exc, ValidationError) else type(exc).__name__
        finally:
            stop.set()
            gateway.cancelled.set()
            if process is not None:
                close_tree(process)
                for pipe in (process.stdin, process.stdout):
                    try:
                        pipe.close()
                    except (OSError, ValueError):
                        pass
            if cleanup:
                cleanup()
    receipt = {'exit_code': reported_exit, 'error': failure, 'timed_out': time.monotonic() >= deadline,
               'gateway_requests': gateway.requests, 'gateway_events': gateway.events, 'settled_usd': None,
               'network_policy': 'NO_CHILD_NETWORK_FIXED_PROVIDER_RPC', 'credentials_in_child': False,
               'automatic_retry': False, 'status': 'COMPLETED' if failure is None and reported_exit == 0 else 'FAILED'}
    write_json(output / 'receipt.json', receipt)
    return receipt


def inspect_windows_backend(backend, config, root):
    def inspect(args):
        proc = subprocess.run([backend, '--host', 'npipe:////./pipe/docker_engine', *args],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20, shell=False, env=clean_environment(root))
        if proc.returncode:
            raise ValidationError('Windows Hyper-V container engine/image unavailable; no WSL or process-isolation fallback')
        return json.loads(proc.stdout)
    server = inspect(['version', '--format', '{{json .Server}}'])
    if not isinstance(server, dict) or server.get('Os') != 'windows':
        raise ValidationError('A native Windows Docker engine is required; Linux/WSL engines are not equivalent')
    image = inspect(['image', 'inspect', config['runtime'], '--format', '{{json .}}'])
    if image.get('Os') != 'windows' or image.get('Id') != config['runtime'] or image.get('Config', {}).get('Volumes'):
        raise ValidationError('Require a pinned Windows image without implicit volumes')
    return {'image_id': image['Id'], 'guest_os': 'windows', 'isolation': 'hyperv', 'daemon_version': server.get('Version')}


def prepare_session(directory, plan_digest, plugin, invocation, output, *, references=None, timeout_seconds=1800, sandbox=None):
    from .native_session import _sources, _invocation
    if sandbox is None:
        raise ValidationError('Explicit --sandbox config required; online host-root masking has been retired')
    config = json.loads(json.dumps(validate_config(sandbox)))
    windows = config['backend'] == 'windows-hyperv'
    if (windows and sys.platform != 'win32') or (not windows and sys.platform != 'linux'):
        raise ValidationError('Selected backend does not match this OS: Windows uses Hyper-V, Linux uses bubblewrap')
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 86400:
        raise ValidationError('Explicit timeout must be 1..86400 seconds')
    output, plugin, directory = _fresh(output), Path(plugin).resolve(), Path(directory).resolve()
    references = Path(references).resolve() if references is not None else None
    private = [directory] + ([references] if references else [])
    for a in (output, plugin):
        for b in private:
            _separate(a, b)
    _separate(output, plugin)
    plan = _sources(directory, plan_digest, plugin, references)
    argv, ceiling = _invocation(invocation, plugin, output, plan)
    requested_models = [argv[i+1] for i, v in enumerate(argv[:-1]) if v in ('--model', '--judge-model')]
    if any(model not in config['gateway']['models'] for model in requested_models):
        raise ValidationError('Native models must be explicitly allowed by the model gateway')
    backend = shutil.which('docker' if windows else 'bwrap')
    if not backend:
        raise ValidationError('Selected OS sandbox backend unavailable; no fallback or automatic installation')
    backend = str(Path(backend).resolve())
    if not windows:
        runtime = Path(config['runtime']).resolve()
        config['runtime'] = str(runtime)
        for other in (*private, plugin, output):
            _separate(runtime, other)
        for exposed in ('/usr/bin', '/usr/lib', '/usr/lib64', '/bin', '/lib', '/lib64'):
            if any(p.is_relative_to(Path(exposed).resolve()) for p in (*private, output)):
                raise ValidationError('Private evidence cannot reside under exposed system runtime directories')
        runtime_pin = runtime_inventory(runtime)
        if config['executable'] not in runtime_pin:
            raise ValidationError('Selected native executable absent from runtime bundle')
    else:
        runtime_pin = None
    output.mkdir(parents=True)
    for name in ('native', 'retained', 'control', 'public-plugin', 'docker-config'):
        (output / name).mkdir()
    if windows:
        runtime_pin = inspect_windows_backend(backend, config, output)
    public_files = {**plan['plugin_files'], **plan['case_files']}
    for name, digest in public_files.items():
        source = confined(plugin, name)
        if sha(source) != digest or source.stat().st_nlink != 1:
            raise ValidationError('Selected public plugin bytes changed or linked')
        dest = confined(output / 'public-plugin', name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    shutil.copyfile(BRIDGE, output / 'control/model_bridge.py')
    prefix = r'C:\runtime' if windows else '/runtime'
    argv[0] = prefix + ('\\' if windows else '/') + config['executable'].replace('/', '\\' if windows else '/')
    # An unselected canary is deliberately readable to the parent, absent inside.
    (output / 'host-canary.txt').write_text(uuid.uuid4().hex, encoding='ascii')
    targets = [directory / 'plan.json', output / 'host-canary.txt'] + [confined(references, n) for n in plan['references']]
    isolation = probe_backend(config, plugin, output, output / 'control', backend, targets, output / 'public-plugin')
    frozen = {'schema_version': 2, 'isolation_profile': PROFILE, 'sandbox': config, 'runtime_pin': runtime_pin,
              'backend': backend, 'backend_sha256': sha(backend), 'bridge_sha256': sha(output / 'control/model_bridge.py'),
              'python': sys.executable, 'python_sha256': sha(sys.executable),
              'evidence_plan': str(directory), 'evidence_plan_sha256': plan_digest, 'plugin': str(plugin),
              'references': str(references) if references else None, 'argv': argv, 'public_files': public_files,
              'private_roots': [str(p) for p in private], 'probe_targets': [str(p) for p in targets],
              'timeout_seconds': timeout_seconds, 'estimated_ceiling_usd': ceiling,
              'expected_sessions': sum(c['repetitions'] * 2 for c in plan['contract']['cases']),
              'isolation_preflight': isolation, 'isolated_cli_version': isolation['version'],
              'network_isolated': True, 'host_root_mounted': False, 'credentials_in_child': False,
              'automatic_retry': False, 'model_calls': 0}
    write_json(output / 'session-plan.json', frozen)
    disclosure = {'invocation': argv, 'expected_sessions': frozen['expected_sessions'], 'profile': PROFILE,
                  'gateway': config['gateway'], 'host_root_mounted': False, 'credentials_in_child': False,
                  'model_calls': 0, 'isolation_preflight': isolation,
                  'cost': {'native_estimate_ceiling_usd': ceiling, 'request_ceiling': config['gateway']['max_requests'],
                           'can_overrun_in_flight': True, 'settled_usd': None},
                  'limitations': ['Provider RPC sends approved prompts to the selected model origin; no general network access.',
                                  'Request/token limits are not a guaranteed dollar spending cap.',
                                  'Trusted runtime/images must contain no secrets. Native eval case sealing is not independently established.',
                                  'Buffered SSE transport is bounded to 8 MiB and the configured request timeout.',
                                  'No actual model call is made during preparation; runtime/SDK compatibility needs a separately authorized pilot.']}
    write_json(output / 'COLLECTION.json', disclosure)
    (output / 'COLLECTION.md').write_text('# 在线原生隔离采集\n\n'
        '子进程断网、无宿主根与账户目录；只读公开插件快照，写入 native/ 与 retained/。\n\n'
        '模型请求通过父进程网关发送到冻结的 HTTPS 提供方；真实密钥只从指定 PVL_ 环境变量在执行时读取。'
        '允许发送的材料、模型、请求/输出令牌上限与费用估计见 COLLECTION.json。请求上限不是费用结算保证。\n\n'
        'Windows 使用原生 Windows 引擎与 Hyper-V 客体内核；后端缺失时阻断，禁止降级为共享宿主网络或进程遮蔽。'
        '预检不是实际模型试跑；SDK/宿主行为与完整盲法仍需独立验证。\n', encoding='utf-8')
    return {'output': str(output), 'session_sha256': suite_digest(frozen), 'model_calls': 0, 'disclosure': disclosure}


def run_session(root, frozen, pin):
    from .native_session import _sources, finish_native_session
    from .native import require_budget_boundary
    # Network/request/token limits alone do not enforce dollars. Refuse before
    # reading credentials, starting a child or contacting a model provider.
    if frozen.get('isolation_profile') != PROFILE:
        raise ValidationError('Legacy online masking plans cannot execute; prepare a networkless revision')
    config = validate_config(frozen['sandbox'])
    windows = config['backend'] == 'windows-hyperv'
    if (windows and sys.platform != 'win32') or (not windows and sys.platform != 'linux') or (root / 'started.json').exists():
        raise ValidationError('Frozen backend mismatch or already attempted; no automatic retry')
    if sys.executable != frozen['python'] or sha(sys.executable) != frozen['python_sha256']:
        raise ValidationError('Collector Python changed')
    if sha(frozen['backend']) != frozen['backend_sha256'] or sha(BRIDGE) != frozen['bridge_sha256']:
        raise ValidationError('Isolation backend/bridge changed')
    if runtime_inventory(root / 'control') != {'model_bridge.py': frozen['bridge_sha256']}:
        raise ValidationError('Bridge snapshot changed')
    if runtime_inventory(root / 'public-plugin') != frozen['public_files']:
        raise ValidationError('Public plugin snapshot changed')
    runtime_pin = inspect_windows_backend(frozen['backend'], config, root) if windows else runtime_inventory(config['runtime'])
    if runtime_pin != frozen['runtime_pin']:
        raise ValidationError('Frozen runtime changed')
    _sources(frozen['evidence_plan'], frozen['evidence_plan_sha256'], frozen['plugin'], frozen['references'])
    require_budget_boundary()
    gateway = ModelGateway(config['gateway'], os.environ.get(config['gateway']['api_key_env']))
    probe_backend(config, frozen['plugin'], root, root / 'control', frozen['backend'], frozen['probe_targets'], root / 'public-plugin')
    # Reserve the entire session exclusively before any model request.
    with (root / 'started.json').open('x', encoding='utf-8') as stream:
        json.dump({'session_sha256': pin, 'execute': True, 'automatic_retry': False}, stream)
    spec = {'argv': frozen['argv'], 'plugin': frozen['plugin'], 'retained': str(root / 'retained'),
            'path': r'C:\runtime;C:\Windows\System32' if windows else '/runtime:/usr/bin:/bin'}
    python = r'C:\runtime\python.exe' if windows else '/usr/bin/python3'
    bridge = r'C:\pvl-control\model_bridge.py' if windows else '/pvl-control/model_bridge.py'
    name = 'pvl-' + uuid.uuid4().hex
    argv = sandbox_command(config, frozen['plugin'], root, root / 'control',
        [python, '-I', bridge, '--run', json.dumps(spec)], frozen['backend'], name=name, public_plugin=root / 'public-plugin')
    try:
        process = run_exchange(argv, clean_environment(root), root, root / 'native-process', gateway,
            frozen['timeout_seconds'], cleanup=(lambda: remove_container(frozen['backend'], name, root)) if windows else None)
    except (OSError, ValueError, subprocess.SubprocessError):
        write_json(root / 'interrupted.json', {'process_state': 'UNKNOWN', 'settled_usd': None, 'automatic_retry': False})
        raise
    write_json(root / 'process.json', process)
    return finish_native_session(root, pin)
