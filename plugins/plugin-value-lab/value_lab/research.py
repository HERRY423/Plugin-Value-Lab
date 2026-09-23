"""Local validation of Agent-authored research diagnosis and bounded next steps.

This module does not infer scientific facts from prose. The host Agent supplies
contextual reasoning; this engine makes missing evidence, assumptions, resource
limits and changes inspectable. Nothing here searches, installs, spends or runs.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext
import json
import math
from pathlib import Path
import re

from .core import ValidationError, suite_digest, write_json


DIMENSIONS = {
    "question": ("问题与决策", "哪一个具体判断会因这项研究而改变，什么结果会改变当前判断？"),
    "data": ("资料与样本", "现有资料来自哪些对象与采样过程，哪些关键对象或条件还没有覆盖？"),
    "measurement": ("测量与构念", "当前测量是否直接对应研究对象，需要什么校准或正交测量才能排除代理偏差？"),
    "design": ("设计与对照", "哪个对照或设计变化能够区分目标解释与混杂、选择或批次效应？"),
    "alternatives": ("竞争解释", "目前最强的替代解释是什么，什么观察能够区分它与首选解释？"),
    "robustness": ("稳健性与失败条件", "哪一种合理的参数、数据排除或分析选择变化最可能使结论失效？"),
    "generalization": ("适用边界", "结论计划适用于哪些未观察人群、条件或场景，外推需要补充什么证据？"),
    "reproducibility": ("可复核与复现", "另一位研究者能否用原始输入、环境和决策记录重建结果？"),
    "resources": ("资源与可行性", "哪些资料授权、人员、时间、预算或能力依赖会阻碍下一项区分性验证？"),
    "impact": ("贡献与后续决策", "相对于当前知识，这项研究具体解决哪个不确定性，什么阴性结果仍有信息价值？"),
}
_EVIDENCE = {"observed", "reported", "hypothesis", "unknown", "contradicted"}
_COVERAGE = {"covered", "partial", "missing", "unknown", "not_applicable"}
_STATES = {"proposed", "accepted", "deferred", "rejected"}
_KINDS = {"knowledge", "evidence", "method", "capability", "resource"}
_LIMITS = [
    "这是研究诊断与行动提案；没有执行实验、搜索文献、核实来源、安装插件或支付费用。",
    "背景解释、证据状态和方向由用户或宿主 Agent 提供；本地引擎验证结构与约束，不从文本自动发现科学事实。",
    "observed 和 reported 均是提交者的状态声明；引用绑定和哈希不能证明来源真实性、独立性或科学有效性。",
    "优先级 = 影响 × 不确定性 ÷ 工作量，是可修改的排序启发式；不是成功概率、真实价值或预期信息增益的测量。",
    "预算与时间是声明的估计；未提供的数值保持未知。计划不等于执行授权，依赖完成后仍需核验。",
    "方向变化与覆盖状态变化不证明缺口关闭、发现具有新颖性或生物学结论成立。",
]


def _object(value, where, allowed, required=()):
    if not isinstance(value, dict):
        raise ValidationError(f"{where} must be an object")
    if any(not isinstance(k, str) for k in value):
        raise ValidationError(f"{where} keys must be strings")
    extra = set(value) - set(allowed)
    missing = set(required) - set(value)
    if extra:
        raise ValidationError(f"{where}: unknown fields: {', '.join(sorted(extra))}")
    if missing:
        raise ValidationError(f"{where}: missing fields: {', '.join(sorted(missing))}")
    return value


def _text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{where} must be nonempty text")
    if len(value) > 100_000:
        raise ValidationError(f"{where} is too long")
    return value


def _identifier(value, where):
    _text(value, where)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}", value):
        raise ValidationError(f"{where} must be a safe identifier")
    return value


def _choice(value, choices, where):
    if not isinstance(value, str) or value not in choices:
        raise ValidationError(f"{where} must be one of {', '.join(sorted(choices))}")
    return value


def _number(value, where, nullable=False):
    if value is None and nullable:
        return
    try:
        valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        raise ValidationError(f"{where} must be a finite nonnegative number" + (" or null" if nullable else ""))


def _list(value, where, limit=1000):
    if not isinstance(value, list) or len(value) > limit:
        raise ValidationError(f"{where} must be a list of at most {limit} items")
    return value


def _refs(value, identifiers, where):
    _list(value, where)
    seen = set()
    for ref in value:
        _identifier(ref, where)
        if ref not in identifiers:
            raise ValidationError(f"{where}: unknown reference {ref}")
        if ref in seen:
            raise ValidationError(f"{where}: duplicate reference {ref}")
        seen.add(ref)


def _validate(context):
    _object(context, "context", {"schema_version", "evidence_type", "task", "evidence", "dimensions", "directions", "constraints", "revision_note"}, {"schema_version", "task"})
    if type(context["schema_version"]) is not int or context["schema_version"] != 1:
        raise ValidationError("context.schema_version must be 1")
    if "evidence_type" in context:
        _choice(context["evidence_type"], {"synthetic", "local"}, "evidence_type")
    task = _object(context["task"], "task", {"question", "background", "decision", "domain"}, {"question", "background"})
    for key, value in task.items():
        _text(value, f"task.{key}")
    if "revision_note" in context:
        _text(context["revision_note"], "revision_note")
    evidence = _list(context.get("evidence", []), "evidence")
    evidence_ids = set()
    for i, item in enumerate(evidence):
        where = f"evidence[{i}]"
        _object(item, where, {"id", "summary", "source", "status"}, {"id", "summary", "source", "status"})
        ident = _identifier(item["id"], where + ".id")
        if ident in evidence_ids:
            raise ValidationError(f"Duplicate evidence ID: {ident}")
        evidence_ids.add(ident)
        _text(item["summary"], where + ".summary")
        _text(item["source"], where + ".source")
        _choice(item["status"], _EVIDENCE, where + ".status")
    dims = _object(context.get("dimensions", {}), "dimensions", DIMENSIONS)
    for dimension, item in dims.items():
        where = f"dimensions.{dimension}"
        _object(item, where, {"status", "rationale", "evidence_ids"}, {"status", "rationale", "evidence_ids"})
        _choice(item["status"], _COVERAGE, where + ".status")
        _text(item["rationale"], where + ".rationale")
        _refs(item["evidence_ids"], evidence_ids, where + ".evidence_ids")
    directions = _list(context.get("directions", []), "directions", 200)
    direction_ids = set()
    required = {"id", "title", "gap", "kind", "dimension", "why_now", "evidence_ids", "alternative_explanation", "next_test", "success_signal", "stop_signal", "depends_on", "impact", "uncertainty", "effort", "cost_usd", "hours"}
    for i, item in enumerate(directions):
        where = f"directions[{i}]"
        _object(item, where, required | {"capability_query", "status"}, required)
        ident = _identifier(item["id"], where + ".id")
        if ident in direction_ids:
            raise ValidationError(f"Duplicate direction ID: {ident}")
        direction_ids.add(ident)
        for key in ("title", "gap", "why_now", "alternative_explanation", "next_test", "success_signal", "stop_signal"):
            _text(item[key], where + "." + key)
        _choice(item["kind"], _KINDS, where + ".kind")
        _choice(item["dimension"], DIMENSIONS, where + ".dimension")
        _choice(item.get("status", "proposed"), _STATES, where + ".status")
        _refs(item["evidence_ids"], evidence_ids, where + ".evidence_ids")
        for key in ("impact", "uncertainty", "effort"):
            if type(item[key]) is not int or not 1 <= item[key] <= 5:
                raise ValidationError(f"{where}.{key} must be an integer in 1..5")
        for key in ("cost_usd", "hours"):
            _number(item[key], where + "." + key, nullable=True)
        if "capability_query" in item:
            _text(item["capability_query"], where + ".capability_query")
            if item["kind"] != "capability":
                raise ValidationError(f"{where}.capability_query is only valid for capability directions")
            query = item["capability_query"]
            if len(query) > 160 or any(char in query for char in "\r\n\t"):
                raise ValidationError(f"{where}.capability_query must be a single-line public capability query of at most 160 characters")
            if re.search(r"(?i)(?:[a-z]:[\\/]|https?://|file:|\\\\|(?:^|\s)(?:~/|\.{1,2}/|/)[^\s]+)", query):
                raise ValidationError(f"{where}.capability_query must not contain URLs or local paths; use public capability keywords")
    for item in directions:
        _refs(item["depends_on"], direction_ids, f"directions.{item['id']}.depends_on")
        if item["id"] in item["depends_on"]:
            raise ValidationError(f"Direction {item['id']} cannot depend on itself")
    by_id = {item["id"]: item for item in directions}
    visiting, visited = set(), set()

    def visit(ident):
        if ident in visiting:
            raise ValidationError(f"Direction dependencies contain a cycle at {ident}")
        if ident in visited:
            return
        visiting.add(ident)
        for dep in by_id[ident]["depends_on"]:
            visit(dep)
        visiting.remove(ident)
        visited.add(ident)

    for ident in by_id:
        visit(ident)
    constraints = _object(context.get("constraints", {}), "constraints", {"budget_usd", "hours_available", "max_next_actions"})
    for key in ("budget_usd", "hours_available"):
        if key in constraints:
            _number(constraints[key], "constraints." + key, nullable=True)
    if "max_next_actions" in constraints and (type(constraints["max_next_actions"]) is not int or not 1 <= constraints["max_next_actions"] <= 5):
        raise ValidationError("constraints.max_next_actions must be an integer in 1..5")


def _support(refs, evidence):
    statuses = [evidence[ref]["status"] for ref in refs]
    if "contradicted" in statuses:
        return "contested"
    if any(status in {"observed", "reported"} for status in statuses):
        return "declared_support"
    return "unsupported"


def diagnose_research(context):
    """Validate context and return an auditable, non-executing research plan."""
    _validate(context)
    context = deepcopy(context)
    evidence = {item["id"]: item for item in context.get("evidence", [])}
    dimensions, gaps = [], []
    for key, (label, question) in DIMENSIONS.items():
        supplied = context.get("dimensions", {}).get(key)
        state = supplied["status"] if supplied else "unknown"
        refs = supplied["evidence_ids"] if supplied else []
        support = _support(refs, evidence)
        effective = state
        if support == "contested":
            effective = "contested"
        elif state == "covered" and support == "unsupported":
            effective = "unsupported"
        row = {"dimension": key, "label": label, "declared_status": state, "effective_status": effective,
               "support_status": support, "rationale": supplied["rationale"] if supplied else "尚未提交该方向的分析。",
               "evidence_ids": list(refs), "question": question, "source": "submitted" if supplied else "missing_context"}
        dimensions.append(row)
        if effective not in {"covered", "not_applicable"}:
            gaps.append(deepcopy(row))
    submitted = context.get("directions", [])
    directions = []
    for item in submitted:
        row = deepcopy(item)
        row.setdefault("status", "proposed")
        row["priority_score"] = round(item["impact"] * item["uncertainty"] / item["effort"], 6)
        row["priority_formula"] = "impact * uncertainty / effort"
        row["support_status"] = _support(item["evidence_ids"], evidence)
        row["evidence_states"] = {ref: evidence[ref]["status"] for ref in item["evidence_ids"]}
        row["disposition"] = "pending"
        row["reasons"] = []
        row["execution_authorized"] = False
        if row["status"] in {"rejected", "deferred"}:
            row["disposition"] = row["status"]
            row["reasons"].append("尊重已声明的方向处置状态。")
        directions.append(row)
    directions.sort(key=lambda row: (-row["priority_score"], row["id"]))
    for i, row in enumerate(directions, 1):
        row["priority_rank"] = i
    by_id = {row["id"]: row for row in directions}
    # Block transitively on rejected/deferred dependencies. Accepted means the
    # proposal was accepted, not that its prerequisite experiment succeeded.
    changed = True
    while changed:
        changed = False
        for row in directions:
            if row["disposition"] != "pending":
                continue
            blocked = [dep for dep in row["depends_on"] if by_id[dep]["disposition"] in {"rejected", "deferred", "blocked_dependency"}]
            if blocked:
                row["disposition"] = "blocked_dependency"
                row["reasons"].append("前置方向尚不可安排：" + ", ".join(blocked))
                changed = True
    constraints = context.get("constraints", {})
    budget, hours = constraints.get("budget_usd"), constraints.get("hours_available")
    maximum = constraints.get("max_next_actions", 3)
    selected, chosen = [], set()
    used_cost, used_hours = Decimal(0), Decimal(0)
    unknown_cost, unknown_hours = False, False
    while len(selected) < maximum:
        candidates = [row for row in directions if row["disposition"] == "pending" and all(dep in chosen for dep in row["depends_on"])]
        if not candidates:
            break
        for row in candidates:
            if len(selected) >= maximum:
                break
            need_estimate = (budget is not None and row["cost_usd"] is None) or (hours is not None and row["hours"] is None)
            if need_estimate:
                row["disposition"] = "needs_estimate"
                row["reasons"].append("已声明资源上限，但本方向的费用或时间仍未知。")
                continue
            # Cover the full finite binary-float exponent range plus large
            # accepted integers, without decimal-context rounding under caps.
            with localcontext() as decimal_context:
                decimal_context.prec = 700
                cost_sum = used_cost + Decimal(str(row["cost_usd"] or 0))
                hour_sum = used_hours + Decimal(str(row["hours"] or 0))
            if not math.isfinite(cost_sum) or not math.isfinite(hour_sum):
                raise ValidationError("Selected direction resource totals must be finite")
            if (budget is not None and cost_sum > Decimal(str(budget))) or (hours is not None and hour_sum > Decimal(str(hours))):
                row["disposition"] = "over_budget"
                row["reasons"].append("加入当前行动批次会超过累计费用或时间上限。")
                continue
            row["disposition"] = "next_action"
            row["sequence"] = len(selected) + 1
            row["readiness"] = "after_dependency_verification" if row["depends_on"] else "proposal_only"
            row["reasons"].append("按启发式优先级及依赖、累计资源约束安排；执行前仍需研究者判断。")
            if row["depends_on"]:
                row["reasons"].append("前置方向仅已列入本计划；未声明完成，也未证明其成功信号成立。")
            chosen.add(row["id"])
            selected.append(row)
            used_cost, used_hours = cost_sum, hour_sum
            unknown_cost = unknown_cost or row["cost_usd"] is None
            unknown_hours = unknown_hours or row["hours"] is None
            # Reconsider newly available dependents against remaining roots.
            break
    for row in directions:
        if row["disposition"] != "pending":
            continue
        unmet = [dep for dep in row["depends_on"] if dep not in chosen]
        row["disposition"] = "waiting_dependency" if unmet else "not_selected"
        row["reasons"].append("前置方向未列入本次行动：" + ", ".join(unmet) if unmet else "已达到本次行动数量上限，保留待下一次安排。")
    questions = []
    if not context["task"].get("decision"):
        questions.append("这项研究要支持哪个具体决策，什么结果会让你改变当前选择？")
    if any(row["disposition"] == "needs_estimate" for row in directions):
        questions.append("受预算或时间上限约束的优先方向，需要补充哪些费用与时间估计？")
    addressed = {row["dimension"] for row in directions if row["status"] not in {"rejected", "deferred"}}
    order = {"contested": 0, "unsupported": 1, "missing": 2, "unknown": 3, "partial": 4}
    for gap in sorted(gaps, key=lambda row: (row["dimension"] in addressed, order.get(row["effective_status"], 5), list(DIMENSIONS).index(row["dimension"]))):
        if gap["question"] not in questions:
            questions.append(gap["question"])
    if not directions and not gaps:
        questions.append("当前覆盖声明之下，最可能改变结论的失败模式或新的区分性检验是什么？")
    handoffs = [{"direction_id": row["id"], "capability_query": row["capability_query"],
                 "disposition": row["disposition"],
                 "authority": "DISCOVERY_PROPOSAL_ONLY", "check_existing_capabilities_first": True}
                for row in directions if row["kind"] == "capability" and "capability_query" in row and row["status"] not in {"rejected", "deferred"}]
    return {
        "schema_version": 1, "status": "RESEARCH_DIAGNOSIS_ONLY", "scientific_authorization": "NONE",
        "evidence_type": context.get("evidence_type", "undeclared"),
        "context": context, "context_sha256": suite_digest(context),
        "dimensions": dimensions, "gaps": gaps, "directions": directions, "next_actions": deepcopy(selected),
        "questions": questions[:3],
        "priority_policy": {"formula": "impact * uncertainty / effort", "input_scale": "integers 1..5",
                            "meaning": "Uncalibrated planning heuristic; uncertainty is not information gain.",
                            "selection": "Descending score among dependency-ready proposals; cumulative caps; ID breaks ties.",
                            "optimality": "Greedy bounded plan, not an optimal portfolio."},
        "resource_plan": {"budget_usd": budget, "hours_available": hours, "max_next_actions": maximum,
                          "known_cost_usd": float(used_cost), "known_hours": float(used_hours),
                          "total_cost_usd": None if unknown_cost else float(used_cost),
                          "total_hours": None if unknown_hours else float(used_hours),
                          "unknown_cost": unknown_cost, "unknown_hours": unknown_hours,
                          "budget_verified": False, "execution_authorized": False},
        "handoff": {"owner": "plugin-management", "status": "CAPABILITY_DISCOVERY_PROPOSAL" if handoffs else "NO_CAPABILITY_REQUEST",
                    "requests": handoffs, "automatic_install": False, "automatic_transmission": False,
                    "requires_host_redaction_review": True,
                    "instruction": "先核对已有原生与已连接能力。只为具体能力缺口搜索；公开查询中移除私有任务、路径与资料。不把知识或证据不足等同于缺插件。"},
        "limits": list(_LIMITS),
    }


def compare_research(before_context, after_context):
    """Compare declared revisions without interpreting changes as gap closure."""
    before, after = diagnose_research(before_context), diagnose_research(after_context)
    before_e = {row["id"]: row for row in before["context"].get("evidence", [])}
    after_e = {row["id"]: row for row in after["context"].get("evidence", [])}
    before_d = {row["id"]: row for row in before["context"].get("directions", [])}
    after_d = {row["id"]: row for row in after["context"].get("directions", [])}

    def diff(first, second):
        return {"added": sorted(second.keys() - first.keys()), "removed": sorted(first.keys() - second.keys()),
                "changed": sorted(key for key in first.keys() & second.keys() if first[key] != second[key]),
                "unchanged": sorted(key for key in first.keys() & second.keys() if first[key] == second[key])}

    changes = []
    for old, new in zip(before["dimensions"], after["dimensions"]):
        if old != new:
            changes.append({"dimension": old["dimension"], "before": old, "after": new,
                            "interpretation": "Submitted diagnosis changed; gap closure and evidence independence are not established."})
    task_changed = before_context["task"] != after_context["task"]
    old_priorities = {row["id"]: row for row in before["directions"]}
    priority_changes = []
    for row in after["directions"]:
        if row["id"] not in old_priorities:
            continue
        old = old_priorities[row["id"]]
        if any(old[key] != row[key] for key in ("priority_score", "priority_rank", "disposition")):
            priority_changes.append({"id": row["id"], "before_score": old["priority_score"], "after_score": row["priority_score"],
                                     "before_rank": old["priority_rank"], "after_rank": row["priority_rank"],
                                     "before_disposition": old["disposition"], "after_disposition": row["disposition"]})
    return {"schema_version": 1, "status": "RESEARCH_REVISION_COMPARISON_ONLY", "scientific_authorization": "NONE",
            "before_sha256": before["context_sha256"], "after_sha256": after["context_sha256"],
            "task_changed": task_changed, "comparability": "CONTEXT_CHANGED" if task_changed else "SAME_DECLARED_TASK",
            "before_evidence_type": before["evidence_type"], "after_evidence_type": after["evidence_type"],
            "evidence_type_changed": before["evidence_type"] != after["evidence_type"],
            "task_change": {"before": before["context"]["task"], "after": after["context"]["task"]} if task_changed else None,
            "evidence_changes": diff(before_e, after_e), "direction_changes": diff(before_d, after_d),
            "dimension_changes": changes, "priority_changes": priority_changes,
            "constraints_changed": before_context.get("constraints", {}) != after_context.get("constraints", {}),
            "before_gap_count": len(before["gaps"]), "after_gap_count": len(after["gaps"]),
            "remaining_gaps": after["gaps"], "next_actions": after["next_actions"],
            "closure_verified": False, "new_evidence_independently_verified": False,
            "limits": list(_LIMITS) + ["缺口数量减少可能来自口径、适用性或状态声明改变，不是研究进步的独立测量。"]}


def assess_research_update(context, update):
    """Locate decisions to revisit after a *declared* result, without changing the plan.

    The submitted result is not verified here. In particular, a result matching
    a success signal never marks a direction complete or unlocks dependents.
    """
    plan = diagnose_research(context)
    _object(update, "update", {"direction_id", "result", "source", "signal", "interpretation", "reviewer"},
            {"direction_id", "result", "source", "signal", "interpretation"})
    direction_id = _identifier(update["direction_id"], "update.direction_id")
    directions = {row["id"]: row for row in plan["directions"]}
    if direction_id not in directions:
        raise ValidationError(f"update.direction_id: unknown direction {direction_id}")
    for field in ("result", "source", "interpretation"):
        _text(update[field], "update." + field)
    if "reviewer" in update:
        _text(update["reviewer"], "update.reviewer")
    _choice(update["signal"], {"supports_favored", "supports_rival", "inconclusive", "conflicting"}, "update.signal")
    direct = directions[direction_id]
    affected = {direction_id}
    # Transitive dependents can be affected even when the initial proposal was
    # merely selected in the same planning batch.
    changed = True
    while changed:
        old_count = len(affected)
        affected.update(row["id"] for row in directions.values() if set(row["depends_on"]) & affected)
        changed = len(affected) != old_count
    shared = {row["id"] for row in directions.values()
              if set(row["evidence_ids"]) & set(direct["evidence_ids"])}
    affected.update(shared)
    prompts = [
        "核对提交的结果及来源，记录它与事先写下的成功、停止信号是否真正相符。",
        "让研究者审阅首选解释、竞争解释和不确定结果；不要自动更改方向状态。",
        "修订受影响方向的证据引用、依赖、资源估计与下一步，并保留旧上下文。",
    ]
    if update["signal"] in {"supports_rival", "conflicting"}:
        prompts.append("重点审阅停止或缩小结论的条件，并检查是否应撤回下游提案。")
    if update["signal"] == "inconclusive":
        prompts.append("明确是哪一项测量或设计限制使结果无法区分两种解释。")
    return {"schema_version": 1, "status": "REASSESSMENT_REQUIRED", "scientific_authorization": "NONE",
            "context_sha256": plan["context_sha256"], "update": deepcopy(update),
            "update_sha256": suite_digest(update), "direction": deepcopy(direct),
            "affected_direction_ids": sorted(affected), "dependent_direction_ids": sorted(affected - shared - {direction_id}),
            "shared_evidence_direction_ids": sorted(shared - {direction_id}),
            "review_questions": prompts, "context_revised": False, "result_verified": False,
            "direction_completed": False, "dependencies_unlocked": False,
            "limits": list(_LIMITS) + ["信号分类、结果与解释均为提交者声明；本入口只定位需复核的方向，不确认结果符合预设判据。"]}


def _md(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("[", "\\[").replace("]", "\\]").replace("`", "\\`").replace("|", "\\|").replace("\n", " ")


def write_research(plan, output):
    """Write a recomputed plan to an absent/empty folder, refusing overwrites."""
    if not isinstance(plan, dict) or "context" not in plan:
        raise ValidationError("Research plan must include validated context")
    expected = diagnose_research(plan["context"])
    if suite_digest(plan) != suite_digest(expected):
        raise ValidationError("Research plan does not match its recomputed context")
    root = Path(output)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValidationError("Research output directory must be absent or empty")
    json.dumps(plan, allow_nan=False)
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "research-plan.json", plan)
    lines = ["# 研究方向诊断", "", f"任务：{_md(plan['context']['task']['question'])}", "",
             "状态：研究诊断提案；科学授权 NONE。", "", f"证据类型声明：{_md(plan['evidence_type'])}（未独立核实）。", "", f"上下文指纹：{plan['context_sha256']}", "",
             "## 缺口地图", "", "| 方向 | 声明状态 | 校验后状态 | 依据 |", "| --- | --- | --- | --- |"]
    for row in plan["dimensions"]:
        lines.append(f"| {_md(row['label'])} | {_md(row['declared_status'])} | {_md(row['effective_status'])} | {_md(row['rationale'])} |")
    lines.extend(["", "## 下一步提案", "", "排序依据：影响 × 不确定性 ÷ 工作量；非概率或已测量价值。", ""])
    for row in plan["next_actions"]:
        lines.extend([f"### {row['sequence']}. {_md(row['title'])}", "", f"缺口：{_md(row['gap'])}", "",
                      f"现在做的理由：{_md(row['why_now'])}", "", f"竞争解释：{_md(row['alternative_explanation'])}", "",
                      f"下一项检验：{_md(row['next_test'])}", "", f"成功信号：{_md(row['success_signal'])}", "",
                      f"停止或改向信号：{_md(row['stop_signal'])}", "",
                      f"依赖：{_md(', '.join(row['depends_on']) or '无声明依赖')}；证据：{_md(', '.join(row['evidence_ids']) or '未提供')}。", "",
                      f"费用估计：{_md(row['cost_usd'] if row['cost_usd'] is not None else '未知')} USD；时间估计：{_md(row['hours'] if row['hours'] is not None else '未知')} 小时。", ""])
    if not plan["next_actions"]:
        lines.extend(["目前没有满足已声明约束的行动提案；先补充上下文、依赖或资源估计。", ""])
    lines.extend(["## 全部方向及处置", ""])
    lines.extend(f"- {_md(row['title'])}：{_md(row['disposition'])}；{_md(' '.join(row['reasons']))}" for row in plan["directions"])
    lines.extend(["", "## 优先澄清", ""] + [f"- {_md(q)}" for q in plan["questions"]])
    lines.extend(["", "## 证据清单", ""] + [f"- {_md(row['id'])}（{_md(row['status'])}）：{_md(row['summary'])}；来源声明：{_md(row['source'])}" for row in plan["context"].get("evidence", [])])
    lines.extend(["", "## 能力交接", "", _md(plan["handoff"]["instruction"])])
    lines.extend(f"- {_md(row['direction_id'])}：{_md(row['capability_query'])}（{_md(row['disposition'])}）" for row in plan["handoff"]["requests"])
    lines.extend(["", "## 适用限制", ""] + [f"- {_md(item)}" for item in plan["limits"]])
    (root / "RESEARCH.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(root / "research-plan.json"), "md": str(root / "RESEARCH.md")}


def research_example():
    """Manufactured research context for workflow demonstration, not observations."""
    return {
        "schema_version": 1, "evidence_type": "synthetic",
        "task": {"question": "模拟示例：一种细胞状态是否与处理反应相关，下一步应优先补什么？",
                 "background": "完全虚构的演示：单批次样本的探索分析提示状态差异，但尚未排除供体构成与测量偏差。没有真实患者、实验或研究观察。",
                 "decision": "决定先追加探索测量，还是先用现有数据排查混杂。", "domain": "模拟单细胞研究"},
        "evidence": [
            {"id": "demo-pattern", "summary": "虚构线索：探索聚类中看到状态比例不同。", "source": "synthetic demonstration; no dataset", "status": "hypothesis"},
            {"id": "demo-design", "summary": "演示设定：处理组与批次及供体构成可能重合。", "source": "synthetic design assumption", "status": "hypothesis"}],
        "dimensions": {
            "question": {"status": "partial", "rationale": "示例问题尚未定义效应量和决策阈值。", "evidence_ids": []},
            "design": {"status": "missing", "rationale": "演示设定缺少能区分处理与供体或批次的对照。", "evidence_ids": ["demo-design"]},
            "measurement": {"status": "unknown", "rationale": "RNA 状态能否代表拟研究功能尚未建立。", "evidence_ids": ["demo-pattern"]}},
        "directions": [
            {"id": "check-confounding", "title": "先判定处理效应是否可识别", "gap": "处理与供体及批次可能无法区分。", "kind": "method", "dimension": "design",
             "why_now": "低成本的设计核对可能避免在不可识别设计上追加复杂分析。", "evidence_ids": ["demo-design"],
             "alternative_explanation": "状态比例差异由供体组成或批次产生。", "next_test": "在授权元数据上检查处理、供体、批次交叉表；预先写明不可识别条件。",
             "success_signal": "存在独立重复和可区分的处理比较；明确比较单位。", "stop_signal": "处理完全与批次或供体混杂，则停止因果解释并重新设计。",
             "depends_on": [], "impact": 5, "uncertainty": 5, "effort": 1, "cost_usd": 0, "hours": 1, "status": "proposed"},
            {"id": "orthogonal-measure", "title": "设计能够挑战细胞状态解释的正交测量", "gap": "转录状态与目标功能之间缺少直接测量。", "kind": "evidence", "dimension": "measurement",
             "why_now": "先明确什么观察会推翻首选解释，再决定是否值得新增测量。", "evidence_ids": ["demo-pattern"],
             "alternative_explanation": "转录变化是压力或技术过程，而非目标功能改变。", "next_test": "在可识别设计基础上，提出与目标功能直接相关的测量和阴性对照；先询价。",
             "success_signal": "预先规定的正交指标与状态假设一致，且对照排除主要替代解释。", "stop_signal": "正交指标不支持目标功能，或费用与样本要求超出约束。",
             "depends_on": ["check-confounding"], "impact": 5, "uncertainty": 4, "effort": 4, "cost_usd": None, "hours": None, "status": "proposed"},
            {"id": "find-metadata-reader", "title": "核对现有工具是否能读取授权元数据", "gap": "示例中尚未核实可用的本地元数据读取能力。", "kind": "capability", "dimension": "resources",
             "why_now": "仅在现有能力不足时寻找额外工具。", "evidence_ids": [],
             "alternative_explanation": "已有原生读取能力足够，无需安装插件。", "next_test": "先检查现有工具和文件格式适配度，再决定是否搜索。",
             "success_signal": "能按权限读取必要字段并保留来源。", "stop_signal": "现有工具已经足够，或缺少数据授权。",
             "depends_on": [], "impact": 2, "uncertainty": 2, "effort": 1, "cost_usd": 0, "hours": 0.5,
             "capability_query": "local tabular metadata inspection", "status": "proposed"}],
        "constraints": {"budget_usd": 100, "hours_available": 4, "max_next_actions": 3},
        "revision_note": "纯模拟输入，用于检查诊断与资源约束；不是科研结果。",
    }
