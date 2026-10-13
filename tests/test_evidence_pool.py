import copy
import json
import unittest

from tests.optional import available, requires
from value_lab.core import ValidationError, suite_digest
from value_lab.evidence_pool import (seed_pool, inspect_pool, public_manifest,
                                     review_statement, custody_statement)


class PoolTests(unittest.TestCase):
    def test_thirty_candidates_are_not_thirty_validated_families(self):
        pool = seed_pool()
        state = inspect_pool(pool, {'keys': []})
        self.assertEqual(state['candidate_families'], 30)
        self.assertEqual(state['accepted_development_families'], 0)
        self.assertEqual(state['attested_heldout_families'], 0)
        self.assertEqual(state['status'], 'AWAITING_EVIDENCE')
        self.assertIsNone(state['evaluation_family_target'])
        self.assertEqual(state['positive_verdict_ceiling'], 'SIMULATION_ONLY')

    def test_public_export_contains_no_answer_or_forbidden_labels(self):
        result = public_manifest(seed_pool(), {'keys': []})
        encoded = json.dumps(result)
        for word in ('reference_answer', 'legal_variants', 'forbidden_examples', 'included_ids'):
            self.assertNotIn(word, encoded)
        self.assertEqual(result['heldout'], [])

    def test_power_requirement_is_not_replaced_by_thirty(self):
        from value_lab.core import demo_suite
        suite = demo_suite()
        suite['policy']['power_plan'] = {'expected_family_sd': .2, 'minimum_detectable_delta': .1,
                                         'alpha': .05, 'power': .8}
        status = inspect_pool(seed_pool(), {'keys': []}, suite)
        self.assertEqual(status['evaluation_family_target'], 32)
        suite['policy']['power_plan']['expected_family_sd'] = .02
        self.assertEqual(inspect_pool(seed_pool(), {'keys': []}, suite)['evaluation_family_target'], 30)

    def test_snapshot_tamper_duplicate_and_untraceable_reference_rejected(self):
        for change in ('snapshot', 'duplicate', 'reference'):
            pool = seed_pool()
            f = pool['development'][0]['family']
            if change == 'snapshot':
                f['input_snapshot']['records'][0]['text'] += ' changed'
            elif change == 'duplicate':
                pool['development'].append(copy.deepcopy(pool['development'][0]))
            else:
                f['reference_answer']['evidence_spans'][f['reference_answer']['included_ids'][0]] = 'missing span'
            with self.assertRaises(ValidationError):
                inspect_pool(pool, {'keys': []})


@requires('cryptography')
@unittest.skipUnless(available('cryptography'), 'requires: cryptography')
class SignedPoolTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from value_lab.signatures import public_identity
        self.expert, self.custodian = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        self.trust = {'keys': [
            {**public_identity(self.expert.public_key()), 'identity': 'Fixture expert', 'organization': 'Fixture reviewers',
             'roles': ['domain_reviewer'], 'revoked': False},
            {**public_identity(self.custodian.public_key()), 'identity': 'Fixture custodian', 'organization': 'Fixture escrow',
             'roles': ['holdout_custodian'], 'revoked': False}]}

    def sign(self, payload, key, domain):
        from value_lab.signatures import sign
        return sign(payload, key, domain)

    def test_signature_binds_every_field_and_synthetic_cannot_become_real(self):
        pool = seed_pool()
        row = pool['development'][0]
        row['expert_signature'] = self.sign(review_statement(pool['id'], row['family']), self.expert, 'pvl-literature-review-1')
        self.assertEqual(inspect_pool(pool, self.trust)['accepted_development_families'], 0)
        row['family']['legal_variants'][0]['rationale'] += ' altered'
        with self.assertRaises(ValidationError):
            inspect_pool(pool, self.trust)

    def heldout_pool(self):
        pool = seed_pool()
        private = pool['development'].pop()['family']
        # Synthetic test of the ingestion contract; never shipped as real evidence.
        private['provenance']['kind'] = 'public_snapshot'
        statement = review_statement(pool['id'], private)
        pool['heldout'] = [{'family_id': private['id'], 'family_sha256': suite_digest(private),
                            'expert_statement': statement,
                            'expert_signature': self.sign(statement, self.expert, 'pvl-literature-review-1')}]
        pool['custody_signature'] = self.sign(custody_statement(pool), self.custodian, 'pvl-holdout-custody-1')
        return pool

    def test_custody_is_pinned_independent_and_not_proof_of_nonexposure(self):
        pool = self.heldout_pool()
        state = inspect_pool(pool, self.trust)
        self.assertEqual(state['attested_heldout_families'], 1)
        self.assertEqual(state['heldout_non_exposure'], 'ATTESTED_NOT_INDEPENDENTLY_OBSERVED')
        exported = public_manifest(pool, self.trust)
        self.assertNotIn('input_snapshot', exported['heldout'][0])
        self.trust['keys'][1]['organization'] = self.trust['keys'][0]['organization']
        with self.assertRaisesRegex(ValidationError, 'independent'):
            inspect_pool(pool, self.trust)

    def test_revocation_unknown_signer_and_split_overlap_rejected(self):
        pool = self.heldout_pool()
        with self.assertRaises(ValidationError):
            inspect_pool(pool, {'keys': []})
        self.trust['keys'][1]['revoked'] = True
        with self.assertRaises(ValidationError):
            inspect_pool(pool, self.trust)
        self.trust['keys'][1]['revoked'] = False
        pool['heldout'][0]['family_id'] = pool['development'][0]['family']['id']
        with self.assertRaises(ValidationError):
            inspect_pool(pool, self.trust)


if __name__ == '__main__':
    unittest.main()
