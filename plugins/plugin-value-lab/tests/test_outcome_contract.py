"""Manufactured boundary probes: labels exercise gates, not real user benefit."""
from copy import deepcopy
from itertools import permutations
import json
from pathlib import Path
import tempfile
import unittest

from value_lab.artifacts import sha
from value_lab.core import ValidationError, evaluate, freeze, suite_digest, validate_suite, write_json
from value_lab.usage import build_usage_card


class OutcomeContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_json(self.root / 'truth.json', {'decision': 'allow', 'rationale': 'Manufactured arithmetic fixture'})
        def rule(gid, kind, verifier):
            return {'id': gid, 'type': kind, 'dimension': 'outcome', 'critical': False,
                    'weight': 1, 'artifact': 'result', 'verifier': verifier}
        self.decision = rule('decision', 'over_refusal', {'truth': {'path': 'truth.json', 'sha256': sha(self.root / 'truth.json')}})
        self.delivery = rule('delivery', 'artifact_schema', {'format': 'json', 'fields': {'answer': {'type': 'number', 'nullable': False}},
                              'allow_extra': True, 'min_rows': 1})
        self.correctness = rule('correctness', 'artifact', {'kind': 'json_fields', 'expected': {'answer': 7}})
        self.process = {'id': 'process', 'type': 'contains', 'dimension': 'process',
                        'critical': False, 'weight': 1000, 'value': 'PROCESS_OK'}
        self.suite = {'schema_version': 1, 'id': 'manufactured-outcome-boundaries',
            'plugin': {'name': 'fixture', 'version': '0', 'sha256': 'a' * 64},
            'evidence_type': 'local', 'runs_per_case': 1,
            'conditions': {'model': 'fixture', 'model_version': '1', 'host': 'offline', 'host_version': '1',
                           'environment': 'manufactured-not-observed', 'tools': [], 'budget': {'max_turns': 2}},
            'policy': {'min_quality_delta': 0, 'quality_floor': .6, 'max_case_regression': 1,
                       'min_clusters': 2, 'require_cost_saving': False, 'human_hourly_usd': 60},
            'cases': [{'id': f'case-{i}', 'cluster': f'family-{i}', 'kind': 'task',
                       'prompt': 'Return the exact numeric answer, not merely permission to answer.',
                       'graders': []} for i in range(2)],
            'usage_scopes': [{'id': 'all-tested', 'families': ['family-0', 'family-1'],
                'rationale': 'Manufactured software gate fixture only', 'min_clusters': 2, 'min_complete_pairs': 2}]}
        self.ledger = {'schema_version': 1, 'entries': [],
                       'coverage': {k: 'not_applicable' for k in ('setup', 'judge', 'retry', 'other')}}
        self.counter = 0

    def run_case(self, graders, with_value, without_value=None, *, kind='task', contract=None, status='completed'):
        suite = deepcopy(self.suite)
        for case in suite['cases']:
            case['graders'] = deepcopy(graders)
            case['kind'] = kind
            if contract is not None:
                case['success_contract'] = deepcopy(contract)
        self.counter += 1
        lock = freeze(suite, self.root / f'lock-{self.counter}.json')
        records = []
        for case in suite['cases']:
            for arm, obj in [('with', with_value), ('without', without_value if without_value is not None else with_value)]:
                path = self.root / f'{case["id"]}-{arm}.json'
                write_json(path, obj)
                records.append({'case_id': case['id'], 'arm': arm, 'repetition': 1,
                    'source': 'manual', 'session_id': f'MANUFACTURED-{case["id"]}-{arm}',
                    'suite_sha256': lock['suite_sha256'], 'conditions': suite['conditions'],
                    'plugin_loaded': arm == 'with', 'status': status, 'output': 'PROCESS_OK',
                    'cost': {'model_usd': 1, 'tool_usd': 0, 'human_minutes': 0}, 'human_intervals': [],
                    'artifacts': {'result': {'path': path.name, 'sha256': sha(path)}}})
        options = dict(artifact_root=self.root, verifier_root=self.root)
        if hasattr(self, 'edit_records'):
            self.edit_records(records)
        report = evaluate(suite, records, lock, self.ledger, **options)
        card = build_usage_card(suite, records, lock, self.ledger, **options)
        self.last_study = {'suite': suite, 'records': records, 'lock': lock, 'cost_ledger': self.ledger}
        return report, card

    def assert_counts(self, report, successes, unknown, arm='with'):
        metrics = report['value_metrics']['success']['arms'][arm]
        self.assertEqual((metrics['successes'], metrics['unknown']), (successes, unknown))
        costs = report['cost_analysis']['arms'][arm]
        self.assertEqual(costs['successful_outcomes'], successes)
        self.assertEqual(costs['success_unknown'], unknown)
        expected = costs['total_usd'] / successes if successes and not unknown else None
        self.assertEqual(costs['cost_per_success_usd'], expected)
        self.assertEqual(report['value_metrics']['arms'][arm]['cost_per_success_usd'], expected)

    def assert_not_recommended(self, report, card):
        self.assertNotEqual(report['verdict'], 'PROMISING_LOCAL_SIGNAL')
        self.assertFalse(report['value_metrics']['benefit_claim_eligible'])
        self.assertEqual(card['use_when'], [])
        self.assertFalse(any(s['supported'] for s in card['scope_assessments']))
        self.assertFalse(any(r['decision_code'] == 'LIMITED_TRIAL' for r in card['envelope']['rows']))

    def test_o1_process_pass_cannot_establish_delivery_or_correctness(self):
        for graders in ([self.decision], [self.decision, self.process]):
            with self.subTest(process=len(graders) == 2):
                report, card = self.run_case(graders, {'decision': 'allow', 'answer': None}, {'decision': 'withhold'})
                self.assert_counts(report, 0, 2)
                self.assert_not_recommended(report, card)
                self.assertEqual(report['summary']['with_score'], 1)

    def test_o2_o4_m5_wrong_numeric_above_floor_never_success_or_recommendation(self):
        report, card = self.run_case([self.decision, self.delivery, self.correctness],
            {'decision': 'allow', 'answer': 6}, {'decision': 'withhold', 'answer': None})
        self.assertAlmostEqual(report['summary']['with_score'], 2 / 3)
        self.assertTrue(report['summary']['quality_gate_met'])
        self.assert_counts(report, 0, 0)
        self.assert_not_recommended(report, card)

    def test_m2_all_grader_orders_have_identical_success(self):
        states = []
        for rules in permutations([self.decision, self.delivery, self.correctness]):
            report, _ = self.run_case(list(rules), {'decision': 'allow', 'answer': 6})
            self.assert_counts(report, 0, 0)
            states.append(report['cases'][0]['runs'][0]['task_outcome'])
        self.assertTrue(all(state == states[0] for state in states))

    def test_m1_arm_state_never_leaks(self):
        good = {'decision': 'allow', 'answer': 7}
        bad = {'decision': 'withhold', 'answer': 6}
        for value in (good, bad, good):
            report, _ = self.run_case([self.decision, self.delivery, self.correctness], value, good)
            self.assert_counts(report, 2, 0, 'without')

    def test_zero_is_a_correct_result_and_positive_control_is_recommended(self):
        self.correctness['verifier']['expected']['answer'] = 0
        report, card = self.run_case([self.decision, self.delivery, self.correctness, self.process],
            {'decision': 'allow', 'answer': 0}, {'decision': 'withhold', 'answer': None})
        self.assert_counts(report, 2, 0)
        self.assertEqual(report['verdict'], 'PROMISING_LOCAL_SIGNAL')
        self.assertEqual(len(card['use_when']), 2)
        self.assertTrue(card['scope_assessments'][0]['supported'])
        process = next(g for g in report['cases'][0]['runs'][0]['grades'] if g['id'] == 'process')
        self.assertFalse(process['scored'])

    def test_valid_falsy_results_use_typed_checks_not_python_truthiness(self):
        for value in (0, False, '', [], {}, None):
            with self.subTest(value=value):
                self.correctness['verifier']['expected']['answer'] = value
                report, _ = self.run_case([self.correctness], {'answer': value})
                self.assert_counts(report, 2, 0)

    def test_m3_critical_process_failure_is_unknown_in_every_consumer(self):
        self.process.update(critical=True, value='MISSING_PROCESS')
        report, card = self.run_case([self.decision, self.delivery, self.correctness, self.process],
                                    {'decision': 'allow', 'answer': 7})
        self.assert_counts(report, 0, 2)
        self.assert_not_recommended(report, card)
        self.assertEqual(report['summary']['with_score'], 1)

    def test_m6_valid_pure_decision_task_and_abstention(self):
        write_json(self.root / 'truth.json', {'decision': 'withhold', 'rationale': 'Decision-only manufactured fixture'})
        self.decision['verifier']['truth']['sha256'] = sha(self.root / 'truth.json')
        self.decision['type'] = 'abstention_correct'
        for kind, contract in [('abstention', None), ('task', {'version': 1, 'mode': 'decision'})]:
            report, _ = self.run_case([self.decision, self.process], {'decision': 'withhold'}, kind=kind, contract=contract)
            self.assert_counts(report, 2, 0)

    def test_schema_and_process_alone_do_not_establish_correctness(self):
        report, card = self.run_case([self.delivery, self.process], {'answer': 7})
        self.assert_counts(report, 0, 2)
        self.assert_not_recommended(report, card)

    def test_unscored_noncritical_failure_or_unknown_never_changes_success(self):
        for process in [dict(self.process, value='MISSING'),
                        {'id': 'process', 'type': 'human', 'rubric': 'Optional trace note',
                         'dimension': 'process', 'critical': False, 'weight': 1000}]:
            report, _ = self.run_case([self.decision, self.delivery, self.correctness, process],
                                     {'decision': 'allow', 'answer': 7})
            self.assert_counts(report, 2, 0)
            self.assertEqual(report['summary']['with_score'], 1)

    def test_missing_artifact_preserves_unknown_denominators_across_consumers(self):
        def remove_artifact(records):
            records[0]['artifacts'] = {}
        self.edit_records = remove_artifact
        report, card = self.run_case([self.decision, self.delivery, self.correctness],
                                    {'decision': 'allow', 'answer': 7})
        self.assert_counts(report, 1, 1)
        self.assert_counts(report, 2, 0, 'without')
        self.assertIsNone(report['value_metrics']['cost_per_success_saved_usd'])
        self.assert_not_recommended(report, card)
        row = next(r for r in card['envelope']['rows'] if r['family'] == 'family-0')
        self.assertEqual(row['arms']['with']['success_unknown'], 1)
        self.assertIsNone(row['arms']['with']['cost_per_success_usd'])

    def test_runtime_failure_cannot_be_repaired_by_passing_artifact_checks(self):
        report, card = self.run_case([self.decision, self.delivery, self.correctness],
                                    {'decision': 'allow', 'answer': 7}, status='timeout')
        self.assert_counts(report, 0, 0)
        self.assert_not_recommended(report, card)

    def test_contract_survives_tree_roundtrip_and_changed_contract_invalidates_lock(self):
        from value_lab.declarative import dump_evals, load_evals
        contract = {'version': 1, 'mode': 'task', 'decision': ['decision'],
                    'delivery': ['delivery'], 'correctness': ['correctness']}
        self.run_case([self.decision, self.delivery, self.correctness], {'decision': 'allow', 'answer': 7}, contract=contract)
        suite = self.last_study['suite']
        dump_evals(suite, self.root / 'evals')
        self.assertEqual(load_evals(self.root / 'evals'), suite)
        altered = deepcopy(suite)
        for case in altered['cases']:
            del case['success_contract']
        report = evaluate(altered, self.last_study['records'], self.last_study['lock'], self.ledger,
                          artifact_root=self.root, verifier_root=self.root)
        self.assertTrue(any('Protocol lock' in b for b in report['blockers']))

    def test_empty_contract_lists_cannot_erase_existing_correctness_failure(self):
        report, card = self.run_case([self.decision, self.delivery, self.correctness],
            {'decision': 'allow', 'answer': 6}, contract={'version': 1, 'mode': 'task', 'correctness': []})
        self.assert_counts(report, 0, 0)
        self.assert_not_recommended(report, card)

    def test_independent_delivery_and_correctness_endpoints_and_rendering(self):
        from test_interpretation import plan
        from value_lab.report import write_reports
        self.suite['policy']['value_interpretation'] = plan()
        report, _ = self.run_case([self.decision, self.delivery, self.correctness], {'decision': 'allow', 'answer': 6})
        endpoints = report['value_interpretation']['endpoints']
        self.assertEqual(endpoints['runtime_reliability']['arms']['with']['successes'], 2)
        self.assertEqual(endpoints['full_delivery']['arms']['with']['successes'], 2)
        self.assertEqual(endpoints['scientific_correctness']['arms']['with']['failures'], 2)
        write_reports(report, self.root / 'report')
        self.assertIn('任务成功：失败', (self.root / 'report/report.html').read_text(encoding='utf-8'))
        self.assertIn('correctness=FAIL', (self.root / 'report/report.md').read_text(encoding='utf-8'))

    def test_explicit_contract_cannot_promote_process_or_schema_to_correctness(self):
        for field, ids in [('correctness', ['process']), ('correctness', ['delivery']), ('decision', ['absent'])]:
            suite = deepcopy(self.suite)
            for case in suite['cases']:
                case['graders'] = [self.decision, self.delivery, self.process]
                case['success_contract'] = {'version': 1, 'mode': 'task', field: ids}
            with self.subTest(field=field, ids=ids), self.assertRaises(ValidationError):
                validate_suite(suite)


if __name__ == '__main__':
    unittest.main()
