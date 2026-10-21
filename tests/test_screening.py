"""Local engineering fixtures, not native plugin or laboratory benefit evidence."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from value_lab.core import ValidationError, load_json, suite_digest
from value_lab.request_budget import RequestBudget
from value_lab.screening import CHECKS, evaluate, prepare, schedule, screen


def inputs():
    plugins = [{'id': 'fixture-plugin', 'version': '1', 'sha256': 'a' * 64,
                'checks': {k: {'status': 'pass', 'evidence_ref': 'fixture-only'} for k in CHECKS}}]
    tasks = [{'id': f't{i}', 'kind': kind, 'input': 'synthetic input', 'rubric': 'fixture rubric',
              'baseline': 'same host without plugin'} for i, kind in enumerate(('positive', 'failure', 'boundary'))]
    return plugins, tasks


def observations(plan, delta=.2):
    return [{**run, 'plan_sha256': plan['plan_sha256'], 'status': 'completed',
             'score': .5 + (delta if run['arm'] == 'with' else 0), 'critical_failure': False,
             'evidence_ref': 'fixture-output', 'scoring_ref': 'fixture-score', 'cost_micros': 0,
             'cost_ref': 'offline-fixture', 'correction_seconds': 1} for run in schedule(plan)]


class ScreeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plugins, self.tasks = inputs()
        self.plan = prepare(self.plugins, self.tasks)

    def save(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def test_three_outcomes_and_frozen_local_not_general_claim(self):
        self.assertEqual(evaluate(self.plan, [])['status'], 'INSUFFICIENT_EVIDENCE')
        gain = evaluate(self.plan, observations(self.plan))
        self.assertEqual(gain['status'], 'ADVANCE_PILOT')
        self.assertFalse(gain['adoption_supported'])
        self.assertAlmostEqual(gain['mean_task_delta'], .2)
        self.assertEqual(evaluate(self.plan, observations(self.plan, 0))['status'], 'STOP')

    def test_static_block_missing_and_failed_without_evidence(self):
        for state, ref, expected in [('fail', 'verified-ref', 'STOP'), ('fail', None, 'INSUFFICIENT_EVIDENCE'),
                                     ('UNKNOWN', 'ref', 'INSUFFICIENT_EVIDENCE')]:
            plugins = deepcopy(self.plugins)
            plugins[0]['checks']['egress'] = {'status': state, 'evidence_ref': ref}
            self.assertEqual(evaluate(prepare(plugins, self.tasks), [])['status'], expected)
        self.tasks[0]['kind'] = 'boundary'
        self.assertTrue(any('三类' in item for item in evaluate(prepare(self.plugins, self.tasks), [])['missing']))

    def test_partial_unknown_duplicate_mismatched_and_nonfinite_cannot_advance(self):
        for mutation in ('partial', 'cost', 'score', 'risk', 'duplicate', 'digest', 'extra', 'bool_repeat'):
            rows = observations(self.plan)
            if mutation == 'partial': rows.pop()
            if mutation == 'cost': rows[0]['cost_micros'] = None
            if mutation == 'score': rows[0]['score'] = float('nan')
            if mutation == 'risk': rows[0]['critical_failure'] = None
            if mutation == 'duplicate': rows.append(rows[0])
            if mutation == 'digest': rows[0]['plan_sha256'] = 'b' * 64
            if mutation == 'extra': rows[0]['task_id'] = 'extra'
            if mutation == 'bool_repeat': rows[0]['repeat'] = False
            with self.subTest(mutation=mutation):
                self.assertEqual(evaluate(self.plan, rows)['status'], 'INSUFFICIENT_EVIDENCE')

    def test_verified_harm_stops_incomplete_unverified_holds(self):
        row = observations(self.plan)[0]
        row['critical_failure'] = True
        self.assertEqual(evaluate(self.plan, [row])['status'], 'INSUFFICIENT_EVIDENCE')
        row['critical_verified_ref'] = 'reviewer-ref'
        self.assertEqual(evaluate(self.plan, [row])['status'], 'STOP')
        missing_plan = deepcopy(self.plan)
        missing_plan['plugins'][0]['checks']['license']['status'] = 'UNKNOWN'
        self.assertEqual(evaluate(missing_plan, [row])['status'], 'STOP')

    def test_cost_breach_and_task_regression_not_averaged_away(self):
        rows = observations(self.plan)
        rows[0]['cost_micros'] = 100001
        self.assertEqual(evaluate(self.plan, rows)['status'], 'STOP')
        rows = observations(self.plan)
        for row in rows:
            if row['task_id'] == 't0' and row['arm'] == 'with': row['score'] = 0
        self.assertEqual(evaluate(self.plan, rows)['status'], 'STOP')

    def test_cli_writes_card_and_import_recomputes_frozen_matrix(self):
        plugins, tasks = self.save('plugins.json', self.plugins), self.save('tasks.json', self.tasks)
        result = subprocess.run([sys.executable, '-m', 'value_lab.easy_cli', 'screen', '--plugins', str(plugins),
            '--tasks', str(tasks), '--output', str(self.root / 'first'), '--json'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'INSUFFICIENT_EVIDENCE')
        frozen = self.root / 'first/frozen-plan.json'
        plan = load_json(frozen)
        bundle = self.save('results.json', {'plan_sha256': plan['plan_sha256'], 'runs': observations(plan)})
        result = screen(plugins, tasks, self.root / 'second', results_path=bundle, frozen_path=frozen)
        self.assertEqual(result['status'], 'ADVANCE_PILOT')
        self.assertIn('进入先导', Path(result['use_card']).read_text(encoding='utf-8'))
        with self.assertRaises(ValidationError): screen(plugins, tasks, self.root / 'second')
        self.tasks[0]['rubric'] = 'changed'
        self.save('tasks.json', self.tasks)
        with self.assertRaisesRegex(ValidationError, 'mismatch'):
            screen(plugins, tasks, self.root / 'third', results_path=bundle, frozen_path=frozen)

    def runner_settings(self, body, upper=0):
        adapter = self.root / 'adapter.py'
        adapter.write_text(body, encoding='utf-8')
        ledger = self.root / 'task.sqlite'
        RequestBudget.create(ledger, 'fixture', 100000, 1000000, history=[], coverage_ref='offline-fixture-only')
        return {'runner': {'argv': [sys.executable, str(adapter)], 'files': [str(adapter)],
                'timeout_seconds': 5, 'upper_micros': upper, 'bound_ref': 'offline-fixture-only',
                'ledger': str(ledger), 'task_id': 'fixture'}}

    def test_actual_local_adapter_full_run_and_replay_no_dispatch(self):
        settings = self.runner_settings('''import json,sys
r=json.load(sys.stdin)
print(json.dumps(dict(status='completed', score=.8 if r['arm']=='with' else .5,
critical_failure=False, evidence_ref='synthetic', scoring_ref='fixture',
cost_micros=0, cost_ref='offline-fixture', correction_seconds=0)))
''')
        plugins, tasks = self.save('plugins.json', self.plugins), self.save('tasks.json', self.tasks)
        config = self.save('settings.json', settings)
        result = screen(plugins, tasks, self.root / 'run', settings_path=config)
        self.assertEqual(result['status'], 'ADVANCE_PILOT')
        self.assertEqual(result['observed_runs'], 12)
        again = screen(plugins, tasks, self.root / 'replay', settings_path=config)
        self.assertEqual(again['observed_runs'], 0)
        self.assertEqual(again['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(len(RequestBudget(settings['runner']['ledger'], 'fixture').status()['requests']), 12)

    def test_failed_runner_preserves_attempt_cost_unknown_and_no_retry(self):
        settings = self.runner_settings('raise SystemExit(7)', upper=100000)
        result = screen(self.save('plugins.json', self.plugins), self.save('tasks.json', self.tasks),
                        self.root / 'failed', settings_path=self.save('settings.json', settings))
        self.assertEqual(result['observed_runs'], 1)
        self.assertEqual(result['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(RequestBudget(settings['runner']['ledger'], 'fixture').status()['remaining_micros'], 900000)
        self.assertIsNone(load_json(self.root / 'failed/receipt-00.json')['cost_micros'])

    def test_input_and_budget_validation(self):
        for tasks in (self.tasks[:2], self.tasks * 2):
            with self.assertRaises(ValidationError): prepare(self.plugins, tasks)
        for settings in ({'min_gain': float('nan')}, {'per_request_micros': True}, {'repeats': 3}, {'extra': 1}):
            with self.assertRaises(ValidationError): prepare(self.plugins, self.tasks, settings)
        plan = prepare(self.plugins, self.tasks, {'per_request_micros': 500000, 'total_micros': 5000000})
        self.assertEqual(plan['settings']['per_request_micros'], 500000)
        self.assertEqual(len(schedule(plan)), 12)
