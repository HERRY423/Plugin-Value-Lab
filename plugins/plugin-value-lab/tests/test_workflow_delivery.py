"""Workflow boundary tests: real evaluator decisions, tampering and unsigned mappings."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from value_lab.core import demo_suite, demo_records, evaluate, freeze, load_json, write_json, suite_digest
from value_lab.cli import write_records
from value_lab.ci_gate import run, summary
from value_lab.evidence_crate import export_crate, verify_crate


class WorkflowDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.suite = demo_suite()
        self.records = demo_records(self.suite)
        self.save()

    def save(self):
        write_json(self.root / 'suite.json', self.suite)
        (self.root / 'runs.jsonl').unlink(missing_ok=True)
        write_records(self.root / 'runs.jsonl', self.records)
        lock = self.root / 'lock.json'
        if lock.exists():
            lock.unlink()
        self.lock = freeze(self.suite, lock)
        write_json(self.root / 'report.json', evaluate(self.suite, self.records, self.lock))
        self.spec = {'name': 'Synthetic evidence', 'license': 'https://spdx.org/licenses/CC0-1.0',
                     'files': {'suite': 'suite.json', 'lock': 'lock.json', 'records': 'runs.jsonl', 'report': 'report.json'}}
        write_json(self.root / 'package.json', self.spec)

    def gate(self, name='gate'):
        return run(self.root / 'suite.json', self.root / 'lock.json', self.root / name, records=self.root / 'runs.jsonl')

    def crate(self, name='crate'):
        return export_crate(self.root / 'package.json', self.root / name)

    def test_simulation_and_missing_data_fail_closed(self):
        self.assertEqual(self.gate()['exit_code'], 2)
        self.assertEqual(self.gate('another')['model_calls'], 0)
        self.records = []
        self.save()
        self.assertEqual(self.gate('empty')['exit_code'], 2)

    def test_existing_real_evaluator_exit_semantics(self):
        # Manufactured unit-test inputs only; never retained as real evidence.
        self.suite['evidence_type'] = 'local'
        self.records = demo_records(self.suite)
        for record in self.records:
            record['source'] = 'manual'
        self.save()
        self.assertEqual(self.gate('positive')['exit_code'], 0)
        for i in range(0, len(self.records), 2):
            self.records[i + 1]['output'] = self.records[i]['output']
        self.save()
        self.assertEqual(self.gate('equal')['exit_code'], 1)
        self.records[0]['cost']['tool_usd'] = None
        self.save()
        self.assertEqual(self.gate('unknown')['exit_code'], 2)

    def test_submitted_executable_never_evaluated(self):
        self.suite['cases'][0]['graders'] = [{'type': 'exec'}]
        write_json(self.root / 'suite.json', self.suite)
        with patch('value_lab.ci_gate.evaluate', side_effect=AssertionError('must not evaluate')):
            self.assertEqual(self.gate()['exit_code'], 2)

    def test_summary_escapes_mentions_and_html(self):
        text = summary({'verdict': 'INSUFFICIENT_EVIDENCE', 'blockers': ['<script>@team</script>']}, 2, 0)
        self.assertNotIn('<script>', text)
        self.assertNotIn('@team', text)

    def test_portable_crate_has_scoped_unsigned_statement_and_missing_evidence(self):
        result = self.crate()
        self.assertEqual(result['anchor'], 'EXTERNAL_COMMITMENT_MATCHED')
        self.assertEqual(result['statement_signature'], 'UNSIGNED')
        self.assertIn('replay_receipt', result['missing_components'])
        statement = load_json(self.root / 'crate/statement.json')
        self.assertEqual(statement['_type'], 'https://in-toto.io/Statement/v1')
        self.assertNotIn('signatures', statement)
        self.assertEqual(verify_crate(self.root / 'crate')['scientific_validity'], 'NOT_ESTABLISHED')
        self.assertEqual((self.root / 'crate/data/lock.bin').read_bytes(), (self.root / 'lock.json').read_bytes())

    def test_tampered_payload_graph_extra_file_and_anchor_are_rejected(self):
        for change in ('payload', 'graph', 'extra', 'anchor'):
            with self.subTest(change=change):
                result = self.crate(change)
                root = self.root / change
                if change == 'payload':
                    (root / 'data/lock.bin').write_bytes(b'{}')
                elif change == 'graph':
                    graph = load_json(root / 'ro-crate-metadata.json')
                    graph['@graph'][1]['description'] = 'Scientifically certified'
                    write_json(root / 'ro-crate-metadata.json', graph)
                elif change == 'extra':
                    (root / 'private.txt').write_text('unlisted')
                with self.assertRaises(ValueError):
                    verify_crate(root, '0'*64 if change == 'anchor' else result['metadata_sha256'])

    def test_traversal_and_unbound_report_rejected_before_output(self):
        self.spec['files']['lock'] = '../lock.json'
        write_json(self.root / 'package.json', self.spec)
        with self.assertRaises(ValueError):
            self.crate()
        self.assertFalse((self.root / 'crate').exists())
        self.save()
        lock = load_json(self.root / 'lock.json')
        lock['suite_sha256'] = '0'*64
        write_json(self.root / 'lock.json', lock)
        with self.assertRaises(ValueError):
            self.crate()

    def test_stale_signed_review_is_rejected_and_original_bytes_retained(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from value_lab.signatures import sign
        registration = {'test': 'synthetic-only'}
        write_json(self.root / 'registration.json', registration)
        review = {'format': 'pvl-study-review-1', 'reviewer_id': 'fixture-not-a-person',
                  'suite_sha256': suite_digest(self.suite),
                  'report_sha256': suite_digest(load_json(self.root / 'report.json')),
                  'registration_sha256': suite_digest(registration), 'decision': 'unknown', 'basis': 'test'}
        write_json(self.root / 'review.json', review)
        write_json(self.root / 'signature.json', sign(review, Ed25519PrivateKey.generate(), 'pvl-review-1'))
        self.spec['files'].update(registration='registration.json', review_statement='review.json', review_signature='signature.json')
        write_json(self.root / 'package.json', self.spec)
        result = self.crate()
        self.assertEqual(result['review_signature'], 'KEY_SIGNATURE_VALID_IDENTITY_UNTRUSTED')
        self.assertEqual((self.root / 'crate/data/review_signature.bin').read_bytes(), (self.root / 'signature.json').read_bytes())
        review['decision'] = 'accept'
        write_json(self.root / 'review.json', review)
        with self.assertRaises(ValueError):
            self.crate('bad-signature')

    def test_no_overwrite(self):
        self.crate()
        with self.assertRaises(FileExistsError):
            self.crate()


if __name__ == '__main__':
    unittest.main()
