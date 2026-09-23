from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from value_lab.artifacts import grade_artifact, sha, validate_verifier
from value_lab.core import ValidationError, demo_suite, demo_records, evaluate, freeze
from value_lab.science import cluster_score


class ScienceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scorers = self.root / "scorers"
        self.scorers.mkdir()

    def ref(self, content, name="truth.csv"):
        path = self.scorers / name
        path.write_text(content, encoding="utf-8")
        return {"path": name, "sha256": sha(path)}

    def record(self, content, name="result.csv"):
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return {"session_id": "run-1", "artifacts": {"result": {"path": name, "sha256": sha(path)}}}

    def rule(self, kind, spec):
        g = {"id": "science", "type": kind, "artifact": "result", "verifier": spec,
             "dimension": "outcome", "weight": 1, "critical": True}
        validate_verifier(g)
        return g

    def grade(self, g, record):
        return grade_artifact(g, record, self.root, self.scorers)

    def numeric(self, metric="ari", truth="id,value\na,T\nb,T\nc,B\nd,B", threshold=.9):
        return self.rule("numeric_tolerance", {"metric": metric, "truth": self.ref(truth),
            "id_column": "id", "value_column": "value", "threshold": threshold, "absolute": 0, "relative": 0})

    def test_clustering_permutation_agreement_disagreement_and_coverage(self):
        for metric in ("ari", "nmi"):
            g = self.numeric(metric)
            passed, _, receipt = self.grade(g, self.record("id,value\nd,2\nc,2\nb,1\na,1"))
            self.assertIs(passed, True)
            self.assertEqual(receipt["value"], 1)
            for bad in ("a,1\nb,2\nc,1\nd,2", "a,1\nb,1", "a,1\na,1\nc,2\nd,2", "a,1\nb,1\nc,2\nd,"):
                self.assertIs(self.grade(g, self.record("id,value\n" + bad))[0], False)
        self.assertAlmostEqual(cluster_score([0, 0, 1, 1], [0, 1, 0, 1], "ari"), -.5)
        self.assertEqual(cluster_score([0, 0, 1, 1], [0, 1, 0, 1], "nmi"), 0)

    def test_elementwise_tolerance_and_nonfinite_values(self):
        g = self.numeric("absolute_relative", "id,value\na,10\nb,-10", 1)
        g["verifier"].update(absolute=.01, relative=.01)
        self.assertTrue(self.grade(g, self.record("id,value\na,10.1\nb,-10.1"))[0])
        self.assertFalse(self.grade(g, self.record("id,value\na,10.2\nb,-10"))[0])
        self.assertFalse(self.grade(g, self.record("id,value\na,nan\nb,-10"))[0])

    def test_pearson_negative_constant_and_reference_tampering(self):
        g = self.numeric("pearson", "id,value\na,-2\nb,0\nc,2", .95)
        self.assertTrue(self.grade(g, self.record("id,value\nc,20\na,-20\nb,0"))[0])
        self.assertFalse(self.grade(g, self.record("id,value\nc,-20\na,20\nb,0"))[0])
        self.assertIsNone(self.grade(g, self.record("id,value\na,1\nb,1\nc,1"))[0])
        (self.scorers / "truth.csv").write_text("tampered")
        self.assertIsNone(self.grade(g, self.record("id,value\na,0"))[0])

    def test_schema_types_required_fields_and_csv(self):
        spec = {"format": "json", "fields": {"score": {"type": "number", "nullable": False}}, "allow_extra": False, "min_rows": 1}
        g = self.rule("artifact_schema", spec)
        for content, expected in [('{"score":1}', True), ('{"score":true}', False), ('{"score":null}', False), ('{}', False), ('{"score":1,"extra":2}', False), ('[]', False), ('{"score":NaN}', False)]:
            self.assertIs(self.grade(g, self.record(content, "result.json"))[0], expected)
        spec.update(format="csv")
        for content, expected in [("score\n2", True), ("score\nnan", False), ("score,score\n1,2", False)]:
            self.assertIs(self.grade(g, self.record(content))[0], expected)

    def test_abstention_decisions_are_separate_from_output_validity(self):
        for kind, decision in (("abstention_correct", "withhold"), ("over_refusal", "allow")):
            truth = self.ref(json.dumps({"decision": decision, "rationale": "Frozen expert criterion"}), "decision.json")
            g = self.rule(kind, {"truth": truth})
            self.assertTrue(self.grade(g, self.record(json.dumps({"decision": decision}), "result.json"))[0])
            opposite = "withhold" if decision == "allow" else "allow"
            passed, _, receipt = self.grade(g, self.record(json.dumps({"decision": opposite}), "result.json"))
            self.assertFalse(passed)
            self.assertTrue(receipt["error"])
            passed, _, receipt = self.grade(g, self.record('{"decision":"unknown"}', "result.json"))
            self.assertFalse(passed)
            self.assertIsNone(receipt["error"])

    def test_backend_receipt_must_bind_actual_session_and_artifact(self):
        g = self.rule("backend_identity", {"backend": "engine", "version": "1", "entrypoint": "engine.run"})
        record = self.record("id,value\na,1")
        record["output"] = '{"backend":"engine","passed":true}'
        self.assertIsNone(self.grade(g, record)[0])
        receipt = {"backend": "engine", "version": "1", "entrypoint": "engine.run", "fallback": False,
                   "session_id": "run-1", "artifact_sha256": record["artifacts"]["result"]["sha256"],
                   "collector": "operator", "basis": "runtime_observation"}
        for change, expected in [({}, True), ({"fallback": True}, False), ({"backend": "other"}, False), ({"session_id": "other"}, None), ({"basis": "model_claim"}, None)]:
            record["backend_receipt"] = self.ref(json.dumps({**receipt, **change}), "receipt.json")
            self.assertIs(self.grade(g, record)[0], expected)

    def test_exec_requires_real_sandbox_and_digest(self):
        g = self.rule("exec", {"program": self.ref('print("never run")', "verify.py"),
                              "image": "python@sha256:" + "1" * 64, "timeout_seconds": 1})
        with patch("value_lab.science.shutil.which", return_value=None), patch("value_lab.science.subprocess.Popen") as popen:
            self.assertIsNone(self.grade(g, self.record("input"))[0])
            popen.assert_not_called()
        g["verifier"]["image"] = "python:latest"
        with self.assertRaises(ValidationError):
            validate_verifier(g)

    def test_exec_stages_only_pinned_program_and_artifact_and_cleans_owned_container(self):
        g = self.rule("exec", {"program": self.ref('print("fixture")', "verify.py"),
                              "image": "python@sha256:" + "1" * 64, "timeout_seconds": 1})
        (self.scorers / "secret.txt").write_text("Never mount this scorer root")
        seen = []
        def launch(command, **kwargs):
            seen.append(command)
            mount = command[command.index("--mount") + 1]
            stage = Path(mount.split("source=", 1)[1].split(",target=", 1)[0])
            self.assertEqual({p.name for p in stage.iterdir()}, {"artifact", "verify.py", "contract.json"})
            self.assertIn("--pull=never", command)
            for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=65534:65534", "--memory=256m", "--pids-limit=32"):
                self.assertIn(flag, command)
            kwargs["stdout"].write(b'{"passed":true,"rationale":"Synthetic container transport fixture"}')
            kwargs["stdout"].flush()
            return Mock(poll=Mock(return_value=0), returncode=0, wait=Mock(return_value=0))
        with patch("value_lab.science.shutil.which", return_value="docker"), patch("value_lab.science.subprocess.Popen", side_effect=launch), patch("value_lab.science.subprocess.run") as cleanup:
            self.assertIs(self.grade(g, self.record("input"))[0], True)
            name = seen[0][seen[0].index("--name") + 1]
            self.assertEqual(cleanup.call_args.args[0], ["docker", "rm", "--force", name])

    def test_exec_timeout_stops_client_and_removes_container(self):
        g = self.rule("exec", {"program": self.ref('print("fixture")', "verify.py"),
                              "image": "python@sha256:" + "1" * 64, "timeout_seconds": 1})
        process = Mock(poll=Mock(return_value=None))
        with patch("value_lab.science.shutil.which", return_value="docker"), patch("value_lab.science.subprocess.Popen", return_value=process), patch("value_lab.science.time.monotonic", side_effect=[0, 2]), patch("value_lab.science.subprocess.run") as cleanup:
            self.assertIsNone(self.grade(g, self.record("input"))[0])
            process.kill.assert_called_once()
            cleanup.assert_called_once()

    def test_new_graders_cannot_trust_imported_booleans(self):
        g = self.numeric()
        suite = demo_suite()
        suite["cases"][0]["graders"] = [g]
        records = demo_records(suite)
        for record in records:
            record["grades"] = {"science": {"passed": True}}
        report = evaluate(suite, records, freeze(suite, self.root / "lock.json"))
        self.assertIsNone(report["cases"][0]["runs"][0]["score"])
        self.assertTrue(report["blockers"])

    def test_critical_backend_process_cannot_disappear_from_gate(self):
        suite = demo_suite()
        g = self.rule("backend_identity", {"backend": "engine", "version": "1", "entrypoint": "run"})
        g["dimension"] = "process"
        suite["cases"][0]["graders"].append(g)
        report = evaluate(suite, demo_records(suite), freeze(suite, self.root / "lock.json"))
        self.assertTrue(any("Critical verification" in b for b in report["blockers"]))

    def test_invalid_specs_fail_before_execution(self):
        g = self.numeric()
        for key, value in (("threshold", True), ("relative", float("nan")), ("id_column", "value")):
            changed = deepcopy(g)
            changed["verifier"][key] = value
            with self.assertRaises(ValidationError):
                validate_verifier(changed)
        g["verifier"]["truth"]["path"] = "../truth.csv"
        with self.assertRaises(ValidationError):
            validate_verifier(g)


if __name__ == "__main__":
    unittest.main()
