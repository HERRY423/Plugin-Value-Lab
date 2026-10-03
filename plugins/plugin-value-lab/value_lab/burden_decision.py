"""Prospective, constrained burden decisions over recomputed complete task plans.

Raw timers and settlement references are submitted evidence, not authenticated
facts. No scalar score, hidden conversion of labor to cash, or execution grant.
"""
from copy import deepcopy
from datetime import datetime
from itertools import combinations
import math
from statistics import mean

from .core import ValidationError, suite_digest, validate_suite
from .task_selection import _keys, _sha, _text, _id, select_task_plan

FORMAT = 'pvl-burden-decision-1'
METRICS = ('human_seconds', 'cash_usd', 'elapsed_seconds', 'new_plugins', 'total_plugins')
PHASES = ('setup', 'execution', 'review', 'rework', 'pvl_prepare', 'pvl_verify',
          'pvl_report', 'pvl_false_positive', 'pvl_recovery')
EPSILON = 1e-12  # Arithmetic only. Materiality comes from the frozen policy.


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1e12:
        raise ValidationError('Burden values must be finite nonnegative bounded numbers')


def _policy(policy, plans):
    _keys(policy, ('objective', 'metrics', 'local_only', 'incumbent_plan_sha256', 'scope'))
    if policy['objective'] not in (*METRICS, 'pareto') or policy['scope'] != 'one_complete_frozen_task_no_amortization':
        raise ValidationError('Declare a supported burden objective and complete-task scope')
    if type(policy['local_only']) is not bool:
        raise ValidationError('Local-only data handling must be explicitly true or false')
    if policy['incumbent_plan_sha256'] is not None and policy['incumbent_plan_sha256'] not in plans:
        raise ValidationError('Incumbent must be a complete plan in the frozen catalog')
    _keys(policy['metrics'], METRICS)
    for metric in METRICS:
        row = policy['metrics'][metric]
        _keys(row, ('material_delta', 'max_value'))
        _number(row['material_delta'])
        if row['max_value'] is not None:
            _number(row['max_value'])


def prepare(selection, policy, study_suites):
    if selection.get('studies'):
        raise ValidationError('Freeze burden goals before observations; do not retrofit existing studies')
    catalog = select_task_plan(selection)
    ids = [p['plan_sha256'] for p in catalog['plans']]
    manifests = {p['plan_sha256']: p['manifest'] for p in catalog['plans']}
    _policy(policy, ids)
    if not isinstance(study_suites, list) or not 1 <= len(study_suites) <= 32:
        raise ValidationError('Freeze 1..32 complete study protocols, never just winning observations')
    seen = set()
    for suite in study_suites:
        validate_suite(suite)
        if 'burden_decision' in suite or suite['id'] in seen:
            raise ValidationError('Use unique fresh study protocols without a prior burden binding')
        seen.add(suite['id'])
        binding = suite.get('task_selection', {})
        _keys(binding, ('catalog_sha256', 'arms', 'treatment_component'))
        if binding.get('catalog_sha256') != catalog['catalog_sha256']:
            raise ValidationError('Study must bind the frozen task catalog')
        arms = binding.get('arms', {})
        if set(arms) != {'with', 'without'} or any(v not in ids for v in arms.values()):
            raise ValidationError('Study arms must bind complete candidate plans')
        treatment = next((c for c in manifests[arms['with']]['components'] if c['id'] == binding['treatment_component']), None)
        if (treatment is None or treatment['kind'] != 'plugin'
                or any(c['id'] == binding['treatment_component'] for c in manifests[arms['without']]['components'])
                or any(suite['plugin'].get(k) != treatment[k] for k in ('name', 'version', 'sha256'))):
            raise ValidationError('Prospective study treatment and baseline load semantics differ from the full plans')
        if any(suite_digest(suite[k]) != suite_digest(selection['task'][k]) for k in ('cases', 'conditions')):
            raise ValidationError('Studies must share the exact frozen task and runtime conditions')
        if suite['policy']['quality_floor'] != selection['policy']['quality_floor']:
            raise ValidationError('Burden preference cannot lower the scientific quality floor')
    protocol = {'format': FORMAT, 'catalog_sha256': catalog['catalog_sha256'],
                'task_sha256': catalog['task_sha256'], 'candidate_plan_sha256s': ids,
                'policy': deepcopy(policy), 'study_suites': deepcopy(study_suites)}
    digest = suite_digest(protocol)
    studies = []
    for suite in study_suites:
        bound = deepcopy(suite)
        bound['burden_decision'] = {'protocol_sha256': digest}
        studies.append({'suite': bound, 'lock': {'suite_sha256': suite_digest(bound)}})
    return {'protocol': protocol, 'protocol_sha256': digest, 'prepared_studies': studies,
            'state': 'AWAITING_PROSPECTIVE_EVIDENCE', 'execution_authorized': False}


def _stamp(value):
    try:
        result = datetime.fromisoformat(value)
        if result.utcoffset() is None:
            raise ValueError('timezone required')
        return result
    except (TypeError, ValueError) as exc:
        raise ValidationError('Timezone-qualified original timer boundaries required') from exc


def _resources(resource, intervals, cash_refs):
    """Full task window; actor-time sums, wall-time does not. Unknown stays null."""
    _keys(resource, ('window', 'timers', 'cash', 'coverage'))
    _keys(resource['coverage'], PHASES)
    issues, human, cash, estimates = [], 0.0, 0.0, 0.0
    totals = {p: {'human_seconds': 0.0, 'cash_usd': 0.0} for p in PHASES}
    window = resource['window']
    elapsed = None
    if window is not None:
        _keys(window, ('start', 'end', 'source_sha256'))
        _sha(window['source_sha256'])
        begin, end = _stamp(window['start']), _stamp(window['end'])
        elapsed = (end-begin).total_seconds()
        _number(elapsed)
    else:
        issues.append('MISSING_END_TO_END_WINDOW')
    for key in ('timers', 'cash'):
        if not isinstance(resource[key], list) or len(resource[key]) > 10000:
            raise ValidationError('Resource entries require bounded original records')
    if len(intervals)+len(resource['timers']) > 100000 or len(cash_refs)+len(resource['cash']) > 100000:
        raise ValidationError('Total burden ledger exceeds the bounded evidence budget')
    ids = set()
    for timer in resource['timers']:
        _keys(timer, ('id', 'phase', 'actor', 'start', 'end', 'source_sha256'))
        _id(timer['id']); _text(timer['actor']); _sha(timer['source_sha256'])
        if timer['id'] in ids or timer['phase'] not in PHASES:
            raise ValidationError('Duplicate timer or unknown burden phase')
        ids.add(timer['id'])
        start, stop = _stamp(timer['start']), _stamp(timer['end'])
        seconds = (stop-start).total_seconds()
        _number(seconds)
        if window is not None and not begin <= start <= stop <= end:
            raise ValidationError('Human timer falls outside the complete task window')
        intervals.append((timer['actor'], start, stop))
        human += seconds
        totals[timer['phase']]['human_seconds'] += seconds
    ids = set()
    for item in resource['cash']:
        _keys(item, ('id', 'phase', 'amount_usd', 'basis', 'source_sha256', 'line_id'))
        _id(item['id']); _text(item['line_id']); _sha(item['source_sha256'])
        if item['id'] in ids or item['phase'] not in PHASES or item['basis'] not in ('settled', 'estimate', 'unknown'):
            raise ValidationError('Duplicate cash item or unsupported category/basis')
        ids.add(item['id'])
        ref = (item['source_sha256'], item['line_id'])
        if ref in cash_refs:
            raise ValidationError('Settlement line reused across plan or shared overhead')
        cash_refs.add(ref)
        amount = item['amount_usd']
        if amount is not None: _number(amount)
        if item['basis'] != 'settled' or amount is None:
            issues.append('UNSETTLED_OR_UNKNOWN_CASH')
            totals[item['phase']]['cash_usd'] = None
            if item['basis'] == 'estimate' and amount is not None: estimates += amount
        else:
            cash += amount
            if totals[item['phase']]['cash_usd'] is not None: totals[item['phase']]['cash_usd'] += amount
    for phase, coverage in resource['coverage'].items():
        _keys(coverage, ('human', 'cash', 'note'))
        _text(coverage['note'])
        for kind, entries, metric in (('human', resource['timers'], 'human_seconds'), ('cash', resource['cash'], 'cash_usd')):
            status = coverage[kind]
            if status not in ('complete', 'not_applicable', 'unknown'):
                raise ValidationError('Declare coverage for every burden category')
            present = any(e['phase'] == phase for e in entries)
            if status == 'not_applicable' and present:
                raise ValidationError('Not-applicable declaration contradicts original resource entries')
            if status == 'unknown' or (status == 'complete' and not present):
                totals[phase][metric] = None
                issues.append('MISSING_' + kind.upper() + ':' + phase)
    values = {'human_seconds': human if all(t['human_seconds'] is not None for t in totals.values()) else None,
              'cash_usd': cash if all(t['cash_usd'] is not None for t in totals.values()) else None,
              'elapsed_seconds': elapsed}
    for value in values.values():
        if value is not None: _number(value)
    return {'metrics': values, 'phases': totals, 'known_settled_subtotal_usd': cash,
            'estimated_subtotal_usd': estimates, 'issues': sorted(set(issues))}


def _relation(left, right, policy):
    deltas = {m: None if left[m] is None or right[m] is None else left[m]-right[m] for m in METRICS}
    if any(v is None for v in deltas.values()):
        return 'UNKNOWN', deltas
    better = [m for m, d in deltas.items() if d < -policy['metrics'][m]['material_delta']-EPSILON]
    worse = [m for m, d in deltas.items() if d > policy['metrics'][m]['material_delta']+EPSILON]
    if not better and not worse: return 'NO_MATERIAL_DIFFERENCE', deltas
    objective = policy['objective']
    if not worse and (better if objective == 'pareto' else objective in better): return 'LEFT_PREFERRED', deltas
    if not better and (worse if objective == 'pareto' else objective in worse): return 'RIGHT_PREFERRED', deltas
    return 'TRADEOFF', deltas


def analyze(selection, request, *, artifact_root=None, verifier_root=None):
    _keys(request, ('protocol', 'protocol_sha256', 'receipts', 'assurances', 'decision_overhead'))
    protocol = request['protocol']
    _keys(protocol, ('format', 'catalog_sha256', 'task_sha256', 'candidate_plan_sha256s', 'policy', 'study_suites'))
    clean = deepcopy(selection)
    clean['studies'] = []
    prepared = prepare(clean, protocol['policy'], protocol['study_suites'])
    if suite_digest(protocol) != request['protocol_sha256'] or protocol != prepared['protocol']:
        raise ValidationError('Frozen task, policy, catalog or study schedule changed')
    digest = request['protocol_sha256']
    expected = {s['lock']['suite_sha256']: s for s in prepared['prepared_studies']}
    original, submitted = {}, set()
    for study in selection['studies']:
        ident = suite_digest(study['suite'])
        if ident not in expected or ident in submitted:
            raise ValidationError('Unexpected/duplicate study or burden policy was not frozen into the original study')
        submitted.add(ident)
        for arm in ('with', 'without'):
            for rep in range(1, study['suite']['runs_per_case']+1):
                rows = [r for r in study['records'] if r.get('arm') == arm and r.get('repetition') == rep]
                original[(ident, arm, rep)] = sorted(rows, key=lambda r: r.get('case_id', ''))
    # Recompute all scientific, task, regression and full-cost checks. No submitted pass labels.
    base = select_task_plan(selection, artifact_root=artifact_root, verifier_root=verifier_root)
    from .costs import allocation
    cost_plans = {suite_digest(s['suite']): (s['suite'], allocation(s['suite'], s.get('cost_ledger'))) for s in selection['studies']}
    if not isinstance(request['receipts'], list) or len(request['receipts']) > 3200:
        raise ValidationError('Invalid burden receipts')
    observed, intervals, cash_refs = {}, [], set()
    for receipt in request['receipts']:
        _keys(receipt, ('suite_sha256', 'arm', 'repetition', 'records_sha256', 'protocol_sha256', 'resources'))
        _sha(receipt['suite_sha256']); _sha(receipt['records_sha256'])
        if type(receipt['repetition']) is not int or not isinstance(receipt['arm'], str):
            raise ValidationError('Invalid burden receipt coordinates')
        key = (receipt['suite_sha256'], receipt['arm'], receipt['repetition'])
        if key not in original or key in observed or receipt['protocol_sha256'] != digest:
            raise ValidationError('Burden receipt is unbound, duplicate or belongs to another policy')
        if receipt['records_sha256'] != suite_digest(original[key]):
            raise ValidationError('Burden must bind every original case, including failures')
        observed[key] = _resources(receipt['resources'], intervals, cash_refs)
        # A whole-task ledger cannot erase already recorded base expenditure.
        rows = original[key]
        base_cash = [r.get('cost', {}).get(m) for r in rows if r.get('cost', {}).get('basis') == 'settled' for m in ('model_usd', 'tool_usd')]
        base_human = [r.get('cost', {}).get('human_minutes') for r in rows]
        known = lambda values: sum(v for v in values if type(v) in (int,float) and math.isfinite(v) and v >= 0)
        floors = {'cash_usd': known(base_cash), 'human_seconds': known(base_human)*60}
        suite, cost_plan = cost_plans[key[0]]
        for entry in cost_plan['entries']:
            if entry['treatment'] != 'additional' or ('repetition' in entry and entry['repetition'] != key[2]): continue
            fraction = entry['shares'][key[1]] / (1 if 'repetition' in entry else suite['runs_per_case'])
            if entry['category'] == 'human':
                floors['human_seconds'] += fraction*sum((_stamp(t['end'])-_stamp(t['start'])).total_seconds() for t in entry['human_intervals'])
            elif entry['basis'] == 'settled' and entry['amount_usd'] is not None:
                floors['cash_usd'] += fraction*entry['amount_usd']
        for metric, floor in floors.items():
            total = observed[key]['metrics'][metric]
            if total is not None and total + EPSILON < floor:
                raise ValidationError('Whole-task burden is lower than its bound original run records')
    overhead = None
    if request['decision_overhead'] is not None:
        entry = request['decision_overhead']
        _keys(entry, ('protocol_sha256', 'observations_sha256', 'resources'))
        if entry['protocol_sha256'] != digest or entry['observations_sha256'] != suite_digest(selection['studies']):
            raise ValidationError('Shared decision overhead must bind the full original evidence collection')
        overhead = _resources(entry['resources'], intervals, cash_refs)
    latest = {}
    for actor, start, end in sorted(intervals):
        if actor in latest and start < latest[actor]:
            raise ValidationError('Human effort overlaps across phases, candidates or shared PVL overhead')
        latest[actor] = max(end, latest.get(actor, end))
    assurance_by_plan = {}
    if not isinstance(request['assurances'], list) or len(request['assurances']) > len(base['plans']):
        raise ValidationError('Invalid plan review/privacy receipts')
    plans = {p['plan_sha256']: p for p in base['plans']}
    for assurance in request['assurances']:
        _keys(assurance, ('plan_sha256', 'protocol_sha256', 'records_sha256', 'components_sha256', 'locality', 'reviews'))
        ident = assurance['plan_sha256']
        _sha(ident)
        if ident not in plans or ident in assurance_by_plan or assurance['protocol_sha256'] != digest:
            raise ValidationError('Duplicate or unbound plan assurance')
        records = [r for key in sorted(original) for r in original[key] if r.get('selection_plan_sha256') == ident]
        if assurance['records_sha256'] != suite_digest(records) or assurance['components_sha256'] != suite_digest(plans[ident]['manifest']['components']):
            raise ValidationError('Assurance does not bind the current original records and all plan components')
        _keys(assurance['locality'], ('status', 'source_sha256', 'note'))
        if assurance['locality']['status'] not in ('satisfied', 'violated', 'unknown'):
            raise ValidationError('Locality cannot be inferred from a plugin name')
        _sha(assurance['locality']['source_sha256']); _text(assurance['locality']['note'])
        _keys(assurance['reviews'], plans[ident]['required_reviews'])
        for review in assurance['reviews'].values():
            _keys(review, ('status', 'reviewer', 'source_sha256', 'note'))
            if review['status'] not in ('accepted', 'rejected', 'unknown'):
                raise ValidationError('Explicit scoped review status required')
            _text(review['reviewer']); _sha(review['source_sha256']); _text(review['note'])
        assurance_by_plan[ident] = assurance
    policy, candidates = protocol['policy'], []
    synthetic = any(s['evidence_type'] == 'synthetic' for s in protocol['study_suites'])
    for plan in base['plans']:
        ident = plan['plan_sha256']
        keys = [(sha, arm, rep) for sha, study in expected.items() for arm, p in study['suite']['task_selection']['arms'].items()
                if p == ident for rep in range(1, study['suite']['runs_per_case']+1)]
        trials = [observed.get(k) for k in keys]
        metrics = {m: mean(t['metrics'][m] for t in trials) if trials and all(t is not None and t['metrics'][m] is not None for t in trials) else None
                   for m in METRICS[:3]}
        metrics.update(new_plugins=None if plan['size_is_lower_bound'] else plan['size'][0], total_plugins=plan['size'][1])
        blocked, excluded = [], []
        science = plan['sample_outcome'] if synthetic and plan['status'] == 'SIMULATION_ONLY' else plan['status']
        if science in ('FAILED', 'INAPPLICABLE'): excluded.append('SCIENTIFIC_OR_APPLICABILITY_FAILURE')
        elif science != 'SUPPORTED' or plan['applicability_blockers']: blocked.append('SCIENTIFIC_EVIDENCE_INCOMPLETE')
        assurance = assurance_by_plan.get(ident)
        if assurance is None:
            blocked.append('REVIEW_AND_PRIVACY_EVIDENCE_MISSING')
        else:
            if policy['local_only']:
                status = assurance['locality']['status']
                if status == 'violated': excluded.append('LOCAL_ONLY_CONSTRAINT_VIOLATED')
                elif status != 'satisfied': blocked.append('LOCALITY_UNKNOWN')
            reviews = [r['status'] for r in assurance['reviews'].values()]
            if 'rejected' in reviews: excluded.append('REQUIRED_SCIENTIFIC_REVIEW_REJECTED')
            elif 'unknown' in reviews: blocked.append('REQUIRED_SCIENTIFIC_REVIEW_PENDING')
        for m, value in metrics.items():
            if value is None: blocked.append('MISSING_BURDEN:' + m)
            cap = policy['metrics'][m]['max_value']
            # Caps apply to every observed whole-task trial, not only its mean.
            values = [t['metrics'][m] for t in trials if t is not None] if m in METRICS[:3] else [value]
            if cap is not None and any(v is not None and v > cap+EPSILON for v in values): excluded.append('BURDEN_CAP_EXCEEDED:' + m)
        candidates.append({'plan_sha256': ident, 'manifest': plan['manifest'], 'scientific_status': plan['status'],
            'status': 'EXCLUDED' if excluded else 'UNKNOWN' if blocked else 'FEASIBLE',
            'exclusion_reasons': excluded, 'missing_evidence': blocked, 'metrics': metrics,
            'planned_complete_task_trials': len(keys), 'received_burden_trials': sum(t is not None for t in trials),
            'trial_details': [{'suite_sha256': k[0], 'arm': k[1], 'repetition': k[2], 'burden': t} for k,t in zip(keys,trials)],
            'required_reviews': plan['required_reviews']})
    eligible = [c for c in candidates if c['status'] == 'FEASIBLE']
    pairs, wins = [], {c['plan_sha256']: set() for c in eligible}
    relations = {}
    for left, right in combinations(eligible, 2):
        relation, deltas = _relation(left['metrics'], right['metrics'], policy)
        l, r = left['plan_sha256'], right['plan_sha256']
        relations[frozenset((l,r))] = relation
        if relation == 'LEFT_PREFERRED': wins[l].add(r)
        if relation == 'RIGHT_PREFERRED': wins[r].add(l)
        pairs.append({'left': l, 'right': r, 'relation': relation, 'left_minus_right': deltas})
    # Direct comparisons to every alternative avoid order-dependent pruning and
    # cycles introduced by practical tolerance bands. No transitive shortcut.
    preferred = [p for p, beaten in wins.items() if len(beaten) == len(eligible)-1]
    common_complete = overhead is not None and all(v is not None for v in overhead['metrics'].values())
    expected_trials = sum(2*s['suite']['runs_per_case'] for s in expected.values())
    gaps = ['UNOBSERVED_STUDY'] if set(expected) != submitted else []
    gaps += ['UNRESOLVED_CANDIDATES'] if any(c['status'] == 'UNKNOWN' for c in candidates) else []
    gaps += ['DECISION_OVERHEAD_UNKNOWN'] if not common_complete else []
    if len(observed) != expected_trials or any(any(v is None for v in r['metrics'].values()) for r in observed.values()):
        gaps.append('TOTAL_SELECTION_BURDEN_INCOMPLETE')
    gaps += base['baseline_coverage_gaps']
    selected = preferred[0] if len(preferred) == 1 and not gaps else None
    state = 'PREFERRED_IN_OBSERVED_CATALOG' if selected else 'EVIDENCE_REQUIRED' if gaps else 'CHOICE_REQUIRED' if eligible else 'NO_FEASIBLE_PLAN'
    incumbent = policy['incumbent_plan_sha256']
    if selected is None and not gaps and incumbent in wins and all(relations.get(frozenset((incumbent, c['plan_sha256']))) == 'NO_MATERIAL_DIFFERENCE' for c in eligible if c['plan_sha256'] != incumbent):
        selected, state = incumbent, 'NO_MATERIAL_CHANGE_KEEP_INCUMBENT'
    simulated_choice = selected if synthetic else None
    computed_state = state
    if synthetic:
        selected, state = None, 'SIMULATION_ONLY'
    # Common overhead is counted once in the total observed selection process,
    # never copied into every plan or silently amortized into a future forecast.
    all_resources = list(observed.values()) + ([overhead] if overhead else [])
    spent = {m: sum(r['metrics'][m] for r in all_resources) if len(observed)==expected_trials and common_complete and all(r['metrics'][m] is not None for r in all_resources) else None for m in METRICS[:2]}
    return {'format': FORMAT, 'state': state, 'computed_state': computed_state, 'protocol_sha256': digest, 'policy': deepcopy(policy),
        'evidence_status': 'SIMULATION_ONLY' if synthetic else 'RECOMPUTED_SUBMITTED_EVIDENCE',
        'selected_plan_sha256': selected, 'simulation_choice_sha256': simulated_choice,
        'observed_preference_established': bool(selected) and state == 'PREFERRED_IN_OBSERVED_CATALOG',
        'global_minimum_established': False,
        'preferred_observed_plan_sha256s': preferred, 'candidates': candidates, 'comparisons': pairs,
        'blockers': gaps, 'decision_overhead': overhead, 'total_observed_selection_burden': spent,
        'planned_task_trials': expected_trials, 'received_task_trials': len(observed),
        'known_settled_subtotal_usd': sum(r['known_settled_subtotal_usd'] for r in all_resources),
        'default_dependency_choice_sha256': base['selected_plan_sha256'],
        'original_observations_sha256': suite_digest(selection['studies']),
        'required_reviews': sorted({r for p in candidates for r in p['required_reviews']}),
        'execution_authorized': False, 'statistical_guarantee': 'NONE', 'real_benefit_established': False,
        'limits': ['Observed finite catalog only; no future-task optimum, causal savings or statistical equivalence.',
            'Original per-case scientific checks, regression guards, full costs and required reviews cannot be offset by cheaper metrics.',
            'Human timers, privacy reviews and settlement references are submitted, not authenticated facts.',
            'Task means summarize frozen complete-task trials; caps apply to each observed trial.',
            'Shared decision overhead is counted once; plan-specific PVL work stays with that plan.',
            'No labor-to-cash conversion, amortization, weighted score or automatic installation/execution.',
            'Protocol hashes bind content, not an independently witnessed preregistration time.']}


def route(selection, request, **roots):
    if not isinstance(request, dict): raise ValidationError('Burden decision request must be an object')
    if request.get('action') == 'prepare':
        _keys(request, ('action', 'policy', 'study_suites'))
        return prepare(selection, request['policy'], request['study_suites'])
    _keys(request, ('action', 'protocol', 'protocol_sha256', 'receipts', 'assurances', 'decision_overhead'))
    if request['action'] != 'analyze': raise ValidationError('Unknown burden decision action')
    return analyze(selection, {k:v for k,v in request.items() if k != 'action'}, **roots)


def markdown(report):
    from .burden_presentation import escape_markdown as esc
    policy = report.get('policy', report.get('protocol', {}).get('policy'))
    labels = {'human_seconds':'人工投入（秒）', 'cash_usd':'已结算现金（美元）',
              'elapsed_seconds':'完整任务耗时（秒）', 'new_plugins':'新增插件', 'total_plugins':'全部插件', 'pareto':'保留多目标取舍'}
    value = lambda v: '未知' if v is None else f'{v:.6g}'
    lines = ['', '## 科学约束下的负担决策', '',
        f"目标：{labels[policy['objective']]}；数据必须留本地：{'是' if policy['local_only'] else '未设为硬约束'}。",
        '先通过完整任务、科学复核与隐私门槛；现金、人工和耗时分开比较，不折算综合分。', '',
        '指标 | 足以影响行动的差异 | 每次完整任务的上限', '--- | ---: | ---:']
    for m in METRICS:
        lines.append(f"{labels[m]} | {value(policy['metrics'][m]['material_delta'])} | {value(policy['metrics'][m]['max_value']) if policy['metrics'][m]['max_value'] is not None else '未设置'}")
    if 'candidates' not in report:
        return lines + ['', '独立保留协议及 prepared_studies 的冻结内容，再收集原始产物、完整人工计时和费用明细。']
    lines += ['', '方案 | 约束状态 | 人工秒 | 现金美元 | 完整任务秒 | 新增／全部插件', '--- | --- | ---: | ---: | ---: | ---']
    notes = []
    for row in report['candidates']:
        name = ' → '.join(s['component_id'] for s in row['manifest']['steps'])
        m = row['metrics']
        lines.append(f"{esc(name)} ({row['plan_sha256'][:8]}) | {row['status']} | {value(m['human_seconds'])} | {value(m['cash_usd'])} | {value(m['elapsed_seconds'])} | {value(m['new_plugins'])}／{value(m['total_plugins'])}")
        if row['exclusion_reasons'] or row['missing_evidence']:
            notes.append('- '+esc(name)+'：'+esc('；'.join(row['exclusion_reasons']+row['missing_evidence'])))
    lines += ['', *notes]
    lines += ['', '数值为冻结完整任务试次的观察均值；上限逐试次检查，低均值不能掩盖超限。失败和未测方案保留。',
              '准备、执行、复核、返工和 PVL 材料准备／检查／读报告／误报处理／恢复在原始明细中分别记录。']
    for pair in report['comparisons']:
        lines.append(f"- {pair['left'][:8]} / {pair['right'][:8]}：{pair['relation']}；人工差 {value(pair['left_minus_right']['human_seconds'])} 秒，现金差 {value(pair['left_minus_right']['cash_usd'])} 美元。")
    common = report['decision_overhead']
    lines += ['', '共同选型开销只计一次，不复制到每个方案，也不推测未来摊销。',
              f"共同开销：人工 {value(common['metrics']['human_seconds']) if common else '未知'} 秒；现金 {value(common['metrics']['cash_usd']) if common else '未知'} 美元。",
              f"已观察选型过程总投入（含失败）：人工 {value(report['total_observed_selection_burden']['human_seconds'])} 秒；现金 {value(report['total_observed_selection_burden']['cash_usd'])} 美元。",
              '完整明细与缺口见 plan.json。计时、隐私复核与结算引用为提交证据，未独立认证；没有统计等效或现实收益保证。']
    return lines
