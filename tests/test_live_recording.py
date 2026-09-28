"""Run an actual local server, then replay without it. No real provider calls."""
import io
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest

from value_lab.core import ValidationError, load_json
from value_lab.live_recording import _public, record_live
from value_lab.replay import ToolReplay

SERVER = Path(__file__).parent / 'fixtures/recording_server.py'


class Session:
    """Interactive client, so initialization ordering reflects a real MCP client."""
    def __init__(self, calls):
        self.calls, self.messages, self.counter = calls, [], 1
        self.lines = queue.Queue()
        self.push({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'fixture', 'version': '1'}}})

    def push(self, message):
        self.lines.put(json.dumps(message) + '\n')

    def readline(self, limit):
        return self.lines.get()

    def write(self, text):
        msg = json.loads(text)
        self.messages.append(msg)
        if msg['id'] == 1:
            self.push({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            self.push({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        elif self.calls:
            self.counter += 1
            self.push({'jsonrpc': '2.0', 'id': self.counter + 1, 'method': 'tools/call',
                       'params': {'name': 'matrix_sum', 'arguments': self.calls.pop(0)}})
        else:
            self.lines.put('')

    def flush(self):
        pass


class LiveRecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_session(self, calls, timeout=10):
        session = Session(calls)
        try:
            result = record_live([sys.executable, '-S', str(SERVER)], self.root / 'recording', ['matrix_sum'],
                session, session, public_data=True, timeout_seconds=timeout)
        finally:
            session.lines.put('')
        return result, session.messages

    def test_real_tool_run_to_automatic_cassette_then_backend_free_replay(self):
        result, messages = self.run_session([{'values': [1, 2, 3]}, {'mode': 'tool_error'}, {'mode': 'protocol_error'}])
        self.assertEqual(result['status'], 'RECORDING_COMPLETE', result)
        self.assertEqual(result['backend_calls_started'], 3)
        self.assertEqual(result['responses_recorded'], 3)
        self.assertEqual(result['cost'], 'UNKNOWN')
        replay = ToolReplay(self.root / 'recording/cassette', result['cassette_sha256'])
        replay.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}})
        replay.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        for i, arguments in enumerate([{'values': [1, 2, 3]}, {'mode': 'tool_error'}, {'mode': 'protocol_error'}], 3):
            actual = replay.handle({'jsonrpc': '2.0', 'id': i, 'method': 'tools/call', 'params': {'name': 'matrix_sum', 'arguments': arguments}})
            self.assertEqual(actual, messages[i - 1])
        self.assertEqual(replay.receipt()['status'], 'REPLAY_COMPLETE')
        self.assertEqual(replay.receipt()['backend_calls'], 0)

    def test_secret_response_does_not_reach_disk(self):
        result, _ = self.run_session([{'mode': 'secret'}])
        self.assertEqual(result['status'], 'RECORDING_FAILED')
        self.assertFalse((self.root / 'recording/cassette').exists())
        self.assertNotIn('fixture-secret-must-not-persist', (self.root / 'recording/recording.json').read_text())

    def test_crashed_backend_withholds_cassette(self):
        result, _ = self.run_session([{'mode': 'crash'}])
        self.assertEqual(result['status'], 'RECORDING_FAILED')
        self.assertEqual(result['backend_calls_started'], 1)
        self.assertFalse((self.root / 'recording/cassette').exists())

    def test_partial_success_then_crash_is_not_complete(self):
        result, _ = self.run_session([{'values': [2, 3]}, {'mode': 'crash'}])
        self.assertEqual(result['status'], 'RECORDING_FAILED')
        self.assertEqual(result['responses_recorded'], 1)
        self.assertEqual(result['backend_calls_started'], 2)
        self.assertFalse((self.root / 'recording/cassette').exists())

    def test_unselected_tool_cannot_be_called(self):
        class WrongTool(Session):
            def push(self, message):
                if message.get('method') == 'tools/call':
                    message['params']['name'] = 'unselected_mutating_tool'
                super().push(message)
        session = WrongTool([{'values': [1]}])
        try:
            result = record_live([sys.executable, '-S', str(SERVER)], self.root / 'recording', ['matrix_sum'],
                session, session, public_data=True, timeout_seconds=5)
        finally:
            session.lines.put('')
        self.assertEqual(result['status'], 'RECORDING_FAILED')
        self.assertEqual(result['backend_calls_started'], 0)

    def test_oversized_frame_cannot_reach_backend(self):
        result = record_live([sys.executable, '-S', str(SERVER)], self.root / 'recording', ['matrix_sum'],
            io.StringIO('x' * (1024 * 1024 + 2)), io.StringIO(), public_data=True, timeout_seconds=2)
        self.assertEqual(result['status'], 'RECORDING_FAILED')
        self.assertEqual(result['backend_calls_started'], 0)

    def test_deadline_stops_hung_tool(self):
        result, _ = self.run_session([{'mode': 'hang'}], timeout=1)
        self.assertEqual(result['status'], 'RECORDING_FAILED')
        self.assertFalse((self.root / 'recording/cassette').exists())

    def test_public_data_opt_in_required_before_launch(self):
        with self.assertRaises(ValidationError):
            record_live(['invalid'], self.root / 'recording', ['matrix_sum'], io.StringIO(), io.StringIO())
        self.assertFalse((self.root / 'recording').exists())

    def test_sensitive_arguments_block_before_tool_execution(self):
        result, _ = self.run_session([{'password': 'do-not-send'}])
        self.assertEqual(result['status'], 'RECORDING_FAILED')
        self.assertEqual(result['backend_calls_started'], 0)

    def test_empty_and_uninitialized_sessions_cannot_publish(self):
        result = record_live([sys.executable, '-S', str(SERVER)], self.root / 'recording', ['matrix_sum'],
            io.StringIO(''), io.StringIO(), public_data=True, timeout_seconds=2)
        self.assertEqual(result['status'], 'RECORDING_FAILED')
        self.assertFalse((self.root / 'recording/cassette').exists())

    def test_existing_capture_cannot_be_overwritten(self):
        self.run_session([{'values': [1]}])
        with self.assertRaises(FileExistsError):
            self.run_session([{'values': [2]}])

    def test_credentials_in_nested_json_and_text(self):
        for value in ({'authorization': 'Bearer fixture'}, {'text': '{"api_key":"secret"}'},
                      {'text': 'Bearer abcdefghijklmnop'}, {'text': 'password=hunter2'}):
            with self.assertRaises(ValidationError):
                _public(value)
        _public({'structuredContent': {'tokens': 32, 'value': False}})


if __name__ == '__main__':
    unittest.main()
