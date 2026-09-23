"""Real subprocess/HTTP tests with synthetic payloads; no provider calls."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from value_lab.core import ValidationError
from value_lab.execution import Engine, digest, read, save
from value_lab.workbench import create_server


REAL_POPEN = subprocess.Popen
FIXTURE = Path(__file__).with_name("fixture_native_process.py")


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plugin = self.root / "plugin with 空格"
        self.plugin.mkdir()
        save(self.plugin / "plugin.json", {"name": "fixture", "version": "1.0"})
        self.engine = Engine(self.root / "evidence", sys.executable)
        self.addCleanup(self.engine.close)
        self.patches = [patch("value_lab.execution.preflight", return_value={"version": "2.1.278 synthetic test", "executable_sha256": digest(sys.executable)})]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.data = {"plugin_path": str(self.plugin), "model": "SYNTHETIC-NOT-A-MODEL", "runs": 1, "budget_usd": 0.1,
                     "cases": [{"prompt": "Task A", "criterion": "A", "cluster": "a"},
                               {"prompt": "Task B", "criterion": "B", "cluster": "b", "kind": "negative"}]}

    def prepare(self, mode="normal"):
        (self.plugin / "fixture-mode.txt").write_text(mode)
        return self.engine.prepare(deepcopy(self.data))

    def start(self, detail):
        state = detail["state"]
        def launch(argv, **kwargs):
            return REAL_POPEN([sys.executable, str(FIXTURE), *argv[1:]], **kwargs)
        with patch("value_lab.execution.subprocess.Popen", side_effect=launch):
            self.engine.start(state["id"], {"authorize_execution": True, "frozen_sha256": state["frozen_sha256"]})
            # Keep the fixture substitution live until launch is observed.
            deadline = time.monotonic() + 5
            while not (self.root / "evidence" / state["id"] / "stdout.log").exists() and time.monotonic() < deadline:
                time.sleep(.01)
            while not self.engine.processes and time.monotonic() < deadline:
                if read(self.engine.directory(state["id"]) / "state.json")["status"] != "running":
                    break
                time.sleep(.01)

    def wait(self, job):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            detail = self.engine.detail(job)
            if detail["state"]["status"] not in ("running", "stopping"):
                return detail
            time.sleep(.02)
        self.fail("Fixture did not finish")

    def test_prepare_freezes_copy_without_model_calls(self):
        detail = self.prepare()
        self.assertEqual(detail["state"]["status"], "frozen")
        self.assertFalse((self.plugin / "value-lab-evals").exists())
        cmd = detail["frozen.json"]["command"]
        for flag in ("--no-publish", "--json", "--trust-plugin", "--no-scaffold"):
            self.assertIn(flag, cmd)
        self.assertNotIn("--allow-real-servers", cmd)
        self.assertFalse(self.engine.processes)

    def test_launch_collects_raw_failure_sensitive_evidence_and_remains_incomplete(self):
        detail = self.prepare()
        self.start(detail)
        result = self.wait(detail["state"]["id"])
        self.assertEqual(result["state"]["status"], "needs_evidence", result)
        self.assertEqual(result["state"]["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["state"]["observed_runs"], 4)
        self.assertIsNone(result["state"]["settled_cost_usd"])
        self.assertIn("execution-receipt.json", result["files"])
        self.assertIn("usage-card/card.json", result["files"])
        self.assertEqual(result["integrity"]["mismatches"], [])
        with self.assertRaises(ValidationError):
            self.engine.start(detail["state"]["id"], {"authorize_execution": True})

    def test_approval_is_bound_to_exact_frozen_plan(self):
        detail = self.prepare()
        for approval in ({}, {"authorize_execution": True, "frozen_sha256": "stale"}):
            with self.assertRaises(ValidationError):
                self.engine.start(detail["state"]["id"], approval)
        self.assertFalse(self.engine.processes)

    def test_changed_and_added_snapshot_files_refuse_before_launch(self):
        detail = self.prepare()
        path = self.engine.directory(detail["state"]["id"])
        (path / "plugin/new-skill.txt").write_text("changed")
        with self.assertRaises(ValidationError):
            self.engine.start(detail["state"]["id"], {"authorize_execution": True, "frozen_sha256": detail["state"]["frozen_sha256"]})

    def test_partial_does_not_invent_unstarted_runs_or_retry(self):
        detail = self.prepare("partial")
        self.start(detail)
        result = self.wait(detail["state"]["id"])
        self.assertEqual(result["state"]["status"], "partial")
        self.assertEqual(result["state"]["observed_runs"], 2)
        self.assertEqual(result["state"]["exit_code"], 1)

    def test_failure_and_malformed_json_preserve_logs_and_unknown_cost(self):
        for mode, status in (("failure", "failed"), ("malformed", "collection_failed")):
            detail = self.prepare(mode)
            self.start(detail)
            result = self.wait(detail["state"]["id"])
            self.assertEqual(result["state"]["status"], status)
            self.assertIsNone(result["state"]["estimated_cost_usd"])
            self.assertIn("stderr.log", result["files"])

    def test_cancel_stops_process_and_retains_evidence(self):
        detail = self.prepare("sleep")
        self.start(detail)
        self.engine.stop(detail["state"]["id"])
        result = self.wait(detail["state"]["id"])
        self.assertEqual(result["state"]["status"], "cancelled")
        self.assertEqual(result["state"]["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_deadline_stops_process_without_automatic_retry(self):
        detail = self.prepare("sleep")
        path = self.engine.directory(detail["state"]["id"])
        frozen = read(path / "frozen.json")
        frozen["timeout_seconds"] = .2
        save(path / "frozen.json", frozen)
        state = read(path / "state.json")
        state["frozen_sha256"] = digest(path / "frozen.json")
        save(path / "state.json", state)
        self.start(self.engine.detail(state["id"]))
        result = self.wait(state["id"])
        self.assertEqual(result["state"]["status"], "timed_out")
        self.assertIsNone(result["state"]["estimated_cost_usd"])

    def test_sealed_evidence_tamper_is_visible(self):
        detail = self.engine.demo()
        path = self.engine.directory(detail["state"]["id"])
        (path / "runs.jsonl").write_text("tampered")
        changed = self.engine.detail(detail["state"]["id"])
        self.assertIn("runs.jsonl", changed["integrity"]["mismatches"])

    def test_single_owner_and_restart_do_not_retry(self):
        with self.assertRaises(ValidationError):
            Engine(self.root / "evidence")
        detail = self.prepare()
        path = self.engine.directory(detail["state"]["id"])
        state = read(path / "state.json")
        state["status"] = "running"
        save(path / "state.json", state)
        self.engine.close()
        self.engine = Engine(self.root / "evidence", sys.executable)
        self.addCleanup(self.engine.close)
        self.assertEqual(self.engine.detail(state["id"])["state"]["status"], "interrupted")
        self.assertFalse(self.engine.processes)

    def test_unsupported_tools_and_secrets_rejected(self):
        (self.plugin / ".env").write_text("fixture-key=NOT-A-SECRET")
        with self.assertRaises(ValidationError):
            self.prepare()


class WorkbenchHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = Engine(Path(self.temp.name) / "evidence")
        self.server = create_server(self.engine, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.token = self.get("/api/bootstrap")["token"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.engine.close()
        self.temp.cleanup()

    def get(self, path):
        with urlopen(self.base + path) as response:
            return json.load(response)

    def post(self, path, headers=None):
        request = Request(self.base + path, data=b"{}", headers=headers or {
            "Content-Type": "application/json", "X-Value-Lab-Token": self.token})
        return urlopen(request)

    def test_http_demo_report_and_safe_download(self):
        with self.post("/api/demo") as response:
            detail = json.load(response)
        job = detail["state"]["id"]
        self.assertEqual(detail["state"]["verdict"], "SIMULATION_ONLY")
        with urlopen(self.base + f"/api/studies/{job}/files/report/report.html") as response:
            self.assertEqual(response.headers["Content-Disposition"], "attachment")
            self.assertIn("text/plain", response.headers["Content-Type"])
        with self.assertRaises(HTTPError):
            urlopen(self.base + f"/api/studies/{job}/files/../../.owner.lock")

    def test_cross_site_and_missing_token_rejected(self):
        for headers in ({"Content-Type": "application/json"},
                        {"Content-Type": "application/json", "X-Value-Lab-Token": self.token, "Origin": "https://evil.invalid"}):
            with self.assertRaises(HTTPError) as error:
                self.post("/api/demo", headers)
            self.assertEqual(error.exception.code, 400)
        self.assertEqual(self.engine.list(), [])

    def test_dns_rebinding_host_rejected(self):
        with self.assertRaises(HTTPError):
            urlopen(Request(self.base + "/api/bootstrap", headers={"Host": "evil.invalid"}))

    def test_rules_comparison_and_cost_revision_routes(self):
        def submit(path, payload):
            with urlopen(Request(self.base + path, data=json.dumps(payload).encode(), headers={
                "Content-Type": "application/json", "X-Value-Lab-Token": self.token})) as response:
                return json.load(response)
        checked = submit("/api/rules/check", {"model": "fixture", "budget_usd": .1, "runs": 1,
            "cases": [{"prompt": "Task", "criterion": "OK"}], "samples": {"case-1": ["OK"]}})
        self.assertTrue(checked["valid"])
        self.assertEqual(checked["cases"][0]["samples"][0]["score"], 1)
        first, second = submit("/api/demo", {}), submit("/api/demo", {})
        job = first["state"]["id"]
        book = {"schema_version": 1, "entries": [], "coverage": {k: "included" for k in ("judge", "setup", "retry", "other")}}
        revised = submit(f"/api/studies/{job}/costs", book)
        self.assertIn("analysis", revised)
        costs = self.get(f"/api/costs/{job}")
        self.assertTrue(costs["complete_category_coverage"])
        self.assertFalse(costs["saving_claim_eligible"])
        compared = submit("/api/compare", {"before": job, "after": second["state"]["id"]})
        self.assertEqual(compared["status"], "SIMULATION_ONLY")
        with urlopen(self.base + "/analysis.js") as response:
            self.assertEqual(response.status, 200)

    def test_research_routes_diagnose_without_starting_agent(self):
        context = self.get("/api/research/example")
        def submit(path, payload):
            with urlopen(Request(self.base + path, data=json.dumps(payload).encode(), headers={
                "Content-Type": "application/json", "X-Value-Lab-Token": self.token})) as response:
                return json.load(response)
        plan = submit("/api/research/diagnose", context)
        self.assertEqual(plan["status"], "RESEARCH_DIAGNOSIS_ONLY")
        self.assertEqual(plan["scientific_authorization"], "NONE")
        self.assertIn("status", submit("/api/research/compare", {"before": context, "after": context}))
        followup = submit("/api/research/followup", {"context": context, "update": {
            "direction_id": "check-confounding", "result": "Synthetic fixture",
            "source": "fixture", "signal": "inconclusive", "interpretation": "Needs review"}})
        self.assertEqual(followup["status"], "REASSESSMENT_REQUIRED")
        self.assertIn("orthogonal-measure", followup["affected_direction_ids"])
        with self.assertRaises(HTTPError):
            submit("/api/research/diagnose", {**context, "unknown_input": True})
        with self.assertRaises(HTTPError):
            submit("/api/research/compare", {"before": context, "after": context, "ignored": True})
        with self.assertRaises(HTTPError):
            submit("/api/research/followup", {"context": context, "update": {}, "ignored": True})
        self.assertEqual(self.engine.list(), [])
        self.assertFalse(self.engine.processes)
        with urlopen(self.base + "/research.js") as response:
            self.assertEqual(response.status, 200)

    def test_team_record_route_preserves_history_and_explicit_decision(self):
        def submit(path, payload):
            with urlopen(Request(self.base + path, data=json.dumps(payload).encode(), headers={
                "Content-Type": "application/json", "X-Value-Lab-Token": self.token})) as response:
                return json.load(response)
        study = submit("/api/demo", {})["state"]["id"]
        decision = {"actor": "fixture reviewer", "choice": "undecided", "rationale": "Synthetic only"}
        first = submit("/api/team-records", {"study_id": study, "decision": decision,
                                             "previous_id": None, "research_context": None})
        self.assertEqual(first["record"]["entries"][0]["card"]["status"], "TRIAL_GUIDANCE_ONLY")
        self.assertEqual(len(self.get("/api/team-records")), 1)
        second = submit("/api/team-records", {"study_id": study, "decision": decision,
                                              "previous_id": first["id"], "research_context": None})
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["record"]["entries"][0], first["record"]["entries"][0])
        self.assertEqual(self.get("/api/team-records/" + second["id"])["entries"][-1]["revision"], 2)
        with urlopen(self.base + "/team.js") as response:
            self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
