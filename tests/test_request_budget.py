"""Admission races, crash recovery and accounting failures; no paid calls."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from value_lab.core import ValidationError
from value_lab.request_budget import RequestBudget
from value_lab.online_sandbox import ModelGateway


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'task.sqlite'

    def create(self, history=None, per=100000, total=1000000):
        return RequestBudget.create(self.path, 'same-task', per, total,
                                    history=[] if history is None else history, coverage_ref='fixture-inventory')

    def reserve(self, ledger, key='one', upper=100000):
        return ledger.reserve(key, 'a' * 64, 'fixture POST /messages', upper)

    def test_unknown_history_is_not_zero_or_estimate(self):
        ledger = self.create([{'id': 'old', 'estimate_usd': '0.2562524', 'source_ref': 'old-report'}])
        self.assertIsNone(ledger.status()['remaining_micros'])
        self.assertIsNone(ledger.status()['settled_total_micros'])
        with self.assertRaisesRegex(ValidationError, 'HISTORY_UNKNOWN'):
            self.reserve(ledger)
        ledger.reconcile_history('old', 200000, 100000, 'fixture-invoice#line1')
        self.assertEqual(ledger.status()['remaining_micros'], 700000)
        self.assertEqual(ledger.status()['history'][0]['estimate_usd'], '0.2562524')

    def test_restart_holds_reservation_and_replay_never_dispatches(self):
        self.assertTrue(self.reserve(self.create())['dispatch'])
        recovered = RequestBudget(self.path, 'same-task')
        self.assertEqual(recovered.status()['remaining_micros'], 900000)
        self.assertFalse(self.reserve(recovered)['dispatch'])
        self.assertFalse(recovered.status()['paid_launch_authorized'])
        with self.assertRaisesRegex(ValidationError, 'conflicts'):
            recovered.reserve('one', 'b' * 64, 'fixture POST /messages', 100000)

    def test_missing_file_task_change_and_reinitialization_cannot_reset(self):
        with self.assertRaisesRegex(ValidationError, 'missing'):
            RequestBudget(self.path, 'same-task')
        self.create()
        with self.assertRaises(FileExistsError):
            self.create()
        with self.assertRaisesRegex(ValidationError, 'identity'):
            RequestBudget(self.path, 'new-task')

    def test_concurrent_admission_uses_one_total(self):
        self.create(total=300000)
        def attempt(i):
            try:
                return self.reserve(RequestBudget(self.path, 'same-task'), str(i))['dispatch']
            except ValidationError as exc:
                self.assertIn('TASK_BUDGET_EXHAUSTED', str(exc))
                return False
        with ThreadPoolExecutor(max_workers=12) as pool:
            self.assertEqual(sum(pool.map(attempt, range(20))), 3)
        self.assertEqual(RequestBudget(self.path, 'same-task').status()['remaining_micros'], 0)

    def test_same_key_concurrent_admission_dispatches_once(self):
        self.create()
        def attempt(_):
            return self.reserve(RequestBudget(self.path, 'same-task'))['dispatch']
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt, range(16))), 1)

    def test_process_exit_after_reservation_does_not_release_it(self):
        self.create()
        code = ('import os,sys; from value_lab.request_budget import RequestBudget; '
                "b=RequestBudget(sys.argv[1], 'same-task'); "
                "b.reserve('crash', 'a'*64, 'fixture', 100000); os._exit(7)")
        result = subprocess.run([sys.executable, '-c', code, str(self.path)], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 7, result.stderr.decode(errors='replace'))
        recovered = RequestBudget(self.path, 'same-task')
        self.assertEqual(recovered.status()['remaining_micros'], 900000)
        self.assertFalse(recovered.reserve('crash', 'a'*64, 'fixture', 100000)['dispatch'])

    def test_single_request_cap_checked_before_total(self):
        ledger = self.create()
        with self.assertRaisesRegex(ValidationError, 'PER_REQUEST_CAP'):
            self.reserve(ledger, upper=100001)
        self.assertEqual(ledger.status()['requests'], [])

    def test_money_is_integer_and_unknown_bound_is_rejected(self):
        ledger = self.create()
        for value in (None, True, 0, -1, .1, float('nan'), '1000', 10**13):
            with self.assertRaises(ValidationError):
                self.reserve(ledger, upper=value)

    def test_settlement_releases_only_known_difference(self):
        ledger = self.create()
        self.reserve(ledger)
        ledger.settle('one', 23000, 'invoice#line1')
        ledger.settle('one', 23000, 'invoice#line1')
        state = ledger.status()
        self.assertEqual(state['remaining_micros'], 977000)
        self.assertEqual(state['known_settled_subtotal_micros'], 23000)
        self.assertFalse(self.reserve(ledger)['dispatch'])
        with self.assertRaisesRegex(ValidationError, 'rewrite'):
            ledger.settle('one', 0, 'new-ref')

    def test_overrun_is_retained_and_stops_later_requests(self):
        ledger = self.create()
        self.reserve(ledger)
        ledger.settle('one', 113755, 'overrun#line1')
        self.assertEqual(ledger.status()['status'], 'BOUND_BREACH')
        self.assertEqual(ledger.status()['known_settled_subtotal_micros'], 113755)
        with self.assertRaisesRegex(ValidationError, 'BOUND_BREACH'):
            self.reserve(ledger, 'two')

    def test_reused_invoice_lines_cannot_release_multiple_reservations(self):
        ledger = self.create()
        self.reserve(ledger)
        self.reserve(ledger, 'two')
        ledger.settle('one', 0, 'release#line1')
        with self.assertRaisesRegex(ValidationError, 'already used'):
            ledger.settle('two', 0, 'release#line1')
        self.assertEqual(ledger.status()['known_reserved_subtotal_micros'], 100000)

    def test_history_revisions_keep_estimates_and_settled_costs(self):
        ledger = self.create([{'id': 'old', 'estimate_usd': None, 'source_ref': 'old-report'}])
        ledger.reconcile_history('old', 100, 200, 'invoice#1')
        ledger.reconcile_history('old', 200, 0, 'invoice#2')
        with self.assertRaisesRegex(ValidationError, 'erase'):
            ledger.reconcile_history('old', 0, 0, 'invoice#3')
        self.assertEqual(ledger.status()['settled_total_micros'], 200)

    def test_direct_https_gateway_cannot_bypass_gate(self):
        gateway = ModelGateway({'endpoint': 'https://api.example.com'}, 'synthetic-key')
        with patch('socket.getaddrinfo', side_effect=AssertionError('No network allowed')):
            with self.assertRaisesRegex(ValidationError, 'BUDGET_BOUNDARY_UNAVAILABLE'):
                gateway._https('/v1/messages', b'{}', '', 1)
            with self.assertRaisesRegex(ValidationError, 'BUDGET_BOUNDARY_UNAVAILABLE'):
                gateway.request({}, 1)
        self.assertEqual(gateway.requests, 0)
        self.assertEqual(gateway.events, [])


if __name__ == '__main__':
    unittest.main()
