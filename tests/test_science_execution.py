from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from value_lab.artifacts import sha
from value_lab.core import ValidationError, load_json, suite_digest, write_json
from value_lab.science_execution import execute, compare_json, validate_manifest


class ScienceExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs, self.submitted, self.spec = [self.root / n for n in ('inputs', 'answers', 'spec')]
        for p in (self.inputs, self.submitted, self.spec):
            p.mkdir()
        (self.inputs / 'run.py').write_text('raise RuntimeError("must run only in sandbox")')
        write_json(self.submitted / 'result.json', {'value': 2.0})
        self.lock = {'format': 'pvl-execution-environment-1', 'runtime_sha256': None, 'environment': {'roots': ['packaging']}}
        write_json(self.spec / 'environment.json', self.lock)
        self.manifest = {'format': 'pvl-science-execution-1', 'files': {'run.py': sha(self.inputs / 'run.py')},
                         'entrypoint': 'run.py', 'arguments': [], 'timeout_seconds': 10, 'memory_mb': 512,
                         'environment': {'path': 'environment.json', 'sha256': sha(self.spec / 'environment.json')},
                         'outputs': [{'path': 'result.json', 'submitted': {'path': 'result.json', 'sha256': sha(self.submitted / 'result.json')},
                                      'comparison': 'json', 'absolute': 1e-7, 'relative': 1e-6}]}

    def run_case(self, value=2.0, failure=False, environments=None):
        write_json(self.spec / 'manifest.json', self.manifest)
        def runner(inputs, files, command, output, **kwargs):
            self.assertEqual(set(files), {'run.py'})
            self.assertNotIn(str(self.submitted), ' '.join(command))
            self.assertNotIn('result.json', files)
            (output / 'artifacts').mkdir(parents=True)
            if value is not None:
                write_json(output / 'artifacts/result.json', {'value': value})
            return {'status': 'FAILED' if failure else 'COMPLETED'}
        with patch('value_lab.science_execution.capture_runtime', side_effect=environments or [self.lock, self.lock]), \
                patch('value_lab.science_execution.run_offline', side_effect=runner) as run:
            result = execute(self.spec / 'manifest.json', suite_digest(self.manifest), self.inputs, self.submitted, self.root / 'result')
        return result, run.call_count

    def test_match_requires_real_pipeline_and_both_environment_checks(self):
        result, calls = self.run_case()
        self.assertEqual((result['status'], calls), ('REPRODUCED', 1))
        self.assertTrue(result['pipeline_completed'])
        self.assertEqual(result['environment_check'], 'MATCH_BEFORE_AND_AFTER')
        self.assertEqual(result['scientific_validity'], 'NOT_ESTABLISHED')

    def test_submitted_artifact_not_mounted_and_mismatch_detected(self):
        result, _ = self.run_case(9)
        self.assertEqual(result['status'], 'RESULT_MISMATCH')
        self.assertFalse(result['passed'])

    def test_failure_missing_and_nonfinite_remain_distinct(self):
        result, _ = self.run_case(failure=True)
        self.assertEqual(result['status'], 'EXECUTION_FAILED')
        self.assertIsNone(result['passed'])

    def test_missing_output_unknown(self):
        result, _ = self.run_case(None)
        self.assertEqual(result['status'], 'UNRESOLVED')
        self.assertIsNone(result['passed'])

    def test_before_drift_prevents_submission_execution(self):
        result, calls = self.run_case(environments=[{}])
        self.assertEqual((result['status'], calls), ('UNRESOLVED', 0))

    def test_after_drift_invalidates_agreement(self):
        result, calls = self.run_case(environments=[self.lock, {}])
        self.assertEqual((result['status'], calls), ('UNRESOLVED', 1))
        self.assertIsNone(result['passed'])

    def test_changed_input_blocked_before_run(self):
        (self.inputs / 'run.py').write_text('print("changed")')
        with self.assertRaisesRegex(ValidationError, 'Pinned file changed'):
            self.run_case()
        self.assertFalse((self.root / 'result').exists())

    def test_invalid_tolerance_path_duplicate_and_budget_rejected(self):
        for change in (lambda m: m['outputs'][0].update(absolute=float('nan')),
                       lambda m: m['outputs'][0].update(relative=True),
                       lambda m: m['outputs'][0].update(path='../escape'),
                       lambda m: m['outputs'].append(deepcopy(m['outputs'][0])),
                       lambda m: m.update(memory_mb=100000), lambda m: m.update(timeout_seconds=0)):
            m = deepcopy(self.manifest)
            change(m)
            with self.assertRaises(ValidationError):
                validate_manifest(m)

    def test_full_shape_and_nonfinite_comparison(self):
        for a, b in [({'x': True}, {'x': 1}), ({'x': float('nan')}, {'x': float('nan')}),
                     ({'x': []}, {'x': [1]}), ({'x': 1, 'extra': 2}, {'x': 1}),
                     ({'x': float('inf')}, {'x': float('inf')})]:
            self.assertTrue(compare_json(a, b, 1e-7, 1e-6))
        self.assertFalse(compare_json({'x': 1.00000001}, {'x': 1.0}, 1e-7, 0))
        self.assertTrue(compare_json({'counts': 1000001}, {'counts': 1000000}, 1e-4, 1e-4))
        self.assertTrue(compare_json({'counts': 1.0}, {'counts': 1}, 1e-4, 1e-4))

    def test_ambiguous_duplicate_json_answer_cannot_be_reproduced(self):
        (self.submitted / 'result.json').write_text('{"value":9,"value":2.0}')
        self.manifest['outputs'][0]['submitted']['sha256'] = sha(self.submitted / 'result.json')
        result, _ = self.run_case()
        self.assertEqual(result['status'], 'UNRESOLVED')
        self.assertIsNone(result['passed'])

    def test_v2_large_bytes_streamed_and_last_byte_mismatch_detected(self):
        import shutil
        self.manifest.update(format='pvl-science-execution-2', timeout_seconds=600,
            resources={'input_bytes': 40*1048576, 'output_bytes': 40*1048576,
                       'file_bytes': 40*1048576, 'reserve_bytes': 0})
        source = self.inputs / 'counts.bin'
        with source.open('wb') as f:
            for _ in range(33):
                f.write(b'1' * 1048576)
        shutil.copyfile(source, self.submitted / 'counts.bin')
        self.manifest['files']['counts.bin'] = sha(source)
        self.manifest['outputs'] = [{'path': 'counts.bin', 'submitted': {'path': 'counts.bin', 'sha256': sha(source)},
                                     'comparison': 'bytes', 'absolute': 0, 'relative': 0}]
        write_json(self.spec / 'manifest.json', self.manifest)
        def runner(inputs, files, command, output, **kwargs):
            self.assertEqual(kwargs['resources'], self.manifest['resources'])
            (output / 'artifacts').mkdir(parents=True)
            target = output / 'artifacts/counts.bin'
            shutil.copyfile(inputs / 'counts.bin', target)
            with target.open('r+b') as f:
                f.seek(-1, 2)
                f.write(b'2')
            return {'status': 'COMPLETED'}
        original = Path.read_bytes
        def bounded_read(path):
            if path.suffix == '.bin':
                raise AssertionError('Large input/output was read wholesale')
            return original(path)
        with patch('value_lab.science_execution.capture_runtime', return_value=self.lock), \
                patch('value_lab.science_execution.run_offline', side_effect=runner), \
                patch.object(Path, 'read_bytes', bounded_read):
            result = execute(self.spec / 'manifest.json', suite_digest(self.manifest), self.inputs,
                             self.submitted, self.root / 'large')
        self.assertEqual(result['status'], 'RESULT_MISMATCH')

    def test_v2_requires_explicit_valid_budgets_and_exact_count_comparison(self):
        m = deepcopy(self.manifest)
        m['format'] = 'pvl-science-execution-2'
        with self.assertRaises(ValidationError):
            validate_manifest(m)
        m['resources'] = {'input_bytes': 1024, 'output_bytes': 1024, 'file_bytes': 1024, 'reserve_bytes': 0}
        validate_manifest(m)
        for key, value in [('input_bytes', True), ('reserve_bytes', -1), ('file_bytes', 1025)]:
            bad = deepcopy(m)
            bad['resources'][key] = value
            with self.assertRaises(ValidationError):
                validate_manifest(bad)
        m['outputs'][0]['comparison'] = 'h5ad_counts'
        with self.assertRaises(ValidationError):
            validate_manifest(m)


if __name__ == '__main__':
    unittest.main()
