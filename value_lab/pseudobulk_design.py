"""Bounded additive covariate design for the paired-donor task family."""
import math
import re

from .core import ValidationError
from .science import number


def validate_covariates(design):
    specs = design['covariates']
    if not isinstance(specs, dict) or not 1 <= len(specs) <= 12:
        raise ValidationError('Declare 1..12 covariates for design v2')
    for name, spec in specs.items():
        if not re.fullmatch('[A-Za-z][A-Za-z0-9_]*', name) or name in ('donor', 'condition', 'id', 'cells', 'counts'):
            raise ValidationError('Covariate requires a distinct simple column name')
        if not isinstance(spec, dict) or spec.get('kind') not in ('continuous', 'categorical'):
            raise ValidationError('Covariate kind must be continuous or categorical')
        if spec['kind'] == 'continuous':
            if set(spec) != {'kind'}:
                raise ValidationError('Continuous covariate accepts only kind')
        else:
            levels = spec.get('levels')
            if set(spec) != {'kind', 'levels'} or not isinstance(levels, list) or not 2 <= len(levels) <= 12 or any(
                    not isinstance(v, str) or not v.strip() for v in levels) or len(set(levels)) != len(levels):
                raise ValidationError('Freeze distinct categorical levels, with reference first')


def formula(design):
    return '~donor + ' + ' + '.join([*design.get('covariates', {}), 'condition'])


def attach_covariates(design, data, samples):
    values, specs = data['sample_covariates'], design['covariates']
    if not isinstance(values, dict) or set(values) != {row['id'] for row in samples}:
        raise ValidationError('Covariates must join exactly once to every pseudobulk sample')
    for row in samples:
        fields = values[row['id']]
        if not isinstance(fields, dict) or set(fields) != set(specs):
            raise ValidationError('Missing or extra sample covariate')
        for name, spec in specs.items():
            value = fields[name]
            if spec['kind'] == 'continuous':
                if abs(number(value)) > 1e12:
                    raise ValidationError('Covariate outside bounded numeric range')
            elif value not in spec['levels']:
                raise ValidationError('Unknown categorical level')
        row['covariates'] = dict(fields)


def design_matrix(design, samples):
    """Rebuild an additive treatment-coded matrix without trusting fit output.

    Conservative numerical rank gate on column-normalized values. It does not
    establish causal identifiability, covariate suitability or donor identity.
    """
    if len(samples) > 256:
        raise ValidationError('Covariate design is bounded to 256 samples')
    donors = sorted({s['donor'] for s in samples})
    columns = ['Intercept'] + ['donor[T.' + d + ']' for d in donors[1:]]
    vectors = [[1.] * len(samples)] + [[float(s['donor'] == d) for s in samples] for d in donors[1:]]
    for name, spec in design['covariates'].items():
        if spec['kind'] == 'continuous':
            columns.append(name)
            vectors.append([float(s['covariates'][name]) for s in samples])
        else:
            observed = {s['covariates'][name] for s in samples}
            if observed != set(spec['levels']):
                raise ValidationError('Declared categorical level has no observations')
            for level in spec['levels'][1:]:
                columns.append(name + '[T.' + level + ']')
                vectors.append([float(s['covariates'][name] == level) for s in samples])
    columns.append('condition[T.' + design['treatment'] + ']')
    vectors.append([float(s['condition'] == design['treatment']) for s in samples])
    if len(columns) >= len(samples):
        raise ValidationError('Design has no residual degrees of freedom')
    # Modified Gram-Schmidt with reorthogonalization, after scale normalization.
    basis = []
    for vector in vectors:
        norm = math.sqrt(sum(v * v for v in vector))
        if not norm:
            raise ValidationError('Zero design column')
        v = [x / norm for x in vector]
        for _ in range(2):
            for q in basis:
                dot = sum(a * b for a, b in zip(v, q))
                v = [a - dot * b for a, b in zip(v, q)]
        residual = math.sqrt(sum(x * x for x in v))
        if residual <= 1e-10:
            raise ValidationError('Rank-deficient or nearly confounded donor/covariate/condition design')
        basis.append([x / residual for x in v])
    return {'columns': columns, 'rows': {s['id']: [v[i] for v in vectors] for i, s in enumerate(samples)},
            'rank': len(columns), 'residual_df': len(samples) - len(columns),
            'rank_tolerance': 1e-10, 'covariate_suitability': 'REQUIRES_DOMAIN_REVIEW'}
