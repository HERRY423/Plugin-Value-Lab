"""Four identities and revision lifecycle, using manufactured evidence only."""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import unittest
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from value_lab.core import ValidationError
from value_lab.decision_store import DecisionStore
from value_lab import evidence_dependencies as dependencies
from tests import test_decision_recovery as fixtures
from tests.test_evidence_dependencies import fixture


def judgment(jid="j1", parent=None, mode="evaluation", status="PASSED"):
    return {"judgment_id": jid, "parent": parent, "mode": mode, "attempt_ids": ["first"],
            "contract": {"grader": {"version": jid}, "reference": {"kind": "none"},
                         "domain": {"scope": "fixture JSON format only"}},
            "implementation": "synthetic-checker", "result": {"checks": {"format": {"status": status,
            "reason": "manufactured result, not scientific evidence"}}, "pending_checks": []}, "reason": "fixture revision"}


def decision(did="d1", jid="j1", replaces=None):
    return {"decision_id": did, "judgment_id": jid, "policy": {"purpose": "fixture selection",
            "quality_thresholds": {"required": ["format"]}, "budget_micros": 1000},
            "scope": {"task": "fixture"}, "recommendation": "Review this synthetic example", "reason": "fixture policy",
            "replaces": replaces, "status": "current"}


class InterpretationHistoryTests(unittest.TestCase):
    setUp = fixtures.RecoveryTests.setUp
    add = fixtures.RecoveryTests.add
    collect = fixtures.RecoveryTests.collect

    def ready(self):
        self.collect()
        self.add("settle", {"attempt_id": "first", "cost_micros": 100, "basis": "synthetic invoice"})
        self.add("judge", judgment())
        return self.add("decide", decision())

    def test_revision_marks_review_and_explicit_replacement_preserves_old(self):
        before = self.ready()
        self.assertEqual(before["current_decisions"], ["d1"])
        after = self.add("judge", judgment("j2", "j1", "rescore", "FAILED"))
        self.assertEqual(after["current_decisions"], [])
        self.assertEqual(after["guidance_review_required"], ["d1"])
        self.assertEqual(after["explanations"]["judgments"]["j1"], before["explanations"]["judgments"]["j1"])
        updated = self.add("decide", decision("d2", "j2", "d1"))
        layer = updated["explanations"]
        self.assertEqual(layer["decision_states"]["d1"]["status"], "superseded")
        self.assertEqual(layer["decision_states"]["d1"]["superseded_by"], "d2")
        self.assertEqual(layer["decisions"]["d1"], before["explanations"]["decisions"]["d1"])
        self.assertEqual(layer["judgments"]["j1"]["observation_sha256"], layer["judgments"]["j2"]["observation_sha256"])
        self.assertEqual(updated["attempts"], before["attempts"])
        self.assertEqual(updated["costs"], before["costs"])
        self.assertEqual(updated["current_decisions"], ["d2"])
        self.assertFalse(updated["execution_authorized"])

    def test_policy_only_change_reuses_judgment_without_scoring(self):
        before = self.ready()
        payload = decision("d2", "j1", "d1")
        payload["policy"]["purpose"] = "new research purpose"
        with patch("value_lab.artifacts.grade_artifact", side_effect=AssertionError("must not score")):
            after = self.add("decide", payload)
        self.assertEqual(after["explanations"]["judgments"], before["explanations"]["judgments"])
        self.assertNotEqual(after["explanations"]["decisions"]["d2"]["policy_sha256"],
                            before["explanations"]["decisions"]["d1"]["policy_sha256"])
        self.assertEqual(after["attempts"], before["attempts"])

    def test_presentation_changes_no_judgment_or_current_pointer(self):
        before = self.ready()
        for version in ("one", "two"):
            after = self.add("present", {"presentation_id": version, "target_kind": "decision", "target_id": "d1",
                             "renderer": {"version": version}}, files={"report": version.encode()})
        for key in ("judgments", "decisions", "decision_states", "lifecycle"):
            self.assertEqual(after["explanations"][key], before["explanations"][key])
        self.assertEqual(after["current_decisions"], ["d1"])
        stale = self.add("review", {"decision_id": "d1", "status": "not_applicable", "reason": "different task"})
        self.assertEqual(stale["current_decisions"], [])
        self.assertEqual(stale["explanations"]["presentations"]["one"]["lifecycle_at_render"]["status"], "current")
        self.assertFalse(stale["presentation_is_current_guidance"])

    def test_unknown_judgment_or_budget_cannot_become_current(self):
        self.ready()
        payload = judgment("j2", "j1", "rescore", "UNKNOWN")
        self.add("judge", payload)
        after = self.add("decide", decision("d2", "j2", "d1"))
        self.assertEqual(after["current_decisions"], [])
        self.assertEqual(after["guidance_review_required"], ["d2"])

    def test_unsettled_cost_and_exceeded_policy_need_review(self):
        self.collect()
        self.add("judge", judgment())
        self.assertEqual(self.add("decide", decision())["current_decisions"], [])
        self.add("settle", {"attempt_id": "first", "cost_micros": 2000, "basis": "fixture"})
        self.assertEqual(self.add("decide", decision("d2", "j1", "d1"))["current_decisions"], [])

    def test_new_attempt_invalidates_guidance_without_losing_old_failure(self):
        self.ready()
        after = self.add("start", fixtures.start("retry"))
        self.assertEqual(after["current_decisions"], [])
        self.add("finish", {"attempt_id": "retry", "status": "FAILED", "receipt": {"reason": "fixture"}}, files={})
        self.add("settle", {"attempt_id": "retry", "cost_micros": 0, "basis": "fixture"})
        after = self.add("decide", decision("d2", "j1", "d1"))
        self.assertEqual(after["current_decisions"], [])
        self.assertEqual(after["attempts"]["retry"]["status"], "FAILED")

    def test_new_other_group_reservation_also_invalidates_budget_guidance(self):
        self.ready()
        view = self.add("start", fixtures.start("other", "plugin"))
        self.assertEqual(view["current_decisions"], [])
        self.assertEqual(view["guidance_review_required"], ["d1"])

    def test_import_unknown_dependency_keeps_review_even_if_file_checks_pass(self):
        card, graph, inventory = fixture(self.root)
        graph["nodes"] = [n for n in graph["nodes"] if n["id"] not in ("retrieval", "retrieval-claim", "retrieval-guidance")]
        inventory["model"] = None
        self.add("start", fixtures.start())
        self.add("finish", {"attempt_id": "first", "status": "COLLECTED", "receipt": {"source": "fixture"}},
                 files={"raw": (self.root / "retrieved.json").read_bytes()})
        self.add("settle", {"attempt_id": "first", "cost_micros": 0, "basis": "fixture"})
        report = dependencies.recheck(card, graph, inventory, self.root, action="rescore")
        self.assertEqual(report["rules"]["format"]["status"], "PASSED")
        view = self.store.record_recheck(report, card, ["first"], "j1", key="unknown-import", expected_sequence=self.store.snapshot()["sequence"])
        self.assertTrue(view["explanations"]["judgments"]["j1"]["result"]["pending_checks"])
        self.assertEqual(self.add("decide", decision())["current_decisions"], [])

    def test_rescore_must_keep_observations_and_change_judgment(self):
        self.ready()
        same = judgment("j2", "j1", "rescore")
        same["contract"] = judgment()["contract"]
        with self.assertRaisesRegex(ValidationError, "replay"):
            self.add("judge", same)
        self.collect("second", "plugin")
        changed = judgment("j2", "j1", "rescore")
        changed["attempt_ids"].append("second")
        with self.assertRaisesRegex(ValidationError, "same observations"):
            self.add("judge", changed)

    def test_terminal_decision_cannot_be_reactivated_by_status_edit(self):
        self.ready()
        self.add("review", {"decision_id": "d1", "status": "not_applicable", "reason": "domain changed"})
        for status in ("current", "review_required", "superseded"):
            with self.assertRaises(ValidationError):
                self.add("review", {"decision_id": "d1", "status": status, "reason": "overwrite"})
        with self.assertRaisesRegex(ValidationError, "explicitly"):
            self.add("decide", decision("d2"))

    def test_restored_lifecycle_and_presentations_identical_and_idempotent(self):
        self.ready()
        self.add("present", {"presentation_id": "p1", "target_kind": "judgment", "target_id": "j1",
                             "renderer": {"version": "v1"}}, files={"report": b"historical report"})
        self.add("judge", judgment("j2", "j1", "rescore", "FAILED"))
        original = self.store.snapshot()
        bundle = self.root / "export"
        self.store.export(bundle)
        imported = DecisionStore(self.root / "new.sqlite")
        result = imported.restore(bundle, checkpoint=original["checkpoint"])
        self.assertEqual(result["explanations"], original["explanations"])
        self.assertTrue(imported.restore(bundle)["replayed"])
        self.assertEqual(imported.snapshot()["sequence"], original["sequence"])

    def test_revised_judgment_cannot_silently_reactivate_old_support(self):
        self.ready()
        self.add("judge", judgment("j2", "j1", "rescore", "FAILED"))
        after = self.add("decide", decision("d2", "j1", "d1"))
        self.assertEqual(after["current_decisions"], [])

    def test_bad_presentation_does_not_commit(self):
        self.ready()
        before = self.store.snapshot()
        with self.assertRaises(ValidationError):
            self.add("present", {"presentation_id": "p", "target_kind": "decision", "target_id": "missing",
                                 "renderer": {"version": "v1"}}, files={"report": b"uncommitted"})
        self.assertEqual(self.store.snapshot(), before)

    def test_same_judgment_key_concurrently_commits_once(self):
        self.collect()
        sequence = self.store.snapshot()["sequence"]
        def submit(_):
            return self.store.append("judge", judgment(), key="same-judgment", expected_sequence=sequence)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, range(2)))
        self.assertEqual(sorted(r["replayed"] for r in results), [False, True])
        self.assertEqual(len(self.store.snapshot()["explanations"]["judgments"]), 1)

    def test_policy_revision_is_atomic_when_process_dies_before_commit(self):
        self.ready()
        before = self.store.snapshot()
        payload = decision("d2", "j1", "d1")
        payload["policy"]["purpose"] = "explicit new purpose"
        event = self.root / "policy.json"
        event.write_text(json.dumps({"kind": "decide", "payload": payload, "key": "policy-crash", "expected_sequence": before["sequence"]}), encoding="utf-8")
        script = '''import json, os, sys
from unittest.mock import patch
from value_lab.decision_store import DecisionStore
store = DecisionStore(sys.argv[1])
# append inserts the event, then derives its return view before commit.
# Kill at that boundary: replay must retain d1 and never half-supersede it.
with patch("value_lab.decision_store.recovery_view", side_effect=lambda state: os._exit(78)):
    store.append(**json.load(open(sys.argv[2])))
'''
        child = subprocess.run([sys.executable, "-c", script, str(self.store.path), str(event)], cwd=fixtures.ROOT, capture_output=True)
        self.assertEqual(child.returncode, 78, child.stderr.decode(errors="replace"))
        self.assertEqual(self.store.snapshot(), before)
        retry = self.store.append(**json.loads(event.read_bytes()))
        self.assertEqual(retry["current_decisions"], ["d2"])
        self.assertEqual(retry["explanations"]["decision_states"]["d1"]["superseded_by"], "d2")

    def test_unknown_implementation_and_pending_checks_survive_reopen(self):
        self.collect()
        self.add("settle", {"attempt_id": "first", "cost_micros": 0, "basis": "fixture"})
        payload = judgment()
        payload["implementation"] = None
        payload["result"]["pending_checks"] = ["independent domain review"]
        self.add("judge", payload)
        self.add("decide", decision())
        view = DecisionStore(self.store.path).snapshot()
        self.assertEqual(view["current_decisions"], [])
        self.assertIn({"action": "VERIFY_JUDGMENT_IMPLEMENTATION", "judgment_id": "j1"}, view["next_steps"])
        self.assertIn({"action": "COMPLETE_CHECK", "check": "independent domain review"}, view["next_steps"])

    def test_old_unknown_dependency_cannot_disappear_with_new_judgment(self):
        other = DecisionStore(self.root / "unknown-dependency.sqlite")
        initial = fixtures.initialization()
        initial["dependencies"]["reference"] = None
        other.append("initialize", initial, key="init", expected_sequence=0)
        self.store = other
        view = self.ready()
        self.assertEqual(view["current_decisions"], [])
        self.assertIsNone(view["effective_dependencies"]["reference"])

    def test_reference_revision_preserves_bytes_but_changes_judgment(self):
        self.ready()
        payload = judgment("j2", "j1", "rescore")
        payload["contract"]["grader"] = judgment()["contract"]["grader"]
        payload["contract"]["reference"] = {"reference_digest": "new adjudicated fixture"}
        view = self.add("judge", payload)
        first, second = [view["explanations"]["judgments"][i] for i in ("j1", "j2")]
        self.assertEqual(first["observation_sha256"], second["observation_sha256"])
        self.assertNotEqual(first["judgment_sha256"], second["judgment_sha256"])

    def test_recheck_import_rejects_unrelated_bytes(self):
        self.collect()
        card, graph, inventory = fixture(self.root)
        report = dependencies.recheck(card, graph, inventory, self.root, action="rescore")
        before = self.store.snapshot()
        with self.assertRaisesRegex(ValidationError, "selected retained bytes"):
            self.store.record_recheck(report, card, ["first"], "j1", key="import", expected_sequence=before["sequence"])
        self.assertEqual(self.store.snapshot(), before)

    def test_four_event_schemas_match_runtime_and_reject_extra_fields(self):
        import jsonschema
        schema = json.loads((fixtures.ROOT / "schemas/decision-event.schema.json").read_bytes())
        jsonschema.Draft202012Validator.check_schema(schema)
        self.ready()
        for kind, payload in (("judge", judgment()), ("decide", decision()),
                ("review", {"decision_id": "d1", "status": "review_required", "reason": "fixture"}),
                ("present", {"presentation_id": "p1", "target_kind": "decision", "target_id": "d1", "renderer": {"version": "v1"}})):
            request = {"kind": kind, "payload": payload, "key": "schema", "expected_sequence": 1}
            jsonschema.validate(request, schema)
            request["payload"]["execute"] = True
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(request, schema)

    def test_real_grader_old_rule_error_and_policy_only_acceptance(self):
        from scripts.check_interpretation_history import exercise
        result = exercise(self.root / "acceptance")
        self.assertEqual(result["corrected_rule"], "FAILED")
        self.assertTrue(result["historical_blob_bytes_unchanged"])
        self.assertEqual(result["policy_only_revision_added_judgments"], 0)

    def test_cli_import_keeps_source_report_and_unknown_behavior_check(self):
        card, graph, inventory = fixture(self.root)
        self.add("start", fixtures.start())
        self.add("finish", {"attempt_id": "first", "status": "COLLECTED", "receipt": {"source": "synthetic"}},
                 files={"raw": (self.root / "retrieved.json").read_bytes()})
        report = dependencies.recheck(card, graph, inventory, self.root, action="rescore")
        for name, obj in (("card", card), ("report", report)):
            (self.root / (name + ".json")).write_text(json.dumps(obj), encoding="utf-8")
        command = [sys.executable, "-m", "value_lab.decision_store", "--store", str(self.store.path), "record-recheck",
                   "--report", str(self.root / "report.json"), "--card", str(self.root / "card.json"),
                   "--attempt", "first", "--judgment-id", "j1", "--key", "cli-import", "--expected-sequence", str(self.store.snapshot()["sequence"])]
        run = subprocess.run(command, cwd=fixtures.ROOT, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        view = json.loads(run.stdout)
        result = view["explanations"]["judgments"]["j1"]
        self.assertEqual(result["result"]["checks"]["retrieval"]["status"], "UNKNOWN")
        self.assertIn("source_recheck", result["artifacts"])
        self.assertTrue(result["result"]["pending_checks"])
        repeated = subprocess.run(command, cwd=fixtures.ROOT, capture_output=True, text=True)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertTrue(json.loads(repeated.stdout)["replayed"])
        self.assertEqual(self.store.snapshot()["collected_attempts"], 1)


class HistoricalCompatibilityTests(unittest.TestCase):
    setUp = fixtures.RecoveryTests.setUp

    def bundles(self):
        golden = json.loads((fixtures.ROOT / "tests/fixtures/decision-history-v2.json").read_bytes())
        for case, files in golden["bundles"].items():
            bundle = self.root / (case + "-original")
            bundle.mkdir()
            for name, data in files.items():
                (bundle / name).write_bytes(base64.b64decode(data))
            yield case, bundle

    def test_frozen_previous_wheel_outputs_read_without_upgrading(self):
        for case, bundle in self.bundles():
            with self.subTest(case=case):
                original = json.loads((bundle / "decision.json").read_bytes())
                files = {p.name: p.read_bytes() for p in bundle.iterdir()}
                store = DecisionStore(self.root / (case + ".sqlite"))
                view = store.restore(bundle)
                for field in ("attempts", "interpretations", "costs", "sequence"):
                    self.assertEqual(view[field], original[field])
                self.assertEqual(view["current_decisions"], [])
                self.assertFalse(view["legacy_interpretations_promoted"])
                exported = self.root / (case + "-export")
                store.export(exported)
                self.assertEqual((exported / "events.json").read_bytes(), files["events.json"])
                for name, data in files.items():
                    self.assertEqual((bundle / name).read_bytes(), data)
                    if name.endswith(".blob"):
                        self.assertEqual((exported / name).read_bytes(), data)

    def test_unknown_format_fails_without_partial_restore(self):
        from value_lab.delivery import publish_bundle
        source = next(bundle for case, bundle in self.bundles() if case == "normal")
        files = {p.name: p.read_bytes() for p in source.iterdir() if p.name != "COMMITTED.json"}
        events = json.loads(files["events.json"])
        events[0]["format"] = "pvl-decision-store-999"
        files["events.json"] = json.dumps(events).encode()
        bundle = self.root / "unknown"
        publish_bundle(bundle, files)
        target = DecisionStore(self.root / "unknown.sqlite")
        with self.assertRaisesRegex(ValidationError, "unsupported|Invalid"):
            target.restore(bundle)
        self.assertFalse(target.path.exists())


class EnginePartitionTests(unittest.TestCase):
    def test_only_checked_renderer_body_is_excluded(self):
        path = Path(dependencies.__file__)
        original = Path.read_bytes
        baseline = dependencies._engine()
        source = path.read_bytes()
        self.assertTrue(dependencies._engine_sources()["partition_verified"])
        def modified(p):
            return source.replace("使用依据局部复核".encode(), "使用依据复核展示第二版".encode()) if p == path else original(p)
        with patch.object(Path, "read_bytes", modified):
            self.assertEqual(dependencies._engine(), baseline)
            self.assertNotEqual(dependencies._engine_sources()["presentation_sha256"], hashlib.sha256(b"").hexdigest())
        def scorer_changed(p):
            return source.replace(b'changed, changes = set(), []', b'changed, changes = set(), [] # new computational source') if p == path else original(p)
        with patch.object(Path, "read_bytes", scorer_changed):
            self.assertNotEqual(dependencies._engine(), baseline)

    def test_unknown_reference_falls_back_to_full_source(self):
        path = Path(dependencies.__file__)
        original = Path.read_bytes
        source = path.read_bytes() + b'\ndef unreviewed_dependency():\n    return _revision_files({})\n'
        with patch.object(Path, "read_bytes", lambda p: source if p == path else original(p)):
            self.assertFalse(dependencies._engine_sources()["partition_verified"])

    def test_renderer_new_side_effect_or_argument_write_disables_exception(self):
        path, original = Path(dependencies.__file__), Path.read_bytes
        source = path.read_bytes().replace(b"\r\n", b"\n")
        for extra in (b'    report["status"] = "PASSED"\n', b'    perform_scoring()\n'):
            changed = source.replace(b'def _revision_files(report, request=None):\n', b'def _revision_files(report, request=None):\n' + extra)
            with patch.object(Path, "read_bytes", lambda p: changed if p == path else original(p)):
                self.assertFalse(dependencies._engine_sources()["partition_verified"])

    def test_renderer_change_does_not_rescore_but_rule_change_does(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            card, graph, inventory = fixture(root)
            first = dependencies.recheck(card, graph, inventory, root, action="rescore")
            path, original = Path(dependencies.__file__), Path.read_bytes
            source = path.read_bytes().replace("使用依据局部复核".encode(), "新的报告标题".encode())
            with patch.object(Path, "read_bytes", lambda p: source if p == path else original(p)), \
                    patch.object(dependencies, "grade_artifact", side_effect=AssertionError("renderer must not rescore")):
                second = dependencies.recheck(card, graph, inventory, root, previous=first, action="rescore")
            self.assertEqual(second["local_rescores"], 0)
            for identity in ("observation_sha256", "judgment_sha256", "decision_sha256"):
                self.assertEqual(first["identities"][identity], second["identities"][identity])
            self.assertNotEqual(first["identities"]["presentation"], second["identities"]["presentation"])
            next(n for n in graph["nodes"] if n["id"] == "format")["grader"]["verifier"]["expected"]["format"] = "v2"
            third = dependencies.recheck(card, graph, inventory, root, previous=second, action="rescore")
            self.assertEqual(third["local_rescores"], 1)
            self.assertEqual(third["rules"]["format"]["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
