"""Fast stdlib contract tests; actual kernel isolation has a separate hard gate."""
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from value_lab.core import ValidationError, load_json, write_json
from value_lab.native_session import offline_namespace, run_offline
from value_lab.replay import ToolReplay, record_tools, serve_tools

ROOT = Path(__file__).resolve().parents[1]
TOOLS = [{'name': 'science_summary', 'inputSchema': {'type': 'object'}}]
EXCHANGES = [
    {'request': {'name': 'science_summary', 'arguments': {'sample': 'fixture', 'n': 0}},
     'response': {'result': {'content': [{'type': 'text', 'text': 'manufactured, not computed'}],
                            'structuredContent': {'value': 0, 'valid': False, 'unknown': None}, 'isError': False}}},
    {'request': {'name': 'science_summary', 'arguments': {'sample': 'missing'}},
     'response': {'result': {'content': [{'type': 'text', 'text': 'known backend failure'}], 'isError': True}}},
    {'request': {'name': 'science_summary', 'arguments': {'sample': 'invalid'}},
     'response': {'error': {'code': -32602, 'message': 'bad argument', 'data': {'keep': True}}}}
]


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cassette = self.root / '.replay'
        self.pin = record_tools(self.cassette, TOOLS, EXCHANGES,
            provenance={'origin': 'manufactured', 'description': 'Software tests, not scientific observations'})['cassette_sha256']

    def request(self, i, arguments=None):
        return {'jsonrpc': '2.0', 'id': i + 1, 'method': 'tools/call',
                'params': deepcopy(EXCHANGES[i]['request']) if arguments is None else {'name': 'science_summary', 'arguments': arguments}}

    def replay(self):
        replay = ToolReplay(self.cassette, self.pin)
        replay.handle({'jsonrpc': '2.0', 'id': 'init', 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}})
        replay.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return replay

    def test_success_tool_failure_protocol_failure_preserved(self):
        replay = self.replay()
        for i, entry in enumerate(EXCHANGES):
            response = replay.handle(self.request(i))
            self.assertEqual({k: v for k, v in response.items() if k not in ('id', 'jsonrpc')}, entry['response'])
        self.assertEqual(replay.receipt()['status'], 'REPLAY_COMPLETE')
        self.assertEqual(replay.receipt()['new_observations'], 0)
        self.assertEqual(replay.receipt()['backend_calls'], 0)

    def test_mismatch_does_not_consume_or_fall_back(self):
        for args in ({'sample': 'fixture', 'n': False}, {'sample': 'fixture', 'n': 0.0},
                     {'sample': 'fixture'}, {'sample': 'fixture', 'n': None}, {'sample': 'other', 'n': 0}):
            replay = self.replay()
            self.assertIn('error', replay.handle(self.request(0, args)))
            self.assertEqual(replay.position, 0)
            self.assertEqual(replay.receipt()['status'], 'REPLAY_INCOMPLETE')

    def test_order_exhaustion_and_missing_calls_fail(self):
        replay = self.replay()
        self.assertIn('error', replay.handle(self.request(1)))
        self.assertEqual(replay.position, 0)
        self.assertEqual(ToolReplay(self.cassette, self.pin).receipt()['status'], 'REPLAY_INCOMPLETE')
        replay = self.replay()
        for i in range(3):
            replay.handle(self.request(i))
        request = self.request(0)
        request['id'] = 'extra'
        self.assertIn('error', replay.handle(request))
        self.assertEqual(replay.receipt()['status'], 'REPLAY_INCOMPLETE')

    def test_object_key_order_and_transport_meta_do_not_change_match(self):
        replay = self.replay()
        request = self.request(0, {'n': 0, 'sample': 'fixture'})
        request['params']['_meta'] = {'progressToken': 'arbitrary'}
        self.assertIn('result', replay.handle(request))

    def test_tamper_missing_commitment_and_nonfinite_rejected(self):
        for pin in (None, 'f' * 64):
            with self.assertRaises(ValidationError):
                ToolReplay(self.cassette, pin)
        data = load_json(self.cassette / 'cassette.json')
        data['exchanges'][0]['response']['result']['structuredContent']['value'] = 7
        write_json(self.cassette / 'cassette.json', data)
        with self.assertRaises(ValidationError):
            ToolReplay(self.cassette, self.pin)
        bad = deepcopy(EXCHANGES)
        bad[0]['request']['arguments']['n'] = float('nan')
        with self.assertRaises(ValidationError):
            record_tools(self.root / 'bad', TOOLS, bad, provenance={'origin': 'recorded', 'description': 'bad'})

    def test_isolated_sessions_and_returned_objects(self):
        a, b = self.replay(), self.replay()
        reply = a.handle(self.request(0))
        reply['result']['structuredContent']['value'] = 'changed'
        self.assertEqual(b.position, 0)
        self.assertEqual(b.handle(self.request(0))['result']['structuredContent']['value'], 0)

    def test_duplicate_ids_unsupported_methods_and_protocol_fail(self):
        replay = self.replay()
        replay.handle(self.request(0))
        with self.assertRaises(ValidationError):
            replay.handle(self.request(0))
        for method, params in [('resources/read', {'uri': 'file:///private'}),
                               ('initialize', {}), ('tools/list', {'cursor': 'next'})]:
            replay = self.replay()
            self.assertIn('error', replay.handle({'jsonrpc': '2.0', 'id': 8, 'method': method, 'params': params}))
            self.assertTrue(replay.receipt()['violations'])

    def test_stdio_transport_and_catalog(self):
        messages = [{'jsonrpc': '2.0', 'id': 'init', 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
                    {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                    {'jsonrpc': '2.0', 'id': 'tools', 'method': 'tools/list'}] + [self.request(i) for i in range(3)]
        source = io.StringIO(''.join(json.dumps(m) + '\n' for m in messages))
        sink = io.StringIO()
        receipt = serve_tools(self.cassette, self.pin, source, sink)
        responses = [json.loads(line) for line in sink.getvalue().splitlines()]
        self.assertEqual(receipt['status'], 'REPLAY_COMPLETE')
        self.assertEqual(responses[1]['result']['tools'], TOOLS)
        self.assertEqual(len(responses), 5)

    def test_truncated_and_oversized_stdio_rejected(self):
        for text in ('{}', 'x' * (1024 * 1024 + 2),
                     '{"jsonrpc":"2.0","id":1,"id":2,"method":"ping"}\n',
                     '{"jsonrpc":"2.0","id":NaN,"method":"ping"}\n'):
            with self.assertRaises(ValidationError):
                serve_tools(self.cassette, self.pin, io.StringIO(text), io.StringIO())

    def test_stdlib_only_subprocess_with_no_scientific_packages(self):
        handshake = [{'jsonrpc': '2.0', 'id': 'init', 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
                     {'jsonrpc': '2.0', 'method': 'notifications/initialized'}]
        result = subprocess.run([sys.executable, '-S', str(ROOT / 'scripts/offline_eval.py'), 'serve', str(self.cassette),
            '--expected-id', self.pin], input=''.join(json.dumps(m) + '\n' for m in handshake + [self.request(i) for i in range(3)]),
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 4)
        self.assertEqual(json.loads(result.stderr)['status'], 'REPLAY_COMPLETE')

    def test_initialization_required_and_version_negotiated(self):
        replay = ToolReplay(self.cassette, self.pin)
        self.assertIn('error', replay.handle(self.request(0)))
        replay = ToolReplay(self.cassette, self.pin)
        result = replay.handle({'jsonrpc': '2.0', 'id': 'init', 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25'}})
        self.assertEqual(result['result']['protocolVersion'], '2025-06-18')
        self.assertFalse(replay.ready)

    def test_no_overwrite_and_invalid_cassette_rejected(self):
        with self.assertRaises(FileExistsError):
            record_tools(self.cassette, TOOLS, EXCHANGES, provenance={'origin': 'recorded', 'description': 'duplicate'})
        with self.assertRaises(ValidationError):
            record_tools(self.root / 'bad', TOOLS * 2, EXCHANGES, provenance={'origin': 'manufactured', 'description': 'duplicate'})

    def test_cassette_cannot_be_staged_even_under_an_innocent_directory_name(self):
        cache = self.root / 'innocent'
        pin = record_tools(cache, TOOLS, EXCHANGES, provenance={'origin': 'manufactured', 'description': 'private'})['cassette_sha256']
        with patch('value_lab.native_session.sys.platform', 'linux'), patch('shutil.which', return_value='/usr/bin/bwrap'), patch('subprocess.Popen') as launch:
            with self.assertRaisesRegex(ValidationError, 'Cassette cannot'):
                run_offline(cache, ['cassette.json'], ['python'], self.root / 'run', cassette=cache, expected_id=pin)
            launch.assert_not_called()
        self.assertFalse((self.root / 'run').exists())


class OfflineBoundaryContractTests(unittest.TestCase):
    def test_no_host_root_network_env_or_reference_mount(self):
        command = offline_namespace(['/usr/bin/python3', '/inputs/job.py'], Path('/stage'), Path('/artifacts'), '/usr/bin/bwrap')
        for option in ('--unshare-all', '--disable-userns', '--new-session', '--clearenv', '--die-with-parent'):
            self.assertIn(option, command)
        mounts = [command[i + 1:i + 3] for i, s in enumerate(command) if s in ('--bind', '--ro-bind')]
        self.assertNotIn(['/', '/'], mounts)
        self.assertNotIn('--share-net', command)
        self.assertNotIn('/mnt/c', command)
        self.assertEqual(mounts[-2:], [[str(Path('/stage')), '/inputs'], [str(Path('/artifacts')), '/output']])

    def test_platform_and_backend_failure_never_launch_payload(self):
        with patch('value_lab.native_session.sys.platform', 'win32'), patch('subprocess.Popen') as launch:
            with self.assertRaises(ValidationError):
                run_offline('.', ['x'], ['x'], 'never-created')
            launch.assert_not_called()
        with patch('value_lab.native_session.sys.platform', 'linux'), patch('shutil.which', return_value=None), patch('subprocess.Popen') as launch:
            with self.assertRaises(ValidationError):
                run_offline('.', ['x'], ['x'], 'never-created')
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
