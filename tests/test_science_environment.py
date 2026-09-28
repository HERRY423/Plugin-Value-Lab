"""Dependency-byte drift and science-free artifact playback acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from value_lab.core import ValidationError, load_json, suite_digest, write_json
from value_lab.science_environment import capture_environment, check_environment, replay_reference, seal_reference


class Distribution:
    def __init__(self, root, name, requirements=()):
        self.root, self.version, self.requires = root, '1.0', list(requirements)
        self.metadata = {'Name': name}
        self.files = [Path(name + '.py')]
        (root / self.files[0]).write_text('value = 1\n', encoding='utf-8')

    def locate_file(self, file):
        return self.root / file

    def read_text(self, file):
        return None


class ScienceEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def distributions(self):
        return [Distribution(self.root, 'pydeseq2', ['numpy>=1', 'optional; extra == "test"']),
                Distribution(self.root, 'numpy')]

    def test_dependency_bytes_change_with_same_version_blocks(self):
        distributions = self.distributions()
        with patch('value_lab.science_environment.metadata.distributions', return_value=distributions):
            lock = capture_environment(['pydeseq2'])
            self.assertNotIn('optional', lock['distributions'])
            self.assertEqual(check_environment(lock, suite_digest(lock))['status'], 'ENVIRONMENT_MATCH')
            (self.root / 'numpy.py').write_text('value = 2\n', encoding='utf-8')
            drift = check_environment(lock, suite_digest(lock))
            self.assertEqual(drift['status'], 'ENVIRONMENT_DRIFT')
            self.assertIn('/distributions/numpy/files_sha256', drift['changes']['paths'])

    def test_missing_root_and_ambiguous_install_fail_closed(self):
        distributions = self.distributions()
        with patch('value_lab.science_environment.metadata.distributions', return_value=distributions):
            with self.assertRaises(ValidationError):
                capture_environment(['absent'])
        with patch('value_lab.science_environment.metadata.distributions', return_value=distributions * 2):
            with self.assertRaises(ValidationError):
                capture_environment(['pydeseq2'])

    def test_editable_or_missing_inventory_rejected(self):
        distributions = self.distributions()
        with patch('value_lab.science_environment.metadata.distributions', return_value=distributions):
            with patch.object(distributions[0], 'read_text', return_value='{"dir_info":{"editable":true}}'):
                with self.assertRaises(ValidationError):
                    capture_environment(['pydeseq2'])
            distributions[0].files = []
            with self.assertRaises(ValidationError):
                capture_environment(['pydeseq2'])

    def test_required_dependency_missing_and_unrelated_duplicate(self):
        distributions = self.distributions()
        unrelated = Distribution(self.root, 'unrelated')
        with patch('value_lab.science_environment.metadata.distributions', return_value=distributions + [unrelated, unrelated]):
            self.assertIn('numpy', capture_environment(['pydeseq2'])['distributions'])
        with patch('value_lab.science_environment.metadata.distributions', return_value=distributions[:1]):
            with self.assertRaisesRegex(ValidationError, 'dependency is missing'):
                capture_environment(['pydeseq2'])

    def test_transitive_extras_are_resolved_but_doc_extras_are_not(self):
        distributions = [Distribution(self.root, 'root', ['child[compute]>=1']),
                         Distribution(self.root, 'child', ['numeric; extra == "compute"', 'absent; extra == "docs"']),
                         Distribution(self.root, 'numeric')]
        with patch('value_lab.science_environment.metadata.distributions', return_value=distributions):
            lock = capture_environment(['root'])
        self.assertEqual(set(lock['distributions']), {'root', 'child', 'numeric'})

    def test_lock_tamper_and_thread_policy_drift(self):
        with patch('value_lab.science_environment.metadata.distributions', return_value=self.distributions()):
            lock = capture_environment(['pydeseq2'])
            with self.assertRaises(ValidationError):
                check_environment(lock, '0' * 64)
            with patch.dict('os.environ', {'OMP_NUM_THREADS': '237'}):
                self.assertEqual(check_environment(lock, suite_digest(lock))['status'], 'ENVIRONMENT_DRIFT')

    def bundle(self):
        source = self.root / 'source'
        source.mkdir()
        for name in ('design.json', 'data.json', 'reference.json', 'backend-receipt.json', 'verifier.json', 'environment.lock.json'):
            write_json(source / name, {'manufactured': True})
        (source / 'reference-runner.py').write_text('raise RuntimeError("must never execute during replay")', encoding='utf-8')
        write_json(source / 'execution.json', {'status': 'COMPLETED'})
        return source, seal_reference(source)

    def test_artifact_replay_with_no_site_packages_no_science(self):
        source, pin = self.bundle()
        target = self.root / 'playback'
        script = Path(__file__).resolve().parents[1] / 'scripts/science_env.py'
        process = subprocess.run([sys.executable, '-S', str(script), 'replay-reference', str(source),
            '--expected-id', pin, '--output', str(target)], capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        receipt = json.loads(process.stdout)
        self.assertFalse(receipt['scientific_execution'])
        self.assertEqual(receipt['new_observations'], 0)
        self.assertEqual((target / 'recorded/reference.json').read_bytes(), (source / 'reference.json').read_bytes())
        self.assertEqual(load_json(target / 'playback.json')['numerical_reproducibility'], 'NOT_RECOMPUTED')

    def test_mutation_blocks_before_output_creation(self):
        source, pin = self.bundle()
        (source / 'data.json').write_text('{}', encoding='utf-8')
        target = self.root / 'playback'
        with self.assertRaises(ValidationError):
            replay_reference(source, pin, target)
        self.assertFalse(target.exists())

    def test_manifest_traversal_rejected_even_with_recomputed_commitment(self):
        source, _ = self.bundle()
        manifest = load_json(source / 'artifact-manifest.json')
        manifest['files']['../outside'] = '0' * 64
        write_json(source / 'artifact-manifest.json', manifest)
        with self.assertRaises(ValidationError):
            replay_reference(source, suite_digest(manifest), self.root / 'playback')

    def test_completed_reference_is_automatically_sealed(self):
        from test_pseudobulk import fixture
        from value_lab.pseudobulk import create_reference
        design, data, result = fixture()
        write_json(self.root / 'design.json', design)
        write_json(self.root / 'data.json', data)
        environment = {'format': 'pvl-science-environment-1', 'roots': ['pydeseq2']}
        with patch('value_lab.science_environment.capture_environment', return_value=environment), \
             patch('value_lab.science_environment.require_environment') as require, \
             patch('value_lab.pseudobulk.fit_reference', return_value=result), \
             patch('importlib.metadata.version', return_value='fixture'):
            receipt = create_reference(self.root / 'design.json', self.root / 'data.json', self.root / 'reference')
            self.assertEqual(require.call_count, 1)
        replayed = replay_reference(self.root / 'reference', receipt['artifact_sha256'], self.root / 'playback')
        self.assertFalse(replayed['scientific_execution'])

    def test_expected_lock_drift_prevents_fit_and_output(self):
        from test_pseudobulk import fixture
        from value_lab.pseudobulk import create_reference
        design, data, _ = fixture()
        write_json(self.root / 'design.json', design)
        write_json(self.root / 'data.json', data)
        lock = {'format': 'pvl-science-environment-1', 'roots': ['pydeseq2']}
        write_json(self.root / 'lock.json', lock)
        with patch('value_lab.science_environment.require_environment', side_effect=ValidationError('drift')), \
             patch('value_lab.pseudobulk.fit_reference') as fit:
            with self.assertRaises(ValidationError):
                create_reference(self.root / 'design.json', self.root / 'data.json', self.root / 'reference',
                    environment_lock=self.root / 'lock.json', environment_id=suite_digest(lock))
            fit.assert_not_called()
        self.assertFalse((self.root / 'reference').exists())


if __name__ == '__main__':
    unittest.main()
