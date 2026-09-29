"""Bind report conclusions to explicit evidence units and reject wider citations."""
from copy import deepcopy
import re
from .core import ValidationError, suite_digest

UNSUPPORTED = ['broader_adoption', 'causal_benefit', 'independent_scientific_validity',
               'human_usability', 'other_models', 'other_hosts', 'larger_or_different_data', 'unseen_tasks']
BRANCHES = ('verdict', 'measured_verdict', 'summary', 'quality_estimand', 'value_metrics',
            'decision_review', 'value_interpretation', 'claim_limits', 'scientific_errors', 'corpus_errors',
            'cost_analysis', 'methodology', 'uncertainty', 'blockers', 'warnings', 'scope_integrity_blockers')


def validate_context(suite):
    context = suite.get('claim_context')
    if context is not None and (not isinstance(context, dict) or set(context) != {'model_version', 'host_version', 'excluded_uses'}
            or any(not isinstance(context[k], str) or not context[k].strip() for k in ('model_version', 'host_version'))
            or not isinstance(context['excluded_uses'], list)
            or any(not isinstance(x, str) or not x for x in context['excluded_uses'])):
        raise ValidationError('claim_context requires model_version, host_version and excluded_uses before freezing')
    for case in suite['cases']:
        if not isinstance(case, dict):
            raise ValidationError('Case must be an object')
        if 'data_scale' not in case:
            continue
        scale = case['data_scale']
        if (not isinstance(scale, dict) or set(scale) != {'unit', 'count'} or not isinstance(scale['unit'], str)
                or not scale['unit'] or type(scale['count']) is not int or scale['count'] < 0):
            raise ValidationError('data_scale requires a named unit and nonnegative integer count')


def _leaves(value, pointer):
    if isinstance(value, dict):
        for key, v in value.items():
            yield from _leaves(v, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for index, v in enumerate(value):
            yield from _leaves(v, pointer + '/' + str(index))
    else:
        yield pointer, value


def build_claims(report, context):
    """All conclusion scalars carry scope; raw observations/provenance are separate."""
    claims = []
    cases = context['cases']
    def add(pointer, value, kind, selected, family=None):
        card = {'evidence_unit': {'kind': kind, 'case_ids': selected, 'family': family},
                'conditions': context['conditions'],
                'data_scale': {cid: cases[cid]['data_scale'] for cid in selected},
                'explicitly_unsupported': context['excluded_uses'],
                'evidence_type': report['evidence_type'], 'observation_authenticity': 'NOT_AUTHENTICATED'}
        claims.append({'id': pointer, 'value': deepcopy(value), 'value_sha256': suite_digest(value), 'scope': deepcopy(card)})
    for branch in BRANCHES:
        if branch in report:
            for pointer, value in _leaves(report[branch], '/' + branch):
                # Family results retain family as the unit, never promote a
                # study verdict into evidence that each constituent case won.
                family = None
                for name in {c['family'] for c in cases.values()}:
                    escaped = name.replace('~', '~0').replace('/', '~1')
                    if pointer.startswith('/value_metrics/families/deltas/' + escaped) and pointer == '/value_metrics/families/deltas/' + escaped:
                        family = name
                ids = sorted(cid for cid, c in cases.items() if family is None or c['family'] == family)
                add(pointer, value, 'family' if family is not None else 'study', ids, family)
    for index, case in enumerate(report['cases']):
        for field in ('with_score', 'without_score', 'delta', 'runs'):
            if field in case:
                for pointer, value in _leaves(case[field], f'/cases/{index}/{field}'):
                    # Per-run observations and grade decisions are bound to the
                    # case, not treated as independent population conclusions.
                    add(pointer, value, 'case', [case['id']])
    return claims


def attach(suite, report):
    validate_context(suite)
    declared = suite.get('claim_context') or {}
    conditions = {k: suite['conditions'][k] for k in ('model', 'host')}
    conditions.update({k: declared.get(k) for k in ('model_version', 'host_version')})
    context = {'conditions': conditions,
        'cases': {c['id']: {'family': c['cluster'], 'data_scale': deepcopy(c.get('data_scale'))} for c in suite['cases']},
        'excluded_uses': sorted(set(UNSUPPORTED + declared.get('excluded_uses', [])))}
    report['scoped_conclusions'] = {'format': 'pvl-scoped-conclusions-1', 'context': context,
        'source_report_sha256': suite_digest(report), 'claims': build_claims(report, context),
        'missing_dimensions': [k for k, v in conditions.items() if v is None] +
            ['data_scale:' + c for c, v in context['cases'].items() if v['data_scale'] is None],
        'scope_authenticity': 'Frozen declarations, not independently measured identities or scales'}
    return report


def verify_report(report, expected_sha256=None):
    if not isinstance(report, dict):
        raise ValidationError('Report must be an object')
    if expected_sha256 is not None and suite_digest(report) != expected_sha256:
        raise ValidationError('Report commitment changed')
    bound = report.get('scoped_conclusions')
    if not isinstance(bound, dict) or bound.get('format') != 'pvl-scoped-conclusions-1':
        raise ValidationError('Report has no machine-enforced scope binding')
    base = {k: v for k, v in report.items() if k != 'scoped_conclusions'}
    try:
        unchanged = (suite_digest(base) == bound['source_report_sha256'] and
                     build_claims(base, bound['context']) == bound['claims'])
    except (KeyError, TypeError, AttributeError):
        raise ValidationError('Malformed conclusion scope binding') from None
    if not unchanged:
        raise ValidationError('Conclusion, scope card, or claim coverage changed')
    return bound


def cite(report, request, expected_sha256):
    if not isinstance(expected_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256):
        raise ValidationError('An independently retained report SHA256 commitment is required')
    bound = verify_report(report, expected_sha256)
    fields = {'claim_id', 'evidence_unit', 'conditions', 'data_scale', 'intended_use'}
    if not isinstance(request, dict) or set(request) != fields:
        raise ValidationError('Citation must declare exact unit, conditions, data scale and intended use')
    found = [c for c in bound['claims'] if c['id'] == request['claim_id']]
    if len(found) != 1:
        raise ValidationError('Unknown claim identifier')
    claim = found[0]
    for field in ('evidence_unit', 'conditions', 'data_scale'):
        if suite_digest(request[field]) != suite_digest(claim['scope'][field]):
            raise ValidationError('OUT_OF_SCOPE: ' + field)
    if request['intended_use'] != 'describe_observed_result':
        raise ValidationError('OUT_OF_SCOPE: only the bound descriptive conclusion is supported')
    return {'status': 'IN_SCOPE', 'claim': deepcopy(claim), 'source_report_sha256': expected_sha256,
            'scope_check_only': True, 'broader_use': 'NOT_ESTABLISHED'}
