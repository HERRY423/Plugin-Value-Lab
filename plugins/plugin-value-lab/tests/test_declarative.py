"""Tests for declarative Markdown/file-tree suites (evals/ directory structure)."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from value_lab.core import ValidationError, demo_records, demo_suite, evaluate, freeze, load_suite, suite_digest
from value_lab.native import dump_evals, load_evals, parse_frontmatter


def rich_science_suite_fixture():
    return {
        "schema_version": 1,
        "id": "science-eval-declarative",
        "plugin": {"name": "bionexus", "version": "1.0.0"},
        "evidence_type": "local",
        "runs_per_case": 2,
        "conditions": {
            "model": "claude-3-7-sonnet",
            "host": "local",
            "environment": "scientific-linux",
            "tools": ["Read", "Bash", "BioNexus"],
            "budget": {"max_turns": 15, "timeout_seconds": 600},
        },
        "policy": {
            "min_quality_delta": 0.15,
            "quality_floor": 0.85,
            "max_case_regression": 0.05,
            "min_clusters": 2,
            "require_cost_saving": False,
            "human_hourly_usd": 50,
        },
        "cases": [
            {
                "id": "de_analysis",
                "cluster": "transcriptomics",
                "kind": "task",
                "prompt": "Run differential expression analysis on donor-aware PBMC counts.",
                "rules": [{"scope": "tool", "target": "run_pydeseq2", "verdict": "allow"}],
                "graders": [
                    {
                        "id": "de_results",
                        "dimension": "outcome",
                        "type": "artifact",
                        "artifact": "result",
                        "weight": 2,
                        "critical": True,
                        "verifier": {
                            "kind": "de_table",
                            "id_column": "gene",
                            "p_column": "p",
                            "q_column": "q",
                            "effect_column": "effect",
                            "min_rows": 3,
                            "bh_tolerance": 1e-09,
                        },
                    },
                    {
                        "id": "call_order",
                        "dimension": "process",
                        "type": "contains",
                        "value": "PyDESeq2 fitted successfully",
                        "weight": 1,
                        "critical": False,
                    },
                ],
            },
            {
                "id": "cell_clustering",
                "cluster": "single-cell",
                "kind": "task",
                "prompt": "Identify clusters and assign verified marker labels.",
                "graders": [
                    {
                        "id": "cluster_markers",
                        "dimension": "outcome",
                        "type": "artifact",
                        "artifact": "clusters",
                        "weight": 1,
                        "critical": True,
                        "verifier": {
                            "kind": "labels",
                            "id_column": "cell_id",
                            "label_column": "cell_type",
                            "expected": {"cell_1": "CD4_T", "cell_2": "B_cell"},
                        },
                    },
                ],
            },
        ],
    }


class DeclarativeSuiteTests(unittest.TestCase):
    def test_demo_suite_roundtrip_digest_invariant(self):
        suite = demo_suite()
        original_digest = suite_digest(suite)
        with tempfile.TemporaryDirectory() as temp_dir:
            out_evals = Path(temp_dir) / "evals"
            dump_evals(suite, out_evals)

            # Check that files were written
            self.assertTrue((out_evals / "suite.json").is_file())
            for case in suite["cases"]:
                self.assertTrue((out_evals / case["id"] / "prompt.md").is_file())
                for g in case["graders"]:
                    self.assertTrue((out_evals / case["id"] / "graders" / f"{g['id']}.md").is_file())

            # Load back and verify hash exact match
            loaded = load_evals(out_evals)
            self.assertEqual(suite_digest(loaded), original_digest)
            self.assertEqual(loaded, suite)

    def test_science_suite_roundtrip_with_numeric_tolerances(self):
        suite = rich_science_suite_fixture()
        original_digest = suite_digest(suite)
        with tempfile.TemporaryDirectory() as temp_dir:
            out_evals = Path(temp_dir) / "evals"
            dump_evals(suite, out_evals)

            # Check de_table grader preserves float tolerances
            grader_file = out_evals / "de_analysis" / "graders" / "de_results.md"
            self.assertTrue(grader_file.is_file())
            fm, _ = parse_frontmatter(grader_file.read_text(encoding="utf-8"))
            self.assertEqual(fm["type"], "artifact")
            self.assertEqual(fm["verifier"]["kind"], "de_table")
            self.assertAlmostEqual(fm["verifier"]["bh_tolerance"], 1e-09)

            # Check case.yaml rules
            case_yaml_file = out_evals / "de_analysis" / "case.yaml"
            self.assertTrue(case_yaml_file.is_file())

            loaded = load_suite(out_evals)
            self.assertEqual(suite_digest(loaded), original_digest)
            self.assertEqual(loaded, suite)

    def test_pure_directory_without_suite_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            evals_dir = Path(temp_dir) / "evals"
            case_dir = evals_dir / "case_alpha"
            g_dir = case_dir / "graders"
            g_dir.mkdir(parents=True)

            (case_dir / "prompt.md").write_text(
                "---\ncluster: cluster-1\nkind: task\n---\nRun step A and return the summary.\n",
                encoding="utf-8",
            )
            (g_dir / "accuracy.md").write_text(
                "---\ntype: contains\nvalue: SUCCESS\nweight: 1\ncritical: true\n---\nCheck success log\n",
                encoding="utf-8",
            )

            # Missing metadata must not invent a plugin/model or local evidence.
            with self.assertRaisesRegex(ValidationError, 'missing suite metadata'):
                load_suite(evals_dir)
            metadata = {k: v for k, v in demo_suite().items() if k != 'cases'}
            loaded = load_evals(evals_dir, suite_meta=metadata)
            self.assertEqual(len(loaded["cases"]), 1)
            case = loaded["cases"][0]
            self.assertEqual(case["id"], "case_alpha")
            self.assertEqual(case["cluster"], "cluster-1")
            self.assertEqual(case["prompt"], "Run step A and return the summary." + os.linesep)
            self.assertEqual(len(case["graders"]), 1)
            self.assertEqual(case["graders"][0]["type"], "contains")
            self.assertEqual(case["graders"][0]["value"], "SUCCESS")

    def test_frontmatter_parser_variants(self):
        # JSON frontmatter
        fm1, body1 = parse_frontmatter('---\n"id": "test1"\n"value": 42\n---\nHello world\n')
        self.assertEqual(fm1, {"id": "test1", "value": 42})
        self.assertEqual(body1, "Hello world")

        # YAML plain frontmatter
        fm2, body2 = parse_frontmatter("---\nid: test2\nvalue: 3.1415\nflag: true\n---\nBody text\n")
        self.assertEqual(fm2["id"], "test2")
        self.assertAlmostEqual(fm2["value"], 3.1415)
        self.assertEqual(fm2["flag"], True)
        self.assertEqual(body2, "Body text")

        # Scientific notation string in YAML
        fm3, _ = parse_frontmatter("---\ntol: 1e-09\n---\n")
        self.assertAlmostEqual(fm3["tol"], 1e-09)
        self.assertIsInstance(fm3["tol"], float)

        # Windows CRLF
        fm4, body4 = parse_frontmatter("---\r\nid: test4\r\n---\r\nLine 1\r\nLine 2\r\n")
        self.assertEqual(fm4["id"], "test4")
        self.assertEqual(body4, "Line 1\nLine 2")

    def test_validation_errors_on_malformed_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            evals_dir = Path(temp_dir) / "evals"
            case_dir = evals_dir / "invalid..case"
            case_dir.mkdir(parents=True)
            (case_dir / "prompt.md").write_text("Hello", encoding="utf-8")

            # Missing graders directory
            with self.assertRaises(ValidationError):
                load_evals(evals_dir)

    def test_cli_freeze_and_evaluate_with_directory_suite(self):
        suite = demo_suite()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evals_dir = root / "evals"
            dump_evals(suite, evals_dir)

            lock_file = root / "protocol.lock.json"
            runs_file = root / "runs.jsonl"
            records = demo_records(suite)
            with runs_file.open("w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r) + "\n")

            # Test freeze CLI with evals directory
            cmd_freeze = [
                sys.executable,
                "-m",
                "value_lab.cli",
                "freeze",
                str(evals_dir),
                "--lock",
                str(lock_file),
            ]
            res_freeze = subprocess.run(cmd_freeze, capture_output=True, text=True, check=False)
            self.assertEqual(res_freeze.returncode, 0, res_freeze.stderr)
            lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
            self.assertEqual(lock_data["suite_sha256"], suite_digest(suite))

            # Test evaluate CLI with evals directory
            out_report = root / "report"
            cmd_eval = [
                sys.executable,
                "-m",
                "value_lab.cli",
                "evaluate",
                str(evals_dir),
                str(runs_file),
                "--lock",
                str(lock_file),
                "--output",
                str(out_report),
            ]
            res_eval = subprocess.run(cmd_eval, capture_output=True, text=True, check=False)
            self.assertEqual(res_eval.returncode, 0, res_eval.stderr)
            eval_output = json.loads(res_eval.stdout)
            self.assertIn("verdict", eval_output)
            self.assertTrue((out_report / "report.json").is_file())


if __name__ == "__main__":
    unittest.main()
