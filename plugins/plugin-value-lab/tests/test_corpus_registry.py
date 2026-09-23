from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from value_lab.core import ValidationError, demo_suite, demo_records, evaluate, freeze, load_json, suite_digest, write_json
from value_lab.corpus import seed_corpus, prepare_suite, validate_release, error_rates, check_output
from value_lab.registry import (register_study, registry_view, add_review, export_entry, verify_bundle,
                                write_view, replay_bundle, export_review_packet, verify_submission)


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key = self.root / "key"
        seed_corpus(self.key)
        self.release = load_json(self.key / "corpus.json")
        self.truth = load_json(self.key / "answers.private.json")
        self.suite = prepare_suite(self.release, demo_suite())
        self.lock = freeze(self.suite, self.root / "lock.json")
        self.records = []
        for case in self.suite["cases"]:
            answer = self.truth["answers"][case["id"]]
            for arm in ("with", "without"):
                for rep in range(1, self.suite["runs_per_case"] + 1):
                    self.records.append({"case_id": case["id"], "arm": arm, "repetition": rep,
                        "suite_sha256": suite_digest(self.suite), "source": "synthetic",
                        "session_id": f'{case["id"]}-{arm}-{rep}', "status": "completed",
                        "conditions": self.suite["conditions"], "plugin_loaded": arm == "with",
                        "output": json.dumps({"decision": answer["decision"], "result": answer["result"]}),
                        "cost": {"model_usd": 0, "tool_usd": 0, "human_minutes": 0},
                        "duration_seconds": 1, "human_intervals": []})

    def report(self):
        return evaluate(self.suite, self.records, self.lock, corpus_root=self.key)

    def test_complete_computational_contract_not_scientific_truth(self):
        report = self.report()
        self.assertEqual(report["verdict"], "SIMULATION_ONLY")
        self.assertEqual(report["summary"]["with_score"], 1)
        self.assertEqual(report["blockers"], [])
        self.assertTrue(all(m["rate"] == 0 for m in report["corpus_errors"]["metrics"]))
        self.assertNotIn("answers", json.dumps(self.suite))
        self.assertEqual({c["kind"] for c in self.suite["cases"]}, {"task"})

    def test_missing_or_changed_key_does_not_score(self):
        report = evaluate(self.suite, self.records, self.lock)
        self.assertIsNone(report["summary"]["quality_delta"])
        self.truth["answers"][self.suite["cases"][0]["id"]]["result"] = {"total": 999}
        write_json(self.key / "answers.private.json", self.truth)
        report = self.report()
        self.assertIsNone(report["summary"]["quality_delta"])
        self.assertTrue(any("commitment" in b for b in report["blockers"]))

    def test_always_refuse_is_not_success(self):
        for record in self.records:
            if record["arm"] == "with":
                obj = json.loads(record["output"])
                obj["decision"] = "withhold"
                record["output"] = json.dumps(obj)
        report = self.report()
        self.assertEqual(report["summary"]["with_score"], .5)
        metrics = report["corpus_errors"]["metrics"]
        self.assertTrue(all(m["rate"] == 1 for m in metrics if m["arm"] == "with" and m["metric"] == "over_refusal"))
        self.assertTrue(all(m["rate"] == 0 for m in metrics if m["arm"] == "with" and m["metric"] == "unsupported_acceptance"))

    def test_always_accept_and_wrong_results_are_distinct(self):
        for record in self.records:
            obj = json.loads(record["output"])
            obj["decision"] = "allow"
            obj["result"] = {"fabricated": True}
            record["output"] = json.dumps(obj)
        report = self.report()
        self.assertEqual(report["summary"]["with_score"], 0)
        self.assertTrue(all(m["rate"] == 1 for m in report["corpus_errors"]["metrics"] if m["metric"] == "unsupported_acceptance"))

    def test_missing_duplicate_malformed_remain_unknown_with_fixed_denominators(self):
        self.records.pop(0)
        self.records.append(deepcopy(self.records[0]))
        self.records[2]["output"] = '{"decision":"allow","decision":"withhold","result":{}}'
        result = error_rates(self.suite, self.records, self.key)
        metric = next(m for m in result["metrics"] if m["arm"] == "with" and m["split"] == "development" and m["metric"] == "over_refusal")
        self.assertEqual(metric["planned"], 6)
        self.assertEqual(metric["unknown"], 2)
        self.assertIsNone(metric["rate"])
        self.assertGreater(metric["upper_bound"], metric["lower_bound"])

    def test_family_split_leakage_and_hidden_extra_fields_rejected(self):
        bad = deepcopy(self.release)
        bad["cases"][0]["split"] = "heldout"
        with self.assertRaisesRegex(ValidationError, "family"):
            validate_release(bad)
        bad = deepcopy(self.release)
        bad["cases"][0]["answer"] = "withhold"
        with self.assertRaises(ValidationError):
            validate_release(bad)

    def test_changed_prompt_cannot_inherit_sealed_grades(self):
        self.suite["cases"][0]["prompt"] = "An entirely different task"
        report = self.report()
        self.assertTrue(any("cases differ" in b for b in report["blockers"]))
        self.assertFalse(report["summary"]["comparison_eligible"])

    def test_synthetic_release_cannot_be_upgraded_by_changing_suite_label(self):
        self.suite["evidence_type"] = "external"
        for record in self.records:
            record["source"] = "manual"
            record["suite_sha256"] = suite_digest(self.suite)
        self.lock["suite_sha256"] = suite_digest(self.suite)
        self.assertEqual(self.report()["verdict"], "SIMULATION_ONLY")

    def test_types_and_nonfinite_output_are_not_equivalent(self):
        answer = {"decision": "allow", "result": {"valid": True}}
        for output in ('{"decision":"allow","result":{"valid":1}}', '{"decision":"allow","result":{"valid":NaN}}'):
            self.assertFalse(check_output(output, answer)["passed"])

    def test_portable_sealed_study_replays_only_with_separate_key(self):
        study = self.root / "study"
        study.mkdir()
        write_json(study / "suite.json", self.suite)
        write_json(study / "protocol.lock.json", self.lock)
        (study / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in self.records), encoding="utf-8")
        meta = {"observed_at": "2026-09-22T12:00:00Z", "authors": [{"id": "fixture", "organization": "fixture"}],
                "plugin_sha256": "a" * 64, "limitations": "Synthetic only"}
        registry = self.root / "registry"
        incomplete = register_study(study, meta, registry)
        receipt = register_study(study, meta, registry, corpus_root=self.key, parent=incomplete["entry_id"],
                                 revision_reason="Provide the separately committed answer key")
        self.assertTrue(incomplete["blockers"])
        self.assertEqual(receipt["blockers"], [])
        bundle = self.root / "bundle"
        export_entry(registry, receipt["entry_id"], bundle)
        self.assertEqual(replay_bundle(bundle, corpus_root=self.key)["status"], "REPRODUCED")
        self.assertEqual(replay_bundle(bundle)["status"], "REPLAY_DIFFERS")
        self.assertEqual(list(bundle.rglob("answers.private.json")), [])
        self.assertIn("corpus.json", load_json(bundle / "manifest.json")["files"])
        self.assertEqual(load_json(bundle / "usage-card.json")["verdict"], "SIMULATION_ONLY")

    def test_report_renders_both_error_types_and_unknowns(self):
        from value_lab.report import write_reports
        self.records.pop(0)
        paths = write_reports(self.report(), self.root / "report")
        rendered = Path(paths["html"]).read_text(encoding="utf-8")
        self.assertIn("误拒合理分析", rendered)
        self.assertIn("放行不足证据", rendered)
        self.assertIn("缺失上下界", rendered)

    def test_exchange_schemas_match_templates_and_seed(self):
        from jsonschema import Draft202012Validator, FormatChecker
        repo = Path(__file__).resolve().parents[1]
        examples = {"corpus": self.release, "answers": self.truth,
                    "metadata": load_json(repo / "examples/registry-metadata.json"),
                    "review": load_json(repo / "examples/registry-review.json")}
        for name, data in examples.items():
            schema = load_json(repo / ("schemas/registry/1/" + name + ".schema.json"))
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)


class RegistryTests(unittest.TestCase):
    def test_empty_and_synthetic_registry_never_become_a_trusted_standard(self):
        empty = registry_view(self.registry)["bootstrap"]
        self.assertEqual(empty["stage"], "EMPTY")
        study = self.study()
        first = register_study(study, self.meta, self.registry)
        status = registry_view(self.registry)["bootstrap"]
        self.assertEqual(status["stage"], "SYNTHETIC_ONLY")
        self.assertEqual(status["synthetic_lineages"], 1)
        self.assertFalse(status["trusted_evidence_layer"])
        self.assertEqual(status["interchange_status"], "PROVISIONAL_LOCAL_FORMAT")
        self.assertIsNone(status["independent_samples"])
        records = [json.loads(s) for s in (study / "runs.jsonl").read_text().splitlines()]
        records[0]["output"] += " Changed fixture evidence"
        self.write_records(study, records)
        register_study(study, self.meta, self.registry, parent=first["entry_id"], revision_reason="Fixture revision")
        self.assertEqual(registry_view(self.registry)["bootstrap"]["synthetic_lineages"], 1)

    def test_declared_external_records_are_not_adoption_or_independence(self):
        study = self.study(synthetic=False)
        register_study(study, self.meta, self.registry)
        self.assertEqual(registry_view(self.registry)["bootstrap"]["stage"], "LOCAL_PILOT")
        study2 = self.study("external", synthetic=False, session_prefix="external")
        suite = load_json(study2 / "suite.json")
        suite["evidence_type"] = "external"
        write_json(study2 / "suite.json", suite)
        write_json(study2 / "protocol.lock.json", {"suite_sha256": suite_digest(suite)})
        records = [json.loads(s) for s in (study2 / "runs.jsonl").read_text().splitlines()]
        for record in records:
            record["suite_sha256"] = suite_digest(suite)
        self.write_records(study2, records)
        register_study(study2, self.meta, self.registry)
        status = registry_view(self.registry)["bootstrap"]
        self.assertEqual(status["stage"], "EXTERNAL_SUBMISSIONS_UNVERIFIED")
        self.assertEqual(status["declared_external_lineages"], 1)
        self.assertFalse(status["trusted_evidence_layer"])
        self.assertEqual(status["external_adoption"], "NOT_ESTABLISHED")
        view = self.root / "view"
        write_view(self.registry, view)
        self.assertIn("暂定交换格式", (view / "index.html").read_text(encoding="utf-8"))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.registry = self.root / "registry"
        self.meta = {"observed_at": "2026-09-22T12:00:00Z", "authors": [{"id": "Alice", "organization": "Lab A"}],
                     "plugin_sha256": "a" * 64, "limitations": "Synthetic local test fixture"}

    def study(self, name="study", *, synthetic=True, model=None, env=None, session_prefix="first"):
        root = self.root / name
        root.mkdir()
        suite = demo_suite()
        if not synthetic:
            suite["evidence_type"] = "local"
        if model:
            suite["conditions"]["model"] = model
        if env:
            suite["conditions"]["environment"] = env
        records = demo_records(suite)
        for record in records:
            record["session_id"] = session_prefix + record["session_id"]
            if not synthetic:
                record["source"] = "manual"
        write_json(root / "suite.json", suite)
        freeze(suite, root / "protocol.lock.json")
        self.write_records(root, records)
        return root

    def write_records(self, root, records):
        (root / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

    def register(self, root, **kwargs):
        return register_study(root, self.meta, self.registry, **kwargs)

    def review(self, eid, **kwargs):
        return {"entry_id": eid, "reviewer": "Bob", "organization": "Lab B", "relationship": "independent", "conflicts": [],
                "verdict": "support", "rationale": "Checked the computational contract only", "reviewed_at": "2026-09-23T10:00:00Z",
                "evidence": [{"reference": "review-notes-local", "sha256": "b" * 64}], "replication_entry_id": None, **kwargs}

    def test_recomputed_snapshot_roundtrip_and_original_tampering_isolated(self):
        study = self.study()
        write_json(study / "report.json", {"verdict": "CERTIFIED"})
        receipt = self.register(study)
        self.assertEqual(receipt["verdict"], "SIMULATION_ONLY")
        export = self.root / "export"
        self.assertEqual(export_entry(self.registry, receipt["entry_id"], export)["entry_id"], receipt["entry_id"])
        (study / "runs.jsonl").write_text("corrupted")
        view = registry_view(self.registry)
        self.assertEqual(view["counts"]["registered_studies"], 1)
        self.assertFalse(view["entries"][0]["descriptive_comparison_eligible"])
        self.assertFalse((export / "answers.private.json").exists())
        (export / "report.json").write_text("{}")
        with self.assertRaisesRegex(ValidationError, "changed"):
            verify_bundle(export)

    def test_duplicate_observations_cannot_be_new_evidence(self):
        study = self.study()
        self.register(study)
        self.meta["observed_at"] = "2026-09-23T10:00:00Z"
        with self.assertRaisesRegex(ValidationError, "already registered"):
            self.register(study)
        self.assertEqual(registry_view(self.registry)["counts"]["registered_studies"], 1)

    def test_reused_sessions_preserved_but_not_independent_replicates(self):
        first = self.register(self.study("first", synthetic=False))
        second = self.register(self.study("second", synthetic=False, model="another-model"))
        self.assertEqual(second["overlapping_entries"], [first["entry_id"]])
        view = registry_view(self.registry)
        self.assertFalse(view["changes"][0]["eligible"])
        self.assertIsNone(view["changes"][0]["quality_gain_change"])

    def test_conditions_change_makes_different_cohort(self):
        self.register(self.study("first", synthetic=False))
        self.register(self.study("second", synthetic=False, env="new environment", session_prefix="second"))
        view = registry_view(self.registry)
        self.assertNotEqual(view["entries"][0]["cohort_sha256"], view["entries"][1]["cohort_sha256"])
        self.assertEqual(view["changes"], [])

    def test_model_and_plugin_simultaneously_cannot_attribute_gain(self):
        self.register(self.study("first", synthetic=False))
        self.meta["observed_at"] = "2026-09-23T10:00:00Z"
        self.meta["plugin_sha256"] = "c" * 64
        self.register(self.study("second", synthetic=False, model="another-model", session_prefix="second"))
        change = registry_view(self.registry)["changes"][0]
        self.assertEqual(change["axis"], "combined")
        self.assertFalse(change["eligible"])

    def test_missing_cost_retained_as_unknown(self):
        study = self.study(synthetic=False)
        records = [json.loads(line) for line in (study / "runs.jsonl").read_text().splitlines()]
        records[0]["cost"]["model_usd"] = None
        self.write_records(study, records)
        receipt = self.register(study)
        self.assertEqual(receipt["verdict"], "INSUFFICIENT_EVIDENCE")
        row = registry_view(self.registry)["entries"][0]
        self.assertIsNone(row["cost_delta_usd"])
        self.assertTrue(row["blockers"])

    def test_independence_conflicts_and_review_dissent_remain_visible(self):
        entry = self.register(self.study())["entry_id"]
        for fields in ({"reviewer": " alice "}, {"organization": "lab a"}, {"conflicts": ["funded by author"]}):
            with self.assertRaisesRegex(ValidationError, "conflicts"):
                add_review(self.registry, self.review(entry, **fields))
        add_review(self.registry, self.review(entry))
        add_review(self.registry, self.review(entry, reviewer="Carol", verdict="dispute"))
        add_review(self.registry, self.review(entry, reviewer="Dave", verdict="support"))
        row = registry_view(self.registry)["entries"][0]
        self.assertEqual(row["review_status"], "DISPUTED")
        self.assertEqual(len(row["reviews"]), 3)
        self.assertEqual(registry_view(self.registry)["counts"]["authenticated_independent_reviews"], 0)
        with self.assertRaises(FileExistsError):
            add_review(self.registry, self.review(entry))

    def test_review_target_and_bytes_cannot_be_changed(self):
        entry = self.register(self.study())["entry_id"]
        with self.assertRaises(ValidationError):
            add_review(self.registry, self.review("f" * 64))
        receipt = add_review(self.registry, self.review(entry))
        path = self.registry / "reviews" / (receipt["review_id"] + ".json")
        event = load_json(path)
        event["review"]["verdict"] = "dispute"
        write_json(path, event)
        with self.assertRaises(ValidationError):
            registry_view(self.registry)

    def test_manifest_paths_and_unlisted_files_rejected(self):
        entry = self.register(self.study())["entry_id"]
        root = self.registry / "entries" / entry
        (root / "extra.txt").write_text("unexpected")
        with self.assertRaisesRegex(ValidationError, "Unexpected"):
            verify_bundle(root)

    def test_report_escapes_and_does_not_overwrite(self):
        self.meta["authors"][0]["id"] = "<script>alert(1)</script>"
        self.register(self.study())
        output = self.root / "view"
        write_view(self.registry, output)
        self.assertNotIn("<script>", (output / "index.html").read_text(encoding="utf-8"))
        with self.assertRaises(ValidationError):
            write_view(self.registry, output)

    def test_writer_lock_refuses_uncertain_concurrent_commit(self):
        study = self.study()
        self.registry.mkdir()
        (self.registry / ".writer.lock").write_text("interrupted")
        with self.assertRaisesRegex(ValidationError, "interrupted"):
            self.register(study)
        self.assertTrue((self.registry / ".writer.lock").exists())

    def test_invalid_timestamp_and_unmatched_lock_rejected(self):
        study = self.study()
        self.meta["observed_at"] = "not a timestamp"
        with self.assertRaises(ValidationError):
            self.register(study)
        self.meta["observed_at"] = "2026-09-23T00:00:00Z"
        write_json(study / "protocol.lock.json", {"suite_sha256": "f" * 64})
        with self.assertRaisesRegex(ValidationError, "frozen"):
            self.register(study)

    def test_replication_link_is_checked_not_promoted(self):
        first = self.register(self.study("first"))["entry_id"]
        second = self.register(self.study("second", session_prefix="second"))["entry_id"]
        add_review(self.registry, self.review(first, replication_entry_id=second))
        row = next(r for r in registry_view(self.registry)["entries"] if r["entry_id"] == first)
        check = row["replication_checks"][0]
        self.assertEqual(check["status"], "NOT_COMPARABLE")
        self.assertFalse(check["authenticated_independence"])
        self.assertIn("Synthetic or incomplete evidence", check["blockers"])

    def test_reordering_jsonl_cannot_register_duplicate_observations(self):
        study = self.study()
        self.register(study)
        records = [json.loads(line) for line in (study / "runs.jsonl").read_text().splitlines()]
        self.write_records(study, list(reversed(records)))
        with self.assertRaisesRegex(ValidationError, "already registered"):
            self.register(study)

    def test_cost_evidence_revision_preserves_old_entry_and_counts_one_lineage(self):
        study = self.study(synthetic=False)
        first = self.register(study)["entry_id"]
        old_bytes = (self.registry / "entries" / first / "report.json").read_bytes()
        write_json(study / "cost-ledger.json", {"schema_version": 1,
            "coverage": {k: "included" for k in ("judge", "setup", "retry", "other")}, "entries": []})
        second = self.register(study, parent=first, revision_reason="Add explicit cost coverage")["entry_id"]
        view = registry_view(self.registry)
        old = next(r for r in view["entries"] if r["entry_id"] == first)
        new = next(r for r in view["entries"] if r["entry_id"] == second)
        self.assertEqual(old["superseded_by"], [second])
        self.assertFalse(old["descriptive_comparison_eligible"])
        self.assertTrue(new["descriptive_comparison_eligible"])
        self.assertEqual(new["unrelated_session_overlaps"], [])
        self.assertEqual(view["counts"]["study_lineages"], 1)
        self.assertEqual(view["counts"]["evidence_revisions"], 1)
        self.assertEqual(view["changes"], [])
        self.assertEqual((self.registry / "entries" / first / "report.json").read_bytes(), old_bytes)
        with self.assertRaisesRegex(ValidationError, "No new assessment"):
            self.register(study, parent=second, revision_reason="No-op resubmission")
        records = [json.loads(line) for line in (study / "runs.jsonl").read_text().splitlines()]
        self.write_records(study, list(reversed(records)))
        with self.assertRaisesRegex(ValidationError, "No new assessment"):
            self.register(study, parent=second, revision_reason="Reordering is not evidence")

    def test_revision_requires_reason_and_cannot_change_protocol_or_identity(self):
        study = self.study()
        first = self.register(study)["entry_id"]
        with self.assertRaisesRegex(ValidationError, "revision_reason"):
            self.register(study, parent=first)
        self.meta["plugin_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValidationError, "identity"):
            self.register(study, parent=first, revision_reason="Change plugin")
        self.meta["plugin_sha256"] = "a" * 64
        other = self.study("other", model="new model")
        with self.assertRaisesRegex(ValidationError, "frozen suite"):
            self.register(other, parent=first, revision_reason="Change conditions")

    def test_backdated_session_reuse_blocks_both_rows(self):
        first = self.register(self.study("first", synthetic=False))["entry_id"]
        self.meta["observed_at"] = "2025-01-01T00:00:00Z"
        second = self.register(self.study("second", synthetic=False, model="different"))["entry_id"]
        rows = registry_view(self.registry)["entries"]
        self.assertTrue(all(not r["descriptive_comparison_eligible"] for r in rows))
        self.assertEqual(next(r for r in rows if r["entry_id"] == first)["unrelated_session_overlaps"], [second])

    def test_review_packet_preserves_ancestor_dissent_without_other_study_bytes(self):
        study = self.study(synthetic=False)
        first = self.register(study)["entry_id"]
        add_review(self.registry, self.review(first, verdict="dispute"))
        write_json(study / "cost-ledger.json", {"schema_version": 1,
            "coverage": {k: "included" for k in ("judge", "setup", "retry", "other")}, "entries": []})
        second = self.register(study, parent=first, revision_reason="Supplement costs")["entry_id"]
        row = next(r for r in registry_view(self.registry)["entries"] if r["entry_id"] == second)
        self.assertEqual(row["review_status"], "ANCESTOR_DISPUTED")
        self.assertFalse(row["descriptive_comparison_eligible"])
        packet = self.root / "review-packet"
        receipt = export_review_packet(self.registry, second, packet)
        self.assertEqual(receipt["review_status"], "ANCESTOR_DISPUTED")
        self.assertEqual(verify_submission(packet, receipt["packet_id"])["entry_id"], second)
        self.assertEqual(replay_bundle(packet)["status"], "REPRODUCED")
        self.assertFalse((packet / "entries").exists())
        self.assertEqual(load_json(packet / "review-history.json")["ancestors"], [first])
        with self.assertRaisesRegex(ValidationError, "expected ID"):
            verify_submission(packet, "f" * 64)
        # Later reviews remain in the registry, never rewrite an exported snapshot.
        add_review(self.registry, self.review(second))
        self.assertEqual(verify_submission(packet)["review_events"], 1)
        with self.assertRaises(ValidationError):
            export_review_packet(self.registry, second, packet)

    def test_review_packet_detects_changed_or_missing_reviews(self):
        entry = self.register(self.study())["entry_id"]
        add_review(self.registry, self.review(entry, verdict="dispute"))
        packet = self.root / "packet"
        receipt = export_review_packet(self.registry, entry, packet)
        self.assertEqual(receipt["review_status"], "DISPUTED")
        history = load_json(packet / "review-history.json")
        history["reviews"] = []
        write_json(packet / "review-history.json", history)
        with self.assertRaisesRegex(ValidationError, "changed"):
            verify_submission(packet)

    def test_snapshot_export_explicitly_excludes_review_history(self):
        entry = self.register(self.study())["entry_id"]
        add_review(self.registry, self.review(entry, verdict="dispute"))
        receipt = export_entry(self.registry, entry, self.root / "plain-bundle")
        self.assertFalse(receipt["review_history_included"])

    def test_invalid_lock_type_is_validation_error(self):
        study = self.study()
        write_json(study / "protocol.lock.json", [])
        with self.assertRaises(ValidationError):
            self.register(study)

    def test_artifact_can_be_supplied_in_revision_without_new_model_sessions(self):
        from value_lab.artifacts import sha
        study = self.root / "artifact-study"
        study.mkdir()
        artifacts = self.root / "collected"
        artifacts.mkdir()
        write_json(artifacts / "result.json", {"valid": True})
        suite = demo_suite()
        suite["cases"][0]["graders"] = [{"id": "file", "type": "artifact", "artifact": "result",
            "dimension": "outcome", "weight": 1, "critical": True,
            "verifier": {"kind": "json_fields", "expected": {"valid": True}}}]
        records = demo_records(suite)
        for r in records:
            if r["case_id"] == suite["cases"][0]["id"]:
                r["artifacts"] = {"result": {"path": "result.json", "sha256": sha(artifacts / "result.json")}}
        write_json(study / "suite.json", suite)
        freeze(suite, study / "protocol.lock.json")
        self.write_records(study, records)
        first = self.register(study)
        self.assertTrue(first["blockers"])
        second = self.register(study, artifact_root=artifacts, parent=first["entry_id"], revision_reason="Attach collected file")
        self.assertEqual(second["blockers"], [])
        view = registry_view(self.registry)
        self.assertEqual(view["counts"]["study_lineages"], 1)


if __name__ == "__main__":
    unittest.main()
