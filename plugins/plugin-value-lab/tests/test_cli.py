import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def test_json_streams_round_trip_unicode_under_legacy_encodings(self):
        from value_lab.cli import _emit
        payload = {'路径': '新同事/结果 🧬.json', 'value': None, 'ok': True}
        for encoding in ('cp1252', 'ascii', 'utf-8'):
            for output in ('stdout', 'stderr'):
                with self.subTest(encoding=encoding, output=output):
                    buffer = io.BytesIO()
                    with io.TextIOWrapper(buffer, encoding=encoding, errors='strict') as stream:
                        if output == 'stdout':
                            with contextlib.redirect_stdout(stream):
                                _emit(payload)
                        else:
                            _emit(payload, stream=stream)
                        stream.flush()
                        raw = buffer.getvalue()
                        self.assertEqual(json.loads(raw.decode('ascii')), payload)
        with self.assertRaises(ValueError):
            _emit({'invalid': float('nan')})

    def test_redirected_unicode_success_errors_and_utf8_files(self):
        for encoding in ('cp1252:strict', 'ascii:strict'):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / '中文 workspace 🧬'
                root.mkdir()
                env = dict(os.environ, PYTHONIOENCODING=encoding, PYTHONUTF8='0')
                def run(*args):
                    return subprocess.run([sys.executable, str(ROOT / 'scripts/value_lab.py'), *map(str, args)],
                                          capture_output=True, env=env, timeout=30)
                context = root / '输入.json'
                # Source JSON is UTF-8, independent of stdout's legacy encoding.
                data = {'schema_version': 1, 'intent': 'choose',
                        'task': {'summary': '中文研究 🧬', 'capability': 'web reading'},
                        'native_fit': 'sufficient', 'connected_fit': 'unknown',
                        'plugin_management_available': False}
                context.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
                result = run('plan-use', context, '--output', root / '输出')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIsInstance(json.loads(result.stdout.decode('ascii')), dict)
                contents = '\n'.join(p.read_text(encoding='utf-8') for p in (root / '输出').rglob('*') if p.is_file())
                self.assertIn(data['task']['summary'], contents)
                missing = root / '不存在.json'
                result = run('freeze', missing, '--lock', root / 'lock.json')
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, b'')
                error = json.loads(result.stderr.decode('ascii'))
                self.assertEqual(error['status'], 'INVALID_INPUT')
                self.assertIn('不存在.json', error['error'])
                # A file handle, rather than PIPE, must use the same contract.
                with (root / 'stdout.json').open('wb') as stdout, (root / 'stderr.json').open('wb') as stderr:
                    result = subprocess.run([sys.executable, str(ROOT / 'scripts/value_lab.py'),
                        'freeze', str(missing), '--lock', str(root / 'lock.json')],
                        stdout=stdout, stderr=stderr, env=env, timeout=30)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads((root / 'stderr.json').read_bytes()), error)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "value_lab.py"), *map(str, args)],
                              capture_output=True, encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=30)

    def test_demo_runs_offline_and_gate_refuses_simulation(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "demo"
            result = self.run_cli("demo", "--output", out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["verdict"], "SIMULATION_ONLY")
            self.assertTrue((out / "report.html").exists())
            result = self.run_cli("evaluate", out / "suite.json", out / "runs.jsonl", "--lock",
                                  out / "protocol.lock.json", "--output", Path(directory) / "gated", "--gate")
            self.assertEqual(result.returncode, 2)

    def test_init_is_blank_and_preserves_existing_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "study"
            result = self.run_cli("init", "--output", out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((out / "runs.jsonl").read_text(encoding="utf-8"), "")
            self.assertFalse((out / "protocol.lock.json").exists())
            again = self.run_cli("init", "--output", out)
            self.assertEqual(again.returncode, 2)

    def test_plan_and_usage_card_are_real_artifacts_without_external_action(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = root / "context.json"
            context.write_text(json.dumps({"schema_version": 1, "intent": "choose",
                "task": {"summary": "Summarize a public page", "capability": "web reading"},
                "native_fit": "sufficient", "connected_fit": "unknown", "plugin_management_available": False}), encoding="utf-8")
            plan = self.run_cli("plan-use", context, "--output", root / "plan")
            self.assertEqual(plan.returncode, 0, plan.stderr)
            self.assertEqual(json.loads(plan.stdout)["route"], "USE_NATIVE")
            self.assertTrue((root / "plan" / "PLAN.md").is_file())
            demo = self.run_cli("demo", "--output", root / "demo")
            self.assertEqual(demo.returncode, 0, demo.stderr)
            card = self.run_cli("usage-card", root / "demo" / "suite.json", root / "demo" / "runs.jsonl",
                                "--lock", root / "demo" / "protocol.lock.json", "--output", root / "card")
            self.assertEqual(card.returncode, 0, card.stderr)
            payload = json.loads((root / "card" / "card.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "TRIAL_GUIDANCE_ONLY")
            self.assertEqual(payload["use_when"], [])
            self.assertTrue((root / "card" / "USAGE.md").is_file())

    def test_default_help_and_commands_exclude_extensions(self):
        help_text = self.run_cli("--help")
        self.assertEqual(help_text.returncode, 0)
        for command in ("research-example", "research-plan", "research-compare", "research-followup", "team-card"):
            self.assertNotIn(command, help_text.stdout)
            result = self.run_cli(command)
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid choice", result.stderr)

    def test_research_context_diagnosis_and_revision_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            example = self.run_cli("--enable-extensions", "research-example")
            self.assertEqual(example.returncode, 0, example.stderr)
            context = root / "context.json"
            context.write_text(example.stdout, encoding="utf-8")
            planned = self.run_cli("--enable-extensions", "research-plan", context, "--output", root / "plan")
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual(json.loads(planned.stdout)["status"], "RESEARCH_DIAGNOSIS_ONLY")
            again = self.run_cli("--enable-extensions", "research-plan", context, "--output", root / "plan")
            self.assertEqual(again.returncode, 2)
            compared = self.run_cli("--enable-extensions", "research-compare", context, context, "--output", root / "comparison.json")
            self.assertEqual(compared.returncode, 0, compared.stderr)
            self.assertTrue((root / "comparison.json").is_file())
            duplicate = self.run_cli("--enable-extensions", "research-compare", context, context, "--output", root / "comparison.json")
            self.assertEqual(duplicate.returncode, 2)


    def test_registry_revision_review_export_and_pinned_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            study, registry = root / "study", root / "registry"
            self.assertEqual(self.run_cli("demo", "--output", study).returncode, 0)
            metadata = {"observed_at": "2026-09-23T12:00:00Z",
                "authors": [{"id": "synthetic-author", "organization": "synthetic-lab"}],
                "plugin_sha256": "a" * 64, "limitations": "Unit test only; no research observations"}
            (root / "metadata.json").write_text(json.dumps(metadata))
            def add(*extra):
                return self.run_cli("registry-add", study, "--metadata", root / "metadata.json", "--registry", registry, *extra)
            first = add()
            self.assertEqual(first.returncode, 0, first.stderr)
            eid = json.loads(first.stdout)["entry_id"]
            (study / "cost-ledger.json").write_text(json.dumps({"schema_version": 1,
                "coverage": {k: "included" for k in ("judge", "setup", "retry", "other")}, "entries": []}))
            self.assertEqual(add("--parent", eid).returncode, 2)
            revision = add("--parent", eid, "--revision-reason", "Synthetic test: supply cost coverage")
            self.assertEqual(revision.returncode, 0, revision.stderr)
            new_id = json.loads(revision.stdout)["entry_id"]
            review = {"entry_id": eid, "reviewer": "synthetic-reviewer", "organization": "synthetic-lab",
                "relationship": "collaborator", "conflicts": [], "verdict": "dispute", "rationale": "Synthetic test dissent",
                "reviewed_at": "2026-09-23T13:00:00Z", "evidence": [{"reference": "test-fixture-only", "sha256": "b" * 64}],
                "replication_entry_id": None}
            (root / "review.json").write_text(json.dumps(review))
            result = self.run_cli("registry-review", root / "review.json", "--registry", registry)
            self.assertEqual(result.returncode, 0, result.stderr)
            packet = root / "packet"
            exported = self.run_cli("registry-export", new_id, "--registry", registry, "--output", packet, "--with-reviews")
            self.assertEqual(exported.returncode, 0, exported.stderr)
            receipt = json.loads(exported.stdout)
            checked = self.run_cli("registry-verify", packet, "--expected-id", receipt["packet_id"])
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(json.loads(checked.stdout)["review_status"], "ANCESTOR_DISPUTED")
            replayed = self.run_cli("registry-replay", packet)
            self.assertEqual(replayed.returncode, 0, replayed.stderr)
            self.assertEqual(json.loads(replayed.stdout)["scientific_replication"], "NOT_ESTABLISHED")
            self.assertEqual(self.run_cli("registry-verify", packet, "--expected-id", "f" * 64).returncode, 2)
            viewed = self.run_cli("registry-view", "--registry", registry, "--output", root / "view")
            self.assertEqual(viewed.returncode, 0, viewed.stderr)
            self.assertEqual(json.loads(viewed.stdout)["counts"]["study_lineages"], 1)


if __name__ == "__main__":
    unittest.main()
