"""Local durable execution-attempt journal; never a model dispatcher.

The controller must use one original journal for its frozen study. Recreating or
copying a journal is not permission to repeat work. Appended operator evidence
does not authenticate host execution, independent sessions, or provider costs.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .core import ValidationError


_FORMAT = 'pvl-attempt-journal-1'
_RETRYABLE = {'failed', 'cancelled', 'not_dispatched'}
_TRANSITIONS = {
    'prepared': {'dispatched', 'not_dispatched'},
    'dispatched': {'running', 'completed', 'failed', 'cancelled', 'unknown'},
    'running': {'completed', 'failed', 'cancelled', 'unknown'},
    'unknown': {'completed', 'failed', 'cancelled'},
    'completed': set(), 'failed': set(), 'cancelled': set(), 'not_dispatched': set(),
}
_LIMITATION = ('Local append-only accounting, not authentication of host events, '
               'independence, settled costs or execution authorization.')


def _text(value, name):
    if (not isinstance(value, str) or not value.strip() or len(value) > 1024
            or any(c in value for c in '\r\n\x00')):
        raise ValidationError('Invalid ' + name)
    return value


def _payload(value):
    if not isinstance(value, dict) or not value:
        raise ValidationError('Transition evidence must be a nonempty JSON object')
    try:
        # Round-trip prevents tuple/key coercion from changing evidence identity.
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                             separators=(',', ':'))
        if json.loads(encoded) != value or len(encoded.encode('utf-8')) > 1024 * 1024:
            raise ValueError('Noncanonical or oversized evidence')
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValidationError('Evidence must contain finite JSON data, at most 1 MiB') from exc
    return encoded


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


class AttemptJournal:
    """Create/open ``study/journal.db`` bound to one frozen plan digest.

    ``reserve`` commits a prepared event before the caller dispatches anything.
    Only its first successful return has ``dispatch=True``; replay does not.
    Persist dispatched before the external operation. After uncertain outcomes,
    retain unknown and reconcile the original attempt using external evidence.
    This class itself performs no external calls or automatic recovery/retries.
    """

    def __init__(self, path, plan_sha256, *, create=True):
        if not isinstance(plan_sha256, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', plan_sha256):
            raise ValidationError('plan_sha256 must be a SHA-256 digest of the frozen plan')
        self.plan_sha256 = plan_sha256.lower()
        self.path = Path(path).absolute()
        if self.path.is_symlink():
            raise ValidationError('Journal path must not be a symbolic link')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction(create=create) as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if not tables:
                if not create:
                    raise ValidationError('Existing study journal is empty; recover original history, never reinitialize')
                self._initialize(db)
                db.execute('INSERT INTO metadata VALUES(1,?,?)', (_FORMAT, self.plan_sha256))
            elif tables != {'metadata', 'attempts', 'events'}:
                raise ValidationError('Unrecognized or incomplete attempt journal; recover the original')
            self._identity(db)

    @staticmethod
    def _initialize(db):
        # Individual statements preserve the surrounding initialization transaction.
        db.execute('CREATE TABLE metadata (id INTEGER PRIMARY KEY CHECK(id=1), '
                   'format TEXT NOT NULL, plan_sha256 TEXT NOT NULL)')
        db.execute('CREATE TABLE attempts (attempt_id TEXT PRIMARY KEY, slot_id TEXT NOT NULL, '
                   'idempotency_key TEXT NOT NULL UNIQUE, retry_of TEXT UNIQUE '
                   'REFERENCES attempts(attempt_id), created_at TEXT NOT NULL)')
        db.execute('CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, '
                   'attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id), '
                   "state TEXT NOT NULL CHECK(state IN ('prepared','dispatched','running',"
                   "'completed','failed','cancelled','unknown','not_dispatched')), "
                   'occurred_at TEXT NOT NULL, payload TEXT NOT NULL)')
        db.execute('CREATE INDEX attempt_slots ON attempts(slot_id)')
        db.execute('CREATE INDEX attempt_events ON events(attempt_id,seq)')
        for table in ('metadata', 'attempts', 'events'):
            for action in ('UPDATE', 'DELETE'):
                db.execute(f'CREATE TRIGGER immutable_{table}_{action.lower()} BEFORE {action} ON {table} '
                           "BEGIN SELECT RAISE(ABORT,'Attempt journal history is immutable'); END")

    def _identity(self, db):
        rows = db.execute('SELECT format,plan_sha256 FROM metadata').fetchall()
        if len(rows) != 1 or tuple(rows[0]) != (_FORMAT, self.plan_sha256):
            raise ValidationError('Journal frozen plan identity/format mismatch')

    @contextmanager
    def _transaction(self, *, create=False):
        db = None
        try:
            # Existing objects never recreate a deleted journal after a crash.
            db = sqlite3.connect(self.path.as_uri() + ('?mode=rwc' if create else '?mode=rw'),
                                 uri=True, timeout=30, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            if not create:
                self._identity(db)
            yield db
            db.commit()
        except sqlite3.Error as exc:
            if db is not None:
                db.rollback()
            raise ValidationError('Attempt journal unavailable or invalid: ' + str(exc)) from exc
        except Exception:
            if db is not None:
                db.rollback()
            raise
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def _attempt(db, attempt_id):
        row = db.execute('SELECT * FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
        if row is None:
            raise ValidationError('Unknown attempt_id')
        event = db.execute('SELECT seq,state,occurred_at,payload FROM events '
                           'WHERE attempt_id=? ORDER BY seq DESC LIMIT 1', (attempt_id,)).fetchone()
        if event is None:
            raise ValidationError('Attempt journal missing prepared event')
        return {**dict(row), 'state': event['state'], 'last_seq': event['seq'],
                'updated_at': event['occurred_at']}

    @staticmethod
    def _append(db, attempt_id, state, payload, stamp=None):
        db.execute('INSERT INTO events(attempt_id,state,occurred_at,payload) VALUES(?,?,?,?)',
                   (attempt_id, state, stamp or _now(), payload))

    def reserve(self, slot_id, key, retry_of=None):
        """Reserve once, or explicitly retry the most recent resolved failure.

        Unknown/running/dispatched/prepared attempts cannot be retried. A
        prepared attempt needs explicit not_dispatched evidence before retry.
        Reusing an identical key returns the original attempt without dispatch.
        """
        _text(slot_id, 'slot_id')
        _text(key, 'idempotency key')
        if retry_of is not None:
            _text(retry_of, 'retry_of')
        with self._transaction() as db:
            old = db.execute('SELECT * FROM attempts WHERE idempotency_key=?', (key,)).fetchone()
            if old is not None:
                if (old['slot_id'], old['retry_of']) != (slot_id, retry_of):
                    raise ValidationError('Idempotency key conflicts with the original slot/retry parameters')
                return {**self._attempt(db, old['attempt_id']), 'created': False, 'dispatch': False}
            latest = db.execute('SELECT a.attempt_id FROM attempts a JOIN events e '
                                "ON a.attempt_id=e.attempt_id AND e.state='prepared' "
                                'WHERE a.slot_id=? ORDER BY e.seq DESC LIMIT 1', (slot_id,)).fetchone()
            if latest is None:
                if retry_of is not None:
                    raise ValidationError('retry_of must identify the latest attempt of this slot')
            else:
                previous = self._attempt(db, latest['attempt_id'])
                if retry_of != previous['attempt_id']:
                    raise ValidationError('Slot already reserved; explicit retry_of latest resolved attempt required')
                if previous['state'] not in _RETRYABLE:
                    raise ValidationError('Attempt is not retryable: ' + previous['state'])
            attempt_id, stamp = str(uuid4()), _now()
            db.execute('INSERT INTO attempts VALUES(?,?,?,?,?)', (attempt_id, slot_id, key, retry_of, stamp))
            self._append(db, attempt_id, 'prepared', _payload(
                {'slot_id': slot_id, 'idempotency_key': key, 'retry_of': retry_of}), stamp)
            return {**self._attempt(db, attempt_id), 'created': True, 'dispatch': True}

    def transition(self, attempt_id, state, evidence):
        """Append a state transition; no event is overwritten.

        Reconciliation from unknown and release as not_dispatched require a
        nonempty evidence.source_ref. They remain operator-supplied assertions.
        Identical state/evidence replay is a no-op; altered replay is rejected.
        """
        _text(attempt_id, 'attempt_id')
        if not isinstance(state, str) or state not in _TRANSITIONS:
            raise ValidationError('Unknown attempt state')
        encoded = _payload(evidence)
        with self._transaction() as db:
            old = self._attempt(db, attempt_id)
            if state == old['state']:
                payload = db.execute('SELECT payload FROM events WHERE seq=?', (old['last_seq'],)).fetchone()[0]
                if payload != encoded:
                    raise ValidationError('Cannot rewrite evidence for an existing attempt state')
                return {**old, 'changed': False}
            if state not in _TRANSITIONS[old['state']]:
                raise ValidationError(f"Invalid attempt transition: {old['state']} -> {state}")
            if old['state'] == 'unknown' or state == 'not_dispatched':
                _text(evidence.get('source_ref'), 'reconciliation source_ref')
            self._append(db, attempt_id, state, encoded)
            return {**self._attempt(db, attempt_id), 'changed': True}

    def snapshot(self):
        """Return all attempts/events atomically, including failures and unknowns."""
        with self._transaction() as db:
            ids = [row[0] for row in db.execute("SELECT attempt_id FROM events WHERE state='prepared' GROUP BY attempt_id ORDER BY MIN(seq)")]
            events = [{**dict(row), 'payload': json.loads(row['payload'])}
                      for row in db.execute('SELECT * FROM events ORDER BY seq')]
            return {'format': _FORMAT, 'plan_sha256': self.plan_sha256,
                    'attempts': [self._attempt(db, ident) for ident in ids], 'events': events,
                    'last_seq': events[-1]['seq'] if events else 0,
                    'host_events_authenticated': False, 'execution_authorized': False,
                    'limitations': _LIMITATION}

    def note(self, attempt_id, evidence):
        """Append receipt metadata without changing or resolving the state."""
        encoded = _payload(evidence)
        with self._transaction() as db:
            old = self._attempt(db, attempt_id)
            if old['state'] not in {'prepared', 'dispatched', 'running', 'unknown'}:
                raise ValidationError('Cannot append new capture metadata to a terminal attempt')
            self._append(db, attempt_id, old['state'], encoded)
            return self._attempt(db, attempt_id)
