"""Manufactured records test decisions; these are not observed plugin benefits."""
import copy
import tempfile
import unittest
from pathlib import Path

from value_lab.artifacts import sha
from value_lab.core import ValidationError, demo_suite, demo_records, suite_digest, write_json, freeze
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

    def declare_na(self, family='delivery'):
        self.suite.setdefault('metric_applicability', {})[family] = {'over_refusal': {
            'status': 'not_applicable', 'reason': 'Fixture fixed transformation with no refusal decision interface',
            'review': {'reviewer': 'fixture reviewer', 'basis': 'Reviewed the frozen task and output contract', 'accepted': True}}}

    def declare_scope(self):
        self.suite['usage_scopes'] = [{'id': 'delivery-only', 'families': ['delivery'],
            'rationale': 'Prespecified narrow formatting task; no generalization outside this family',
            'min_clusters': 1, 'min_complete_pairs': 3}]
        self.declare_na()

    def test_baseline_is_visually_distinct_from_harm_and_unknown(self):
        row = self.row('negative-control')
        self.assertEqual((row['decision_code'], row['decision'], row['color']),
                         ('BASELINE_PREFERRED', '基线优先', 'blue'))
        self.assertEqual(self.row()['decision_code'], 'INSUFFICIENT_EVIDENCE')
        self.records[6]['output'] = 'wrong'
        self.assertEqual(self.row('negative-control')['decision_code'], 'OBSERVED_REGRESSION')

    def test_applicability_distinguishes_not_measured_unknown_and_not_applicable(self):
        self.assertEqual(self.row()['metric_status']['over_refusal']['with']['status'], 'NOT_MEASURED')
        self.declare_na()
        row = self.row()
        self.assertEqual(row['decision_code'], 'LIMITED_TRIAL')
        self.assertEqual(row['metric_status']['over_refusal']['with']['status'], 'NOT_APPLICABLE')
        self.assertIsNone(row['over_refusal']['with']['rate'])
        page = render_usage_envelope(self.card())
        self.assertIn('不适用（两组；声明复核）：Fixture', page)
        self.suite.pop('metric_applicability')
        self.refusal_rule()
        self.records.pop(0)
        row = self.row()
        self.assertEqual(row['metric_status']['over_refusal']['with']['status'], 'UNKNOWN')
        self.assertEqual(row['metric_status']['over_refusal']['without']['status'], 'MEASURED')
        self.assertNotEqual(row['decision_code'], 'LIMITED_TRIAL')

    def test_na_requires_review_and_cannot_override_decision_rules(self):
        self.declare_na()
        rule = self.suite['metric_applicability']['delivery']['over_refusal']
        for key, bad in [('reason', ''), ('review', {'reviewer': 'x', 'basis': 'x', 'accepted': False})]:
            original = copy.deepcopy(rule[key])
            rule[key] = bad
            with self.subTest(key=key), self.assertRaises(ValidationError):
                freeze(self.suite, self.root/(key+'.lock'))
            rule[key] = original
        self.refusal_rule()
        with self.assertRaisesRegex(ValidationError, 'contradicts'):
            freeze(self.suite, self.root/'contradiction.lock')

    def test_scoped_signal_survives_unrelated_regression_without_hiding_it(self):
        self.declare_scope()
        self.records[6]['output'] = 'wrong'
        card = self.card()
        self.assertEqual(card['verdict'], 'REGRESSION_DETECTED')
        self.assertEqual(card['status'], 'REVIEW_REQUIRED')
        assessment = card['scope_assessments'][0]
        self.assertTrue(assessment['supported'])
        self.assertEqual(assessment['decision_code'], 'LIMITED_TRIAL')
        self.assertEqual(self.row()['decision_code'], 'LIMITED_TRIAL')
        self.assertEqual(self.row('negative-control')['decision_code'], 'OBSERVED_REGRESSION')
        self.assertTrue(card['envelope']['negative_evidence'])
        self.assertEqual([r['case_id'] for r in card['use_when']], ['structured-delivery'])
        self.assertEqual(card['scope_assessments'][0]['cost_allocation'], 'ORIGINAL_FULL_STUDY')

    def test_unregistered_subset_does_not_escape_study_regression(self):
        self.declare_na()
        self.records[6]['output'] = 'wrong'
        self.assertEqual(self.row()['decision_code'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(self.card()['use_when'], [])

    def test_posthoc_scope_or_na_change_invalidates_original_lock(self):
        self.card()  # Bind records to original contract, then retain the actual old lock.
        lock = {'suite_sha256': suite_digest(self.suite)}
        self.declare_scope()
        card = build_usage_card(self.suite, self.records, lock, self.ledger)
        self.assertFalse(card['scope_assessments'][0]['supported'])
        self.assertNotEqual(next(r for r in card['envelope']['rows'] if r['family'] == 'delivery')['decision_code'], 'LIMITED_TRIAL')
        self.assertTrue(any('Protocol lock' in gap for gap in card['scope_assessments'][0]['blockers']))

    def test_scope_minimum_and_within_scope_missingness_remain_blocking(self):
        self.declare_scope()
        self.suite['usage_scopes'][0]['min_complete_pairs'] = 4
        self.assertFalse(self.card()['scope_assessments'][0]['supported'])
        self.assertNotIn('structured-delivery', [r['case_id'] for r in self.card()['use_when']])
        self.suite['usage_scopes'][0]['min_complete_pairs'] = 3
        self.records.pop(0)
        self.assertFalse(self.card()['scope_assessments'][0]['supported'])
        self.assertEqual(self.row()['unknown_pairs'], 1)

    def test_scope_cannot_drop_case_from_family_or_share_sessions(self):
        self.declare_scope()
        self.suite['usage_scopes'][0]['case_ids'] = ['structured-delivery']
        with self.assertRaises(ValidationError):
            self.card()
        self.suite['usage_scopes'][0].pop('case_ids')
        self.suite['cases'][1]['cluster'] = 'delivery'
        self.records[6]['output'] = 'wrong'
        self.assertFalse(self.card()['scope_assessments'][0]['supported'])
        self.suite['cases'][1]['cluster'] = 'negative-control'
        self.records[6]['session_id'] = self.records[0]['session_id']
        assessment = self.card()['scope_assessments'][0]
        self.assertFalse(assessment['supported'])
        self.assertTrue(any('session' in gap for gap in assessment['blockers']))

    def test_missing_unrelated_run_keeps_scope_cost_allocation_and_full_study_gap(self):
        self.declare_scope()
        self.records.pop(6)
        card = self.card()
        self.assertTrue(card['scope_assessments'][0]['supported'])
        self.assertEqual(card['verdict'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(card['source']['run_counts']['missing_runs'], 1)

    def test_scope_retains_shared_setup_cost_and_cannot_reallocate_to_win(self):
        self.declare_scope()
        self.suite['policy']['require_cost_saving'] = True
        self.ledger['coverage']['setup'] = 'itemized'
        self.ledger['entries'] = [{'id': 'setup', 'category': 'setup', 'arm': 'with',
            'amount_usd': 180, 'basis': 'estimate', 'evidence_ref': 'fixture:setup', 'treatment': 'additional'}]
        assessment = self.card()['scope_assessments'][0]
        self.assertFalse(assessment['supported'])
        self.assertGreater(assessment['cost_delta_usd'], 10)

    def test_synthetic_scopes_and_overlapping_declarations_cannot_promote(self):
        self.declare_scope()
        self.suite['evidence_type'] = 'synthetic'
        self.assertFalse(self.card()['scope_assessments'][0]['supported'])
        duplicate = copy.deepcopy(self.suite['usage_scopes'][0])
        duplicate['id'] = 'another-name'
        self.suite['usage_scopes'].append(duplicate)
        with self.assertRaises(ValidationError):
            freeze(self.suite, self.root/'overlap.lock')

    def test_scope_rechecks_decision_ceilings_within_its_original_cases(self):
        self.declare_scope()
        self.suite.pop('metric_applicability')
        self.refusal_rule()
        self.suite['policy']['decision_error_limits'] = {'over_refusal': 0, 'unsupported_acceptance': 0}
        # Both directions are measured in the scope; neither ceiling is dropped.
        write_json(self.root/'withhold-truth.json', {'decision': 'withhold', 'rationale': 'Fixture unsupported request'})
        write_json(self.root/'withhold-answer.json', {'decision': 'withhold'})
        self.suite['cases'][0]['graders'].append({'id': 'abstain', 'type': 'abstention_correct',
            'artifact': 'unsupported', 'verifier': {'truth': {'path': 'withhold-truth.json', 'sha256': sha(self.root/'withhold-truth.json')}},
            'weight': 1, 'dimension': 'outcome', 'critical': False})
        for r in self.records:
            if r['case_id'] == 'structured-delivery':
                r['artifacts']['unsupported'] = {'path': 'withhold-answer.json', 'sha256': sha(self.root/'withhold-answer.json')}
        self.suite['cases'][1]['graders'].append(copy.deepcopy(self.suite['cases'][0]['graders'][-2]))
        for r in self.records:
            if r['case_id'] == 'unrelated-request':
                r['artifacts'] = {'decision': {'path': 'withhold-answer.json', 'sha256': sha(self.root/'withhold-answer.json')}}
        card = self.card()
        self.assertEqual(card['verdict'], 'REGRESSION_DETECTED')
        self.assertTrue(card['scope_assessments'][0]['supported'])
        self.assertEqual(card['scope_assessments'][0]['methodology']['status'], 'WITHIN_FROZEN_LIMITS')
        self.records[0]['artifacts']['unsupported'] = {'path': 'answer.json', 'sha256': sha(self.root/'answer.json')}
        self.assertFalse(self.card()['scope_assessments'][0]['supported'])

    def test_scope_block_does_not_color_unharmed_family_as_regression(self):
        self.declare_scope()
        self.suite['usage_scopes'][0]['families'].append('negative-control')
        self.declare_na('negative-control')
        self.records[6]['output'] = 'wrong'
        self.assertEqual(self.row()['decision_code'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(self.row()['color'], 'yellow')
        self.assertEqual(self.row('negative-control')['decision_code'], 'OBSERVED_REGRESSION')


if __name__ == '__main__':
    unittest.main()
