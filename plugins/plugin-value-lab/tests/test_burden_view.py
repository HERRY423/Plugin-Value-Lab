"""Burden tradeoffs must never silently change original candidate selection."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from value_lab.core import ValidationError, suite_digest
from value_lab.workflow import plan_plugin_use, write_plan

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('burden_example', ROOT / 'examples/plugin-combinations/burden_demo.py')
example = importlib.util.module_from_spec(loader)
loader.loader.exec_module(example)


class BurdenTests(unittest.TestCase):
    def setUp(self):
        self.request = example.request()

    def result(self):
        return plan_plugin_use(self.request)['combination']

    def view(self):
        return self.result()['burden_view']

    def pair(self, left='A', right='B'):
        return next(p for p in self.view()['comparisons'] if (p['left'], p['right']) == (left, right))

    def test_dominance_only_among_feasible_candidates(self):
        view = self.view()
        self.assertEqual(view['frontier']['fully_observed_nondominated'], ['A'])
        self.assertEqual(self.pair()['relation'], 'LEFT_DOMINATES')
        self.assertNotIn('BASELINE', view['eligible_arms'])
        self.assertEqual(view['candidates'][0]['eligibility'], 'FAILED')
        self.assertFalse(view['selection_rule_changed'])
        self.assertEqual(view['evidence_status'], 'SIMULATION_ONLY')

    def test_tradeoff_reports_specific_directions(self):
        self.request = example.request('tradeoff')
        pair = self.pair()
        self.assertEqual(pair['relation'], 'TRADEOFF')
        self.assertEqual({p['metric'] for p in pair['left_better_on']}, {'cost_usd'})
        self.assertEqual({p['metric'] for p in pair['right_better_on']}, {'context_peak_fraction', 'duration_seconds'})
        self.assertEqual(self.view()['frontier']['fully_observed_nondominated'], ['A', 'B'])

    def test_equal_retains_ties(self):
        self.request = example.request('equal')
        self.assertEqual(self.pair()['relation'], 'EQUAL')
        self.assertEqual(self.view()['frontier']['fully_observed_nondominated'], ['A', 'B'])

    def test_right_dominance_and_real_zero_are_supported(self):
        sub = self.request['plugin_combination']['burden_observations']
        for row in self.request['plugin_combination']['observations']['runs']:
            if row['arm'] == 'B':
                row['record']['cost']['model_usd'] = .001
                row['record']['duration_seconds'] = 1
                record = next(r for r in sub['runs'] if r['session_id'] == row['record']['session_id'])
                record['record_sha256'] = suite_digest(row['record'])
                for sample in record['samples']:
                    sample['input_tokens'] = 0
        self.assertEqual(self.pair()['relation'], 'RIGHT_DOMINATES')
        row = next(r for r in self.view()['candidates'] if r['arm'] == 'B')
        self.assertEqual(row['metrics']['context_peak_fraction'], 0)

    def test_baseline_can_be_in_burden_frontier(self):
        req = self.request['plugin_combination']
        for row in req['observations']['runs']:
            row['record']['output'] = '{"source_and_identifier_checked":true}'
        req['burden_observations'] = example.context_samples(req['design'], req['observations'],
                                                            {a: .1 for a in ('BASELINE', 'A', 'B', 'AB', 'BA')})
        self.assertIn('BASELINE', self.view()['frontier']['fully_observed_nondominated'])

    def test_explicit_null_sidecar_rejected(self):
        self.request['plugin_combination']['burden_observations'] = None
        with self.assertRaises(ValidationError):
            self.result()

    def test_no_selection_or_existing_report_change_and_no_input_mutation(self):
        before = deepcopy(self.request)
        report = self.result()
        self.assertEqual(before, self.request)
        self.request['plugin_combination'].pop('burden_observations')
        legacy = self.result()
        report.pop('burden_view')
        legacy.pop('burden_view')
        self.assertEqual(report, legacy)
        self.assertEqual(report['recommendation']['candidate_arms'], ['A', 'B'])

    def test_missing_never_becomes_zero_or_complete_frontier(self):
        self.request = example.request('missing')
        self.assertEqual(self.pair()['relation'], 'UNKNOWN')
        view = self.view()
        self.assertEqual(view['frontier']['status'], 'PARTIAL')
        self.assertIn('B', view['frontier']['unresolved_arms'])
        row = next(r for r in view['candidates'] if r['arm'] == 'B')
        self.assertIsNone(row['metrics']['context_peak_fraction'])
        self.assertIsNotNone(row['metrics']['cost_usd'])

    def test_legacy_records_show_cost_time_with_unknown_context(self):
        self.request['plugin_combination'].pop('burden_observations')
        self.assertEqual(self.view()['context_evidence'], 'MISSING')
        self.assertEqual(self.pair()['relation'], 'UNKNOWN')
        self.assertEqual(self.view()['frontier']['fully_observed_nondominated'], [])

    def test_partial_or_missing_request_cannot_establish_peak(self):
        for mutation in ('coverage', 'missing_sample', 'empty'):
            self.request = example.request()
            row = next(r for r in self.request['plugin_combination']['burden_observations']['runs'] if r['arm'] == 'A')
            if mutation == 'coverage':
                row['coverage'] = 'partial'
            else:
                row['samples'] = row['samples'][:1] if mutation == 'missing_sample' else []
            self.assertEqual(self.pair()['relation'], 'UNKNOWN')

    def test_context_drop_keeps_peak_not_last_sample(self):
        for row in self.request['plugin_combination']['burden_observations']['runs']:
            row['samples'].reverse()
            for i, sample in enumerate(row['samples'], 1):
                sample['request_index'] = i
        self.assertEqual(self.pair()['relation'], 'LEFT_DOMINATES')
        a = next(r for r in self.view()['candidates'] if r['arm'] == 'A')
        self.assertAlmostEqual(a['metrics']['context_peak_fraction'], .2)

    def test_per_case_reversal_not_hidden_by_aggregate(self):
        runs = self.request['plugin_combination']['burden_observations']['runs']
        case = runs[0]['case_id']
        for row in runs:
            if row['arm'] == 'A' and row['case_id'] == case:
                row['samples'][1]['input_tokens'] = 50000
        self.assertEqual(self.pair()['relation'], 'TRADEOFF')

    def test_wrong_design_session_record_or_conditions_rejected(self):
        for field in ('design', 'session', 'record', 'host', 'model'):
            self.request = example.request()
            sub = self.request['plugin_combination']['burden_observations']
            if field == 'design':
                sub['design_sha256'] = '0' * 64
            elif field in ('host', 'model'):
                sub['measurement'][field] = 'another'
            else:
                sub['runs'][0]['session_id' if field == 'session' else 'record_sha256'] = '0' * 64
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.result()

    def test_duplicate_unexpected_or_reordered_samples_rejected(self):
        for mutation in ('duplicate_run', 'unexpected_run', 'duplicate_index', 'reordered'):
            self.request = example.request()
            runs = self.request['plugin_combination']['burden_observations']['runs']
            if mutation == 'duplicate_run':
                runs[1] = deepcopy(runs[0])
            elif mutation == 'unexpected_run':
                runs[0]['case_id'] = 'unexpected'
            elif mutation == 'duplicate_index':
                runs[0]['samples'][1]['request_index'] = 1
            else:
                runs[0]['samples'].reverse()
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                self.result()

    def test_invalid_numbers_and_measurement_rejected(self):
        for value in (True, -1, 1.5, float('nan'), float('inf'), 2**53):
            self.request = example.request()
            self.request['plugin_combination']['burden_observations']['runs'][0]['samples'][0]['input_tokens'] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.result()
        for field, value in (('context_window_tokens', 0), ('sampling', 'last_turn_only')):
            self.request = example.request()
            self.request['plugin_combination']['burden_observations']['measurement'][field] = value
            with self.assertRaises(ValidationError):
                self.result()

    def test_missing_duration_cost_or_contamination_not_ranked(self):
        for field in ('cost', 'duration', 'exposure'):
            self.request = example.request()
            row = next(r for r in self.request['plugin_combination']['observations']['runs'] if r['arm'] == 'A')
            if field == 'cost':
                row['additional_cost_usd']['setup_usd'] = None
            elif field == 'duration':
                row['record']['duration_seconds'] = None
                sub = next(r for r in self.request['plugin_combination']['burden_observations']['runs'] if r['session_id'] == row['record']['session_id'])
                sub['record_sha256'] = suite_digest(row['record'])
            else:
                row['exposure']['plugins'] = []
            self.assertNotIn('A', self.view()['eligible_arms'])

    def test_no_eligible_candidates_and_empty_records(self):
        self.request['plugin_combination']['observations']['runs'] = []
        self.request['plugin_combination']['burden_observations']['runs'] = []
        self.assertEqual(self.view()['frontier']['status'], 'NOT_ASSESSED')
        self.assertEqual(self.view()['comparisons'], [])

    def test_render_and_schema(self):
        self.request = example.request('tradeoff')
        with tempfile.TemporaryDirectory() as tmp:
            write_plan(plan_plugin_use(self.request), Path(tmp) / 'report')
            text = (Path(tmp) / 'report/PLAN.md').read_text(encoding='utf-8')
            self.assertIn('独立负担视图', text)
            self.assertIn('存在取舍', text)
            self.assertIn('不改变最小插件选择规则', text)
        import jsonschema
        schema = json.loads((ROOT / 'schemas/plugin-combination.schema.json').read_text(encoding='utf-8'))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(self.request['plugin_combination'], schema)
        self.request['plugin_combination']['burden_observations']['runs'][0]['samples'][0]['input_tokens'] = True
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(self.request['plugin_combination'], schema)


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'Optional MCP SDK not installed')
class BurdenMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_stdio_tool_returns_burden_without_selection_change(self):
        import sys
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(command=sys.executable, args=[str(ROOT / 'scripts/value_lab.py'), 'serve'])
        context = example.request('tradeoff')
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                result = await session.call_tool('plan_plugin_use', {'context': context})
                self.assertFalse(result.isError)
                response = json.loads(result.content[0].text)
                self.assertEqual(response['evidence_brief']['state'], 'REVIEW_TRADEOFF')
                report = response['combination']
                pair = next(p for p in report['burden_view']['comparisons'] if p['left'] == 'A' and p['right'] == 'B')
                self.assertEqual(pair['relation'], 'TRADEOFF')
                self.assertEqual(report['recommendation']['candidate_arms'], ['A', 'B'])


if __name__ == '__main__':
    unittest.main()
