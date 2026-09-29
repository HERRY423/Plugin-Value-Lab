import unittest
from value_lab.component_localization import summarize
from value_lab.core import ValidationError


class ComponentLocalizationTests(unittest.TestCase):
    def setUp(self):
        self.design = {'components': [{'id': 'method'}, {'id': 'format'}],
                       'cases': [{'id': 'target', 'role': 'target'}, {'id': 'control', 'role': 'control'}]}
        self.runs = [{'arm': a, 'case_id': c, 'pipeline_completed': True, 'environment_check': 'MATCH_BEFORE_AND_AFTER',
            'passed': c == 'control' or a[0] == '1', 'outputs': [{'path': 'result.json', 'passed': c == 'control' or a[0] == '1'}]}
            for a in ('00', '01', '10', '11') for c in ('target', 'control')]

    def test_conditional_actual_replacements(self):
        r = summarize(self.design, self.runs)
        self.assertEqual(r['status'], 'COMPLETE')
        self.assertEqual([c['component'] for c in r['contrasts'] if c['failure_disappeared']], ['method', 'method'])

    def test_failed_missing_or_drifted_control_is_not_resolution(self):
        for field, value in (('passed', False), ('passed', None), ('pipeline_completed', False), ('environment_check', 'DRIFT')):
            rows = [dict(r) for r in self.runs]
            for r in rows:
                if r['case_id'] == 'control':
                    r[field] = value
            self.assertFalse(any(c['failure_disappeared'] for c in summarize(self.design, rows)['contrasts']))

    def test_missing_targets_and_duplicates(self):
        self.assertEqual(summarize(self.design, self.runs[:-1])['status'], 'INCOMPLETE')
        with self.assertRaises(ValidationError):
            summarize(self.design, self.runs + [self.runs[0]])

    def test_failed_execution_does_not_count_as_fixed(self):
        for r in self.runs:
            if r['arm'][0] == '1':
                r['pipeline_completed'] = False
        self.assertFalse(any(c['failure_disappeared'] for c in summarize(self.design, self.runs)['contrasts']))
