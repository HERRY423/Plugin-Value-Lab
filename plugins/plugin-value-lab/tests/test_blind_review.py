from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from value_lab.blind_review import prepare, score, metrics
from value_lab.core import ValidationError, load_json, write_json

CORPUS = Path(__file__).resolve().parents[1] / 'examples/scientific-calibration'


class BlindReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'review'
        self.prepared = prepare(CORPUS / 'manifest.json', [
            {'case_id': k, 'task': 'Check BH on the supplied family.', 'materials': []}
            for k in ('bh-correct', 'bh-no-reverse-minimum')], self.root, verifier_root=CORPUS)
        self.labels = load_json(self.root / 'reviewer/labels.template.json')
        self.labels['reviewer'] = {'kind': 'model', 'name': 'External model', 'model': 'fixture-model',
                                  'expertise': 'Software fixture', 'non_author': True, 'conflict_free': True, 'blinded': True}
        for row in self.labels['labels']:
            row.update(label='valid', rationale='Manufactured test label, not a review')

    def score(self):
        write_json(self.root / 'labels.json', self.labels)
        return score(self.root / 'controller.private.json', self.prepared['controller_sha256'],
                     self.root / 'reviewer/packet.json', self.root / 'labels.json')

    def test_packet_omits_original_ids_labels_and_detector_results(self):
        packet = load_json(self.root / 'reviewer/packet.json')
        for row in packet['cases']:
            self.assertEqual(set(row), {'id', 'task', 'artifact', 'materials'})
            self.assertNotIn('bh-', row['id'])
        self.assertFalse((self.root / 'reviewer/controller.private.json').exists())

    def test_model_reference_separate_from_author_not_human(self):
        report = self.score()
        self.assertEqual(report['reference_class'], 'EXTERNAL_MODEL_REVIEW')
        self.assertEqual(report['reviewer_selected']['FP'], 1)
        self.assertEqual(report['author_selected']['TP'], 1)
        self.assertEqual(len(report['disagreements']), 1)
        self.assertEqual(report['independent_expert_validation'], 'NOT_ESTABLISHED')

    def test_partial_duplicate_and_wrong_packet_rejected(self):
        original = deepcopy(self.labels)
        for mode in ('missing', 'duplicate', 'packet'):
            self.labels = deepcopy(original)
            if mode == 'missing':
                self.labels['labels'].pop()
            elif mode == 'duplicate':
                self.labels['labels'][1] = self.labels['labels'][0]
            else:
                self.labels['packet_sha256'] = '0' * 64
            with self.assertRaises(ValidationError):
                self.score()

    def test_non_author_conflict_and_blinding_not_assumed(self):
        for field in ('non_author', 'conflict_free', 'blinded'):
            original = deepcopy(self.labels)
            self.labels['reviewer'][field] = False
            with self.assertRaises(ValidationError):
                self.score()
            self.labels = original

    def test_unknowns_preserved_in_label_and_detector_denominators(self):
        report = metrics([{'label': 'defect', 'passed': False}, {'label': 'defect', 'passed': None},
                          {'label': 'unknown', 'passed': True}, {'label': 'disputed', 'passed': False}])
        self.assertIsNone(report['detection']['rate'])
        self.assertEqual((report['detection']['lower'], report['detection']['upper']), (.5, 1))
        self.assertEqual(report['UNLABELED'], 1)
        self.assertEqual(report['EXCLUDED_LABEL'], 1)


if __name__ == '__main__':
    unittest.main()
