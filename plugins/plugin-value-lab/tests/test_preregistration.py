"""Cryptographic trust-boundary unit tests; generated keys are test-only."""
import copy
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from value_lab.signatures import sign, public_identity
from value_lab.preregistration import verify_reviewer
from value_lab.core import ValidationError


class ReviewSignatureTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.expected = {'suite_sha256':'a'*64, 'report_sha256':'b'*64, 'registration_sha256':'c'*64}
        self.statement = {'format':'pvl-study-review-1', 'reviewer_id':'TEST-ONLY-NOT-A-PERSON',
                          **self.expected, 'decision':'unknown', 'basis':'Unit test only'}
        self.signature = sign(self.statement, self.key, 'pvl-review-1')
        self.trust = {'keys':[{**public_identity(self.key.public_key()), 'identity':self.statement['reviewer_id'],
                             'organization':'TEST', 'roles':['domain_reviewer'], 'revoked':False}]}

    def test_separate_signature_preserves_unknown_review(self):
        result = verify_reviewer(self.statement, self.signature, self.trust, self.expected)
        self.assertEqual(result['decision'], 'unknown')
        self.assertIn('no independent person authentication', result['identity_basis'])

    def test_embedded_public_key_does_not_establish_trust(self):
        with self.assertRaises(ValidationError):
            verify_reviewer(self.statement, self.signature, {'keys':[]}, self.expected)

    def test_review_for_another_report_is_rejected(self):
        for field in self.expected:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                verify_reviewer(self.statement, self.signature, self.trust, {**self.expected, field:'d'*64})

    def test_tampering_with_signed_decision_is_rejected(self):
        with self.assertRaises(ValidationError):
            verify_reviewer({**self.statement,'decision':'accept'}, self.signature, self.trust, self.expected)

    def test_signing_placeholder_targets_does_not_verify_a_review(self):
        expected = {key: 'unknown' for key in self.expected}
        statement = {**self.statement, **expected}
        signature = sign(statement, self.key, 'pvl-review-1')
        with self.assertRaises(ValidationError):
            verify_reviewer(statement, signature, self.trust, expected)

    def test_revoked_wrong_role_and_identity_mismatch_are_rejected(self):
        for field,value in [('revoked',True), ('roles',['publisher']), ('identity','other')]:
            trust = copy.deepcopy(self.trust)
            trust['keys'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                verify_reviewer(self.statement, self.signature, trust, self.expected)


if __name__ == '__main__':
    unittest.main()
