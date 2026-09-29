from pathlib import Path
import tempfile
import unittest
from value_lab.core import ValidationError, load_json, write_json
from value_lab.diagnostic_review import prepare, score


class DiagnosticReviewTests(unittest.TestCase):
    def test_missing_answers_remain_in_denominator_and_humans_pending(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'study'
            answer = {'producer_call': 'w', 'skill_call': 'UNKNOWN', 'replacement_component': 'UNKNOWN'}
            prepare([{'id': '1', 'report': 'report only', 'answer': answer, 'source': 'fixture'}], root)
            self.assertNotIn('answer', str(load_json(root / 'reviewer/packet.json')))
            r = score(root, {'cases': []}, elapsed_seconds=5, response_metadata={})
            self.assertEqual(r['exact_case_accuracy'], 0)
            self.assertIsNone(r['human_reading_seconds'])
            self.assertEqual(r['human_validation'], 'PENDING')
            r = score(root, {'cases': [{'id': '1', **answer}]}, elapsed_seconds=5, response_metadata={})
            self.assertEqual(r['exact_case_accuracy'], 1)
            key = load_json(root / 'private/answer-key.json')
            key['cases'][0]['answer']['producer_call'] = 'changed'
            write_json(root / 'private/answer-key.json', key)
            with self.assertRaises(ValidationError):
                score(root, {'cases': []}, elapsed_seconds=5, response_metadata={})
