import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
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

    def test_research_context_diagnosis_and_revision_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            example = self.run_cli("research-example")
            self.assertEqual(example.returncode, 0, example.stderr)
            context = root / "context.json"
            context.write_text(example.stdout, encoding="utf-8")
            planned = self.run_cli("research-plan", context, "--output", root / "plan")
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual(json.loads(planned.stdout)["status"], "RESEARCH_DIAGNOSIS_ONLY")
            again = self.run_cli("research-plan", context, "--output", root / "plan")
            self.assertEqual(again.returncode, 2)
            compared = self.run_cli("research-compare", context, context, "--output", root / "comparison.json")
            self.assertEqual(compared.returncode, 0, compared.stderr)
            self.assertTrue((root / "comparison.json").is_file())
            duplicate = self.run_cli("research-compare", context, context, "--output", root / "comparison.json")
            self.assertEqual(duplicate.returncode, 2)


if __name__ == "__main__":
    unittest.main()
