"""Scope enforcement tests; fixtures are never external value evidence."""
import copy
import tempfile
import unittest
from value_lab.core import demo_suite, demo_records, evaluate, suite_digest, ValidationError, validate_suite
from value_lab.claim_scope import cite, verify_report
from value_lab.report import write_reports


class ClaimScopeTests(unittest.TestCase):
    def setUp(self):
        self.suite = demo_suite()
        self.suite['claim_context'] = {'model_version': 'fixture-1', 'host_version': 'fixture-2', 'excluded_uses': ['patient_decisions']}
        for case in self.suite['cases']:
            case['data_scale'] = {'unit': 'prompts', 'count': 1}
        self.report = evaluate(self.suite, demo_records(self.suite), {'suite_sha256': suite_digest(self.suite)})
        self.digest = suite_digest(self.report)

    def request(self, identifier='/cases/0/delta'):
        claim = next(c for c in self.report['scoped_conclusions']['claims'] if c['id'] == identifier)
        return {'claim_id': identifier, **{k: copy.deepcopy(claim['scope'][k]) for k in ('evidence_unit', 'conditions', 'data_scale')},
                'intended_use': 'describe_observed_result'}

    def test_case_family_study_units_remain_distinct(self):
        for pointer, kind in [('/cases/0/delta', 'case'), ('/summary/quality_delta', 'study'),
                              ('/value_metrics/families/deltas/delivery', 'family')]:
            result = cite(self.report, self.request(pointer), self.digest)
            self.assertEqual(result['claim']['scope']['evidence_unit']['kind'], kind)
            self.assertIn('patient_decisions', result['claim']['scope']['explicitly_unsupported'])

    def test_widening_any_dimension_is_an_error(self):
        changes = [('evidence_unit', {'kind':'study', 'case_ids':['structured-delivery'], 'family':None}),
                   ('conditions', {**self.request()['conditions'], 'model_version':'new'}),
                   ('conditions', {**self.request()['conditions'], 'host_version':'new'}),
                   ('data_scale', {'structured-delivery':{'unit':'prompts','count':2}}),
                   ('intended_use', 'causal_benefit')]
        for key, value in changes:
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValidationError, 'OUT_OF_SCOPE'):
                request = self.request()
                request[key] = value
                cite(self.report, request, self.digest)

    def test_unknown_versions_and_scales_do_not_become_zero_or_default(self):
        suite = demo_suite()
        report = evaluate(suite, demo_records(suite), {'suite_sha256': suite_digest(suite)})
        bound = report['scoped_conclusions']
        self.assertIsNone(bound['context']['conditions']['host_version'])
        self.assertIsNone(bound['context']['cases']['structured-delivery']['data_scale'])
        self.assertIn('data_scale:structured-delivery', bound['missing_dimensions'])

    def test_changed_result_or_removed_claim_cannot_render(self):
        for mutation in ('result', 'coverage'):
            altered = copy.deepcopy(self.report)
            if mutation == 'result':
                altered['summary']['quality_delta'] = 999
            else:
                altered['scoped_conclusions']['claims'].pop()
            with tempfile.TemporaryDirectory() as root, self.assertRaises(ValidationError):
                write_reports(altered, root)

    def test_recomputed_forgery_still_fails_external_commitment(self):
        altered = copy.deepcopy(self.report)
        altered['scoped_conclusions']['scope_authenticity'] = 'invented'
        with self.assertRaisesRegex(ValidationError, 'commitment changed'):
            cite(altered, self.request(), self.digest)

    def test_pin_is_mandatory_and_unknown_claim_is_rejected(self):
        for pin in (None, '', 'wrong'):
            with self.assertRaises(ValidationError):
                cite(self.report, self.request(), pin)
        request = self.request()
        request['claim_id'] = '/made-up'
        with self.assertRaisesRegex(ValidationError, 'Unknown claim'):
            cite(self.report, request, self.digest)

    def test_invalid_declarations_fail_before_freeze(self):
        for count in (-1, True, 1.5):
            suite = copy.deepcopy(self.suite)
            suite['cases'][0]['data_scale']['count'] = count
            with self.assertRaises(ValidationError):
                validate_suite(suite)

    def test_cost_and_uncertainty_claims_are_bound_too(self):
        identifiers = {x['id'] for x in self.report['scoped_conclusions']['claims']}
        self.assertIn('/cost_analysis/saving_claim_eligible', identifiers)
        self.assertTrue(any(x.startswith('/uncertainty/') for x in identifiers))
        verify_report(self.report, self.digest)

    def test_malformed_binding_is_validation_error(self):
        altered = copy.deepcopy(self.report)
        altered['scoped_conclusions']['context'] = None
        with self.assertRaises(ValidationError):
            verify_report(altered)


if __name__ == '__main__':
    unittest.main()
