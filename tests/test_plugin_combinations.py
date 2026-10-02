"""Adversarial combination checks; all observations are manufactured fixtures."""
from copy import deepcopy
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

from value_lab.core import ValidationError, suite_digest, write_json
from value_lab import plugin_combinations as combinations
from value_lab.workflow import plan_plugin_use, write_plan

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('combination_example', ROOT / 'examples/plugin-combinations/demo.py')
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class CombinationTests(unittest.TestCase):
    def setUp(self):
        self.design = combinations.plan(example.specification())
        self.obs = example.observations(self.design)

    def result(self):
        return combinations.analyze(self.design, self.obs, suite_digest(self.design))

    def context(self):
        return {'schema_version': 1, 'intent': 'choose', 'plugin_combination': {'action': 'analyze',
            'design': self.design, 'expected_id': suite_digest(self.design), 'observations': self.obs}}

    def test_exact_interaction_not_half_scaling_and_ties(self):
        report = self.result()
        self.assertEqual(report['status'], 'COMPLETE')
        for metric in ('quality', 'success'):
            self.assertEqual(report['contrasts'][0]['interaction'][metric]['mean'], 1)
        self.assertEqual(report['recommendation']['candidate_arms'], ['AB', 'BA'])
        self.assertEqual(report['relationship'], 'COMBINATION_REQUIRED_WITHIN_TESTED_SET')
        self.assertEqual(report['recommendation']['status'], 'SIMULATION_ONLY')
        self.assertEqual(report['causal_attribution'], 'NOT_ESTABLISHED')
        self.assertEqual(report['automatic_actions'], [])

    def test_substitutes_negative_interaction_does_not_mean_interference(self):
        self.obs = example.observations(self.design, 'substitutes')
        report = self.result()
        self.assertEqual(report['contrasts'][0]['interaction']['quality']['mean'], -1)
        self.assertEqual(report['contrasts'][0]['observed_quality_pattern'], 'JOINT_WITHIN_MARGIN_OF_BEST_SINGLE')
        self.assertEqual(report['relationship'], 'SINGLE_PLUGIN_ALTERNATIVES')
        self.assertEqual(report['recommendation']['candidate_arms'], ['A', 'B'])

    def test_joint_underperformance_and_order_difference(self):
        self.obs = example.observations(self.design, 'interference')
        self.assertEqual(self.result()['contrasts'][0]['observed_quality_pattern'], 'JOINT_BELOW_BEST_SINGLE')
        self.obs = example.observations(self.design, 'order')
        report = self.result()
        self.assertEqual(report['order_effect_AB_minus_BA']['quality']['mean'], 1)
        self.assertEqual(report['recommendation']['candidate_arms'], ['AB'])

    def test_zero_plugins_is_valid_minimum(self):
        self.obs = example.observations(self.design, 'baseline')
        report = self.result()
        self.assertEqual(report['recommendation']['candidate_arms'], ['BASELINE'])
        self.assertEqual(report['recommendation']['retain_capabilities']['BASELINE']['plugins'], [])

    def test_four_arm_plan_does_not_infer_reverse_order(self):
        self.design = combinations.plan(example.specification(False))
        self.obs = example.observations(self.design)
        self.assertEqual(self.result()['planned_runs'], 24)
        self.assertIsNone(self.result()['order_effect_AB_minus_BA'])

    def test_freeze_determinism_and_no_mutation(self):
        before = deepcopy((self.design, self.obs))
        self.result()
        self.assertEqual(before, (self.design, self.obs))
        self.assertEqual(self.design, combinations.plan(self.design['spec']))
        self.design['assignments'].pop()
        with self.assertRaises(ValidationError):
            self.result()

    def test_expected_id_and_observation_id_required(self):
        with self.assertRaises(ValidationError):
            combinations.analyze(self.design, self.obs, '0' * 64)
        self.obs['design_sha256'] = '0' * 64
        with self.assertRaises(ValidationError):
            self.result()

    def test_missing_arm_retains_cells_and_unknown_minimum(self):
        self.obs['runs'] = [r for r in self.obs['runs'] if r['arm'] != 'A']
        report = self.result()
        self.assertEqual(len(report['cells']), 30)
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertIsNone(report['contrasts'][0]['interaction']['quality']['mean'])
        self.assertFalse(report['recommendation']['minimum_within_tested_set'])
        self.assertIn('A', report['recommendation']['unresolved_smaller_or_equal_arms'])

    def test_empty_observations_and_duplicate_attempts(self):
        self.obs['runs'] = []
        report = self.result()
        self.assertEqual(report['observed_runs'], 0)
        self.assertEqual(len(report['cells']), 30)
        self.assertEqual(report['recommendation']['candidate_arms'], [])
        self.obs = example.observations(self.design)
        self.obs['runs'][1] = deepcopy(self.obs['runs'][0])
        with self.assertRaises(ValidationError):
            self.result()

    def test_exposure_input_background_order_session_drift(self):
        for mutation in ('plugins', 'inputs', 'background_conditions', 'order', 'session', 'execution_index'):
            self.obs = example.observations(self.design)
            row = next(r for r in self.obs['runs'] if r['arm'] == 'AB')
            if mutation == 'session':
                row['record']['session_id'] = []
            elif mutation == 'execution_index':
                row[mutation] = True
            else:
                row['exposure'][mutation] = []
            with self.subTest(mutation=mutation):
                report = self.result()
                self.assertEqual(report['status'], 'INCOMPLETE')
                self.assertIsNone(report['contrasts'][0]['interaction']['quality']['mean'])
                self.assertEqual(report['recommendation']['candidate_arms'], [])

    def test_cross_nonbaseline_session_and_timer_overlap(self):
        selected = [r['record'] for r in self.obs['runs'] if r['arm'] in ('A', 'B')][:2]
        selected[1]['session_id'] = selected[0]['session_id']
        self.assertEqual(self.result()['status'], 'INCOMPLETE')
        self.obs = example.observations(self.design)
        for row in [r for r in self.obs['runs'] if r['arm'] in ('A', 'B')][:2]:
            row['record']['human_intervals'] = [{'actor': 'fixture', 'start': '2026-01-01T00:00:00Z', 'end': '2026-01-01T00:01:00Z'}]
            row['record']['cost']['human_minutes'] = 1
        self.assertEqual(self.result()['status'], 'INCOMPLETE')

    def test_output_regraded_not_imported_success(self):
        for row in self.obs['runs']:
            row['record']['output'] = '{"source_and_identifier_checked":false}'
            row['record']['grades'] = {'checked': {'passed': True}}
        self.assertEqual(self.result()['recommendation']['candidate_arms'], [])

    def test_task_failure_zero_infrastructure_unknown(self):
        row = self.obs['runs'][0]['record']
        row.update(status='timeout', output='')
        self.assertEqual(self.result()['status'], 'COMPLETE')
        row.update(status='error', failure_kind='infrastructure')
        self.assertEqual(self.result()['status'], 'INCOMPLETE')

    def test_unknown_nonfinite_cost_never_zero(self):
        self.obs['runs'][0]['additional_cost_usd']['setup_usd'] = None
        report = self.result()
        self.assertFalse(report['recommendation']['minimum_within_tested_set'])
        self.assertTrue(any(c['cost_usd'] is None for c in report['cells']))
        for value in (float('nan'), float('inf'), True, -1):
            self.obs['runs'][0]['additional_cost_usd']['setup_usd'] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.result()

    def test_additional_cost_once_and_cap_blocks_pair(self):
        for row in self.obs['runs']:
            if row['arm'] in ('AB', 'BA'):
                row['additional_cost_usd']['judge_usd'] = .09
        report = self.result()
        pair = next(a for a in report['arms'] if a['arm'] == 'AB')
        self.assertAlmostEqual(pair['metrics']['cost_usd']['mean'], .12)
        self.assertEqual(pair['status'], 'FAILED')
        self.assertEqual(report['recommendation']['candidate_arms'], [])
        self.assertEqual(report['observed_runs'], 30)

    def test_cost_required_suite_keeps_itemized_coverage(self):
        request = example.specification()
        request['suite']['policy']['require_cost_categories'] = True
        self.design = combinations.plan(request)
        self.obs = example.observations(self.design)
        self.assertEqual(self.result()['status'], 'COMPLETE')

    def test_unknown_duration_prevents_selection(self):
        for row in self.obs['runs']:
            row['record'].pop('duration_seconds')
        report = self.result()
        self.assertEqual(report['recommendation']['candidate_arms'], [])
        self.assertEqual(report['contrasts'][0]['interaction']['quality']['mean'], 1)
        self.assertEqual(report['status'], 'INCOMPLETE')

    def test_per_case_floor_and_original_regression_guard(self):
        self.obs = example.observations(self.design, 'baseline')
        target = next(r for r in self.obs['runs'] if r['arm'] == 'AB')
        target['record']['output'] = '{"source_and_identifier_checked":false}'
        pair = next(a for a in self.result()['arms'] if a['arm'] == 'AB')
        self.assertEqual(pair['status'], 'FAILED')
        self.assertIn('Original per-case regression guard failed', pair['reasons'])

    def test_invalid_duration_is_unknown_not_nonfinite_report(self):
        for value in (True, -1, float('nan'), float('inf')):
            self.obs = example.observations(self.design)
            self.obs['runs'][0]['record']['duration_seconds'] = value
            # JSON-bound observations reject NaN/inf; finite malformed values
            # survive only as unknown metrics, never a feasible candidate.
            if isinstance(value, float):
                with self.assertRaises(ValueError):
                    self.result()
            else:
                report = self.result()
                self.assertEqual(report['status'], 'INCOMPLETE')
                json.dumps(report, allow_nan=False)

    def test_critical_process_failure_not_hidden_by_quality(self):
        request = example.specification()
        for case in request['suite']['cases']:
            case['graders'].append({'id': 'critical', 'type': 'contains', 'value': 'MUST', 'dimension': 'process', 'weight': 1, 'critical': True})
        self.design = combinations.plan(request)
        self.obs = example.observations(self.design)
        self.assertEqual(self.result()['recommendation']['candidate_arms'], [])

    def test_diagnostic_bytes_checked_without_promoting_semantics(self):
        from value_lab.artifacts import sha
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'trace.txt'
            path.write_text('manufactured duplicate query event', encoding='utf-8')
            self.obs['runs'][0]['diagnostics'] = {'assessed': ['duplicate_work'], 'events': [
                {'kind': 'duplicate_work', 'detail': 'manufactured event', 'evidence': {'path': 'trace.txt', 'sha256': sha(path)}}]}
            report = combinations.analyze(self.design, self.obs, suite_digest(self.design), artifact_root=temp)
            self.assertEqual(report['diagnostics'][0]['events'][0]['evidence_status'], 'BYTES_VERIFIED')
            path.write_text('changed', encoding='utf-8')
            report = combinations.analyze(self.design, self.obs, suite_digest(self.design), artifact_root=temp)
            self.assertEqual(report['diagnostics'][0]['events'][0]['evidence_status'], 'MISSING_OR_CHANGED')
            self.assertEqual(report['causal_attribution'], 'NOT_ESTABLISHED')

    def test_unassessed_diagnostics_and_path_escape(self):
        self.assertEqual(self.result()['diagnostics'][0]['assessed'], [])
        self.obs['runs'][0]['diagnostics'] = {'assessed': ['duplicate_work'], 'events': [
            {'kind': 'duplicate_work', 'detail': 'bad path', 'evidence': {'path': '../private', 'sha256': 'a'*64}}]}
        with self.assertRaises(ValidationError):
            self.result()

    def test_invalid_prospective_requests(self):
        for mutate in (lambda s: s.update(seed=True), lambda s: s.update(compare_orders=1),
                       lambda s: s['plugins'].append(deepcopy(s['plugins'][0])),
                       lambda s: s['policy'].update(quality_floor=.1),
                       lambda s: s['policy'].update(interaction_margin=float('nan'))):
            request = example.specification()
            mutate(request)
            with self.assertRaises(ValidationError):
                combinations.plan(request)

    def test_existing_planner_markdown_and_cli(self):
        context = {'schema_version': 1, 'intent': 'choose', 'plugin_combination': {'action': 'plan', 'spec': example.specification()}}
        self.assertEqual(plan_plugin_use(context)['combination']['design'], self.design)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_plan(plan_plugin_use(self.context()), root / 'render')
            self.assertIn('SIMULATION_ONLY', (root / 'render/PLAN.md').read_text(encoding='utf-8'))
            write_json(root / 'context.json', self.context())
            from value_lab.cli import main
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(['plan-use', str(root / 'context.json'), '--output', str(root / 'cli')]), 0)
            saved = json.loads((root / 'cli/plan.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['combination']['planned_runs'], 30)

    def test_modes_and_management_authority_not_conflated(self):
        for field, value in (('intent', 'manage'), ('task_selection', {}), ('selected_plugin', {'id': 'x'})):
            context = self.context()
            context[field] = value
            with self.assertRaises(ValidationError):
                plan_plugin_use(context)

    def test_evaluation_read_only(self):
        from value_lab.artifacts import _EXECUTION_ALLOWED
        real = combinations.evaluate
        def guarded(*args, **kwargs):
            self.assertFalse(_EXECUTION_ALLOWED.get())
            return real(*args, **kwargs)
        with patch.object(combinations, 'evaluate', side_effect=guarded):
            self.result()

    @unittest.skipUnless(importlib.util.find_spec('jsonschema'), 'Developer schema dependency not installed')
    def test_published_schema_matches_both_requests_and_rejects_extra_fields(self):
        import jsonschema
        schema = json.loads((ROOT / 'schemas/plugin-combination.schema.json').read_text(encoding='utf-8'))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate({'action': 'plan', 'spec': self.design['spec']}, schema)
        request = self.context()['plugin_combination']
        jsonschema.validate(request, schema)
        request['observations']['runs'][0]['additional_cost_usd']['unknown_field'] = 0
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(request, schema)


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'Optional MCP SDK not installed')
class CombinationMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_pair_planning_analysis_and_legacy_evaluation(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        design = combinations.plan(example.specification(False))
        params = StdioServerParameters(command=sys.executable, args=[str(ROOT / 'scripts/value_lab.py'), 'serve'])
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                self.assertEqual(len((await session.list_tools()).tools), 6)
                context = {'schema_version': 1, 'intent': 'choose', 'plugin_combination': {'action': 'plan', 'spec': design['spec']}}
                result = await session.call_tool('plan_plugin_use', {'context': context})
                self.assertFalse(result.isError)
                self.assertEqual(json.loads(result.content[0].text)['combination']['design'], design)
                context['plugin_combination'] = {'action': 'analyze', 'design': design,
                    'expected_id': suite_digest(design), 'observations': example.observations(design)}
                result = await session.call_tool('plan_plugin_use', {'context': context})
                self.assertFalse(result.isError)
                report = json.loads(result.content[0].text)['combination']
                self.assertEqual(report['recommendation']['candidate_arms'], ['AB'])
                self.assertEqual(report['evidence_status'], 'SIMULATION_ONLY')
                result = await session.call_tool('evaluate_plugin_value', {'suite': design['spec']['suite'], 'records': []})
                self.assertFalse(result.isError)
                self.assertEqual(json.loads(result.content[0].text)['verdict'], 'SIMULATION_ONLY')


if __name__ == '__main__':
    unittest.main()
