"""Bounded L0/L1 local screening, never confirmatory adoption evidence.

The optional runner is a trusted lab-owned adapter, not an execution sandbox.
PVL reserves its declared transport bound before launch; receipts are assertions,
not authenticated provider invoices. No runner is inferred or downloaded.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import random
import re
import shutil
import subprocess
import time

from .core import ValidationError, load_json, suite_digest, _constant, _unique_object
from .gateway_budget import DEFAULT_PER_REQUEST_MICROS, DEFAULT_TOTAL_MICROS, validate_policy
from .request_budget import RequestBudget

CHECKS = ('declaration', 'permissions', 'egress', 'license', 'identity')
LABELS = {'STOP': '停止', 'INSUFFICIENT_EVIDENCE': '证据不足', 'ADVANCE_PILOT': '进入先导'}
DEFAULTS = {'repeats': 2, 'min_gain': 0.05, 'max_regression': 0.05,
            'max_correction_seconds': 600, 'max_seconds': 600,
            'per_request_micros': DEFAULT_PER_REQUEST_MICROS, 'total_micros': DEFAULT_TOTAL_MICROS}


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and value != 'UNKNOWN'


def _number(value, low=0, high=10**12):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def _save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def prepare(plugins, tasks, settings=None):
    if not isinstance(plugins, list) or not plugins:
        raise ValidationError('Supply a nonempty plugin list')
    if not isinstance(tasks, list) or not 3 <= len(tasks) <= 5:
        raise ValidationError('L1 requires 3–5 tasks')
    for rows, kind in ((plugins, 'plugin'), (tasks, 'task')):
        ids = [row.get('id') if isinstance(row, dict) else None for row in rows]
        if any(not _text(i) for i in ids) or len(set(ids)) != len(ids):
            raise ValidationError('Unique nonempty ' + kind + ' IDs required')
    settings = deepcopy({} if settings is None else settings)
    if not isinstance(settings, dict) or set(settings) - set(DEFAULTS) - {'runner', 'model_policy'}:
        raise ValidationError('Unknown screening setting')
    settings = {**DEFAULTS, **settings}
    if type(settings['repeats']) is not int or settings['repeats'] != 2:
        raise ValidationError('L1 freezes two repeats (12–20 attempts)')
    for key in ('min_gain', 'max_regression'):
        if not _number(settings[key], 0, 1):
            raise ValidationError('Invalid screening threshold: ' + key)
    for key in ('max_correction_seconds', 'max_seconds'):
        if not _number(settings[key], 0.001):
            raise ValidationError('Invalid time bound')
    per, total = settings['per_request_micros'], settings['total_micros']
    if type(per) is not int or type(total) is not int or not 0 < per <= total <= 10**12:
        raise ValidationError('Require integer 0 < per-request <= total USD micros')
    if 'model_policy' in settings:
        validate_policy(settings['model_policy'])
        if any(settings['model_policy'][k] != settings[k] for k in ('per_request_micros', 'total_micros')):
            raise ValidationError('Screening and frozen model budgets must agree')
    runner = settings.get('runner')
    if runner is not None:
        if (not isinstance(runner, dict) or set(runner) != {'argv', 'timeout_seconds', 'upper_micros', 'bound_ref', 'files', 'ledger', 'task_id'}
                or not isinstance(runner['argv'], list) or not runner['argv']
                or any(not _text(v) for v in runner['argv'])
                or not _number(runner['timeout_seconds'], 0.001, settings['max_seconds'])
                or type(runner['upper_micros']) is not int or not 0 <= runner['upper_micros'] <= per
                or not _text(runner['bound_ref']) or not isinstance(runner['files'], list) or not runner['files']
                or not _text(runner['task_id']) or not _text(runner['ledger']) or not Path(runner['ledger']).is_absolute()):
            raise ValidationError('Runner needs argv/time/verified upper bound/reference/files')
        # Pin the local adapter files before collecting any results.
        import hashlib
        executable = shutil.which(runner['argv'][0])
        if not executable:
            raise ValidationError('Runner executable is unavailable')
        runner['argv'][0] = str(Path(executable).resolve())
        runner['file_hashes'] = {str(Path(p).resolve()): hashlib.sha256(Path(p).read_bytes()).hexdigest()
                               for p in [executable, *runner['files']]}
    plan = {'format': 'pvl-screen-plan-1', 'plugins': deepcopy(plugins), 'tasks': deepcopy(tasks), 'settings': settings}
    plan['plan_sha256'] = suite_digest(plan)
    return plan


def static_check(plan):
    blocked, missing = [], []
    for plugin in plan['plugins']:
        for field in ('version', 'sha256'):
            if not _text(plugin.get(field)):
                missing.append(f"{plugin['id']}: {field}")
        if not isinstance(plugin.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', plugin['sha256']):
            missing.append(f"{plugin['id']}: 需要有效的内容 SHA-256")
        checks = plugin.get('checks', {})
        if not isinstance(checks, dict):
            checks = {}
        for name in CHECKS:
            check = checks.get(name, {})
            if not isinstance(check, dict):
                check = {}
            if check.get('status') == 'fail' and _text(check.get('evidence_ref')):
                blocked.append(f"{plugin['id']}/{name}: {check['evidence_ref']}")
            elif check.get('status') != 'pass' or not _text(check.get('evidence_ref')):
                missing.append(f"{plugin['id']}/{name}: 需要检查与依据")
    for task in plan['tasks']:
        for field in ('input', 'rubric', 'baseline'):
            if not _text(task.get(field)):
                missing.append(f"{task['id']}: {field}")
    if not {'positive', 'failure', 'boundary'} <= {t.get('kind') for t in plan['tasks']}:
        missing.append('任务应覆盖 positive / failure / boundary 三类')
    return blocked, missing


def schedule(plan):
    runs = []
    rng = random.Random(plan['plan_sha256'])
    for task in plan['tasks']:
        for repeat in range(plan['settings']['repeats']):
            arms = ['without', 'with']
            rng.shuffle(arms)
            for arm in arms:
                runs.append({'task_id': task['id'], 'repeat': repeat, 'arm': arm})
    return runs


def evaluate(plan, rows, execution_reason=None):
    blocked, missing = static_check(plan)
    result = {'format': 'pvl-screen-result-1', 'plan_sha256': plan['plan_sha256'],
              'status': 'INSUFFICIENT_EVIDENCE', 'level': 'L0', 'reasons': [],
              'missing': missing, 'observed_runs': len(rows), 'expected_runs': len(schedule(plan)),
              'claim_level': '描述性观察', 'adoption_supported': False,
              'cost_evidence': 'LAB_REPORTED_NOT_AUTHENTICATED', 'task_deltas': {}}
    if blocked:
        result.update(status='STOP', reasons=blocked)
        return result
    if not missing:
        result['level'] = 'L1'
    expected = {(r['task_id'], r['repeat'], r['arm']) for r in schedule(plan)}
    indexed = {}
    verified_harm = []
    for row in rows:
        if not isinstance(row, dict):
            missing.append('运行记录格式不正确')
            continue
        key = (row.get('task_id'), row.get('repeat'), row.get('arm'))
        try:
            valid_key = key in expected and key not in indexed and type(row.get('repeat')) is int
        except TypeError:
            valid_key = False
        if not valid_key or row.get('plan_sha256') != plan['plan_sha256']:
            missing.append('重复、额外或未绑定冻结方案的记录')
            continue
        indexed[key] = row
        if row.get('critical_failure') is True and _text(row.get('critical_verified_ref')):
            verified_harm.append(f"{key}: {row['critical_verified_ref']}")
        if row.get('critical_failure') is not False:
            missing.append(f'{key}: 关键失败需核实')
        if (row.get('status') not in ('completed', 'failed') or not _number(row.get('score'), 0, 1)
                or not _text(row.get('evidence_ref')) or not _text(row.get('scoring_ref'))
                or not _number(row.get('correction_seconds'))
                or type(row.get('cost_micros')) is not int or row['cost_micros'] < 0
                or not _text(row.get('cost_ref'))):
            missing.append(f'{key}: 分数、评分依据、耗时或费用未知')
    # A verified critical failure stops even if the remaining pairs are absent.
    if verified_harm:
        result.update(status='STOP', reasons=verified_harm)
        return result
    if set(indexed) != expected:
        missing.append(f'配对记录不完整：{len(indexed)}/{len(expected)}')
    if execution_reason:
        missing.append(execution_reason)
        if execution_reason.startswith('BOUND_BREACH:'):
            result.update(status='STOP', reasons=[execution_reason])
            return result
    costs = [r.get('cost_micros') for r in indexed.values()]
    known_costs = [c for c in costs if type(c) is int and c >= 0]
    result['known_cost_micros'] = sum(known_costs)
    result['total_cost_micros'] = sum(known_costs) if len(known_costs) == len(expected) else None
    if (sum(known_costs) > plan['settings']['total_micros']
            or any(c > plan['settings']['per_request_micros'] for c in known_costs)):
        result.update(status='STOP', reasons=['实验室冻结费用上限已超出；保留超额记录'])
        return result
    if missing:
        return result
    for task in plan['tasks']:
        differences = [indexed[(task['id'], r, 'with')]['score'] - indexed[(task['id'], r, 'without')]['score']
                       for r in range(plan['settings']['repeats'])]
        result['task_deltas'][task['id']] = sum(differences) / len(differences)
    average = sum(result['task_deltas'].values()) / len(plan['tasks'])
    result['mean_task_delta'] = average
    settings = plan['settings']
    correction = sum(r['correction_seconds'] for r in indexed.values() if r['arm'] == 'with')
    if correction > settings['max_correction_seconds']:
        result.update(status='STOP', reasons=['人工修正耗时超过冻结的本地实用上限'])
    elif min(result['task_deltas'].values()) < -settings['max_regression']:
        result.update(status='STOP', reasons=['至少一个任务的质量下降超过冻结上限'])
    elif average < settings['min_gain']:
        result.update(status='STOP', reasons=['完整筛查未达到冻结的本地继续投入阈值；不代表总体无效'])
    else:
        result.update(status='ADVANCE_PILOT', reasons=['完整 L1 记录达到预设本地筛选规则；仅支持规划独立先导'])
    return result


def _run(plan, output):
    runner = plan['settings'].get('runner')
    if not runner:
        return [], '未提供实验室执行适配器或配对运行记录'
    import hashlib
    if any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != digest for p, digest in runner['file_hashes'].items()):
        return [], '执行适配器与冻结版本不一致'
    ledger = RequestBudget(runner['ledger'], runner['task_id'])
    state = ledger.status()
    if any(state[k] != plan['settings'][k] for k in ('per_request_micros', 'total_micros')):
        return [], '账本额度与冻结方案不一致'
    rows, start = [], time.monotonic()
    for index, run in enumerate(schedule(plan)):
        remaining = plan['settings']['max_seconds'] - (time.monotonic() - start)
        if remaining <= 0:
            return rows, '冻结时间上限已到；未完成记录保留'
        key = plan['plan_sha256'] + ':' + str(index)
        request = {'format': 'pvl-screen-run-1', 'plan': plan, **run}
        try:
            reservation = ledger.reserve(key, suite_digest(request), 'trusted lab adapter', runner['upper_micros'], allow_zero=runner['upper_micros'] == 0)
            if not reservation['dispatch']:
                return rows, 'RECOVER_ORIGINAL_INVOCATION：不得重复执行已启动的筛查'
        except ValidationError as exc:
            return rows, str(exc)
        # Save the attempt before launch. Errors/timeouts retain their reservation.
        _save(output / f'attempt-{index:02}.json', request)
        row = {**run, 'plan_sha256': plan['plan_sha256'], 'status': 'failed', 'score': None,
               'critical_failure': None, 'cost_micros': None}
        try:
            process = subprocess.run(runner['argv'], input=json.dumps(request), capture_output=True,
                text=True, encoding='utf-8', timeout=min(remaining, runner['timeout_seconds']), shell=False)
            if process.returncode != 0:
                row['failure_reason'] = f'ADAPTER_EXIT_{process.returncode}'
            else:
                receipt = json.loads(process.stdout, parse_constant=_constant, object_pairs_hook=_unique_object)
                if not isinstance(receipt, dict) or any(receipt.get(k, v) != v for k, v in {**run, 'plan_sha256': plan['plan_sha256']}.items()):
                    raise ValueError('receipt identity mismatch')
                row.update(receipt)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            row['failure_reason'] = 'ADAPTER_FAILED_OR_TIMED_OUT_NO_RETRY'
        rows.append(row)
        _save(output / f'receipt-{index:02}.json', row)
        if type(row.get('cost_micros')) is int and row['cost_micros'] > runner['upper_micros']:
            return rows, 'BOUND_BREACH: 执行适配器报告费用超过冻结包络；停止后续运行'
        if row.get('critical_failure') is not False:
            return rows, '关键失败或风险状态未知；停止后续运行，保留缺失配对'
        if time.monotonic() - start > plan['settings']['max_seconds']:
            return rows, '冻结时间上限已到；当前结果仍保留'
    return rows, None


def screen(plugins_path, tasks_path, output, *, settings_path=None, results_path=None, frozen_path=None):
    output = Path(output).resolve()
    if output.exists():
        raise ValidationError('Use a new output directory; prior attempts are never overwritten or rerun')
    plugins, tasks = load_json(plugins_path), load_json(tasks_path)
    if frozen_path:
        plan = load_json(frozen_path)
        content = {k: v for k, v in plan.items() if k != 'plan_sha256'}
        if (plan.get('format') != 'pvl-screen-plan-1' or suite_digest(content) != plan.get('plan_sha256')
                or plan['plugins'] != plugins or plan['tasks'] != tasks or settings_path):
            raise ValidationError('Frozen plan/input mismatch; settings cannot be changed on resume')
        if not results_path:
            raise ValidationError('Resume imports results only; it never relaunches unknown attempts')
    else:
        plan = prepare(plugins, tasks, load_json(settings_path) if settings_path else None)
    output.mkdir(parents=True)
    _save(output / 'frozen-plan.json', plan)
    _save(output / 'schedule.json', schedule(plan))
    blocked, missing = static_check(plan)
    reason = None
    if results_path:
        bundle = load_json(results_path)
        if (not isinstance(bundle, dict) or bundle.get('plan_sha256') != plan['plan_sha256']
                or not isinstance(bundle.get('runs'), list)):
            raise ValidationError('Results must bind the frozen plan and contain runs')
        rows = bundle['runs']
    elif blocked or missing:
        rows = []
    else:
        try:
            rows, reason = _run(plan, output)
        except (ValidationError, OSError):
            rows, reason = [], '执行账本或适配器无法核对；未获得可用配对记录'
    _save(output / 'runs.json', {'plan_sha256': plan['plan_sha256'], 'runs': rows})
    result = evaluate(plan, rows, reason)
    result['decision'] = LABELS[result['status']]
    result['use_card'] = str(output / 'use-card.md')
    result['frozen_plan'] = str(output / 'frozen-plan.json')
    _save(output / 'result.json', result)
    next_step = {'STOP': '停止当前用途；修复后以新版本、新记录重新筛查。',
                 'INSUFFICIENT_EVIDENCE': '补齐所列信息或导入绑定本方案的配对记录；不重跑未知请求。',
                 'ADVANCE_PILOT': '规划独立任务族先导；本结果不自动启动下一轮执行。'}[result['status']]
    details = result['reasons'] + result['missing']
    card = [f"# 插件使用卡：{result['decision']}", '',
            '插件组合：' + '、'.join(p['id'] for p in plugins),
            f"当前阶段：{result['level']}；范围：本清单作为一个组合、当前 {len(tasks)} 个任务。",
            f"已回答：是否满足本地筛选规则；运行记录 {len(rows)}/{result['expected_runs']}。",
            '尚未回答：真实增益、跨任务泛化及采用价值。', '',
            *['- ' + item for item in details], '', '下一步：' + next_step,
            f"上限：单次 ${plan['settings']['per_request_micros']/1e6:g}；本轮 ${plan['settings']['total_micros']/1e6:g}；{plan['settings']['max_seconds']:g} 秒。",
            '费用与检查依据由实验室提供；UNKNOWN 不等于零。哈希绑定内容，不证明事前注册或来源真实性。',
            f"冻结方案：`{plan['plan_sha256']}`", '']
    (output / 'use-card.md').write_text('\n'.join(card), encoding='utf-8')
    return result
