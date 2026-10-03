"""Prospective paired-design planning and family-level conditional intervals.

Families, tasks within families and repetitions are distinct sampling levels.
No observed-effect power, automatic collection, optional stopping or adoption gate.
"""
from collections import Counter, defaultdict
from statistics import NormalDist, mean, stdev
import math

from .core import ValidationError, _number, _text, suite_digest

SOURCES = [
    'https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestPower.html',
    'https://www.itl.nist.gov/div898/handbook/prc/section3/prc312.htm',
    'https://doi.org/10.1080/01621459.1963.10500830',
    'https://arxiv.org/abs/1808.02997',
]


def validate(plan):
    required = {'version', 'minimum_detectable_delta', 'alpha', 'power', 'between_family_sd',
                'between_task_sd', 'within_task_sd', 'tasks_per_family', 'repetitions_per_case',
                'max_families', 'variance_source', 'sampling_basis', 'method', 'comparisons'}
    if not isinstance(plan, dict) or not required <= set(plan) or set(plan) - required - {'sd_multipliers', 'cost_weights'}:
        raise ValidationError('power_plan v2 requires effect, alpha/power, three SD components, task/repeat grids, '
                              'max_families, variance_source, sampling_basis, method and comparisons')
    if type(plan['version']) is not int or plan['version'] != 2:
        raise ValidationError('Sample-size plan version must be 2')
    for key, low, high in [('minimum_detectable_delta', 1e-6, 1), ('alpha', 1e-6, .2), ('power', .5, .999),
                         ('between_family_sd', 0, 1), ('between_task_sd', 0, 1), ('within_task_sd', 0, 1)]:
        _number(plan[key], key, low, high)
    variance = sum(plan[k] ** 2 for k in ('between_family_sd', 'between_task_sd', 'within_task_sd'))
    if variance <= 0 or variance > 1 - plan['minimum_detectable_delta'] ** 2 + 1e-12:
        raise ValidationError('Positive variance compatible with a paired score difference in [-1,1] required')
    for key, high in [('tasks_per_family', 1000), ('repetitions_per_case', 50)]:
        values = plan[key]
        if (not isinstance(values, list) or not 1 <= len(values) <= 8
                or any(type(v) is not int or not 1 <= v <= high for v in values) or len(set(values)) != len(values)):
            raise ValidationError(key + ' must contain 1..8 distinct positive bounded integers')
    for key, low, high in [('max_families', 2, 100000), ('comparisons', 1, 1000)]:
        if type(plan[key]) is not int or not low <= plan[key] <= high:
            raise ValidationError('Invalid ' + key)
    _text(plan['variance_source'], 'variance_source: independent pilot/reference or explicit assumption')
    if plan['sampling_basis'] not in ('independent_representative_families', 'fixed_benchmark', 'unknown'):
        raise ValidationError('Declare independent representative family sampling, fixed benchmark or unknown')
    if plan['method'] not in ('normal_approximation', 'paired_t'):
        raise ValidationError('method must be normal_approximation or paired_t')
    multipliers = plan.get('sd_multipliers', [1, 1.5])
    if not isinstance(multipliers, list) or not 1 <= len(multipliers) <= 5:
        raise ValidationError('Provide 1..5 SD sensitivity multipliers including 1')
    for value in multipliers:
        _number(value, 'SD multiplier', .1, 5)
    if 1 not in multipliers or len(set(multipliers)) != len(multipliers):
        raise ValidationError('Distinct SD multipliers must include the base scenario 1')
    weights = plan.get('cost_weights')
    if weights is not None:
        if not isinstance(weights, dict) or set(weights) != {'unit', 'family_setup', 'task_setup', 'generation'}:
            raise ValidationError('cost_weights requires unit/family_setup/task_setup/generation')
        _text(weights['unit'], 'effort unit')
        for key in ('family_setup', 'task_setup', 'generation'):
            _number(weights[key], key, 0, 1e9)
        if weights['generation'] <= 0:
            raise ValidationError('Generation effort must be positive')
    return plan


def _scipy_stats():
    try:
        from scipy import stats
    except ImportError:
        raise ValidationError('paired_t requires the optional plugin-value-lab[planning] dependency; '
                              'do not silently substitute a normal approximation') from None
    return stats


def _power(n, effect, sd, alpha, method):
    ncp = effect * math.sqrt(n) / sd
    if method == 'normal_approximation':
        z = NormalDist().inv_cdf(1 - alpha / 2)
        result = NormalDist().cdf(ncp - z) + NormalDist().cdf(-ncp - z)
    else:
        stats = _scipy_stats()
        critical = stats.t.isf(alpha / 2, n - 1)
        # Symmetry avoids a SciPy/Boost negative-tail CDF NaN at large positive
        # noncentrality: P(T_d < -c) = P(T_-d > c). No normal fallback.
        result = float(stats.nct.sf(critical, n - 1, ncp) + stats.nct.sf(critical, n - 1, -ncp))
    if not math.isfinite(result):
        raise ValidationError('Power solver did not converge to a finite value')
    return min(1., max(0., result))


def _required(effect, sd, alpha, target, maximum, method):
    if _power(maximum, effect, sd, alpha, method) < target:
        return None
    low, high = 2, maximum
    while low < high:
        mid = (low + high) // 2
        if _power(mid, effect, sd, alpha, method) >= target:
            high = mid
        else:
            low = mid + 1
    return low


def plan_sample_size(spec):
    validate(spec)
    if spec['method'] == 'paired_t':
        _scipy_stats()  # fail clearly before returning a partial design grid
    effect, alpha = spec['minimum_detectable_delta'], spec['alpha'] / spec['comparisons']
    rows = []
    for multiplier in sorted(spec.get('sd_multipliers', [1, 1.5])):
        # These are SDs of paired differences, not per-arm SDs.
        a, b, c = (spec[k] * multiplier for k in ('between_family_sd', 'between_task_sd', 'within_task_sd'))
        compatible = a*a + b*b + c*c <= 1 - effect*effect + 1e-12
        for tasks in sorted(spec['tasks_per_family']):
            for repeats in sorted(spec['repetitions_per_case']):
                sd = math.sqrt(a*a + b*b/tasks + c*c/(tasks*repeats))
                required = _required(effect, sd, alpha, spec['power'], spec['max_families'], spec['method']) if compatible else None
                runs = 2 * required * tasks * repeats if required else None
                row = {'sd_multiplier': multiplier, 'tasks_per_family': tasks, 'repetitions_per_case_per_arm': repeats,
                       'family_mean_sd': sd, 'required_families': required,
                       'required_tasks': required * tasks if required else None, 'generation_runs': runs,
                       'status': 'INCOMPATIBLE_SCORE_VARIANCE' if not compatible else 'TARGET_ATTAINABLE' if required else 'EXCEEDS_SEARCH_LIMIT',
                       'conditional_power': _power(required, effect, sd, alpha, spec['method']) if required else None,
                       'power_one_fewer_family': _power(required-1, effect, sd, alpha, spec['method']) if required and required > 2 else None,
                       'expected_ci_half_width': (NormalDist().inv_cdf(1-alpha/2) if spec['method'] == 'normal_approximation'
                           else float(_scipy_stats().t.isf(alpha/2, required-1))) * sd / math.sqrt(required) if required else None}
                weights = spec.get('cost_weights')
                row['assumed_effort'] = (required * weights['family_setup'] + required * tasks * weights['task_setup']
                                         + runs * weights['generation']) if required and weights else None
                rows.append(row)
    feasible = [r for r in rows if r['sd_multiplier'] == 1 and r['required_families']]
    chosen = min(feasible, key=lambda r: (r['assumed_effort'] if spec.get('cost_weights') else r['generation_runs'],
                                         r['required_tasks'], r['required_families'])) if feasible else None
    return {'format': 'pvl-sample-size-2', 'status': 'CONDITIONAL_DESIGN' if feasible else 'NO_FEASIBLE_DESIGN_IN_GRID',
            'spec': spec, 'spec_sha256': suite_digest(spec), 'effective_alpha': alpha,
            'estimand': 'Equal-family mean WITH-minus-WITHOUT outcome quality score',
            'null_effect': 0, 'alternative_effect': effect,
            'expected_ci_method': 'Student t model interval' if spec['method'] == 'paired_t' else 'Normal model interval',
            'power_applies_to_hoeffding_interval': False,
            'variance_formula': 'family_sd^2 + task_sd^2/K + repeat_sd^2/(K*R)',
            'designs': rows, 'recommended_design': chosen,
            'recommendation_objective': 'MIN_ASSUMED_EFFORT' if spec.get('cost_weights') else 'MIN_GENERATION_RUNS_IN_GRID',
            'population_inference_supported_by_declaration': spec['sampling_basis'] == 'independent_representative_families',
            'executed': False, 'sources': SOURCES,
            'limitations': [
                '样本量是给定效应量和方差假设下的条件计算；不是事后功效、收益证明或执行授权。',
                '功效针对双侧 H0: 差值=0；检测到非零差值不等于置信下界超过最小实用收益。',
                '任务族相互独立且有代表性；任务在族内抽样，重复噪声条件独立。族名与不同会话不能验证这些假设。',
                '三个标准差均针对 WITH−WITHOUT 配对差值。不能直接填入单臂标准差或用当前研究的有利差值倒推功效。',
                '重复评审票不增加生成样本数；增加任务和重复不能消除任务族间异质性。',
                'paired_t 使用非中心 t 功效，依赖近似正态的独立族均值；normal_approximation 使用正态近似。离散、偏斜及少族设计应另做模拟核验。',
                '比较数使用 Bonferroni 校正；不覆盖可选停止、事后挑指标、同一数据筛选后再确认或非劣效检验。',
                '模型运行数仅为两臂生成数，不含评审、失败重试或其他费用；推荐只在提交的网格和假设投入内成立。',
                '预计区间半宽使用设计标准差与所选正态/t 模型；不表示更保守的 Hoeffding 区间宽度或检验功效。实际区间须用新观察重算。']}


def suite_plan(suite):
    spec = suite['policy']['power_plan']
    result = plan_sample_size(spec)
    counts = Counter(c['cluster'] for c in suite['cases'])
    minimum_tasks = min(counts.values())
    repeats = suite['runs_per_case']
    sd = math.sqrt(spec['between_family_sd']**2 + spec['between_task_sd']**2/minimum_tasks
                   + spec['within_task_sd']**2/(minimum_tasks*repeats))
    required = _required(spec['minimum_detectable_delta'], sd, result['effective_alpha'], spec['power'],
                         spec['max_families'], spec['method'])
    result.update(planned_families=len(counts), planned_tasks=len(suite['cases']), repetitions_per_case=repeats,
                  required_families=required, additional_families=max(0, required-len(counts)) if required else None,
                  unit='Independent task-family mean paired difference; equal family weight',
                  minimum_tasks_per_family=minimum_tasks, unbalanced_families=len(set(counts.values())) > 1,
                  current_design_basis='Balanced-design proxy at the smallest family task count; assumed SDs, never observed effect',
                  aligned_with_primary_quality_gate=suite['policy'].get('quality_weighting', 'case') == 'family')
    result['current_design_conditional_power'] = _power(len(counts), spec['minimum_detectable_delta'], sd,
                         result['effective_alpha'], spec['method']) if len(counts) >= 2 and not result['unbalanced_families'] else None
    result['current_design_status'] = ('UNBALANCED_DESIGN_REVIEW' if result['unbalanced_families'] else
                                      'PLANNING_TARGET_MET' if required and len(counts) >= required else 'MORE_FAMILIES_NEEDED')
    return result


def confidence_intervals(suite, report):
    """Fixed-sample family CI; never treat repetitions or judge votes as df."""
    spec = suite['policy'].get('power_plan')
    unavailable = lambda why: {'status': 'UNAVAILABLE', 'reason': why}
    if not isinstance(spec, dict) or spec.get('version') != 2:
        return unavailable('Freeze a v2 sampling/alpha plan before collection; legacy bootstrap remains descriptive')
    if spec['sampling_basis'] != 'independent_representative_families':
        return unavailable('Population sampling/independence is unknown or a fixed convenience benchmark')
    if suite['policy'].get('quality_weighting', 'case') != 'family':
        return unavailable('Planned equal-family estimand differs from primary quality weighting')
    lock = report.get('provenance', {}).get('local_lock')
    if not isinstance(lock, dict) or lock.get('suite_sha256') != suite_digest(suite):
        return unavailable('Matching frozen plan required; local digest does not authenticate preregistration time')
    if report.get('blockers') or not report['summary']['comparison_eligible']:
        return unavailable('Incomplete, excluded or confounded evidence; no complete-case deletion')
    groups = defaultdict(list)
    for case in report['cases']:
        delta = case['delta']
        if type(delta) not in (int, float) or not math.isfinite(delta) or not -1 <= delta <= 1:
            return unavailable('Incomplete or out-of-range family outcome')
        groups[case['cluster']].append(delta)
    values = [mean(v) for v in groups.values()]
    n = len(values)
    if n < 2:
        return unavailable('Fewer than two independent family labels')
    estimate, alpha = mean(values), spec['alpha'] / spec['comparisons']
    half = math.sqrt(2 * math.log(2 / alpha) / n)
    bounded = {'method': 'Hoeffding fixed-sample bound for independent family scores in [-1,1]',
               'low': max(-1., estimate-half), 'high': min(1., estimate+half),
               'confidence_level_at_least': 1-alpha}
    student = unavailable('paired_t was not selected prospectively')
    sd = stdev(values)
    if spec['method'] == 'paired_t':
        if len({len(v) for v in groups.values()}) != 1:
            student = unavailable('Unequal task counts give heterogeneous family precision; use bounded interval or a separately justified model')
        elif sd <= 1e-15:
            student = unavailable('Zero observed family variance is not proof of zero population variance; use bounded interval')
        else:
            half_t = float(_scipy_stats().t.isf(alpha/2, n-1)) * sd / math.sqrt(n)
            student = {'status': 'CONDITIONAL_ON_NORMAL_FAMILY_MEANS', 'method': 'Paired Student t on family mean differences',
                       'low': estimate-half_t, 'high': estimate+half_t, 'df': n-1, 'confidence_level': 1-alpha}
    return {'status': 'SIMULATION_ONLY' if report['evidence_type'] == 'synthetic' else 'CONDITIONAL_ON_SAMPLING_ASSUMPTIONS',
            'estimate': estimate, 'independent_units': n, 'unit': 'task_family', 'observed_family_sd': sd,
            'family_deltas': dict(zip(groups, values)), 'effective_alpha': alpha,
            'familywise_confidence_level': 1-spec['alpha'], 'comparisons': spec['comparisons'],
            'bounded_interval': bounded, 'student_t_interval': student,
            'changes_adoption_verdict': False, 'independence': 'DECLARED_NOT_VERIFIED',
            'limitations': ['固定样本量、完整观测和独立代表性族抽样条件下的区间；不支持反复查看后选择停止。',
                           'Hoeffding 区间保守但不依赖正态；t 区间依赖族均值正态模型，小样本时需特别审查。',
                           '零样本方差不产生零宽度确认性区间；统计区间不认证因果、外部有效性或插件采用。']}
