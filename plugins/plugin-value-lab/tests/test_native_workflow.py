"""Controlled event/launcher fixtures; never claim real model executions."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_native_analysis as support
from value_lab.core import ValidationError, load_json, write_json
from value_lab.native_evidence import discover_native_bindings
from value_lab.native_hypotheses import build_native_hypotheses, write_native_hypotheses, skill_events
from value_lab.native_trigger import prepare_trigger_probe, compare_trigger_probe
from value_lab.native_session import prepare_native_session, run_native_session, finish_native_session, _namespace


class HypothesisTests(unittest.TestCase):
    def test_real_skill_result_optional_error_flag_and_missing_result_are_distinct(self):
        call = {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Skill',
                'id': 'call1', 'input': {'skill': 'plugin:skill'}}]}}
        reply = {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'call1',
                 'content': 'Launching skill: plugin:skill'}]}}
        terminal = {'type': 'result', 'subtype': 'success'}
        def status(events):
            return skill_events('\n'.join(json.dumps(e) for e in events), 'trace.jsonl')[0]['result_status']
        self.assertEqual(status([call, reply, terminal]), 'TOOL_REPORTED_SUCCESS')
        self.assertEqual(status([call, terminal]), 'UNKNOWN')
        self.assertEqual(status([reply, call, terminal]), 'UNKNOWN')
        self.assertEqual(status([call, terminal, reply]), 'UNKNOWN')
        self.assertEqual(status([call, reply, reply, terminal]), 'UNKNOWN')
        reply['message']['content'][0]['is_error'] = True
        self.assertEqual(status([call, reply, terminal]), 'TOOL_ERROR')
        reply['message']['content'][0]['is_error'] = None
        self.assertEqual(status([call, reply, terminal]), 'UNKNOWN')

    def setUp(self):
        self.fx = support.NativeAnalysisTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root = self.fx.root
        self.expect = {'cases': {'numeric': {'expected_skills': ['fixture-analysis:analyze'], 'conclusion_grader_ids': []}}}

    def report(self, capture):
        return build_native_hypotheses(capture[0], capture[1], self.expect)

    @staticmethod
    def skill(workspace, events, run, case, arm, *, wrong=False, error=False):
        if arm == 'with':
            events[1]['message']['content'].append({'type': 'tool_use', 'id': 'skill1', 'name': 'Skill',
                'input': {'skill': 'other:skill' if wrong else 'fixture-analysis:analyze'}})
            events[2]['message']['content'].append({'type': 'tool_result', 'tool_use_id': 'skill1',
                'is_error': error, 'content': 'fixture skill result'})

    def contrast(self, *, mutate=None):
        natural = self.fx.captured('natural', correct=False)
        plan = load_json(natural[0] / 'receipt.json')['plan_sha256']
        probe_root = self.root / 'probe'
        probe = prepare_trigger_probe(natural[0], plan, self.expect, probe_root)
        with patch.object(self.fx, 'prepare', return_value=(probe_root, probe)):
            explicit = self.fx.captured('explicit', mutate=mutate or self.skill)
        return natural, explicit

    def compare(self, a, b):
        return compare_trigger_probe(a[0], a[1], b[0], b[1], self.expect, self.root / 'contrast')

    def test_missing_trigger_has_fact_prediction_and_falsifier(self):
        capture = self.fx.captured('natural', correct=False)
        report = self.report(capture)
        row = report['runs'][0]
        self.assertEqual([f['stage'] for f in row['facts']], ['load', 'trigger', 'selection', 'execution', 'artifact', 'conclusion'])
        self.assertEqual(row['facts'][1]['status'], 'NOT_OBSERVED')
        self.assertEqual(row['facts'][-1]['status'], 'NOT_ASSESSED')
        self.assertEqual({h['stage'] for h in row['hypotheses']}, {'trigger', 'artifact'})
        for h in row['hypotheses']:
            self.assertTrue(h['prediction'] and h['falsifier'] and h['fact_refs'])
            self.assertFalse(h['value_estimate_eligible'])
        self.assertEqual(report['runs'][1]['facts'][1]['status'], 'NOT_APPLICABLE')

    def test_truncated_trace_cannot_establish_no_trigger(self):
        def mutate(workspace, events, *_):
            events.pop()
        capture = self.fx.captured('truncated', mutate=mutate)
        self.assertEqual(self.report(capture)['runs'][0]['facts'][1]['status'], 'UNKNOWN')

    def test_other_skill_is_observed_not_declared_a_proven_wrong_method(self):
        capture = self.fx.captured('other', mutate=lambda *args: self.skill(*args, wrong=True))
        row = self.report(capture)['runs'][0]
        self.assertEqual(row['facts'][2]['status'], 'OTHER_SKILL_OBSERVED')
        self.assertIsNone(row['facts'][2]['causal_explanation'])
        self.assertIn('mapping may be wrong', next(h for h in row['hypotheses'] if h['stage'] == 'selection')['hypothesis'])

    def test_missing_plugin_and_contaminated_baseline_are_distinct(self):
        def mutate(workspace, events, run, case, arm):
            events[0]['plugins'] = [] if arm == 'with' else [{'name': 'fixture-analysis'}]
        report = self.report(self.fx.captured('load', mutate=mutate))
        self.assertEqual(report['runs'][0]['facts'][0]['status'], 'NOT_OBSERVED')
        self.assertEqual(report['runs'][1]['facts'][0]['status'], 'BASELINE_CONTAMINATED')

    def test_runtime_failure_not_erased_by_successful_tool_or_artifact(self):
        def mutate(workspace, events, run, *_):
            run['error'] = 'runtime timeout'
        report = self.report(self.fx.captured('failed', mutate=mutate))
        self.assertEqual(report['runs'][0]['facts'][3]['status'], 'REPORTED_FAILURE')

    def test_conclusion_requires_existing_declared_check(self):
        capture = self.fx.captured('failed', correct=False)
        self.expect['cases']['numeric']['conclusion_grader_ids'] = ['correct']
        row = self.report(capture)['runs'][0]
        self.assertEqual(row['facts'][-1]['status'], 'FAILED')
        self.expect['cases']['numeric']['conclusion_grader_ids'] = ['invented-review']
        with self.assertRaises(ValidationError):
            self.report(capture)

    def test_explicit_probe_is_exact_append_and_diagnostic_only(self):
        a, b = self.contrast()
        result = self.compare(a, b)
        self.assertEqual(result['status'], 'CONTROLLED_DIAGNOSTIC_CONTRAST')
        self.assertEqual(result['cases'][0]['finding'], 'TEST_TRIGGER_DESCRIPTION_NEXT')
        self.assertFalse(result['comparison_eligible'])
        self.assertFalse(result['natural_use_value_replaced'])
        self.assertEqual(load_json(a[0] / 'diagnosis.json')['runs'][0]['grades'][0]['passed'], False)

    def test_failed_skill_result_does_not_support_trigger_fix(self):
        a, b = self.contrast(mutate=lambda *args: self.skill(*args, error=True))
        self.assertEqual(self.compare(a, b)['cases'][0]['finding'], 'TRIGGER_EXPLANATION_NOT_ESTABLISHED')

    def test_repeated_skill_result_is_not_success_evidence(self):
        def mutate(workspace, events, *args):
            self.skill(workspace, events, *args)
            if args[-1] == 'with':
                events[2]['message']['content'].append(dict(events[2]['message']['content'][-1]))
        a, b = self.contrast(mutate=mutate)
        self.assertEqual(self.compare(a, b)['cases'][0]['finding'], 'TRIGGER_EXPLANATION_NOT_ESTABLISHED')

    def test_input_change_blocks_trigger_contrast(self):
        def mutate(workspace, *args):
            self.skill(workspace, *args)
            (workspace / 'input.csv').write_text('changed', encoding='utf-8')
        a, b = self.contrast(mutate=mutate)
        self.assertEqual(self.compare(a, b)['status'], 'INCOMPARABLE_DIAGNOSTIC')

    def test_model_change_blocks_trigger_contrast(self):
        def mutate(workspace, events, *args):
            self.skill(workspace, events, *args)
            events[0]['model'] = 'different'
        a, b = self.contrast(mutate=mutate)
        self.assertEqual(self.compare(a, b)['status'], 'INCOMPARABLE_DIAGNOSTIC')

    def test_two_unbound_captures_cannot_become_controlled_probe(self):
        a = self.fx.captured('natural', correct=False)
        b = self.fx.captured('unbound', mutate=self.skill)
        self.assertEqual(self.compare(a, b)['status'], 'INCOMPARABLE_DIAGNOSTIC')

    def test_external_pin_and_no_overwrite(self):
        capture = self.fx.captured('natural')
        with self.assertRaises(ValidationError):
            build_native_hypotheses(capture[0], '0' * 64, self.expect)
        write_native_hypotheses(capture[0], capture[1], self.expect, self.root / 'hypotheses')
        with self.assertRaises(ValidationError):
            write_native_hypotheses(capture[0], capture[1], self.expect, self.root / 'hypotheses')

    def test_cli_hypotheses(self):
        capture = self.fx.captured('natural', correct=False)
        write_json(self.root / 'expect.json', self.expect)
        cli = Path(__file__).resolve().parents[1] / 'scripts/value_lab.py'
        result = subprocess.run([sys.executable, '-B', str(cli), 'native-hypotheses', str(capture[0]),
            '--receipt-sha256', capture[1], '--expectations', str(self.root / 'expect.json'), '--output', str(self.root / 'cli')],
            capture_output=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.fx = support.NativeAnalysisTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root = self.fx.root
        self.prep, self.result = self.fx.prepare()
        self.cli = self.root / 'claude'
        self.bwrap = self.root / 'bwrap'
        self.cli.write_text('fixture executable', encoding='utf-8')
        self.bwrap.write_text('fixture isolation backend', encoding='utf-8')
        self.argv = [str(self.cli), 'plugin', 'eval', str(self.prep / 'candidate'), '--eval-dir', 'pvl-analysis-evals',
                     '--model', 'fixture-model', '--runs', '1', '--max-cost-usd', '0.1', '--ablation', 'with-without',
                     '--allow-tools', 'Write', 'Bash']
        self.output = self.root / 'session'

    def prepare(self, argv=None):
        with patch('value_lab.native_session.sys.platform', 'linux'), \
             patch('value_lab.native_session.shutil.which', side_effect=lambda name: str(self.bwrap) if name == 'bwrap' else str(self.cli)), \
             patch('value_lab.native_session.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '2.1.278 (Claude Code)\n', '')), \
             patch('value_lab.native_session.probe_namespace', return_value={'passed': True, 'fixture': True}):
            return prepare_native_session(self.prep / 'plan', self.result['plan_sha256'], self.prep / 'candidate', argv or self.argv, self.output)

    def test_preparation_preserves_case_bytes_and_does_not_launch_model(self):
        before = (self.prep / 'candidate/pvl-analysis-evals/numeric/prompt.md').read_bytes()
        result = self.prepare()
        frozen = load_json(self.output / 'session-plan.json')
        self.assertEqual(result['model_calls'], 0)
        self.assertFalse((self.output / 'started.json').exists())
        self.assertEqual(before, (self.prep / 'candidate/pvl-analysis-evals/numeric/prompt.md').read_bytes())
        for flag in ('--keep-temp', '--no-publish', '--json'):
            self.assertIn(flag, frozen['argv'])
        self.assertNotIn('--trust-plugin', frozen['argv'])
        self.assertEqual(frozen['expected_sessions'], 2)
        self.assertEqual(result['disclosure']['expected_sessions'], 2)
        self.assertEqual(result['disclosure']['invocation'], frozen['argv'])
        self.assertEqual(result['disclosure']['cost']['native_estimate_ceiling_usd'], 0.1)

    def test_unknown_publish_real_server_and_count_changes_refused(self):
        variants = [self.argv + ['--publish-report'], self.argv + ['--allow-real-servers'],
                    self.argv + ['--mocks', 'off'], self.argv + ['--runs', '2'], self.argv + ['--case', 'only-failure']]
        for argv in variants:
            with self.assertRaises(ValidationError):
                self.prepare(argv)
            self.assertFalse(self.output.exists())

    def test_host_wrapper_that_fails_inside_namespace_blocks_preparation(self):
        with patch('value_lab.native_session.sys.platform', 'linux'), \
             patch('value_lab.native_session.shutil.which', side_effect=lambda name: str(self.bwrap) if name == 'bwrap' else str(self.cli)), \
             patch('value_lab.native_session.subprocess.run', side_effect=[
                 subprocess.CompletedProcess([], 0, '2.1.278 (Claude Code)\n', ''),
                 subprocess.CompletedProcess([], 126, '', 'Exec format error')]), \
             patch('value_lab.native_session.probe_namespace', return_value={'passed': True}), \
             self.assertRaisesRegex(ValidationError, 'compatible Linux executable'):
            prepare_native_session(self.prep / 'plan', self.result['plan_sha256'], self.prep / 'candidate', self.argv, self.output)
        self.assertFalse((self.output / 'session-plan.json').exists())
        self.assertFalse((self.output / 'started.json').exists())

    def test_unplanned_case_blocks_unbudgeted_native_work(self):
        extra = self.prep / 'candidate/pvl-analysis-evals/unplanned'
        extra.mkdir()
        (extra / 'prompt.md').write_text('Additional unfrozen native work', encoding='utf-8')
        with self.assertRaisesRegex(ValidationError, 'unplanned cases'):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_exact_authorization_and_once_only(self):
        result = self.prepare()
        with self.assertRaises(ValidationError):
            run_native_session(self.output, result['session_sha256'])
        self.assertFalse((self.output / 'started.json').exists())
        write_json(self.output / 'started.json', {'fixture': True})
        with self.assertRaises(ValidationError):
            run_native_session(self.output, result['session_sha256'], execute=True)

    def test_changed_executable_and_case_block_launch(self):
        result = self.prepare()
        self.cli.write_text('changed', encoding='utf-8')
        with patch('value_lab.native_session.sys.platform', 'linux'), self.assertRaises(ValidationError):
            run_native_session(self.output, result['session_sha256'], execute=True)
        self.assertFalse((self.output / 'started.json').exists())

    def test_unknown_process_state_never_relaunches(self):
        result = self.prepare()
        with self.assertRaises(ValidationError):
            finish_native_session(self.output, result['session_sha256'])
        self.assertFalse((self.output / 'started.json').exists())

    def test_native_failure_without_aggregate_retains_unknown_cost(self):
        result = self.prepare()
        def launch(*args):
            return {'exit_code': 2, 'timed_out': False, 'duration_seconds': .01}
        with patch('value_lab.native_session.sys.platform', 'linux'), \
             patch('value_lab.native_session.probe_namespace', return_value={'passed': True}), \
             patch('value_lab.codex._run', side_effect=launch) as run:
            observed = run_native_session(self.output, result['session_sha256'], execute=True)
            self.assertEqual(observed['status'], 'NATIVE_RESULT_MISSING')
            self.assertIsNone(observed['settled_usd'])
            self.assertEqual(run.call_count, 1)
            self.assertEqual(finish_native_session(self.output, result['session_sha256']), observed)

    def test_automatic_capture_keeps_partial_missing_trace(self):
        result = self.prepare()
        def launch(*args):
            write_json(self.output / 'native/result.json', {'schemaVersion': 1, 'claudeVersion': '2.1.278', 'partial': True,
                'cases': [{'name': 'numeric', 'arms': {'with': [{'error': 'timeout', 'tracePath': str(self.output / 'retained/missing.jsonl')}], 'without': []}}]})
            return {'exit_code': 2, 'timed_out': False, 'duration_seconds': .01}
        with patch('value_lab.native_session.sys.platform', 'linux'), \
             patch('value_lab.native_session.probe_namespace', return_value={'passed': True}), \
             patch('value_lab.codex._run', side_effect=launch):
            observed = run_native_session(self.output, result['session_sha256'], execute=True)
        self.assertEqual(observed['status'], 'COLLECTED')
        report = load_json(self.output / 'collected/diagnosis.json')
        self.assertEqual([r['status'] for r in report['runs']], ['error', 'missing'])
        self.assertTrue(all(g['passed'] is None for r in report['runs'] for g in r['grades']))
        # A crash after sealing but before writing completion can be resumed offline.
        (self.output / 'completion.json').unlink()
        recovered = finish_native_session(self.output, result['session_sha256'])
        self.assertEqual(recovered['receipt_sha256'], observed['receipt_sha256'])
        (self.output / 'collected/records.json').write_text('[]', encoding='utf-8')
        with self.assertRaises(ValidationError):
            finish_native_session(self.output, result['session_sha256'])

    def test_isolation_command_masks_references_and_parent_proc(self):
        command = _namespace(['claude'], ['/private/scorers'], Path('/safe/empty'), '/usr/bin/bwrap', ['/runs'])
        self.assertEqual(command[1:4], ['--ro-bind', '/', '/'])
        self.assertIn('--unshare-pid', command)
        self.assertIn('WSL_INTEROP', command)
        self.assertIn('/private/scorers', command)
        self.assertNotIn('--unshare-net', command)  # Native model transport remains possible; native tool rules govern agent networking.

    def test_missing_retained_workspace_is_unknown_not_invented(self):
        retained = self.root / 'retained'
        retained.mkdir()
        trace = retained / 'trace.jsonl'
        trace.write_text(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 'fixture',
                                    'cwd': str(retained / 'gone')}) + '\n', encoding='utf-8')
        native = self.root / 'native.json'
        write_json(native, {'schemaVersion': 1, 'claudeVersion': '2.1.278', 'cases': [
            {'name': 'numeric', 'arms': {'with': [{'error': None, 'tracePath': str(trace)}]}}]})
        result = discover_native_bindings(native, retained)
        self.assertFalse(result['bindings'])
        self.assertEqual(result['missing'][0]['reason'], 'Retained workspace missing')


if __name__ == '__main__':
    unittest.main()
