"""Paired pilot variance, provenance separation and uncertainty boundaries."""
import copy
import hashlib
import random
import unittest

from value_lab.core import ValidationError, suite_digest
from value_lab.pilot import summarize_pilot, validate_disjoint, validated_source


def pilot_packet():
    records = []
    for family, family_effect in enumerate((-.2, 0, .2)):
        for task, task_effect in enumerate((-.1, .1)):
            task_id = f'pilot-task-{family}-{task}'
            for repetition, noise in enumerate((-.05, .05), 1):
                baseline = .5 + .2 * family_effect + .2 * task_effect + .2 * noise
                records.append({
                    'family_id': f'pilot-family-{family}', 'task_id': task_id,
                    'input_sha256': hashlib.sha256(task_id.encode()).hexdigest(), 'repetition': repetition,
                    'with_score': baseline + family_effect + task_effect + noise, 'without_score': baseline,
                    'with_run_id': f'pilot-with-{task_id}-{repetition}',
                    'without_run_id': f'pilot-without-{task_id}-{repetition}',
                    'with_session_id': f'pilot-with-session-{task_id}-{repetition}',
                    'without_session_id': f'pilot-without-session-{task_id}-{repetition}',
                    'source_ref': f'local-fixture://pilot/{task_id}/{repetition}',
                })
    return {'version': 1, 'pilot_id': 'manufactured-pilot', 'evidence_type': 'synthetic',
            'endpoint': 'outcome_quality', 'task_source': 'Manufactured balanced fixture, not researcher data',
            'independence_rationale': 'Independent-family assumption is for this test fixture only', 'records': records}


def confirmation_suite():
    return {'cases': [{'id': 'confirm-task', 'cluster': 'confirm-family',
                       'input_sha256': hashlib.sha256(b'confirmation input').hexdigest()}]}


class PilotTests(unittest.TestCase):
    def test_known_balanced_anova_and_pair_covariance(self):
        # Orthogonal effects: family=(-.2,0,.2), task=(-.1,.1), noise=(-.05,.05).
        result = summarize_pilot(pilot_packet())
        self.assertEqual(result['design']['paired_observations'], 12)
        self.assertEqual(result['design']['generation_runs'], 24)
        self.assertEqual([row['degrees_of_freedom'] for row in result['anova']], [2, 3, 6])
        for row, expected in zip(result['anova'], (.16, .04, .005)):
            self.assertAlmostEqual(row['mean_square'], expected, places=13)
        for row, expected in zip(result['variance_components'], (.03, .0175, .005)):
            self.assertAlmostEqual(row['raw_variance'], expected, places=13)
            self.assertFalse(row['truncated'])
            self.assertAlmostEqual(row['sd']**2, expected, places=13)
        covariance = result['arm_covariance']
        self.assertAlmostEqual(covariance['paired_sample_covariance'], .1128 / 11)
        self.assertAlmostEqual(covariance['paired_difference_sample_variance'], .47 / 11)
        self.assertAlmostEqual(covariance['reconstructed_difference_variance'], .47 / 11)
        self.assertTrue(covariance['identity_verified'])
        self.assertLess(covariance['paired_difference_sample_variance'],
                        covariance['with_sample_variance'] + covariance['without_sample_variance'])

    def test_deterministic_cluster_uncertainty_preserves_rng_and_nested_sampling(self):
        random.seed(500)
        before = random.getstate()
        result = summarize_pilot(pilot_packet())
        self.assertEqual(random.getstate(), before)
        self.assertEqual(result, summarize_pilot(pilot_packet()))
        uncertainty = result['uncertainty']
        self.assertGreaterEqual(uncertainty['resamples'], 1000)
        self.assertFalse(uncertainty['hard_variance_bound'])
        self.assertEqual(uncertainty['planning_upper_quantile'], .975)
        self.assertEqual(set(uncertainty['planning_sd_upper95']),
                         {'between_family_sd', 'between_task_sd', 'within_task_sd'})
        # Every family in this fixture has the same within-family/task SS.
        # Resampling whole families must therefore preserve these two estimates.
        for name, expected in [('between_task_sd', .0175), ('within_task_sd', .005)]:
            self.assertAlmostEqual(uncertainty['sd_intervals'][name]['lower']**2, expected)
            self.assertAlmostEqual(uncertainty['sd_intervals'][name]['upper']**2, expected)
            self.assertTrue(uncertainty['sd_intervals'][name]['degenerate_bootstrap'])
        self.assertEqual(uncertainty['planning_sd_upper95']['between_family_sd'],
                         uncertainty['sd_intervals']['between_family_sd']['upper'])
        self.assertTrue(any('SMALL_PILOT' in warning for warning in result['warnings']))
        self.assertTrue(any('BOOTSTRAP_UNCERTAINTY_UNRESOLVED' in warning for warning in result['warnings']))
        self.assertTrue(any('approximate' in note for note in result['limitations']))

    def test_retains_sources_identities_and_copies_original_packet(self):
        packet = pilot_packet()
        digest = suite_digest(packet)
        result = summarize_pilot(packet)
        self.assertEqual(result['source_packet_sha256'], digest)
        self.assertEqual(result['source_packet'], packet)
        self.assertEqual(len(result['identities']['tasks']), 6)
        self.assertEqual(len(result['identities']['run_ids']), 24)
        self.assertEqual(len(result['identities']['session_ids']), 24)
        self.assertEqual(len(result['identities']['tasks'][0]['source_refs']), 2)
        self.assertEqual(result['evidence_type'], 'synthetic')
        self.assertFalse(result['executed'])
        packet['records'][0]['with_score'] = 0
        self.assertNotEqual(packet, result['source_packet'])

    def test_constant_pilot_requires_explicit_floors_not_zero_risk(self):
        packet = pilot_packet()
        for row in packet['records']:
            row['with_score'] = row['without_score'] = .5
        result = summarize_pilot(packet)
        self.assertEqual(result['status'], 'VARIANCE_FLOOR_REQUIRED')
        self.assertEqual(set(result['uncertainty']['variance_floor_required']),
                         {'between_family_sd', 'between_task_sd', 'within_task_sd'})
        self.assertTrue(all(row['requires_variance_floor'] for row in result['variance_components']))
        self.assertTrue(all(value == 0 for value in result['uncertainty']['planning_sd_upper95'].values()))

    def test_negative_anova_components_remain_visible(self):
        packet = pilot_packet()
        for row in packet['records']:
            row['without_score'] = .5
            row['with_score'] = .4 if row['repetition'] == 1 else .6
        result = summarize_pilot(packet)
        task_component = result['variance_components'][1]
        self.assertAlmostEqual(task_component['raw_variance'], -.01)
        self.assertEqual(task_component['variance'], 0)
        self.assertTrue(task_component['truncated'])
        self.assertTrue(task_component['requires_variance_floor'])
        self.assertTrue(any('NEGATIVE_ANOVA_COMPONENT_TRUNCATED' in warning for warning in result['warnings']))

    def test_strict_packet_and_numeric_validation(self):
        for field, value in [('version', True), ('version', 2), ('evidence_type', 'estimated'),
                             ('endpoint', 'cost'), ('task_source', ''), ('independence_rationale', ''),
                             ('records', []), ('unexpected', 1)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                summarize_pilot({**pilot_packet(), field: value})
        for field, value in [('with_score', True), ('without_score', -1), ('with_score', 1.01),
                             ('with_score', float('nan')), ('with_score', float('inf')),
                             ('repetition', True), ('repetition', 0), ('input_sha256', 'not-a-hash'),
                             ('source_ref', ''), ('extra', 1)]:
            packet = pilot_packet()
            packet['records'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                summarize_pilot(packet)

    def test_rejects_unbalanced_incomplete_or_small_pilots(self):
        packet = pilot_packet()
        altered = [packet['records'][:-1], packet['records'][:-2], packet['records'][:-4],
                   [row for row in packet['records'] if row['repetition'] == 1]]
        for records in altered:
            with self.subTest(count=len(records)), self.assertRaises(ValidationError):
                summarize_pilot({**packet, 'records': records})
        packet['records'][0]['repetition'] = 3
        with self.assertRaisesRegex(ValidationError, 'consecutive'):
            summarize_pilot(packet)

    def test_rejects_pair_duplicates_task_relabelling_and_reused_input(self):
        packet = pilot_packet()
        packet['records'].append(copy.deepcopy(packet['records'][0]))
        with self.assertRaisesRegex(ValidationError, 'Duplicate'):
            summarize_pilot(packet)
        for change in ({'family_id': 'different'}, {'input_sha256': 'f' * 64}):
            packet = pilot_packet()
            packet['records'][0].update(change)
            with self.assertRaisesRegex(ValidationError, 'one family and one input'):
                summarize_pilot(packet)
        packet = pilot_packet()
        packet['records'][2]['input_sha256'] = packet['records'][0]['input_sha256']
        with self.assertRaisesRegex(ValidationError, 'different task IDs'):
            summarize_pilot(packet)

    def test_rejects_run_and_session_reuse_across_arms_and_records(self):
        for target, source in [('without_run_id', 'with_run_id'),
                               ('without_session_id', 'with_session_id'),
                               ('without_session_id', 'with_run_id')]:
            packet = pilot_packet()
            packet['records'][0][target] = packet['records'][0][source]
            with self.subTest(target=target, source=source), self.assertRaisesRegex(ValidationError, 'identity reused'):
                summarize_pilot(packet)
        packet = pilot_packet()
        packet['records'][1]['with_run_id'] = packet['records'][0]['with_run_id']
        with self.assertRaisesRegex(ValidationError, 'identity reused'):
            summarize_pilot(packet)
        packet = pilot_packet()
        del packet['records'][0]['without_session_id']
        with self.assertRaisesRegex(ValidationError, 'both arms'):
            summarize_pilot(packet)

    def test_missing_sessions_retained_as_unknown(self):
        packet = pilot_packet()
        for row in packet['records']:
            del row['with_session_id'], row['without_session_id']
        result = summarize_pilot(packet)
        self.assertEqual(result['identities']['session_ids'], [])
        self.assertTrue(any('SESSION_PROVENANCE_INCOMPLETE' in warning for warning in result['warnings']))

    def test_independent_confirmation_passes_and_all_three_identity_overlaps_block(self):
        packet = pilot_packet()
        self.assertEqual(validate_disjoint(packet, confirmation_suite()), [])
        source = packet['records'][0]
        for field, value, code in [('id', source['task_id'], 'PILOT_TASK_OVERLAP'),
                                   ('cluster', source['family_id'], 'PILOT_FAMILY_OVERLAP'),
                                   ('input_sha256', source['input_sha256'].upper(), 'PILOT_INPUT_OVERLAP')]:
            suite = confirmation_suite()
            suite['cases'][0][field] = value
            self.assertTrue(any(code in issue for issue in validate_disjoint(packet, suite)))

    def test_confirmation_identity_missing_or_reused_is_unknown_not_disjoint(self):
        packet = pilot_packet()
        for field in ('id', 'cluster', 'input_sha256'):
            suite = confirmation_suite()
            del suite['cases'][0][field]
            self.assertTrue(any('MISSING_CONFIRMATION_IDENTITY' in issue for issue in validate_disjoint(packet, suite)))
        for suite in ({}, {'cases': []}, {'cases': [None]}):
            self.assertTrue(validate_disjoint(packet, suite))
        suite = confirmation_suite()
        suite['cases'].append(copy.deepcopy(suite['cases'][0]))
        self.assertTrue(any('REUSED_CONFIRMATION_TASK_OR_INPUT' in issue for issue in validate_disjoint(packet, suite)))

    def test_execution_overlap_missing_and_reused_ids_block(self):
        packet, suite = pilot_packet(), confirmation_suite()
        self.assertEqual(validate_disjoint(packet, suite, [{'session_id': 'fresh-session'}]), [])
        self.assertEqual(validate_disjoint(packet, suite, [{'run_id': 'fresh-run'}]), [])
        for record in ({'run_id': packet['records'][0]['with_run_id']},
                       {'session_id': packet['records'][0]['with_run_id']},
                       {'run_id': packet['records'][0]['with_session_id']}):
            self.assertTrue(any('PILOT_EXECUTION_OVERLAP' in issue for issue in validate_disjoint(packet, suite, [record])))
        for records in ([], [{}], [{'run_id': '', 'session_id': 'fresh'}], [None]):
            self.assertTrue(validate_disjoint(packet, suite, records))
        self.assertTrue(any('REUSED_CONFIRMATION_EXECUTION' in issue for issue in
                            validate_disjoint(packet, suite, [{'run_id': 'same'}, {'session_id': 'same'}])))

    def test_summary_must_replay_before_reuse_and_source_hash_is_bound(self):
        packet = pilot_packet()
        summary = summarize_pilot(packet)
        self.assertEqual(validated_source(summary), packet)
        self.assertEqual(validate_disjoint(summary, confirmation_suite()), [])
        for corruption in ('hash', 'derived', 'source'):
            altered = copy.deepcopy(summary)
            if corruption == 'hash':
                altered['source_packet_sha256'] = '0' * 64
            elif corruption == 'derived':
                altered['uncertainty']['planning_sd_upper95']['between_family_sd'] = 0
            else:
                altered['source_packet']['records'][0]['with_score'] = .5
            with self.subTest(corruption=corruption), self.assertRaises(ValidationError):
                validated_source(altered)
            self.assertTrue(any('INVALID_PILOT_SOURCE' in issue for issue in
                                validate_disjoint(altered, confirmation_suite())))


if __name__ == '__main__':
    unittest.main()
