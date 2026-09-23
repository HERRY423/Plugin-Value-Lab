"""Compare frozen studies without attributing simultaneous changes to one factor."""
from .core import ValidationError, evaluate, suite_digest


def _difference(before, after, prefix=""):
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(set(before) | set(after)):
            result.extend(_difference(before.get(key), after.get(key), f"{prefix}.{key}".strip(".")))
        return result
    if suite_digest(before) != suite_digest(after):
        return [{"field": prefix, "before": before, "after": after}]
    return []


def compare_studies(before, after):
    """Input objects contain suite, records, lock; optional cost_ledger and context.

    Context is observed by the caller (snapshot hash / CLI version), not inferred
    from a version string. All numeric comparisons remain descriptive.
    """
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValidationError("比较需要两份完整研究输入")
    for study in (before, after):
        if any(k not in study for k in ("suite", "records", "lock")):
            raise ValidationError("比较输入缺少方案、记录或冻结锁")
    a, b = before["suite"], after["suite"]
    reports = [evaluate(s["suite"], s["records"], s["lock"], s.get("cost_ledger")) for s in (before, after)]
    contexts = [s.get("context") or {} for s in (before, after)]
    if any(not isinstance(c, dict) for c in contexts):
        raise ValidationError("比较上下文必须是对象")
    differences = _difference({"plugin": a["plugin"], "conditions": a["conditions"], "policy": a["policy"], "runs_per_case": a["runs_per_case"]},
                              {"plugin": b["plugin"], "conditions": b["conditions"], "policy": b["policy"], "runs_per_case": b["runs_per_case"]})
    differences += _difference(contexts[0], contexts[1], "context")
    fields = {d["field"] for d in differences}
    plugin_change = bool(fields & {"plugin.version", "context.plugin_sha256"})
    model_change = "conditions.model" in fields
    axis = "combined" if plugin_change and model_change else "plugin_revision" if plugin_change else "model" if model_change else "replicate"
    blockers, warnings = [], []
    allowed = {"plugin.version", "context.plugin_sha256", "conditions.model"}
    confounders = sorted(fields - allowed)
    if confounders:
        blockers.append("除目标因素外还有条件变化：" + ", ".join(confounders))
    if axis == "combined":
        blockers.append("插件与模型同时变化，不能把差异归因给其中任一个；请补齐同模型版本比较或同插件模型比较")
    if a["plugin"]["name"] != b["plugin"]["name"]:
        blockers.append("插件身份不同：这是替代插件比较，不是同一插件升级")
    if not all(c.get("plugin_sha256") for c in contexts):
        blockers.append("缺少两份插件内容指纹，仅版本标签不能建立插件一致或变化")
    if any(c.get("integrity_issues") for c in contexts):
        blockers.append("研究证据文件与封存哈希不一致")
    before_cases = {c["id"]: c for c in a["cases"]}
    after_cases = {c["id"]: c for c in b["cases"]}
    added, removed = sorted(after_cases.keys()-before_cases.keys()), sorted(before_cases.keys()-after_cases.keys())
    if added or removed:
        blockers.append("任务集合变化；缺失或新增任务不能从整体比较中静默剔除")
    rows, changed = [], []
    r_before = {c["id"]: c for c in reports[0]["cases"]}
    r_after = {c["id"]: c for c in reports[1]["cases"]}
    def delta(x, y):
        return y-x if x is not None and y is not None else None
    for case_id in sorted(before_cases.keys() | after_cases.keys()):
        left, right = before_cases.get(case_id), after_cases.get(case_id)
        same = left is not None and right is not None
        if same:
            # Rule order has no scoring significance; IDs, definitions and calibration do.
            def canonical(c):
                return {**c, "graders": sorted(c["graders"], key=lambda g: g["id"])}
            same = suite_digest(canonical(left)) == suite_digest(canonical(right))
            if not same:
                changed.append(case_id)
        old, new = r_before.get(case_id, {}), r_after.get(case_id, {})
        rows.append({"case_id": case_id, "same_task_and_rules": same,
                     "before_with": old.get("with_score"), "after_with": new.get("with_score"),
                     "with_change": delta(old.get("with_score"), new.get("with_score")) if same else None,
                     "baseline_change": delta(old.get("without_score"), new.get("without_score")) if same else None,
                     "plugin_gain_change": delta(old.get("delta"), new.get("delta")) if same else None,
                     "regression": same and old.get("with_score") is not None and new.get("with_score") is not None and new["with_score"] < old["with_score"] - b["policy"]["max_case_regression"]})
    if changed:
        blockers.append("任务提示、评分规则、权重、样例或类别变化：" + ", ".join(changed))
    sessions = [{r.get("session_id") for r in s["records"] if isinstance(r.get("session_id"), str) and r["session_id"]} for s in (before, after)]
    if sessions[0] & sessions[1]:
        blockers.append("两项研究复用了会话身份，不能当成两次独立执行")
    for label, report in zip(("原研究", "新研究"), reports):
        if report["blockers"]:
            blockers.append(f"{label}有 {len(report['blockers'])} 项证据缺口")
        if report["summary"]["critical_failures"]:
            warnings.append(label + "存在关键结果失败，不能用整体均值掩盖")
    synthetic = any(r["evidence_type"] == "synthetic" for r in reports)
    eligible = not blockers and not synthetic
    whole_same = not added and not removed and not changed
    summaries = [r["summary"] for r in reports]
    metrics = {"with_quality_change": delta(summaries[0]["with_score"], summaries[1]["with_score"]) if whole_same else None,
               "baseline_quality_change": delta(summaries[0]["without_score"], summaries[1]["without_score"]) if whole_same else None,
               "plugin_gain_change": delta(summaries[0]["quality_delta"], summaries[1]["quality_delta"]) if whole_same else None,
               "with_mean_cost_change_usd": delta(summaries[0]["with_cost_usd"], summaries[1]["with_cost_usd"]) if whole_same else None}
    def basis_set(report):
        return {basis for arm in report["cost_analysis"]["arms"].values()
                for basis, amount in arm["known_amounts_by_basis_usd"].items() if amount > 0}
    cost_comparable = eligible and all(r["cost_analysis"]["complete_category_coverage"] for r in reports) and basis_set(reports[0]) == basis_set(reports[1])
    if not cost_comparable:
        warnings.append("成本比较尚未就绪：需要两边类别完整、证据可比且费用来源口径一致；不能用估计与结算混比宣称节省")
    return {"schema_version": 1, "axis": axis, "status": "SIMULATION_ONLY" if synthetic else "COMPARABLE_DESCRIPTIVE" if eligible else "NOT_COMPARABLE",
            "comparison_eligible": eligible, "cost_comparison_eligible": cost_comparable,
            "differences": differences, "blockers": list(dict.fromkeys(blockers)),
            "warnings": warnings + ["相同任务并不证明因果效应；时间、提供商路由和模型别名可能漂移。", "插件贡献变化 = 新研究的有/无插件差值 - 原研究的差值；同时展示基线变化。"],
            "metrics": metrics, "added_cases": added, "removed_cases": removed, "changed_cases": changed, "cases": rows,
            "costs": {"before": reports[0]["cost_analysis"], "after": reports[1]["cost_analysis"]},
            "provenance": {"before": reports[0]["provenance"], "after": reports[1]["provenance"], "context": contexts},
            "claim_limit": "Descriptive matched-task comparison only; no causal attribution, independent validation or automatic upgrade recommendation"}
