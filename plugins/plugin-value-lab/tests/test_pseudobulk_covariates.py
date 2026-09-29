from copy import deepcopy
import unittest
from pathlib import Path
import tempfile

from value_lab.core import ValidationError
from value_lab.pseudobulk import aggregate
from value_lab.pseudobulk import check
from value_lab.core import write_json
from value_lab.artifacts import sha
from value_lab.pseudobulk_design import design_matrix, formula
from test_pseudobulk import fixture


def covariate_fixture():
    design, data, _ = fixture()
    design.update(format='pvl-pseudobulk-design-2', covariates={'dose': {'kind': 'continuous'}})
    data['sample_covariates'] = {s: {'dose': v} for s, v in zip(sorted({c['sample'] for c in data['cells']}), [0, 1, 2, 4, 3, 7])}
    return design, data


class CovariateTests(unittest.TestCase):
    def test_design_full_rank_with_residual_df(self):
        design, data = covariate_fixture()
        pb = aggregate(design, data)
        matrix = design_matrix(design, pb['samples'])
        self.assertEqual((matrix['rank'], matrix['residual_df']), (5, 1))
        self.assertEqual(formula(design), '~donor + dose + condition')
        import numpy as np
        self.assertEqual(np.linalg.matrix_rank(list(matrix['rows'].values())), matrix['rank'])

    def test_condition_confounded_or_donor_constant_covariate_rejected(self):
        for mode in ('condition', 'donor', 'constant'):
            design, data = covariate_fixture()
            for i, s in enumerate(sorted(data['sample_covariates'])):
                data['sample_covariates'][s]['dose'] = int(s.endswith('stim')) if mode == 'condition' else i // 2 if mode == 'donor' else 1
            with self.assertRaisesRegex(ValidationError, 'confounded'):
                aggregate(design, data)

    def test_missing_nonfinite_boolean_and_extra_samples_rejected(self):
        for change in (lambda d: d['sample_covariates'].pop('actrl'),
                       lambda d: d['sample_covariates']['actrl'].update(dose=None),
                       lambda d: d['sample_covariates']['actrl'].update(dose=True),
                       lambda d: d['sample_covariates']['actrl'].update(dose=float('nan')),
                       lambda d: d['sample_covariates'].update(extra={'dose': 1})):
            design, data = covariate_fixture()
            change(data)
            with self.assertRaises(ValidationError):
                aggregate(design, data)

    def test_categorical_reference_level_and_missing_level(self):
        design, data = covariate_fixture()
        design['covariates'] = {'dose': {'kind': 'categorical', 'levels': ['low', 'high']}}
        for i, s in enumerate(sorted(data['sample_covariates'])):
            data['sample_covariates'][s]['dose'] = 'high' if i in (1, 2, 5) else 'low'
        pb = aggregate(design, data)
        self.assertIn('dose[T.high]', design_matrix(design, pb['samples'])['columns'])
        design['covariates']['dose']['levels'].append('absent')
        with self.assertRaisesRegex(ValidationError, 'no observations'):
            aggregate(design, data)

    def test_no_residual_df_and_formula_injection_rejected(self):
        design, data = covariate_fixture()
        design['covariates']['extra'] = {'kind': 'continuous'}
        for value in data['sample_covariates'].values():
            value['extra'] = 1
        with self.assertRaisesRegex(ValidationError, 'residual'):
            aggregate(design, data)
        design['covariates'] = {'x + condition': {'kind': 'continuous'}}
        with self.assertRaisesRegex(ValidationError, 'column name'):
            aggregate(design, data)

    def test_reference_and_submitted_covariate_matrix_reconstructed(self):
        design, data = covariate_fixture()
        _, _, truth = fixture()
        truth['pseudobulk'] = aggregate(design, data)
        truth['method']['formula'] = formula(design)
        truth['design_matrix'] = design_matrix(design, truth['pseudobulk']['samples'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = {'absolute': 1e-7, 'relative': 1e-6}
            for name, value in [('design', design), ('data', data), ('truth', truth)]:
                write_json(root / (name + '.json'), value)
                spec[name] = {'path': name + '.json', 'sha256': sha(root / (name + '.json'))}
            write_json(root / 'result.json', truth)
            self.assertTrue(check(root / 'result.json', spec, root)[0])
            truth['design_matrix']['rows']['actrl'][-2] += 1
            write_json(root / 'result.json', truth)
            self.assertFalse(check(root / 'result.json', spec, root)[0])
            write_json(root / 'truth.json', truth)
            spec['truth']['sha256'] = sha(root / 'truth.json')
            with self.assertRaisesRegex(OSError, 'covariate matrix'):
                check(root / 'result.json', spec, root)


if __name__ == '__main__':
    unittest.main()
