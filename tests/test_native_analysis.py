"""Manufactured transport/retest cases; these are not real host observations."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from value_lab.artifacts import sha
from value_lab.core import ValidationError, load_json, write_json
from value_lab.native_analysis import prepare_native_analysis
from value_lab.native_evidence import capture_native_evidence, verify_native_evidence
from value_lab.native_execution import observe_execution
from value_lab.native_repair import compare_native_repair


class NativeAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plugin = self.root / 'source'
        self.plugin.mkdir()
        write_json(self.plugin / 'plugin.json', {'name': 'fixture-analysis', 'version': '1'})
        (self.plugin / 'SKILL.md').write_text('fixture candidate v1', encoding='utf-8')
        (self.plugin / 'private.txt').write_text('not selected', encoding='utf-8')
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir()
        (self.inputs / 'input.csv').write_bytes(b'id,value\na,1\nb,2\n')
        self.context = {'host_version': 'fixture', 'model': 'fixture-model', 'model_version': 'fixture-weights',
                        'environment': 'synthetic only', 'tools': ['Read', 'Skill', 'Write', 'Bash'],
                        'max_turns': 8, 'timeout_seconds': 60, 'max_cost_usd': .1}
        self.case = {'name': 'numeric', 'prompt': 'Analyze input.csv and write result.json.', 'repetitions': 1,
                     'inputs': {'data': {'path': 'input.csv', 'sha256': sha(self.inputs / 'input.csv')}},
                     'artifacts': {'result': 'result.json', 'script': 'analysis.py'},
                     'execution': {'script_artifact': 'script', 'command': 'python3 analysis.py'},
                     'graders': [{'id': 'correct', 'type': 'artifact', 'artifact': 'result',
                                  'verifier': {'kind': 'json_fields', 'expected': {'ok': True}}}]}
        self.recipe = {'schema_version': 1, 'plugin_files': ['SKILL.md'],
                       'execution_context': self.context, 'cases': [self.case]}

    def prepare(self, name='prepared', recipe=None):
        root = self.root / name
        result = prepare_native_analysis(recipe or self.recipe, self.plugin, self.inputs, root)
        return root, result

    def stream(self, sid, arm, *, success=True, command='python3 analysis.py', end=True):
        events = [{'type': 'system', 'subtype': 'init', 'session_id': sid, 'model': 'fixture-model',
                   'claude_code_version': 'fixture', 'tools': self.context['tools'],
                   'plugins': [{'name': 'fixture-analysis'}] if arm == 'with' else []},
                  {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Bash',
                   'id': 'call1', 'input': {'command': command}}]}},
                  {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'call1',
                   'is_error': not success, 'content': 'observed tool response'}]}}]
        if end:
            events.append({'type': 'result', 'subtype': 'success', 'is_error': False,
                           'session_id': sid, 'result': 'fixture completion'})
        return events

    def captured(self, name, *, correct=True, recipe=None, mutate=None, same_sessions=False, baseline=True):
        prep, result = self.prepare(name + '-plan', recipe)
        contract = load_json(prep / 'contract.json')
        native = {'schemaVersion': 1, 'claudeVersion': 'fixture', 'partial': False, 'cases': []}
        bindings = []
        for case in contract['cases']:
            item = {'name': case['name'], 'arms': {'with': [], 'without': []}}
            native['cases'].append(item)
            for arm in ('with', 'without'):
                for rep in range(1, case['repetitions'] + 1):
                    item['arms'][arm].append({'error': None})
                    workspace = self.root / f'{name}-{case["name"]}-{arm}-{rep}'
                    workspace.mkdir()
                    (workspace / 'input.csv').write_bytes((self.inputs / 'input.csv').read_bytes())
                    (workspace / 'analysis.py').write_text('print("fixture only")', encoding='utf-8')
                    write_json(workspace / 'result.json', {'ok': correct if arm == 'with' else baseline})
                    sid = f'{"reused" if same_sessions else name}-{case["name"]}-{arm}-{rep}'
                    events = self.stream(sid, arm)
                    if mutate:
                        mutate(workspace, events, item['arms'][arm][-1], case, arm)
                    (workspace / 'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events), encoding='utf-8')
                    bindings.append({'case_id': case['name'], 'arm': arm, 'repetition': rep,
                                     'workspace': str(workspace), 'events': 'events.jsonl'})
        native_path = self.root / (name + '.json')
        write_json(native_path, native)
        output = self.root / (name + '-capture')
        captured = capture_native_evidence(prep / 'plan', result['plan_sha256'], prep / 'candidate',
                                          native_path, bindings, output)
        return output, captured['receipt_sha256'], captured['diagnosis']

    def compare(self, a, b, name='comparison'):
        return compare_native_repair(a[0], a[1], b[0], b[1], self.root / name)['report']

    def revisions(self, **after_options):
        before = self.captured('before', correct=False)
        (self.plugin / 'SKILL.md').write_text('fixture candidate v2', encoding='utf-8')
        after = self.captured('after', **after_options)
        return before, after

    def test_preparation_native_files_input_pins_and_no_private_copy(self):
        root, result = self.prepare()
        contract = load_json(root / 'contract.json')
        self.assertEqual(contract['cases'][0]['input_sha256']['data'], sha(self.inputs / 'input.csv'))
        self.assertFalse((root / 'candidate/private.txt').exists())
        argv = result['execution_plan']['argv']
        for option in ('--keep-temp', '--no-publish', '--scaffold', 'with-without'):
            self.assertIn(option, argv)
        self.assertNotIn('--trust-plugin', argv)
        self.assertNotIn('--allow-real-servers', argv)
        self.assertEqual(result['model_calls'], 0)
        case = root / 'candidate/pvl-analysis-evals/numeric'
        self.assertEqual(load_json(case / 'case.yaml')['schema_version'], '1.1')
        self.assertIn('type: "file_exists"', (case / 'graders/result.md').read_text())

    def test_preparation_refuses_changed_input_before_writing(self):
        (self.inputs / 'input.csv').write_text('changed', encoding='utf-8')
        with self.assertRaises(ValidationError):
            self.prepare()
        self.assertFalse((self.root / 'prepared').exists())

    def test_path_collisions_traversal_and_invalid_context(self):
        for change in ('collision', 'traversal', 'cost', 'model', 'tools', 'script'):
            recipe = deepcopy(self.recipe)
            if change == 'collision':
                recipe['cases'][0]['artifacts']['script'] = 'INPUT.csv'
            elif change == 'traversal':
                recipe['cases'][0]['inputs']['data']['path'] = '../input.csv'
            elif change == 'cost':
                recipe['execution_context']['max_cost_usd'] = float('nan')
            elif change == 'model':
                recipe['execution_context']['model'] = '--unsafe'
            elif change == 'tools':
                recipe['execution_context']['tools'].append('WebFetch')
            else:
                recipe['cases'][0]['execution']['script_artifact'] = 'missing'
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.prepare(change, recipe)

    def test_no_overwrite_or_startup_server_profile(self):
        self.prepare()
        with self.assertRaises(ValidationError):
            self.prepare()
        write_json(self.plugin / 'plugin.json', {'name': 'fixture', 'hooks': {}})
        with self.assertRaises(ValidationError):
            self.prepare('hooked')

    def test_exact_command_success_and_no_prose_execution(self):
        events = self.stream('one', 'with')
        def observe(events):
            return observe_execution('\n'.join(json.dumps(e) for e in events), self.case['execution'], {'script': {'sha256': 'fixture'}})
        self.assertEqual(observe(events)['status'], 'TOOL_REPORTED_SUCCESS')
        events[1]['message']['content'][0]['input']['command'] = 'echo python3 analysis.py'
        self.assertEqual(observe(events)['status'], 'NOT_OBSERVED')
        events[1]['message']['content'][0]['input']['command'] = 'python3 analysis.py'
        events[1]['message']['content'][0]['input']['run_in_background'] = True
        self.assertEqual(observe(events)['status'], 'UNKNOWN')

    def test_tool_result_missing_ambiguous_or_wrong_order_is_unknown(self):
        cases = []
        events = self.stream('one', 'with')
        cases.append([events[0], events[2], events[1], events[3]])
        cases.append([events[0], events[3], events[1], events[2]])
        cases.append(events + [events[2]])
        missing_flag = deepcopy(events)
        del missing_flag[2]['message']['content'][0]['is_error']
        cases.append(missing_flag)
        cases.append([events[0], events[1], events[3]])
        for stream in cases:
            result = observe_execution('\n'.join(json.dumps(e) for e in stream), self.case['execution'], {'script': {}})
            self.assertEqual(result['status'], 'UNKNOWN')

    def test_failed_tool_attempt_is_retained(self):
        events = self.stream('one', 'with', success=False)
        call = deepcopy(events[1])
        call['message']['content'][0]['id'] = 'retry'
        reply = deepcopy(events[2])
        reply['message']['content'][0].update(tool_use_id='retry', is_error=False)
        events[3:3] = [call, reply]
        result = observe_execution('\n'.join(json.dumps(e) for e in events), self.case['execution'], {'script': {}})
        self.assertEqual(result['status'], 'TOOL_ERROR')
        self.assertEqual(len(result['calls']), 2)

    def test_full_repair_is_descriptive_and_not_value_promotion(self):
        before, after = self.revisions()
        report = self.compare(before, after)
        self.assertEqual(report['status'], 'LOCAL_RETEST_IMPROVEMENT')
        self.assertEqual(len(report['checks']), 2)
        self.assertFalse(report['comparison_eligible'])
        self.assertFalse(report['paired_repetition_claim'])
        self.assertEqual(verify_native_evidence(after[0], after[1])['status'], 'REPRODUCED')

    def test_input_mutation_blocks_repair_even_if_result_passes(self):
        def mutate(workspace, *_):
            (workspace / 'input.csv').write_text('tampered', encoding='utf-8')
        a, b = self.revisions(mutate=mutate)
        self.assertEqual(b[2]['runs'][0]['input_integrity']['data'], 'CHANGED')
        self.assertTrue(b[2]['runs'][0]['grades'][0]['passed'])
        self.assertEqual(self.compare(a, b)['status'], 'INCOMPLETE_EVIDENCE')

    def test_failed_runtime_does_not_become_success_from_artifact(self):
        def mutate(workspace, events, run, *_):
            run['error'] = 'timeout'
        a, b = self.revisions(mutate=mutate)
        self.assertEqual(self.compare(a, b)['status'], 'INCOMPLETE_EVIDENCE')

    def test_missing_script_trace_blocks_repair(self):
        def mutate(workspace, events, *_):
            del events[1:3]
        a, b = self.revisions(mutate=mutate)
        self.assertEqual(self.compare(a, b)['status'], 'INCOMPLETE_EVIDENCE')

    def test_terminal_error_and_assistant_model_drift_block_repair(self):
        a = self.captured('before', correct=False)
        for kind in ('terminal', 'assistant'):
            def mutate(workspace, events, *_, kind=kind):
                if kind == 'terminal':
                    events[-1]['is_error'] = True
                else:
                    events[1]['message']['model'] = 'changed-model'
            b = self.captured(kind, mutate=mutate)
            self.assertEqual(self.compare(a, b, kind + '-comparison')['status'], 'INCOMPLETE_EVIDENCE')

    def test_manifest_version_change_alone_is_not_repair(self):
        a = self.captured('before', correct=False)
        write_json(self.plugin / 'plugin.json', {'name': 'fixture-analysis', 'version': '2'})
        b = self.captured('after')
        self.assertEqual(self.compare(a, b)['status'], 'NO_CANDIDATE_CHANGE')

    def test_model_drift_and_baseline_contamination(self):
        for field in ('model', 'plugins', 'claude_code_version', 'tools'):
            def mutate(workspace, events, *_, field=field):
                events[0][field] = ['unexpected'] if field == 'tools' else 'unexpected'
            a = self.captured('before-' + field, correct=False)
            b = self.captured('after-' + field, mutate=mutate)
            self.assertEqual(self.compare(a, b, field)['status'], 'INCOMPLETE_EVIDENCE')

    def test_case_or_grader_or_repetitions_change_blocks_repair(self):
        a = self.captured('before', correct=False)
        for field in ('grader', 'prompt', 'repetitions'):
            recipe = deepcopy(self.recipe)
            if field == 'grader':
                recipe['cases'][0]['graders'][0]['verifier']['expected'] = {'ok': False}
            elif field == 'prompt':
                recipe['cases'][0]['prompt'] += ' new requirement'
            else:
                recipe['cases'][0]['repetitions'] = 2
            b = self.captured('after-' + field, recipe=recipe)
            self.assertEqual(self.compare(a, b, field)['status'], 'PROTOCOL_CHANGED')

    def test_same_capture_or_sessions_are_not_a_new_retest(self):
        a = self.captured('before', same_sessions=True)
        b = self.captured('after', same_sessions=True)
        self.assertEqual(self.compare(a, b)['status'], 'INCOMPLETE_EVIDENCE')
        self.assertEqual(self.compare(a, a, 'same')['status'], 'INCOMPLETE_EVIDENCE')

    def test_control_regression_preserved(self):
        a, b = self.revisions(baseline=False)
        result = self.compare(a, b)
        self.assertEqual(result['status'], 'REGRESSION_OBSERVED')
        self.assertEqual(len(result['baseline_changes']), 1)

    def test_baseline_improvement_requires_review(self):
        a = self.captured('before', correct=False, baseline=False)
        (self.plugin / 'SKILL.md').write_text('changed', encoding='utf-8')
        b = self.captured('after')
        self.assertEqual(self.compare(a, b)['status'], 'BASELINE_CHANGED_REVIEW_REQUIRED')

    def test_no_candidate_change_cannot_be_attributed_to_repair(self):
        a = self.captured('before', correct=False)
        b = self.captured('after')
        self.assertEqual(self.compare(a, b)['status'], 'NO_CANDIDATE_CHANGE')

    def test_cli_preparation_and_comparison(self):
        recipe = self.root / 'recipe.json'
        write_json(recipe, self.recipe)
        cli = Path(__file__).resolve().parents[1] / 'scripts/value_lab.py'
        result = subprocess.run([sys.executable, '-B', str(cli), 'prepare-native-analysis', str(recipe),
                                 '--plugin', str(self.plugin), '--inputs', str(self.inputs), '--output', str(self.root / 'cli')],
                                capture_output=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        a, b = self.revisions()
        result = subprocess.run([sys.executable, '-B', str(cli), 'compare-native-repair', str(a[0]), str(b[0]),
                                 '--before-receipt', a[1], '--after-receipt', b[1], '--output', str(self.root / 'cli-repair')],
                                capture_output=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['report']['status'], 'LOCAL_RETEST_IMPROVEMENT')


if __name__ == '__main__':
    unittest.main()
