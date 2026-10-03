"""Prospective power, uncertainty and real public entry points; synthetic only."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from value_lab.core import ValidationError, demo_suite, demo_records, evaluate, suite_digest, validate_suite, freeze
from value_lab.declarative import inspect_suite
from value_lab.sample_size import plan_sample_size, suite_plan, confidence_intervals, _power
from value_lab.workflow import plan_plugin_use
from value_lab.report import write_reports

SCIPY = importlib.util.find_spec('scipy') is not None


def spec(method='normal_approximation'):
    return {'version': 2, 'minimum_detectable_delta': .1, 'alpha': .05, 'power': .8,
            'between_family_sd': .15, 'between_task_sd': .1, 'within_task_sd': .2,
            'tasks_per_family': [1, 2], 'repetitions_per_case': [1, 3, 5], 'max_families': 10000,
            'variance_source': 'Manufactured design assumption, not an observed pilot',
            'sampling_basis': 'independent_representative_families', 'method': method, 'comparisons': 1}


class SampleSizeTests(unittest.TestCase):
    def test_known_normal_answer_and_integer_minimum(self):
        p = spec()
        p.update(between_family_sd=.2, between_task_sd=0, within_task_sd=0, sd_multipliers=[1])
        r = plan_sample_size(p)
        for row in r['designs']:
            self.assertEqual(row['required_families'], 32)
            self.assertGreaterEqual(row['conditional_power'], .8)
            self.assertLess(row['power_one_fewer_family'], .8)

    @unittest.skipUnless(SCIPY, 'optional planning dependency')
    def test_noncentral_t_matches_independent_statsmodels_reference(self):
        # Frozen values from statsmodels TTestPower(0.5, nobs=34, alpha=.05).
        self.assertAlmostEqual(_power(34, .1, .2, .05, 'paired_t'), .8077775012792748, places=10)
        p = spec('paired_t')
        p.update(between_family_sd=.2, between_task_sd=0, within_task_sd=0, sd_multipliers=[1])
        self.assertEqual(plan_sample_size(p)['recommended_design']['required_families'], 34)
        self.assertEqual(_power(5001, .1, .2, .05, 'paired_t'), 1.)

    def test_repeats_reduce_only_within_task_variance(self):
        r = plan_sample_size(spec())
        rows = [v for v in r['designs'] if v['sd_multiplier'] == 1 and v['tasks_per_family'] == 1]
        self.assertGreater(rows[0]['required_families'], rows[-1]['required_families'])
        self.assertGreater(rows[-1]['family_mean_sd'], .15)
        self.assertAlmostEqual(rows[1]['family_mean_sd'] ** 2, .15**2 + .1**2 + .2**2/3)
        for row in rows:
            self.assertEqual(row['generation_runs'], 2*row['required_tasks']*row['repetitions_per_case_per_arm'])

    def test_more_tasks_do_not_erase_family_heterogeneity(self):
        p = spec()
        p.update(between_task_sd=0, within_task_sd=0)
        rows = [r for r in plan_sample_size(p)['designs'] if r['sd_multiplier'] == 1]
        self.assertEqual(len({r['required_families'] for r in rows}), 1)

    def test_alpha_power_effect_and_sensitivity_move_correctly(self):
        p = spec()
        n = plan_sample_size(p)['designs'][0]['required_families']
        for changes in ({'power': .9}, {'minimum_detectable_delta': .05}, {'comparisons': 5}):
            self.assertGreater(plan_sample_size({**p, **changes})['designs'][0]['required_families'], n)
        r = plan_sample_size(p)['designs']
        self.assertGreater(r[len(r)//2]['required_families'], r[0]['required_families'])

    def test_low_cap_preserves_unattainability(self):
        r = plan_sample_size({**spec(), 'max_families': 2})
        self.assertEqual(r['status'], 'NO_FEASIBLE_DESIGN_IN_GRID')
        self.assertIsNone(r['recommended_design'])
        self.assertTrue(all(row['required_families'] is None for row in r['designs']))

    def test_known_effort_objective_is_explicit(self):
        p = spec()
        p['cost_weights'] = {'unit': 'assumed minutes', 'family_setup': 100, 'task_setup': 10, 'generation': 1}
        r = plan_sample_size(p)
        best = r['recommended_design']
        self.assertEqual(best['assumed_effort'], min(v['assumed_effort'] for v in r['designs'] if v['sd_multiplier'] == 1))
        self.assertFalse(r['executed'])

    def test_fixed_benchmark_not_representative_population(self):
        p = {**spec(), 'sampling_basis': 'fixed_benchmark'}
        self.assertFalse(plan_sample_size(p)['population_inference_supported_by_declaration'])

    def test_invalid_and_missing_assumptions(self):
        for key, values in {'minimum_detectable_delta': [0, True, float('nan')],
                            'between_family_sd': [-1, float('inf')], 'tasks_per_family': [[0], [1, 1], [True]],
                            'repetitions_per_case': [[51], []], 'comparisons': [True, 0],
                            'sd_multipliers': [[2], [1, 1], [True]], 'variance_source': [''],
                            'method': ['seeded_t'], 'sampling_basis': ['all independent because hashes differ']}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                    plan_sample_size({**spec(), key: value})
        for changes in ({'between_family_sd': 0, 'between_task_sd': 0, 'within_task_sd': 0},
                        {'between_family_sd': 1}, {'random_extra': True}):
            with self.assertRaises(ValidationError):
                plan_sample_size({**spec(), **changes})
        p = spec()
        del p['variance_source']
        with self.assertRaises(ValidationError):
            plan_sample_size(p)

    def test_no_silent_t_to_normal_fallback(self):
        with patch('value_lab.sample_size._scipy_stats', side_effect=ValidationError('dependency required')):
            with self.assertRaisesRegex(ValidationError, 'dependency'):
                plan_sample_size(spec('paired_t'))
            self.assertEqual(plan_sample_size(spec())['status'], 'CONDITIONAL_DESIGN')

    def test_mcp_planning_route_preserves_proposed_only(self):
        result = plan_plugin_use({'schema_version': 1, 'intent': 'evaluate', 'task': 'quality gain', 'sample_size_plan': spec()})
        self.assertEqual(result['route'], 'PLAN_SAMPLE_SIZE')
        self.assertFalse(result['handoff']['execute'])
        self.assertEqual(len(result['sample_size']['designs']), 12)
        with self.assertRaises(ValidationError):
            plan_plugin_use({'schema_version': 1, 'intent': 'use', 'task': 'quality gain', 'sample_size_plan': spec()})

    def test_suite_check_exposes_design_before_data(self):
        s = demo_suite()
        s['policy']['power_plan'] = spec()
        result = inspect_suite(s)
        self.assertFalse(result['executed'])
        self.assertEqual(result['power_plan']['planned_tasks'], 3)
        self.assertFalse(result['power_plan']['aligned_with_primary_quality_gate'])
        old_digest = suite_digest(s)
        s['policy']['power_plan']['minimum_detectable_delta'] = .2
        self.assertNotEqual(suite_digest(s), old_digest)

    def test_schema_and_runtime_agree_on_example_and_invalid_inputs(self):
        import jsonschema
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root/'schemas/sample-size-plan.schema.json').read_text(encoding='utf-8'))
        example = json.loads((root/'examples/sample-size-plan.json').read_text(encoding='utf-8'))['sample_size_plan']
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(example, schema)
        plan_sample_size(example)
        for change in ({'version': True}, {'power': 1}, {'repetitions_per_case': [0]}, {'comparisons': False}):
            invalid = {**example, **change}
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(invalid, schema)
            with self.assertRaises(ValidationError):
                plan_sample_size(invalid)

    def test_documented_cli_writes_human_design_and_machine_plan(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'plan'
            run = subprocess.run([sys.executable, str(root/'scripts/value_lab.py'), 'plan-use',
                                  str(root/'examples/sample-size-plan.json'), '--output', str(output)],
                                 capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr.decode(errors='replace'))
            result = json.loads((output/'plan.json').read_text(encoding='utf-8'))
            self.assertEqual(result['route'], 'PLAN_SAMPLE_SIZE')
            text = (output/'PLAN.md').read_text(encoding='utf-8')
            self.assertIn('所需任务总数', text)
            self.assertIn('网格内推荐', text)


class IntervalTests(unittest.TestCase):
    def data(self, method='normal_approximation'):
        s = demo_suite()
        s['policy'].update(power_plan=spec(method), quality_weighting='family')
        # Minimal report for transparent numerical oracle tests.
        r = {'evidence_type': 'local', 'blockers': [], 'summary': {'comparison_eligible': True},
             'provenance': {'local_lock': {'suite_sha256': suite_digest(s)}},
             'cases': [{'id': str(i), 'cluster': str(i), 'delta': d} for i, d in enumerate([.1, .2, .3, .4])]}
        return s, r

    @unittest.skipUnless(SCIPY, 'optional planning dependency')
    def test_family_t_interval_reference_df_not_repeats(self):
        s, r = self.data('paired_t')
        result = confidence_intervals(s, r)
        ci = result['student_t_interval']
        self.assertEqual(ci['df'], 3)
        self.assertAlmostEqual(ci['low'], .04457397432391, places=10)
        self.assertAlmostEqual(ci['high'], .45542602567609, places=10)
        s['runs_per_case'] = 50
        r['provenance']['local_lock']['suite_sha256'] = suite_digest(s)
        self.assertEqual(confidence_intervals(s, r)['student_t_interval'], ci)

    def test_hoeffding_formula_and_zero_variance_not_zero_width(self):
        s, r = self.data()
        r['cases'] = [{'id': str(i), 'cluster': str(i), 'delta': .2} for i in range(100)]
        result = confidence_intervals(s, r)
        half = math.sqrt(2*math.log(40)/100)
        self.assertAlmostEqual(result['bounded_interval']['low'], .2-half)
        self.assertGreater(result['bounded_interval']['high'], result['bounded_interval']['low'])

    @unittest.skipUnless(SCIPY, 'optional planning dependency')
    def test_zero_variance_and_unbalanced_tasks_refuse_t(self):
        s, r = self.data('paired_t')
        r['cases'].append({'id': 'extra', 'cluster': '0', 'delta': .1})
        self.assertEqual(confidence_intervals(s, r)['student_t_interval']['status'], 'UNAVAILABLE')
        r['cases'].pop()
        for row in r['cases']:
            row['delta'] = .1
        self.assertEqual(confidence_intervals(s, r)['student_t_interval']['status'], 'UNAVAILABLE')

    def test_missing_confounded_unfrozen_or_nonrandom_never_produces_ci(self):
        for change in ('missing', 'blocked', 'lock', 'weighting', 'fixed', 'one-family'):
            s, r = self.data()
            if change == 'missing': r['cases'][0]['delta'] = None
            if change == 'blocked': r['blockers'] = ['conditions changed']
            if change == 'lock': r['provenance']['local_lock'] = None
            if change == 'weighting': s['policy']['quality_weighting'] = 'case'
            if change == 'fixed': s['policy']['power_plan']['sampling_basis'] = 'fixed_benchmark'
            if change == 'one-family':
                for c in r['cases']: c['cluster'] = 'same'
            self.assertEqual(confidence_intervals(s, r)['status'], 'UNAVAILABLE', change)

    def test_real_evaluator_freeze_and_report_keep_simulation_label(self):
        s = demo_suite()
        s['policy'].update(power_plan=spec(), quality_weighting='family')
        records = demo_records(s)
        with tempfile.TemporaryDirectory() as tmp:
            lock = freeze(s, Path(tmp)/'lock.json')
            result = evaluate(s, records, lock)
            self.assertEqual(result['verdict'], 'SIMULATION_ONLY')
            ci = result['value_metrics']['confidence_intervals']
            self.assertEqual(ci['status'], 'SIMULATION_ONLY')
            self.assertFalse(ci['changes_adoption_verdict'])
            write_reports(result, Path(tmp)/'report')
            for file in ('report.html', 'report.md'):
                content = (Path(tmp)/'report'/file).read_text(encoding='utf-8')
                self.assertIn('任务数与重复次数方案', content)
                self.assertIn('Hoeffding', content)


if __name__ == '__main__':
    unittest.main()
