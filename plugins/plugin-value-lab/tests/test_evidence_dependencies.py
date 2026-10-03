"""Manufactured scope/invalidation fixtures, never evidence of real benefit."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from value_lab.core import ValidationError, demo_records, demo_suite, suite_digest
from value_lab.usage import build_usage_card
from value_lab.evidence_dependencies import FORMAT, REQUIRED, recheck, validate_graph, write_revision
from value_lab.artifacts import sha


def fixture(root):
    suite = demo_suite()
    card = build_usage_card(suite, demo_records(suite), {"suite_sha256": suite_digest(suite)})
    (root / "retrieved.json").write_text('{"format":"v1","items":["A"]}', encoding="utf-8")
    deps = sorted(REQUIRED | {"tool"})
    nodes = [{"id": d, "kind": "dependency", "category": d, "depends_on": []} for d in deps]
    nodes += [{"id": "raw", "kind": "artifact", "path": "retrieved.json", "sha256": sha(root / "retrieved.json"), "depends_on": deps},
              {"id": "format", "kind": "rule", "scope": "historical_artifact", "mode": "artifact_rescore",
               "basis": "Only the frozen JSON's format, not current retrieval behavior.", "depends_on": ["raw"],
               "grader": {"id": "format", "type": "artifact", "artifact": "raw", "verifier": {"kind": "json_fields", "expected": {"format": "v1"}}}},
              {"id": "retrieval", "kind": "rule", "scope": "current_behavior", "mode": "model_execution", "grader": None,
               "basis": "New retrieval/model execution required under the new API.", "depends_on": ["raw"]},
              {"id": "format-claim", "kind": "claim", "statement": "Recorded JSON meets the declared format.", "depends_on": ["format"]},
              {"id": "retrieval-claim", "kind": "claim", "statement": "Current retrieval still needs execution evidence.", "depends_on": ["retrieval", "format"]},
              {"id": "format-guidance", "kind": "recommendation", "card_pointer": "/envelope/rows/0", "depends_on": ["format-claim"]},
              {"id": "retrieval-guidance", "kind": "recommendation", "card_pointer": "/envelope/rows/1", "depends_on": ["retrieval-claim"]}]
    graph = {"format": FORMAT, "card_sha256": suite_digest(card),
             "coverage": {"complete": True, "basis": "Manufactured fixture with explicitly closed dependencies."}, "nodes": nodes}
    return card, graph, {d: "fixture-v1" for d in deps}


class EvidenceDependencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.card, self.graph, self.inventory = fixture(self.root)
        self.baseline = self.run_check(action="rescore")

    def run_check(self, *, previous=None, action="plan"):
        return recheck(self.card, self.graph, self.inventory, self.root, previous=previous, action=action)

    def node(self, ident):
        return next(n for n in self.graph["nodes"] if n["id"] == ident)

    def test_tool_change_retains_format_and_invalidates_only_retrieval_guidance(self):
        self.inventory["tool"] = "api-v2"
        with patch("value_lab.evidence_dependencies.grade_artifact", side_effect=AssertionError("Unrelated check rerun")):
            result = self.run_check(previous=self.baseline, action="rescore")
        self.assertEqual(result["recheck_scope"], "LOCAL")
        self.assertEqual(result["rules"]["format"]["status"], "PASSED")
        self.assertEqual(result["rules"]["format"]["action"], "retained")
        self.assertEqual(result["rules"]["retrieval"]["causes"], ["tool"])
        self.assertEqual([r["review_required"] for r in result["recommendations"]], [False, True])
        self.assertIn("tool", result["rules"]["format"]["producer_dependencies_excluded"])
        self.assertEqual(result["new_model_executions"], 0)

    def test_all_declared_producer_categories_invalidate_current_behavior(self):
        for category in REQUIRED:
            with self.subTest(category=category):
                inventory = deepcopy(self.inventory)
                inventory[category] = "changed-without-version-bump"
                result = recheck(self.card, self.graph, inventory, self.root, previous=self.baseline)
                self.assertTrue(result["rules"]["retrieval"]["affected"])
                self.assertFalse(result["rules"]["format"]["affected"])

    def test_rule_change_rescores_only_its_path_and_keeps_negative_result(self):
        self.node("format")["grader"]["verifier"]["expected"]["format"] = "v2"
        result = self.run_check(previous=self.baseline, action="rescore")
        self.assertEqual(result["local_rescores"], 1)
        self.assertEqual(result["rules"]["format"]["status"], "FAILED")
        again = self.run_check(previous=result, action="rescore")
        self.assertEqual(again["rules"]["format"]["status"], "FAILED")
        self.assertEqual(again["local_rescores"], 0)
        self.assertTrue(all(r["review_required"] for r in again["recommendations"]))

    def test_replay_never_passes_scoring_or_execution(self):
        replay = self.run_check(action="replay")
        self.assertEqual(replay["rules"]["format"]["status"], "REPLAYED_ONLY")
        self.assertIsNone(replay["rules"]["format"]["passed"])
        self.assertEqual(replay["artifact_replays"], 1)
        self.assertEqual(replay["local_rescores"], 0)
        self.assertEqual(replay["rules"]["retrieval"]["status"], "REEXECUTION_REQUIRED")
        rescored = self.run_check(previous=replay, action="rescore")
        self.assertEqual(rescored["local_rescores"], 1)
        self.assertEqual(rescored["rules"]["format"]["status"], "PASSED")
        self.assertFalse(rescored["whole_card_renewed"])

    def test_plan_then_rescore_does_not_lose_pending_check(self):
        planned = self.run_check()
        self.assertEqual(planned["rules"]["format"]["status"], "RECHECK_REQUIRED")
        scored = self.run_check(previous=planned, action="rescore")
        self.assertEqual(scored["rules"]["format"]["status"], "PASSED")
        self.assertEqual(scored["local_rescores"], 1)

    def test_repeated_update_does_not_clear_execution_or_guidance_review(self):
        self.inventory["model"] = "new-model"
        changed = self.run_check(previous=self.baseline, action="rescore")
        again = self.run_check(previous=changed, action="rescore")
        self.assertEqual(again["rules"]["retrieval"]["status"], "REEXECUTION_REQUIRED")
        self.assertTrue(again["recommendations"][1]["review_required"])
        self.assertEqual(len(again["pending_tasks"]), 1)

    def test_unknown_inventory_widens_scope(self):
        for change in ("extra", "missing", "null"):
            with self.subTest(change=change):
                inventory = deepcopy(self.inventory)
                if change == "extra":
                    inventory["unmapped-interface"] = "v2"
                elif change == "missing":
                    del inventory["model"]
                else:
                    inventory["model"] = None
                result = recheck(self.card, self.graph, inventory, self.root, previous=self.baseline, action="rescore")
                self.assertEqual(result["recheck_scope"], "FULL")
                self.assertTrue(all(r["affected"] for r in result["rules"].values()))
                self.assertTrue(all(r["review_required"] for r in result["recommendations"]))

    def test_incomplete_coverage_widens(self):
        self.graph["coverage"]["complete"] = False
        result = self.run_check(previous=self.baseline)
        self.assertIn("DEPENDENCY_COVERAGE_INCOMPLETE", result["fallback_reasons"])
        self.assertTrue(result["rules"]["format"]["affected"])

    def test_missing_category_widens(self):
        self.node("model")["category"] = "tool"
        self.assertEqual(self.run_check(previous=self.baseline)["recheck_scope"], "FULL")

    def test_declared_but_unconnected_behavior_dependency_widens(self):
        self.node("raw")["depends_on"].remove("model")
        initial = self.run_check(action="rescore")
        self.assertTrue(any(x.startswith("INCOMPLETE_BEHAVIOR_PATH:retrieval:model") for x in initial["fallback_reasons"]))
        self.inventory["model"] = "changed"
        updated = self.run_check(previous=initial, action="rescore")
        self.assertEqual(updated["recheck_scope"], "FULL")
        self.assertTrue(updated["recommendations"][1]["review_required"])

    def test_topology_change_widens_including_removed_edge(self):
        self.node("raw")["depends_on"].remove("tool")
        result = self.run_check(previous=self.baseline)
        self.assertIn("GRAPH_TOPOLOGY_CHANGED", result["fallback_reasons"])
        self.assertTrue(result["rules"]["format"]["affected"])

    def test_engine_change_widens(self):
        with patch("value_lab.evidence_dependencies._engine", return_value="f" * 64):
            result = self.run_check(previous=self.baseline)
        self.assertIn("CHECK_ENGINE_OR_RUNTIME_CHANGED", result["fallback_reasons"])

    def test_missing_or_mutated_raw_bytes_never_pass(self):
        artifact = self.root / "retrieved.json"
        artifact.write_text('{"format":"v1","items":["different"]}', encoding="utf-8")
        result = self.run_check(previous=self.baseline, action="rescore")
        self.assertEqual(result["rules"]["format"]["status"], "UNKNOWN")
        self.assertEqual(result["local_rescores"], 0)
        artifact.unlink()
        missing = self.run_check(previous=result, action="rescore")
        self.assertEqual(missing["rules"]["format"]["status"], "UNKNOWN")

    def test_restored_bytes_recheck_but_do_not_auto_clear_review(self):
        artifact = self.root / "retrieved.json"
        old = artifact.read_bytes()
        artifact.write_text("broken", encoding="utf-8")
        broken = self.run_check(previous=self.baseline)
        artifact.write_bytes(old)
        fixed = self.run_check(previous=broken, action="rescore")
        self.assertEqual(fixed["rules"]["format"]["status"], "PASSED")
        self.assertTrue(fixed["recommendations"][0]["review_required"])

    def test_current_behavior_cannot_use_old_artifact_rescore(self):
        self.node("retrieval")["mode"] = "artifact_rescore"
        with self.assertRaises(ValidationError):
            self.run_check(action="rescore")

    def test_science_reexecution_is_separate_pending_work(self):
        self.node("retrieval")["mode"] = "scientific_execution"
        result = self.run_check(action="rescore")
        self.assertEqual(result["pending_tasks"][0]["required_evidence"], "scientific_execution")
        self.assertFalse(result["pending_tasks"][0]["execution_authorized"])
        self.assertEqual(result["new_scientific_executions"], 0)

    def test_executable_grader_rejected(self):
        self.node("format")["grader"]["type"] = "executable"
        with self.assertRaises(ValidationError):
            self.run_check(action="rescore")

    def test_external_reference_rejected_until_its_dependencies_supported(self):
        self.node("format")["grader"]["verifier"]["testing_family"] = {"path": "truth.json", "sha256": "a" * 64}
        with self.assertRaises(ValidationError):
            self.run_check()

    def test_dangling_cycle_duplicate_and_empty_support_rejected(self):
        for change in ("dangling", "cycle", "duplicate", "empty"):
            with self.subTest(change=change):
                graph = deepcopy(self.graph)
                if change == "duplicate":
                    graph["nodes"].append(deepcopy(graph["nodes"][0]))
                else:
                    rule = next(n for n in graph["nodes"] if n["id"] == "format")
                    rule["depends_on"] = {"dangling": ["absent"], "cycle": ["format-claim"], "empty": []}[change]
                with self.assertRaises(ValidationError):
                    validate_graph(graph, self.card)

    def test_path_escape_and_bad_card_binding_rejected(self):
        for path in ("../secret.json", "C:/secret.json", "/secret.json"):
            self.node("raw")["path"] = path
            with self.assertRaises(ValidationError):
                self.run_check()
        self.node("raw")["path"] = "retrieved.json"
        self.graph["card_sha256"] = "0" * 64
        with self.assertRaises(ValidationError):
            self.run_check()

    def test_prior_tampering_and_other_card_rejected(self):
        previous = deepcopy(self.baseline)
        previous["rules"]["retrieval"]["status"] = "PASSED"
        with self.assertRaises(ValidationError):
            self.run_check(previous=previous)
        self.card["study_id"] = "another"
        self.graph["card_sha256"] = suite_digest(self.card)
        with self.assertRaises(ValidationError):
            self.run_check(previous=self.baseline)

    def test_inputs_preserved_and_synthetic_ceiling_unmapped_rows_reported(self):
        original = deepcopy((self.card, self.graph, self.inventory, self.baseline))
        result = self.run_check(previous=self.baseline, action="rescore")
        self.assertEqual((self.card, self.graph, self.inventory, self.baseline), original)
        self.assertEqual(result["source_verdict"], "SIMULATION_ONLY")
        self.assertFalse(result["whole_card_renewed"])
        self.assertTrue(result["unmapped_card_pointers"])
        self.assertFalse(result["claims"]["format-claim"]["claim_truth_established"])

    def test_file_race_rejected(self):
        from value_lab.evidence_dependencies import _observe
        before = _observe(validate_graph(self.graph, self.card), self.root)
        after = deepcopy(before)
        after["raw"]["intact"] = False
        with patch("value_lab.evidence_dependencies._observe", side_effect=[before, after]):
            with self.assertRaises(ValidationError):
                self.run_check(action="rescore")

    def test_write_new_revision_and_never_overwrite(self):
        output = self.root / "revision"
        paths = write_revision(self.baseline, output)
        self.assertTrue(Path(paths["report"]).exists())
        self.assertEqual(write_revision(self.baseline, output), paths)
        changed = deepcopy(self.baseline)
        changed["source_status"] = "changed"
        with self.assertRaises(ValidationError):
            write_revision(changed, output)

    def test_cli_roundtrip(self):
        for name, data in (("card", self.card), ("graph", self.graph), ("inventory", self.inventory)):
            (self.root / (name + ".json")).write_text(json.dumps(data), encoding="utf-8")
        command = [sys.executable, "-m", "value_lab.evidence_dependencies", "rescore",
                   "--card", str(self.root / "card.json"), "--graph", str(self.root / "graph.json"),
                   "--inventory", str(self.root / "inventory.json"), "--artifacts", str(self.root),
                   "--output", str(self.root / "cli-revision")]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = json.loads((self.root / "cli-revision/revision.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["rules"]["format"]["status"], "PASSED")
        replay = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertTrue(json.loads(replay.stdout)["replayed"])

    def test_schema_accepts_fixture_and_rejects_extra_fields(self):
        import jsonschema
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/evidence-dependencies.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(self.graph, schema)
        self.graph["nodes"][0]["unexpected"] = True
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(self.graph, schema)

    def test_rule_direct_dependency_is_not_excluded_as_producer(self):
        self.node("format")["depends_on"].append("environment")
        initial = self.run_check(action="rescore")
        self.inventory["environment"] = "new-check-runtime"
        changed = self.run_check(previous=initial, action="rescore")
        self.assertEqual(changed["rules"]["format"]["action"], "rescored")
        self.assertEqual(changed["rules"]["format"]["causes"], ["environment"])

    def test_retained_failure_keeps_original_failure_explanation(self):
        self.node("format")["grader"]["verifier"]["expected"]["format"] = "v2"
        failed = self.run_check(action="rescore")
        retained = self.run_check(previous=failed)
        again = self.run_check(previous=retained)
        self.assertEqual(again["rules"]["format"]["retained_result_reason"], failed["rules"]["format"]["reason"])


if __name__ == "__main__":
    unittest.main()
