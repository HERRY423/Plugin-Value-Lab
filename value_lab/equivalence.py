"""Paired, feature-wise TOST with a separate individual agreement guard.

Rows are declared independent experimental units, never flattened matrix cells.
Bounds and the complete endpoint family belong to the pinned scorer design.
"""
import math
from statistics import mean, stdev

from .core import ValidationError, load_json, suite_digest
from .science import keys, number, reference, reference_json

FORMAT = 'pvl-equivalence-design-1'


def validate_spec(spec):
    keys(spec, 'design truth')
    reference(spec['design'])
    reference(spec['truth'])


def _names(items, maximum):
    if (not isinstance(items, list) or not 1 <= len(items) <= maximum
            or any(not isinstance(x, str) or not x.strip() or len(x) > 200 for x in items)
            or len(set(items)) != len(items)):
        raise ValidationError('Expected bounded, unique unit/feature names')


def validate_design(design):
    keys(design, 'format unit_kind independence_rationale unit_ids features alpha minimum_units')
    if design['format'] != FORMAT or design['unit_kind'] not in ('independent_dataset', 'biological_replicate'):
        raise ValidationError('TOST needs independent datasets or biological replicates, not genes/cells')
    if not isinstance(design['independence_rationale'], str) or not design['independence_rationale'].strip():
        raise ValidationError('Document the independent sampling unit and paired design')
    _names(design['unit_ids'], 10000)
    if type(design['minimum_units']) is not int or not 3 <= design['minimum_units'] <= len(design['unit_ids']):
        raise ValidationError('Predeclare at least three independent paired units')
    if not 1e-6 <= number(design['alpha']) <= .05:
        raise ValidationError('alpha must be in [1e-6, .05] for bounded numerical inference')
    features = design['features']
    if not isinstance(features, dict):
        raise ValidationError('Named endpoint family is required')
    _names(list(features), 1000)
    if len(features) * len(design['unit_ids']) > 200000:
        raise ValidationError('Equivalence matrix exceeds work budget')
    for bounds in features.values():
        keys(bounds, 'lower upper max_abs_difference rationale')
        low, high, guard = (number(bounds[k]) for k in ('lower', 'upper', 'max_abs_difference'))
        if not -1e100 <= low < 0 < high <= 1e100 or not 0 < guard <= 1e100:
            raise ValidationError('Finite prospective equivalence bounds must straddle zero')
        if not isinstance(bounds['rationale'], str) or not bounds['rationale'].strip():
            raise ValidationError('Every endpoint needs a scientific margin rationale')
    return design


def _matrix(obj, design):
    keys(obj, 'unit_ids features values')
    _names(obj['unit_ids'], 10000)
    _names(obj['features'], 1000)
    if set(obj['unit_ids']) != set(design['unit_ids']) or set(obj['features']) != set(design['features']):
        raise ValidationError('Matrix must cover every frozen unit and endpoint exactly once')
    values = obj['values']
    if not isinstance(values, list) or len(values) != len(obj['unit_ids']):
        raise ValidationError('Matrix row count mismatch')
    result = {}
    for identity, row in zip(obj['unit_ids'], values):
        if not isinstance(row, list) or len(row) != len(obj['features']):
            raise ValidationError('Matrix column count mismatch')
        if any(abs(number(x)) > 1e100 for x in row):
            raise ValidationError('Matrix magnitude exceeds numerical work bound')
        result[identity] = dict(zip(obj['features'], row))
    return result


def assess(design, actual, truth):
    validate_design(design)
    observed, expected = _matrix(actual, design), _matrix(truth, design)
    try:
        from scipy.stats import t
    except ImportError as exc:
        raise OSError('Paired TOST requires the optional science environment (SciPy)') from exc
    n, family = len(design['unit_ids']), len(design['features'])
    # Bonferroni across feature-level equivalence claims; never twice-correct
    # the two one-sided tests, whose maximum is the TOST p value.
    alpha = design['alpha'] / family
    critical = float(t.isf(alpha, n - 1))
    rows = []
    for feature, bounds in design['features'].items():
        differences = [observed[u][feature] - expected[u][feature] for u in design['unit_ids']]
        delta, se = mean(differences), stdev(differences) / math.sqrt(n)
        low, high = bounds['lower'], bounds['upper']
        maximum = max(abs(x) for x in differences)
        guard = maximum <= bounds['max_abs_difference']
        if se == 0:
            # A degenerate empirical sample is not a calibrated t inference.
            # Outside the bounds it demonstrably fails; inside it is unknown.
            p_low = p_high = p_tost = interval = None
            equivalent = False if not low < delta < high else None
            status = 'ZERO_VARIANCE_INFERENCE_UNAVAILABLE'
        else:
            p_low = float(t.sf((delta - low) / se, n - 1))
            p_high = float(t.cdf((delta - high) / se, n - 1))
            p_tost = max(p_low, p_high)
            interval = [delta - critical * se, delta + critical * se]
            equivalent = p_tost < alpha
            status = 'EQUIVALENCE_ESTABLISHED' if equivalent else 'EQUIVALENCE_NOT_ESTABLISHED'
        passed = False if not guard or equivalent is False else equivalent
        rows.append({'feature': feature, 'n_units': n, 'mean_difference': delta, 'standard_error': se,
                     'bounds': [low, high], 'confidence_interval': interval, 'confidence_level': 1 - 2 * alpha,
                     'p_lower': p_low, 'p_upper': p_high, 'p_tost': p_tost, 'alpha_per_feature': alpha,
                     'max_abs_difference': maximum, 'individual_agreement_passed': guard,
                     'mean_equivalence': equivalent, 'passed': passed, 'status': status})
    from .scoring import _all_states
    passed = _all_states(r['passed'] for r in rows)
    return passed, {'format': 'pvl-equivalence-receipt-1', 'design_sha256': suite_digest(design),
        'status': 'PASS' if passed is True else 'FAIL' if passed is False else 'UNKNOWN',
        'method': 'PAIRED_TOST_BONFERRONI_WITH_INDIVIDUAL_GUARD', 'features': rows,
        'scope': 'DECLARED_ENDPOINT_MEAN_EQUIVALENCE_AND_OBSERVED_INDIVIDUAL_AGREEMENT',
        'assumptions': 'Independent paired units; approximately normal paired differences; margins fixed before observation',
        'independence': 'DECLARED_NOT_AUTHENTICATED', 'reference_validity': 'NOT_ESTABLISHED',
        'claim_limit': 'Failure to establish equivalence is not proof of a difference; no distributional or biological validity claim'}


def check(path, spec, root):
    validate_spec(spec)
    design, truth = reference_json(root, spec['design']), reference_json(root, spec['truth'])
    try:
        validate_design(design)
        _matrix(truth, design)
    except (ValidationError, TypeError, KeyError) as exc:
        raise OSError('Invalid frozen equivalence reference/design') from exc
    return assess(design, load_json(path), truth)
