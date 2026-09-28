"""Policy/transport fixtures. Real kernel acceptance is a separate script."""
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from value_lab.core import ValidationError, load_json, suite_digest, write_json
from value_lab.native_session import prepare_native_session, run_native_session
from value_lab.online_sandbox import (BRIDGE, ModelGateway, PROFILE, clean_environment, inspect_windows_backend,
                                      run_exchange, sandbox_command, validate_config, runtime_inventory)


def config():
    return {'format': 'pvl-online-sandbox-1', 'backend': 'bubblewrap', 'runtime': '/selected/runtime',
            'executable': 'claude', 'gateway': {'endpoint': 'https://api.example.com', 'models': ['selected-model'],
            'api_key_env': 'PVL_MODEL_API_KEY', 'max_requests': 2, 'max_output_tokens': 100, 'request_timeout_seconds': 5}}


def request(rid=1, **changes):
    value = {'kind': 'request', 'id': rid, 'path': '/v1/messages', 'beta': '',
             'body': base64.b64encode(json.dumps({'model': 'selected-model', 'max_tokens': 20, 'messages': []}).encode()).decode()}
    value.update(changes)
    return value


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def transport(*args):
            self.calls.append(args)
            return 200, 'application/json', b'{"fixture":true}'
        self.gateway = ModelGateway(config()['gateway'], 'private-synthetic-key', transport)

    def test_exact_model_route_and_secret_free_receipt(self):
        self.assertEqual(self.gateway.request(request(), 5)[2], b'{"fixture":true}')
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn('private-synthetic-key', json.dumps(self.gateway.events))
        self.assertIsNone(self.gateway.events[0]['settled_usd'])

    def test_ssrf_alternate_routes_connect_encoding_and_query_rejected(self):
        for path in ('https://evil.example/v1/messages', '//evil.example', '/v1/messages/../files',
                     '/v1/%6dessages', '/v1/messages?url=http://localhost', '/v1/files', '/v1/messages\r\nHost: evil'):
            with self.assertRaises(ValidationError):
                self.gateway.request(request(path=path), 5)
        with self.assertRaises(ValidationError):
            self.gateway.request(request(method='CONNECT'), 5)
        self.assertFalse(self.calls)

    def test_model_token_type_and_request_ceilings(self):
        for body in ({'model': 'other', 'max_tokens': 1}, {'model': 'selected-model', 'max_tokens': 101},
                     {'model': 'selected-model', 'max_tokens': True}, {'model': 'selected-model'}):
            with self.assertRaises(ValidationError):
                self.gateway.request(request(body=base64.b64encode(json.dumps(body).encode()).decode()), 5)
        self.gateway.request(request(), 5)
        self.gateway.request(request(2), 5)
        with self.assertRaisesRegex(ValidationError, 'ceiling'):
            self.gateway.request(request(3), 5)
        self.assertEqual(len(self.calls), 2)

    def test_uncertain_request_reserved_no_retry_or_secret_in_error(self):
        self.gateway.transport = lambda *a: (_ for _ in ()).throw(OSError('private-synthetic-key'))
        with self.assertRaises(ValidationError) as error:
            self.gateway.request(request(), 5)
        self.assertNotIn('private-synthetic-key', str(error.exception))
        self.assertEqual(self.gateway.requests, 1)
        self.assertEqual(self.gateway.events[0]['state'], 'UNKNOWN')
        with self.assertRaisesRegex(ValidationError, 'replayed'):
            self.gateway.request(request(), 5)

    def test_redirect_and_provider_error_are_terminal(self):
        for status in (301, 307, 401, 429, 500):
            gateway = ModelGateway(config()['gateway'], 'test-key', lambda *a: (status, 'text/plain', b'private response'))
            with self.assertRaises(ValidationError):
                gateway.request(request(), 5)
            self.assertEqual(gateway.events[0]['http_status'], status)
            self.assertEqual(gateway.requests, 1)

    def test_private_dns_denied_before_connect(self):
        gateway = ModelGateway(config()['gateway'], 'test-key')
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]), \
             patch('socket.create_connection', side_effect=AssertionError('Must not connect')):
            with self.assertRaises(ValidationError):
                gateway.request(request(), 5)

    def test_fixed_endpoint_and_dedicated_credential_policy(self):
        for endpoint in ('http://api.example.com', 'https://127.0.0.1', 'https://169.254.169.254',
                         'https://api.example.com:8443', 'https://key@api.example.com', 'https://api.example.com/redirect'):
            value = config()
            value['gateway']['endpoint'] = endpoint
            with self.assertRaises(ValidationError):
                validate_config(value)
        value = config()
        value['gateway']['api_key_env'] = 'HOME'
        with self.assertRaises(ValidationError):
            validate_config(value)

    def test_no_host_environment_is_carried_to_launcher(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'private', 'HTTPS_PROXY': 'private', 'LD_PRELOAD': 'private',
                                     'DOCKER_HOST': 'tcp://attacker:2375', 'PVL_MODEL_API_KEY': 'private'}):
            env = clean_environment(Path('run'))
        self.assertTrue(set(env).isdisjoint({'ANTHROPIC_API_KEY', 'HTTPS_PROXY', 'LD_PRELOAD', 'DOCKER_HOST', 'PVL_MODEL_API_KEY'}))

    def test_windows_backend_enforces_native_hyperv_and_no_network(self):
        value = config()
        value.update(backend='windows-hyperv', runtime='sha256:' + 'a' * 64, executable='claude.exe')
        validate_config(value)
        argv = sandbox_command(value, Path('public'), Path('out'), Path('control'),
                               ['python.exe', 'bridge.py'], 'docker.exe', name='pvl-' + 'a' * 32)
        self.assertIn('--isolation=hyperv', argv)
        self.assertIn('--network=none', argv)
        self.assertIn('--pull=never', argv)
        self.assertIn('--user=ContainerUser', argv)
        self.assertNotIn('--privileged', argv)
        mounts = [argv[i+1] for i, v in enumerate(argv[:-1]) if v == '--mount']
        self.assertEqual(len(mounts), 4)
        self.assertFalse(any('docker_engine' in item for item in mounts))

    def test_windows_linux_engine_or_missing_engine_is_not_downgraded(self):
        value = config()
        value.update(backend='windows-hyperv', runtime='sha256:' + 'a' * 64)
        for response in (subprocess.CompletedProcess([], 1, '', 'missing'),
                         subprocess.CompletedProcess([], 0, '{"Os":"linux"}', '')):
            with patch('value_lab.online_sandbox.subprocess.run', return_value=response), self.assertRaises(ValidationError):
                inspect_windows_backend('docker', value, Path('run'))

    def test_legacy_online_plan_cannot_execute_even_with_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            frozen = {'isolation_profile': 'ONLINE_NAMED_ROOT_MASKING'}
            write_json(Path(tmp) / 'session-plan.json', frozen)
            with self.assertRaisesRegex(ValidationError, 'Legacy'):
                run_native_session(tmp, suite_digest(frozen), execute=True)

    def test_no_implicit_fallback_without_explicit_sandbox(self):
        with self.assertRaisesRegex(ValidationError, 'retired'):
            prepare_native_session('unused', 'unused', 'unused', [], 'unused')


class PipeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def exchange(self, source, gateway=None, timeout=5):
        child = self.root / 'child.py'
        child.write_text(source, encoding='utf-8')
        return run_exchange([sys.executable, '-I', str(child)], dict(os.environ), self.root, self.root / 'log',
                            gateway or ModelGateway(config()['gateway'], 'test-key', lambda *a: (200, 'application/json', b'{}')), timeout)

    def test_real_loopback_http_bridge_roundtrip_no_provider_key_in_child(self):
        script = self.root / 'native-fixture.py'
        script.write_text('''import json,os,urllib.request
assert os.environ['ANTHROPIC_API_KEY']=='pvl-broker-placeholder-not-a-credential'
assert 'PVL_MODEL_API_KEY' not in os.environ
body=json.dumps({'model':'selected-model','max_tokens':20,'messages':[]}).encode()
req=urllib.request.Request(os.environ['ANTHROPIC_BASE_URL']+'/v1/messages', data=body, headers={'content-type':'application/json'})
assert json.load(urllib.request.urlopen(req))=={'fixture':True}
print('BRIDGE_OK')
''', encoding='utf-8')
        retained = self.root / 'retained'
        retained.mkdir()
        spec = {'argv': [sys.executable, str(script)], 'retained': str(retained), 'plugin': str(self.root), 'path': os.environ['PATH']}
        gateway = ModelGateway(config()['gateway'], 'parent-only-secret', lambda *a: (200, 'application/json', b'{"fixture":true}'))
        result = run_exchange([sys.executable, '-I', str(BRIDGE), '--run', json.dumps(spec)], clean_environment(self.root),
                              self.root, self.root / 'log', gateway, 10)
        self.assertEqual(result['status'], 'COMPLETED', result)
        self.assertEqual(result['gateway_requests'], 1)
        self.assertIn('BRIDGE_OK', (self.root / 'log/stdout.txt').read_text())
        self.assertNotIn('parent-only-secret', json.dumps(result))

    def test_oversized_or_invalid_frames_fail_before_provider(self):
        result = self.exchange("print('[]',flush=True)")
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['gateway_requests'], 0)

    def test_child_timeout_has_terminal_failure_receipt(self):
        result = self.exchange('import time; time.sleep(10)', timeout=.3)
        self.assertEqual(result['status'], 'FAILED')
        self.assertTrue(result['timed_out'])

    def test_slow_provider_does_not_hold_controller_past_session_deadline(self):
        def transport(*args):
            time.sleep(.8)
            return 200, 'application/json', b'{}'
        gateway = ModelGateway(config()['gateway'], 'test-key', transport)
        source = 'import json,time\nprint(' + repr(json.dumps(request())) + ',flush=True)\ntime.sleep(10)'
        started = time.monotonic()
        result = self.exchange(source, gateway=gateway, timeout=.3)
        self.assertLess(time.monotonic()-started, 3)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['gateway_requests'], 1)
        self.assertIsNone(result['settled_usd'])
        self.assertTrue(gateway.cancelled.is_set())

    def test_child_that_will_not_read_responses_cannot_stall_broker(self):
        gateway = ModelGateway(config()['gateway'], 'test-key', lambda *a: (200, 'application/json', b'x' * (2*1024*1024)))
        source = 'import time\nprint(' + repr(json.dumps(request())) + ',flush=True)\ntime.sleep(10)'
        result = self.exchange(source, gateway=gateway, timeout=.4)
        self.assertEqual(result['status'], 'FAILED')
        self.assertTrue(result['timed_out'])
        self.assertEqual(result['gateway_requests'], 1)

    def test_runtime_mutation_is_detectable_and_links_rejected(self):
        path = self.root / 'runtime'
        path.mkdir()
        (path / 'cli').write_text('v1')
        before = runtime_inventory(path)
        (path / 'cli').write_text('v2')
        self.assertNotEqual(before, runtime_inventory(path))
        os.link(path / 'cli', path / 'alias')
        with self.assertRaises(ValidationError):
            runtime_inventory(path)


if __name__ == '__main__':
    unittest.main()
