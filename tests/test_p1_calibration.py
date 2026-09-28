"""Computational calibration, not independent scientific validation."""
import csv
import json
from pathlib import Path
import random
import tempfile
import unittest

from value_lab.artifacts import grade_artifact, sha
from value_lab.core import load_json
from value_lab.methodology import audit_detector

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / 'examples/scientific-calibration'


class ScientificCalibrationTests(unittest.TestCase):
    def test_all_frozen_development_controls_match_declared_expectations(self):
        manifest = load_json(CORPUS / 'manifest.json')
        report = audit_detector(CORPUS / 'manifest.json', verifier_root=CORPUS)
        self.assertEqual(len(report['cases']), 22)
        for row in report['cases']:
            with self.subTest(case=row['id']):
                self.assertIs(row['passed'], manifest['expected_passed'][row['id']], row['reason'])
        self.assertEqual(report['summary']['FP'], 0)
        self.assertEqual(report['summary']['FN'], 0)
        self.assertEqual(report['summary']['UNKNOWN'], 3)
        self.assertEqual(report['summary']['EXCLUDED_LABEL'], 2)
        self.assertIsNone(report['summary']['detection']['rate'])
        self.assertIsNone(report['representative_accuracy'])
        self.assertEqual(report['heldout_generalization'], 'NOT_ESTABLISHED')

    def test_method_dispute_and_invalid_design_do_not_become_scientific_defects(self):
        rows = {r['id']: r for r in audit_detector(CORPUS / 'manifest.json', verifier_root=CORPUS)['cases']}
        self.assertFalse(rows['by-method-dispute']['passed'])
        self.assertIsNone(rows['paired-unresolved-identity']['passed'])
        for key in ('by-method-dispute', 'paired-unresolved-identity'):
            self.assertEqual(rows[key]['classification'], 'EXCLUDED_LABEL')

    def test_missing_scorer_root_never_passes_calibration(self):
        report = audit_detector(CORPUS / 'manifest.json')
        self.assertEqual(report['summary']['TN'], 0)
        self.assertGreater(report['summary']['UNKNOWN'], 0)

    def test_bh_independent_scipy_crosscheck_ties_extremes_and_order(self):
        from scipy.stats import false_discovery_control
        rng = random.Random(20260928)
        vectors = [[0, 0, 1, 1], [.01, .03, .04], [1e-300, 1e-200, 1e-100], [1],
                   *[[rng.choice([0, .01, .05, .9, 1, rng.random()]) for _ in range(17)] for _ in range(40)]]
        rule = load_json(CORPUS / 'manifest.json')['cases'][0]['grader']
        rule['verifier'].pop('testing_family')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'result.csv'
            for values in vectors:
                oracle = false_discovery_control([float(v) for v in values], method='bh')
                path.write_text('gene,p_value,q_value,log2fc\n' + ''.join(
                    f'g{i},{p},{q},0\n' for i, (p, q) in enumerate(zip(values, oracle))), encoding='utf-8')
                record = {'artifacts': {'result': {'path': path.name, 'sha256': sha(path)}}}
                self.assertTrue(grade_artifact(rule, record, directory)[0])

    def test_paired_manual_reference_agrees_with_scipy_independent_implementation(self):
        import numpy as np
        from scipy.stats import permutation_test
        result = load_json(CORPUS / 'paired-correct.json')
        oracle = permutation_test((np.arange(4.) + 4, np.arange(4.)), lambda a, b: np.mean(a) - np.mean(b),
                                  permutation_type='samples', n_resamples=np.inf, vectorized=False)
        self.assertAlmostEqual(result['results'][0]['p_value'], oracle.pvalue)
        self.assertAlmostEqual(result['results'][0]['effect'], oracle.statistic)

    def test_original_false_alarms_and_misses_are_not_erased(self):
        report = audit_detector(ROOT / 'examples/detector-corpus/manifest.json')
        self.assertGreater(report['summary']['FP'], 0)
        self.assertGreater(report['summary']['FN'], 0)


if __name__ == '__main__':
    unittest.main()
