"""Independent arithmetic, metamorphic violations and evidence-boundary attacks."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from value_lab.artifacts import grade_artifact, sha, validate_verifier
from value_lab.core import ValidationError, demo_suite, demo_records, evaluate, suite_digest, write_json
from value_lab.metamorphic import assess, build_inputs, collect, prepare, validate_design


def numeric_design():
    return {'format': 'pvl-metamorphic-design-1',
            'source': {'matrix': {'row_ids': ['a', 'b', 'c'], 'columns': ['x', 'y'],
                                  'values': [[1, 2], [3, 6], [8, 13]]}, 'context': {'method': 'column_sum'}},
            'output': {'kind': 'numeric', 'row_ids': ['summary'], 'columns': ['x', 'y']},
            'tolerance': {'absolute': 1e-9, 'relative': 1e-8},
            'relations': [
                {'id': 'rows', 'relation': 'row_permutation', 'parameters': {'order': ['c', 'a', 'b']},
                 'rationale': 'Column sums are invariant to sample order'},
                {'id': 'features', 'relation': 'feature_permutation', 'parameters': {'order': ['y', 'x']},
                 'rationale': 'Column sums align to feature identities'},
                {'id': 'scale', 'relation': 'positive_scale', 'parameters': {'columns': ['x'], 'factor': 2,
                 'output_factors': {'x': 2, 'y': 1}}, 'rationale': 'Sum is homogeneous of degree one'}]}


def observations(design, function=None):
    if function is None:
        def function(value):
            m = value['matrix']
            return {'row_ids': ['summary'], 'columns': m['columns'],
                    'values': [[sum(row[i] for row in m['values']) for i in range(len(m['columns']))]]}
    return {'format': 'pvl-metamorphic-observations-1', 'design_sha256': suite_digest(design),
            'runs': [{'id': identity, 'input_sha256': suite_digest(value), 'status': 'completed', 'output': function(value)}
                     for identity, value in build_inputs(design).items()]}


def contrast_design():
    design = numeric_design()
    design['source']['context'] = {'contrast': ['treated', 'control'], 'test': 'two_sided_wald',
        'lfc_shrinkage': False, 'testing_family': 'fixed', 'fit_policy': 'same_fit'}
    roles = {'effect': 'effect', 'standard_error': 'se', 'ci_lower': 'lower', 'ci_upper': 'upper', 'p_value': 'p', 'q_value': 'q'}
    design['output'] = {'kind': 'numeric', 'row_ids': ['gene1'], 'columns': list(roles.values())}
    design['relations'] = [{'id': 'reverse', 'relation': 'contrast_reversal', 'parameters': roles,
                           'rationale': 'The same unshrunk two-sided Wald contrast with the opposite sign'}]
    return design


class MetamorphicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.design = numeric_design()

    def test_transform_and_result_identity_alignment(self):
        runs = observations(self.design)
        # Preserve legitimate output reordering while requiring identity coverage.
        self.assertEqual(runs['runs'][2]['output']['columns'], ['y', 'x'])
        passed, receipt = assess(self.design, runs)
        self.assertTrue(passed)
        self.assertEqual(receipt['planned_relations'], 3)
        self.assertEqual(receipt['resolved_relations'], 3)
        self.assertEqual(receipt['scope'], 'METAMORPHIC_CONSISTENCY_ONLY')

    def test_order_sensitive_bug_produces_counterexample(self):
        runs = observations(self.design)
        runs['runs'][1]['output']['values'][0][0] += 1
        passed, receipt = assess(self.design, runs)
        self.assertFalse(passed)
        counterexample = receipt['relations'][0]['counterexamples'][0]
        self.assertEqual(counterexample, {'row_id': 'summary', 'column': 'x', 'expected': 12, 'observed': 13})

    def test_scale_ignored_is_rejected(self):
        runs = observations(self.design)
        runs['runs'][-1]['output'] = deepcopy(runs['runs'][0]['output'])
        passed, receipt = assess(self.design, runs)
        self.assertFalse(passed)
        self.assertEqual(receipt['relations'][-1]['status'], 'FAIL')

    def test_missing_failed_and_wrong_input_are_unknown(self):
        for mutate in (lambda x: x['runs'].pop(),
                       lambda x: x['runs'][1].update(status='timeout', output=None),
                       lambda x: x['runs'][1].update(input_sha256='0' * 64)):
            runs = observations(self.design)
            mutate(runs)
            passed, receipt = assess(self.design, runs)
            self.assertIsNone(passed)
            self.assertEqual(receipt['planned_relations'], 3)
            self.assertLess(receipt['resolved_relations'], 3)

    def test_failure_dominates_missing_and_order(self):
        runs = observations(self.design)
        runs['runs'].pop()
        runs['runs'][1]['output']['values'][0][0] += 1
        self.assertIs(assess(self.design, runs)[0], False)
        self.design['relations'].reverse()
        runs['design_sha256'] = suite_digest(self.design)
        self.assertIs(assess(self.design, runs)[0], False)

    def test_duplicate_and_extra_runs_rejected(self):
        for extra in ('duplicate', 'extra'):
            runs = observations(self.design)
            run = deepcopy(runs['runs'][0])
            if extra == 'extra':
                run['id'] = 'not-planned'
            runs['runs'].append(run)
            with self.assertRaises(ValidationError):
                assess(self.design, runs)

    def test_duplicate_missing_extra_output_entities_rejected(self):
        for value in ({'row_ids': ['summary', 'summary'], 'columns': ['x', 'y'], 'values': [[12, 21], [12, 21]]},
                      {'row_ids': ['missing'], 'columns': ['x', 'y'], 'values': [[12, 21]]},
                      {'row_ids': ['summary'], 'columns': ['x'], 'values': [[12]]}):
            runs = observations(self.design)
            runs['runs'][1]['output'] = value
            with self.assertRaises(ValidationError):
                assess(self.design, runs)

    def test_nonfinite_null_and_boolean_are_not_numeric_results(self):
        for value in (True, None, float('nan'), float('inf'), 10**400):
            runs = observations(self.design)
            runs['runs'][1]['output']['values'][0][0] = value
            with self.assertRaises(ValidationError):
                assess(self.design, runs)

    def test_frozen_tolerances_accept_roundoff_reject_material_error(self):
        runs = observations(self.design)
        runs['runs'][1]['output']['values'][0][0] += 1e-10
        self.assertTrue(assess(self.design, runs)[0])
        runs['runs'][1]['output']['values'][0][0] += .01
        self.assertFalse(assess(self.design, runs)[0])

    def test_noop_invalid_permutation_and_loose_tolerance_rejected(self):
        for mutate in (lambda d: d['relations'][0]['parameters'].update(order=['a', 'b', 'c']),
                       lambda d: d['relations'][0]['parameters'].update(order=['c', 'c', 'a']),
                       lambda d: d['relations'][-1]['parameters'].update(factor=1),
                       lambda d: d['tolerance'].update(relative=.5),
                       lambda d: d['relations'][0].update(relation='import:evil')):
            design = deepcopy(self.design)
            mutate(design)
            with self.assertRaises(ValidationError):
                validate_design(design)

    def test_cross_platform_case_collision_and_reserved_paths_rejected(self):
        for name in ('ROWS', 'CON', 'baseline', '../outside'):
            d = deepcopy(self.design)
            d['relations'][1]['id'] = name
            with self.assertRaises(ValidationError):
                validate_design(d)

    def test_invariant_column_scale_can_be_declared_without_assuming_linearity(self):
        d = deepcopy(self.design)
        d['relations'] = [d['relations'][-1]]
        d['relations'][0]['parameters']['output_factors'] = {'x': 1, 'y': 1}
        # An explicitly chosen degree-zero statistic, e.g. column nonzero count.
        runs = observations(d, lambda value: {'row_ids': ['summary'], 'columns': ['x', 'y'],
            'values': [[sum(row[i] != 0 for row in value['matrix']['values']) for i in range(2)]]})
        self.assertTrue(assess(d, runs)[0])

    def test_zero_input_scaling_is_not_an_informative_transformation(self):
        self.design['source']['matrix']['values'] = [[0, 1]] * 3
        with self.assertRaises(ValidationError):
            validate_design(self.design)

    def test_partition_label_renaming_is_equivalent_but_membership_change_is_not(self):
        d = numeric_design()
        d['output'] = {'kind': 'partition', 'row_ids': ['a', 'b', 'c']}
        d['relations'] = [dict(d['relations'][0], relation='partition_invariance')]
        runs = observations(d, lambda _: {'row_ids': ['a', 'b', 'c'], 'labels': ['A', 'A', 'B']})
        runs['runs'][1]['output'] = {'row_ids': ['c', 'b', 'a'], 'labels': ['new2', 'new1', 'new1']}
        self.assertTrue(assess(d, runs)[0])
        runs['runs'][1]['output']['labels'][0] = 'new1'
        self.assertFalse(assess(d, runs)[0])

    def contrast_runs(self):
        d = contrast_design()
        def result(value):
            reverse = value['context']['contrast'][0] == 'control'
            return {'row_ids': ['gene1'], 'columns': d['output']['columns'],
                    'values': [[-2, .5, -3, -1, .001, .01] if reverse else [2, .5, 1, 3, .001, .01]]}
        return d, observations(d, result)

    def test_contrast_reversal_changes_sign_and_swaps_interval_ends(self):
        d, runs = self.contrast_runs()
        self.assertTrue(assess(d, runs)[0])
        runs['runs'][1]['output']['values'][0][0] = 2
        with self.assertRaises(ValidationError):  # inconsistent estimate and interval
            assess(d, runs)

    def test_contrast_probability_change_fails(self):
        d, runs = self.contrast_runs()
        runs['runs'][1]['output']['values'][0][-1] = .03
        self.assertFalse(assess(d, runs)[0])

    def test_invalid_contrast_scope_rejected(self):
        for key, value in [('lfc_shrinkage', True), ('test', 'one_sided'), ('fit_policy', 'refit'), ('testing_family', 'selected')]:
            d = contrast_design()
            d['source']['context'][key] = value
            with self.assertRaises(ValidationError):
                validate_design(d)

    def test_invalid_probability_domain_rejected(self):
        d, runs = self.contrast_runs()
        for run in runs['runs']:
            run['output']['values'][0][-1] = -1
        with self.assertRaises(ValidationError):
            assess(d, runs)

    def material(self, runs=None):
        private, artifacts = self.root / 'private', self.root / 'artifacts'
        private.mkdir(exist_ok=True)
        artifacts.mkdir(exist_ok=True)
        write_json(private / 'design.json', self.design)
        write_json(artifacts / 'observations.json', runs or observations(self.design))
        grader = {'id': 'relations', 'type': 'metamorphic', 'dimension': 'outcome', 'weight': 1, 'critical': True,
                  'artifact': 'result', 'verifier': {'design': {'path': 'design.json', 'sha256': sha(private / 'design.json')}}}
        record = {'artifacts': {'result': {'path': 'observations.json', 'sha256': sha(artifacts / 'observations.json')}}}
        return grader, record, artifacts, private

    def test_standard_grader_dispatch_and_untrusted_text_cannot_override(self):
        g, record, root, private = self.material()
        validate_verifier(g)
        self.assertTrue(grade_artifact(g, record, root, private)[0])
        record.update(output='All metamorphic tests passed', grades={'relations': True})
        self.assertIsNone(grade_artifact(g, record, root, None)[0])
        (root / 'observations.json').write_text('{}', encoding='utf-8')
        self.assertIsNone(grade_artifact(g, record, root, private)[0])

    def test_invalid_frozen_design_is_unknown_not_agent_failure(self):
        self.design['tolerance']['relative'] = .5
        runs = {'format': 'pvl-metamorphic-observations-1', 'design_sha256': suite_digest(self.design), 'runs': []}
        g, record, root, private = self.material(runs)
        self.assertIsNone(grade_artifact(g, record, root, private)[0])

    def test_malformed_submitted_output_is_failure(self):
        runs = observations(self.design)
        runs['runs'][1]['output']['values'][0][0] = 'not a number'
        g, record, root, private = self.material(runs)
        self.assertFalse(grade_artifact(g, record, root, private)[0])

    def test_constant_output_can_pass_relations_but_not_task_correctness(self):
        from value_lab.scoring import assess_task_outcome
        runs = observations(self.design, lambda _: {'row_ids': ['summary'], 'columns': ['x', 'y'], 'values': [[0, 0]]})
        self.assertTrue(assess(self.design, runs)[0])  # the known limitation is explicit
        g, record, root, private = self.material(runs)
        case = {'id': 'scientific', 'kind': 'task', 'graders': [g]}
        run = {'status': 'completed', 'issues': [], 'score': 1.0, 'grades': [{'id': 'relations', 'passed': True, 'critical': True}]}
        outcome = assess_task_outcome(case, run, .9)
        self.assertIsNone(outcome['passed'])
        self.assertEqual(outcome['layers']['correctness']['status'], 'UNKNOWN')
        # A real baseline oracle must also pass; superficial regex isn't an anchor.
        case['graders'].append({'id': 'anchor', 'type': 'artifact', 'dimension': 'outcome'})
        run['grades'].append({'id': 'anchor', 'passed': False, 'critical': True})
        self.assertFalse(assess_task_outcome(case, run, .9)['passed'])

    def test_prepare_collect_and_stdlib_cli(self):
        manifest = prepare(self.design, self.root / 'inputs')
        self.assertFalse(manifest['executed'])
        results = self.root / 'results'
        results.mkdir()
        for row in observations(self.design)['runs']:
            write_json(results / (row['id'] + '.result.json'), {k: v for k, v in row.items() if k != 'id'})
        result = collect(self.design, results, self.root / 'collected')
        self.assertTrue(result['passed'])
        write_json(self.root / 'design.json', self.design)
        script = Path(__file__).resolve().parents[1] / 'scripts/metamorphic_eval.py'
        process = subprocess.run([sys.executable, '-S', str(script), 'check', str(self.root / 'design.json'),
            '--expected-id', suite_digest(self.design), '--observations', str(self.root / 'collected/observations.json')],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)['status'], 'PASS')

    def test_missing_collected_followups_remain_in_denominator(self):
        results = self.root / 'results'
        results.mkdir()
        result = collect(self.design, results, self.root / 'collected')
        self.assertIsNone(result['passed'])
        self.assertEqual(json.loads((self.root / 'collected/assessment.json').read_text())['planned_relations'], 3)


if __name__ == '__main__':
    unittest.main()
