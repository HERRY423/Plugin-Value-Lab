"""Author entry point and detector denominators, including uncomfortable outcomes."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from value_lab.core import ValidationError, load_json, write_json
from value_lab.methodology import audit_detector
from value_lab.usage import diagnose

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / 'examples/detector-corpus/manifest.json'


class AuthorDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_one_command_artifact_requires_explicit_method_and_preserves_source(self):
        source = CORPUS.parent / 'wrong-bh.csv'
        before = source.read_bytes()
        with self.assertRaises(ValidationError):
            diagnose(source, self.root/'unspecified')
        result = diagnose(source, self.root/'report', check='bh')
        self.assertEqual(result['status'], 'CONTRACT_FAILED')
        self.assertGreaterEqual(result['timing']['machine_seconds_to_diagnosis'], 0)
        self.assertIsNone(result['timing']['human_time_to_first_diagnosis_seconds'])
        self.assertEqual(source.read_bytes(), before)
        report = load_json(result['json'])
        self.assertFalse(report['result']['plugin_defect_established'])
        with self.assertRaises(ValidationError):
            diagnose(source, self.root/'report', check='bh')

    def test_audit_exposes_blind_spots_false_alarm_and_unknown_denominator(self):
        report = audit_detector(CORPUS)
        rows = {r['id']: r for r in report['cases']}
        self.assertEqual(rows['wrong-bh']['classification'], 'TP')
        self.assertEqual(rows['allowed-bonferroni']['classification'], 'FP')
        for name in ('truncated-family', 'reversed-effects', 'fabricated-input-p', 'observed-ngs-duplicate_transcript'):
            self.assertEqual(rows[name]['classification'], 'FN')
        self.assertEqual(rows['missing-transport']['classification'], 'UNKNOWN')
        self.assertEqual(report['summary']['EXCLUDED_LABEL'], 2)
        rate = report['summary']['detection']
        self.assertIsNone(rate['rate'])
        self.assertEqual(rate['planned'], 10)
        self.assertEqual((rate['lower'], rate['upper']), (.5, .6))
        self.assertIn('confounding', report['blind_spots']['untested_families'])
        self.assertIsNone(report['representative_accuracy'])
        self.assertEqual(report['by_origin']['replayed_real']['cases'], 4)

    def test_audit_refuses_duplicate_denominator_and_executable_check(self):
        manifest = load_json(CORPUS)
        # Path need not exist: a copied corpus with absent artifacts remains unknown.
        other = deepcopy(manifest['cases'][0])
        other['id'] = 'duplicate'
        other['grader']['id'] = 'renamed-check'
        manifest['cases'].append(other)
        path = self.root/'manifest.json'
        write_json(path, manifest)
        with self.assertRaisesRegex(ValidationError, 'denominator'):
            audit_detector(path)
        manifest['cases'] = manifest['cases'][:1]
        manifest['cases'][0]['grader']['type'] = 'executable'
        write_json(path, manifest)
        with self.assertRaisesRegex(ValidationError, 'built-in'):
            audit_detector(path)

    def test_changed_artifact_is_unknown_not_detected_or_cleared(self):
        manifest = load_json(CORPUS)
        manifest['cases'] = manifest['cases'][:1]
        artifact = self.root/manifest['cases'][0]['artifact']['path']
        artifact.write_text('changed', encoding='utf-8')
        write_json(self.root/'manifest.json', manifest)
        report = audit_detector(self.root/'manifest.json')
        self.assertEqual(report['summary']['UNKNOWN'], 1)
        self.assertEqual(report['summary']['TN'], 0)
        self.assertIsNone(report['summary']['false_positive']['rate'])
        self.assertEqual(report['summary']['false_positive']['upper'], 1)

    def test_invalid_corpus_and_spec_types_are_actionable_errors(self):
        path = self.root/'bad.json'
        write_json(path, [])
        with self.assertRaises(ValidationError):
            audit_detector(path)
        with self.assertRaises(ValidationError):
            diagnose(CORPUS.parent/'wrong-bh.csv', self.root/'diagnosis', spec=path)

    def cli(self, *args, input=None):
        return subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'scripts/value_lab.py'), *map(str, args)],
                              input=input, capture_output=True, encoding='utf-8', timeout=30)

    def test_default_help_is_short_but_legacy_commands_still_work(self):
        help_text = self.cli('--help')
        self.assertEqual(help_text.returncode, 0, help_text.stderr)
        self.assertIn('{doctor,freeze,evaluate,usage-card,compare-studies}', help_text.stdout)
        self.assertNotIn('diagnose', help_text.stdout)
        self.assertNotIn('registry-add', help_text.stdout)
        self.assertIn('registry-add', self.cli('--advanced', '--help').stdout)
        self.assertEqual(self.cli('demo', '--output', self.root/'demo').returncode, 0)
        result = self.cli('diagnose', self.root/'demo', '--output', self.root/'report')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'TRIAL_GUIDANCE_ONLY')

    def test_unhelpful_and_abandoned_feedback_never_become_actionable_ttfd(self):
        for answer in ('unhelpful\n', ''):
            output = self.root/('unhelpful' if answer else 'abandoned')
            result = self.cli('diagnose', CORPUS.parent/'wrong-bh.csv', '--check', 'bh', '--interactive', '--output', output, input=answer)
            self.assertEqual(result.returncode, 0, result.stderr)
            timing = load_json(output/'author-timing.json')
            self.assertIsNone(timing['time_to_first_actionable_diagnosis_seconds'])
            self.assertIn(timing['feedback'], ('unhelpful', 'abandoned'))


if __name__ == '__main__':
    unittest.main()
