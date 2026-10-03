"""Synthetic upgrade/recovery qualification; never host adoption evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.test_codex_context import event, fixture
from value_lab.codex_context import capture
from value_lab.context_stream import capture_incremental, capabilities, qualification, read_checkpoint
from value_lab.core import ValidationError
from value_lab.delivery import read_bundle
from value_lab.host_capabilities import SEMANTICS, resolve_requirements, compare_capabilities, validate

ROOT = Path(__file__).resolve().parents[1]


def encoded(events):
    return ''.join(json.dumps(e) + '\n' for e in events).encode()


class ContextStreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'log.jsonl'
        self.events = fixture()
        self.path.write_bytes(encoded(self.events))
        self.number = 0

    def run_capture(self, previous=None, **kwargs):
        self.number += 1
        target = self.root / str(self.number)
        r = capture_incremental(self.path, 'session', target, previous=previous, **kwargs)
        return target, r['report']

    def append(self, raw):
        with self.path.open('ab') as stream:
            stream.write(raw)

    def test_frozen_legacy_outputs_unchanged(self):
        archive = json.loads((ROOT / 'tests/fixtures/codex-context-v1.json').read_text())
        for case in archive['cases']:
            with self.subTest(case=case['name']):
                self.path.write_bytes(encoded(case['events']) + case['tail'].encode())
                self.assertEqual(capture(self.path, 'session'), case['expected'])

    def test_one_shot_and_every_event_boundary_have_same_state(self):
        full, result = self.run_capture()
        full_state = read_checkpoint(full)[0]['state']
        for split in range(1, len(self.events)):
            with self.subTest(split=split):
                self.path.write_bytes(encoded(self.events[:split]))
                first, _ = self.run_capture()
                self.append(encoded(self.events[split:]))
                second, report = self.run_capture(first)
                self.assertEqual(read_checkpoint(second)[0]['state'], full_state)
                self.assertEqual(report['parser_events_processed'], len(self.events)-split)
                self.assertEqual(report['total_unique_response_ids'], 1)

    def test_partial_json_and_multibyte_tail_resume_without_double_count(self):
        raw = encoded(self.events)
        extra = encoded([event('response_item', {'text': '私人内容'})])
        # Ensure Unicode UTF-8 split, not just ASCII JSON escapes.
        extra = json.dumps(event('response_item', {'text': '私人内容'}), ensure_ascii=False).encode()+b'\n'
        split = extra.index('私'.encode())+1
        self.append(extra[:split])
        first, r = self.run_capture()
        self.assertEqual(r['state'], 'INCOMPLETE_TRAILING_EVENT')
        self.assertEqual(read_checkpoint(first)[0]['offset'], len(raw))
        self.append(extra[split:])
        _, resumed = self.run_capture(first)
        self.assertEqual(resumed['new_response_count'], 0)
        self.assertEqual(resumed['parser_events_processed'], 1)
        self.assertNotIn('私人', json.dumps(resumed, ensure_ascii=False))

    def test_pending_response_is_upsert_after_context_arrives(self):
        self.path.write_bytes(encoded(self.events[:4]))
        first, r = self.run_capture()
        self.assertEqual(r['capabilities']['capabilities']['request_usage']['status'], 'OBSERVED')
        self.assertEqual(r['capabilities']['capabilities']['context_sample']['status'], 'UNKNOWN')
        self.append(encoded(self.events[4:]))
        second, r = self.run_capture(first)
        self.assertEqual(r['new_response_count'], 0)
        self.assertEqual(len(r['sample_upserts']), 1)
        self.assertEqual(r['sample_upserts'][0]['status'], 'MEASURED_RESPONSE_BOUND')
        _, unchanged = self.run_capture(second)
        self.assertEqual(unchanged['sample_upserts'], [])
        self.assertEqual(unchanged['parser_events_processed'], 0)
        self.assertEqual(unchanged['new_bytes_parsed'], 0)

    def test_compaction_across_boundary_revises_original_identity(self):
        first, _ = self.run_capture()
        self.append(encoded([event('compacted', {'compaction_response_id': 'response'})]))
        second, r = self.run_capture(first)
        self.assertEqual(r['new_response_count'], 0)
        self.assertEqual(r['sample_upserts'][0]['status'], 'EXCLUDED_FROM_MAIN_REQUESTS')
        self.assertEqual(read_checkpoint(second)[0]['state']['epoch'], 1)
        self.assertEqual(r['capabilities']['capabilities']['context_sample']['status'], 'UNKNOWN')

    def test_duplicate_response_across_checkpoints_rejected(self):
        first, _ = self.run_capture()
        self.append(encoded([self.events[3]]))
        with self.assertRaisesRegex(ValidationError, 'duplicated'):
            self.run_capture(first)

    def test_modified_prefix_rejected_even_same_size_and_mtime(self):
        import os
        first, _ = self.run_capture()
        stat = self.path.stat()
        self.path.write_bytes(self.path.read_bytes().replace(b'PRIVATE-TEXT', b'PRIVATE-FAKE'))
        os.utime(self.path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with self.assertRaisesRegex(ValidationError, 'PREFIX_CHANGED'):
            self.run_capture(first)

    def test_truncation_rejected(self):
        first, _ = self.run_capture()
        self.path.write_bytes(encoded(self.events[:2]))
        with self.assertRaisesRegex(ValidationError, 'TRUNCATED'):
            self.run_capture(first)

    def test_rotation_with_identical_bytes_rejected(self):
        first, _ = self.run_capture()
        raw = self.path.read_bytes()
        self.path.rename(self.root / 'old')
        self.path.write_bytes(raw)
        with self.assertRaisesRegex(ValidationError, 'ROTATED'):
            self.run_capture(first)

    def test_changed_parser_rejected_without_reinterpreting_old_state(self):
        first, _ = self.run_capture()
        with patch('value_lab.context_stream.PARSER_VERSION', 'new-parser'):
            with self.assertRaisesRegex(ValidationError, 'PARSER_CHANGED'):
                self.run_capture(first)
        self.assertEqual(read_bundle(first)['format'], 'pvl-delivery-1')

    def test_wrong_session_rejected(self):
        first, _ = self.run_capture()
        with self.assertRaisesRegex(ValidationError, 'SESSION_CHANGED'):
            capture_incremental(self.path, 'other', self.root/'wrong', previous=first)

    def test_corrupt_checkpoint_or_missing_commit_marker_rejected(self):
        first, _ = self.run_capture()
        (first/'checkpoint.json').write_text('{}')
        with self.assertRaisesRegex(ValidationError, 'damaged'):
            self.run_capture(first)
        incomplete = self.root/'incomplete'
        incomplete.mkdir()
        (incomplete/'checkpoint.json').write_text('{}')
        with self.assertRaisesRegex(ValidationError, 'Uncommitted'):
            self.run_capture(incomplete)

    def test_atomic_failure_and_resume_retain_old_bundle_and_source(self):
        from value_lab import delivery
        first, _ = self.run_capture()
        original = (first/'checkpoint.json').read_bytes()
        target = self.root/'interrupted'
        writer = delivery._write
        def fail(path, data):
            if path.name == 'report.json':
                raise OSError('simulated interruption')
            return writer(path, data)
        with patch('value_lab.delivery._write', fail), self.assertRaises(OSError):
            capture_incremental(self.path, 'session', target, previous=first)
        self.assertFalse(target.exists())
        pending = capture_incremental(self.path, 'session', target, previous=first)
        self.assertEqual(pending['delivery']['status'], 'INCOMPLETE')
        resumed = capture_incremental(self.path, 'session', target, previous=first, resume=True)
        self.assertEqual(resumed['delivery']['status'], 'COMMITTED')
        self.assertEqual(resumed['report']['new_response_count'], 0)
        self.assertEqual(original, (first/'checkpoint.json').read_bytes())
        self.assertTrue(list(self.root.glob('.interrupted.pvl-*')))

    def test_same_request_publication_idempotent(self):
        target = self.root/'same'
        a = capture_incremental(self.path, 'session', target)
        b = capture_incremental(self.path, 'session', target)
        self.assertEqual(a, b)

    def test_small_batches_do_not_expose_stale_current_sample(self):
        raw = encoded(self.events)
        self.append(encoded([event('event_msg', {'type': 'task_started', 'turn_id': 'later'})]))
        first, r = self.run_capture(max_new_bytes=len(raw))
        self.assertTrue(r['more_events_available'])
        self.assertEqual(r['capabilities']['capabilities']['context_sample']['status'], 'UNKNOWN')
        _, r = self.run_capture(first)
        self.assertFalse(r['more_events_available'])
        self.assertEqual(r['state'], 'AWAITING_RESPONSE')

    def test_total_log_exceeds_legacy_limit_without_raising_limit(self):
        # Reduce only the legacy cap in this fast boundary test. Incremental mode
        # advances bounded complete-event chunks rather than reading the full log.
        with patch('value_lab.codex_context.MAX_BYTES', 64):
            with self.assertRaises(ValidationError):
                capture(self.path, 'session')
            first, r = self.run_capture(max_new_bytes=len(encoded(self.events[:3])))
            _, r = self.run_capture(first)
            self.assertEqual(r['total_unique_response_ids'], 1)

    def test_malformed_new_event_does_not_publish_or_advance(self):
        first, _ = self.run_capture()
        old = (first/'checkpoint.json').read_bytes()
        self.append(b'{bad}\n')
        with self.assertRaisesRegex(ValidationError, 'Malformed'):
            self.run_capture(first)
        self.assertEqual(old, (first/'checkpoint.json').read_bytes())

    def test_report_and_checkpoint_do_not_export_private_text_or_path(self):
        first, r = self.run_capture()
        text = (first/'checkpoint.json').read_text()+(first/'report.json').read_text()
        self.assertNotIn('PRIVATE-', text)
        self.assertNotIn(str(self.path), text)
        self.assertIsNone(r['settled_cost_usd'])
        self.assertEqual(r['model_calls'], 0)

    def test_version_upgrade_degrades_measurements_not_local_resume(self):
        _, old = self.run_capture()
        self.events[0]['payload']['cli_version'] = '0.160.0'
        self.path.write_bytes(encoded(self.events))
        _, new = self.run_capture()
        rows = new['capabilities']['capabilities']
        for name in ('context_sample', 'request_usage', 'session_identity'):
            self.assertEqual(rows[name]['status'], 'UNSUPPORTED')
            self.assertIsNone(rows[name]['value'])
        self.assertEqual(rows['incremental_resume']['status'], 'OBSERVED')
        diff = compare_capabilities(old['capabilities'], new['capabilities'])
        self.assertFalse(diff['unrelated_artifact_checks_invalidated'])

    def test_cumulative_not_cost_context_or_plugin_execution(self):
        _, r = self.run_capture()
        rows = r['capabilities']['capabilities']
        self.assertEqual(rows['thread_usage']['value']['total_tokens'], 10000)
        self.assertEqual(rows['context_sample']['value']['context_tokens'], 210)
        for name in ('settled_cost', 'plugin_identity', 'tool_declared', 'tool_loaded', 'tool_invoked', 'comparable_execution', 'remote_task_status', 'artifact_access'):
            self.assertEqual(rows[name]['status'], 'NOT_PROVIDED')
            self.assertIsNone(rows[name]['value'])

    def test_generic_resolver_has_no_host_switch_or_cross_claim_promotion(self):
        _, r = self.run_capture()
        snapshot = deepcopy(r['capabilities'])
        snapshot['adapter'] = 'synthetic-unrelated-adapter'
        result = resolve_requirements(snapshot, {'usage': {'request_usage': SEMANTICS['request_usage']},
            'cost': {'settled_cost': SEMANTICS['settled_cost']},
            'changed_semantics': {'request_usage': 'input-excludes-cache/v2'}})['claims']
        self.assertEqual(result['usage']['status'], 'LOCAL_EVIDENCE_AVAILABLE')
        self.assertEqual(result['cost']['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(result['changed_semantics']['status'], 'INSUFFICIENT_EVIDENCE')

    def test_semantic_mutation_or_unknown_value_rejected(self):
        _, r = self.run_capture()
        for mutation in ('semantics', 'value', 'missing', 'authorization'):
            c = deepcopy(r['capabilities'])
            if mutation == 'semantics': c['capabilities']['request_usage']['semantic_id'] = 'new'
            if mutation == 'value': c['capabilities']['settled_cost']['value'] = 0
            if mutation == 'missing': c['capabilities'].pop('plugin_identity')
            if mutation == 'authorization': c['execution_authorized'] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError): validate(c)

    def test_cli_incremental_then_resume(self):
        first = self.root/'cli1'
        args = [sys.executable, str(ROOT/'scripts/collect_codex_context.py'), '--rollout', str(self.path),
                '--session-id', 'session', '--output', str(first), '--incremental']
        a = subprocess.run(args, capture_output=True, text=True, timeout=20)
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(json.loads(a.stdout)['new_response_count'], 1)
        args[args.index(str(first))] = str(self.root/'cli2')
        b = subprocess.run(args+['--previous',str(first)], capture_output=True, text=True, timeout=20)
        self.assertEqual(b.returncode, 0, b.stderr)
        self.assertEqual(json.loads(b.stdout)['new_response_count'], 0)

    def test_missing_input_counter_does_not_support_input_usage_claim(self):
        self.events[3]['payload']['usage'].pop('input_tokens')
        self.path.write_bytes(encoded(self.events))
        _, r = self.run_capture()
        self.assertEqual(r['claims']['claims']['request_input_usage']['status'], 'INSUFFICIENT_EVIDENCE')

    def test_unknown_host_leaves_csv_verification_independent(self):
        from value_lab.artifacts import grade_artifact, sha
        self.events[0]['payload']['cli_version'] = 'unknown'
        self.path.write_bytes(encoded(self.events))
        _, r = self.run_capture()
        before = deepcopy(r['capabilities'])
        artifact = self.root/'result.csv'
        artifact.write_text('cell,type\nc1,T\nc2,B\n')
        rule = {'id':'labels', 'type':'artifact', 'artifact':'result', 'dimension':'outcome',
                'weight':1, 'critical':True, 'verifier':{'kind':'labels', 'id_column':'cell',
                'label_column':'type', 'expected':{'c1':'T','c2':'B'}}}
        record = {'artifacts':{'result':{'path':'result.csv', 'sha256':sha(artifact)}}}
        self.assertTrue(grade_artifact(rule, record, self.root)[0])
        self.assertEqual(before, r['capabilities'])
        self.assertEqual(r['claims']['claims']['sampled_context']['status'], 'INSUFFICIENT_EVIDENCE')

    def test_untyped_ordinal_cannot_export_embedded_private_content(self):
        self.events[3]['ordinal'] = {'private':'SECRET'}
        self.path.write_bytes(encoded(self.events))
        with self.assertRaisesRegex(ValidationError, 'ordinal'):
            self.run_capture()

    def test_concurrent_mutation_between_reads_rejected(self):
        from value_lab import context_stream
        first, _ = self.run_capture()
        original = context_stream._prefix
        calls = 0
        def mutate(stream, size):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.path.write_bytes(self.path.read_bytes().replace(b'PRIVATE-TEXT', b'PRIVATE-FAKE'))
            return original(stream, size)
        with patch('value_lab.context_stream._prefix', mutate):
            with self.assertRaisesRegex(ValidationError, 'SOURCE_CHANGED_DURING_READ'):
                self.run_capture(first)

    def test_oversized_event_or_too_small_batch_never_advances(self):
        with patch('value_lab.context_stream.MAX_LINE_BYTES', 64):
            with self.assertRaisesRegex(ValidationError, 'EVENT_TOO_LARGE'):
                self.run_capture()
        with self.assertRaisesRegex(ValidationError, 'READ_BUDGET_TOO_SMALL'):
            self.run_capture(max_new_bytes=2)

    def test_unknown_semantics_and_empty_requirements_cannot_pass(self):
        _, r = self.run_capture()
        for claims in ({}, {'anything':{}}):
            with self.assertRaises(ValidationError): resolve_requirements(r['capabilities'], claims)

    def test_schema_accepts_real_snapshot_rejects_hidden_capability_promotion(self):
        import jsonschema
        schema = json.loads((ROOT/'schemas/host-capabilities.schema.json').read_text())
        _, r = self.run_capture()
        jsonschema.Draft202012Validator(schema).validate(r['capabilities'])
        bad = deepcopy(r['capabilities'])
        bad['capabilities']['settled_cost']['value'] = 0
        self.assertTrue(list(jsonschema.Draft202012Validator(schema).iter_errors(bad)))


if __name__ == '__main__':
    unittest.main()
