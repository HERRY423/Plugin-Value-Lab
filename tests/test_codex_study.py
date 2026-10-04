"""Contract fixtures only: these tests never run Codex or establish benefit."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from value_lab.core import ValidationError, demo_suite, load_json
from value_lab import codex_study as work


def fixture_design():
    suite = demo_suite()
    suite["id"] = "codex-contract-fixture"
    suite["runs_per_case"] = 1
    suite["cases"] = [suite["cases"][0]]
    suite["conditions"].update(host="codex", host_version="SYNTHETIC-CODEX-BUILD-1", model="SYNTHETIC-MODEL-1")
    contract = {"host": {"product": "codex", "surface": "desktop", "build": "SYNTHETIC-CODEX-BUILD-1", "model": "SYNTHETIC-MODEL-1"},
                "plugin": {"id": suite["plugin"]["name"], "version": suite["plugin"]["version"], "sha256": "a" * 64},
                "common_tools": [], "candidate_tools": [{"name": "fixture_tool", "definition_sha256": "b" * 64}],
                "context_sha256": "c" * 64, "max_attempts_per_slot": 2}
    return suite, contract


def fixture_packet(plan, slot, attempt_id, *, state="completed", output="SOURCE: fixture LIMITS: synthetic"):
    now = datetime.now(timezone.utc).isoformat()
    with_arm = slot["arm"] == "with"
    events = [{"seq": 1, "kind": "final", "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest()},
              {"seq": 2, "kind": "terminal", "state": state}] if state == "completed" else [{"seq": 1, "kind": "terminal", "state": state}]
    return {"format": "pvl-codex-study-observation-1", "origin": "synthetic", "plan_sha256": plan["plan_sha256"],
            "attempt_id": attempt_id, "slot_id": slot["slot_id"], "session_id": "SYNTHETIC-session-" + attempt_id,
            "request_id": "SYNTHETIC-request-" + attempt_id, "host": plan["host"], "host_source_ref": "raw",
            "started_at": now, "finished_at": now, "prompt": slot["prompt"], "input_sha256": slot["input_sha256"],
            "raw_output": output, "terminal_state": state,
            "context": {"fresh_session": True, "parent_session_id": None, "prior_messages": 0, "memory_enabled": False,
                        "project_id": None, "shared_artifacts": False, "context_sha256": plan["context_sha256"],
                        "inventory_complete": True, "source_ref": "raw"},
            "exposure": {"inventory_complete": True, "source_kind": "host_effective_inventory",
                         "tools": plan["common_tools"] + (plan["candidate_tools"] if with_arm else []),
                         "plugins": [plan["plugin"]] if with_arm else [], "source_ref": "raw"},
            "events": events, "sources": {"raw": "Manufactured test evidence. No host, model or person participated."}}


class CodexStudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.study = self.root / "study"
        self.suite, self.contract = fixture_design()
        self.pin = work.prepare(self.suite, self.contract, self.study)["plan_sha256"]
        self.plan = {**load_json(self.study / "plan.json"), "plan_sha256": self.pin}

    def start(self, index=0, *, retry_of=None):
        slot = self.plan["schedule"][index]
        key = "key-" + slot["slot_id"] + (retry_of or "")
        attempt = work.reserve(self.study, self.pin, slot["slot_id"], key, retry_of=retry_of)
        work.record_state(self.study, self.pin, attempt["attempt_id"], "dispatched", {"source_ref": "synthetic-dispatch"})
        return attempt, slot

    def submit(self, attempt, slot, *, state="completed", mutate=None, output="SOURCE: fixture LIMITS: synthetic"):
        packet = fixture_packet(self.plan, slot, attempt["attempt_id"], state=state, output=output)
        if mutate:
            mutate(packet)
        path = self.root / (attempt["attempt_id"] + "-input.json")
        path.write_text(json.dumps(packet), encoding="utf-8")
        return work.capture(self.study, self.pin, path)

    def complete(self):
        for i in range(len(self.plan["schedule"])):
            attempt, slot = self.start(i)
            self.assertEqual(self.submit(attempt, slot)["issues"], [])

    def test_complete_fixture_rescores_raw_and_replays_in_fresh_process(self):
        self.complete()
        result = work.review(self.study, self.pin)
        self.assertTrue(result["local_contract_complete"], result["issues"])
        self.assertEqual(result["status"], "SIMULATION_ONLY")
        self.assertFalse(result["live_host_accepted"])
        self.assertFalse(result["third_person_recomputed"])
        bundle = self.root / "bundle"
        pin = work.export_review(self.study, self.pin, bundle)["manifest_sha256"]
        replay = work.verify_review(bundle, pin)
        self.assertEqual(replay["model_calls"], 0)
        process = subprocess.run([sys.executable, "-m", "value_lab.codex_study", "verify", str(bundle),
                                  "--manifest-sha256", pin], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), replay)

    def test_missing_slot_does_not_shrink_denominator(self):
        result = work.review(self.study, self.pin)
        self.assertFalse(result["local_contract_complete"])
        self.assertEqual(result["planned_slots"], 2)
        self.assertTrue(all(pair["delta"] is None for pair in result["pairs"]))

    def test_cannot_start_later_slot_first(self):
        with self.assertRaises(ValidationError):
            self.start(1)

    def test_late_result_reconciles_unknown_without_new_attempt(self):
        attempt, slot = self.start()
        work.record_state(self.study, self.pin, attempt["attempt_id"], "unknown", {"source_ref": "connection-lost"})
        with self.assertRaises(ValidationError):
            self.start(retry_of=attempt["attempt_id"])
        self.assertEqual(self.submit(attempt, slot)["issues"], [])
        result = work.review(self.study, self.pin)
        self.assertEqual(result["attempts_retained"], 1)
        self.assertEqual(result["attempts"][0]["state"], "completed")

    def test_failure_then_retry_preserves_failed_primary(self):
        first, slot = self.start()
        self.assertEqual(self.submit(first, slot, state="failed")["issues"], [])
        retry, _ = self.start(retry_of=first["attempt_id"])
        self.assertEqual(self.submit(retry, slot)["issues"], [])
        other, other_slot = self.start(1)
        self.assertEqual(self.submit(other, other_slot)["issues"], [])
        result = work.review(self.study, self.pin)
        self.assertEqual(result["attempts_retained"], 3)
        self.assertEqual(result["attempts"][0]["state"], "failed")
        self.assertFalse(result["attempts"][1]["primary"])
        self.assertIsNone(result["pairs"][0]["delta"])
        self.assertFalse(result["local_contract_complete"])

    def test_baseline_exposure_without_call_is_contamination(self):
        first, slot = self.start()
        self.submit(first, slot)
        other, baseline = self.start(1)
        result = self.submit(other, baseline, mutate=lambda p: p["exposure"].update(plugins=[self.contract["plugin"]]))
        self.assertTrue(result["issues"])
        self.assertTrue(list((self.study / "submissions").glob(other["attempt_id"] + "-*.json")))
        self.assertFalse(work.review(self.study, self.pin)["local_contract_complete"])

    def test_forged_imported_grades_ignored(self):
        attempt, slot = self.start()
        self.submit(attempt, slot, output="incorrect", mutate=lambda p: p.update(grades={"source": {"passed": True}, "limits": {"passed": True}}))
        result = work.review(self.study, self.pin)
        self.assertEqual(result["attempts"][0]["score"]["quality"], 0)

    def test_missing_raw_reference_is_retained_but_not_reconciled(self):
        attempt, slot = self.start()
        result = self.submit(attempt, slot, mutate=lambda p: p.pop("sources"))
        self.assertIn("RAW_SOURCE_REFERENCE_MISSING", result["issues"])
        self.assertEqual(work.review(self.study, self.pin)["attempts"][0]["state"], "dispatched")

    def test_conflicting_capture_cannot_overwrite_original(self):
        attempt, slot = self.start()
        self.submit(attempt, slot)
        original = (self.study / "captures" / (attempt["attempt_id"] + ".json")).read_bytes()
        with self.assertRaises(ValidationError):
            self.submit(attempt, slot, output="replacement")
        self.assertEqual((self.study / "captures" / (attempt["attempt_id"] + ".json")).read_bytes(), original)

    def test_tampering_or_removed_failed_capture_rejected_by_bundle_pin(self):
        self.complete()
        bundle = self.root / "bundle"
        pin = work.export_review(self.study, self.pin, bundle)["manifest_sha256"]
        path = next((bundle / "captures").iterdir())
        path.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValidationError):
            work.verify_review(bundle, pin)

    def test_unsafe_or_unpinned_version_rejected(self):
        contract = deepcopy(self.contract)
        contract["host"]["build"] = "latest"
        with self.assertRaises(ValidationError):
            work.prepare(self.suite, contract, self.root / "bad")
        with self.assertRaises(ValidationError):
            work.review(self.study, "0" * 64)

    def test_prepare_rejects_other_hosts_and_surfaces_before_creating_study(self):
        for product, surface in (("other-host", "desktop"), ("codex", "web"), ("codex", "cli")):
            suite, contract = deepcopy(self.suite), deepcopy(self.contract)
            suite["conditions"]["host"] = product
            contract["host"].update(product=product, surface=surface)
            output = self.root / (product + "-" + surface)
            with self.subTest(product=product, surface=surface):
                with self.assertRaises(ValidationError):
                    work.prepare(suite, contract, output)
                self.assertFalse(output.exists())

    def test_deleted_journal_is_not_recreated(self):
        self.start()
        (self.study / "attempts.sqlite").unlink()
        with self.assertRaises(ValidationError):
            work.review(self.study, self.pin)
        with self.assertRaises(ValidationError):
            self.start()
        self.assertFalse((self.study / "attempts.sqlite").exists())

    def test_truncated_journal_is_not_reinitialized(self):
        self.start()
        (self.study / "attempts.sqlite").write_bytes(b"")
        with self.assertRaises(ValidationError):
            self.start()
        self.assertEqual((self.study / "attempts.sqlite").stat().st_size, 0)

    def test_invalid_first_capture_can_reconcile_original_request_without_erasing_rejection(self):
        attempt, slot = self.start()
        rejected = self.submit(attempt, slot, mutate=lambda p: p.pop("sources"))
        self.assertTrue(rejected["issues"])
        accepted = self.submit(attempt, slot)
        self.assertEqual(accepted["issues"], [])
        result = work.review(self.study, self.pin)
        self.assertEqual(result["attempts_retained"], 1)
        self.assertEqual(result["attempts"][0]["state"], "completed")
        self.assertEqual(len(result["retained_submissions"]), 2)
        self.assertTrue(any("RETAINED_SUBMISSION" in issue for issue in result["issues"]))

    def test_invalid_utf8_output_does_not_destroy_review_or_export(self):
        attempt, slot = self.start()
        self.submit(attempt, slot, mutate=lambda p: p.update(raw_output="\ud800"))
        result = work.review(self.study, self.pin)
        self.assertFalse(result["local_contract_complete"])
        self.assertEqual(result["attempts_retained"], 1)
        work.export_review(self.study, self.pin, self.root / "invalid-output-review")

    def test_deep_json_is_a_failed_grader_not_a_review_crash(self):
        case = {"graders": [{"id": "json", "type": "json_equals", "path": "answer", "value": 1,
                             "dimension": "outcome", "weight": 1, "critical": True}]}
        result = work._score(case, "[" * 2000 + "0" + "]" * 2000, "completed")
        self.assertFalse(result["graders"][0]["passed"])

    def test_replay_validates_event_structure_not_only_hashes(self):
        attempt, slot = self.start()
        self.submit(attempt, slot)
        journal = work._journal(self.study, self.pin).snapshot()
        journal["events"][0]["seq"] = 2
        with self.assertRaises(ValidationError):
            work._assess(self.study, self.suite, self.plan, journal)

    def test_reused_session_invalidates_pair(self):
        first, slot = self.start()
        self.submit(first, slot)
        other, baseline = self.start(1)
        self.submit(other, baseline, mutate=lambda p: p.update(session_id="SYNTHETIC-session-" + first["attempt_id"]))
        result = work.review(self.study, self.pin)
        self.assertFalse(result["local_contract_complete"])
        self.assertIsNone(result["pairs"][0]["delta"])

    def test_version_change_and_incomplete_inventory_remain_unresolved(self):
        first, slot = self.start()
        def change(packet):
            packet["host"] = {**packet["host"], "build": "DIFFERENT-BUILD"}
            packet["exposure"]["inventory_complete"] = False
        self.assertTrue(self.submit(first, slot, mutate=change)["issues"])
        with self.assertRaises(ValidationError):
            self.start(1)

    def test_operator_packet_never_certifies_live_host(self):
        for i in range(2):
            first, slot = self.start(i)
            self.submit(first, slot, mutate=lambda p: p.update(origin="operator_capture"))
        # Even perfect normalized fields never stand in for a qualified host.
        result = work.review(self.study, self.pin)
        self.assertTrue(result["local_contract_complete"], result["issues"])
        self.assertFalse(result["host_transport_qualified"])
        self.assertFalse(result["benefit_claim_supported"])

    def test_deleted_capture_is_detected_and_primary_denominator_kept(self):
        self.complete()
        next((self.study / "captures").iterdir()).unlink()
        result = work.review(self.study, self.pin)
        self.assertEqual(result["primary_attempts"], 2)
        self.assertTrue(any("CAPTURE_MISSING" in issue for issue in result["issues"]))

    def test_repeated_reservation_never_grants_second_dispatch(self):
        slot = self.plan["schedule"][0]
        first = work.reserve(self.study, self.pin, slot["slot_id"], "once")
        again = work.reserve(self.study, self.pin, slot["slot_id"], "once")
        self.assertEqual(first["attempt_id"], again["attempt_id"])
        self.assertFalse(again["dispatch"])

    def test_cross_slot_process_race_admits_only_one_pending_attempt(self):
        first, slot = self.start()
        self.submit(first, slot, state="failed")
        barrier = self.root / "go"
        program = '''
import json, pathlib, sys, time
from value_lab.codex_study import reserve
from value_lab.core import ValidationError
root, pin, slot, key, retry, barrier = sys.argv[1:]
deadline = time.monotonic() + 10
while not pathlib.Path(barrier).exists() and time.monotonic() < deadline:
    time.sleep(0.01)
try:
    result = reserve(root, pin, slot, key, retry_of=retry or None)
    print(json.dumps({"admitted": result["created"]}))
except ValidationError:
    print(json.dumps({"admitted": False}))
'''
        children = []
        for slot_id, key, retry in [(slot["slot_id"], "retry-race", first["attempt_id"]),
                                   (self.plan["schedule"][1]["slot_id"], "next-race", "")]:
            children.append(subprocess.Popen([sys.executable, "-c", program, str(self.study), self.pin,
                                               slot_id, key, retry, str(barrier)], stdout=subprocess.PIPE,
                                              stderr=subprocess.PIPE, text=True))
        barrier.write_text("start", encoding="utf-8")
        admissions = []
        for child in children:
            stdout, stderr = child.communicate(timeout=15)
            self.assertEqual(child.returncode, 0, stderr)
            admissions.append(json.loads(stdout)["admitted"])
        self.assertEqual(sum(admissions), 1)


if __name__ == "__main__":
    unittest.main()
