"""Synthetic engineering/fault tests; never human or native-host acceptance."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from value_lab.collaboration import capture_inputs, dispatch
from value_lab.core import ValidationError, demo_suite
from value_lab.decision_store import DecisionStore


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.who = {"id": "agent-a", "kind": "agent"}
        self.sequence = 0
        self.counter = 0
        self.material = {"suite": demo_suite(), "records": [], "lock": None, "cost_ledger": None}
        self.call("open", {"inputs": self.material})

    def call(self, action, arguments=None, **kwargs):
        self.counter += 1
        opts = {"who": self.who, "key": "request-" + str(self.counter), "expected_sequence": self.sequence}
        opts.update(kwargs)
        result = dispatch(self.root, "study", action, arguments, **opts)
        if "sequence" in result:
            self.sequence = result["sequence"]
        return result

    def execute(self):
        return self.call("execute", {"attempt_id": "a1", "reason": "Synthetic engineering evaluation"})

    def review(self, result, verdict="request_changes"):
        return self.call("review", {"review_id": "review-" + str(self.counter), "attempt_id": "a1",
            "result_sha256": result["result_sha256"], "verdict": verdict, "notes": "Fixture review only"})

    def test_full_correction_invalidates_review_and_preserves_evidence(self):
        first = self.execute()
        reviewed = self.review(first)
        corrected = deepcopy(self.material)
        corrected["suite"]["id"] += "-revised"
        changed = self.call("correct", {"review_id": reviewed["status"]["latest_review"]["id"],
                                       "inputs": corrected, "reason": "Change fixture label"})
        self.assertEqual(changed["status"]["stage"], "READY_TO_EXECUTE")
        self.assertIsNone(changed["status"]["latest_review"])
        self.assertIsNone(changed["result"])
        second = self.call("execute", {"attempt_id": "a2", "reason": "Explicit post-review reevaluation"})
        self.assertTrue(second["status"]["post_review_revision"])
        self.assertEqual(second["result"]["new_observations"], 0)
        state = DecisionStore(self.root / "study.sqlite").snapshot()
        self.assertEqual(len(state["attempts"]), 2)
        self.assertEqual(state["attempts"]["a1"]["artifacts"]["result"], first["result_sha256"])

    def test_replayed_execute_never_executes_twice(self):
        args = {"attempt_id": "a1", "reason": "Stable execution request"}
        seq = self.sequence
        self.call("execute", args, key="execute", expected_sequence=seq)
        with patch("value_lab.collaboration.evaluate", side_effect=AssertionError("Must not run")):
            repeated = self.call("execute", args, key="execute", expected_sequence=seq)
        self.assertTrue(repeated["replayed"])
        self.assertFalse(repeated["execution_performed"])
        with self.assertRaises(ValidationError):
            self.call("execute", {**args, "reason": "Changed"}, key="execute", expected_sequence=seq)

    def test_stale_writer_wrong_owner_and_unbound_review_rejected(self):
        first = self.execute()
        for options in ({"expected_sequence": 1}, {"who": {"id": "other", "kind": "agent"}}):
            with self.assertRaises(ValidationError):
                self.call("handoff", {"handoff_id": "h", "recipient": {"id": "b", "kind": "agent"},
                                      "note": "Take over"}, **options)
        with self.assertRaises(ValidationError):
            self.review({**first, "result_sha256": "0" * 64})

    def test_handoff_requires_recipient_and_freezes_owner(self):
        first = self.execute()
        self.review(first, "accept")
        human = {"id": "human-fixture", "kind": "human"}
        self.call("handoff", {"handoff_id": "h1", "recipient": human, "note": "Synthetic identity fixture"})
        with self.assertRaises(ValidationError):
            self.review(first)
        with self.assertRaises(ValidationError):
            self.call("receive", {"handoff_id": "h1"})
        self.who = human
        self.call("receive", {"handoff_id": "h1"})
        accepted = self.review(first, "accept")
        self.assertEqual(accepted["status"]["stage"], "ACCEPTED_AS_DECLARED")
        self.assertFalse(accepted["status"]["human_acceptance_verified"])
        self.assertFalse(accepted["status"]["human_identity_authenticated"])
        self.assertFalse(accepted["status"]["live_host_accepted"])

    def test_agent_acceptance_requires_human_review(self):
        result = self.review(self.execute(), "accept")
        self.assertEqual(result["status"]["stage"], "AWAITING_HUMAN_REVIEW")

    def test_crash_remains_pending_and_retry_needs_explicit_resolution(self):
        args = {"attempt_id": "a1", "reason": "Crash fault fixture"}
        with patch("value_lab.collaboration.evaluate", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.call("execute", args, key="crash")
        self.call("status")
        repeated = self.call("execute", args, key="crash", expected_sequence=1)
        self.assertEqual(repeated["status"]["stage"], "EXECUTION_UNRESOLVED")
        with self.assertRaises(ValidationError):
            self.call("execute", {"attempt_id": "a2", "reason": "Unsafe retry"})
        self.call("resolve", {"attempt_id": "a1", "reason": "Confirmed old process stopped; no retained result"})
        result = self.call("execute", {"attempt_id": "a2", "reason": "Explicit retry"})
        self.assertTrue(result["execution_performed"])
        state = DecisionStore(self.root / "study.sqlite").snapshot()
        self.assertEqual(state["attempts"]["a1"]["receipt"]["execution_outcome"], "UNKNOWN")

    def test_failure_is_retained_and_cannot_be_accepted(self):
        with patch("value_lab.collaboration.evaluate", side_effect=ValueError("fixture failure")):
            result = self.execute()
        self.assertEqual(result["status"]["stage"], "EXECUTION_FAILED")
        self.assertEqual(result["result"]["error_type"], "ValueError")
        with self.assertRaises(ValidationError):
            self.review(result, "accept")
        self.review(result)

    def test_export_restore_requires_external_checkpoint_and_does_not_execute(self):
        first = self.execute()
        self.call("handoff", {"handoff_id": "h", "recipient": {"id": "next-agent", "kind": "agent"}, "note": "Continue"})
        bundle = self.call("export", {"directory": "bundle"})
        with self.assertRaises(ValidationError):
            dispatch(self.root, "restored", "restore", {"directory": "bundle", "checkpoint": None}, who=self.who)
        with patch("value_lab.collaboration.evaluate", side_effect=AssertionError("Restore must not execute")):
            restored = dispatch(self.root, "restored", "restore",
                {"directory": "bundle", "checkpoint": bundle["checkpoint"]}, who=self.who)
        self.assertEqual(restored["result_sha256"], first["result_sha256"])
        self.assertEqual(restored["status"]["stage"], "HANDOFF_PENDING")
        self.assertFalse(restored["execution_performed"])
        self.assertTrue((self.root / "bundle/HANDOFF.md").is_file())
        wrong = {**bundle["checkpoint"], "head_sha256": "0" * 64}
        with self.assertRaises(ValidationError):
            dispatch(self.root, "bad", "restore", {"directory": "bundle", "checkpoint": wrong}, who=self.who)
        with self.assertRaises(ValidationError):
            dispatch(self.root, "restored", "export", {"directory": "../escape"}, who=self.who)

    def test_raw_legacy_event_cannot_bypass_collaboration(self):
        with self.assertRaises(ValidationError):
            DecisionStore(self.root / "study.sqlite").append("start", {}, key="bypass", expected_sequence=1)

    def test_stale_review_and_unchanged_correction_rejected(self):
        result = self.execute()
        reviewed = self.review(result)
        review_id = reviewed["status"]["latest_review"]["id"]
        with self.assertRaises(ValidationError):
            self.call("correct", {"review_id": review_id, "inputs": self.material, "reason": "No change"})
        changed = deepcopy(self.material)
        changed["suite"]["id"] += "-changed"
        self.call("correct", {"review_id": review_id, "inputs": changed, "reason": "Fixture"})
        with self.assertRaises(ValidationError):
            self.review(result)

    def test_cli_reopens_in_fresh_process(self):
        result = self.execute()
        request = self.root / "request.json"
        request.write_text(json.dumps({"task_id": "study", "action": "status"}), encoding="utf-8")
        process = subprocess.run([sys.executable, "-B", "-m", "value_lab.collaboration",
            "--root", str(self.root), "--actor", "agent-a", "--request", str(request)],
            capture_output=True, text=True, timeout=30, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["result_sha256"], result["result_sha256"])

    def test_paths_and_extra_actor_arguments_rejected(self):
        for ident in ("../escape", "C:escape", "x/y"):
            with self.assertRaises(ValidationError):
                dispatch(self.root, ident, "status", who=self.who)
        with self.assertRaises(ValidationError):
            self.call("status", {"actor": {"kind": "human", "id": "spoof"}})

    def test_concurrent_writers_only_one_commits(self):
        seq = self.sequence
        def writer(ident):
            try:
                return dispatch(self.root, "study", "handoff",
                    {"handoff_id": ident, "recipient": {"id": ident, "kind": "agent"}, "note": "Concurrency fixture"},
                    who=self.who, key=ident, expected_sequence=seq)["sequence"]
            except ValidationError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(writer, ["recipient-a", "recipient-b"]))
        self.assertEqual(sum(x is not None for x in outcomes), 1)

    def test_capture_retains_bytes_and_missing_files_without_forging_hash(self):
        path = self.root / "answer.json"
        path.write_bytes(b'{"wrong": true}')
        records = [{"artifacts": {"answer": {"path": "answer.json", "sha256": "0" * 64},
                                  "absent": {"path": "absent.json", "sha256": "1" * 64}}}]
        captured = capture_inputs(demo_suite(), records, artifact_root=self.root)
        self.assertEqual(set(captured["artifact_files"]), {"answer.json"})
        self.assertEqual(captured["records"][0]["artifacts"]["answer"]["sha256"], "0" * 64)
        with self.assertRaises(ValidationError):
            capture_inputs(demo_suite(), [{"artifacts": {"bad": {"path": "../secret"}}}], artifact_root=self.root)

    def test_malformed_retained_artifact_paths_rejected_before_execution(self):
        for name, encoded in (("../secret", "eA=="), ("okay", "not base64")):
            material = {**self.material, "artifact_files": {name: encoded}}
            with self.assertRaises(ValidationError):
                dispatch(self.root, "bad", "open", {"inputs": material},
                         who=self.who, key="bad", expected_sequence=0)

    def test_json_field_failure_is_stable_across_canonical_persistence(self):
        from value_lab.artifacts import _builtin
        path = self.root / "fields.json"
        path.write_text('{"a": 0, "z": 0}', encoding="utf-8")
        spec = {"kind": "json_fields", "expected": {"z": 1, "a": 1}}
        self.assertEqual(_builtin(path, spec), _builtin(path, json.loads(json.dumps(spec, sort_keys=True))))
        self.assertEqual(_builtin(path, spec), (False, "JSON artifact field mismatch: a"))

    def test_actual_process_exit_retains_pending_start_and_blocks_redispatch(self):
        code = """
import os, sys
from pathlib import Path
from value_lab import collaboration as c
c.evaluate = lambda **kwargs: os._exit(73)
c.dispatch(Path(sys.argv[1]), 'study', 'execute',
    {'attempt_id':'killed','reason':'Actual process-exit engineering fault injection'},
    who={'id':'agent-a','kind':'agent'}, key='exit-test', expected_sequence=1)
"""
        killed = subprocess.run([sys.executable, "-B", "-S", "-c", code, str(self.root)],
                                cwd=Path(__file__).resolve().parents[1], timeout=30)
        self.assertEqual(killed.returncode, 73)
        status = self.call("status")
        self.assertEqual(status["status"]["stage"], "EXECUTION_UNRESOLVED")
        with patch("value_lab.collaboration.evaluate", side_effect=AssertionError("No automatic redispatch")):
            replay = self.call("execute", {"attempt_id": "killed",
                "reason": "Actual process-exit engineering fault injection"}, key="exit-test", expected_sequence=1)
        self.assertFalse(replay["execution_performed"])


if __name__ == "__main__":
    unittest.main()
