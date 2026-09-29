"""Grader-combination counterexamples from the 2026-09-28 review.

All fixtures are manufactured column sums, not independent scientific evidence.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from test_metamorphic import numeric_design, observations
from value_lab.artifacts import sha
from value_lab.core import demo_records, demo_suite, evaluate, write_json


class CorrectnessReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.design = numeric_design()
        self.good = observations(self.design)
        self.zero = observations(self.design, lambda source: {
            'row_ids': ['summary'], 'columns': source['matrix']['columns'],
            'values': [[0] * len(source['matrix']['columns'])]})
        write_json(self.root / 'design.json', self.design)
        self.relation = {'id': 'relation', 'type': 'metamorphic', 'dimension': 'outcome',
            'weight': 1, 'critical': False, 'artifact': 'result',
            'verifier': {'design': {'path': 'design.json', 'sha256': sha(self.root / 'design.json')}}}

    def json_rule(self, path='status', value='ok'):
        return {'id': 'reference', 'type': 'json_equals', 'dimension': 'outcome',
                'weight': 1, 'critical': False, 'path': path, 'value': value}

    def file_rule(self, expected=None, artifact='result'):
        return {'id': 'reference', 'type': 'artifact', 'dimension': 'outcome',
                'weight': 1, 'critical': False, 'artifact': artifact,
                'verifier': {'kind': 'json_fields', 'expected': expected or {
                    'runs.0.output': self.good['runs'][0]['output']}}}

    def run_case(self, payload, extra=(), output=None, private=False, reverse=False):
        rules = [deepcopy(self.relation), *deepcopy(extra)]
        if reverse:
            rules.reverse()
        write_json(self.root / 'result.json', payload)
        write_json(self.root / 'other.json', self.good)
        artifacts = {name: {'path': name + '.json', 'sha256': sha(self.root / (name + '.json'))}
                     for name in ('result', 'other')}
        if private:
            from value_lab.scenarios import grade_scenario
            children = [{k: v for k, v in rule.items() if k in ('id', 'type', 'artifact', 'verifier')}
                        for rule in rules]
            truth = {'type': 'ScorerOnlyGroundTruth', 'case_id': 'science', 'evidence_type': 'synthetic',
                     'nonce': 'a' * 64, 'rationale': 'Manufactured combination regression', 'graders': children}
            write_json(self.root / 'private.json', truth)
            rule = {'id': 'private', 'type': 'scenario', 'verifier': {'path': 'private.json',
                    'sha256': sha(self.root / 'private.json'), 'case_id': 'science', 'evidence_type': 'synthetic'}}
            return grade_scenario(rule, {'artifacts': artifacts}, self.root, self.root)
        suite = demo_suite()
        suite['cases'] = suite['cases'][:1]
        suite['cases'][0]['graders'] = rules
        records = demo_records(suite)
        for record in records:
            record['artifacts'] = artifacts
            record['output'] = json.dumps({'status': 'ok'} if output is None else output)
        report = evaluate(suite, records, artifact_root=self.root, verifier_root=self.root)
        return report['cases'][0]['runs'][0]

    def test_original_zero_plus_status_counterexample_remains_unknown(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                run = self.run_case(self.zero, [self.json_rule()], reverse=reverse)
                self.assertTrue(all(g['passed'] for g in run['grades']))
                self.assertEqual(run['score'], 1)
                self.assertIsNone(run['task_outcome']['passed'])
                self.assertEqual(run['task_outcome']['layers']['correctness']['status'], 'UNKNOWN')

    def test_status_and_format_inside_same_artifact_do_not_qualify(self):
        for private in (False, True):
            for path, value in [('runs.0.status', 'completed'), ('format', self.zero['format'])]:
                with self.subTest(private=private, path=path):
                    result = self.run_case(self.zero, [self.file_rule({path: value})], private=private)
                    self.assertIsNone(result[0] if private else result['task_outcome']['passed'])

    def test_correct_result_in_other_artifact_cannot_anchor_wrong_result(self):
        for private in (False, True):
            with self.subTest(private=private):
                result = self.run_case(self.zero, [self.file_rule(artifact='other')], private=private)
                self.assertIsNone(result[0] if private else result['task_outcome']['passed'])

    def test_partial_numeric_reference_does_not_establish_complete_result(self):
        run = self.run_case(self.zero, [self.file_rule({'runs.0.output.values.0.0': 0})])
        self.assertIsNone(run['task_outcome']['passed'])

    def test_genuine_json_reference_still_passes_when_bound_to_same_result(self):
        rule = self.json_rule('runs.0.output', self.good['runs'][0]['output'])
        run = self.run_case(self.good, [rule], output=self.good)
        self.assertTrue(run['task_outcome']['passed'])
        forged = self.run_case(self.zero, [rule], output=self.good)
        self.assertIsNone(forged['task_outcome']['passed'])

    def test_actual_reference_passes_good_and_rejects_zero_in_both_routes(self):
        for private in (False, True):
            for payload, expected in [(self.good, True), (self.zero, False)]:
                with self.subTest(private=private, expected=expected):
                    result = self.run_case(payload, [self.file_rule()], private=private)
                    self.assertIs(result[0] if private else result['task_outcome']['passed'], expected)

    def test_missing_relation_stays_unknown_with_valid_reference(self):
        missing = deepcopy(self.good)
        missing['runs'].pop()
        for private in (False, True):
            result = self.run_case(missing, [self.file_rule()], private=private)
            self.assertIsNone(result[0] if private else result['task_outcome']['passed'])

    def test_identity_preserving_order_variation_with_matching_reference(self):
        varied = deepcopy(self.good)
        base = varied['runs'][0]['output']
        base['columns'].reverse()
        base['values'][0].reverse()
        run = self.run_case(varied, [self.file_rule({'runs.0.output': base})])
        self.assertTrue(run['task_outcome']['passed'])

    def test_reference_follows_baseline_identity_not_first_list_item(self):
        reordered = deepcopy(self.good)
        reordered['runs'][0], reordered['runs'][1] = reordered['runs'][1], reordered['runs'][0]
        run = self.run_case(reordered, [self.file_rule({'runs.1.output': self.good['runs'][0]['output']})])
        self.assertTrue(run['task_outcome']['passed'])
        # The numerically equal transformed run is not the baseline proposition.
        run = self.run_case(reordered, [self.file_rule()])
        self.assertIsNone(run['task_outcome']['passed'])

    def test_complete_fields_and_ancestor_object_are_valid_propositions(self):
        base = self.good['runs'][0]['output']
        for expected in [{'runs.0': self.good['runs'][0]},
                         {'runs.0.output.' + key: value for key, value in base.items()}]:
            run = self.run_case(self.good, [self.file_rule(expected)])
            self.assertTrue(run['task_outcome']['passed'])

    def test_each_relation_artifact_requires_its_own_reference(self):
        other = dict(self.relation, id='other-relation', artifact='other')
        run = self.run_case(self.good, [other, self.file_rule()])
        self.assertIsNone(run['task_outcome']['passed'])
        oracle = dict(self.file_rule(artifact='other'), id='other-reference')
        run = self.run_case(self.good, [other, self.file_rule(), oracle])
        self.assertTrue(run['task_outcome']['passed'])

    def test_private_known_failure_dominates_unknown_regardless_of_order(self):
        payload = deepcopy(self.zero)
        payload['runs'].pop()
        for reverse in (False, True):
            result = self.run_case(payload, [self.file_rule()], private=True, reverse=reverse)
            self.assertIs(result[0], False)

    def test_qualification_receipt_explains_missing_and_valid_reference(self):
        bad = self.run_case(self.zero, [self.json_rule()])
        detail = bad['task_outcome']['layers']['correctness']['reference_qualification']
        self.assertEqual(detail['status'], 'UNKNOWN')
        self.assertEqual(detail['targets'][0]['candidates'][0]['reason'],
                         'REFERENCE_NOT_BOUND_TO_RELATION_ARTIFACT')
        good = self.run_case(self.good, [self.file_rule()])
        detail = good['task_outcome']['layers']['correctness']['reference_qualification']
        self.assertEqual(detail['status'], 'QUALIFIED')
        self.assertEqual(detail['reference_truth'], 'NOT_INDEPENDENTLY_VALIDATED')

    def test_unordered_identity_membership_cannot_relabel_result_values(self):
        base = self.good['runs'][0]['output']
        expected = {'runs.0.output.' + key: deepcopy(value) for key, value in base.items()}
        expected['runs.0.output.columns'].reverse()
        rule = self.file_rule(expected)
        rule['verifier']['unordered_paths'] = ['runs.0.output.columns']
        run = self.run_case(self.good, [rule])
        self.assertTrue(all(g['passed'] for g in run['grades']))
        self.assertIsNone(run['task_outcome']['passed'])

    def test_report_explains_qualification_without_rendering_untrusted_html(self):
        from value_lab.report import _run_details
        run = self.run_case(self.zero, [self.json_rule()])
        qualification = run['task_outcome']['layers']['correctness']['reference_qualification']
        qualification['targets'][0]['candidates'][0]['grader_id'] = '<script>bad</script>'
        rendered = _run_details({'runs': [run]})
        self.assertIn('正确性参考资格', rendered)
        self.assertIn('REFERENCE_NOT_BOUND_TO_RELATION_ARTIFACT', rendered)
        self.assertNotIn('<script>', rendered)

    def test_missing_frozen_reference_stays_unknown_in_both_routes(self):
        (self.root / 'design.json').unlink()
        for private in (False, True):
            result = self.run_case(self.good, [self.file_rule()], private=private)
            self.assertIsNone(result[0] if private else result['task_outcome']['passed'])


if __name__ == '__main__':
    unittest.main()
