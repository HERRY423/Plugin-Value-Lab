"""Durable attempt recovery and real multiprocess races; no model requests."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from value_lab.attempt_journal import AttemptJournal
from value_lab.core import ValidationError


ROOT = Path(__file__).resolve().parents[1]
PLAN = 'a' * 64


class AttemptJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'study' / 'journal.db'
        self.journal = AttemptJournal(self.path, PLAN)

    def reserve(self, key='first'):
        return self.journal.reserve('case-1/with/1', key)

    def move(self, attempt, state, ref='fixture-event'):
        return self.journal.transition(attempt['attempt_id'], state, {'source_ref': ref})

    def test_plan_binding_and_idempotent_parameter_conflicts(self):
        attempt = self.reserve()
        self.assertTrue(attempt['dispatch'])
        self.assertEqual(attempt['state'], 'prepared')
        recovered = AttemptJournal(self.path, PLAN.upper())
        replay = recovered.reserve(attempt['slot_id'], 'first')
        self.assertEqual(replay['attempt_id'], attempt['attempt_id'])
        self.assertFalse(replay['dispatch'])
        self.assertFalse(replay['created'])
        for slot, retry in [('different-slot', None), (attempt['slot_id'], attempt['attempt_id'])]:
            with self.assertRaisesRegex(ValidationError, 'conflicts'):
                recovered.reserve(slot, 'first', retry_of=retry)
        with self.assertRaisesRegex(ValidationError, 'identity'):
            AttemptJournal(self.path, 'b' * 64)
        self.assertEqual(len(recovered.snapshot()['events']), 1)

    def test_all_events_are_retained_and_completed_never_retries(self):
        attempt = self.reserve()
        for state in ('dispatched', 'running', 'completed'):
            self.move(attempt, state, state)
        snap = self.journal.snapshot()
        self.assertEqual([row['state'] for row in snap['events']], ['prepared','dispatched','running','completed'])
        self.assertEqual([row['seq'] for row in snap['events']], [1,2,3,4])
        self.assertTrue(all(row['occurred_at'].endswith('+00:00') for row in snap['events']))
        self.assertFalse(snap['host_events_authenticated'])
        with self.assertRaisesRegex(ValidationError, 'not retryable: completed'):
            self.journal.reserve(attempt['slot_id'], 'new', retry_of=attempt['attempt_id'])
        self.assertFalse(self.reserve()['dispatch'])

    def test_unknown_requires_evidenced_reconciliation_and_explicit_retry(self):
        attempt = self.reserve()
        self.move(attempt, 'dispatched')
        self.move(attempt, 'running')
        self.move(attempt, 'unknown', 'connection-lost')
        for key, retry in [('new', None), ('new', attempt['attempt_id'])]:
            with self.assertRaises(ValidationError):
                self.journal.reserve(attempt['slot_id'], key, retry_of=retry)
        for target, evidence in [('prepared', {'source_ref':'x'}), ('dispatched', {'source_ref':'x'}),
                                 ('not_dispatched', {'source_ref':'x'}), ('failed', {'reason':'claimed'})]:
            with self.assertRaises(ValidationError):
                self.journal.transition(attempt['attempt_id'], target, evidence)
        self.move(attempt, 'failed', 'host-final-status#attempt-1')
        retry = self.journal.reserve(attempt['slot_id'], 'retry', retry_of=attempt['attempt_id'])
        self.assertTrue(retry['created'])
        self.assertEqual([row['state'] for row in self.journal.snapshot()['attempts']], ['failed','prepared'])
        with self.assertRaises(ValidationError):
            self.journal.reserve(attempt['slot_id'], 'fork', retry_of=attempt['attempt_id'])

    def test_prepared_crash_does_not_imply_not_dispatched(self):
        attempt = self.reserve()
        reopened = AttemptJournal(self.path, PLAN)
        self.assertEqual(reopened.snapshot()['attempts'][0]['state'], 'prepared')
        with self.assertRaises(ValidationError):
            reopened.reserve(attempt['slot_id'], 'retry', retry_of=attempt['attempt_id'])
        with self.assertRaisesRegex(ValidationError, 'source_ref'):
            reopened.transition(attempt['attempt_id'], 'not_dispatched', {'reason':'crashed'})
        with self.assertRaises(ValidationError):
            reopened.transition(attempt['attempt_id'], 'cancelled', {'source_ref':'x'})
        reopened.transition(attempt['attempt_id'], 'not_dispatched', {'source_ref':'controller-pre-dispatch-audit'})
        self.assertTrue(reopened.reserve(attempt['slot_id'], 'retry', retry_of=attempt['attempt_id'])['dispatch'])

    def test_failed_cancelled_and_not_dispatched_chains_preserve_every_attempt(self):
        attempt = self.reserve()
        self.move(attempt, 'not_dispatched')
        for index, terminal in enumerate(('failed', 'cancelled', 'failed'), 1):
            attempt = self.journal.reserve(attempt['slot_id'], f'key-{index}', retry_of=attempt['attempt_id'])
            self.move(attempt, 'dispatched')
            self.move(attempt, terminal)
        snapshot = self.journal.snapshot()
        self.assertEqual([r['state'] for r in snapshot['attempts']], ['not_dispatched','failed','cancelled','failed'])
        self.assertEqual(len(snapshot['events']), 11)
        with self.assertRaises(ValidationError):
            self.journal.reserve('another-slot', 'cross-slot', retry_of=attempt['attempt_id'])

    def test_transition_replay_does_not_rewrite_or_duplicate_history(self):
        attempt = self.reserve()
        self.move(attempt, 'dispatched', 'dispatch-1')
        replay = self.move(attempt, 'dispatched', 'dispatch-1')
        self.assertFalse(replay['changed'])
        with self.assertRaisesRegex(ValidationError, 'rewrite'):
            self.move(attempt, 'dispatched', 'different-proof')
        self.assertEqual(len(self.journal.snapshot()['events']), 2)
        for evidence in ({}, {'x':float('nan')}, {'x':object()}, {1:'number-key'}, {'x':('tuple',)}):
            with self.assertRaises(ValidationError):
                self.journal.transition(attempt['attempt_id'], 'running', evidence)

    def test_illegal_state_moves_and_unknown_ids_fail_closed(self):
        attempt = self.reserve()
        for state in ('running', 'completed', 'failed', 'unknown', 'invented'):
            with self.assertRaises(ValidationError):
                self.move(attempt, state)
        with self.assertRaisesRegex(ValidationError, 'Unknown attempt'):
            self.journal.transition('nonexistent', 'dispatched', {'source_ref':'x'})
        for value in ('', 'a\n', None, 1):
            with self.assertRaises(ValidationError):
                self.journal.reserve(value, 'x')

    def test_database_enforces_immutable_history_and_foreign_keys(self):
        attempt = self.reserve()
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        db.execute('PRAGMA foreign_keys=ON')
        for table in ('events', 'attempts', 'metadata'):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'immutable'):
                db.execute('DELETE FROM ' + table)
            db.rollback()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'immutable'):
            db.execute("UPDATE events SET payload='{}'")
        db.rollback()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY'):
            db.execute("INSERT INTO events(attempt_id,state,occurred_at,payload) VALUES('missing','prepared','now','{}')")
        db.rollback()
        self.assertEqual(self.journal.snapshot()['attempts'][0]['attempt_id'], attempt['attempt_id'])

    def test_process_exit_retains_unknown_and_does_not_redispatch(self):
        code = ("import os,sys; from value_lab.attempt_journal import AttemptJournal; "
                "j=AttemptJournal(sys.argv[1], 'a'*64); a=j.reserve('crashed-slot','crashed-key'); "
                "j.transition(a['attempt_id'],'dispatched',{'source_ref':'controller'}); "
                "j.transition(a['attempt_id'],'unknown',{'source_ref':'lost-connection'}); os._exit(7)")
        result = subprocess.run([sys.executable, '-c', code, str(self.path)], cwd=ROOT,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 7, result.stderr.decode(errors='replace'))
        reopened = AttemptJournal(self.path, PLAN)
        snapshot = reopened.snapshot()
        self.assertEqual(snapshot['attempts'][0]['state'], 'unknown')
        self.assertFalse(reopened.reserve('crashed-slot','crashed-key')['dispatch'])
        with self.assertRaisesRegex(ValidationError, 'not retryable'):
            reopened.reserve('crashed-slot','new-key',retry_of=snapshot['attempts'][0]['attempt_id'])

    def race(self, *, same_key):
        # Actual independent Python processes contend on the same SQLite journal.
        code = ("import json,sys; from value_lab.attempt_journal import AttemptJournal; "
                "from value_lab.core import ValidationError\n"
                "try:\n j=AttemptJournal(sys.argv[1], 'a'*64); "
                "r=j.reserve('racing-slot',sys.argv[2]); print(json.dumps(r))\n"
                "except ValidationError as e:\n print(json.dumps({'error':str(e)}))\n")
        processes = [subprocess.Popen([sys.executable,'-c',code,str(self.path),'same' if same_key else str(i)],
                                      cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(6)]
        results = []
        try:
            for process in processes:
                stdout, stderr = process.communicate(timeout=45)
                self.assertEqual(process.returncode, 0, stderr.decode(errors='replace'))
                results.append(json.loads(stdout))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
        return results

    def test_cross_process_same_key_has_one_admission(self):
        results = self.race(same_key=True)
        self.assertEqual(sum(r.get('dispatch',False) for r in results), 1)
        self.assertEqual(len({r['attempt_id'] for r in results}), 1)
        self.assertEqual(len(self.journal.snapshot()['events']), 1)

    def test_cross_process_first_open_initializes_one_journal(self):
        self.path.unlink()
        results = self.race(same_key=True)
        self.assertEqual(sum(r.get('created',False) for r in results), 1)
        self.assertEqual(len({r['attempt_id'] for r in results}), 1)
        self.assertEqual(len(self.journal.snapshot()['events']), 1)

    def test_process_exit_after_prepare_keeps_slot_closed(self):
        code = ("import os,sys; from value_lab.attempt_journal import AttemptJournal; "
                "j=AttemptJournal(sys.argv[1], 'a'*64); j.reserve('prepared-slot','prepared-key'); os._exit(8)")
        result = subprocess.run([sys.executable, '-c', code, str(self.path)], cwd=ROOT,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 8, result.stderr.decode(errors='replace'))
        reopened = AttemptJournal(self.path, PLAN)
        attempt = reopened.snapshot()['attempts'][0]
        self.assertEqual(attempt['state'], 'prepared')
        self.assertFalse(reopened.reserve('prepared-slot','prepared-key')['dispatch'])
        with self.assertRaisesRegex(ValidationError, 'not retryable: prepared'):
            reopened.reserve('prepared-slot','replacement',retry_of=attempt['attempt_id'])

    def test_cross_process_different_keys_cannot_duplicate_slot(self):
        results = self.race(same_key=False)
        self.assertEqual(sum(r.get('dispatch',False) for r in results), 1)
        self.assertEqual(sum('error' in r for r in results), 5)
        self.assertEqual(len(self.journal.snapshot()['attempts']), 1)

    def test_existing_object_does_not_recreate_lost_database(self):
        self.reserve()
        self.path.unlink()
        with self.assertRaisesRegex(ValidationError, 'unavailable'):
            self.journal.snapshot()
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
