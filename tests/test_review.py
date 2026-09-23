import tempfile
import unittest
from pathlib import Path

from value_lab.core import ValidationError, demo_records, demo_suite, load_json
from value_lab.review import apply_reviews, review_pack


class ReviewTests(unittest.TestCase):
    def test_packet_is_masked_and_input_binding_enforced(self):
        suite = demo_suite()
        suite["cases"][0]["graders"][0].update(type="human", rubric="Does the cited source support this output?")
        records = demo_records(suite)
        with tempfile.TemporaryDirectory() as directory:
            result = review_pack(suite, records, directory)
            packet = load_json(result["reviewer_packet"])
            mapping = load_json(result["operator_mapping"])
            self.assertEqual(len(packet["items"]), 6)
            self.assertIn("prompt", packet["items"][0])
            self.assertNotIn('"arm"', Path(result["reviewer_packet"]).read_text(encoding="utf-8"))
            token = packet["items"][0]["review_id"]
            decision = {"review_id": token, "grader_id": "source", "passed": None,
                        "reviewer": "test-reviewer", "rationale": "Disputed; supporting material missing"}
            revised = apply_reviews(suite, records, mapping, [decision])
            index = mapping["mapping"][token]["record_index"]
            self.assertIsNone(revised[index]["reviews"]["source"]["passed"])
            self.assertNotIn("reviews", records[index])
            records[index]["output"] = "tampered"
            with self.assertRaises(ValidationError):
                apply_reviews(suite, records, mapping, [decision])


if __name__ == "__main__":
    unittest.main()
