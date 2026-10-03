"""Risk-bound algebra, prospective history, abstentions and matched comparisons."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from value_lab.core import ValidationError, suite_digest
from value_lab.risk_acquisition import analyze, decision, empty_stats, intervals, risk_identity
from value_lab.task_selection import select_task_plan
from value_lab.workflow import plan_plugin_use, write_plan
from scripts.check_risk_acquisition import protocol, simulate, compare
from tests.test_evidence_acquisition import example

ROOT = Path(__file__).resolve().parents[1]


def results(plan, spec, utilities=None):
    utilities = utilities or {"c0": 1.0, "c1": 0.0, "c2": 0.0}
    return [{"candidate_id": candidate, "unit_id": unit, "input_sha256": suite_digest({"unit": unit}),
             "session_id": candidate + "-" + unit, "assessment_sha256": suite_digest({"unit": unit, "candidate": candidate, "utility": utilities[candidate]}),
             "utility_contract_sha256": suite_digest(spec["utility_contract"]), "status": "observed", "utility": utilities[candidate],
             "cost_micros": 1, "runs_started": spec["runs_per_unit"]}
            for candidate in plan["candidate_ids"] for unit in plan["unit_ids"]]


def context(root):
    original, *_ = example.fixture(root)
    selection = original["task_selection"]
    base = select_task_plan(selection)
    spec = protocol(3)
    spec.update(catalog_sha256=base["catalog_sha256"], task_sha256=suite_digest(selection["task"]),
                max_units_per_candidate=128, batch_units=4)
    for candidate, plan in zip(spec["candidates"], base["plans"]):
        candidate["plan_sha256"] = plan["plan_sha256"]
    return {"schema_version": 1, "intent": "choose", "task_selection": selection,
            "risk_acquisition": {"protocol": spec, "protocol_sha256": suite_digest(spec), "batches": []}}


class RiskAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.spec = protocol(3)
        self.spec.update(max_units_per_candidate=128, batch_units=4)
        self.request = {"protocol": self.spec, "protocol_sha256": suite_digest(self.spec), "batches": []}

    def freeze(self):
        self.request["protocol_sha256"] = suite_digest(self.spec)

    def advance(self, values=None):
        view = analyze(self.request)
        self.assertEqual(view["state"], "NEXT_BLOCK")
        batch = {"plan": view["next_block"], "result": results(view["next_block"], self.spec, values)}
        self.request["batches"].append(batch)
        return batch

    def finish(self, values=None):
        for _ in range(128):
            view = analyze(self.request)
            if not view["next_block"]:
                return view
            self.advance(values)
        self.fail("bounded protocol did not stop")

    def test_deterministic_success_certifies_at_frozen_risk_without_adoption(self):
        result = self.finish()
        self.assertEqual(result["state"], "CERTIFIED_CANDIDATE")
        self.assertEqual(result["certified_candidate_id"], "c0")
        self.assertIsNone(result["candidate_for_confirmation"])
        self.assertIsNone(result["selected_plan_sha256"])
        self.assertFalse(result["efficiency_gain_established"])
        self.assertFalse(result["statistical_guarantee"]["assumptions_verified"])
        self.assertEqual(result["statistical_guarantee"]["family_error_upper_bound"], 0.05)

    def test_none_acceptable_is_a_certified_useful_decision(self):
        result = self.finish({"c0": 0, "c1": 0, "c2": 0})
        self.assertEqual(result["state"], "CERTIFIED_NO_ACCEPTABLE_CANDIDATE")
        self.assertIsNone(result["certified_candidate_id"])

    def test_low_budget_is_abstention_not_savings(self):
        self.spec["max_total_units"] = 0
        self.freeze()
        result = analyze(self.request)
        self.assertEqual(result["state"], "STOP_BUDGET_UNRESOLVED")
        self.assertIsNone(result["certified_candidate_id"])
        self.assertFalse(result["efficiency_gain_established"])

    def test_horizon_near_boundary_preserves_uncertainty(self):
        self.spec.update(max_units_per_candidate=4, batch_units=4)
        self.freeze()
        self.advance({"c0": 0.5, "c1": 0.5, "c2": 0.5})
        result = analyze(self.request)
        self.assertEqual(result["state"], "STOP_HORIZON_UNRESOLVED")
        self.assertIsNone(result["candidate_for_confirmation"])

    def test_post_stop_sampling_rejected(self):
        self.finish()
        self.request["batches"].append(deepcopy(self.request["batches"][-1]))
        with self.assertRaisesRegex(ValidationError, "after"):
            analyze(self.request)

    def test_pending_block_reserves_full_cost_and_cannot_restart(self):
        batch = self.advance()
        batch["result"] = None
        view = analyze(self.request)
        self.assertEqual(view["state"], "WAIT_FOR_ORIGINAL_BLOCK")
        self.assertEqual(view["budget"]["spent_or_reserved_micros"], batch["plan"]["reserved_micros"])
        self.assertIsNone(view["budget"]["total_cost_micros"])
        self.assertIsNone(view["next_block"])

    def test_unknown_outcome_is_not_zero_and_costs_retained(self):
        batch = self.advance()
        batch["result"][0].update(status="unknown", utility=None, cost_micros=None)
        result = analyze(self.request)
        self.assertEqual(result["state"], "REPAIR_EVIDENCE")
        self.assertEqual(result["candidate_units_started"], 12)
        self.assertEqual(result["candidate_units_received"], 12)
        self.assertEqual(result["candidate_units_resolved"], 11)
        self.assertIsNone(result["budget"]["total_cost_micros"])
        self.assertEqual(result["intervals"]["c0"]["n"], 0)
        batch["result"][0]["utility"] = 0
        with self.assertRaisesRegex(ValidationError, "imputed"):
            analyze(self.request)

    def test_missing_cells_remain_in_denominator_and_reservations(self):
        batch = self.advance()
        batch["result"].pop()
        view = analyze(self.request)
        self.assertEqual(view["candidate_units_started"], 12)
        self.assertEqual(view["observations"][0]["missing"], 1)
        self.assertEqual(view["budget"]["spent_or_reserved_micros"], 21)
        self.assertIsNone(view["next_block"])

    def test_failures_are_observations_and_cannot_be_deleted_or_scored_as_success(self):
        batch = self.advance()
        batch["result"][0].update(status="failed", utility=0)
        view = analyze(self.request)
        self.assertEqual(view["failed_units"], 1)
        self.assertEqual(view["intervals"]["c0"]["n"], 4)
        self.assertEqual(view["intervals"]["c0"]["mean"], 0.75)
        batch["result"][0]["utility"] = 1
        with self.assertRaisesRegex(ValidationError, "zero utility"):
            analyze(self.request)

    def test_overrun_is_not_clipped(self):
        batch = self.advance()
        batch["result"][0]["cost_micros"] = 10000
        view = analyze(self.request)
        self.assertEqual(view["budget"]["spent_or_reserved_micros"], 10011)
        self.assertEqual(view["state"], "REPAIR_EVIDENCE")

    def test_protocol_cannot_change_alpha_or_drop_candidate_after_outcome(self):
        self.advance()
        original = deepcopy(self.request)
        for change in ("alpha", "candidate", "utility", "horizon"):
            self.request = deepcopy(original)
            self.spec = self.request["protocol"]
            if change == "alpha":
                self.spec["alpha"] = 0.1
            elif change == "candidate":
                self.spec["candidates"].pop()
            elif change == "utility":
                self.spec["utility_contract"]["new"] = "rule"
            else:
                self.spec["max_units_per_candidate"] += 1
            self.freeze()
            with self.assertRaisesRegex(ValidationError, "assignment"):
                analyze(self.request)

    def test_matched_inputs_and_no_reused_experimental_units(self):
        self.advance()
        batch = self.advance()
        batch["result"][0]["input_sha256"] = self.request["batches"][0]["result"][0]["input_sha256"]
        with self.assertRaisesRegex(ValidationError, "reused"):
            analyze(self.request)

    def test_repeated_input_with_new_unit_name_rejected(self):
        batch = self.advance()
        batch["result"][1]["input_sha256"] = batch["result"][0]["input_sha256"]
        with self.assertRaisesRegex(ValidationError, "Renamed"):
            analyze(self.request)

    def test_duplicate_session_and_record_rejected(self):
        batch = self.advance()
        batch["result"][1]["session_id"] = batch["result"][0]["session_id"]
        with self.assertRaisesRegex(ValidationError, "session reused"):
            analyze(self.request)
        batch["result"][1] = deepcopy(batch["result"][0])
        with self.assertRaisesRegex(ValidationError, "Duplicate"):
            analyze(self.request)

    def test_execution_repeats_do_not_inflate_independent_unit_count(self):
        self.spec["runs_per_unit"] = 5
        self.freeze()
        self.advance()
        view = analyze(self.request)
        self.assertEqual(view["planned_runs_started"], 60)
        self.assertEqual(view["intervals"]["c0"]["n"], 4)
        self.assertEqual(view["independent_input_blocks_started"], 4)

    def test_partial_unit_cannot_look_complete(self):
        self.spec["runs_per_unit"] = 3
        self.freeze()
        batch = self.advance()
        batch["result"][0]["runs_started"] = 1
        self.assertEqual(analyze(self.request)["state"], "REPAIR_EVIDENCE")

    def test_unknown_sampling_assumption_removes_guarantee(self):
        self.spec["assumptions"]["independent_units"] = None
        self.freeze()
        view = analyze(self.request)
        self.assertEqual(view["state"], "REVIEW_SAMPLING_ASSUMPTIONS")
        self.assertIsNone(view["statistical_guarantee"]["family_error_upper_bound"])
        self.assertIsNone(view["next_block"])

    def test_discovered_drift_retains_history_but_revokes_statistical_choice(self):
        self.finish()
        before = deepcopy(self.request["batches"])
        self.request["assumption_violations"] = ["Target task population changed"]
        view = analyze(self.request)
        self.assertEqual(view["state"], "REVIEW_SAMPLING_ASSUMPTIONS")
        self.assertEqual(self.request["batches"], before)
        self.assertIsNone(view["certified_candidate_id"])
        self.assertEqual(view["statistical_guarantee"]["status"], "UNAVAILABLE")

    def test_repeated_reads_do_not_add_evidence(self):
        self.advance()
        first = analyze(self.request)
        self.assertEqual(analyze(self.request), first)

    def test_submitted_candidate_still_cannot_bypass_scientific_confirmation(self):
        self.spec["evidence_type"] = "submitted_observations"
        self.freeze()
        self.assertEqual(analyze(self.request)["evidence_status"], "NO_OBSERVATIONS")
        result = self.finish()
        self.assertEqual(result["candidate_for_confirmation"], "c0")
        self.assertIsNone(result["selected_plan_sha256"])
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(result["utility_evidence_basis"], "SUBMITTED_UTILITY_WITH_HASH_BINDINGS_NOT_INDEPENDENTLY_REGRADED")

    def test_schema_accepts_complete_history_and_rejects_hidden_control(self):
        import jsonschema
        self.advance()
        schema = json.loads((ROOT / "schemas/risk-acquisition.schema.json").read_bytes())
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(self.request, schema)
        self.request["protocol"]["force_choice"] = True
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(self.request, schema)

    def test_invalid_numbers_and_utilities_fail_closed(self):
        self.advance()
        for invalid in (True, -0.1, 1.1, float("nan"), float("inf")):
            self.request["batches"][0]["result"][0]["utility"] = invalid
            with self.assertRaises((ValidationError, ValueError)):
                analyze(self.request)


class RiskBoundTests(unittest.TestCase):
    def test_exact_bernoulli_crossing_probability_within_candidate_budget(self):
        spec = protocol(2)
        spec["max_units_per_candidate"] = 40
        for mean in (0.05, 0.2, 0.5, 0.8, 0.95):
            live, crossed = {0: 1.0}, 0.0
            for n in range(1, 41):
                following = {}
                for total, probability in live.items():
                    for outcome, chance in ((0, 1 - mean), (1, mean)):
                        sums = total + outcome
                        stats = empty_stats(spec)
                        stats["c0"] = {"n": n, "sum": sums}
                        row = intervals(spec, stats)["c0"]
                        if not row["lower"] <= mean <= row["upper"]:
                            crossed += probability * chance
                        else:
                            following[sums] = following.get(sums, 0) + probability * chance
                live = following
            self.assertLessEqual(crossed, spec["alpha"] / 2 + 1e-12)
            self.assertAlmostEqual(crossed + sum(live.values()), 1.0)

    def test_only_allocation_can_change_in_same_risk_comparison(self):
        first = protocol()
        second = {**deepcopy(first), "allocation": "uniform_all"}
        self.assertEqual(risk_identity(first), risk_identity(second))
        for key, value in (("epsilon", 0.5), ("quality_floor", 0.1), ("alpha", 0.1), ("budget_micros", 0)):
            changed = {**second, key: value}
            self.assertNotEqual(risk_identity(first), risk_identity(changed))

    def test_abstaining_for_zero_cost_never_establishes_efficiency(self):
        spec = protocol(2)
        spec["max_total_units"] = 0
        adaptive = [simulate(spec, (0.9, 0.8), i) for i in range(5)]
        uniform = [simulate({**spec, "allocation": "uniform_all"}, (0.9, 0.8), i) for i in range(5)]
        report = compare(spec, adaptive, uniform)
        self.assertEqual(report["efficiency_status"], "NOT_ESTABLISHED")
        self.assertEqual(report["adaptive"]["useful_decision_rate"], 0)
        self.assertIsNone(report["adaptive"]["wrong_among_issued"])

    def test_comparison_rejects_larger_epsilon_and_duplicated_replications(self):
        spec = protocol(2)
        spec["max_total_units"] = 0
        a = simulate(spec, (0.9, 0.8), 1)
        u = simulate({**spec, "allocation": "uniform_all", "epsilon": 0.9}, (0.9, 0.8), 1)
        with self.assertRaisesRegex(ValueError, "preserve risk"):
            compare(spec, [a], [u])
        u = simulate({**spec, "allocation": "uniform_all"}, (0.9, 0.8), 1)
        with self.assertRaisesRegex(ValueError, "Repeated"):
            compare(spec, [a, a], [u, u])

    def test_applicable_certificate_implies_oracle_loss_and_floor_on_coverage_event(self):
        spec = protocol(3)
        spec["max_units_per_candidate"] = 2048
        stats = {"c0": {"n": 2048, "sum": 2048 * 0.90}, "c1": {"n": 2048, "sum": 2048 * 0.40}, "c2": {"n": 2048, "sum": 2048 * 0.35}}
        state, chosen, rows = decision(spec, stats)
        self.assertEqual(state, "CERTIFIED_CANDIDATE")
        # Enumerate interval endpoints: the least favorable valid mean vector
        # must still satisfy both parts of the frozen useful-decision target.
        self.assertGreaterEqual(rows[chosen]["lower"], spec["quality_floor"])
        self.assertLessEqual(max(r["upper"] for i, r in rows.items() if i != chosen) - rows[chosen]["lower"], spec["epsilon"])

    def test_fewer_experiments_with_lost_decisions_does_not_pass_efficiency(self):
        spec = protocol(2)
        adaptive, uniform = [], []
        for i in range(1000):
            common = {"risk_identity": risk_identity(spec), "replication_id": str(i), "oracle_sha256": "fixture", "wrong": False, "regret": None}
            adaptive.append({**common, "allocation": "adaptive_frontier", "issued": False, "useful": False, "units": 0, "cost_micros": 0})
            uniform.append({**common, "allocation": "uniform_all", "issued": True, "useful": True, "units": 4096, "cost_micros": 40960})
        report = compare(spec, adaptive, uniform)
        self.assertGreater(report["mean_paired_units_saved"], 0)
        self.assertEqual(report["adaptive"]["wrong_decisions"], 0)
        self.assertEqual(report["efficiency_status"], "NOT_ESTABLISHED")


class RiskWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.context = context(self.root)

    def test_existing_plan_entry_and_report_reach_risk_mode(self):
        report = plan_plugin_use(self.context)
        self.assertEqual(report["route"], "RISK_CONTROLLED_ACQUISITION")
        self.assertEqual(report["risk_acquisition"]["state"], "NEXT_BLOCK")
        write_plan(report, self.root / "plan")
        self.assertIn("停止但没有决策证据", (self.root / "plan/PLAN.md").read_text(encoding="utf-8"))

    def test_no_silent_mix_with_previous_acquisition_or_bridge(self):
        for key in ("evidence_acquisition", "evidence_bridge", "plugin_combination"):
            mixed = {**self.context, key: {}}
            with self.assertRaises(ValidationError):
                plan_plugin_use(mixed)

    def test_no_relabelled_plugin_baseline(self):
        spec = self.context["risk_acquisition"]["protocol"]
        spec["baseline_id"] = "c2"
        self.context["risk_acquisition"]["protocol_sha256"] = suite_digest(spec)
        with self.assertRaisesRegex(ValidationError, "non-plugin baseline"):
            plan_plugin_use(self.context)

    def test_actual_cli_uses_same_contract(self):
        path = self.root / "context.json"
        path.write_text(json.dumps(self.context), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/value_lab.py"), "plan-use", str(path),
                               "--output", str(self.root / "cli")], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        view = json.loads((self.root / "cli/plan.json").read_bytes())
        self.assertEqual(view["risk_acquisition"]["state"], "NEXT_BLOCK")
        self.assertFalse(view["risk_acquisition"]["automatic_execution"])


class RiskMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_six_tool_stdio_server_supports_new_context(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as temp:
            ctx = context(Path(temp))
            params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "scripts/value_lab.py"), "serve"],
                                           env={**os.environ, "PYTHONUTF8": "1"})
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    self.assertEqual(len((await session.list_tools()).tools), 6)
                    result = await session.call_tool("plan_plugin_use", {"context": ctx})
                    self.assertFalse(result.isError, result)
                    report = json.loads(result.content[0].text)
                    self.assertEqual(report["risk_acquisition"]["state"], "NEXT_BLOCK")
                    self.assertIsNone(report["risk_acquisition"]["selected_plan_sha256"])


if __name__ == "__main__":
    unittest.main()
