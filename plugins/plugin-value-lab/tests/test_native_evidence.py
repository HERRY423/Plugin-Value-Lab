"""Synthetic transport tests; never evidence of a real native model run."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from value_lab.artifacts import sha
from value_lab.claude_collection import observe_native_events
from value_lab.core import ValidationError, load_json, write_json
from value_lab.native_evidence import (prepare_native_evidence, capture_native_evidence,
                                       verify_native_evidence, discover_native_bindings)


class NativeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plugin = self.root / "plugin"
        case = self.plugin / "evals/csv"
        case.mkdir(parents=True)
        (case / "prompt.md").write_text("---\nruns: 1\n---\nCreate result.csv\n", encoding="utf-8")
        self.references = self.root / "private-scorers"
        self.references.mkdir()
        truth = self.references / "truth.csv"
        truth.write_text("id,value\na,1\nb,2\n", encoding="utf-8")
        self.contract = {"schema_version": 1, "cases": [{"name": "csv", "case_directory": "evals/csv",
            "repetitions": 1, "inputs": {"input": "input.csv"}, "artifacts": {"result": "result.csv"},
            "graders": [{"id": "numeric", "type": "numeric_tolerance", "artifact": "result",
                         "verifier": {"metric": "absolute_relative", "truth": {"path": "truth.csv", "sha256": sha(truth)},
                                      "id_column": "id", "value_column": "value", "threshold": 1, "absolute": 0, "relative": 0}}]}]}
        self.bindings = []
        for arm, content in (("with", "id,value\nb,2\na,1\n"), ("without", "id,value\na,7\nb,2\n")):
            workspace = self.root / arm
            workspace.mkdir()
            (workspace / "result.csv").write_text(content, encoding="utf-8")
            (workspace / "input.csv").write_text("public input", encoding="utf-8")
            (workspace / "private.txt").write_text("must not collect", encoding="utf-8")
            self.bindings.append({"case_id": "csv", "arm": arm, "repetition": 1, "workspace": str(workspace)})
        self.native = {"schemaVersion": 1, "partial": False, "claudeVersion": "fixture",
                       "cases": [{"name": "csv", "arms": {"with": [{"error": None}], "without": [{"error": None}]}}]}
        self.result_path = self.root / "native.json"
        write_json(self.result_path, self.native)
        self.plan_root = self.root / "plan"
        self.plan = prepare_native_evidence(self.plugin, self.contract, self.plan_root, references=self.references)
        self.output = self.root / "capture"

    def capture(self, **kwargs):
        return capture_native_evidence(self.plan_root, self.plan["plan_sha256"], self.plugin,
                                       self.result_path, kwargs.pop("bindings", self.bindings),
                                       self.output, references=self.references, **kwargs)

    def test_numeric_diagnosis_portable_replay_and_no_private_collection(self):
        result = self.capture()
        report = result["diagnosis"]
        self.assertTrue(report["runs"][0]["grades"][0]["passed"])
        self.assertFalse(report["runs"][1]["grades"][0]["passed"])
        self.assertFalse(report["comparison_eligible"])
        self.assertIsNone(report["settled_cost_usd"])
        self.assertFalse(list(self.output.rglob("private.txt")))
        moved = self.root / "moved"
        shutil.copytree(self.output, moved)
        self.assertEqual(verify_native_evidence(moved, result["receipt_sha256"])["status"], "REPRODUCED")

    def test_partial_and_unstarted_runs_remain_unknown(self):
        self.native["partial"] = True
        self.native["cases"][0]["arms"]["without"] = []
        write_json(self.result_path, self.native)
        report = self.capture(bindings=self.bindings[:1])["diagnosis"]
        self.assertEqual(report["runs"][1]["status"], "missing")
        self.assertIsNone(report["runs"][1]["grades"][0]["passed"])
        self.assertTrue(report["native_partial"])

    def test_missing_workspace_and_artifacts_are_not_fabricated(self):
        (self.root / "with/result.csv").unlink()
        report = self.capture(bindings=self.bindings[:1])["diagnosis"]
        self.assertTrue(all(r["grades"][0]["passed"] is None for r in report["runs"]))
        self.assertTrue(any("Missing artifacts" in x for x in report["runs"][0]["issues"]))

    def test_failed_execution_can_still_have_useful_artifact_diagnosis(self):
        self.native["cases"][0]["arms"]["with"][0]["error"] = "turn limit"
        write_json(self.result_path, self.native)
        run = self.capture()["diagnosis"]["runs"][0]
        self.assertEqual(run["status"], "error")
        self.assertIs(run["grades"][0]["passed"], True)

    def test_plan_and_case_and_reference_changes_refused_before_writing(self):
        for target in (self.plan_root / "plan.json", self.plugin / "evals/csv/prompt.md", self.references / "truth.csv"):
            original = target.read_bytes()
            if target.name == "plan.json":
                value = load_json(target)
                value["model_calls"] = 5
                write_json(target, value)
            else:
                target.write_bytes(b"changed")
            with self.assertRaises(ValidationError):
                self.capture()
            self.assertFalse(self.output.exists())
            target.write_bytes(original)

    def test_receipt_and_artifact_changes_refused(self):
        result = self.capture()
        artifact = self.output / "runs/0/artifacts/result.csv"
        artifact.write_text("id,value\na,99\n", encoding="utf-8")
        with self.assertRaises(ValidationError):
            verify_native_evidence(self.output, result["receipt_sha256"])
        with self.assertRaises(ValidationError):
            verify_native_evidence(self.output, "0" * 64)

    def test_duplicate_or_unknown_binding_and_workspace_refused(self):
        for bindings in (self.bindings * 2, [dict(self.bindings[0], repetition=2)],
                         [dict(self.bindings[0], repetition=True)],
                         [self.bindings[0], dict(self.bindings[1], workspace=self.bindings[0]["workspace"])],
                         [dict(self.bindings[0], case_id="unknown")]):
            with self.assertRaises(ValidationError):
                self.capture(bindings=bindings)

    def test_unknown_case_and_extra_repetition_refused(self):
        for native in (dict(self.native, cases=[{"name": "other", "arms": {"with": []}}]),
                       dict(self.native, cases=[{"name": "csv", "arms": {"with": [{"error": None}] * 2}}])):
            write_json(self.result_path, native)
            with self.assertRaises(ValidationError):
                self.capture()

    def test_no_overwrite(self):
        self.capture()
        with self.assertRaises(ValidationError):
            self.capture()
        with self.assertRaises(ValidationError):
            prepare_native_evidence(self.plugin, self.contract, self.plan_root, references=self.references)

    def test_added_case_file_and_changed_plugin_file_refused(self):
        new_file = self.plugin / "evals/csv/new-grader.md"
        new_file.write_text("changed evaluation", encoding="utf-8")
        with self.assertRaises(ValidationError):
            self.capture()
        new_file.unlink()
        (self.plugin / "plugin.json").write_text('{"name":"csv","version":"1"}', encoding="utf-8")
        self.plan_root = self.root / "new-plan"
        self.plan = prepare_native_evidence(self.plugin, self.contract, self.plan_root, references=self.references)
        (self.plugin / "plugin.json").write_text('{"name":"csv","version":"2"}', encoding="utf-8")
        with self.assertRaises(ValidationError):
            self.capture()

    def test_cli_freeze_capture_replay(self):
        import subprocess
        import sys
        contract_path = self.root / "contract.json"
        binding_path = self.root / "bindings.json"
        write_json(contract_path, self.contract)
        write_json(binding_path, self.bindings)
        cli = Path(__file__).resolve().parents[1] / "scripts/value_lab.py"
        def run(*args):
            result = subprocess.run([sys.executable, str(cli), *map(str, args)], capture_output=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        plan = run("prepare-native-evidence", contract_path, "--plugin", self.plugin,
                   "--references", self.references, "--output", self.root / "cli-plan")
        captured = run("capture-native-evidence", self.root / "cli-plan", "--plan-sha256", plan["plan_sha256"],
                       "--plugin", self.plugin, "--references", self.references, "--result", self.result_path,
                       "--bindings", binding_path, "--output", self.root / "cli-capture")
        replay = run("verify-native-evidence", self.root / "cli-capture", "--receipt-sha256", captured["receipt_sha256"])
        self.assertEqual(replay["status"], "REPRODUCED")
        self.assertTrue((self.root / "cli-capture/DIAGNOSIS.md").is_file())

    def test_references_cannot_be_inside_plugin_or_workspace(self):
        with self.assertRaises(ValidationError):
            prepare_native_evidence(self.plugin, self.contract, self.root / "other-plan", references=self.plugin)
        with self.assertRaises(ValidationError):
            self.capture(bindings=[dict(self.bindings[0], workspace=str(self.root))])

    def test_path_traversal_executable_grading_and_unknown_artifact_rejected(self):
        for path in ("../escape", "/abs", "C:/private", "dir\\file", "a/./b"):
            contract = deepcopy(self.contract)
            contract["cases"][0]["artifacts"]["result"] = path
            with self.assertRaises(ValidationError):
                prepare_native_evidence(self.plugin, contract, self.root / "other-plan", references=self.references)
        for change in ({"type": "executable"}, {"artifact": "missing"}):
            contract = deepcopy(self.contract)
            contract["cases"][0]["graders"][0].update(change)
            with self.assertRaises(ValidationError):
                prepare_native_evidence(self.plugin, contract, self.root / "other-plan", references=self.references)

    def test_observed_events_and_duplicate_session_rejection(self):
        for binding in self.bindings:
            stream = [{"type": "system", "subtype": "init", "session_id": binding["arm"], "model": "observed", "plugins": []},
                      {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "csv"}}]}},
                      {"type": "result", "session_id": binding["arm"], "result": "done"}]
            (Path(binding["workspace"]) / "events.jsonl").write_text("\n".join(json.dumps(e) for e in stream), encoding="utf-8")
            binding["events"] = "events.jsonl"
        report = self.capture()["diagnosis"]
        self.assertEqual(report["runs"][0]["observations"]["model"], "observed")
        self.assertEqual(report["runs"][0]["observations"]["skill_calls"], [{"skill": "csv"}])
        self.output = self.root / "second"
        shutil.copyfile(self.root / "with/events.jsonl", self.root / "without/events.jsonl")
        with self.assertRaises(ValidationError):
            self.capture()

    def test_unknown_stream_does_not_guess_load_or_output(self):
        self.assertIsNone(observe_native_events('{"text":"Skill fired"}')["plugins"])
        with self.assertRaises(ValidationError):
            observe_native_events("not JSON")

    def test_incomplete_native_trace_preserves_observed_init(self):
        observed = observe_native_events(json.dumps({"type": "system", "subtype": "init", "session_id": "observed-session", "model": "observed-model", "plugins": [{"name": "p"}]}))
        self.assertEqual(observed["session_id"], "observed-session")
        self.assertEqual(observed["plugins"], [{"name": "p"}])
        self.assertFalse(observed["trace_complete"])
        self.assertIsNone(observed["final_output"])

    def test_native_profile_links_trace_and_cwd_without_directory_guessing(self):
        retained = self.root / "retained"
        for arm in ("with", "without"):
            workspace = retained / arm / "home/cwd"
            workspace.mkdir(parents=True)
            shutil.copyfile(self.root / arm / "result.csv", workspace / "result.csv")
            trace = retained / arm / "out/trace.jsonl"
            trace.parent.mkdir()
            trace.write_text(json.dumps({"type": "system", "subtype": "init", "session_id": arm,
                                         "cwd": str(workspace), "model": "observed"}), encoding="utf-8")
            self.native["cases"][0]["arms"][arm][0]["tracePath"] = str(trace)
        self.native["claudeVersion"] = "2.1.278"
        write_json(self.result_path, self.native)
        found = discover_native_bindings(self.result_path, retained)
        self.assertFalse(found["missing"])
        result = self.capture(bindings=found["bindings"], retained_root=retained)
        self.assertEqual(result["diagnosis"]["runs"][0]["binding"]["method"], "native_tracePath_and_init_cwd")
        self.assertEqual(verify_native_evidence(self.output, result["receipt_sha256"])["status"], "REPRODUCED")
        # Swap valid trace streams between two real native run slots: reject.
        self.output = self.root / "swapped"
        found["bindings"][0]["events"] = found["bindings"][1]["events"]
        with self.assertRaises(ValidationError):
            self.capture(bindings=found["bindings"], retained_root=retained)

    def test_native_profile_accepts_os_path_aliases(self):
        retained = self.root / 'retained long directory name'
        retained.mkdir()
        alias = retained
        import os
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            get_short = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
            get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
            get_short.restype = wintypes.DWORD
            buffer = ctypes.create_unicode_buffer(32768)
            length = get_short(str(retained), buffer, len(buffer))
            self.assertGreater(length, 0)
            self.assertLess(length, len(buffer))
            alias = Path(buffer.value)
        for arm in ('with', 'without'):
            workspace = alias / arm / 'home/cwd'
            workspace.mkdir(parents=True)
            shutil.copyfile(self.root / arm / 'result.csv', workspace / 'result.csv')
            trace = alias / arm / 'out/trace.jsonl'
            trace.parent.mkdir()
            trace.write_text(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': arm,
                                         'cwd': str(workspace)}), encoding='utf-8')
            self.native['cases'][0]['arms'][arm][0]['tracePath'] = str(trace)
        self.native['claudeVersion'] = '2.1.278'
        write_json(self.result_path, self.native)
        found = discover_native_bindings(self.result_path, retained.resolve())
        self.assertFalse(found['missing'])
        result = self.capture(bindings=found['bindings'], retained_root=retained)
        self.assertEqual(verify_native_evidence(self.output, result['receipt_sha256'])['status'], 'REPRODUCED')
        # Normalization must not turn path traversal into a valid binding.
        self.native['cases'][0]['arms']['with'][0]['tracePath'] = str(alias / 'with/../with/out/trace.jsonl')
        write_json(self.result_path, self.native)
        with self.assertRaises(ValidationError):
            discover_native_bindings(self.result_path, retained)

    def test_native_profile_refuses_unsupported_versions_and_escaping_trace(self):
        with self.assertRaises(ValidationError):
            discover_native_bindings(self.result_path, self.root / "retained")
        self.native["claudeVersion"] = "2.1.278"
        write_json(self.result_path, self.native)
        self.assertEqual(len(discover_native_bindings(self.result_path, self.root / "retained")["missing"]), 2)
        self.native["cases"][0]["arms"]["with"][0]["tracePath"] = str(self.root / "private-account.json")
        write_json(self.result_path, self.native)
        with self.assertRaises(ValidationError):
            discover_native_bindings(self.result_path, self.root / "retained")

    def test_observed_linux_relocation_is_diagnosable_but_not_authenticated(self):
        retained = self.root / 'retained'
        for arm in ('with', 'without'):
            run_root = retained / ('claude-eval-' + arm)
            workspace = run_root / 'sealed/home/cwd'
            workspace.mkdir(parents=True)
            shutil.copyfile(self.root / arm / 'result.csv', workspace / 'result.csv')
            trace = run_root / 'out/trace.jsonl'
            trace.parent.mkdir()
            trace.write_text(json.dumps({'type':'system', 'subtype':'init', 'session_id':arm,
                                         'cwd':str(run_root / 'home/cwd'), 'model':'observed'}), encoding='utf-8')
            self.native['cases'][0]['arms'][arm][0]['tracePath'] = str(trace)
        self.native['claudeVersion'] = '2.1.278'
        write_json(self.result_path, self.native)
        found = discover_native_bindings(self.result_path, retained)
        self.assertFalse(found['missing'])
        result = self.capture(bindings=found['bindings'], retained_root=retained)
        run = result['diagnosis']['runs'][0]
        self.assertTrue(run['grades'][0]['passed'])
        self.assertEqual(run['binding']['method'], 'native_tracePath_init_cwd_sealed_layout')
        self.assertTrue(any('NOT verified' in issue for issue in run['issues']))
        self.assertFalse(result['diagnosis']['comparison_eligible'])
        self.assertEqual(verify_native_evidence(self.output, result['receipt_sha256'])['status'], 'REPRODUCED')
        # Reappeared home/ is ambiguous, not a reason to prefer either tree.
        (retained / 'claude-eval-with/home/cwd').mkdir(parents=True)
        with self.assertRaisesRegex(ValidationError, 'Ambiguous'):
            discover_native_bindings(self.result_path, retained)


if __name__ == "__main__":
    unittest.main()
