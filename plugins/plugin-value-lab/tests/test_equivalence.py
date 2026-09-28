from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from value_lab.core import ValidationError, write_json, demo_records, evaluate
from value_lab.artifacts import sha, grade_artifact
from value_lab.equivalence import assess, validate_design, FORMAT
from test_component_studies import suite_fixture


def fixture():
    design = {'format': FORMAT, 'unit_kind': 'independent_dataset',
        'independence_rationale': 'Independent manufactured benchmark datasets, one paired run each',
        'unit_ids': ['d1', 'd2', 'd3'], 'minimum_units': 3, 'alpha': .05,
        'features': {'effect': {'lower': -.1, 'upper': .1, 'max_abs_difference': .2,
                              'rationale': 'Synthetic test margin, not a biological threshold'}}}
    truth = {'unit_ids': ['d1', 'd2', 'd3'], 'features': ['effect'], 'values': [[1], [2], [3]]}
    actual = deepcopy(truth)
    actual['values'] = [[.99], [2], [3.01]]
    return design, actual, truth


class EquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.design, self.actual, self.truth = fixture()

    def assess(self):
        return assess(self.design, self.actual, self.truth)

    def test_paired_tost_tabulated_df2_quantile(self):
        passed, receipt = self.assess()
        self.assertTrue(passed)
        row = receipt['features'][0]
        self.assertAlmostEqual(row['standard_error'], .01 / 3**.5)
        self.assertAlmostEqual(row['confidence_interval'][1], 2.91998558 * .01 / 3**.5, places=8)
        self.assertLess(row['p_tost'], .05)

    def test_perfect_correlation_offset_is_rejected(self):
        self.actual['values'] = [[11], [12], [13]]
        passed, receipt = self.assess()
        self.assertFalse(passed)
        self.assertFalse(receipt['features'][0]['individual_agreement_passed'])

    def test_cancellation_cannot_hide_large_individual_errors(self):
        # Mean equivalence has ample power under intentionally large mean bounds,
        # but the separately fixed individual agreement guard must reject.
        self.design['features']['effect'].update(lower=-10, upper=10)
        self.actual['values'] = [[0], [2], [4]]
        passed, receipt = self.assess()
        self.assertTrue(receipt['features'][0]['mean_equivalence'])
        self.assertFalse(passed)

    def test_insufficient_power_is_not_reported_as_proven_difference(self):
        self.actual['values'] = [[.9], [2], [3.1]]
        passed, receipt = self.assess()
        self.assertFalse(passed)
        self.assertEqual(receipt['features'][0]['status'], 'EQUIVALENCE_NOT_ESTABLISHED')
        self.assertIn('not proof of a difference', receipt['claim_limit'])

    def test_identical_constant_differences_are_not_fake_t_significance(self):
        self.actual = deepcopy(self.truth)
        passed, receipt = self.assess()
        self.assertIsNone(passed)
        self.assertIsNone(receipt['features'][0]['p_tost'])

    def test_identity_order_independent_complete_family_bonferroni(self):
        self.design['features']['other'] = deepcopy(self.design['features']['effect'])
        self.actual = {'unit_ids': ['d3', 'd1', 'd2'], 'features': ['other', 'effect'],
                       'values': [[3.01, 3.01], [.99, .99], [2, 2]]}
        self.truth['features'].append('other')
        self.truth['values'] = [[1, 1], [2, 2], [3, 3]]
        passed, receipt = self.assess()
        self.assertTrue(passed)
        self.assertTrue(all(r['alpha_per_feature'] == .025 for r in receipt['features']))
        self.assertTrue(all(r['confidence_level'] == .95 for r in receipt['features']))

    def test_no_missing_duplicates_nonfinite_bool_or_extra_endpoints(self):
        for bad in ([[True], [2], [3]], [[float('nan')], [2], [3]], [[1], [2]], [[1, 2], [2], [3]]):
            self.actual['values'] = bad
            with self.assertRaises(ValidationError):
                self.assess()
        self.design, self.actual, self.truth = fixture()
        self.actual['unit_ids'][0] = 'd2'
        with self.assertRaises(ValidationError):
            self.assess()

    def test_no_flattened_gene_or_cell_replicates_no_posthoc_bounds(self):
        for kind in ('gene', 'cell', 'matrix_entry'):
            self.design['unit_kind'] = kind
            with self.assertRaises(ValidationError):
                validate_design(self.design)
        self.design, self.actual, self.truth = fixture()
        self.design['features']['effect']['lower'] = 0
        with self.assertRaises(ValidationError):
            validate_design(self.design)

    def test_missing_scipy_is_unknown_dependency(self):
        with patch.dict('sys.modules', {'scipy.stats': None}):
            with self.assertRaises(OSError):
                self.assess()

    def test_schema_example_and_report_escape(self):
        import jsonschema
        from value_lab.core import load_json
        from value_lab.report import _metamorphic_details
        root = Path(__file__).resolve().parents[1]
        schema = load_json(root / 'schemas/science/equivalence-design.schema.json')
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(load_json(root / 'examples/equivalence/design.json'), schema)
        jsonschema.validate(self.design, schema)
        _, receipt = self.assess()
        receipt['features'][0]['feature'] = '<script>bad</script>'
        rendered = _metamorphic_details([{'verification': receipt}])
        self.assertIn('TOST', rendered)
        self.assertNotIn('<script>', rendered)

    def test_design_work_and_inference_bounds(self):
        for value in (0, 1e-310, True, .5):
            self.design['alpha'] = value
            with self.assertRaises(ValidationError):
                validate_design(self.design)

    def test_replay_and_declarative_preserve_both_private_references(self):
        from value_lab.declarative import dump_evals, load_evals
        from value_lab.replay import replay_contract
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, value in [('design', self.design), ('truth', self.truth)]:
                write_json(root / (name + '.json'), value)
            grader = {'id': 'equivalence', 'type': 'equivalence', 'artifact': 'result', 'weight': 1,
                'dimension': 'outcome', 'critical': True, 'verifier': {
                    name: {'path': name + '.json', 'sha256': sha(root / (name + '.json'))} for name in ('design', 'truth')}}
            suite = suite_fixture()
            suite['cases'][0]['graders'] = [grader]
            dump_evals(suite, root / 'evals')
            self.assertEqual(load_evals(root / 'evals')['cases'][0]['graders'][0], grader)
            materials = replay_contract(suite, [], verifier_root=root)['materials']
            self.assertEqual({m['kind'] for m in materials if m['status'] == 'BYTES_MATCH'}, {'design', 'truth'})

    def test_artifact_evaluator_pinned_reference_and_missing_or_malformed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, obj in [('design', self.design), ('truth', self.truth), ('actual', self.actual)]:
                write_json(root / (name + '.json'), obj)
            grader = {'id': 'equivalence', 'type': 'equivalence', 'artifact': 'result', 'weight': 1,
                'dimension': 'outcome', 'critical': False,
                'verifier': {name: {'path': name + '.json', 'sha256': sha(root / (name + '.json'))}
                             for name in ('design', 'truth')}}
            record = {'artifacts': {'result': {'path': 'actual.json', 'sha256': sha(root / 'actual.json')}}}
            self.assertTrue(grade_artifact(grader, record, root, root)[0])
            suite = suite_fixture()
            suite['cases'][0]['graders'] = [grader]
            records = demo_records(suite)
            for r in records:
                r.update(record)
            report = evaluate(suite, records, artifact_root=root, verifier_root=root)
            self.assertTrue(all(r['task_outcome']['passed'] is True for r in report['cases'][0]['runs']))
            grader['verifier']['design']['sha256'] = '0'*64
            self.assertIsNone(grade_artifact(grader, record, root, root)[0])
            grader['verifier']['design']['sha256'] = sha(root / 'design.json')
            write_json(root / 'actual.json', {'values': []})
            record['artifacts']['result']['sha256'] = sha(root / 'actual.json')
            self.assertFalse(grade_artifact(grader, record, root, root)[0])


if __name__ == '__main__':
    unittest.main()
