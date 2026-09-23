"""Scientific contract attacks and independent numerical cross-checks."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from value_lab.artifacts import grade_artifact, sha, validate_verifier
from value_lab.core import ValidationError, demo_suite, demo_records, evaluate, freeze, write_json
from value_lab.replicates import recompute, validate_design, validate_spec
from value_lab.replay import replay_contract


def fixture(mode="independent"):
    design = {"format": "pvl-replicate-design-1", "mode": mode, "control": "control", "treatment": "treated",
              "features": ["signal", "null"], "training_units": [],
              "exchangeability": "Manufactured exchangeable observations for numerical tests, not biological evidence.", "samples": []}
    rows = ["sample,feature,value"]
    for group in ("control", "treated"):
        for i in range(4):
            sid = group + str(i)
            design["samples"].append({"id": sid, "unit": "donor" + str(i) if mode == "paired" else sid,
                                      "condition": group, "block": "batch"})
            rows.extend((f"{sid},signal,{i + (4 if group == 'treated' else 0)}", f"{sid},null,{i}"))
    return design, ("\n".join(rows) + "\n").encode()


class ReplicateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.design, self.raw = fixture()
        self.spec = {"design": {"path": "design.json", "sha256": "a"*64},
                     "data": {"path": "data.csv", "sha256": "b"*64},
                     "alpha": .1, "minimum_effect": 1, "absolute": 1e-10, "relative": 1e-10}

    def material(self):
        write_json(self.root / "design.json", self.design)
        (self.root / "data.csv").write_bytes(self.raw)
        for field, name in (("design", "design.json"), ("data", "data.csv")):
            self.spec[field]["sha256"] = sha(self.root / name)
        result, _ = recompute(self.design, self.raw, self.spec)
        return result

    def grade(self, result):
        write_json(self.root / "result.json", result)
        grader = {"id": "replicates", "type": "replicate_effect", "artifact": "result", "dimension": "outcome",
                  "critical": True, "weight": 1, "verifier": self.spec}
        validate_verifier(grader)
        record = {"artifacts": {"result": {"path": "result.json", "sha256": sha(self.root / "result.json")}}}
        return grade_artifact(grader, record, self.root, self.root)

    def test_known_exact_values_bh_and_leave_one_unit(self):
        result, audit = recompute(self.design, self.raw, self.spec)
        signal, null = result["results"]
        self.assertEqual(audit["assignments"], 70)
        self.assertEqual(signal["effect"], 4)
        self.assertAlmostEqual(signal["p_value"], 2/70)
        self.assertAlmostEqual(signal["q_value"], 4/70)
        self.assertEqual((signal["loo_effect_min"], signal["loo_effect_max"]), (3.5, 4.5))
        self.assertEqual(signal["decision"], "supported")
        self.assertEqual(null["decision"], "not_supported")
        self.assertEqual(null["p_value"], 1)

    def test_independent_scipy_oracle_for_both_designs(self):
        # Release dependencies include scipy; an unavailable oracle must fail acceptance.
        import numpy as np
        from scipy.stats import permutation_test
        for mode in ("independent", "paired"):
            design, raw = fixture(mode)
            computed, _ = recompute(design, raw, self.spec)
            oracle = permutation_test((np.arange(4.)+4, np.arange(4.)), lambda a,b: np.mean(a)-np.mean(b),
                                      permutation_type="independent" if mode == "independent" else "samples",
                                      n_resamples=np.inf, alternative="two-sided", vectorized=False)
            self.assertAlmostEqual(computed["results"][0]["p_value"], oracle.pvalue)
            self.assertAlmostEqual(computed["results"][0]["effect"], oracle.statistic)

    def test_blocked_assignments_do_not_permute_across_batch(self):
        for sample in self.design["samples"]:
            sample["block"] = sample["id"][-1]
        result, audit = recompute(self.design, self.raw, self.spec)
        self.assertEqual(audit["assignments"], 16)
        self.assertEqual(result["results"][0]["p_value"], .125)
        self.assertEqual(result["results"][0]["decision"], "not_supported")

    def test_ties_null_and_reversed_contrasts_match_scipy(self):
        import numpy as np
        from scipy.stats import permutation_test
        for a,b in (([0,0,1,1],[0,1,1,2]), ([9,8,7,6],[1,2,3,4]), ([1]*4,[1]*4), ([100,1,2,3],[4,5,6,7])):
            design,_ = fixture()
            design["features"] = ["signal"]
            raw = ("sample,feature,value\n" + "".join(f"{group}{i},signal,{v}\n" for group,values in (("control",a),("treated",b)) for i,v in enumerate(values))).encode()
            result,_ = recompute(design,raw,self.spec)
            oracle=permutation_test((np.array(b,dtype=float),np.array(a,dtype=float)),lambda x,y: np.mean(x)-np.mean(y),n_resamples=np.inf,vectorized=False)
            self.assertAlmostEqual(result["results"][0]["p_value"],oracle.pvalue)

    def test_influential_paired_unit_remains_visible(self):
        self.design,_ = fixture("paired")
        self.design["features"] = ["signal"]
        raw = ("sample,feature,value\n" + "".join(f"{group}{i},signal,{v}\n" for group,values in (("control",[0]*4),("treated",[-100,1,1,1])) for i,v in enumerate(values))).encode()
        result,_ = recompute(self.design,raw,self.spec)
        self.assertLess(result["results"][0]["loo_effect_min"],0)
        self.assertEqual(result["results"][0]["loo_effect_max"],1)

    def test_registered_scientific_result_replays_after_relocation(self):
        from value_lab.registry import register_study, export_entry, replay_bundle
        from value_lab.replay import plan_replay
        result=self.material()
        self.grade(result)
        suite=demo_suite()
        suite["cases"][0]["graders"]=[{"id":"replicates","type":"replicate_effect","artifact":"result","dimension":"outcome","weight":1,"critical":True,"verifier":self.spec}]
        rows=demo_records(suite)
        for row in rows:
            if row["case_id"]==suite["cases"][0]["id"]:
                row["artifacts"]={"result":{"path":"result.json","sha256":sha(self.root/"result.json")}}
        write_json(self.root/"suite.json",suite)
        freeze(suite,self.root/"protocol.lock.json")
        (self.root/"runs.jsonl").write_text("".join(json.dumps(r)+"\n" for r in rows),encoding="utf-8")
        registry=self.root/"registry"
        receipt=register_study(self.root,{"observed_at":"2026-09-23T00:00:00Z","authors":[{"id":"fixture","organization":"fixture"}],"plugin_sha256":"a"*64,"limitations":"Synthetic, no model execution"},registry,verifier_root=self.root)
        relocated=self.root/"relocated"
        export_entry(registry,receipt["entry_id"],relocated)
        self.assertEqual(plan_replay(relocated)["status"],"MATERIALS_REQUIRED")
        replay=replay_bundle(relocated,verifier_root=self.root,expected_id=receipt["entry_id"],require_same_environment=True)
        self.assertEqual(replay["status"],"REPRODUCED")
        self.assertEqual(replay["report"]["verdict"],"SIMULATION_ONLY")
        self.assertFalse((relocated/"data.csv").exists())

    def test_small_scale_does_not_turn_signal_into_all_ties(self):
        lines = self.raw.decode().splitlines()
        self.raw = (lines[0] + "\n" + "\n".join(",".join(row.split(",")[:2]) + "," + str(float(row.split(",")[2])*1e-100) for row in lines[1:])).encode()
        result, _ = recompute(self.design, self.raw, self.spec)
        self.assertAlmostEqual(result["results"][0]["p_value"], 2/70)

    def test_row_order_and_feature_order_do_not_change_values(self):
        expected, _ = recompute(self.design, self.raw, self.spec)
        self.design["samples"].reverse()
        rows = self.raw.decode().splitlines()
        self.raw = (rows[0]+"\n"+"\n".join(reversed(rows[1:]))).encode()
        self.assertEqual(recompute(self.design, self.raw, self.spec)[0], expected)

    def test_rejects_pseudoreplication(self):
        self.design["samples"][1]["unit"] = self.design["samples"][0]["unit"]
        with self.assertRaisesRegex(ValidationError, "Pseudoreplication"):
            validate_design(self.design)

    def test_rejects_batch_confounding(self):
        for sample in self.design["samples"]:
            sample["block"] = sample["condition"]
        with self.assertRaisesRegex(ValidationError, "confounded"):
            validate_design(self.design)

    def test_rejects_training_leakage(self):
        self.design["training_units"] = [self.design["samples"][0]["unit"]]
        with self.assertRaisesRegex(ValidationError, "overlap"):
            validate_design(self.design)

    def test_paired_design_requires_complete_pairs_and_same_batch(self):
        self.design, self.raw = fixture("paired")
        for key, value in (("condition", "treated"), ("block", "different"), ("unit", "missing")):
            with self.subTest(key=key):
                changed = deepcopy(self.design)
                changed["samples"][0][key] = value
                with self.assertRaisesRegex(ValidationError, "paired unit"):
                    validate_design(changed)

    def test_limits_bound_exact_work_without_silent_monte_carlo(self):
        self.design["samples"] = [{"id": str(i), "unit": str(i), "condition": "control" if i<16 else "treated", "block": "one"} for i in range(32)]
        with self.assertRaisesRegex(ValidationError, "bounded"):
            validate_design(self.design)

    def test_invalid_reference_coverage_is_unknown_not_bad_model(self):
        result = self.material()
        for raw in (self.raw + b"control0,signal,0\n", self.raw.replace(b"control0,signal,0\n", b""), self.raw.replace(b"control0,signal,0", b"control0,signal,nan")):
            (self.root / "data.csv").write_bytes(raw)
            self.spec["data"]["sha256"] = sha(self.root / "data.csv")
            self.assertIsNone(self.grade(result)[0])

    def test_changed_or_absent_reference_stays_unresolved(self):
        result = self.material()
        (self.root / "data.csv").write_bytes(b"tampered")
        self.assertIsNone(self.grade(result)[0])
        (self.root / "data.csv").unlink()
        self.assertIsNone(self.grade(result)[0])

    def test_adversarial_submissions_are_rejected(self):
        good = self.material()
        mutations = [("effect", -4), ("p_value", 0), ("q_value", 0), ("n_control", 4000),
                     ("loo_effect_min", 4), ("decision", "not_supported"), ("p_value", True), ("effect", 10**400)]
        for key, value in mutations:
            with self.subTest(key=key, value=str(value)[:30]):
                result = deepcopy(good)
                result["results"][0][key] = value
                self.assertIs(self.grade(result)[0], False)
        for field, value in (("analysis_unit", "cell"), ("contrast", ["treated", "control"]), ("design_sha256", "f"*64), ("alpha", True)):
            result = deepcopy(good)
            result[field] = value
            self.assertIs(self.grade(result)[0], False)

    def test_selective_duplicate_and_unexpected_features_rejected(self):
        good = self.material()
        for rows in (good["results"][:1], [good["results"][0]]*2, good["results"]+[good["results"][0]]):
            result = deepcopy(good)
            result["results"] = rows
            self.assertIs(self.grade(result)[0], False)

    def test_correct_negative_result_passes_and_false_positive_fails(self):
        self.design, self.raw = fixture("paired")
        result = self.material()
        self.assertTrue(all(r["decision"] == "not_supported" for r in result["results"]))
        self.assertTrue(self.grade(result)[0])
        result["results"][0]["decision"] = "supported"
        self.assertFalse(self.grade(result)[0])

    def test_reference_tolerance_and_threshold_contract(self):
        for field, value in (("alpha", 1), ("alpha", True), ("relative", 1), ("absolute", -1), ("minimum_effect", -1)):
            changed = dict(self.spec, **{field:value})
            with self.assertRaises(ValidationError):
                validate_spec(changed)

    def test_evaluator_and_replay_dependency_inventory(self):
        result = self.material()
        self.assertTrue(self.grade(result)[0])
        suite = demo_suite()
        suite["cases"][0]["graders"] = [{"id":"replicates","type":"replicate_effect","artifact":"result","dimension":"outcome","weight":1,"critical":True,"verifier":self.spec}]
        rows = demo_records(suite)
        for row in rows:
            if row["case_id"] == suite["cases"][0]["id"]:
                row["artifacts"] = {"result":{"path":"result.json","sha256":sha(self.root/"result.json")}}
        report = evaluate(suite, rows, freeze(suite,self.root/"lock.json"),artifact_root=self.root,verifier_root=self.root)
        self.assertEqual(report["cases"][0]["with_score"], 1)
        self.assertEqual(report["verdict"], "SIMULATION_ONLY")
        ready = replay_contract(suite, rows, verifier_root=self.root, artifact_root=self.root)
        self.assertTrue(ready["material_bytes_ready"])
        self.assertTrue({"design", "data"}.issubset({r["kind"] for r in ready["materials"]}))

    def test_reference_cli_recomputes_and_preserves_existing_output(self):
        from value_lab.cli import main
        expected = self.material()
        write_json(self.root/"spec.json", self.spec)
        args = ["replicate-reference",str(self.root/"spec.json"),"--verifiers",str(self.root),"--output",str(self.root/"out")]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
        self.assertEqual(json.loads((self.root/"out/reference.json").read_text()), expected)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(main(args), 0)

    def test_scenario_allows_declared_measurements_but_not_answers_as_inputs(self):
        from tests.test_scenarios import fixture as scenario_fixture
        from value_lab.scenarios import validate_pack
        self.material()
        pack, inputs, scorers = scenario_fixture(self.root)
        for name in ("design.json", "data.csv"):
            (scorers/name).write_bytes((self.root/name).read_bytes())
            (inputs/name).write_bytes((self.root/name).read_bytes())
        case = pack["scenarios"][0]
        private_path = scorers/case["scorer"]["path"]
        private = json.loads(private_path.read_text())
        private["graders"] = [{"id":"replicate","type":"replicate_effect","artifact":"decision","verifier":self.spec}]
        write_json(private_path, private)
        case["scorer"]["sha256"] = sha(private_path)
        case["inputs"].update({name:sha(inputs/name) for name in ("design.json","data.csv")})
        self.assertTrue(validate_pack(pack,inputs,scorers)["scorers_checked"])
        (inputs/"answer.json").write_bytes(private_path.read_bytes())
        case["inputs"]["answer.json"] = sha(inputs/"answer.json")
        with self.assertRaisesRegex(ValidationError, "Scorer-only"):
            validate_pack(pack,inputs,scorers)
