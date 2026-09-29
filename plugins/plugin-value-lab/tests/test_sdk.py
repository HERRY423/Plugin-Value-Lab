"""Public user journeys and failure recovery, not implementation-mirroring tests."""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from value_lab import sdk
from value_lab.core import load_json, write_json
from value_lab.easy_cli import main

ROOT = Path(__file__).resolve().parents[1]


class PublicSDKTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv = self.root / 'results with spaces.csv'
        self.csv.write_text('gene,p_value,q_value,log2fc\ng1,0.01,0.02,1\ng2,0.2,0.2,-1\n', encoding='utf-8')

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([str(v) for v in args])
        return code, out.getvalue(), err.getvalue()

    def test_zero_dependency_demo_runs_from_module_and_reports_synthetic(self):
        result = subprocess.run([sys.executable, '-S', '-m', 'value_lab', 'demo', '--output',
                                 str(self.root / 'demo'), '--json'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        answer = json.loads(result.stdout)
        self.assertEqual(answer['status'], 'DEMO_COMPLETE')
        self.assertEqual(sdk.verify_run(self.root / 'demo').status, 'DEMO_COMPLETE')
        self.assertTrue(load_json(self.root / 'demo/plan.json')['synthetic'])

    def test_pass_failure_and_unknown_are_distinct_process_exit_codes(self):
        code, out, err = self.cli('check', self.csv, '--rule', 'bh', '--output', self.root / 'pass', '--json')
        self.assertEqual((code, json.loads(out)['status']), (0, 'CONTRACT_PASSED'))
        self.csv.write_text('gene,p_value,q_value,log2fc\ng1,0.01,0.9,1\n', encoding='utf-8')
        code, out, _ = self.cli('check', self.csv, '--rule', 'bh', '--output', self.root / 'fail', '--json')
        self.assertEqual((code, json.loads(out)['status']), (3, 'CONTRACT_FAILED'))
        with patch('value_lab.easy_cli.sdk.check_bh', return_value=sdk.RunResult(self.root, 'UNKNOWN', 'x')):
            code, out, _ = self.cli('check', self.csv, '--rule', 'bh', '--output', self.root / 'unknown', '--json')
        self.assertEqual((code, json.loads(out)['status']), (4, 'UNKNOWN'))

    def test_missing_method_argument_and_input_errors_have_actions_no_traceback(self):
        for args, expected in [
            (['check', self.csv, '--output', self.root / 'none'], 'USAGE'),
            (['check', self.root / 'absent.csv', '--rule', 'bh', '--output', self.root / 'none'], 'INPUT_NOT_FOUND'),
            (['aggregate', self.csv, '--output', self.root / 'none'], 'MISSING_DESIGN')]:
            code, out, err = self.cli(*args, '--json')
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)['code'], expected)
            self.assertTrue(json.loads(out)['hint'])
            self.assertNotIn('Traceback', out + err)

    def test_verified_reuse_no_computation_and_changed_input_cannot_reuse(self):
        first = sdk.check_bh(self.csv, output=self.root / 'run')
        before = first.report.read_bytes()
        with patch('value_lab.usage.diagnose', side_effect=AssertionError('must not run')):
            reused = sdk.check_bh(self.csv, output=self.root / 'run', reuse=True)
        self.assertTrue(reused.reused)
        self.assertEqual(first.commitment, reused.commitment)
        self.csv.write_text('gene,p_value,q_value,log2fc\ng,0.1,0.1,0\n', encoding='utf-8')
        with self.assertRaises(sdk.PVLError) as error:
            sdk.check_bh(self.csv, output=self.root / 'run', reuse=True)
        self.assertEqual(error.exception.code, 'REQUEST_CHANGED')
        self.assertEqual(first.report.read_bytes(), before)

    def test_output_tampering_and_changed_engine_block_reuse(self):
        first = sdk.check_bh(self.csv, output=self.root / 'run')
        with patch('value_lab.sdk._engine_id', return_value='changed-code'):
            with self.assertRaises(sdk.PVLError) as error:
                sdk.check_bh(self.csv, output=first.directory, reuse=True)
        self.assertEqual(error.exception.code, 'REQUEST_CHANGED')
        first.report.write_text('changed', encoding='utf-8')
        with self.assertRaises(sdk.PVLError) as error:
            sdk.verify_run(first.directory, expected_id=first.commitment)
        self.assertEqual(error.exception.code, 'RESULT_CHANGED')

    def test_completed_bundle_relocates_without_original_input(self):
        first = sdk.check_bh(self.csv, output=self.root / 'run')
        moved = self.root / 'relocated with spaces'
        shutil.copytree(first.directory, moved)
        self.csv.unlink()
        result = sdk.verify_run(moved, expected_id=first.commitment)
        self.assertEqual(result.status, 'CONTRACT_PASSED')

    def test_incomplete_and_existing_outputs_are_never_overwritten(self):
        output = self.root / 'existing'
        output.mkdir()
        sentinel = output / 'user-data.txt'
        sentinel.write_text('keep me')
        for reuse in (False, True):
            with self.assertRaises(sdk.PVLError):
                sdk.check_bh(self.csv, output=output, reuse=reuse)
        self.assertEqual(sentinel.read_text(), 'keep me')

    def test_path_traversal_in_manifest_fails_even_with_recomputed_local_marker(self):
        result = sdk.check_bh(self.csv, output=self.root / 'run')
        manifest = result.manifest
        manifest['files'] = {'../results with spaces.csv': '0'*64}
        from value_lab.core import suite_digest
        write_json(result.directory / 'run.json', manifest)
        (result.directory / 'COMPLETED').write_text(suite_digest(manifest))
        with self.assertRaises(sdk.PVLError):
            sdk.verify_run(result.directory)

    def test_config_typo_fails_before_input_access_and_stdout_is_one_json(self):
        config = self.root / 'settings.json'
        write_json(config, {'cell_typ': 'B'})
        code, out, err = self.cli('aggregate', self.csv, '--config', config, '--output', self.root / 'out', '--json')
        self.assertEqual((code, json.loads(out)['code']), (2, 'INVALID_CONFIG'))
        self.assertFalse((self.root / 'out').exists())

    def test_doctor_does_not_require_optional_science_or_launch_hosts(self):
        with patch('value_lab.sdk.importlib.util.find_spec', return_value=None), \
                patch('subprocess.run', side_effect=AssertionError('must not start hosts')):
            result = sdk.doctor()
        self.assertTrue(result['ready']['artifact_checks'])
        self.assertFalse(result['ready']['counts_aggregation'])


class CountsSDKTests(unittest.TestCase):
    def setUp(self):
        from test_science_scale import BackedTests
        BackedTests.setUpClass()
        self.fixture = BackedTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.source = self.fixture.source()
        self.options = {'cell_type': 'B cells', 'control': 'ctrl', 'treatment': 'stim', 'min_cells': 2,
                        'reserve_bytes': 0, 'output': self.root / 'result'}

    def test_one_call_matches_original_counts_and_reuses(self):
        result = sdk.aggregate_counts(self.source, **self.options)
        self.assertEqual(result.status, 'COMPLETE')
        self.assertEqual(result.manifest['summary']['output_shape'], [6, 2])
        x = self.fixture.ad.read_h5ad(result.counts).X
        self.fixture.np.testing.assert_array_equal(x, [[3, 7]]*6)
        with patch('value_lab.pseudobulk_backed.aggregate_h5ad', side_effect=AssertionError('must not recompute')):
            self.assertTrue(sdk.aggregate_counts(self.source, **self.options, reuse=True).reused)

    def test_header_dry_run_writes_nothing_and_does_not_claim_count_validation(self):
        before = set(self.root.iterdir())
        result = sdk.aggregate_counts(self.source, **self.options, dry_run=True)
        self.assertEqual(result['status'], 'PREFLIGHT_ONLY')
        self.assertFalse(result['counts_validated'])
        self.assertFalse(result['donor_design_validated'])
        self.assertEqual(set(self.root.iterdir()), before)

    def test_actionable_column_and_matrix_errors_do_not_create_output(self):
        for extra, code in [({'donor_key': 'patient'}, 'MISSING_COLUMNS'), ({'matrix': 'layers/missing'}, 'MATRIX_NOT_FOUND')]:
            with self.assertRaises(sdk.PVLError) as error:
                sdk.aggregate_counts(self.source, **self.options, **extra)
            self.assertEqual(error.exception.code, code)
            self.assertFalse(self.options['output'].exists())

    def test_scientific_failure_retained_and_never_reused(self):
        options = dict(self.options, min_cells=100)
        with self.assertRaises(sdk.PVLError) as error:
            sdk.aggregate_counts(self.source, **options)
        self.assertEqual(error.exception.code, 'TOO_FEW_CELLS')
        self.assertEqual(load_json(options['output'] / 'run.json')['state'], 'FAILED')
        self.assertTrue((options['output'] / 'plan.json').exists())
        self.assertTrue((options['output'] / 'failure.json').exists())
        with self.assertRaises(sdk.PVLError) as error:
            sdk.aggregate_counts(self.source, **options, reuse=True)
        self.assertEqual(error.exception.code, 'INCOMPLETE_RUN')

    def test_cli_config_with_spaces_and_machine_output(self):
        config = self.root / 'workflow settings.json'
        settings = {k: v for k, v in self.options.items() if k != 'output'}
        write_json(config, settings)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(['aggregate', str(self.source), '--config', str(config), '--output', str(self.options['output']), '--json'])
        self.assertEqual(code, 0, out.getvalue() + err.getvalue())
        self.assertEqual(json.loads(out.getvalue())['status'], 'COMPLETE')
        self.assertIn('Aggregating', err.getvalue())


if __name__ == '__main__':
    unittest.main()
