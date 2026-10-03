"""Durable admission accounting, NOT a provider-enforced price ceiling.

The trusted controller owns this database outside the guest. Amounts are integer
USD micros. An upper bound must come from a separately verified transport; this
module cannot derive one from token estimates, consent, or a provider balance.
Reconciliation references are operator-supplied evidence, not authenticated bills.
Creating/copying a database does not grant a new budget or reset task spending.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3

from .core import ValidationError


def _amount(value, name, nullable=False):
    if nullable and value is None:
        return value
    if type(value) is not int or not 0 <= value <= 10**12:
        raise ValidationError(name + ' must be integer USD micros, not an estimate')
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024 or any(c in value for c in '\r\n\x00'):
        raise ValidationError('Invalid ' + name)
    return value


class RequestBudget:
    """One shared task ledger; reopen explicitly, never recreate on recovery."""

    def __init__(self, path, task_id):
        self.path = Path(path).resolve()
        self.task_id = _text(task_id, 'task_id')
        if not self.path.is_file():
            raise ValidationError('Budget ledger missing; recover the original, do not reset spending')
        with self._transaction() as db:
            if db.execute('SELECT task_id FROM policy').fetchone()[0] != self.task_id:
                raise ValidationError('Budget task identity mismatch')

    @classmethod
    def create(cls, path, task_id, per_request_micros, total_micros, *, history, coverage_ref):
        """Explicit operator initialization. Unknown history remains blocking.

        history contains {id, estimate_usd, source_ref}; estimates are retained
        verbatim as strings and NEVER admitted as settlements or upper bounds.
        An empty list is an explicit no-prior-cost declaration, not a discovery.
        """
        _text(task_id, 'task_id')
        _text(coverage_ref, 'history coverage reference')
        _amount(per_request_micros, 'per-request ceiling')
        _amount(total_micros, 'total ceiling')
        if not 0 < per_request_micros <= total_micros:
            raise ValidationError('Require 0 < per-request ceiling <= total ceiling')
        if not isinstance(history, list):
            raise ValidationError('Explicit history inventory required')
        seen = set()
        for row in history:
            if not isinstance(row, dict) or set(row) != {'id', 'estimate_usd', 'source_ref'}:
                raise ValidationError('History requires id/estimate_usd/source_ref')
            _text(row['id'], 'history id')
            _text(row['source_ref'], 'history source')
            estimate = row['estimate_usd']
            if estimate is not None and (not isinstance(estimate, str) or not re.fullmatch(r'\d+(?:\.\d+)?', estimate)):
                raise ValidationError('Historical estimate must be a decimal string or null')
            if row['id'] in seen:
                raise ValidationError('Duplicate history id')
            seen.add(row['id'])
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents accidental truncation or a recovery reset.
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        db = sqlite3.connect(path)
        try:
            db.executescript('''
                PRAGMA synchronous=FULL;
                CREATE TABLE policy(task_id TEXT PRIMARY KEY, per_request INTEGER NOT NULL,
                    total INTEGER NOT NULL, coverage_ref TEXT NOT NULL);
                CREATE TABLE history(id TEXT PRIMARY KEY, estimate_usd TEXT, source_ref TEXT NOT NULL);
                CREATE TABLE history_evidence(seq INTEGER PRIMARY KEY, id TEXT NOT NULL,
                    settled INTEGER NOT NULL, pending INTEGER NOT NULL, evidence_ref TEXT UNIQUE NOT NULL);
                CREATE TABLE requests(key TEXT PRIMARY KEY, digest TEXT NOT NULL, operation TEXT NOT NULL,
                    upper INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE settlements(key TEXT PRIMARY KEY, charged INTEGER NOT NULL,
                    evidence_ref TEXT UNIQUE NOT NULL);
            ''')
            db.execute('INSERT INTO policy VALUES(?,?,?,?)', (task_id, per_request_micros, total_micros, coverage_ref))
            db.executemany('INSERT INTO history VALUES(:id,:estimate_usd,:source_ref)', history)
            db.commit()
        finally:
            db.close()
        return cls(path, task_id)

    @contextmanager
    def _transaction(self):
        # mode=rw prevents sqlite from silently recreating a lost database.
        db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _status(self, db):
        policy = dict(db.execute('SELECT * FROM policy').fetchone())
        if policy['task_id'] != self.task_id:
            raise ValidationError('Budget task identity mismatch')
        history = []
        for row in db.execute('SELECT * FROM history ORDER BY id'):
            evidence = db.execute('SELECT * FROM history_evidence WHERE id=? ORDER BY seq DESC LIMIT 1', (row['id'],)).fetchone()
            history.append({**dict(row), 'settled_micros': evidence['settled'] if evidence else None,
                            'pending_upper_micros': evidence['pending'] if evidence else None,
                            'reconciliation_ref': evidence['evidence_ref'] if evidence else None})
        requests = [dict(r) for r in db.execute('SELECT r.*, s.charged, s.evidence_ref FROM requests r LEFT JOIN settlements s USING(key) ORDER BY r.rowid')]
        unknown = any(row['settled_micros'] is None for row in history)
        settled = sum(r['settled_micros'] or 0 for r in history) + sum(r['charged'] or 0 for r in requests)
        pending = sum(r['pending_upper_micros'] or 0 for r in history) + sum(r['upper'] for r in requests if r['charged'] is None)
        breach = any(r['charged'] is not None and r['charged'] > r['upper'] for r in requests)
        breached_history = db.execute('SELECT 1 FROM history_evidence WHERE settled + pending > ? LIMIT 1', (policy['total'],)).fetchone()
        breach = breach or bool(breached_history) or settled + pending > policy['total']
        return {'task_id': self.task_id, 'per_request_micros': policy['per_request'], 'total_micros': policy['total'],
                'status': 'BOUND_BREACH' if breach else 'HISTORY_UNKNOWN' if unknown else 'ACCOUNTING_READY',
                'known_settled_subtotal_micros': settled, 'known_reserved_subtotal_micros': pending,
                'settled_total_micros': None if unknown else settled,
                'remaining_micros': None if unknown or breach else policy['total'] - settled - pending,
                'history': history, 'requests': requests, 'provider_cap_verified': False,
                'paid_launch_authorized': False,
                'limitations': 'Accounting only. Evidence references are not authenticated invoices; native budget gate remains in force.'}

    def status(self):
        with self._transaction() as db:
            return self._status(db)

    def reserve(self, key, request_sha256, operation, upper_micros):
        """Commit reservation before dispatch. A replay NEVER grants dispatch."""
        _text(key, 'idempotency key')
        _text(operation, 'operation')
        _amount(upper_micros, 'request upper bound')
        if not isinstance(request_sha256, str) or not re.fullmatch('[0-9a-f]{64}', request_sha256):
            raise ValidationError('Request digest must bind exact model/path/body bytes')
        with self._transaction() as db:
            old = db.execute('SELECT * FROM requests WHERE key=?', (key,)).fetchone()
            if old:
                if (old['digest'], old['operation'], old['upper']) != (request_sha256, operation, upper_micros):
                    raise ValidationError('Idempotency key conflicts with original operation')
                return {'key': key, 'dispatch': False, 'action': 'RECOVER_ORIGINAL_INVOCATION'}
            state = self._status(db)
            if state['status'] != 'ACCOUNTING_READY':
                raise ValidationError(state['status'] + ': admission denied')
            if not 0 < upper_micros <= state['per_request_micros']:
                raise ValidationError('PER_REQUEST_CAP_EXCEEDED')
            if upper_micros > state['remaining_micros']:
                raise ValidationError('TASK_BUDGET_EXHAUSTED')
            db.execute('INSERT INTO requests(key,digest,operation,upper) VALUES(?,?,?,?)',
                       (key, request_sha256, operation, upper_micros))
        return {'key': key, 'dispatch': True, 'reserved_micros': upper_micros,
                'requires_independently_enforced_transport': True}

    @staticmethod
    def _unused_evidence(db, ref):
        if (db.execute('SELECT 1 FROM history_evidence WHERE evidence_ref=?', (ref,)).fetchone()
                or db.execute('SELECT 1 FROM settlements WHERE evidence_ref=?', (ref,)).fetchone()):
            raise ValidationError('Settlement evidence reference already used')

    def reconcile_history(self, history_id, settled_micros, pending_upper_micros, evidence_ref):
        """Append an operator reconciliation; retain every original estimate."""
        _amount(settled_micros, 'historical settled amount')
        _amount(pending_upper_micros, 'historical pending upper bound')
        _text(evidence_ref, 'settlement evidence reference')
        with self._transaction() as db:
            if not db.execute('SELECT 1 FROM history WHERE id=?', (history_id,)).fetchone():
                raise ValidationError('Unknown history id')
            old = db.execute('SELECT * FROM history_evidence WHERE evidence_ref=?', (evidence_ref,)).fetchone()
            if old and (old['id'], old['settled'], old['pending']) == (history_id, settled_micros, pending_upper_micros):
                return
            self._unused_evidence(db, evidence_ref)
            previous = db.execute('SELECT * FROM history_evidence WHERE id=? ORDER BY seq DESC LIMIT 1', (history_id,)).fetchone()
            if previous and settled_micros < previous['settled']:
                raise ValidationError('Cannot erase previously settled spending')
            db.execute('INSERT INTO history_evidence(id,settled,pending,evidence_ref) VALUES(?,?,?,?)',
                       (history_id, settled_micros, pending_upper_micros, evidence_ref))

    def settle(self, key, charged_micros, evidence_ref):
        """No automatic release on HTTP error, timeout, cancellation or restart.

        A confirmed unbilled/released request is settled at zero with its own
        evidence. Overruns are retained and permanently block future admission.
        """
        _amount(charged_micros, 'settled charge')
        _text(evidence_ref, 'settlement evidence reference')
        with self._transaction() as db:
            request = db.execute('SELECT * FROM requests WHERE key=?', (key,)).fetchone()
            if not request:
                raise ValidationError('Unknown request key')
            old = db.execute('SELECT * FROM settlements WHERE key=?', (key,)).fetchone()
            if old:
                if (old['charged'], old['evidence_ref']) == (charged_micros, evidence_ref):
                    return
                raise ValidationError('Cannot rewrite a settlement')
            self._unused_evidence(db, evidence_ref)
            db.execute('INSERT INTO settlements VALUES(?,?,?)', (key, charged_micros, evidence_ref))

    def export(self, path):
        """Reviewable, secret-free snapshot; never an authorization token."""
        with open(path, 'x', encoding='utf-8') as stream:
            json.dump(self.status(), stream, ensure_ascii=False, indent=2)
            stream.write('\n')
