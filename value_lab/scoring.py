"""Deterministic rubric checks and calibration; never an LLM judge."""
from itertools import combinations
import math
import re


def validate_rules(case):
    from .core import FILE_GRADERS, ValidationError, suite_digest
    seen = set()
    for g in case["graders"]:
        allowed = {"id", "type", "dimension", "weight", "critical", "examples", "value", "path", "rubric", "artifact", "verifier"}
        unknown = set(g) - allowed
        if unknown:
            raise ValidationError(f"{case['id']}/{g['id']}: 不支持的评分字段 {sorted(unknown)}")
        if g["type"] == "json_equals":
            if any(not p or p.strip() != p or re.fullmatch(r"-\d+", p) for p in g["path"].split(".")):
                raise ValidationError(f"{case['id']}/{g['id']}: JSON 路径含空段、空白或负索引")
            try:
                suite_digest(g["value"])
            except (ValueError, TypeError) as exc:
                raise ValidationError("JSON 目标必须是有限的 JSON 值") from exc
        signature = suite_digest({k: g[k] for k in ("type", "dimension", "path", "value", "rubric", "artifact", "verifier") if k in g})
        if signature in seen:
            raise ValidationError(f"{case['id']}: 重复评分规则会重复加权")
        seen.add(signature)
        if "examples" in g:
            if g["type"] in FILE_GRADERS | {"sealed", "scenario"}:
                raise ValidationError("Artifact calibration requires files; text examples cannot validate artifacts")
            examples = g["examples"]
            if not isinstance(examples, list):
                raise ValidationError("评分校准样例必须是列表")
            outputs = {}
            for item in examples:
                if not isinstance(item, dict) or set(item) != {"output", "passed"} or not isinstance(item["output"], str) or type(item["passed"]) is not bool:
                    raise ValidationError("校准样例需要 output 文本和 passed 布尔值")
                if item["output"] in outputs:
                    raise ValidationError("校准样例输出重复或标签互相矛盾")
                outputs[item["output"]] = item["passed"]
                if g["type"] != "human":
                    from .core import _grade
                    if _grade(g, {"output": item["output"]})[0] != item["passed"]:
                        raise ValidationError(f"{case['id']}/{g['id']}: 规则与校准样例不一致")
    if not math.isfinite(sum(g["weight"] for g in case["graders"])):
        raise ValidationError("评分权重之和溢出")
    for a, b in combinations(case["graders"], 2):
        if a["dimension"] != b["dimension"]:
            continue
        types = {a["type"], b["type"]}
        if types == {"contains", "not_contains"}:
            positive, negative = (a, b) if a["type"] == "contains" else (b, a)
            if negative["value"] in positive["value"]:
                raise ValidationError(f"{case['id']}: {a['id']} 与 {b['id']} 矛盾，无法同时通过")
        if a["type"] == b["type"] == "json_equals":
            if a["path"] == b["path"] and suite_digest(a["value"]) != suite_digest(b["value"]):
                raise ValidationError(f"{case['id']}: 同一个 JSON 路径有互斥目标值")


def _outcome_roles(grader):
    """Declared verifier capability, never keyword guesses about a prompt/output."""
    if grader['dimension'] != 'outcome':
        return []
    if grader['type'] in ('over_refusal', 'abstention_correct'):
        return ['decision']
    if grader['type'] == 'artifact_schema':
        return ['delivery']
    if grader['type'] == 'backend_identity':
        return []
    return ['delivery', 'correctness']


def success_requirements(case):
    """Normalize the frozen acceptance contract without touching observations."""
    from .core import ValidationError
    contract = case.get('success_contract')
    graders = {g['id']: g for g in case['graders']}
    endpoints = ('decision', 'delivery', 'correctness')
    roles = {e: sorted(g['id'] for g in graders.values() if e in _outcome_roles(g)) for e in endpoints}
    schemas = sorted(g['id'] for g in graders.values() if g['dimension'] == 'outcome' and g['type'] == 'artifact_schema')
    if schemas:
        # A delivered, structurally valid answer can still be wrong. Do not
        # let the correctness layer erase independent delivery evidence.
        roles['delivery'] = schemas
    scored = [g for g in graders.values() if g['dimension'] == 'outcome']
    if contract is None:
        # Existing text-only suites retain their frozen rubric/floor semantics.
        # Typed artifact/decision checks use the evidence layers below.
        mode = ('configured_checks' if all(g['type'] in ('contains', 'not_contains') for g in scored)
                else 'decision' if case['kind'] == 'abstention' and roles['decision']
                     and not roles['delivery'] and not roles['correctness'] else 'task')
        return dict(roles, mode=mode, basis='INFERRED_FROM_FROZEN_GRADER_TYPES_AND_CASE_KIND')
    if (not isinstance(contract, dict) or set(contract) - {'version', 'mode', *endpoints}
            or type(contract.get('version')) is not int or contract['version'] != 1
            or contract.get('mode') not in ('task', 'decision')):
        raise ValidationError(f"{case['id']}: success_contract needs version 1 and task/decision mode")
    for endpoint in endpoints:
        if endpoint not in contract:
            continue
        ids = contract[endpoint]
        if (not isinstance(ids, list) or any(not isinstance(gid, str) or gid not in graders for gid in ids)
                or len(ids) != len(set(ids))):
            raise ValidationError(f"{case['id']}: {endpoint} must list unique existing grader ids")
        for gid in ids:
            grader = graders[gid]
            if (grader['dimension'] != 'outcome' or grader['type'] == 'backend_identity'
                    or (endpoint == 'decision' and grader['type'] not in
                        ('over_refusal', 'abstention_correct', 'human', 'json_equals', 'contains', 'not_contains'))
                    or (grader['type'] in ('artifact_schema', 'over_refusal', 'abstention_correct')
                        and endpoint not in _outcome_roles(grader))):
                raise ValidationError(f"{case['id']}/{gid}: process or narrower evidence cannot establish {endpoint}")
        # Declaring extra necessary checks must not disable existing decisive
        # artifact evidence by supplying an empty list or a passing schema.
        roles[endpoint] = sorted(set(roles[endpoint]) | set(ids))
    if contract['mode'] == 'decision':
        if not roles['decision']:
            raise ValidationError(f"{case['id']}: decision mode needs a decision outcome grader")
        if any(contract.get(e) for e in ('delivery', 'correctness')):
            raise ValidationError(f"{case['id']}: use task mode when delivery/correctness are required")
        if any(g['type'] not in ('over_refusal', 'abstention_correct', 'backend_identity',
                                 'contains', 'not_contains') and g['id'] not in roles['decision'] for g in scored):
            raise ValidationError(f"{case['id']}: result graders require task mode; decision mode cannot bypass them")
    return dict(roles, mode=contract['mode'], basis='EXPLICIT_FROZEN_SUCCESS_CONTRACT')


def _all_states(states):
    """Order-independent conjunction: false dominates unknown; empty is unknown."""
    states = list(states)
    if any(s is False for s in states):
        return False
    if not states or any(s is not True for s in states):
        return None
    return True


def assess_task_outcome(case, run, floor):
    """Preserve partial scores while separately assessing necessary result evidence."""
    required = success_requirements(case)
    grades = {g['id']: g for g in run['grades']}
    mode, layers = required['mode'], {}
    for endpoint in ('decision', 'delivery', 'correctness'):
        needed = ((endpoint == 'decision' and bool(required[endpoint]))
                  or (mode == 'task' and endpoint in ('delivery', 'correctness')))
        if mode == 'decision' and endpoint != 'decision':
            needed = False
        ids = required[endpoint] if needed else []
        state = _all_states(grades.get(gid, {}).get('passed') for gid in ids) if needed else None
        layers[endpoint] = {'required': needed, 'grader_ids': ids, 'passed': state,
                            'status': 'PASS' if state is True else 'FAIL' if state is False
                            else 'UNKNOWN' if needed else 'NOT_REQUIRED'}
    # Invariant constant outputs can satisfy every relation. A relation pass
    # alone must not become a correctness claim through the quality floor.
    correctness = required['correctness']
    definitions = {g['id']: g for g in case['graders']}
    metamorphic = [gid for gid in correctness if definitions[gid]['type'] == 'metamorphic']
    anchors = [gid for gid in correctness if definitions[gid]['type'] not in
               ('metamorphic', 'contains', 'not_contains', 'artifact_schema', 'backend_identity')]
    if metamorphic and not anchors and layers['correctness']['passed'] is True:
        layers['correctness'].update(passed=None, status='UNKNOWN',
            reason='Metamorphic consistency requires a separate task correctness oracle')
    floor_met = run['score'] is not None and run['score'] + 1e-12 >= floor
    critical = [g['passed'] for g in run['grades'] if g['critical']]
    critical_state = _all_states(critical) if critical else True
    checks = [v['passed'] for v in layers.values() if v['required']]
    evidence = _all_states(checks) if checks else None
    if mode == 'configured_checks':
        evidence = floor_met
    # Assessment evidence is kept separate from observation admissibility;
    # cost-only gaps must not erase artifact checks in endpoint interpretation.
    acceptance = _all_states([evidence, critical_state, floor_met])
    if run['status'] in ('error', 'timeout', 'aborted'):
        acceptance = False
    elif run['status'] != 'completed':
        acceptance = None
    state = None if run['issues'] or run['score'] is None else acceptance
    reasons = [f"{name}:{v['status']}" for name, v in layers.items()
               if v['required'] and v['passed'] is not True]
    if critical_state is not True:
        reasons.append('critical_check_failed_or_unknown')
    if not floor_met:
        reasons.append('quality_floor_not_met_or_unknown')
    if run['issues']:
        reasons.append('observation_or_required_verification_issue')
    return {'version': 1, 'mode': mode, 'basis': required['basis'], 'layers': layers,
            'assessment_passed': acceptance, 'passed': state,
            'status': 'PASS' if state is True else 'FAIL' if state is False else 'UNKNOWN',
            'quality_floor_met': floor_met, 'critical_checks_passed': critical_state,
            'reasons': reasons, 'claim_limit': 'Frozen submitted checks only; no independent scientific validation'}


def run_success(run, floor):
    """One success definition for metric, cost and recommendation denominators."""
    if run is None or run.get('issues') or run.get('score') is None:
        return None
    if run['status'] != 'completed':
        return False if run['status'] in ('error', 'timeout', 'aborted') else None
    if 'task_outcome' in run:
        return run['task_outcome']['passed']
    # Legacy report rows remain readable; all new evaluations attach task_outcome.
    return (run['score'] + 1e-12 >= floor
            and all(g['passed'] is True for g in run['grades'] if g['critical']))


def inspect_rules(suite, samples=None):
    from .core import ValidationError, _grade, validate_suite
    try:
        validate_suite(suite)
    except (ValidationError, ValueError, TypeError) as exc:
        return {"valid": False, "errors": [str(exc)], "warnings": [], "cases": [], "sample_scope": "Calibration only; not study observations"}
    if samples is not None and (not isinstance(samples, dict) or any(
        k not in {c["id"] for c in suite["cases"]} or not isinstance(v, list) or any(not isinstance(x, str) for x in v)
        for k, v in samples.items())):
        raise ValidationError("试评分需要按有效任务编号提供文本列表")
    warnings, cases = [], []
    for case in suite["cases"]:
        rules = []
        total = sum(g["weight"] for g in case["graders"] if g["dimension"] == "outcome")
        for g in case["graders"]:
            if g["type"] in ("artifact", "executable", "sealed"):
                warnings.append(f"{case['id']}/{g['id']}: Requires collected artifact bytes; text-only previews remain unresolved")
            if g["critical"] and g["dimension"] == "process":
                warnings.append(f"{case['id']}/{g['id']}: 关键过程规则不计入质量，只限制该案例的使用建议；不能替代关键结果门槛")
            if g["type"] == "json_equals":
                warnings.append(f"{case['id']}/{g['id']}: 支持本地精确评分；原生 Claude 导出没有等价判据，执行准备会拒绝")
            if g["type"] in ("contains", "not_contains"):
                warnings.append(f"{case['id']}/{g['id']}: 文字检查不能验证语义正确或证明插件未触发")
            if g["type"] == "human":
                warnings.append(f"{case['id']}/{g['id']}: 需要真实人工判定；原生导出仅做模型评分诊断")
            labels = {x["passed"] for x in g.get("examples", [])}
            if labels != {False, True}:
                warnings.append(f"{case['id']}/{g['id']}: 尚未提供完整的通过与失败校准样例")
            rules.append({"id": g["id"], "type": g["type"], "critical": g["critical"],
                          "outcome_share": g["weight"] / total if g["dimension"] == "outcome" else 0})
        for a, b in combinations(case["graders"], 2):
            if a["type"] == b["type"] and a["type"] in ("contains", "not_contains") and a["dimension"] == b["dimension"]:
                if a["value"] in b["value"] or b["value"] in a["value"]:
                    warnings.append(f"{case['id']}: {a['id']} 与 {b['id']} 存在包含关系，可能重复奖励同一事实")
        sample_rows = []
        for output in (samples or {}).get(case["id"], []):
            if not isinstance(output, str):
                raise ValidationError("试评分输入必须是文本")
            grades = [{"id": g["id"], "passed": _grade(g, {"output": output})[0], "dimension": g["dimension"]} for g in case["graders"]]
            unresolved = any(row["passed"] is None for row in grades if row["dimension"] == "outcome")
            score = None if unresolved else sum(g["weight"] for g, row in zip(case["graders"], grades) if g["dimension"] == "outcome" and row["passed"] is True) / total
            critical = [g["id"] for g, row in zip(case["graders"], grades) if g["critical"] and row["passed"] is False]
            sample_rows.append({"output": output, "score": score, "grades": grades, "critical_failures": critical})
        requirements = success_requirements(case)
        if requirements['mode'] == 'task':
            for endpoint in ('delivery', 'correctness'):
                if not requirements[endpoint]:
                    warnings.append(f"{case['id']}: 缺少 {endpoint} 结果判据；过程检查或决策通过不能填补该证据")
        cases.append({"id": case["id"], "rules": rules, "samples": sample_rows,
                      "success_requirements": requirements})
    if len({c["cluster"] for c in suite["cases"]}) < suite["policy"]["min_clusters"]:
        warnings.append("任务类别数低于方案门槛；重复运行不能代替独立任务类别")
    prompts = {}
    for case in suite["cases"]:
        prompt = " ".join(case["prompt"].split())
        if prompt in prompts:
            warnings.append(f"{case['id']} 与 {prompts[prompt]} 的提示相同；重复或改名不能建立任务独立性")
        prompts[prompt] = case["id"]
    if suite["policy"]["human_hourly_usd"] == 0:
        warnings.append("人工时薪为零：仍须记录时间，不能据此宣称人工工作没有成本")
    return {"valid": True, "errors": [], "warnings": list(dict.fromkeys(warnings)), "cases": cases,
            "sample_scope": "Calibration only; not study observations", "scientific_validity": "NOT_ESTABLISHED"}
