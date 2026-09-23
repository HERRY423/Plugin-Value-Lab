import copy
import json
import tempfile
import unittest
from pathlib import Path

from value_lab.core import ValidationError, demo_records, demo_suite, suite_digest
from value_lab.research import assess_research_update, research_example
from value_lab.team_record import build_team_record, validate_team_record, write_team_record
from value_lab.cli import main


class ResearchFollowupTests(unittest.TestCase):
    def test_followup_traces_dependencies_without_claiming_completion(self):
        context = research_example()
        result = assess_research_update(context, {
            "direction_id": "check-confounding", "result": "Fixture result", "source": "synthetic fixture",
            "signal": "supports_rival", "interpretation": "Review causal wording",
        })
        self.assertIn("orthogonal-measure", result["affected_direction_ids"])
        self.assertIn("orthogonal-measure", result["dependent_direction_ids"])
        self.assertFalse(result["result_verified"])
        self.assertFalse(result["direction_completed"])
        self.assertFalse(result["dependencies_unlocked"])
        self.assertEqual(context["directions"][0]["status"], "proposed")

    def test_followup_rejects_unknown_direction_and_invalid_signal(self):
        context = research_example()
        update = {"direction_id": "missing", "result": "x", "source": "x", "signal": "supports_rival", "interpretation": "x"}
        with self.assertRaises(ValidationError):
            assess_research_update(context, update)
        update["direction_id"] = "check-confounding"
        update["signal"] = "proven"
        with self.assertRaises(ValidationError):
            assess_research_update(context, update)


class TeamRecordTests(unittest.TestCase):
    def setUp(self):
        self.suite = demo_suite()
        self.records = demo_records(self.suite)
        self.lock = {"suite_sha256": suite_digest(self.suite)}
        self.decision = {"actor": "fixture reviewer", "choice": "undecided", "rationale": "Synthetic case only"}

    def build(self, **kwargs):
        return build_team_record(self.suite, self.records, self.lock, self.decision, **kwargs)

    def test_revision_preserves_old_card_and_flags_new_evidence(self):
        first = self.build(research_context=research_example())
        changed = copy.deepcopy(self.records)
        changed[0]["output"] = "Changed fixture output"
        second = build_team_record(self.suite, changed, self.lock, self.decision, previous=first)
        self.assertEqual(len(second["entries"]), 2)
        self.assertEqual(second["entries"][0], first["entries"][0])
        self.assertTrue(second["entries"][1]["change"]["evidence_changed"])
        self.assertTrue(second["entries"][1]["change"]["previous_guidance_reassessment_required"])
        self.assertEqual(second["entries"][1]["research_plan"]["context_sha256"], first["entries"][0]["research_plan"]["context_sha256"])
        self.assertEqual(second["entries"][1]["previous_sha256"], first["entries"][0]["entry_sha256"])
        self.assertEqual(second["entries"][1]["card"]["status"], "TRIAL_GUIDANCE_ONLY")

    def test_research_revision_is_compared_and_retained(self):
        original = research_example()
        first = self.build(research_context=original)
        changed = copy.deepcopy(original)
        changed["revision_note"] = "Fixture researcher correction"
        changed["directions"][0]["status"] = "deferred"
        second = self.build(previous=first, research_context=changed)
        change = second["entries"][1]["change"]
        self.assertTrue(change["research_changed"])
        self.assertIn("check-confounding", change["research_comparison"]["direction_changes"]["changed"])
        self.assertFalse(change["research_comparison"]["closure_verified"])

    def test_tampering_and_overwrite_are_rejected(self):
        first = self.build()
        tampered = copy.deepcopy(first)
        tampered["entries"][0]["decision"]["choice"] = "keep"
        with self.assertRaises(ValidationError):
            validate_team_record(tampered)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "record-1"
            paths = write_team_record(first, output)
            self.assertTrue(Path(paths["json"]).exists())
            with self.assertRaises(ValidationError):
                write_team_record(first, output)

    def test_decision_is_explicit_and_never_derived_from_score(self):
        first = self.build()
        self.assertEqual(first["entries"][0]["decision"]["choice"], "undecided")
        with self.assertRaises(ValidationError):
            build_team_record(self.suite, self.records, self.lock,
                              {"actor": "someone", "choice": "adopt", "rationale": "score"})

    def test_cli_creates_first_revision_and_followup_file(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name, data in (("suite.json", self.suite), ("lock.json", self.lock),
                               ("decision.json", self.decision), ("research.json", research_example()),
                               ("update.json", {"direction_id": "check-confounding", "result": "fixture",
                                                "source": "fixture", "signal": "inconclusive", "interpretation": "review"})):
                (base / name).write_text(json.dumps(data), encoding="utf-8")
            (base / "runs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in self.records), encoding="utf-8")
            self.assertEqual(main(["--enable-extensions", "team-card", str(base / "suite.json"), str(base / "runs.jsonl"),
                                   "--lock", str(base / "lock.json"), "--decision", str(base / "decision.json"),
                                   "--research", str(base / "research.json"), "--output", str(base / "team")]), 0)
            self.assertEqual(main(["--enable-extensions", "research-followup", str(base / "research.json"), str(base / "update.json"),
                                   "--output", str(base / "followup.json")]), 0)
            self.assertEqual(json.loads((base / "team" / "record.json").read_text(encoding="utf-8"))["entries"][0]["revision"], 1)
            self.assertEqual(json.loads((base / "followup.json").read_text(encoding="utf-8"))["status"], "REASSESSMENT_REQUIRED")


if __name__ == "__main__":
    unittest.main()
