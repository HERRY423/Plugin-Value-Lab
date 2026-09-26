"""Manufactured records test decisions; these are not observed plugin benefits."""
import copy
import tempfile
import unittest
from pathlib import Path

from value_lab.artifacts import sha
from value_lab.core import ValidationError, demo_suite, demo_records, suite_digest, write_json
from value_lab.usage import build_usage_card, check_usage_envelope, render_usage_envelope


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.suite = demo_suite()
        self.suite['evidence_type'] = 'local'  # Test gates only, not real evidence.
        self.suite['plugin']['sha256'] = 'a' * 64
        self.suite['conditions'].update(host_version='1.2.3', model_version='revision-123')
        self.suite['task_families'] = ['delivery', 'negative-control', 'evidence-boundary', 'unmeasured']
        self.records = demo_records(self.suite)
        for r in self.records:
            r['source'] = 'manual'
        self.ledger = {'schema_version': 1, 'coverage': {k: 'not_applicable' for k in ('setup', 'judge', 'retry', 'other')}, 'entries': []}

    def card(self):
        digest = suite_digest(self.suite)
        for r in self.records:
            r['suite_sha256'] = digest
        return build_usage_card(self.suite, self.records, {'suite_sha256': digest}, self.ledger,
                                artifact_root=self.root, verifier_root=self.root)

    def row(self, family='delivery'):
        return next(r for r in self.card()['envelope']['rows'] if r['family'] == family)

    def refusal_rule(self):
        write_json(self.root / 'truth.json', {'decision': 'allow', 'rationale': 'Unit test allowed task'})
        write_json(self.root / 'answer.json', {'decision': 'allow'})
        self.suite['cases'][0]['graders'].append({'id': 'refusal', 'type': 'over_refusal',
            'artifact': 'decision', 'verifier': {'truth': {'path': 'truth.json', 'sha256': sha(self.root / 'truth.json')}},
            'weight': 1, 'dimension': 'outcome', 'critical': False})
        for r in self.records:
            if r['case_id'] == 'structured-delivery':
                r['artifacts'] = {'decision': {'path': 'answer.json', 'sha256': sha(self.root / 'answer.json')}}

    def test_unmeasured_gray_missing_pair_not_zero_and_no_refusal_not_green(self):
        self.assertEqual(self.row('unmeasured')['color'], 'gray')
        self.assertEqual(self.row()['color'], 'yellow')
        self.assertIsNone(self.row()['over_refusal']['with']['rate'])
        self.records = [r for r in self.records if r['case_id'] != 'structured-delivery' or r['arm'] == 'with']
        row = self.row()
        self.assertIsNone(row['quality_delta'])
        self.assertEqual(row['unknown_pairs'], 3)
        self.assertEqual(row['arms']['without']['planned'], 3)
        self.assertEqual(row['color'], 'yellow')

    def test_green_requires_refusal_measurement_and_identity(self):
        self.refusal_rule()
        self.assertEqual(self.row()['color'], 'green')
        self.suite['plugin'].pop('sha256')
        self.assertEqual(self.row()['color'], 'yellow')
        self.suite['plugin']['sha256'] = 'a' * 64
        self.suite['conditions']['model_version'] = 'provider alias; unverified'
        self.assertEqual(self.row()['color'], 'yellow')

    def test_synthetic_never_green(self):
        self.refusal_rule()
        self.suite['evidence_type'] = 'synthetic'
        self.assertNotEqual(self.row()['color'], 'green')

    def test_harm_red_and_negative_first(self):
        self.records[6]['output'] = 'wrong'
        card = self.card()
        first = card['envelope']['rows'][0]
        self.assertEqual((first['color'], first['harmed_pairs']), ('red', 1))
        page = render_usage_envelope(card)
        self.assertLess(page.index('先看负向证据'), page.index('<table>'))
        self.assertIn('harmed pairs', page)

    def test_failure_costs_kept_and_shared_setup_allocated(self):
        self.records[0]['status'] = 'timeout'
        row = self.row()
        self.assertEqual(row['color'], 'red')
        self.assertEqual(row['arms']['with']['failed'], 1)
        self.assertAlmostEqual(row['arms']['with']['cost_per_success_usd'], 3 * 1.02 / 2)
        self.ledger['coverage']['setup'] = 'itemized'
        self.ledger['entries'] = [{'id': 'setup', 'category': 'setup', 'arm': 'shared',
            'amount_usd': 18, 'basis': 'estimate', 'evidence_ref': 'fixture:setup',
            'treatment': 'additional', 'with_fraction': .5}]
        self.assertAlmostEqual(self.row()['arms']['with']['cost_per_success_usd'], (3 * 1.02 + 3) / 2)

    def test_missing_costs_and_zero_success_remain_unknown(self):
        self.ledger = None
        self.assertIsNone(self.row()['arms']['with']['cost_per_success_usd'])
        for r in self.records:
            if r['arm'] == 'with':
                r['status'] = 'timeout'
        self.assertIsNone(self.row()['arms']['with']['cost_per_success_usd'])

    def test_refusal_and_unknown_denominators(self):
        self.refusal_rule()
        write_json(self.root / 'refused.json', {'decision': 'withhold'})
        self.records[0]['artifacts']['decision'] = {'path': 'refused.json', 'sha256': sha(self.root / 'refused.json')}
        row = self.row()
        self.assertEqual(row['over_refusal']['with'], {'planned': 3, 'errors': 1, 'unknown': 0, 'rate': 1/3})
        self.assertEqual(row['color'], 'red')
        self.records.pop(0)
        self.assertEqual(self.row()['over_refusal']['with']['unknown'], 1)
        self.assertIsNone(self.row()['over_refusal']['with']['rate'])

    def test_hash_or_host_change_invalidates_without_version_bump(self):
        card = self.card()
        self.assertEqual(check_usage_envelope(card, 'a' * 64, self.suite['conditions'])['status'], 'MATCHED_DECLARATIONS')
        self.assertEqual(check_usage_envelope(card, 'b' * 64, self.suite['conditions'])['status'], 'STALE')
        conditions = copy.deepcopy(self.suite['conditions'])
        conditions['host_version'] = 'next'
        self.assertEqual(check_usage_envelope(card, 'a' * 64, conditions)['changed'], ['conditions'])

    def test_multiple_cases_stay_one_family_and_missing_rows_stay_planned(self):
        self.suite['cases'][1]['cluster'] = 'delivery'
        row = self.row()
        self.assertEqual(len(row['case_ids']), 2)
        self.assertEqual(row['planned_pairs'], 6)
        self.assertAlmostEqual(row['quality_delta'], (1 - 1/6) / 2)
        self.records = [r for r in self.records if r['case_id'] not in row['case_ids']]
        row = self.row()
        self.assertEqual(row['color'], 'gray')
        self.assertEqual(row['unknown_pairs'], 6)
        self.assertIsNone(row['arms']['with']['failure_rate'])

    def test_incomplete_identity_check_is_unknown_and_inputs_are_not_mutated(self):
        self.suite['plugin'].pop('sha256')
        self.card()  # Bind fixture records before checking immutability.
        before = copy.deepcopy((self.suite, self.records, self.ledger))
        card = self.card()
        self.assertEqual(before, (self.suite, self.records, self.ledger))
        self.assertEqual(check_usage_envelope(card, None, self.suite['conditions'])['status'], 'UNKNOWN')

    def test_hostile_text_is_literal_and_no_remote_resources(self):
        self.suite['task_families'].append('<img src=x onerror=alert(1)>')
        page = render_usage_envelope(self.card())
        self.assertNotIn('<img', page)
        self.assertIn('&lt;img', page)
        self.assertNotIn('<script', page)
        self.assertIn("default-src 'none'", page)

    def test_invalid_family_or_hash_rejected(self):
        self.suite['task_families'] = ['x', 'x']
        with self.assertRaises(ValidationError):
            self.card()
        self.suite['task_families'] = []
        self.suite['plugin']['sha256'] = 'version-is-not-content'
        with self.assertRaises(ValidationError):
            self.card()


if __name__ == '__main__':
    unittest.main()
