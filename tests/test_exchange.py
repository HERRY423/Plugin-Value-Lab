from pathlib import Path
import tempfile
import unittest
from value_lab.core import ValidationError, demo_suite, freeze, write_json
from value_lab.exchange import link_evidence


class ExchangeTests(unittest.TestCase):
    def test_synthetic_decisions_do_not_become_real_host_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suite = demo_suite()
            suite["evidence_type"] = "local"
            write_json(root / "suite.json", suite)
            freeze(suite, root / "protocol.lock.json")
            artifact = root / "offline-decisions.json"
            write_json(artifact, {"score": 1, "evidence_type": "synthetic"})
            result = link_evidence(root, artifact, "arena:fixture", "synthetic")
            self.assertEqual(result["host_layer"]["observed_records"], 0)
            self.assertEqual(result["decision_layer"]["evidence_type"], "synthetic")
            self.assertIsNone(result["combined_value_verdict"])
            suite["cases"][0]["prompt"] = "changed"
            write_json(root / "suite.json", suite)
            with self.assertRaises(ValidationError):
                link_evidence(root, artifact, "arena:fixture", "synthetic")
