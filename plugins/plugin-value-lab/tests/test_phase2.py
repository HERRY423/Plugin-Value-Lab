"""Manufactured records and identities exercise policy, not real scientific reviews."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from value_lab.core import ValidationError, demo_suite, demo_records, freeze, load_json, suite_digest, write_json
from value_lab.hosts import prepare_matrix
from value_lab.longitudinal import analyze_registry
from value_lab.registry import register_study, add_review, registry_view
from value_lab.publication import build_public, verify_public, _heldout
from value_lab.signatures import public_identity, sign, verify


@unittest.skipUnless(importlib.util.find_spec("cryptography"), "optional registry dependency")
class PhaseTwoTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.registry = self.root / "registry"
        self.publisher, self.reviewer = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        self.trust = {"keys": [
            {**public_identity(self.publisher.public_key()), "identity": "Fixture publisher", "organization": "Fixture publisher", "roles": ["publisher"], "revoked": False},
            {**public_identity(self.reviewer.public_key()), "identity": "Fixture reviewer", "organization": "Other fixture lab", "roles": ["domain_reviewer"], "revoked": False}]}
        self.studies = {}

    def study(self, name="first", host="codex-cli", version="1", model="model-fixed", plugin_hash="a"*64,
              bad=False, synthetic=False, change=None, shared_sessions=False, parent=None):
        root = self.root / name
        root.mkdir()
        suite = demo_suite()
        suite["id"] = name
        suite["evidence_type"] = "synthetic" if synthetic else "local"
        suite["plugin"]["version"] = version
        suite["conditions"].update(host=host, host_version="fixture-host-v1", model=model, model_version="fixture-model-v1")
        for case in suite["cases"]:
            case["split"] = "heldout"
        if change:
            change(suite)
        records = demo_records(suite)
        for record in records:
            record["source"] = "synthetic" if synthetic else "manual"  # Policy branch fixture only.
            record["session_id"] = ("shared" if shared_sessions else name) + record["session_id"]
            if bad and record["arm"] == "with":
                record["output"] = "wrong"
        write_json(root / "suite.json", suite)
        freeze(suite, root / "protocol.lock.json")
        (root / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        meta = {"observed_at": f"2026-09-{len(self.studies)+1:02d}T00:00:00Z", "authors": [{"id": "Fixture author", "organization": "Fixture lab"}],
                "plugin_sha256": plugin_hash, "limitations": "All observations and people are unit-test fixtures"}
        entry = register_study(root, meta, self.registry, parent=parent)
        eid = entry["entry_id"]
        self.studies[eid] = (suite, root, meta)
        return eid

    def review(self, eid, **overrides):
        suite, _, meta = self.studies[eid]
        review = {"entry_id": eid, "reviewer": "Fixture reviewer", "organization": "Other fixture lab", "relationship": "independent", "conflicts": [],
                  "verdict": "support", "rationale": "Synthetic policy test", "reviewed_at": "2026-09-23T00:00:00Z",
                  "evidence": [{"reference": "synthetic:review", "sha256": "b" * 64}], "replication_entry_id": None,
                  "protocol": {"version": "pvl-independent-review-1", "role": "domain_reviewer", "plugin_version": suite["plugin"]["version"],
                               "plugin_sha256": meta["plugin_sha256"], "suite_sha256": suite_digest(suite), "disagreements": [], "false_refusals": []}}
        review.update(overrides)
        review["signature"] = sign(review, self.reviewer, "pvl-review-1")
        return review

    def declarations(self):
        result = {}
        for eid, (suite, _, _) in self.studies.items():
            entry = self.registry / "entries" / eid
            heldout = _heldout(entry, suite, None)
            result[eid] = {"suite_sha256": suite_digest(suite), "split_sha256": heldout["split_sha256"],
                           "status": "declared_unexposed", "statement": "Manufactured declaration for policy tests only"}
        return result

    def publish(self, name="site", declarations=True, previous=None):
        return build_public(self.registry, self.root / name, self.publisher, self.trust,
                            self.declarations() if declarations else None, previous)

    def test_signature_tamper_domain_and_key_substitution(self):
        payload = {"value": 1}
        signature = sign(payload, self.publisher, "pvl-public-card-1")
        self.assertEqual(verify(payload, signature, "pvl-public-card-1"), signature["key_id"])
        for value, domain in (({"value": True}, "pvl-public-card-1"), (payload, "pvl-review-1")):
            with self.assertRaises(ValidationError):
                verify(value, signature, domain)
        signature["public_key"] = public_identity(self.reviewer.public_key())["public_key"]
        with self.assertRaises(ValidationError):
            verify(payload, signature, "pvl-public-card-1")

    def test_unsigned_review_never_enables_positive_listing(self):
        eid = self.study()
        review = self.review(eid)
        review.pop("signature")
        add_review(self.registry, review)
        result = self.publish()
        self.assertEqual(result["positive_cards"], 0)
        card = load_json(self.root / "site/cards" / (eid + ".json"))["payload"]
        self.assertEqual(card["status"], "PENDING_REVIEW")

    def test_signed_non_author_review_and_heldout_enables_only_bounded_signal(self):
        eid = self.study()
        add_review(self.registry, self.review(eid))
        result = self.publish()
        self.assertEqual(result["positive_cards"], 1)
        card = load_json(self.root / "site/cards" / (eid + ".json"))["payload"]
        self.assertEqual(card["status"], "REVIEWED_LOCAL_SIGNAL")
        self.assertEqual(card["claim_limits"]["scientific_authorization"], "NONE")
        self.assertNotIn("prompt", json.dumps(card))

    def test_missing_heldout_declaration_or_versions_blocks_positive(self):
        eid = self.study(change=lambda s: s["conditions"].pop("host_version"))
        add_review(self.registry, self.review(eid))
        self.assertEqual(self.publish(declarations=False)["positive_cards"], 0)
        blockers = load_json(self.root / "site/cards" / (eid + ".json"))["payload"]["publication_blockers"]
        self.assertTrue(any("versions" in b for b in blockers))
        self.assertTrue(any("Held-out" in b for b in blockers))

    def test_development_gain_cannot_replace_zero_heldout_gain(self):
        def change(suite):
            for case in suite["cases"]:
                case["split"] = "heldout" if case["id"] == "unrelated-request" else "development"
        eid = self.study(change=change)
        add_review(self.registry, self.review(eid))
        self.assertEqual(self.publish()["positive_cards"], 0)
        card = load_json(self.root / "site/cards" / (eid + ".json"))["payload"]
        self.assertGreater(card["summary"]["quality_delta"], 0)
        self.assertEqual(card["split_results"]["heldout"]["quality_delta"], 0)
        self.assertFalse(card["split_results"]["heldout"]["objective_met"])

    def test_efficiency_without_cost_coverage_never_becomes_public_signal(self):
        eid = self.study(change=lambda suite: suite["policy"].update(objective="efficiency"))
        add_review(self.registry, self.review(eid))
        self.assertEqual(self.publish()["positive_cards"], 0)
        card = load_json(self.root / "site/cards" / (eid + ".json"))["payload"]
        self.assertFalse(card["cost_evidence"]["complete_category_coverage"])

    def test_untrusted_or_revoked_reviewer_preserved_but_not_qualifying(self):
        eid = self.study()
        add_review(self.registry, self.review(eid))
        self.trust["keys"][1]["revoked"] = True
        self.assertEqual(self.publish()["positive_cards"], 0)
        self.assertEqual(registry_view(self.registry)["counts"]["review_events"], 1)

    def test_trusted_key_cannot_impersonate_another_reviewer(self):
        eid = self.study()
        add_review(self.registry, self.review(eid, reviewer="Another identity"))
        self.assertEqual(self.publish()["positive_cards"], 0)

    def test_author_and_same_organization_rejected(self):
        eid = self.study()
        for kwargs in ({"reviewer": "Fixture author"}, {"organization": "Fixture lab"}):
            with self.assertRaises(ValidationError):
                add_review(self.registry, self.review(eid, **kwargs))

    def test_version_mismatch_and_disagreement_do_not_promote(self):
        eid = self.study()
        p = self.review(eid)["protocol"]
        p.update(plugin_version="wrong", disagreements=["Unresolved donor leakage"])
        add_review(self.registry, self.review(eid, protocol=p))
        self.assertEqual(self.publish()["positive_cards"], 0)

    def test_signed_synthetic_evidence_stays_observation_only(self):
        eid = self.study(synthetic=True)
        add_review(self.registry, self.review(eid))
        self.assertEqual(self.publish()["positive_cards"], 0)

    def test_negative_and_disputed_records_remain_visible(self):
        a = self.study()
        self.study("negative", version="2", bad=True, plugin_hash="c"*64)
        add_review(self.registry, self.review(a, verdict="dispute"))
        result = self.publish()
        self.assertEqual((result["cards"], result["positive_cards"]), (2, 0))

    def test_tampered_html_card_and_old_snapshot_are_detected(self):
        self.study()
        first = self.publish()
        second = self.publish("new-site", previous=self.root / "site")
        self.assertEqual(second["previous_snapshot_sha256"], first["snapshot_sha256"])
        with self.assertRaises(ValidationError):
            verify_public(self.root / "site", self.trust, second["snapshot_sha256"])
        (self.root / "site/index.html").write_text("tampered")
        with self.assertRaises(ValidationError):
            verify_public(self.root / "site", self.trust)
        card = next((self.root / "new-site/cards").iterdir())
        obj = load_json(card)
        obj["payload"]["positive_listing_eligible"] = True
        write_json(card, obj)
        with self.assertRaises(ValidationError):
            verify_public(self.root / "new-site", self.trust)

    def test_trust_change_requires_snapshot_rebuild(self):
        eid = self.study()
        add_review(self.registry, self.review(eid))
        self.publish()
        self.trust["keys"][1]["revoked"] = True
        with self.assertRaisesRegex(ValidationError, "Trust policy changed"):
            verify_public(self.root / "site", self.trust)
        self.assertEqual(self.publish("updated")["positive_cards"], 0)

    def test_untrusted_publisher_and_bad_declaration_leave_no_site(self):
        eid = self.study()
        untrusted = {"keys": self.trust["keys"][1:]}
        with self.assertRaises(ValidationError):
            build_public(self.registry, self.root / "site", self.publisher, untrusted)
        self.assertFalse((self.root / "site").exists())
        declarations = self.declarations()
        declarations[eid]["suite_sha256"] = "f" * 64
        with self.assertRaises(ValidationError):
            build_public(self.registry, self.root / "site", self.publisher, self.trust, declarations)
        self.assertFalse((self.root / "site").exists())

    def test_cross_host_delta_preserves_model_and_baseline(self):
        self.study()
        self.study("other", host="claude-code", bad=True)
        result = analyze_registry(self.registry)["host_contrasts"][0]
        self.assertEqual(result["status"], "COMPARABLE_DESCRIPTIVE")
        self.assertLess(result["plugin_gain_change"], 0)
        self.assertEqual(result["baseline_quality_change"], 0)
        self.assertIsNone(result["alert"])

    def test_host_plus_model_change_is_not_host_effect(self):
        self.study()
        self.study("other", host="claude-code", model="another")
        result = analyze_registry(self.registry)["host_contrasts"][0]
        self.assertEqual(result["status"], "NOT_COMPARABLE")
        self.assertIsNone(result["plugin_gain_change"])

    def test_scoring_truth_or_task_change_blocks_host_comparison(self):
        self.study()
        self.study("other", host="claude-code", change=lambda s: s["cases"][0].update(prompt="Changed question"))
        self.assertEqual(analyze_registry(self.registry)["host_contrasts"][0]["status"], "NOT_COMPARABLE")

    def test_same_version_changed_content_can_raise_regression_alert(self):
        self.study()
        self.study("next", plugin_hash="d"*64, bad=True)
        result = analyze_registry(self.registry)
        self.assertEqual(len(result["alerts"]), 1)
        self.assertEqual(result["alerts"][0]["axis"], "plugin")

    def test_simultaneous_axes_or_reused_sessions_never_raise_alert(self):
        self.study(shared_sessions=True)
        self.study("next", plugin_hash="d"*64, model="changed", bad=True, shared_sessions=True)
        result = analyze_registry(self.registry)
        self.assertEqual(result["alerts"], [])
        self.assertTrue(all(c["status"] == "NOT_COMPARABLE" for c in result["longitudinal_contrasts"]))

    def test_signed_review_schema_roundtrip_and_tamper(self):
        from jsonschema import Draft202012Validator
        eid = self.study()
        review = self.review(eid)
        schema = load_json(Path(__file__).resolve().parents[1] / "schemas/registry/1/review.schema.json")
        Draft202012Validator(schema).validate(review)
        review["rationale"] = "tampered"
        with self.assertRaises(ValidationError):
            add_review(self.registry, review)

    def test_unrelated_latest_task_cannot_hide_a_matching_cohort_regression(self):
        first = self.study()
        self.study("different-task", plugin_hash="b"*64, change=lambda s: s["cases"][0].update(prompt="Unrelated"))
        last = self.study("last", plugin_hash="c"*64, bad=True)
        alerts = analyze_registry(self.registry)["alerts"]
        self.assertTrue(any(a["before"] == first and a["after"] == last for a in alerts))

    def test_model_version_change_without_alias_change_is_a_model_axis(self):
        self.study()
        self.study("model-revision", bad=True, change=lambda s: s["conditions"].update(model_version="fixture-v2"))
        alerts = analyze_registry(self.registry)["alerts"]
        self.assertEqual([a["axis"] for a in alerts], ["model"])

    def test_known_family_leakage_blocks_an_unexposed_declaration(self):
        def leak(suite):
            suite["cases"][1]["cluster"] = suite["cases"][0]["cluster"]
            suite["cases"][1]["split"] = "development"
        eid = self.study(change=leak)
        add_review(self.registry, self.review(eid))
        self.assertEqual(self.publish()["positive_cards"], 0)

    def test_review_before_observations_cannot_qualify(self):
        eid = self.study()
        add_review(self.registry, self.review(eid, reviewed_at="2026-01-01T00:00:00Z"))
        self.assertEqual(self.publish()["positive_cards"], 0)

    def test_cli_signed_review_to_verified_public_snapshot(self):
        from value_lab.cli import main
        from cryptography.hazmat.primitives import serialization
        eid = self.study()
        review = self.review(eid)
        review.pop("signature")
        for label, key in (("reviewer", self.reviewer), ("publisher", self.publisher)):
            (self.root / (label + ".pem")).write_bytes(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        for label, data in (("review", review), ("trust", self.trust), ("heldout", self.declarations())):
            write_json(self.root / (label + ".json"), data)
        def call(*args):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main([str(a) for a in args])
            self.assertEqual(code, 0)
            return json.loads(output.getvalue())
        signed = self.root / "signed.json"
        self.assertFalse(call("registry-sign-review", self.root / "review.json", "--key", self.root / "reviewer.pem", "--output", signed)["review_recorded"])
        call("registry-review", signed, "--registry", self.registry)
        result = call("registry-public", "--registry", self.registry, "--publisher-key", self.root / "publisher.pem",
                      "--trust", self.root / "trust.json", "--heldout", self.root / "heldout.json", "--output", self.root / "site")
        self.assertEqual(result["positive_cards"], 1)
        call("registry-public-verify", self.root / "site", "--trust", self.root / "trust.json", "--expected-snapshot", result["snapshot_sha256"])
        call("registry-contrasts", "--registry", self.registry, "--output", self.root / "contrasts.json")


class HostMatrixTests(unittest.TestCase):
    def test_frozen_cells_change_only_host_identity_and_do_not_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "matrix"
            suite = demo_suite()
            result = prepare_matrix(suite, [{"host": "codex-cli", "host_version": "fixture-1"}, {"host": "opencode", "host_version": "fixture-2"}], out)
            self.assertEqual(result["model_calls"], 0)
            self.assertEqual(result["planned_runs"], 36)
            a, b = [load_json(out / h / "suite.json") for h in ("codex-cli", "opencode")]
            self.assertEqual(a["cases"], b["cases"])
            self.assertEqual(a["conditions"]["model"], b["conditions"]["model"])
            self.assertEqual(result["cells"][1]["adapter_status"], "EXECUTION_ADAPTER_NOT_IMPLEMENTED")
            with self.assertRaises(ValidationError):
                prepare_matrix(suite, [{"host": "codex-cli", "host_version": "1"}] * 2, out)


if __name__ == "__main__":
    unittest.main()
