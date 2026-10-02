"""Layer boundaries and pre-refactor behavior must survive independent replay."""
import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests.test_burden_view import example
from value_lab.burden_collector import collect
from value_lab.burden_analyzer import analyze
from value_lab.burden_presentation import markdown as burden_markdown
from value_lab.core import ValidationError, suite_digest
from value_lab.decision_view import brief, render, markdown
from value_lab.workflow import plan_plugin_use

ROOT = Path(__file__).resolve().parents[1]


class BurdenLayerTests(unittest.TestCase):
    def setUp(self):
        self.request = example.request('tradeoff')
        self.source = self.request['plugin_combination']
        self.report = plan_plugin_use(self.request)['combination']

    def collect(self):
        return collect(self.source['design'], self.source['observations'],
                       self.source.get('burden_observations'))

    def test_collection_preserves_raw_samples_and_bindings_without_analysis(self):
        before = deepcopy(self.request)
        snapshot = self.collect()
        raw = self.source['burden_observations']['runs'][0]
        row = snapshot.runs[0]
        self.assertEqual(row.samples, tuple((s['request_index'], s['input_tokens']) for s in raw['samples']))
        for field in ('case_id', 'repetition', 'arm', 'session_id', 'record_sha256', 'coverage', 'expected_samples'):
            self.assertEqual(getattr(row, field), raw[field])
        self.assertEqual(snapshot.observations_sha256, self.report['observations_sha256'])
        self.assertEqual(snapshot.context_observations_sha256, suite_digest(self.source['burden_observations']))
        self.assertNotIn('value', asdict(row))
        self.assertNotIn('eligibility', asdict(row))
        self.assertEqual(self.request, before)

    def test_collection_is_immutable_and_detached_from_mutable_inputs(self):
        snapshot = self.collect()
        original = asdict(snapshot)
        with self.assertRaises(FrozenInstanceError):
            snapshot.runs_per_case = 1
        with self.assertRaises(FrozenInstanceError):
            snapshot.runs[0].coverage = 'partial'
        with self.assertRaises(TypeError):
            snapshot.runs[0].samples[0] = (1, 0)
        self.source['burden_observations']['runs'][0]['samples'][0]['input_tokens'] = 99999
        self.source['burden_observations']['measurement']['source'] = 'changed after collection'
        self.source['design']['spec']['suite']['cases'][0]['id'] = 'changed'
        self.assertEqual(asdict(snapshot), original)

    def test_analyzer_replays_without_recollection_and_does_not_mutate(self):
        snapshot = self.collect()
        before = deepcopy(self.report)
        with patch('value_lab.burden_collector.collect', side_effect=AssertionError('must not recollect')):
            first = analyze(snapshot, self.report)
            second = analyze(snapshot, self.report)
        self.assertEqual(first, self.report['burden_view'])
        self.assertEqual(first, second)
        self.assertEqual(self.report, before)
        first['measurement']['source'] = 'changed output'
        first['candidates'][0]['reasons'].append('changed output')
        self.assertEqual(analyze(snapshot, self.report), second)

    def test_mismatched_report_bindings_rejected(self):
        snapshot = self.collect()
        for field in ('design_sha256', 'observations_sha256'):
            report = deepcopy(self.report)
            report[field] = '0' * 64
            with self.subTest(field=field), self.assertRaises(ValidationError):
                analyze(snapshot, report)

    def test_existing_route_collects_once_and_default_analyze_stays_compatible(self):
        from value_lab.plugin_combinations import analyze as analyze_tasks
        for submitted in (True, False):
            request = deepcopy(self.request)
            if not submitted:
                del request['plugin_combination']['burden_observations']
            with patch('value_lab.burden_view.collect', wraps=collect) as collector:
                report = plan_plugin_use(request)['combination']
                self.assertEqual(collector.call_count, 1)
                self.assertEqual(collector.call_args.args[2], request['plugin_combination'].get('burden_observations'))
            if not submitted:
                self.assertEqual(analyze_tasks(self.source['design'], self.source['observations'],
                                               self.source['expected_id']), report)

    def test_original_task_analysis_is_independent_of_burden_pipeline(self):
        from value_lab.plugin_combinations import _analyze_tasks
        with patch('value_lab.burden_view.build', side_effect=AssertionError('burden in grading')):
            report = _analyze_tasks(self.source['design'], self.source['observations'], self.source['expected_id'])
        expected = deepcopy(self.report)
        del expected['burden_view']
        self.assertEqual(report, expected)

    def test_partial_and_absent_collection_remain_unknown(self):
        for absent in (True, False):
            self.source = example.request('tradeoff')['plugin_combination']
            if absent:
                del self.source['burden_observations']
            else:
                for row in self.source['burden_observations']['runs']:
                    row['coverage'] = 'partial'
            view = analyze(self.collect(), self.report)
            with self.subTest(absent=absent):
                self.assertTrue(all(c['metrics']['context_peak_fraction'] is None for c in view['candidates']))
                self.assertTrue(all(p['relation'] == 'UNKNOWN' for p in view['comparisons']))
                self.assertEqual(view['frontier']['dominated'], [])

    def test_collector_rejects_changed_binding_or_duplicate_requests(self):
        for fault in ('binding', 'duplicate'):
            self.source = example.request('tradeoff')['plugin_combination']
            row = self.source['burden_observations']['runs'][0]
            if fault == 'binding':
                row['record_sha256'] = '0' * 64
            else:
                row['samples'][1]['request_index'] = 1
            with self.subTest(fault=fault), self.assertRaises(ValidationError):
                self.collect()

    def test_presentation_replays_serialized_report_without_collection_or_analysis(self):
        report = json.loads(json.dumps(self.report, allow_nan=False))
        before = deepcopy(report)
        with patch('value_lab.burden_collector.collect', side_effect=AssertionError('collection in UI')), \
             patch('value_lab.burden_analyzer.analyze', side_effect=AssertionError('analysis in UI')), \
             patch('value_lab.burden_view.build', side_effect=AssertionError('pipeline in UI')):
            self.assertEqual(brief(report)['state'], 'REVIEW_TRADEOFF')
            self.assertIn('EVIDENCE.html', '\n'.join(markdown(report)))
            self.assertIn('<details', render(report, 'Replay'))
            self.assertTrue(burden_markdown(report['burden_view']))
        self.assertEqual(report, before)

    def test_dependency_direction_excludes_orchestration_and_io(self):
        allowed = {
            'burden_contracts': {'dataclasses'},
            'burden_collector': {'burden_contracts', 'core', 'science', 'task_selection'},
            'burden_analyzer': {'copy', 'itertools', 'statistics', 'burden_contracts', 'core'},
            'burden_presentation': set(),
            'decision_view': {'base64', 'hashlib', 'html', 'json', 'burden_presentation'},
        }
        for module, dependencies in allowed.items():
            tree = ast.parse((ROOT / 'value_lab' / (module + '.py')).read_text(encoding='utf-8'))
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imports.add(node.module)
                elif isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
            with self.subTest(module=module):
                self.assertLessEqual(imports, dependencies)

    def test_pre_refactor_results_and_presentations_unchanged(self):
        golden = json.loads((ROOT / 'tests/fixtures/burden-layering-before.json').read_text(encoding='utf-8'))
        for mode, hashes in golden['scenarios'].items():
            report = plan_plugin_use(example.request(mode))['combination']
            outputs = {'result': report, 'brief': brief(report),
                       'html': render(report, 'Architecture replay'), 'markdown': markdown(report),
                       'burden_markdown': burden_markdown(report['burden_view'])}
            for name, output in outputs.items():
                with self.subTest(mode=mode, output=name):
                    self.assertEqual(suite_digest(output), hashes[name])


if __name__ == '__main__':
    unittest.main()
