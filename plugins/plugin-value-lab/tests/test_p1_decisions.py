"""Unequal task-family sizes must not silently change a frozen estimand."""
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path

from value_lab.core import ValidationError, demo_suite, demo_records, evaluate, suite_digest, validate_suite
from value_lab.report import write_reports
from value_lab.usage import build_usage_card


class DecisionReviewTests(unittest.TestCase):
    def setUp(self):
        self.suite = demo_suite()
        self.suite.update(evidence_type='local', runs_per_case=1)
        self.suite['policy'].update(min_clusters=2, quality_floor=.5, min_quality_delta=.1, max_case_regression=1)
        self.suite['cases'] = [{'id': 'case' + str(i), 'cluster': 'many' if i < 3 else 'rare',
            'kind': 'task', 'prompt': 'Manufactured arithmetic test; not actual human or model data',
            'graders': [{'id': t, 'type': 'contains', 'value': t, 'dimension': 'outcome', 'weight': 1, 'critical': False}
                        for t in ('alpha', 'beta', 'gamma', 'delta')]} for i in range(4)]
        self.records = demo_records(demo_suite())[:8]
        for index, record in enumerate(self.records):
            record.update(case_id='case' + str(index // 2), repetition=1)
        for r in self.records:
            r['source'] = 'manual'  # Fixture-only label to exercise the gate, never exported as empirical evidence.
            if r['case_id'] == 'case3':
                r['output'] = 'alpha beta' if r['arm'] == 'with' else 'alpha beta gamma delta'
            else:
                r['output'] = 'alpha beta gamma delta' if r['arm'] == 'with' else 'alpha beta gamma'

    def run_report(self):
        digest = suite_digest(self.suite)
        for record in self.records:
            record['suite_sha256'] = digest
        return evaluate(self.suite, self.records, {'suite_sha256': digest})

    def test_primary_gate_and_interval_use_frozen_weighting(self):
        self.suite['policy']['min_quality_delta'] = .05
        case = self.run_report()
        self.assertAlmostEqual(case['summary']['quality_delta'], .0625)
        self.assertEqual(case['verdict'], 'PROMISING_LOCAL_SIGNAL')
        self.suite['policy']['quality_weighting'] = 'family'
        family = self.run_report()
        self.assertAlmostEqual(family['summary']['quality_delta'], -.125)
        self.assertFalse(family['summary']['quality_gate_met'])
        self.assertEqual(family['verdict'], 'NO_DEMONSTRATED_GAIN')
        self.assertEqual(family['uncertainty']['quality_weighting'], 'family')
        self.assertEqual(family['summary']['quality_delta'], family['value_metrics']['families']['equal_weight_quality_delta'])
        self.assertEqual(family['quality_estimand']['sensitivity']['case']['quality_delta'], case['summary']['quality_delta'])

    def test_old_default_is_exactly_explicit_case_weighting(self):
        old = self.run_report()
        self.suite['policy']['quality_weighting'] = 'case'
        new = self.run_report()
        self.assertEqual(old['summary'], new['summary'])
        self.assertEqual(old['uncertainty'], new['uncertainty'])

    def test_weighting_change_invalidates_existing_freeze(self):
        self.run_report()
        digest = suite_digest(self.suite)
        self.suite['policy']['quality_weighting'] = 'family'
        result = evaluate(self.suite, self.records, {'suite_sha256': digest})
        self.assertEqual(result['verdict'], 'INSUFFICIENT_EVIDENCE')

    def test_invalid_weighting_cannot_silently_fallback(self):
        for value in (None, [], True, 'auto', 'best'):
            self.suite['policy']['quality_weighting'] = value
            with self.assertRaises(ValidationError):
                validate_suite(self.suite)

    def test_failed_or_missing_task_never_becomes_recommended_via_average(self):
        self.records[0]['status'] = 'timeout'
        report = self.run_report()
        decision = report['decision_review']
        self.assertEqual(decision['single_run']['arms']['with']['failed'], 1)
        self.assertFalse(decision['controlled_trial']['all_with_success_gate_met'])
        self.assertEqual(decision['broader_use']['status'], 'NOT_ESTABLISHED')
        self.records.pop(0)
        self.assertEqual(self.run_report()['decision_review']['single_run']['arms']['with']['unknown'], 1)

    def test_report_and_usage_card_expose_same_decision_basis(self):
        report = self.run_report()
        card = build_usage_card(self.suite, self.records, {'suite_sha256': suite_digest(self.suite)})
        self.assertEqual(card['source']['quality_estimand'], report['quality_estimand'])
        with tempfile.TemporaryDirectory() as directory:
            paths = write_reports(report, directory)
            for kind in ('html', 'md'):
                content = Path(paths[kind]).read_text(encoding='utf-8')
                self.assertIn('统一口径', content)
                self.assertIn('广泛采用仍未建立', content)


if __name__ == '__main__':
    unittest.main()
