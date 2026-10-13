"""Researcher-loss decisions over simultaneous bounds; no probability imputation.

Losses and guardrail effects are explicit preferences/assumptions, not observed
benefit. Selection shrinkage never changes certification or rank bounds.
"""
from datetime import datetime, timezone
import math

from .core import ValidationError
from .task_selection import _keys, _text

ACTIONS = {'adopt': '采用(限域)', 'trial': '带护栏试用',
           'baseline': '默认基线', 'avoid': '不使用'}


def _number(value, low=0, high=1e12):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValidationError('Decision losses must be finite, nonnegative and within bounds')


def _stamp(value):
    if not isinstance(value, str):
        raise ValidationError('Decision validity requires timezone-aware timestamps')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValidationError('Invalid decision validity timestamp') from exc
    if stamp.tzinfo is None:
        raise ValidationError('Decision validity requires a timezone')
    return stamp.astimezone(timezone.utc)


def validate_policy(policy, candidate_ids, baseline_id):
    _keys(policy, ('researcher_id', 'loss_unit', 'false_adoption_cost', 'missed_use_cost',
                   'time_cost_per_hour', 'scope', 'valid_from', 'valid_until',
                   'minimum_gain', 'confirmation_family_floor', 'candidates', 'shrinkage'))
    for key in ('researcher_id', 'loss_unit', 'scope'):
        _text(policy[key])
    for key in ('false_adoption_cost', 'missed_use_cost', 'time_cost_per_hour'):
        _number(policy[key])
    if policy['false_adoption_cost'] + policy['missed_use_cost'] <= 0:
        raise ValidationError('At least one decision error must have positive loss')
    _number(policy['minimum_gain'], 0, 1)
    if type(policy['confirmation_family_floor']) is not int or not 30 <= policy['confirmation_family_floor'] <= 100000:
        raise ValidationError('Confirmation needs at least 30 independent families')
    if _stamp(policy['valid_until']) <= _stamp(policy['valid_from']):
        raise ValidationError('Decision expiry must follow valid_from')
    rows = policy['candidates']
    if not isinstance(rows, dict) or set(rows) != set(candidate_ids) - {baseline_id}:
        raise ValidationError('Supply researcher preferences for each non-baseline candidate')
    for row in rows.values():
        _keys(row, ('adopt_hours', 'trial_hours', 'evidence_hours', 'trial_exposure',
                    'trial_residual_harm', 'guardrails', 'prohibited', 'prohibition_reason'))
        for key in ('adopt_hours', 'trial_hours', 'evidence_hours'):
            _number(row[key], 0, 1e6)
        for key in ('trial_exposure', 'trial_residual_harm'):
            _number(row[key], 0, 1)
        if type(row['prohibited']) is not bool:
            raise ValidationError('Declare whether this use is prohibited')
        if not isinstance(row['guardrails'], list) or len(row['guardrails']) > 30:
            raise ValidationError('Supply bounded explicit trial guardrails')
        for guard in row['guardrails']:
            _text(guard)
        if row['prohibited']:
            _text(row['prohibition_reason'])
        elif row['prohibition_reason'] is not None:
            raise ValidationError('A non-prohibited candidate has no prohibition reason')
    shrink = policy['shrinkage']
    _keys(shrink, ('target', 'strength', 'rationale'))
    _number(shrink['target'], 0, 1)
    _number(shrink['strength'], 1e-8, 100000)
    _text(shrink['rationale'])


def selection_uncertainty(protocol, rows, valid=True):
    """Project the existing simultaneous rectangle onto possible rank positions."""
    k = len(rows)
    shrink = protocol.get('decision_policy', {}).get('shrinkage')
    result = []
    for ident, row in rows.items():
        lower = 1 + sum(other['lower'] > row['upper'] for key, other in rows.items() if key != ident)
        upper = k - sum(other['upper'] < row['lower'] for key, other in rows.items() if key != ident)
        estimate = (row['n'] * row['mean'] + shrink['strength'] * shrink['target']) / (row['n'] + shrink['strength']) if shrink and row['n'] else None
        result.append({'candidate_id': ident, 'raw_mean': row['mean'], 'shrunk_mean': estimate,
                       'rank_interval': [lower, upper] if valid else [1, k]})
    return {'scope': 'Frozen candidate set and utility population only; ties span possible positions',
            'method': 'simultaneous_candidate_bounds_rank_projection',
            'status': 'CONDITIONAL' if valid else 'UNAVAILABLE',
            'multiplicity': {'candidate_count': k, 'local_horizon': protocol['max_units_per_candidate'],
                             'family_alpha': protocol['alpha'] if valid else None,
                             'correction': 'existing_K_times_H_union_bound_no_extra_rank_tests'},
            'shrinkage': {'status': 'FROZEN_REGULARIZATION' if shrink else 'NOT_CONFIGURED',
                          'parameters': shrink, 'used_for_certification': False,
                          'bias_removal_guaranteed': False}, 'candidates': result}


def action_report(protocol, risk, *, confirmations=None, now=None):
    """Minimax regret over benefit/non-benefit states consistent with the bounds.

    confirmations is an internal map from raw-record recomputation, never a
    passed flag accepted in a public request.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValidationError('Decision clock requires a timezone')
    policy = protocol.get('decision_policy')
    if policy is None:
        return {'status': 'LOSSES_REQUIRED', 'action': ACTIONS['baseline'],
                'reason': '尚未填写研究者损失，保留基线；不自动推断损失或采用。',
                'valid_until': None, 'validity': '仅本次规划；填写损失或证据改变后重算',
                'next_evidence': {'action': '填写误采用成本、漏用成本、每小时成本和适用范围。'},
                'candidates': [], 'automatic_execution': False}
    baseline = risk['intervals'][protocol['baseline_id']]
    live = risk['evidence_status'] == 'SUBMITTED_OBSERVATIONS'
    valid = (risk['statistical_guarantee']['status'] != 'UNAVAILABLE'
             and risk['state'] not in ('REPAIR_EVIDENCE', 'WAIT_FOR_ORIGINAL_BLOCK', 'REVIEW_TASK_APPLICABILITY'))
    fresh = _stamp(policy['valid_from']) <= now.astimezone(timezone.utc) < _stamp(policy['valid_until'])
    confirmations = confirmations or {}
    output = []
    for ident, prefs in policy['candidates'].items():
        row = risk['intervals'][ident]
        dl, du = (row['lower'] - baseline['upper'], row['upper'] - baseline['lower']) if valid else (-1, 1)
        states = ([1] if dl > policy['minimum_gain'] else [0] if du <= policy['minimum_gain'] else [0, 1])
        fa, miss, rate = (policy[k] for k in ('false_adoption_cost', 'missed_use_cost', 'time_cost_per_hour'))
        losses = {'adopt': {0: fa + rate*prefs['adopt_hours'], 1: rate*prefs['adopt_hours']},
                  'baseline': {0: 0, 1: miss}, 'avoid': {0: 0, 1: miss},
                  'trial': {0: fa*prefs['trial_residual_harm'] + rate*prefs['trial_hours'],
                            1: miss*(1-prefs['trial_exposure']) + rate*prefs['trial_hours']}}
        admissible = ['baseline']
        blockers = []
        if not live: blockers.append('合成或尚无真实观察，不作部署建议')
        if not valid: blockers.append('证据完整性、适用性或抽样假设待修复')
        if not fresh: blockers.append('尚未生效或已经到期，须重新审阅')
        if not confirmations.get(ident): blockers.append('缺少独立、达到功效与候选校正门槛的确认记录')
        if prefs['prohibited']:
            admissible = ['avoid']
            blockers.insert(0, prefs['prohibition_reason'])
        elif live and valid and fresh:
            if prefs['guardrails'] and prefs['trial_exposure'] > 0:
                admissible.append('trial')
            if confirmations.get(ident) and dl > policy['minimum_gain']:
                admissible.append('adopt')
            if row['upper'] < protocol['quality_floor']:
                admissible = ['avoid']
                blockers.insert(0, '候选效用上界仍低于冻结最低效用，当前用途不使用')
        # Compare only actions actually feasible in this scope; no fake precise p.
        oracle = {s: min(losses[a][s] for a in admissible) for s in states}
        regrets = {a: max(losses[a][s]-oracle[s] for s in states) for a in admissible}
        chosen = min(admissible, key=lambda a: regrets[a])  # baseline wins exact ties
        ambiguous = len(states) == 2
        next_action = ('核实禁用原因；若条件改变，重新静态审阅。' if prefs['prohibited'] else
                       '修复缺失记录、费用或抽样条件，再重算；不新增重复调用。' if not valid else
                       '重新核对版本、适用范围及损失，设置新的有效期。' if not fresh else
                       '先采集真实独立任务族，合成结果不能进入采用。' if not live else
                       '对候选与基线补一个完整独立族；优先分辨是否超过实用增益阈值。' if ambiguous else
                       '用未参与筛选的保留族完成固定确认；候选多重校正及功效门槛同时满足。' if not confirmations.get(ident) else
                       '在有效期内监测关键失败和任务分布漂移；变化即重新评估。')
        # Additional evidence can unlock adoption; the current admissible set
        # alone would misleadingly assign zero information value to abstention.
        future_actions = ['baseline', 'adopt'] + (['trial'] if prefs['guardrails'] and prefs['trial_exposure'] > 0 else [])
        avoidable = (0.0 if prefs['prohibited'] else max(
            losses[chosen][s] - min(losses[a][s] for a in future_actions) for s in states))
        time_loss = rate*prefs['evidence_hours']
        reason = ('；'.join(blockers[:3]) if len(admissible) == 1 and blockers else
                  '按研究者填写的损失比较当前允许行动的最大后悔值：' +
                  '，'.join(ACTIONS[a] + '=' + format(regrets[a], '.6g') for a in admissible) +
                  '；取最小值，并列保留基线，不赋予状态概率。')
        if live and valid and fresh and not prefs['prohibited'] and avoidable <= time_loss:
            next_action = '补证据价值上限不覆盖填写的时间成本，暂不新增运行；偏好或成本改变后复评，仍监测关键失败。'
        options = [{'action': label, 'eligible': action in admissible,
                    'reason': reason if action == chosen else ('按同一损失表比较后未选中' if action in admissible else '当前证据/禁用/护栏门槛不允许'),
                    'loss_by_state': {'no_material_benefit': losses[action][0], 'material_benefit': losses[action][1]},
                    'worst_regret': regrets.get(action), 'valid_until': policy['valid_until'],
                    'next_evidence_action': next_action} for action, label in ACTIONS.items()]
        output.append({'candidate_id': ident, 'action': ACTIONS[chosen], 'reason': reason,
                       'scope': policy['scope'], 'valid_until': policy['valid_until'],
                       'valid_now': fresh, 'invalidate_on': ['版本或输入范围改变', '新关键失败', '损失或护栏改变'],
                       'adoption_blockers': blockers,
                       'delta_interval': [dl, du], 'benefit_states': states,
                       'worst_regret': regrets[chosen], 'loss_unit': policy['loss_unit'],
                       'worst_state_loss': max(losses[chosen][s] for s in states),
                       'regret_reference': 'Currently admissible actions; zero regret does not imply zero loss',
                       'guardrails': prefs['guardrails'] if chosen == 'trial' else [], 'options': options,
                       'next_evidence': {'action': next_action, 'avoidable_regret_upper_bound': avoidable,
                           'time_loss': time_loss, 'priority_score': max(0.0, avoidable-time_loss),
                           'basis': 'Perfect-information regret ceiling minus submitted time loss; not estimated EVSI',
                           'budget_check_required': True}})
    priority = max(output, key=lambda row: row['next_evidence']['priority_score']) if output else None
    return {'status': 'RESEARCHER_LOSS_ACTIONS', 'candidates': output,
            'loss_basis': 'User supplied binary-state decision losses and assumed guardrail effects; not probabilities',
            'next_evidence': {'candidate_id': priority['candidate_id'], **priority['next_evidence']} if priority else None,
            'simultaneous_trials_authorized': False, 'automatic_execution': False}
