"""Adversarial method and portable replay checks; all study data manufactured."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from value_lab.artifacts import sha
from value_lab.core import ValidationError, demo_suite, demo_records, evaluate, freeze, suite_digest, validate_suite, write_json
from value_lab.corpus import seed_corpus, prepare_suite
from value_lab.registry import register_study, replay_bundle, export_entry
from value_lab.replay import plan_replay, replay_contract, report_changes


class RigorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.suite = demo_suite()
        self.suite["evidence_type"] = "local"

    def records(self):
        rows = demo_records(self.suite)
        for row in rows:
            row["source"] = "manual"  # Only unit-test labels, never real observations.
        return rows

    def register(self, records=None, verifier_root=None):
        study = self.root / "study"
        study.mkdir()
        write_json(study / "suite.json", self.suite)
        freeze(self.suite, study / "protocol.lock.json")
        (study / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (records or self.records())), encoding="utf-8")
        metadata = {"observed_at": "2026-09-23T00:00:00Z", "authors": [{"id": "Fixture", "organization": "Fixture"}],
                    "plugin_sha256": "a" * 64, "limitations": "Unit-test fiction"}
        receipt = register_study(study, metadata, self.root / "registry", verifier_root=verifier_root)
        return self.root / "registry/entries" / receipt["entry_id"], receipt

    def test_required_process_failure_blocks_but_never_adds_quality(self):
        rule = self.suite["cases"][0]["graders"][0]
        self.suite["cases"][0]["graders"].append({**rule, "id": "required-process", "dimension": "process", "critical": True, "value": "AUDIT_TRAIL"})
        r = evaluate(self.suite, self.records(), {"suite_sha256": suite_digest(self.suite)})
        self.assertEqual(r["summary"]["with_score"], 1)
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_decision_limits_cannot_be_satisfied_by_cautious_text(self):
        self.suite["policy"]["decision_error_limits"] = {"unsupported_acceptance": .1, "over_refusal": .1}
        r = evaluate(self.suite, self.records(), {"suite_sha256": suite_digest(self.suite)})
        self.assertEqual(r["methodology"]["status"], "UNRESOLVED")
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_rejects_one_sided_or_boolean_error_policies(self):
        for limits in ({"over_refusal": .1}, {"over_refusal": True, "unsupported_acceptance": 0}):
            self.suite["policy"]["decision_error_limits"] = limits
            with self.assertRaises(ValidationError):
                validate_suite(self.suite)

    def test_always_refuse_trips_frozen_error_limit_even_with_permissive_average(self):
        from value_lab.core import load_json
        key = self.root / "private"
        seed_corpus(key)
        release = load_json(key / "corpus.json")
        self.suite = prepare_suite(release, self.suite)
        self.suite["policy"].update(quality_floor=0, max_case_regression=1,
            decision_error_limits={"unsupported_acceptance": 0, "over_refusal": 0})
        truth = load_json(key / "answers.private.json")
        rows = []
        for case in self.suite["cases"]:
            answer = truth["answers"][case["id"]]
            for rep in range(1, self.suite["runs_per_case"] + 1):
                for arm in ("with", "without"):
                    rows.append({"case_id": case["id"], "repetition": rep, "arm": arm, "source": "synthetic",
                                 "suite_sha256": suite_digest(self.suite), "session_id": f"{case['id']}-{rep}-{arm}",
                                 "conditions": self.suite["conditions"], "plugin_loaded": arm == "with", "status": "completed",
                                 "output": json.dumps({"decision": "withhold" if arm == "with" else answer["decision"], "result": answer["result"]}),
                                 "cost": {"model_usd": 0, "tool_usd": 0, "human_minutes": 0}, "human_intervals": []})
        result = evaluate(self.suite, rows, {"suite_sha256": suite_digest(self.suite)}, corpus_root=key)
        self.assertEqual(result["methodology"]["status"], "VIOLATED")
        self.assertEqual(result["measured_verdict"], "REGRESSION_DETECTED")
        self.assertEqual(result["verdict"], "SIMULATION_ONLY")
        plan = replay_contract(self.suite, rows, corpus_root=key)
        self.assertTrue(plan["material_bytes_ready"])

    def test_contradictory_cost_coverage_is_not_complete(self):
        ledger = {"schema_version": 1, "coverage": {k: "not_applicable" for k in ("judge", "setup", "retry", "other")},
                  "entries": [{"id": "judge", "category": "judge", "arm": "with", "amount_usd": 1,
                               "basis": "settled", "evidence_ref": "fixture:judge", "treatment": "additional"}]}
        with self.assertRaises(ValidationError):
            evaluate(self.suite, self.records(), {"suite_sha256": suite_digest(self.suite)}, ledger)

    def test_relocated_bundle_replays_with_pinned_identity_and_environment(self):
        bundle, receipt = self.register()
        target = self.root / "another-machine-path"
        export_entry(self.root / "registry", receipt["entry_id"], target)
        plan = plan_replay(target, expected_id=receipt["entry_id"])
        self.assertFalse(plan["verifier_execution"])
        r = replay_bundle(target, expected_id=receipt["entry_id"], require_same_environment=True)
        self.assertEqual(r["status"], "REPRODUCED")
        self.assertTrue(r["same_runtime"])
        self.assertEqual(r["report_changes"]["changed_field_count"], 0)
        with self.assertRaises(ValidationError):
            replay_bundle(target, expected_id="f" * 64)

    def test_runtime_change_prevents_strict_execution_and_explains_difference(self):
        bundle, _ = self.register()
        with patch("value_lab.replay.platform.python_version", return_value="0.0.fixture"):
            plan = plan_replay(bundle)
            self.assertFalse(plan["same_runtime"])
            self.assertIn("/python", plan["runtime_changes"]["paths"])
            with patch("value_lab.registry.evaluate", side_effect=AssertionError("must not execute")):
                with self.assertRaisesRegex(ValidationError, "environment"):
                    replay_bundle(bundle, require_same_environment=True)

    def test_preflight_never_executes_supplied_scorer(self):
        scorer = self.root / "scorer"
        scorer.mkdir()
        script = scorer / "verify.py"
        script.write_text("raise RuntimeError('must not execute during preflight')\n", encoding="utf-8")
        rule = self.suite["cases"][0]["graders"][0]
        rule.update(type="executable", artifact="result", verifier={"path": "verify.py", "sha256": sha(script), "timeout_seconds": 1})
        rule.pop("value")
        bundle, _ = self.register()  # Missing root deliberately leaves scoring unresolved.
        with patch("subprocess.Popen", side_effect=AssertionError("must not execute")):
            plan = plan_replay(bundle, verifier_root=scorer)
        self.assertEqual(plan["status"], "MATERIALS_REQUIRED")  # Artifact missing even though scorer exists.
        self.assertTrue(any(m["kind"] == "trusted_python" and m["status"] == "BYTES_MATCH" for m in plan["contract"]["materials"]))
        self.assertFalse((bundle / "verify.py").exists())
        self.assertFalse(replay_bundle(bundle)["assessment_complete"])

    def test_replaying_same_incomplete_assessment_is_not_complete_validation(self):
        rows = self.records()
        rows[0]["cost"]["model_usd"] = None
        bundle, _ = self.register(rows)
        replay = replay_bundle(bundle)
        self.assertEqual(replay["status"], "REPRODUCED")
        self.assertFalse(replay["assessment_complete"])
        self.assertEqual(replay["scientific_replication"], "NOT_ESTABLISHED")

    def test_diff_distinguishes_missing_null_and_json_boolean(self):
        self.assertEqual(report_changes({}, {"new": None})["paths"], ["/new"])
        self.assertEqual(report_changes({"x": 1}, {"x": True})["paths"], ["/x"])

    def test_preflight_reports_missing_required_backend_receipt(self):
        case = self.suite["cases"][0]
        case["graders"].append({"id": "backend", "type": "backend_identity", "dimension": "process",
            "weight": 1, "critical": True, "artifact": "result",
            "verifier": {"backend": "fixture", "version": "1", "entrypoint": "run"}})
        plan = replay_contract(self.suite, self.records())
        missing = [row for row in plan["materials"] if row["kind"] == "backend_receipt"]
        self.assertEqual(len(missing), self.suite["runs_per_case"] * 2)
        self.assertTrue(all(row["status"] == "MISSING_OR_CHANGED" for row in missing))
        self.assertFalse(plan["material_bytes_ready"])

    def test_cli_preflight_and_strict_replay(self):
        from value_lab.cli import main
        bundle, receipt = self.register()
        for command, extra in (("registry-replay-plan", []), ("registry-replay", ["--require-same-environment"])):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = main([command, str(bundle), "--expected-id", receipt["entry_id"], *extra])
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(output.getvalue())["same_runtime"])
