"""Local fault/concurrency fixtures; no scientific execution or paid services."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from value_lab.core import ValidationError, suite_digest, demo_suite, freeze
from value_lab.decision_store import DecisionStore
from value_lab.delivery import publish_bundle, read_bundle

ROOT = Path(__file__).resolve().parents[1]


def initialization():
    plan = {"study": "manufactured-recovery-fixture", "evidence_type": "synthetic"}
    return {"plan": plan, "plan_sha256": suite_digest(plan), "required_evidence": ["baseline", "plugin"],
            "dependencies": {"host": "fixture-v1", "plugin": "fixture-sha"}, "budget_micros": 1000000}


def start(ident="first", requirement="baseline", cost=100000):
    value = {"attempt_id": ident, "requirement": requirement, "mode": "local_execution", "operation": "fixture GET /result",
             "external_key": "external-" + ident, "max_cost_micros": cost}
    if ident == "retry":
        value.update(retry_of="first", reason="Explicit fixture reexecution")
    return value


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = DecisionStore(self.root / "decision.sqlite")
        self.store.append("initialize", initialization(), key="init", expected_sequence=0)

    def add(self, kind, payload, key=None, files=None):
        return self.store.append(kind, payload, key=key or kind + str(self.store.snapshot()["sequence"]),
                                 expected_sequence=self.store.snapshot()["sequence"], files=files)

    def collect(self, ident="first", requirement="baseline"):
        self.add("start", start(ident, requirement))
        return self.add("finish", {"attempt_id": ident, "status": "COLLECTED", "receipt": {"source": "fixture"}},
                        files={"raw": b'{"answer":"synthetic"}'})

    def interpret(self, ident="score1", parent=None, mode="evaluation", checks=None):
        return self.add("interpret", {"interpretation_id": ident, "mode": mode, "reason": "fixture rule revision",
            "attempt_ids": ["first"], "rules": {"version": ident}, "dependencies": {"host": "fixture-v1"},
            "pending_checks": checks or [], "parent": parent},
            files={"report": json.dumps({"status": "SIMULATION_ONLY", "rule": ident}).encode()})

    def test_reopen_replay_and_rescore_do_not_add_observations(self):
        self.collect()
        before = self.store.snapshot()
        for _ in range(3):
            self.assertEqual(DecisionStore(self.store.path).snapshot(), before)
        replay = self.store.append("initialize", initialization(), key="init", expected_sequence=0)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["sequence"], before["sequence"])
        self.interpret(checks=["human review"])
        result = self.interpret("score2", "score1", "rescore", ["human review"])
        self.assertEqual(result["collected_attempts"], 1)
        self.assertEqual(len(result["interpretations"]), 2)
        self.assertEqual(result["current_interpretation"], "score2")
        self.assertIsNone(result["scientific_sample_size"])
        self.assertEqual(result["missing_evidence"], ["plugin"])
        self.assertIn({"action": "COMPLETE_CHECK", "check": "human review"}, result["next_steps"])

    def test_unknown_remote_outcome_retains_key_and_reservation(self):
        self.add("start", start())
        self.add("identify", {"attempt_id": "first", "invocation_id": "invocation-fixture"})
        self.add("unknown", {"attempt_id": "first", "reason": "connection lost"})
        view = DecisionStore(self.store.path).snapshot()
        self.assertEqual(view["attempts"]["first"]["status"], "OUTCOME_UNKNOWN")
        self.assertEqual(view["costs"]["reserved_micros"], 100000)
        self.assertIsNone(view["costs"]["total_cost_micros"])
        self.assertEqual(view["next_steps"][0]["invocation_id"], "invocation-fixture")
        with self.assertRaisesRegex(ValidationError, "Reconcile"):
            self.add("start", start("retry"))
        self.assertEqual(self.store.snapshot(), view)

    def test_failed_retry_keeps_cost_and_failure(self):
        self.add("start", start())
        self.add("finish", {"attempt_id": "first", "status": "FAILED", "receipt": {"error": "fixture"}}, files={})
        result = self.add("start", start("retry"))
        self.assertEqual(result["costs"]["reserved_micros"], 200000)
        self.assertEqual(result["attempts"]["first"]["status"], "FAILED")
        result = self.add("settle", {"attempt_id": "first", "cost_micros": 150000, "basis": "fixture invoice"})
        self.assertEqual(result["costs"]["accounted_micros"], 250000)
        with self.assertRaises(ValidationError):
            self.add("settle", {"attempt_id": "first", "cost_micros": 0, "basis": "overwrite"})

    def test_budget_unknown_and_boolean_costs_fail_closed(self):
        with self.assertRaises(ValidationError):
            self.add("start", start(cost=True))
        self.add("start", start(cost=None))
        with self.assertRaisesRegex(ValidationError, "Unbounded"):
            self.add("start", start("other", "plugin"))
        self.add("settle", {"attempt_id": "first", "cost_micros": 1000001, "basis": "actual invoice exceeds estimate"})
        self.assertTrue(self.store.snapshot()["budget_exceeded"])
        with self.assertRaisesRegex(ValidationError, "budget"):
            self.add("start", start("other", "plugin", 0))

    def test_terminal_evidence_and_changed_key_cannot_be_overwritten(self):
        self.collect()
        before = self.store.snapshot()
        with self.assertRaises(ValidationError):
            self.add("finish", {"attempt_id": "first", "status": "FAILED", "receipt": {"error": "replacement"}}, files={})
        changed = initialization()
        changed["budget_micros"] += 1
        with self.assertRaisesRegex(ValidationError, "Idempotency"):
            self.store.append("initialize", changed, key="init", expected_sequence=0)
        self.assertEqual(self.store.snapshot(), before)

    def test_completed_submission_replay_deduplicates_even_with_stale_sequence(self):
        self.add("start", start())
        payload = {"attempt_id": "first", "status": "COLLECTED", "receipt": {"source": "fixture"}}
        first = self.store.append("finish", payload, key="collect", expected_sequence=2, files={"raw": b"one"})
        again = self.store.append("finish", payload, key="collect", expected_sequence=2, files={"raw": b"one"})
        self.assertEqual(first["sequence"], again["sequence"])
        self.assertEqual(again["collected_attempts"], 1)
        with self.assertRaises(ValidationError):
            self.store.append("finish", payload, key="collect", expected_sequence=2, files={"raw": b"two"})

    def test_new_evidence_requires_new_interpretation(self):
        self.collect()
        self.interpret()
        result = self.collect("second", "plugin")
        self.assertEqual(result["unreviewed_attempts"], ["second"])
        self.assertEqual(result["current_interpretation"], "score1")
        self.assertEqual(result["status"], "FOLLOW_UP_REQUIRED")

    def test_two_stale_writers_one_commits(self):
        def writer(ident, req):
            try:
                return self.store.append("start", start(ident, req), key=ident, expected_sequence=1)
            except ValidationError as exc:
                return str(exc)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: writer(*pair), [("one", "baseline"), ("two", "plugin")]))
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertTrue(any("Stale" in r for r in results if isinstance(r, str)))
        self.assertEqual(len(self.store.snapshot()["attempts"]), 1)

    def test_killed_during_evidence_commit_rolls_back_blobs_and_event(self):
        self.add("start", start())
        script = '''
import os, sys
import value_lab.decision_store as m
m.recovery_view = lambda state: os._exit(73)
m.DecisionStore(sys.argv[1]).append("finish", {"attempt_id":"first", "status":"COLLECTED", "receipt":{"source":"fixture"}}, key="collect", expected_sequence=2, files={"raw":b"x" * (4 * 1024 * 1024)})
'''
        child = subprocess.run([sys.executable, "-c", script, str(self.store.path)], cwd=ROOT, capture_output=True)
        self.assertEqual(child.returncode, 73, child.stderr)
        view = self.store.snapshot()
        self.assertEqual(view["sequence"], 2)
        self.assertEqual(view["collected_attempts"], 0)
        with closing(sqlite3.connect(self.store.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM blobs").fetchone()[0], 0)
        result = self.store.append("finish", {"attempt_id": "first", "status": "COLLECTED", "receipt": {"source": "fixture"}},
                                   key="collect", expected_sequence=2, files={"raw": b"retained-on-retry"})
        self.assertEqual(result["collected_attempts"], 1)

    def test_killed_after_dispatch_record_recovers_original_attempt(self):
        script = '''
import json, os, sys
from value_lab.decision_store import DecisionStore
DecisionStore(sys.argv[1]).append("start", json.loads(sys.argv[2]), key="dispatch", expected_sequence=1)
os._exit(74)
'''
        child = subprocess.run([sys.executable, "-c", script, str(self.store.path), json.dumps(start())], cwd=ROOT, capture_output=True)
        self.assertEqual(child.returncode, 74, child.stderr)
        self.assertEqual(self.store.snapshot()["attempts"]["first"]["status"], "PENDING")
        self.assertEqual(self.store.snapshot()["next_steps"][0]["external_key"], "external-first")
        replay = self.store.append("start", start(), key="dispatch", expected_sequence=1)
        self.assertTrue(replay["replayed"])
        self.assertEqual(len(replay["attempts"]), 1)

    def test_tampered_blob_and_event_are_rejected(self):
        self.collect()
        backup = self.root / "saved.sqlite"
        shutil.copyfile(self.store.path, backup)
        with closing(sqlite3.connect(self.store.path)) as db:
            db.execute("UPDATE blobs SET data=?", (b"tampered",))
            db.commit()
        with self.assertRaisesRegex(ValidationError, "artifact"):
            self.store.snapshot()
        shutil.copyfile(backup, self.store.path)
        with closing(sqlite3.connect(self.store.path)) as db:
            db.execute("UPDATE events SET digest='bad' WHERE seq=1")
            db.commit()
        with self.assertRaisesRegex(ValidationError, "history"):
            self.store.snapshot()

    def test_relocation_and_export_preserve_raw_bytes_and_history(self):
        self.collect()
        expected = self.store.snapshot()
        relocated = self.root / "relocated.sqlite"
        shutil.copyfile(self.store.path, relocated)
        self.assertEqual(DecisionStore(relocated).snapshot(), expected)
        output = self.root / "export"
        result = self.store.export(output)
        self.assertEqual(result["status"], "COMMITTED")
        manifest = read_bundle(output)
        self.assertIn("events.json", manifest["files"])
        self.assertEqual(json.loads((output / "decision.json").read_bytes()), expected)
        self.assertEqual(self.store.export(output), result)
        self.assertEqual(next(output.glob("*.blob")).read_bytes(), b'{"answer":"synthetic"}')

    def test_cli_append_show_and_export(self):
        event = self.root / "event.json"
        event.write_text(json.dumps({"kind": "start", "payload": start(), "key": "cli", "expected_sequence": 1}))
        command = [sys.executable, "-m", "value_lab.decision_store", "--store", str(self.store.path)]
        for args in (["append", "--event", str(event)], ["show"], ["export", "--output", str(self.root / "cli-export")]):
            result = subprocess.run(command + args, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsInstance(json.loads(result.stdout), dict)

    def test_init_binds_existing_study_and_preserves_full_denominator(self):
        suite = demo_suite()
        lock = freeze(suite, self.root / "lock.json")
        other = DecisionStore(self.root / "study.sqlite")
        view = other.initialize_study(suite, lock, {"host": None}, 1000000, key="init")
        self.assertEqual(view["plan"]["suite"], suite)
        self.assertEqual(view["plan"]["lock"], lock)
        self.assertEqual(len(view["missing_evidence"]), lock["expected_runs"])
        self.assertIn({"action": "VERIFY_DEPENDENCY_IDENTITY", "dependency": "host"}, view["next_steps"])
        lock["suite_sha256"] = "0" * 64
        with self.assertRaises(ValidationError):
            DecisionStore(self.root / "bad.sqlite").initialize_study(suite, lock, {}, 0, key="bad")
        self.assertFalse((self.root / "bad.sqlite").exists())

    def test_late_failure_is_not_hidden_by_old_interpretation(self):
        self.collect()
        self.interpret()
        self.add("start", start("retry"))
        view = self.add("finish", {"attempt_id": "retry", "status": "FAILED", "receipt": {"error": "new failure"}}, files={})
        self.assertEqual(view["unreviewed_attempts"], ["retry"])
        self.assertEqual(view["current_interpretation"], "score1")

    def test_incomplete_evidence_and_forged_digests_cannot_commit(self):
        self.add("start", start())
        before = self.store.snapshot()
        for artifacts in ({}, {"raw": "0" * 64}, ["invalid"]):
            with self.assertRaises(ValidationError):
                self.add("finish", {"attempt_id": "first", "status": "COLLECTED", "receipt": {"source": "fixture"}, "artifacts": artifacts})
        self.assertEqual(self.store.snapshot(), before)

    def test_request_schema_and_runtime_reject_extra_fields(self):
        import jsonschema
        schema = json.loads((ROOT / "schemas/decision-event.schema.json").read_bytes())
        jsonschema.Draft202012Validator.check_schema(schema)
        request = {"kind": "start", "payload": start(), "key": "schema", "expected_sequence": 1}
        jsonschema.validate(request, schema)
        request["payload"]["status"] = "COLLECTED"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(request, schema)
        with self.assertRaises(ValidationError):
            self.store.append(**request)

    def test_same_key_concurrent_writers_replay_one_event(self):
        def submit(_):
            return self.store.append("start", start(), key="same", expected_sequence=1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, range(2)))
        self.assertEqual(sorted(r["replayed"] for r in results), [False, True])
        self.assertEqual(self.store.snapshot()["sequence"], 2)

    def test_interpretation_cannot_erase_unknown_dependency_by_omission(self):
        other = DecisionStore(self.root / "unknown.sqlite")
        initial = initialization()
        initial["dependencies"]["model"] = None
        other.append("initialize", initial, key="init", expected_sequence=0)
        self.store = other
        self.collect()
        result = self.interpret()
        self.assertIn({"action": "VERIFY_DEPENDENCY_IDENTITY", "dependency": "model"}, result["next_steps"])


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / "report"
        self.files = {"data.json": b'{"result":"fixture"}', "REPORT.md": b"fixture"}

    def test_killed_report_write_is_not_a_result_and_resume_keeps_attempt(self):
        script = '''
import os, sys
import value_lab.delivery as d
original = d._write
def crash(path, data):
    original(path, data)
    os._exit(75)
d._write = crash
d.publish_bundle(sys.argv[1], {"data.json": b'{"result":"fixture"}', "REPORT.md":b"fixture"})
'''
        result = subprocess.run([sys.executable, "-c", script, str(self.output)], cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertFalse(self.output.exists())
        pending = list(self.root.iterdir())
        self.assertEqual(len(pending), 1)
        self.assertEqual(publish_bundle(self.output, self.files)["status"], "INCOMPLETE")
        with self.assertRaises(ValidationError):
            read_bundle(pending[0])
        self.assertEqual(publish_bundle(self.output, self.files, resume=True)["status"], "COMMITTED")
        self.assertTrue(pending[0].exists())
        self.assertEqual((pending[0] / "data.json").read_bytes(), self.files["data.json"])
        self.assertEqual(read_bundle(self.output)["format"], "pvl-delivery-1")

    def test_same_request_replays_changed_or_damaged_result_rejected(self):
        publish_bundle(self.output, self.files)
        self.assertEqual(publish_bundle(self.output, self.files)["status"], "COMMITTED")
        with self.assertRaises(ValidationError):
            publish_bundle(self.output, {"data.json": b"different"})
        (self.output / "REPORT.md").write_text("tampered")
        with self.assertRaises(ValidationError):
            publish_bundle(self.output, self.files)

    def test_failure_after_marker_before_rename_requires_explicit_resume(self):
        with patch.object(Path, "rename", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                publish_bundle(self.output, self.files)
        self.assertFalse(self.output.exists())
        self.assertEqual(publish_bundle(self.output, self.files)["status"], "INCOMPLETE")
        self.assertEqual(publish_bundle(self.output, self.files, resume=True)["status"], "COMMITTED")

    def test_legacy_directory_and_escaping_members_rejected(self):
        self.output.mkdir()
        (self.output / "data.json").write_bytes(self.files["data.json"])
        with self.assertRaises(ValidationError):
            publish_bundle(self.output, self.files, resume=True)
        with self.assertRaises(ValidationError):
            publish_bundle(self.root / "new", {"../escape": b"bad"})


if __name__ == "__main__":
    unittest.main()

