from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from value_lab.core import ValidationError, demo_suite, demo_records, suite_digest, write_json
from value_lab import component_studies as component, saturation


def suite_fixture():
    suite = demo_suite()
    suite['cases'] = suite['cases'][:2]
    suite['policy']['min_clusters'] = 2
    for case in suite['cases']:
        case['graders'] = [{'id': 'answer', 'type': 'json_equals', 'path': 'answer',
            'value': 4, 'weight': 1, 'dimension': 'outcome', 'critical': False}]
    return suite


def observation_fixture(design, rule=lambda arm: arm == '11'):
    suite = design['suite']
    template = demo_records(suite)[0]
    arms = {a['id']: a for a in design['arms']}
    rows = []
    for assignment in design['assignments']:
        row = deepcopy(assignment)
        arm = row['arm']
        record = deepcopy(template)
        record.update(case_id=row['case_id'], repetition=row['repetition'],
            arm='without' if set(arm) == {'0'} else 'with', plugin_loaded='1' in arm,
            session_id='component-' + str(row['execution_index']),
            output='{"answer":4}' if rule(arm) else '{"answer":0}',
            human_intervals=[], cost={'model_usd': .01, 'tool_usd': 0, 'human_minutes': 0})
        row.update(record=record, components=deepcopy(arms[arm]['components']))
        rows.append(row)
    return {'format': 'pvl-component-observations-1', 'design_sha256': suite_digest(design), 'runs': rows}


def series_fixture():
    studies = []
    for model in ('model-1', 'model-2', 'model-3'):
        suite = suite_fixture()
        suite['conditions']['model'] = model
        records = demo_records(suite)
        for record in records:
            record.update(output='{"answer":4}', session_id=model + '-' + record['session_id'])
        studies.append({'suite': suite, 'records': records, 'lock': {'suite_sha256': suite_digest(suite)}})
    design = saturation.plan(studies[0]['suite'], ['model-1', 'model-2', 'model-3'])
    return design, studies


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.design = component.plan(suite_fixture(), {'prompt': 'a'*64, 'tools': 'b'*64, 'context': None})
        self.obs = observation_fixture(self.design)

    def analyze(self):
        return component.analyze(self.design, self.obs, suite_digest(self.design))

    def test_four_arms_and_interaction_scaling(self):
        report = self.analyze()
        self.assertEqual(report['status'], 'COMPLETE')
        self.assertEqual(len(report['cells']), 24)
        self.assertEqual([c['success'] for c in report['contrasts']], [.5, .5, .5])
        self.assertEqual(report['causal_attribution'], 'NOT_ESTABLISHED')
        self.assertEqual(report['evidence_type'], 'synthetic')

    def test_prompt_main_effect_without_interaction(self):
        self.obs = observation_fixture(self.design, lambda arm: arm[0] == '1')
        self.assertEqual([c['success'] for c in self.analyze()['contrasts']], [1, 0, 0])

    def test_context_gets_full_eight_arm_design(self):
        self.design = component.plan(suite_fixture(), {'prompt': 'a'*64, 'tools': 'b'*64, 'context': 'c'*64})
        self.obs = observation_fixture(self.design, lambda arm: arm[2] == '1')
        report = self.analyze()
        self.assertEqual(report['planned_runs'], 48)
        self.assertEqual(len(report['contrasts']), 7)
        self.assertEqual([r['success'] for r in report['contrasts']], [0, 0, 1, 0, 0, 0, 0])

    def test_missing_arm_never_dropped_or_imputed(self):
        self.obs['runs'].pop()
        report = self.analyze()
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertEqual(len(report['cells']), 24)
        self.assertTrue(all(c['success'] is None for c in report['contrasts']))

    def test_declared_exposure_order_or_session_contamination_blocks_contrasts(self):
        for field, value in [('components', {}), ('execution_index', True), ('execution_index', 99)]:
            with self.subTest(field=field, value=value):
                self.obs = observation_fixture(self.design)
                self.obs['runs'][0][field] = value
                self.assertEqual(self.analyze()['status'], 'INCOMPLETE')
        self.obs = observation_fixture(self.design)
        self.obs['runs'][1]['record']['session_id'] = self.obs['runs'][0]['record']['session_id']
        self.assertEqual(self.analyze()['status'], 'INCOMPLETE')

    def test_duplicate_run_and_unplanned_cell_rejected(self):
        self.obs['runs'][1] = deepcopy(self.obs['runs'][0])
        with self.assertRaises(ValidationError):
            self.analyze()
        self.obs = observation_fixture(self.design)
        self.obs['runs'][0]['arm'] = '111'
        with self.assertRaises(ValidationError):
            self.analyze()

    def test_plan_or_condition_drift_cannot_create_effect(self):
        with self.assertRaises(ValidationError):
            component.analyze(self.design, self.obs, '0'*64)
        self.obs['runs'][0]['record']['conditions']['model'] = 'changed'
        self.assertEqual(self.analyze()['status'], 'INCOMPLETE')
        self.design['assignments'].pop()
        with self.assertRaises(ValidationError):
            self.analyze()

    def test_recomputed_result_failure_not_imported_success(self):
        self.obs = observation_fixture(self.design, lambda arm: False)
        for row in self.obs['runs']:
            row['record']['grades'] = {'answer': {'passed': True}}
        report = self.analyze()
        self.assertTrue(all(c['success'] == 0 for c in report['cells']))

    def test_task_timeout_is_failure_infrastructure_error_is_unknown(self):
        row = self.obs['runs'][0]['record']
        row.update(status='timeout', output='')
        self.assertEqual(self.analyze()['status'], 'COMPLETE')
        row.update(status='error', failure_kind='infrastructure')
        self.assertEqual(self.analyze()['status'], 'INCOMPLETE')

    def test_unknown_cost_is_retained_and_blocks_complete_comparison(self):
        self.obs['runs'][0]['record'].pop('cost')
        report = self.analyze()
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertTrue(any(c['cost_usd'] is None for c in report['cells']))

    def test_human_time_overlap_between_two_nonbaseline_arms(self):
        selected = [r['record'] for r in self.obs['runs'] if r['arm'] != '00'][:2]
        for r in selected:
            r['human_intervals'] = [{'actor': 'same-person', 'start': '2026-01-01T00:00:00Z',
                                     'end': '2026-01-01T00:01:00Z'}]
            r['cost']['human_minutes'] = 1
        self.assertEqual(self.analyze()['status'], 'INCOMPLETE')

    def test_empty_observations_and_all_baseline_missing_keep_denominator(self):
        self.obs['runs'] = []
        report = self.analyze()
        self.assertEqual(len(report['cells']), 24)
        self.assertEqual(report['observed_runs'], 0)
        self.assertEqual(report['status'], 'INCOMPLETE')

    def test_assignment_is_reproducible_complete_and_each_cell_once(self):
        rebuilt = component.plan(self.design['suite'], self.design['components'], self.design['seed'])
        self.assertEqual(self.design, rebuilt)
        self.assertEqual(len({(r['case_id'], r['repetition'], r['arm']) for r in rebuilt['assignments']}), 24)


class SaturationTests(unittest.TestCase):
    def setUp(self):
        self.design, self.studies = series_fixture()

    def analyze(self):
        return saturation.analyze(self.design, self.studies, suite_digest(self.design))

    def test_three_consecutive_versions_review_not_retirement(self):
        result = self.analyze()
        self.assertEqual(result['saturation_index'], 1)
        self.assertEqual(result['cases'][0]['status'], 'SATURATION_REVIEW')
        self.assertFalse(result['automatic_case_removal'])
        self.assertEqual(result['evidence_type'], 'synthetic')
        self.assertEqual(len(result['cases'][0]['versions'][0]['full_costs_usd']), 3)

    def test_missing_middle_or_latest_version_breaks_streak(self):
        for missing in (1, 2):
            _, studies = series_fixture()
            studies.pop(missing)
            self.studies = studies
            report = self.analyze()
            self.assertEqual(report['saturation_index'], 0)
            self.assertIsNone(report['cases'][0]['versions'][missing]['baseline_ceiling'])

    def test_missing_repeat_error_wrong_answer_break_ceiling(self):
        for mode in ('missing', 'error', 'wrong'):
            self.design, self.studies = series_fixture()
            records = self.studies[-1]['records']
            row = next(r for r in records if r['arm'] == 'without')
            if mode == 'missing':
                records.remove(row)
            elif mode == 'error':
                row.update(status='error', failure_kind='task')
            else:
                row['output'] = '{"answer":0}'
            self.assertEqual(self.analyze()['cases'][0]['status'], 'NOT_ESTABLISHED')

    def test_duplicate_versions_reused_sessions_changed_rubric_rejected(self):
        self.studies[1] = deepcopy(self.studies[0])
        with self.assertRaises(ValidationError):
            self.analyze()
        self.design, self.studies = series_fixture()
        self.studies[1]['records'][0]['session_id'] = self.studies[0]['records'][0]['session_id']
        with self.assertRaises(ValidationError):
            self.analyze()
        self.design, self.studies = series_fixture()
        self.studies[1]['suite']['cases'][0]['graders'][0]['value'] = 5
        with self.assertRaises(ValidationError):
            self.analyze()

    def test_missing_lock_remains_unknown(self):
        self.studies[-1]['lock'] = None
        result = self.analyze()
        self.assertIsNone(result['cases'][0]['versions'][-1]['baseline_ceiling'])

    def test_text_only_score_one_does_not_establish_correctness(self):
        suite = suite_fixture()
        suite['cases'][0]['graders'][0] = {'id': 'text', 'type': 'contains', 'value': 'answer',
            'weight': 1, 'critical': False, 'dimension': 'outcome'}
        for study in self.studies:
            study['suite']['cases'] = deepcopy(suite['cases'])
            study['lock'] = {'suite_sha256': suite_digest(study['suite'])}
            for r in study['records']:
                r['suite_sha256'] = study['lock']['suite_sha256']
        self.design = saturation.plan(self.studies[0]['suite'], self.design['models'])
        self.assertEqual(self.analyze()['cases'][0]['status'], 'NOT_ESTABLISHED')

    def test_cli_plan_analysis_and_no_overwrite(self):
        import sys
        from contextlib import redirect_stdout
        import io
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
        from component_eval import main
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(root / 'design.json', self.design)
            write_json(root / 'studies.json', self.studies)
            args = ['saturation', str(root / 'design.json'), '--expected-id', suite_digest(self.design),
                    '--observations', str(root / 'studies.json'), '--output', str(root / 'report')]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
            self.assertIn('SATURATION_REVIEW', (root / 'report/README.md').read_text(encoding='utf-8'))
            self.assertEqual(main(args), 2)


if __name__ == '__main__':
    unittest.main()
