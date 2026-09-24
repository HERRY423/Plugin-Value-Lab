"""Scope-matched, descriptive trial guidance from recomputed complete studies.

Never infer noninferiority from an insignificant gain. Worst observed loss is
only a finite-sample check, not a confidence bound on future loss.
"""
from pathlib import Path
from statistics import mean
from .core import ValidationError, evaluate, suite_digest, write_json
from .comparison import compare_studies


def validate_decision_policy(policy):
    from .core import _number, _text
    decision = policy.get("use_decision")
    if decision is None:
        return
    if not isinstance(decision, dict) or set(decision) != {"version", "scope_rationale", "minimum_gain", "maximum_quality_loss", "maximum_cost_increase_usd", "maximum_failure_rate", "require_settled_costs"}:
        raise ValidationError("use_decision requires the complete prospective decision policy")
    if type(decision["version"]) is not int or decision["version"] != 1 or type(decision["require_settled_costs"]) is not bool:
        raise ValidationError("Invalid use_decision version or settlement requirement")
    _text(decision["scope_rationale"], "decision scope rationale")
    for field in ("minimum_gain", "maximum_quality_loss", "maximum_failure_rate"):
        _number(decision[field], field, 0, 1)
    if decision["minimum_gain"] <= 0:
        raise ValidationError("A positive minimum gain must be selected before observation")
    _number(decision["maximum_cost_increase_usd"], "maximum_cost_increase_usd")


def _target_matches(target, suite, context):
    if not isinstance(target, dict) or set(target) != {"plugin", "plugin_sha256", "conditions", "cases"}:
        raise ValidationError("Target requires exact plugin, content digest, conditions and intended case definitions")
    reasons = []
    for field, expected in (("plugin", suite["plugin"]), ("plugin_sha256", context.get("plugin_sha256")), ("conditions", suite["conditions"])):
        if suite_digest(target[field]) != suite_digest(expected):
            reasons.append("Target differs from tested " + field)
    cases = target["cases"]
    if not isinstance(cases, list) or not cases or any(not isinstance(c, dict) or not isinstance(c.get("id"), str) for c in cases):
        raise ValidationError("Target cases must be nonempty complete case definitions")
    if len({c["id"] for c in cases}) != len(cases):
        raise ValidationError("Duplicate target cases")
    tested = {c["id"]: c for c in suite["cases"]}
    for case in cases:
        if case["id"] not in tested or suite_digest(case) != suite_digest(tested[case["id"]]):
            reasons.append("Untested task, input, rubric or family: " + case["id"])
    return reasons


def _case_observations(case):
    arms = {}
    index = {(r["repetition"], r["arm"]): r for r in case["runs"]}
    losses = []
    for arm in ("with", "without"):
        rows = [r for r in case["runs"] if r["arm"] == arm]
        scores, costs = [r["score"] for r in rows], [r["cost_usd"] for r in rows]
        arms[arm] = {"mean_quality": mean(scores) if scores and None not in scores else None,
                     "minimum_observed_quality": min(scores) if scores and None not in scores else None,
                     "mean_cost_usd": mean(costs) if costs and None not in costs else None,
                     "failure_rate": sum(r["status"] in ("error", "timeout", "aborted") for r in rows) / len(rows) if rows else None,
                     "critical_checks_passed": all(g["passed"] is True for r in rows for g in r["grades"] if g["critical"]),
                     "complete": bool(rows) and all(r["status"] not in ("missing", "skipped") and not r["issues"] and r["score"] is not None for r in rows)}
    for rep in {r["repetition"] for r in case["runs"]}:
        a, b = index.get((rep, "with")), index.get((rep, "without"))
        if a is not None and b is not None and a["score"] is not None and b["score"] is not None:
            losses.append(a["score"] - b["score"])
    return {"arms": arms, "plugin_gain": case["delta"],
            "worst_observed_loss_if_baseline": max(losses) if losses and len(losses) * 2 == len(case["runs"]) else None,
            "scope": "Observed repetitions only; not a bound on future risk or proof of noninferiority"}


def conditional_guidance(before, after, target, *, axis, artifact_roots=None, verifier_roots=None):
    comparison = compare_studies(before, after, axis=axis, artifact_roots=artifact_roots, verifier_roots=verifier_roots)
    suite = after["suite"]
    policy = suite["policy"].get("use_decision")
    if policy is None:
        raise ValidationError("No prospectively frozen use_decision policy; do not invent thresholds from observed results")
    validate_decision_policy(suite["policy"])
    target_blockers = _target_matches(target, suite, after.get("context") or {})
    roots = artifact_roots or (None, None)
    scorers = verifier_roots or (None, None)
    report = evaluate(suite, after["records"], after["lock"], after.get("cost_ledger"), artifact_root=roots[1], verifier_root=scorers[1])
    settled = report["cost_analysis"]["cash_evidence"]["settlement_references_complete"]
    both_settled = all(comparison["costs"][side]["cash_evidence"]["settlement_references_complete"] for side in ("before", "after"))
    cost_ready = comparison["cost_comparison_eligible"] and (not policy["require_settled_costs"] or both_settled)
    eligible = comparison["comparison_eligible"] and not target_blockers
    target_ids = {c["id"] for c in target["cases"]}
    rows = []
    changes = {c["case_id"]: c for c in comparison["cases"]}
    for case in report["cases"]:
        obs = _case_observations(case)
        w, b = obs["arms"]["with"], obs["arms"]["without"]
        status, reasons = "REVIEW_REQUIRED", []
        def quality_ready(arm):
            return (arm["complete"] and arm["critical_checks_passed"] and arm["minimum_observed_quality"] is not None
                    and arm["minimum_observed_quality"] >= suite["policy"]["quality_floor"]
                    and arm["failure_rate"] <= policy["maximum_failure_rate"])
        if not eligible:
            reasons.append("比较或目标范围不满足条件，不能转换为实际使用建议。")
        elif not cost_ready:
            reasons.append("缺少完整且同口径成本，或未满足预设结算要求。")
        elif not w["complete"] or not b["complete"]:
            reasons.append("保留失败与未知，先补齐观测。")
        elif (quality_ready(w) and obs["plugin_gain"] is not None and obs["plugin_gain"] >= policy["minimum_gain"]
              and w["mean_cost_usd"] - b["mean_cost_usd"] <= policy["maximum_cost_increase_usd"]):
            status = "PLUGIN_TRIAL_WITH_REVIEW"
            reasons.append("当前任务的观察质量、失败率和额外成本满足预先设定界限，可在同条件下优先试用并保留复核。")
        elif (quality_ready(b) and obs["worst_observed_loss_if_baseline"] is not None
              and obs["worst_observed_loss_if_baseline"] <= policy["maximum_quality_loss"]
              and b["mean_cost_usd"] - w["mean_cost_usd"] <= policy["maximum_cost_increase_usd"]):
            status = "BASELINE_TRIAL_WITH_REVIEW"
            reasons.append("基线在全部已观察重复中达到下限，观察到的最大质量损失和额外成本在预设界限内；可试用基线。此结果不证明未来非劣效，也不建议自动卸载。")
        else:
            reasons.append("未满足质量、成本或风险界限；小差值或未显示增益本身不是退出依据。")
        change = changes[case["id"]]
        trend = "NO_ATTRIBUTABLE_PATTERN"
        if eligible and change["plugin_gain_change"] is not None and change["plugin_gain_change"] < -1e-12:
            if change["baseline_change"] > 1e-12 and change["with_change"] >= -1e-12:
                trend = "BASELINE_IMPROVED_MARGIN_NARROWED"
            elif change["with_change"] < -1e-12:
                trend = "WITH_PLUGIN_OUTCOME_DECLINED"
        rows.append({"case_id": case["id"], "family": case["cluster"], "target_requested": case["id"] in target_ids,
                     "status": status, "reasons": reasons, "observations": obs, "comparison": change,
                     "trend": trend, "trend_limit": "Descriptive pattern; the causal reason for a change is not established"})
    return {"format": "pvl-conditional-guidance-1", "status": "SIMULATION_ONLY" if comparison["status"] == "SIMULATION_ONLY"
            else "OUT_OF_SCOPE" if target_blockers else "BOUNDED_LOCAL_TRIAL_GUIDANCE" if eligible and cost_ready else "REVIEW_REQUIRED",
            "target": target, "policy": policy, "comparison": comparison, "target_blockers": target_blockers,
            "cases": rows, "scope": {"tested_conditions": suite["conditions"], "tested_plugin": suite["plugin"],
                                       "tested_plugin_sha256": after.get("context", {}).get("plugin_sha256"),
                                       "suite_sha256": suite_digest(suite), "records_sha256": suite_digest(after["records"]),
                                       "case_ids": [c["id"] for c in suite["cases"]]},
            "cash_savings": "SUBMITTED_SETTLEMENT_REFERENCES_COMPLETE" if settled else "NOT_ESTABLISHED",
            "new_data_generalization": "NOT_TESTED", "external_replication": "NOT_ESTABLISHED",
            "automatic_actions": False, "model_calls": 0,
            "refresh_when": ["任务、输入、判据、插件内容、宿主或模型版本变化", "出现失败、异常输出或新的反对证据", "成本或预设风险边界发生变化"],
            "limitations": ["这是条件明确的局部试用建议，不是确认性非劣效或普遍有效证明。", "所有原任务与负结果继续展示，选择目标不会删除不利观察。",
                            "旧观察重放不增加样本量；外部身份与实际采用不能由哈希或反馈文本认证。", "不会自动启停、卸载插件或扩大权限。"]}


def write_guidance(result, output):
    from .usage import _markdown
    output = Path(output)
    if output.exists():
        raise ValidationError("Preserve previous guidance; use a new output directory")
    lines = ["# 条件化插件使用建议", "", "状态：" + _markdown(result["status"]), "",
             "只描述已测试任务和固定条件；不自动安装、关闭或卸载插件。", "",
             "## 适用条件", "", _markdown(result["scope"]), "",
             "## 逐场景建议", ""]
    labels = {"PLUGIN_TRIAL_WITH_REVIEW": "可优先试用插件，保留复核", "BASELINE_TRIAL_WITH_REVIEW": "可试用基线，保留复核", "REVIEW_REQUIRED": "先复核"}
    for row in result["cases"]:
        lines += ["### " + _markdown(row["case_id"]), "", labels[row["status"]] + "：" + " ".join(row["reasons"]),
                  "", "当前目标包含此任务：" + str(row["target_requested"]), "",
                  "描述性变化：" + _markdown(row["trend"]), "", "证据：" + _markdown(row["observations"]), ""]
    lines += ["## 不适用与复核事项", ""]
    lines += ["- " + _markdown(v) for v in result["target_blockers"] + result["comparison"]["blockers"] + result["refresh_when"] + result["limitations"]]
    output.mkdir(parents=True)
    write_json(output / "guidance.json", result)
    (output / "GUIDANCE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(output / "guidance.json"), "md": str(output / "GUIDANCE.md")}
