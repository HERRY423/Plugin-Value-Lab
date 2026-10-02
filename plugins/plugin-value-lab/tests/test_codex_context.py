"""Native-adapter negative controls are synthetic, separate from live receipts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from value_lab.codex_context import capture
from value_lab.core import ValidationError

ROOT = Path(__file__).resolve().parents[1]


def event(kind, payload):
    return {'type': kind, 'timestamp': '2026-10-02T09:00:00Z', 'payload': payload}


def usage(input_tokens=200, output_tokens=10):
    return {'input_tokens': input_tokens, 'output_tokens': output_tokens,
            'cached_input_tokens': 100, 'cache_write_input_tokens': 0,
            'reasoning_output_tokens': 5, 'total_tokens': input_tokens + output_tokens}


def fixture():
    measured = usage()
    total = usage(9000, 1000)
    return [event('session_meta', {'id': 'session', 'originator': 'codex_work_desktop',
                                 'cli_version': '0.159.2', 'source': 'vscode', 'model_provider': 'openai',
                                 'instructions': 'PRIVATE-INSTRUCTIONS', 'cwd': 'PRIVATE-PATH'}),
            event('event_msg', {'type': 'task_started', 'turn_id': 'turn'}),
            event('turn_context', {'turn_id': 'turn', 'model': 'observed-model', 'private': 'PRIVATE-TEXT'}),
            event('token_usage_record', {'thread_id': 'session', 'session_id': 'session',
                                        'turn_id': 'turn', 'root_turn_id': 'turn', 'response_id': 'response',
                                        'usage': measured, 'thread_token_usage': total,
                                        'turn_token_usage': total}),
            event('event_msg', {'type': 'token_count', 'info': {
                'last_token_usage': measured, 'total_token_usage': total, 'model_context_window': 1000}}),
            event('event_msg', {'type': 'task_complete', 'turn_id': 'turn'})]


class CodexContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'rollout.jsonl'
        self.events = fixture()

    def write(self, tail=b''):
        raw = ''.join(json.dumps(e) + '\n' for e in self.events).encode() + tail
        self.path.write_bytes(raw)
        return raw

    def result(self, tail=b''):
        self.write(tail)
        return capture(self.path, 'session')

    def test_real_field_mapping_separates_current_cumulative_input_and_cache(self):
        result = self.result()
        current = result['latest_context_sample']
        self.assertEqual(current['context_tokens'], 210)
        self.assertEqual(current['context_fraction'], .21)
        self.assertEqual(current['request_input_tokens'], 200)
        self.assertEqual(result['samples'][0]['request_input_fraction'], .2)
        self.assertEqual(result['thread_cumulative_usage']['total_tokens'], 10000)
        self.assertIsNone(result['settled_cost_usd'])
        self.assertEqual(current['model'], 'observed-model')
        self.assertEqual(current['phase'], 'post_response_token_count')
        self.assertEqual(result['samples'][0]['response_id'], 'response')

    def test_unknown_window_does_not_become_zero_or_guessed_capacity(self):
        self.events[4]['payload']['info'].pop('model_context_window')
        result = self.result()
        self.assertIsNone(result['latest_context_sample']['context_window_tokens'])
        self.assertIsNone(result['latest_context_sample']['context_fraction'])
        self.assertEqual(result['latest_context_sample']['context_tokens'], 210)

    def test_unknown_usage_and_missing_events_do_not_become_zero(self):
        for missing in ('input_tokens', 'total_tokens', 'usage', 'info', 'context_event'):
            self.events = fixture()
            if missing == 'context_event':
                del self.events[4]
            elif missing == 'info':
                self.events[4]['payload']['info'] = None
            elif missing == 'usage':
                self.events[3]['payload']['usage'] = None
            else:
                self.events[3]['payload']['usage'].pop(missing)
            with self.subTest(missing=missing):
                self.assertIsNone(self.result()['latest_context_sample'])

    def test_explicit_zero_is_preserved_only_for_matched_real_response(self):
        zero = {k: 0 for k in usage()}
        self.events[3]['payload']['usage'] = zero
        self.events[4]['payload']['info']['last_token_usage'] = zero
        self.assertEqual(self.result()['latest_context_sample']['context_tokens'], 0)

    def test_compaction_estimate_is_not_zero_or_a_new_measured_request(self):
        self.events.insert(4, event('compacted', {'compaction_response_id': 'response'}))
        self.events[5]['payload']['info']['last_token_usage'] = {k: 0 for k in usage()} | {'total_tokens': 50}
        result = self.result()
        self.assertIsNone(result['latest_context_sample'])
        self.assertEqual(result['samples'][0]['kind'], 'COMPACTION_RESPONSE')
        self.assertEqual(result['transitions'][-1]['host_reported_last_usage']['total_tokens'], 50)
        self.assertIsNone(result['transitions'][-1]['measured_context_tokens'])

    def test_new_turn_or_model_invalidates_previous_current_sample(self):
        for change in ('turn', 'model', 'start'):
            self.events = fixture()
            self.events.append(event('event_msg', {'type': 'task_started', 'turn_id': 'new'}) if change == 'start'
                               else event('turn_context', {'turn_id': 'new' if change == 'turn' else 'turn',
                                                           'model': 'new' if change == 'model' else 'observed-model'}))
            with self.subTest(change=change):
                self.assertIsNone(self.result()['latest_context_sample'])

    def test_sample_requires_observed_model_turn_root_and_timestamp(self):
        for field in ('model', 'turn_id', 'root_turn_id', 'timestamp'):
            self.events = fixture()
            if field == 'model': self.events[2]['payload'].pop('model')
            elif field == 'timestamp': self.events[3].pop('timestamp')
            else: self.events[3]['payload'][field] = 'different'
            with self.subTest(field=field):
                self.assertIsNone(self.result()['latest_context_sample'])

    def test_session_or_thread_mismatch_and_duplicate_responses_rejected(self):
        for field in ('metadata', 'session_id', 'thread_id', 'duplicate'):
            self.events = fixture()
            if field == 'metadata':self.events[0]['payload']['id'] = 'other'
            elif field == 'duplicate':self.events.append(deepcopy(self.events[3]))
            else:self.events[3]['payload'][field] = 'other'
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.result()

    def test_repeated_token_count_does_not_create_request_samples(self):
        self.events.append(deepcopy(self.events[4]))
        self.assertEqual(len(self.result()['samples']), 1)

    def test_other_host_or_version_not_qualified(self):
        for key in ('originator', 'cli_version'):
            self.events = fixture()
            self.events[0]['payload'][key] = 'different'
            result = self.result()
            self.assertFalse(result['adapter_supported'])
            self.assertIsNone(result['latest_context_sample'])
            self.assertEqual(result['samples'][0]['status'], 'UNSUPPORTED_HOST_VERSION')

    def test_bad_counts_rejected_without_clamping(self):
        for value in (True, -1, 1.5, float('nan'), float('inf')):
            self.events = fixture()
            self.events[3]['payload']['usage']['input_tokens'] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):self.result()
        self.events = fixture()
        self.events[3]['payload']['usage']['total_tokens'] = 1
        with self.assertRaises(ValidationError):self.result()

    def test_partial_write_unknown_then_exact_prefix_replay_after_append(self):
        before = self.result()
        prefix = self.path.stat().st_size
        self.path.write_bytes(self.path.read_bytes() + b'{"type":')
        self.assertEqual(capture(self.path, 'session', prefix_bytes=prefix), before)
        result = capture(self.path, 'session')
        self.assertEqual(result['state'], 'INCOMPLETE_TRAILING_EVENT')
        self.assertIsNone(result['latest_context_sample'])
        self.assertEqual(result['source']['complete_prefix_sha256'], before['source']['complete_prefix_sha256'])

    def test_source_offsets_hashes_and_content_minimization(self):
        result = self.result()
        raw = self.path.read_bytes()
        for sample in result['samples']:
            for key in ('event', 'turn_context_event', 'context_event'):
                ref = sample[key]
                self.assertEqual(hashlib.sha256(raw[ref['byte_start']:ref['byte_end']]).hexdigest(), ref['sha256'])
        self.assertNotIn('PRIVATE-', json.dumps(result))
        self.assertNotIn(str(self.path), json.dumps(result))
        self.assertEqual(raw, self.path.read_bytes())

    def test_missing_cumulative_counters_stay_unknown(self):
        self.events[3]['payload'].pop('thread_token_usage')
        self.events[3]['payload'].pop('turn_token_usage')
        self.events[4]['payload']['info'].pop('total_token_usage')
        result = self.result()
        for key in ('thread_cumulative_usage', 'turn_cumulative_usage', 'context_stream_cumulative_usage'):
            self.assertTrue(all(v is None for v in result[key].values()))

    def test_malformed_complete_line_and_shortened_prefix_rejected(self):
        raw = self.write()
        self.path.write_bytes(raw + b'{bad}\n')
        with self.assertRaises(ValidationError):capture(self.path, 'session')
        with self.assertRaises(ValidationError):capture(self.path, 'session', prefix_bytes=len(raw) + 999)

    def test_script_capture_and_no_overwrite(self):
        self.write()
        output = Path(self.tmp.name) / 'result.json'
        args = [sys.executable, str(ROOT / 'scripts/collect_codex_context.py'), '--rollout', str(self.path),
                '--session-id', 'session', '--output', str(output)]
        done = subprocess.run(args, capture_output=True, text=True, timeout=20)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)['model_calls_launched'], 0)
        contents = output.read_bytes()
        again = subprocess.run(args, capture_output=True, text=True, timeout=20)
        self.assertNotEqual(again.returncode, 0)
        self.assertEqual(output.read_bytes(), contents)


if __name__ == '__main__':
    unittest.main()
