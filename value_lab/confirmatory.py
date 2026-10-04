"""Prospective pilot-bound inference; never authorization or automatic adoption.

Version 3 keeps one equal-family quality endpoint, and optionally a co-primary
total-cost saving endpoint. Fixed sample only. Old descriptive verdicts survive.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from functools import lru_cache
import json
import math
from statistics import mean, stdev

from .core import ValidationError, _number, _stamp, _text, suite_digest

SD_KEYS = ('between_family_sd', 'between_task_sd', 'within_task_sd')
LIMITATIONS = [
    'Conditional statistical support is not execution authorization, causal certification, independent review or adoption.',
    'Pilot/task/session identities, timestamps and settlement references are submitted evidence, not authenticated truth.',
    'Pilot family bootstrap limits are approximate; an upper percentile is not a guaranteed population variance bound.',
    'Fixed complete sampling only: no optional stopping, reused pilot observations or post-hoc endpoint selection.',
    'Total cost includes cash plus timer-valued labor at the frozen hourly rate; labor is not settled cash.',
    'Per-run and total cost bounds are analysis criteria, not a provider-enforced spending cap.',
    'Cost Hoeffding inference assumes a genuine prospective bound on total valued cost; observing no overrun does not prove that bound.',
    'Power covers the named statistical endpoints only, not the probability of also passing all task-success, method, regression and cost-bound gates.',
]


@lru_cache(maxsize=16)
def _pilot_cached(encoded):
    from .pilot import summarize_pilot
    return summarize_pilot(json.loads(encoded))


def pilot_summary(spec):
    return deepcopy(_pilot_cached(json.dumps(spec['pilot'], sort_keys=True, allow_nan=False)))


def validate(spec):
    required = {'version', 'alpha', 'power', 'sampling_basis', 'method', 'tasks_per_family',
                'repetitions_per_case', 'max_families', 'pilot', 'variance_policy', 'rule'}
    if not isinstance(spec, dict) or set(spec) != required or type(spec['version']) is not int or spec['version'] != 3:
        raise ValidationError('Confirmatory power_plan v3 requires pilot, variance_policy, rule and fixed-design parameters')
    _number(spec['alpha'], 'alpha', 1e-6, .2)
    _number(spec['power'], 'power', .5, .999)
    if spec['sampling_basis'] != 'independent_representative_families':
        raise ValidationError('Confirmation requires declared independent representative task-family sampling')
    if spec['method'] not in ('paired_t', 'hoeffding'):
        raise ValidationError('Confirmatory method must be paired_t or hoeffding')
    for key, maximum in [('tasks_per_family', 1000), ('repetitions_per_case', 50)]:
        vals = spec[key]
        if (not isinstance(vals, list) or not 1 <= len(vals) <= 8
                or any(type(v) is not int or not 1 <= v <= maximum for v in vals) or len(set(vals)) != len(vals)):
            raise ValidationError('Invalid design grid: ' + key)
    if type(spec['max_families']) is not int or not 2 <= spec['max_families'] <= 100000:
        raise ValidationError('max_families must be 2..100000')
    rule = spec['rule']
    fields = {'objective', 'primary_endpoint', 'minimum_gain', 'noninferiority_margin',
              'anticipated_quality_delta', 'max_case_regression', 'max_total_cost_usd',
              'cost_per_run_bound_usd', 'minimum_cost_saving_usd', 'anticipated_cost_saving_usd',
              'stopping', 'confirmation_not_started', 'cost_bound_rationale'}
    if not isinstance(rule, dict) or set(rule) != fields:
        raise ValidationError('Confirmation rule requires explicit endpoint, gain/NI, cost bounds and fixed stopping')
    if rule['objective'] not in ('quality', 'efficiency') or rule['primary_endpoint'] != 'equal_family_quality':
        raise ValidationError('Only equal-family quality or quality-noninferiority plus total-cost efficiency is supported')
    if rule['stopping'] != 'fixed_sample' or rule['confirmation_not_started'] is not True:
        raise ValidationError('Declare confirmation not started and fixed_sample; retrospective/optional stopping unsupported')
    _text(rule['cost_bound_rationale'], 'Prospective full-cost bound rationale')
    for key in ('minimum_gain', 'noninferiority_margin', 'max_case_regression'):
        _number(rule[key], key, 0, 1)
    _number(rule['anticipated_quality_delta'], 'anticipated_quality_delta', -1, 1)
    _number(rule['max_total_cost_usd'], 'max_total_cost_usd', 1e-9, 1e12)
    _number(rule['cost_per_run_bound_usd'], 'cost_per_run_bound_usd', 1e-9, 1e9)
    for key in ('minimum_cost_saving_usd', 'anticipated_cost_saving_usd'):
        _number(rule[key], key, 0, rule['cost_per_run_bound_usd'])
    if rule['objective'] == 'quality':
        if rule['noninferiority_margin'] != 0 or rule['minimum_cost_saving_usd'] != 0 or rule['anticipated_cost_saving_usd'] != 0:
            raise ValidationError('Quality design has one primary quality test; NI and saving targets must be zero')
    else:
        if rule['minimum_gain'] != 0 or rule['noninferiority_margin'] <= 0:
            raise ValidationError('Efficiency requires zero minimum_gain and a positive predeclared NI margin')
        if rule['anticipated_cost_saving_usd'] <= rule['minimum_cost_saving_usd']:
            raise ValidationError('Anticipated saving must exceed the practical saving threshold')
    if rule['anticipated_quality_delta'] <= quality_threshold(rule):
        raise ValidationError('Anticipated quality difference must exceed the actual confirmation threshold')
    variance = spec['variance_policy']
    if (not isinstance(variance, dict) or set(variance) != {'basis', 'sd_floor', 'rationale', 'transfer_rationale'}
            or variance['basis'] != 'bootstrap_upper95' or not isinstance(variance['sd_floor'], dict)
            or set(variance['sd_floor']) != set(SD_KEYS)):
        raise ValidationError('variance_policy requires bootstrap_upper95, three-component sd_floor, floor rationale and transfer_rationale')
    _text(variance['rationale'], 'variance floor rationale')
    _text(variance['transfer_rationale'], 'Pilot-to-confirmation population and scoring-scale transfer rationale')
    for key in SD_KEYS:
        _number(variance['sd_floor'][key], key, 0, 1)
    pilot = pilot_summary(spec)
    for key in pilot['uncertainty']['variance_floor_required']:
        if variance['sd_floor'][key] <= 0:
            raise ValidationError('Degenerate/boundary pilot component needs an independently justified positive SD floor: ' + key)
    return spec


def quality_threshold(rule):
    return rule['minimum_gain'] if rule['objective'] == 'quality' else -rule['noninferiority_margin']


def _stats():
    from .sample_size import _scipy_stats
    return _scipy_stats()


def _t_power(n, gap, sd, alpha):
    if sd <= 0:
        raise ValidationError('Positive planning variance required; zero pilot variance is not certainty')
    stats = _stats()
    result = float(stats.nct.sf(stats.t.isf(alpha, n-1), n-1, gap*math.sqrt(n)/sd))
    if not math.isfinite(result):
        raise ValidationError('Noncentral t power did not converge')
    return min(1., max(0., result))


def _bound_power(n, gap, alpha, bound):
    half = bound * math.sqrt(2*math.log(1/alpha)/n)
    return 0. if gap <= half else 1-math.exp(-n*(gap-half)**2/(2*bound**2))


def _required(power, target, maximum):
    if power(maximum) < target:
        return None
    lo, hi = 2, maximum
    while lo < hi:
        mid = (lo+hi)//2
        if power(mid) >= target:
            hi = mid
        else:
            lo = mid+1
    return lo


def _components(spec, pilot):
    return {k: max(pilot['uncertainty']['planning_sd_upper95'][k], spec['variance_policy']['sd_floor'][k]) for k in SD_KEYS}


def _design(spec, sd, k, r):
    rule = spec['rule']
    m = 2 if rule['objective'] == 'efficiency' else 1
    alpha, beta = spec['alpha']/m, (1-spec['power'])/m
    gap = rule['anticipated_quality_delta'] - quality_threshold(rule)
    quality_power = (lambda n: _t_power(n, gap, sd, alpha)) if spec['method'] == 'paired_t' else (
        lambda n: _bound_power(n, gap, alpha, 1))
    qn = _required(quality_power, 1-beta, spec['max_families'])
    cn = None
    if m == 2:
        cost_power = lambda n: _bound_power(n, rule['anticipated_cost_saving_usd']-rule['minimum_cost_saving_usd'],
                                          alpha, rule['cost_per_run_bound_usd'])
        cn = _required(cost_power, 1-beta, spec['max_families'])
    n = max(qn, cn or 2) if qn is not None and (m == 1 or cn is not None) else None
    joint = max(0., quality_power(n) - (1-cost_power(n) if m == 2 else 0)) if n else None
    # Expected half-width is a design-model quantity, not an observed interval.
    half = (float(_stats().t.isf(alpha, n-1))*sd/math.sqrt(n) if spec['method'] == 'paired_t'
            else math.sqrt(2*math.log(1/alpha)/n)) if n else None
    budget_bound = 2*n*k*r*rule['cost_per_run_bound_usd'] if n else None
    return {'sd_multiplier': 1, 'tasks_per_family': k, 'repetitions_per_case_per_arm': r,
            'family_mean_sd': sd, 'required_families': n, 'required_quality_families': qn,
            'required_cost_families': cn, 'required_tasks': n*k if n else None,
            'generation_runs': 2*n*k*r if n else None, 'conditional_power': joint,
            'expected_ci_half_width': half, 'worst_case_total_cost_usd': budget_bound,
            'status': ('EXCEEDS_SEARCH_LIMIT' if not n else 'EXCEEDS_TOTAL_COST_BOUND'
                       if budget_bound > rule['max_total_cost_usd'] else 'TARGET_ATTAINABLE'),
            'endpoint_alpha': alpha, 'endpoint_beta': beta}


def plan_sample_size(spec):
    validate(spec)
    pilot = pilot_summary(spec)
    sd = _components(spec, pilot)
    rows = [_design(spec, math.sqrt(sd[SD_KEYS[0]]**2 + sd[SD_KEYS[1]]**2/k + sd[SD_KEYS[2]]**2/(k*r)), k, r)
            for k in sorted(spec['tasks_per_family']) for r in sorted(spec['repetitions_per_case'])]
    feasible = [row for row in rows if row['status'] == 'TARGET_ATTAINABLE']
    return {'format': 'pvl-sample-size-3', 'status': 'CONDITIONAL_CONFIRMATORY_DESIGN' if feasible else 'NO_FEASIBLE_DESIGN_IN_GRID',
            'spec': deepcopy(spec), 'spec_sha256': suite_digest(spec), 'pilot_summary': pilot,
            'planning_sd': sd, 'effective_alpha': rows[0]['endpoint_alpha'],
            'quality_null_boundary': quality_threshold(spec['rule']),
            'anticipated_quality_delta': spec['rule']['anticipated_quality_delta'],
            'named_hypotheses': ['quality'] + (['total_cost_saving'] if spec['rule']['objective'] == 'efficiency' else []),
            'error_control': 'Bonferroni alpha allocation and union-bound beta allocation across named co-primary endpoints',
            'power_scope': 'NAMED_STATISTICAL_ENDPOINTS_ONLY',
            'designs': rows, 'recommended_design': min(feasible, key=lambda row: (row['generation_runs'], row['required_tasks'])) if feasible else None,
            'recommendation_objective': 'MIN_GENERATION_RUNS_IN_GRID', 'executed': False,
            'limitations': LIMITATIONS + ['Hoeffding planning uses a conservative power lower bound; t planning is conditional on normal independent family means.',
                                         'Anticipated effects are prospective assumptions, not the favorable effect observed in the pilot.']}


def validate_suite_design(suite):
    spec = suite['policy']['power_plan']
    validate(spec)
    from .pilot import validate_disjoint
    issues = validate_disjoint(spec['pilot'], suite)
    counts = Counter(c['cluster'] for c in suite['cases'])
    if len(set(counts.values())) != 1 or next(iter(counts.values())) not in spec['tasks_per_family']:
        issues.append('Confirmation requires balanced task counts from the frozen planning grid')
    if suite['runs_per_case'] not in spec['repetitions_per_case']:
        issues.append('Confirmation repetition count is outside the frozen planning grid')
    policy, rule = suite['policy'], spec['rule']
    if policy.get('quality_weighting') != 'family' or policy.get('objective', 'quality') != rule['objective']:
        issues.append('Primary weighting/objective must match the confirmatory rule')
    if policy['max_case_regression'] != rule['max_case_regression']:
        issues.append('Allowed task regression must match the confirmatory rule')
    if rule['objective'] == 'quality' and policy['min_quality_delta'] != rule['minimum_gain']:
        issues.append('Descriptive quality threshold must match the prospective minimum gain')
    if issues:
        raise ValidationError('; '.join(issues))


def suite_plan(suite):
    spec = suite['policy']['power_plan']
    result = plan_sample_size(spec)
    counts = Counter(c['cluster'] for c in suite['cases'])
    k, r = min(counts.values()), suite['runs_per_case']
    sd = result['planning_sd']
    row = _design(spec, math.sqrt(sd[SD_KEYS[0]]**2+sd[SD_KEYS[1]]**2/k+sd[SD_KEYS[2]]**2/(k*r)), k, r)
    n = row['required_families']
    result.update(planned_families=len(counts), planned_tasks=len(suite['cases']), repetitions_per_case=r,
                  required_families=n, additional_families=max(0, n-len(counts)) if n else None,
                  aligned_with_primary_quality_gate=True,
                  current_design_status=('EXCEEDS_TOTAL_COST_BOUND' if 2*len(suite['cases'])*r*spec['rule']['cost_per_run_bound_usd'] > spec['rule']['max_total_cost_usd']
                                         else 'PLANNING_TARGET_MET' if n and len(counts) >= n else 'MORE_FAMILIES_NEEDED'))
    return result


def lower_bound(values, alpha, method, bound=1.):
    n = len(values)
    if n < 2 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > bound+1e-12 for v in values):
        return {'status': 'UNAVAILABLE', 'reason': 'Need complete bounded independent family observations'}
    estimate = mean(values)
    if method == 'paired_t':
        sd = stdev(values)
        if sd <= 1e-15:
            return {'status': 'UNAVAILABLE', 'reason': 'Zero observed family variance does not establish zero population variance'}
        half = float(_stats().t.isf(alpha, n-1))*sd/math.sqrt(n)
    else:
        half = bound*math.sqrt(2*math.log(1/alpha)/n)
    return {'status': 'CONDITIONAL', 'method': method, 'estimate': estimate,
            'lower': max(-bound, estimate-half), 'one_sided_confidence_level': 1-alpha,
            'independent_families': n, 'df': n-1 if method == 'paired_t' else None}


def assess(suite, report, records):
    spec = suite['policy']['power_plan']
    validate_suite_design(suite)
    rule, plan = spec['rule'], suite_plan(suite)
    result = {'format': 'pvl-confirmatory-result-1', 'status': 'INSUFFICIENT_EVIDENCE',
              'statistical_support': False, 'adoption_authorized': False, 'changes_legacy_verdict': False,
              'rule': deepcopy(rule), 'plan_sha256': suite_digest(spec), 'reasons': [], 'criteria': {},
              'limitations': LIMITATIONS, 'planning_target_met': plan['current_design_status'] == 'PLANNING_TARGET_MET'}
    reasons = result['reasons']
    from .pilot import validate_disjoint
    reasons.extend(validate_disjoint(spec['pilot'], suite, records))
    lock = report.get('provenance', {}).get('local_lock')
    if not isinstance(lock, dict) or lock.get('suite_sha256') != suite_digest(suite):
        reasons.append('Matching prospective frozen plan is required')
    else:
        try:
            frozen = _stamp(lock['frozen_at'])
            for row in records:
                if _stamp(row.get('started_at')) < frozen:
                    raise ValidationError('Confirmation observation predates local freeze')
                case = next(c for c in suite['cases'] if c['id'] == row['case_id'])
                if row.get('input_sha256') != case['input_sha256']:
                    raise ValidationError('Observed confirmation input identity differs from frozen input')
        except (ValueError, TypeError, KeyError, StopIteration) as exc:
            reasons.append('Prospective timing/input evidence incomplete: ' + str(exc))
    if report.get('blockers') or not report['summary']['comparison_eligible']:
        reasons.append('Incomplete or confounded confirmation matrix')
    if not result['planning_target_met']:
        reasons.append('Frozen confirmation design does not meet its prospective planning target')
    costs = report['cost_analysis']
    if not costs['complete_category_coverage'] or not costs['cash_evidence']['settlement_references_complete']:
        reasons.append('Complete cost categories and unique settled cash references required; estimates cannot confirm')
    totals = [costs['arms'][a]['total_usd'] for a in ('with', 'without')]
    total_ok = all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in totals)
    if not total_ok:
        reasons.append('Full cost is unknown')
    result['criteria']['total_cost_within_bound'] = total_ok and sum(totals) <= rule['max_total_cost_usd']
    groups, saving = defaultdict(list), defaultdict(list)
    per_run_ok = True
    for case in report['cases']:
        groups[case['cluster']].append(case['delta'])
        runs = case['runs']
        for rep in range(1, suite['runs_per_case']+1):
            pair = {r['arm']: r.get('cost_usd') for r in runs if r['repetition'] == rep}
            if (set(pair) != {'with', 'without'} or any(type(v) not in (int, float) or not math.isfinite(v)
                    or not 0 <= v <= rule['cost_per_run_bound_usd'] for v in pair.values())):
                per_run_ok = False
            else:
                saving[case['cluster']].append(pair['without']-pair['with'])
    result['criteria']['per_run_cost_within_bound'] = per_run_ok
    if rule['objective'] == 'efficiency':
        # Allocating a common setup bill over families does not make that bill independent.
        if any(e['treatment'] == 'additional' and ('case_id' not in e or 'repetition' not in e or e['arm'] == 'shared')
               for e in costs['entries']):
            reasons.append('Cost inference requires per-run allocated observations, not shared/global overhead')
    if reasons:
        if report['evidence_type'] == 'synthetic' or spec['pilot']['evidence_type'] == 'synthetic':
            result['status'] = 'SIMULATION_ONLY'
        return result
    alpha = plan['effective_alpha']
    quality = lower_bound([mean(v) for v in groups.values()], alpha, spec['method'])
    result['quality_interval'] = quality
    result['criteria']['quality_lower_exceeds_threshold'] = ('lower' in quality and quality['lower'] > quality_threshold(rule))
    result['quality_threshold'] = quality_threshold(rule)
    result['criteria']['case_regression_allowed'] = all(c['delta'] >= -rule['max_case_regression']-1e-12 for c in report['cases'])
    result['criteria']['legacy_task_success_gate'] = report['summary']['task_success_gate_met']
    result['criteria']['no_critical_failure'] = not report['summary'].get('critical_failures')
    result['criteria']['methodology_limits_met'] = not report.get('methodology', {}).get('violations')
    result['criteria']['legacy_cost_gate'] = report['summary']['cost_gate_met']
    if rule['objective'] == 'efficiency':
        cost = lower_bound([mean(saving[k]) for k in groups] if per_run_ok else [], alpha, 'hoeffding', rule['cost_per_run_bound_usd'])
        result['cost_saving_interval'] = cost
        result['criteria']['cost_lower_exceeds_threshold'] = ('lower' in cost and cost['lower'] > rule['minimum_cost_saving_usd'])
    supported = all(result['criteria'].values())
    result['status'] = 'CONDITIONALLY_SUPPORTED' if supported else 'NOT_CONFIRMED'
    result['statistical_support'] = supported
    for interval in (quality, result.get('cost_saving_interval', {})):
        if interval.get('status') == 'UNAVAILABLE':
            result.update(status='INSUFFICIENT_EVIDENCE', statistical_support=False)
            reasons.append(interval['reason'])
    if report['evidence_type'] == 'synthetic' or spec['pilot']['evidence_type'] == 'synthetic':
        result.update(status='SIMULATION_ONLY', statistical_support=False, simulated_criteria_met=supported)
    if not supported:
        reasons.extend('Criterion not met: ' + key for key, value in result['criteria'].items() if not value)
    return result
