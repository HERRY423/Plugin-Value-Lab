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
        cases.append({"id": case["id"], "rules": rules, "samples": sample_rows})
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
