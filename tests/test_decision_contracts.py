"""Strict recovery action boundaries and import faults; all remote receipts are fixtures."""
from contextlib import closing
from contextlib import redirect_stdout
from copy import deepcopy
import io
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from value_lab.core import ValidationError, suite_digest
from value_lab.decision_store import DecisionStore, LEGACY_FORMAT
from tests import test_decision_recovery as fixtures

ROOT, initialization, start = fixtures.ROOT, fixtures.initialization, fixtures.start


class DecisionContractTests(unittest.TestCase):
    setUp = fixtures.RecoveryTests.setUp
    add = fixtures.RecoveryTests.add
    collect = fixtures.RecoveryTests.collect
    interpret = fixtures.RecoveryTests.interpret

    def external(self):
        payload = start()
        payload["mode"] = "tool_execution"
        return self.add("start", payload)

    def reconcile(self, status, **overrides):
        attempt = self.store.snapshot()["attempts"]["first"]
        payload = {"attempt_id": "first", "operation": attempt["operation"], "external_key": attempt["external_key"],
                   "invocation_id": attempt["invocation_id"], "remote_status": status, "receipt": {"source": "manufactured provider status"}}
        payload.update(overrides)
        return self.add("reconcile", payload)

    def test_rescore_cannot_exist_without_parent(self):
        self.collect()
        before = self.store.snapshot()
        with self.assertRaisesRegex(ValidationError, "prior interpretation"):
            self.interpret(mode="rescore")
        self.assertEqual(self.store.snapshot(), before)

    def test_rescore_cannot_add_new_observation(self):
        self.collect()
        self.interpret()
        self.collect("second", "plugin")
        parent = self.store.snapshot()["interpretations"][-1]
        payload = {k: parent[k] for k in ("mode", "reason", "attempt_ids", "rules", "dependencies", "pending_checks")}
        payload.update(interpretation_id="score2", mode="rescore", parent="score1",
                       rules={"version": "new"}, attempt_ids=["first", "second"])
        with self.assertRaisesRegex(ValidationError, "same raw observations"):
            self.add("interpret", payload, files={"report": b"new"})
        self.assertEqual(len(self.store.snapshot()["interpretations"]), 1)

    def test_rescore_cannot_remove_failed_observations(self):
        self.collect()
        self.add("start", start("retry"))
        self.add("finish", {"attempt_id": "retry", "status": "FAILED", "receipt": {"source": "fixture"}}, files={})
        payload = {"interpretation_id": "score1", "mode": "evaluation", "reason": "Include failure",
                   "attempt_ids": ["first", "retry"], "rules": {"version": "v1"},
                   "dependencies": {}, "pending_checks": [], "parent": None}
        self.add("interpret", payload, files={"report": b"old"})
        payload.update(interpretation_id="score2", mode="rescore", rules={"version": "v2"},
                       parent="score1", attempt_ids=["first"])
        with self.assertRaisesRegex(ValidationError, "same raw observations"):
            self.add("interpret", payload, files={"report": b"new"})

    def test_unchanged_rules_are_not_new_rescore(self):
        self.collect()
        self.interpret()
        prior = self.store.snapshot()["interpretations"][-1]
        payload = {k: prior[k] for k in ("reason", "attempt_ids", "rules", "dependencies", "pending_checks")}
        payload.update(interpretation_id="copy", mode="rescore", parent="score1")
        with self.assertRaisesRegex(ValidationError, "replay"):
            self.add("interpret", payload, files={"report": b"same rules"})

    def test_valid_rescore_binds_same_bytes_and_keeps_historical_report(self):
        self.collect()
        first = self.interpret()["interpretations"][0]
        result = self.interpret("score2", "score1", "rescore")
        second = result["interpretations"][1]
        self.assertEqual(first["observations_sha256"], second["observations_sha256"])
        self.assertNotEqual(first["rules_sha256"], second["rules_sha256"])
        self.assertNotEqual(first["result_sha256"], second["result_sha256"])
        self.assertEqual(result["interpretations"][0], first)
        self.assertEqual(result["collected_attempts"], 1)
        self.assertEqual(result["costs"]["reserved_micros"], 100000)

    def test_retry_requires_latest_predecessor_and_reason(self):
        self.collect()
        payload = start("second")
        with self.assertRaisesRegex(ValidationError, "latest terminal"):
            self.add("start", payload)
        payload.update(retry_of="first", reason="Explicit rerun under original frozen plan")
        self.add("start", payload)
        self.add("finish", {"attempt_id": "second", "status": "FAILED", "receipt": {"source": "fixture"}}, files={})
        stale = start("third")
        stale.update(retry_of="first", reason="Wrong predecessor")
        with self.assertRaisesRegex(ValidationError, "latest terminal"):
            self.add("start", stale)
        stale["retry_of"] = "second"
        result = self.add("start", stale)
        self.assertEqual(result["observation_groups"]["baseline"], ["first", "second", "third"])
        self.assertEqual(result["costs"]["reserved_micros"], 300000)
        self.assertEqual(result["attempts"]["second"]["status"], "FAILED")

    def test_cancel_request_and_not_found_do_not_close_or_refund(self):
        self.external()
        self.add("cancel_request", {"attempt_id": "first", "reason": "User requested cancellation"})
        self.reconcile("not_found")
        view = self.store.snapshot()
        self.assertTrue(view["attempts"]["first"]["cancellation_requested"])
        self.assertEqual(view["attempts"]["first"]["status"], "OUTCOME_UNKNOWN")
        self.assertEqual(view["costs"]["reserved_micros"], 100000)
        for terminal in ("CANCELLED", "FAILED", "COLLECTED"):
            with self.assertRaisesRegex(ValidationError, "terminal reconciliation"):
                self.add("finish", {"attempt_id": "first", "status": terminal, "receipt": {"message": "not found"}},
                         files={"raw": b"not a terminal provider result"})
        with self.assertRaisesRegex(ValidationError, "Reconcile"):
            self.add("start", start("retry"))
        self.assertEqual(self.store.snapshot(), view)

    def test_completed_remote_receipt_is_not_collected_evidence(self):
        self.external()
        self.add("identify", {"attempt_id": "first", "invocation_id": "fixture-call"})
        view = self.reconcile("completed")
        self.assertEqual(view["attempts"]["first"]["status"], "RESULT_AVAILABLE")
        self.assertEqual(view["collected_attempts"], 0)
        self.assertIn("baseline", view["missing_evidence"])
        self.assertEqual(view["next_steps"][0]["action"], "COLLECT_CONFIRMED_RESULT")
        with self.assertRaises(ValidationError):
            self.add("start", start("retry"))
        view = self.add("finish", {"attempt_id": "first", "status": "COLLECTED", "receipt": {"source": "fixture"}},
                        files={"raw": b"actual fixture bytes"})
        self.assertEqual(view["collected_attempts"], 1)
        self.assertIsNone(view["costs"]["total_cost_micros"])

    def test_reconciliation_cannot_attach_wrong_call_or_conflicting_terminal(self):
        self.external()
        for fields in ({"external_key": "other"}, {"operation": "different"}, {"invocation_id": "not identified"}):
            with self.assertRaisesRegex(ValidationError, "original operation"):
                self.reconcile("completed", **fields)
        self.reconcile("completed")
        with self.assertRaisesRegex(ValidationError, "Conflicting terminal"):
            self.reconcile("cancelled")

    def test_confirmed_cancellation_retains_cost_until_explicit_settlement(self):
        self.external()
        self.reconcile("cancelled")
        view = self.add("finish", {"attempt_id": "first", "status": "CANCELLED", "receipt": {"source": "confirmed fixture"}}, files={})
        self.assertEqual(view["costs"]["reserved_micros"], 100000)
        view = self.add("settle", {"attempt_id": "first", "cost_micros": 20000, "basis": "Final fixture invoice"})
        self.assertEqual(view["costs"]["total_cost_micros"], 20000)
        self.assertEqual(view["attempts"]["first"]["status"], "CANCELLED")

    def test_later_omission_does_not_drop_dependency_from_previous_revision(self):
        self.collect()
        self.interpret()
        prior = self.store.snapshot()["interpretations"][-1]
        payload = {k: prior[k] for k in ("reason", "attempt_ids", "rules", "pending_checks")}
        payload.update(interpretation_id="score2", mode="rescore", parent="score1",
                       rules={"version": "v2"}, dependencies={"new_tool": None})
        self.add("interpret", payload, files={"report": b"second"})
        result = self.interpret("score3", "score2", "rescore")
        self.assertIn({"action": "VERIFY_DEPENDENCY_IDENTITY", "dependency": "new_tool"}, result["next_steps"])

    def test_checkpoint_detects_truncated_tail_and_accepts_continuation(self):
        self.collect()
        checkpoint = self.store.snapshot()["checkpoint"]
        self.interpret()
        self.assertTrue(self.store.snapshot(checkpoint=checkpoint)["checkpoint_verified"])
        with closing(sqlite3.connect(self.store.path)) as db:
            db.execute("DELETE FROM events WHERE seq >= ?", (checkpoint["sequence"],))
            db.commit()
        with self.assertRaisesRegex(ValidationError, "checkpoint"):
            self.store.snapshot(checkpoint=checkpoint)

    def test_restore_exact_history_and_replay_keys_without_new_observation(self):
        self.collect()
        self.interpret()
        before = self.store.snapshot()
        self.store.export(self.root / "bundle")
        other = DecisionStore(self.root / "restored.sqlite")
        restored = other.restore(self.root / "bundle", checkpoint=before["checkpoint"])
        self.assertEqual(restored["attempts"], before["attempts"])
        self.assertEqual(restored["interpretations"], before["interpretations"])
        self.assertEqual(restored["sequence"], before["sequence"])
        self.assertEqual(restored["costs"], before["costs"])
        self.assertTrue(restored["checkpoint_verified"])
        self.assertTrue(other.append("initialize", initialization(), key="init", expected_sequence=0)["replayed"])
        self.assertTrue(other.restore(self.root / "bundle")["replayed"])
        with closing(sqlite3.connect(self.store.path)) as left, closing(sqlite3.connect(other.path)) as right:
            self.assertEqual(list(left.execute("SELECT * FROM events ORDER BY seq")), list(right.execute("SELECT * FROM events ORDER BY seq")))

    def test_restore_does_not_reset_later_cost_or_unknown_attempt(self):
        self.collect()
        self.store.export(self.root / "bundle")
        self.add("settle", {"attempt_id": "first", "cost_micros": 40000, "basis": "Final invoice"})
        self.add("start", start("retry"))
        before = self.store.snapshot()
        result = self.store.restore(self.root / "bundle")
        self.assertTrue(result["replayed"])
        self.assertEqual(result["sequence"], before["sequence"])
        self.assertEqual(result["costs"]["accounted_micros"], 140000)

    def test_old_bundle_rejected_by_newer_checkpoint_before_target_created(self):
        self.collect()
        self.store.export(self.root / "old")
        checkpoint = self.interpret()
        checkpoint = self.store.snapshot()["checkpoint"]
        other = DecisionStore(self.root / "target.sqlite")
        with self.assertRaisesRegex(ValidationError, "predates"):
            other.restore(self.root / "old", checkpoint=checkpoint)
        self.assertFalse(other.path.exists())

    def test_corrupt_bundle_rejected_without_modifying_target(self):
        self.collect()
        self.store.export(self.root / "bundle")
        before = self.store.snapshot()
        (self.root / "bundle/events.json").write_text("[]")
        with self.assertRaises(ValidationError):
            self.store.restore(self.root / "bundle")
        self.assertEqual(self.store.snapshot(), before)

    def test_interrupted_restore_rolls_back_and_same_bundle_recovers(self):
        self.collect()
        self.store.export(self.root / "bundle")
        target = self.root / "restored.sqlite"
        code = '''
import os, sys
import value_lab.decision_store as m
m.recovery_view = lambda state: os._exit(76)
m.DecisionStore(sys.argv[1]).restore(sys.argv[2])
'''
        result = subprocess.run([sys.executable, "-c", code, str(target), str(self.root / "bundle")], cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 76, result.stderr)
        restored = DecisionStore(target).restore(self.root / "bundle")
        self.assertEqual(restored["collected_attempts"], 1)
        self.assertEqual(restored["sequence"], self.store.snapshot()["sequence"])
        self.assertFalse(restored["replayed"])

    def test_restore_conflicting_existing_history_is_refused(self):
        self.collect()
        self.store.export(self.root / "bundle")
        other = DecisionStore(self.root / "conflict.sqlite")
        initial = initialization()
        initial["budget_micros"] += 1
        other.append("initialize", initial, key="other", expected_sequence=0)
        before = other.snapshot()
        with self.assertRaises(ValidationError):
            other.restore(self.root / "bundle")
        self.assertEqual(other.snapshot(), before)

    def test_legacy_v1_events_remain_readable_without_rewriting(self):
        # Manufactured v1 records intentionally include the old permissive first
        # rescore and externally collected result without reconciliation.
        raw = b"legacy fixture bytes"
        digest = hashlib.sha256(raw).hexdigest()
        init, old_start = initialization(), start()
        old_start["mode"] = "tool_execution"
        payloads = [
            ("initialize", init),
            ("start", old_start),
            ("finish", {"attempt_id": "first", "status": "COLLECTED", "receipt": {"source": "v1 fixture"}, "artifacts": {"raw": digest}}),
            ("interpret", {"interpretation_id": "old", "mode": "rescore", "reason": "v1 permitted this",
                "attempt_ids": ["first"], "rules": {"version": "v1"}, "dependencies": {}, "pending_checks": [],
                "artifacts": {"report": digest}, "parent": None}),
        ]
        path = self.root / "legacy.sqlite"
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE events(seq INTEGER PRIMARY KEY, request_key TEXT UNIQUE, event TEXT, digest TEXT)")
            db.execute("CREATE TABLE blobs(digest TEXT PRIMARY KEY, data BLOB)")
            db.execute("INSERT INTO blobs VALUES(?,?)", (digest, raw))
            parent = None
            for index, (kind, payload) in enumerate(payloads, 1):
                event = {"format": LEGACY_FORMAT, "request_key": str(index), "parent": parent, "kind": kind, "payload": payload}
                parent = suite_digest(event)
                db.execute("INSERT INTO events VALUES(?,?,?,?)", (index, str(index), json.dumps(event), parent))
            db.commit()
        before = path.read_bytes()
        legacy = DecisionStore(path)
        snapshot = legacy.snapshot()
        self.assertEqual(snapshot["interpretations"][0]["mode"], "rescore")
        self.assertNotIn("observations_sha256", snapshot["interpretations"][0])
        self.assertEqual(path.read_bytes(), before)
        legacy.export(self.root / "legacy-bundle")
        restored = DecisionStore(self.root / "legacy-restored.sqlite").restore(self.root / "legacy-bundle")
        self.assertEqual(restored["interpretations"], snapshot["interpretations"])
        self.assertEqual(restored["checkpoint"], snapshot["checkpoint"])
        # New writes onto the old history use v2 constraints.
        with self.assertRaisesRegex(ValidationError, "latest terminal"):
            legacy.append("start", start("next"), key="new", expected_sequence=4)

    def test_restore_cli_and_checkpoint_show(self):
        self.collect()
        self.store.export(self.root / "bundle")
        target = self.root / "cli.sqlite"
        command = [sys.executable, "-m", "value_lab.decision_store", "--store", str(target)]
        checkpoint = self.root / "bundle/checkpoint.json"
        for args in (["restore", "--bundle", str(self.root / "bundle"), "--checkpoint", str(checkpoint)],
                     ["show", "--checkpoint", str(checkpoint)]):
            result = subprocess.run(command + args, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["checkpoint_verified"])

    def interrupted_revision(self, stop_after):
        from tests.test_evidence_dependencies import fixture
        card, graph, inventory = fixture(self.root)
        for name, value in (("card", card), ("graph", graph), ("inventory", inventory)):
            (self.root / (name + ".json")).write_text(json.dumps(value), encoding="utf-8")
        args = ["rescore", "--card", str(self.root / "card.json"), "--graph", str(self.root / "graph.json"),
                "--inventory", str(self.root / "inventory.json"), "--artifacts", str(self.root),
                "--output", str(self.root / "revision")]
        code = '''
import os, sys
import value_lab.delivery as d
from value_lab.evidence_dependencies import main
write = d._write
def interrupted(path, data):
    write(path, data)
    if path.name == sys.argv[1]:
        os._exit(77)
d._write = interrupted
main(sys.argv[2:])
'''
        result = subprocess.run([sys.executable, "-c", code, stop_after, *args], cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 77, result.stderr)
        self.assertFalse((self.root / "revision").exists())
        return args

    def test_report_resume_uses_saved_score_without_running_scorer(self):
        from value_lab.evidence_dependencies import main
        args = self.interrupted_revision("revision.json")
        stage = next(self.root.glob(".revision.pvl-*"))
        original = (stage / "revision.json").read_bytes()
        with patch("value_lab.evidence_dependencies.recheck", side_effect=AssertionError("Scorer must not execute")):
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args), 3)
            self.assertFalse(json.loads(output.getvalue())["scoring_executed"])
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args + ["--resume"]), 0)
            self.assertTrue(json.loads(output.getvalue())["recovered_from_retained_result"])
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
        self.assertTrue(stage.is_dir())
        self.assertEqual((self.root / "revision/revision.json").read_bytes(), original)

    def test_incomplete_score_cannot_be_silently_regenerated_by_resume(self):
        from value_lab.evidence_dependencies import main
        args = self.interrupted_revision("REQUEST.json")
        with patch("value_lab.evidence_dependencies.recheck", side_effect=AssertionError("Scorer must not execute")):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 3)
            with self.assertRaises(SystemExit) as failure:
                main(args + ["--resume"])
            self.assertEqual(failure.exception.code, 2)
        self.assertFalse((self.root / "revision").exists())


if __name__ == "__main__":
    unittest.main()

