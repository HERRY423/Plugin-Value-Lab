"""Turn recomputed paired evidence into narrow, local plugin-use guidance.

No service is contacted and no plugin installation or permission is changed.
These cards describe the submitted cases; hashes do not prove data authenticity.
"""
from __future__ import annotations

import copy
import html
import json
from pathlib import Path
from statistics import mean

from .core import ValidationError, evaluate, suite_digest


_EPSILON = 1e-12
_FAILURES = {"error", "timeout", "aborted"}
_STATUSES = {
    "TRIAL_GUIDANCE_ONLY": "仅供设计试用，不能据此推荐实际使用",
    "BOUNDED_LOCAL_GUIDANCE": "仅适用于已观察任务及固定条件的使用参考",
    "REVIEW_REQUIRED": "先复核缺失证据或回退，再作使用判断",
}


def _counts(runs):
    return {
        "planned_runs": len(runs),
        "observed_runs": sum(run["status"] != "missing" for run in runs),
        "failed_runs": sum(run["status"] in _FAILURES for run in runs),
        "missing_runs": sum(run["status"] == "missing" for run in runs),
        "skipped_runs": sum(run["status"] == "skipped" for run in runs),
        "runs_with_issues": sum(bool(run["issues"]) for run in runs),
    }


def _case_cost_delta(case):
    """Mean with cost minus mean without cost, never a sum of repetitions."""
    costs = {
        arm: [run["cost_usd"] for run in case["runs"] if run["arm"] == arm]
        for arm in ("with", "without")
    }
    if any(not values or None in values for values in costs.values()):
        return None
    return mean(costs["with"]) - mean(costs["without"])


def _scenario(case, prompt, reason, cost_delta):
    return {
        "case_id": case["id"], "prompt": prompt, "reason": reason,
        "quality_delta": case["delta"], "cost_delta_usd": cost_delta,
        "with_score": case["with_score"], "without_score": case["without_score"],
        "run_counts": _counts(case["runs"]),
    }


def build_usage_card(suite, records, lock=None, cost_ledger=None):
    """Recompute evaluation from inputs; a precomputed verdict is never accepted.

    All recommendations are descriptive and bound to exact inputs and conditions.
    Even user-declared external evidence cannot establish universal effectiveness.
    """
    report = evaluate(suite, records, lock, cost_ledger)
    policy, summary = report["policy"], report["summary"]
    synthetic = report["evidence_type"] == "synthetic"
    eligible = summary["comparison_eligible"] and not report["blockers"]
    non_regressed = report["verdict"] in {"PROMISING_LOCAL_SIGNAL", "NO_DEMONSTRATED_GAIN"}
    can_describe = eligible and not synthetic and non_regressed
    can_support = can_describe and report["verdict"] == "PROMISING_LOCAL_SIGNAL"
    objective = policy.get("objective", "quality")
    cost_required = objective == "efficiency" or policy["require_cost_saving"]
    prompts = {case["id"]: case["prompt"] for case in suite["cases"]}
    use_when, prefer_baseline, investigate = [], [], []

    for case in report["cases"]:
        delta, with_score = case["delta"], case["with_score"]
        cost_delta = _case_cost_delta(case)
        counts = _counts(case["runs"])
        critical_failed = any(
            grade["critical"] and grade["passed"] is not True
            for run in case["runs"] if run["arm"] == "with"
            for grade in run["grades"]
        )
        baseline_critical_failed = any(
            grade["critical"] and grade["passed"] is not True
            for run in case["runs"] if run["arm"] == "without"
            for grade in run["grades"]
        )
        complete = not counts["missing_runs"] and not counts["skipped_runs"] and not counts["runs_with_issues"]
        floor_ok = with_score is not None and with_score + _EPSILON >= policy["quality_floor"]
        regression_ok = delta is not None and delta + _EPSILON >= -policy["max_case_regression"]
        if objective == "efficiency":
            objective_ok = delta is not None and delta >= -_EPSILON
        else:
            objective_ok = delta is not None and delta > _EPSILON and delta + _EPSILON >= policy["min_quality_delta"]
        cost_ok = cost_delta is not None and (not cost_required or cost_delta < -_EPSILON)
        supported = can_support and complete and floor_ok and regression_ok and not critical_failed and objective_ok and cost_ok
        baseline_ok = (
            can_describe and complete and case["without_score"] is not None
            and case["without_score"] + _EPSILON >= policy["quality_floor"]
            and delta is not None and delta <= _EPSILON
            and not supported and not baseline_critical_failed
            # Under an efficiency goal, a cheaper plugin remains a useful signal;
            # do not turn failure of some other gate into a baseline recommendation.
            and (objective != "efficiency" or (cost_delta is not None and cost_delta >= -_EPSILON))
        )

        if supported:
            reason = (
                "本案例保持了基线质量、达到质量下限，并降低了完整记录的平均成本；可在相同条件下优先试用。"
                if objective == "efficiency" else
                "本案例达到预设质量增益和质量下限，未触发关键判据或回退限制，并满足本案例的成本条件；可在相同条件下优先试用。"
            )
            use_when.append(_scenario(case, prompts[case["id"]], reason, cost_delta))
        elif baseline_ok:
            reason = "基线在本案例已达到质量下限，未观察到插件带来更高结果质量；按本次目标可先使用基线。"
            if cost_delta is not None and cost_delta < -_EPSILON:
                reason += "插件成本较低，若实际目标是节省投入，应另按效率目标评估。"
            reason += "这不是永久停用或卸载建议。"
            prefer_baseline.append(_scenario(case, prompts[case["id"]], reason, cost_delta))

        reasons = []
        if synthetic:
            reasons.append("包含合成演示，不能转化为实际使用建议")
        elif not eligible:
            reasons.append("整项比较存在证据阻断，先补足并复核全套材料")
        elif not non_regressed:
            reasons.append("整项比较触发关键判据或回退限制，不能只挑选获益案例推荐")
        elif not supported and not baseline_ok:
            if not floor_ok:
                reasons.append("本案例的插件质量未达到下限或尚未知")
            if not objective_ok:
                reasons.append("本案例未达到所选目标的增益条件")
            if not cost_ok:
                reasons.append("本案例未满足成本条件或成本尚未知")
            if not regression_ok or critical_failed:
                reasons.append("本案例存在回退或关键判据问题")
            if not can_support:
                reasons.append("整项比较尚未显示预设增益，局部差异只能作为下一次试用线索")
        if baseline_critical_failed and not supported:
            reasons.append("基线未通过关键判据或关键结果尚未知，不能仅凭平均分达到下限就建议优先使用基线")
        if counts["failed_runs"] or counts["missing_runs"] or counts["skipped_runs"] or counts["runs_with_issues"]:
            reasons.append(
                f"保留 {counts['failed_runs']} 次失败、{counts['missing_runs']} 次缺失、"
                f"{counts['skipped_runs']} 次跳过和 {counts['runs_with_issues']} 次有问题的运行，不能删去后重算收益"
            )
        if reasons:
            investigate.append(_scenario(case, prompts[case["id"]], "；".join(reasons) + "。", cost_delta))

    if synthetic:
        status = "TRIAL_GUIDANCE_ONLY"
        next_steps = ["先冻结真实任务、两组相同的授权输入及比较条件，再收集真实运行和完整成本。", "合成案例只用于演练记录和判读流程。"]
    elif not can_describe:
        status = "REVIEW_REQUIRED"
        next_steps = ["逐项复核阻断、失败、缺失和关键回退；保留原记录，以明确修订后的新实验重新比较。", "问题解决前，不依据单个高分案例作使用推广。"]
    else:
        status = "BOUNDED_LOCAL_GUIDANCE"
        next_steps = ["将当前任务与原案例、插件版本和执行条件逐项比较；仅在相符时参考本卡。", "对范围外任务先作小规模配对试用，保留失败、成本和人工纠正记录。"]
    next_steps.append("安装、连接、权限或卸载需求交由宿主及 Plugin Management 处理；本卡不授予任何变更权限。")

    all_runs = [run for case in report["cases"] for run in case["runs"]]
    card = {
        "schema_version": 1, "type": "plugin_usage_card",
        "plugin": copy.deepcopy(report["plugin"]), "study_id": report["study_id"],
        "verdict": report["verdict"], "status": status,
        "scope": {
            "plugin": copy.deepcopy(report["plugin"]),
            "suite_sha256": report["provenance"]["suite_sha256"],
            "records_sha256": report["provenance"]["records_sha256"],
            "cost_ledger_sha256": report["provenance"].get("cost_ledger_sha256"),
            "conditions_sha256": suite_digest(suite["conditions"]),
            "conditions": copy.deepcopy(suite["conditions"]),
            "case_ids": [case["id"] for case in suite["cases"]],
            "objective": objective, "policy": copy.deepcopy(policy),
            "decision_scope": "仅限本次提交的具体任务及固定条件；不会自动外推到同类或新任务。",
        },
        "use_when": use_when, "prefer_baseline_when": prefer_baseline,
        "investigate": investigate, "next_steps": next_steps,
        "refresh_when": [
            "插件版本、配置、权限或依赖变化时重新核验。",
            "模型、宿主、工具、运行环境或资源预算变化时重新核验。",
            "任务、输入数据、数据访问范围、评分标准或质量与效率目标变化时重新比较。",
            "出现新的失败、回退、人工纠正或成本证据时复核；此清单不创建定时监控。",
        ],
        "source": {
            "evidence_type": report["evidence_type"],
            "evidence_level": "SIMULATION_ONLY" if synthetic else "SUBMITTED_PAIRED_OBSERVATIONS",
            "evaluation_recomputed": True, "comparison_eligible": eligible,
            "measured_verdict": report["measured_verdict"],
            "provenance": copy.deepcopy(report["provenance"]),
            "summary": copy.deepcopy(summary), "run_counts": _counts(all_runs),
            "blockers": list(report["blockers"]), "warnings": list(report["warnings"]),
            "claim_limits": copy.deepcopy(report["claim_limits"]),
            "authenticity_verified": False,
        },
        "limitations": [
            "使用卡是观察范围内的临时参考，不是插件的通用质量认证或长期有效承诺。",
            "来源、外部参与者、任务独立性与人工计时均为提交者声明；程序重算和哈希不证明数据真实性、实际执行或独立验证。",
            "本地增益信号不建立因果收益、外部适用性或科学与临床有效性；科研结论仍需领域证据和研究者判断。",
            "成本来自提交记录及人工费率折算；均值按每个案例每组的计划运行计算，估算费用不等于已结算支出。",
            "基线足够的观察不构成自动停用、卸载、扩权或修改其他插件的授权。",
            "原始任务文字保留在本地卡片中；向他人分享前应由用户检查其中的私有资料。",
        ],
    }
    return card


def _markdown(value):
    """Render user-supplied text literally, without links, images or raw HTML."""
    if value is None:
        return "未知"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = html.escape(str(value), quote=True)
    for character in ("\\", "`", "*", "_", "[", "]", "(", ")", "!", "|", "#", "~", "+", "-"):
        text = text.replace(character, "\\" + character)
    return " ".join(text.splitlines())


def _render_markdown(card):
    plugin, scope, source = card["plugin"], card["scope"], card["source"]
    lines = ["# 插件使用卡", "", f"**{_markdown(plugin['name'])} · {_markdown(plugin['version'])}**", "",
             f"研究：{_markdown(card['study_id'])}", "",
             f"状态：{_markdown(_STATUSES[card['status']])}", "",
             f"重新计算的结论：{_markdown(card['verdict'])}", "",
             "仅对记录中的具体任务提供条件性参考。评分不会产生安装、权限或卸载操作。", "",
             "## 适用范围", "",
             f"- 决策范围：{_markdown(scope['decision_scope'])}",
             f"- 目标：{_markdown(scope['objective'])}",
             f"- 固定条件：{_markdown(scope['conditions'])}",
             f"- 方案 SHA-256：{_markdown(scope['suite_sha256'])}",
             f"- 运行记录 SHA-256：{_markdown(scope['records_sha256'])}",
             f"- 条件 SHA-256：{_markdown(scope['conditions_sha256'])}", ""]
    for title, key, empty in [
        ("何时可优先试用", "use_when", "当前证据不能给出优先使用建议。"),
        ("何时基线可能已足够", "prefer_baseline_when", "尚无可支持的基线优先观察。"),
        ("先调查什么", "investigate", "未产生额外案例调查项；仍须遵守来源限制和适用范围。"),
    ]:
        lines += [f"## {title}", ""]
        for item in card[key]:
            lines += [f"### {_markdown(item['case_id'])}", "",
                      f"任务：{_markdown(item['prompt'])}", "",
                      _markdown(item["reason"]), "",
                      f"质量差（启用 − 未启用）：{_markdown(item['quality_delta'])}；平均成本差（USD）：{_markdown(item['cost_delta_usd'])}。", "",
                      f"运行计数：{_markdown(item['run_counts'])}", ""]
        if not card[key]:
            lines += [empty, ""]
    for title, items in [("接下来怎么做", card["next_steps"]), ("何时重新核验", card["refresh_when"]),
                         ("证据阻断", source["blockers"]), ("需要关注", source["warnings"]),
                         ("限制", card["limitations"])]:
        lines += [f"## {title}", ""]
        lines += [f"- {_markdown(item)}" for item in items] or ["未记录；不代表证据已获独立认证。"]
        lines += [""]
    lines += ["## 来源与完整性", "",
              f"- 证据类型：{_markdown(source['evidence_type'])}",
              f"- 证据层级：{_markdown(source['evidence_level'])}",
              f"- 运行计数：{_markdown(source['run_counts'])}",
              f"- 来源记录：{_markdown(source['provenance'])}", "",
              "来源真实性未获独立验证。完整字段保存在同目录的 `card.json`。", ""]
    return "\n".join(lines)


def write_usage_card(card, output_dir):
    """Write only explicit local card artifacts, refusing any existing contents."""
    if not isinstance(card, dict) or card.get("schema_version") != 1 or card.get("type") != "plugin_usage_card":
        raise ValidationError("Expected a plugin usage card built from suite and execution records")
    # Render everything before touching the filesystem, including strict JSON.
    json_text = json.dumps(card, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    markdown_text = _render_markdown(card)
    output = Path(output_dir)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValidationError("Usage card output directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    paths = {"json": output / "card.json", "md": output / "USAGE.md"}
    for key, content in (("json", json_text), ("md", markdown_text)):
        try:
            with paths[key].open("x", encoding="utf-8") as stream:
                stream.write(content)
        except FileExistsError as exc:
            raise ValidationError("Usage card artifacts already exist; create a new revision") from exc
    return {key: str(path) for key, path in paths.items()}
