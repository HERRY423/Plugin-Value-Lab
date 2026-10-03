"""Synthetic fault controls, never counted as native acceptance observations."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from value_lab.core import ValidationError
from value_lab.native_host_context import capture, digest
from value_lab import antigravity_context as ag


def claude():
    return [{'type': 'assistant', 'sessionId': 's', 'version': '2.1.288', 'uuid': 'u1', 'apiBlockIndex': 0,
             'isSidechain': False, 'message': {'id': 'r1', 'model': 'm', 'stop_reason': 'end_turn',
                 'content': 'PRIVATE-CONTENT', 'usage': {'input_tokens': 100, 'cache_read_input_tokens': 200,
                                                       'cache_creation_input_tokens': 50, 'output_tokens': 25}}}]


def dsh():
    return [{'type': 'session', 'version': 4, 'id': 's', 'cwd': 'PRIVATE-PATH'},
            {'type': 'turn/start', 'seq': 0, 'data': {'turn': 1}},
            {'type': 'step/start', 'seq': 1, 'data': {'turn': 1, 'step': 1}},
            {'type': 'request/context', 'seq': 2, 'data': {'model': 'm', 'contextWindow': 1000000}},
            {'type': 'assistant/message', 'seq': 3, 'data': {'turn': 1, 'step': 1, 'message': 'PRIVATE-CONTENT',
                'usage': {'inputTokens': 100, 'cacheReadTokens': 200, 'cacheWriteTokens': 50,
                          'outputTokens': 25, 'totalTokens': 375}}}]


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def proto(fields):
    raw = b''
    for key, value in fields:
        if isinstance(value, str):
            value = value.encode()
        raw += varint(key * 8 + (2 if isinstance(value, bytes) else 0))
        raw += varint(len(value)) + value if isinstance(value, bytes) else varint(value)
    return raw


class NativeHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'native.jsonl'

    def run_capture(self, events, host='claude-code', tail=b''):
        self.path.write_bytes(b''.join(json.dumps(e).encode() + b'\n' for e in events) + tail)
        return capture(self.path, 's', host=host)

    def test_claude_disjoint_cache_buckets_and_no_capacity_or_invoice(self):
        r = self.run_capture(claude())
        s = r['latest_context_sample']
        self.assertEqual(s['context_tokens'], 375)
        self.assertEqual(s['request_usage']['input_tokens'], 350)
        self.assertIsNone(s['context_window'])
        self.assertIsNone(s['context_fraction'])
        self.assertIsNone(r['settled_cost_usd'])
        self.assertEqual(r['capabilities']['capabilities']['request_identity']['status'], 'UNKNOWN')
        self.assertNotIn('PRIVATE', json.dumps(r))

    def test_claude_native_blocks_are_one_response(self):
        es = claude()
        block = deepcopy(es[0]); block.update(uuid='u2', apiBlockIndex=1)
        r = self.run_capture(es + [block])
        self.assertEqual(len(r['samples']), 1)
        self.assertEqual(len(r['samples'][0]['block_events']), 2)

    def test_conflicting_duplicate_or_replayed_block_fails(self):
        for change in ({}, {'uuid': 'u2'}, {'uuid': 'u2', 'apiBlockIndex': 1, 'message': {'id': 'r1', 'model': 'other', 'stop_reason': 'end_turn'}}):
            with self.subTest(change=change):
                es = claude(); block = deepcopy(es[0]); block.update(change)
                with self.assertRaises(ValidationError): self.run_capture(es + [block])

    def test_sdk_zero_output_and_cumulative_result_not_context(self):
        es = claude(); es[0]['message']['stop_reason'] = None
        es += [{'type': 'result', 'session_id': 's', 'usage': {'input_tokens': 9000, 'output_tokens': 5000}, 'total_cost_usd': 2}]
        r = self.run_capture(es)
        self.assertIsNone(r['latest_context_sample'])
        self.assertEqual(r['samples'], [])
        self.assertEqual(r['capabilities']['capabilities']['request_usage']['status'], 'UNKNOWN')

    def test_unknown_version_and_foreign_session(self):
        for host, fixture in [('claude-code', claude), ('dsh', dsh)]:
            with self.subTest(host=host):
                es = fixture(); es[0]['version'] = 'new'
                r = self.run_capture(es, host)
                self.assertEqual(r['capabilities']['capabilities']['context_sample']['status'], 'UNSUPPORTED')
                es = fixture(); es[0]['sessionId' if host == 'claude-code' else 'id'] = 'foreign'
                with self.assertRaises(ValidationError): self.run_capture(es, host)

    def test_missing_negative_boolean_nonfinite_counters_fail_closed(self):
        for value in (None, -1, True, 1.5, float('nan'), 2**60):
            with self.subTest(value=value):
                es = claude(); es[0]['message']['usage']['input_tokens'] = value
                r = self.run_capture(es)
                self.assertIsNone(r['latest_context_sample'])
                self.assertEqual(r['capabilities']['capabilities']['request_usage']['status'], 'UNKNOWN')

    def test_subagent_and_compaction_do_not_inherit_context(self):
        es = claude(); es[0]['isSidechain'] = True
        self.assertIsNone(self.run_capture(es)['latest_context_sample'])
        es = claude() + [{'type': 'system', 'subtype': 'compact_boundary', 'sessionId': 's'}]
        r = self.run_capture(es)
        self.assertIsNone(r['latest_context_sample'])
        self.assertEqual(r['capabilities']['capabilities']['request_usage']['status'], 'OBSERVED')

    def test_partial_tail_invalidates_current_sample_but_exact_prefix_replays(self):
        es = claude(); r = self.run_capture(es)
        raw = self.path.read_bytes()
        self.path.write_bytes(raw + b'{"unfinished":')
        self.assertIsNone(capture(self.path, 's', host='claude-code')['latest_context_sample'])
        replay = capture(self.path, 's', host='claude-code', prefix_bytes=len(raw))
        self.assertEqual(replay, r)

    def test_invalid_complete_json_is_not_silently_skipped(self):
        with self.assertRaises(ValidationError): self.run_capture(claude(), tail=b'bad\n')

    def test_dsh_cache_not_double_counted_and_capacity_not_atomic(self):
        r = self.run_capture(dsh(), 'dsh')
        self.assertEqual(r['latest_context_sample']['context_tokens'], 375)
        self.assertIsNone(r['latest_context_sample']['context_fraction'])
        self.assertEqual(r['capabilities']['capabilities']['thread_usage']['status'], 'NOT_PROVIDED')

    def test_dsh_attempt_replaced_and_retry_kept_separate(self):
        es = dsh(); attempt = deepcopy(es[-1]); attempt['type'] = 'assistant/attempt'
        attempt['data']['stream'] = [{'type': 'usage', 'usage': attempt['data'].pop('usage')}]
        final = deepcopy(es[-1]); final['seq'] = 4
        r = self.run_capture(es[:-1] + [attempt, final], 'dsh')
        self.assertEqual(len(r['samples']), 1)
        retry = {'type': 'llm/retry-started', 'seq': 4, 'data': {'turn': 1, 'step': 1}}
        final['seq'] = 5
        r = self.run_capture(es[:-1] + [attempt, retry, final], 'dsh')
        self.assertEqual(len(r['samples']), 2)
        self.assertNotEqual(r['samples'][0]['response_id'], r['samples'][1]['response_id'])

    def test_dsh_failed_usage_is_not_post_response_context(self):
        es = dsh(); es[-1]['type'] = 'assistant/attempt'
        es[-1]['data']['stream'] = [{'type': 'usage', 'usage': es[-1]['data'].pop('usage')}]
        r = self.run_capture(es, 'dsh')
        self.assertIsNone(r['latest_context_sample'])
        self.assertIsNotNone(r['samples'][0]['request_usage'])

    def test_dsh_sequence_turn_and_total_mismatch(self):
        for mutation in ('seq', 'turn', 'total'):
            es = dsh()
            if mutation == 'seq': es[-1]['seq'] = 1
            if mutation == 'turn': es[-1]['data']['turn'] = 2
            if mutation == 'total': es[-1]['data']['usage']['totalTokens'] = 100
            if mutation == 'total':
                self.assertIsNone(self.run_capture(es, 'dsh')['latest_context_sample'])
            else:
                with self.assertRaises(ValidationError): self.run_capture(es, 'dsh')

    def test_dsh_model_switch_and_surface_replacement_invalidate_context(self):
        for event in [{'type': 'model/selection', 'data': {'model': 'new'}},
                      {'type': 'surface/change', 'surfaceOp': 'replace', 'data': {}}]:
            event['seq'] = 4
            self.assertIsNone(self.run_capture(dsh() + [event], 'dsh')['latest_context_sample'])

    def test_optional_zstd_concatenated_frames_equal_plain_capture(self):
        # No dependency/skip in the release suite: a conforming short-read
        # decompressor double verifies all frames are consumed, not only first.
        import io
        class Reader(io.BytesIO):
            def read(self, size=-1): return super().read(min(size, 80))
        class Zstd:
            ZstdError = ValueError
            @staticmethod
            def ZstdDecompressor():
                class Decoder:
                    @staticmethod
                    def stream_reader(stream): return Reader(stream.read())
                    @staticmethod
                    def decompressobj():
                        class Frame:
                            eof, unused_data = True, b''
                            @staticmethod
                            def decompress(raw): return raw
                        return Frame()
                return Decoder()
        plain = self.run_capture(dsh(), 'dsh')
        zipped = self.path.with_suffix('.zstd'); zipped.write_bytes(self.path.read_bytes())
        with patch.dict(sys.modules, {'zstandard': Zstd}): r = capture(zipped, 's', host='dsh')
        self.assertEqual(r['samples'], plain['samples'])
        self.assertEqual(r['source']['complete_prefix_sha256'], plain['source']['complete_prefix_sha256'])

    def test_antigravity_transcript_cannot_supply_tokens_or_session_from_path(self):
        r = self.run_capture([{'step_index': 1, 'type': 'PLANNER_RESPONSE', 'content': 'PRIVATE', 'usage': {'input_tokens': 10}}], 'antigravity-transcript')
        self.assertIsNone(r['session_event'])
        self.assertIsNone(r['latest_context_sample'])
        self.assertNotIn('PRIVATE', json.dumps(r))

    def make_db(self):
        self.binary = self.root / 'schema.exe'; self.binary.write_bytes(b'synthetic-wire-profile')
        self.db = self.root / 'native.db'
        usage = proto([(2, 10), (3, 5), (5, 100), (9, 3), (10, 2), (11, 'response')])
        self.blob = proto([(1, proto([(1, 'PRIVATE-PROMPT'), (4, usage), (19, 'model')])), (4, 'execution')])
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript('CREATE TABLE trajectory_meta(trajectory_id TEXT,cascade_id TEXT); CREATE TABLE gen_metadata(idx INTEGER,data BLOB,size INTEGER);')
            db.execute('INSERT INTO trajectory_meta VALUES (?,?)', ('trajectory', 's'))
            db.execute('INSERT INTO gen_metadata VALUES (0,?,?)', (self.blob, len(self.blob)))

    def capture_db(self, session='s'):
        with patch.object(ag, 'BINARY_SHA256', digest(self.binary.read_bytes())):
            return ag.capture(self.db, session, schema_binary=self.binary)

    def test_antigravity_raw_metadata_without_semantic_promotion_or_secret(self):
        self.make_db(); r = self.capture_db()
        counts = r['raw_native_usage'][0]['native_counts']
        self.assertEqual(counts['cache_read_tokens'], 100)
        self.assertIsNone(counts['cache_write_tokens'])
        self.assertIsNone(r['latest_context_sample'])
        self.assertEqual(r['capabilities']['capabilities']['request_usage']['status'], 'UNKNOWN')
        self.assertEqual(r['capabilities']['capabilities']['request_identity']['status'], 'UNKNOWN')
        self.assertEqual(r['samples'][0]['response_id'], 'response')
        self.assertNotIn('PRIVATE', json.dumps(r))

    def test_antigravity_wal_unknown_binary_wrong_session_and_duplicate(self):
        self.make_db()
        with self.assertRaises(ValidationError): ag.capture(self.db, 's', schema_binary=self.binary)
        with self.assertRaises(ValidationError): self.capture_db('foreign')
        wal = Path(str(self.db) + '-wal'); wal.write_bytes(b'uncheckpointed')
        with self.assertRaises(ValidationError): self.capture_db()
        wal.unlink()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO gen_metadata VALUES (1,?,?)', (self.blob, len(self.blob)))
        with self.assertRaises(ValidationError): self.capture_db()

    def test_protobuf_truncation_and_repeated_scalar_refused(self):
        for raw in (b'\x80', b'\x0a\x10short', b'\x00'):
            with self.assertRaises(ValidationError): ag._wire(raw)
        with self.assertRaises(ValidationError): ag._one(ag._wire(proto([(1, 2), (1, 3)])), 1, int)

    def test_cli_never_overwrites_existing_evidence(self):
        self.run_capture(claude()); output = self.root / 'capture.json'; output.write_text('preserve')
        cli = Path(__file__).resolve().parents[1] / 'scripts/collect_host_context.py'
        result = subprocess.run([sys.executable, str(cli), '--host', 'claude-code', '--source', str(self.path),
                                 '--session-id', 's', '--output', str(output)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
