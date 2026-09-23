"""Task-first planning that complements host Plugin Management, without invoking it.

Fit and connection facts are supplied observations, not an internal registry.
Handoffs contain public capability keywords, a chosen reference, and explicitly
requested management actions. No plan changes permissions or plugin lifecycle.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .core import ValidationError, write_json


PM = "Plugin Management"
LAB = "Plugin Value Lab"
FIT = ("sufficient", "insufficient", "unknown")
FRESHNESS = timedelta(hours=24)
BROAD_TARGETS = {"all", "global", "google", "my plugins", "all plugins", "plugins", "所有", "全部", "我的插件"}


def _text(value, name, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValidationError(f"{name} must be nonempty text of at most {limit} characters")
    if any(ord(c) < 32 for c in value):
        raise ValidationError(f"{name} must be a single line")
    return value


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except ValueError:
        return None


def _selected(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationError("selected_plugin must be an object or null")
    reference = _text(value.get("reference"), "selected_plugin.reference", 200)
    display = _text(value.get("display_name"), "selected_plugin.display_name", 120)
    kind = value.get("kind")
    if kind not in ("chatgpt_plugin", "local_code_plugin"):
        raise ValidationError("selected_plugin.kind must be chatgpt_plugin or local_code_plugin")
    if kind == "chatgpt_plugin" and any(token in reference for token in ("/", "\\", ":")):
        raise ValidationError("ChatGPT plugin reference must be a plugin name or ID, not a URL, path or credential")
    if value.get("version") is not None and not isinstance(value["version"], str):
        raise ValidationError("selected_plugin.version must be text or null")
    installed = value.get("installed")
    if installed is not None and type(installed) is not bool:
        raise ValidationError("selected_plugin.installed must be true, false or null")
    connection = value.get("connection_state", "unknown")
    if connection not in ("ready", "pending", "not_connected", "unknown"):
        raise ValidationError("Unknown connection_state")
    source = value.get("status_source", "user")
    if source not in ("plugin_management", "host", "user", "local_manifest"):
        raise ValidationError("Unknown status_source")
    return {"reference": reference, "display_name": display, "kind": kind, "installed": installed,
            "connection_state": connection, "status_source": source,
            "version": value.get("version"), "observed_at": value.get("observed_at")}


def plan_plugin_use(context, now=None):
    if not isinstance(context, dict) or type(context.get("schema_version")) is not int or context["schema_version"] != 1:
        raise ValidationError("context.schema_version must be 1")
    intent = context.get("intent")
    if intent not in ("choose", "use", "evaluate", "manage"):
        raise ValidationError("intent must be choose, use, evaluate or manage")
    task = context.get("task")
    if not isinstance(task, dict):
        raise ValidationError("task must be an object")
    summary = _text(task.get("summary"), "task.summary", 2000)
    capability = _text(task.get("capability"), "task.capability", 120)
    # The public query is explicitly separate from the task. Refuse common
    # non-keyword forms; this guard is not a comprehensive privacy classifier.
    if any(token in capability for token in ("/", ":", "\\", "\n", "@", "Bearer ", "sk-")):
        raise ValidationError("task.capability must contain public capability keywords, not URLs, paths, accounts or credentials")
    native, connected = context.get("native_fit", "unknown"), context.get("connected_fit", "unknown")
    if native not in FIT or connected not in FIT:
        raise ValidationError("Fit must be sufficient, insufficient or unknown")
    pm_available = context.get("plugin_management_available", False)
    if type(pm_available) is not bool:
        raise ValidationError("plugin_management_available must be a host-observed boolean")
    target = _selected(context.get("selected_plugin"))
    goal = context.get("evaluation_goal", "quality")
    access = context.get("baseline_data_access", "unknown")
    if goal not in ("quality", "efficiency", "access"):
        raise ValidationError("evaluation_goal must be quality, efficiency or access")
    if access not in ("same", "different", "unknown"):
        raise ValidationError("baseline_data_access must be same, different or unknown")
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValidationError("now must be a timezone-aware datetime")
    now = now.astimezone(timezone.utc)
    observed = _time(target["observed_at"]) if target else None
    fresh = observed is not None and -timedelta(minutes=5) <= now - observed <= FRESHNESS
    trusted_status = bool(target and target["status_source"] in ("host", "plugin_management"))
    ready = bool(target and fresh and trusted_status and target["installed"] is True and target["connection_state"] == "ready")
    owner = PM if pm_available else "host"
    state = {"native_fit": native, "connected_fit": connected, "selected_plugin": target,
             "connection_observation_fresh": fresh, "ready_for_routing": ready,
             "basis": "Supplied host observations; not independently verified by this planner"}
    comparison = {"goal": goal, "baseline_data_access": access, "quality_comparison_ready": access == "same",
                  "access_is_not_reasoning_gain": True}

    def result(route, assigned, headline, reasons, steps, kind="none", reference=False, query=False):
        handoff = {"kind": kind, "status": "PROPOSED_NOT_EXECUTED", "execute": False}
        if reference and target and target["kind"] == "chatgpt_plugin":
            handoff["plugin_reference"] = target["reference"]
        if query:
            handoff["capability_query"] = capability
        limitations = [
            "任务适配和连接状态来自提交的上下文；规划器没有实时搜索、连接或改变账户。",
            "已连接不等于有增益；未做价值评估也不妨碍完成已授权的普通任务。",
            "交接只携带公开能力关键词、明确插件引用与所请求的管理动作；私有任务说明和资料保留在本地。",
            "推荐只表示下一步；权限变更、卸载和任何外部副作用仍须符合用户的具体请求。",
        ]
        if assigned == "host" and kind != "none" and not pm_available:
            limitations.append("当前未声明 Plugin Management 可用；由宿主查找可用入口，不能据此断言目标服务不存在。")
        return {"schema_version": 1, "type": "plugin_use_plan", "route": route, "owner": assigned,
                "headline": headline, "task_summary": summary, "reasons": reasons,
                "steps": [{"owner": a, "action": b, "purpose": c} for a, b, c in steps],
                "handoff": handoff, "evidence_status": "VALUE_NOT_ASSESSED",
                "observations": state, "comparison": comparison, "limitations": limitations}

    if intent == "manage":
        request = context.get("management")
        if not isinstance(request, dict):
            return result("CLARIFY_MANAGEMENT", "host", "先明确希望管理的对象和动作", [], [], "clarification")
        action = request.get("action")
        if action not in ("discover", "inspect_permissions", "inspect_dependencies", "change_permissions", "remove"):
            raise ValidationError("Unknown management action")
        if action == "discover":
            return result("MANAGE_REQUEST", owner, "按用户指定的能力寻找候选插件", ["这是明确的发现请求。"],
                          [(owner, "discover", "搜索相关候选，核对适配度与当前状态；只建议最小有用集合。")], "discovery", query=True)
        if not target or target["reference"].strip().casefold() in BROAD_TARGETS or target["display_name"].strip().casefold() in BROAD_TARGETS:
            return result("CLARIFY_MANAGEMENT", "host", "需要一个明确的插件对象", ["广泛名称不能代表用户选定的具体插件。"], [], "clarification")
        explicit = request.get("explicit_request")
        if type(explicit) is not bool or not explicit:
            return result("CLARIFY_MANAGEMENT", "host", "当前没有明确的管理请求", ["使用卡或评分不能自动产生账户管理授权。"], [], "clarification")
        if target["kind"] == "local_code_plugin":
            return result("LOCAL_PLUGIN_MANAGEMENT", "host", "在对应的本地宿主管理这个代码插件",
                          ["ChatGPT 应用权限与本地代码插件是不同的管理对象。"],
                          [("host", "resolve_local_plugin_management", "根据确切本地插件和用户请求选择宿主管理入口。")], "local_management")
        if action == "change_permissions" and request.get("permission_mode") not in (
                "inherit", "always_ask", "ask_before_writes", "review_important_actions", "full_access"):
            return result("CLARIFY_MANAGEMENT", "host", "先明确所需权限模式", ["不根据价值分数推断权限应该扩大或缩小。"], [], "clarification")
        plan = result("MANAGE_REQUEST", owner, f"将明确的管理请求交回 {owner}",
                      ["保留用户指定的对象和动作；此计划未执行账户变更。"],
                      [(owner, action, "按当前工具契约处理这一明确请求；模糊或高风险变更先澄清。")], "management_request", reference=True)
        plan["handoff"]["requested_action"] = action
        if action == "change_permissions":
            plan["handoff"]["requested_permission_mode"] = request["permission_mode"]
        plan["handoff"]["authority"] = "USER_REQUEST_MUST_REMAIN_VERIFIABLE_IN_HOST_CONTEXT"
        return plan

    if intent == "evaluate":
        if goal == "access":
            return result("DESIGN_ACCESS_TRIAL", LAB, "先评价这项连接让哪些任务成为可能",
                          ["访问到新资料与分析质量提高需要分别解释。"],
                          [(LAB, "define_access_outcomes", "记录原先无法访问的资料、任务成功与设置成本；不把它写成同资料上的推理提升。"),
                           (LAB, "retain_access_boundary", "核心质量评分器不直接认证访问增益；将访问试验作为单独设计保留。")], "trial_design")
        if access != "same":
            return result("ALIGN_BASELINE_DATA", LAB, "先让两组获得相同的授权资料",
                          ["缺资料或权限不足不能直接解释为内容质量更差。"],
                          [(LAB, "align_authorized_inputs", "准备相同的授权快照或改为明确的访问能力问题。"),
                           (LAB, "prepare_rubric", "先写任务、质量底线与成本指标；连接未就绪也可以做这些准备。")], "trial_design")
        return result("DESIGN_MATCHED_TRIAL", LAB, "设计与当前采用问题相称的小规模比较",
                      ["明确的评估请求优先；不必先改变任何插件连接或权限。"],
                      [(LAB, "prepare_matched_suite", "固定版本、模型、资料和预算，包含普通任务、负对照和应当暂缓结论的案例。"),
                       (LAB, "freeze_then_collect", "冻结后记录独立会话、失败、原始输出和完整成本。"),
                       (LAB, "build_usage_card", "从完整记录重算结果，形成带适用条件的使用卡。")], "trial_design")

    # Explicit use of a selected plugin/provider should not silently fall back
    # to a generic native tool that cannot access the requested account.
    if intent == "use" and target is None:
        return result("CHECK_EXISTING_CAPABILITIES", "host", "先确认你指定的插件或服务",
                      ["明确使用请求不能被替换成未经确认的其他数据来源。"],
                      [("host", "identify_requested_provider", "核对用户指定的服务和当前可用入口，不编造插件引用。")])
    explicit_target_use = intent == "use" and target is not None
    if not explicit_target_use and native == "sufficient":
        return result("USE_NATIVE", "built_in", "直接用现有原生能力完成任务",
                      ["当前任务已被现有能力覆盖，无需新增插件或先做评估。"],
                      [("built_in", "complete_task", "完成用户任务，检查实际结果是否满足要求。")])
    if target:
        target_owner = owner if target["kind"] == "chatgpt_plugin" else "host"
        if target["connection_state"] == "pending" and fresh and trusted_status:
            return result("AWAIT_CONNECTION", target_owner, "沿用已有连接请求，继续可独立完成的准备",
                          ["等待状态不等于连接完成，也不需要重复推荐。"],
                          [("host", "continue_independent_work", "准备输出格式、任务条件或评估方案，保留原连接请求。"),
                           (target_owner, "confirm_pending_connection", "确认原请求的最新状态；得到就绪证据后再调用目标工具。")], "pending_connection", reference=True)
        if not ready:
            return result("VERIFY_CONNECTION", target_owner, "先核对指定插件的实际可用状态",
                          ["安装、用户口述、过期快照与实际连接就绪是不同的证据。"],
                          [("host", "check_available_tools", "核对当前宿主的工具和连接状态；本地清单不证明服务已连通。"),
                           (target_owner, "resolve_connection", "确有能力缺口时使用现有管理入口；只使用已核实的插件身份。")], "connection_check", reference=True)
        if connected != "sufficient":
            return result("CHECK_EXISTING_CAPABILITIES", "host", "连接已具备声明的就绪证据，再核对任务适配度",
                          ["就绪仅表示可访问，不证明工具能够完成这一任务。"],
                          [("host", "check_task_fit", "按用户指定的数据来源、输出和动作核对能力范围。")])
        return result("USE_CONNECTED", "connected_plugin", "在用户指定的任务范围内使用已连接插件",
                      ["当前连接与任务适配已在上下文中明确；不强制增加评估步骤。"],
                      [("connected_plugin", "complete_authorized_task", "使用指定来源与工具完成任务，核对交付结果。"),
                       (LAB, "offer_comparison_when_useful", "只有重复使用、成本或采用判断值得比较时，再形成局部使用依据。")])
    if connected == "sufficient" or native == "unknown" or connected == "unknown":
        return result("CHECK_EXISTING_CAPABILITIES", "host", "先核对现有工具是否足够",
                      ["未知适配度或未指明的连接，不能当成必须安装新插件的证据。"],
                      [("host", "check_existing_tools", "确定已有能力和来源；能够直接完成就继续。")])
    return result("DISCOVER_MISSING_CAPABILITY", owner, "只为明确的能力缺口寻找插件",
                  ["上下文已说明原生和已连接能力都不足。"],
                  [(owner, "discover", "用公开能力关键词搜索，判断结果相关性，保留确切返回引用。"),
                   (owner, "suggest_smallest_useful_set", "只建议相关且未安装、未在等待中的候选，确认连接后再使用。"),
                   ("host", "continue_independent_work", "连接建议不阻断仍能继续的任务准备。")], "discovery", query=True)


def _md(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("[", "\\[").replace("]", "\\]").replace("`", "\\`").replace("|", "\\|").replace("\n", " ")


def write_plan(plan, output_dir):
    root = Path(output_dir)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValidationError("Plan output directory must be absent or empty")
    # Validate serialization before writing any artifact.
    json.dumps(plan, allow_nan=False)
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "plan.json", plan)
    lines = ["# 插件使用计划", "", f"**{_md(plan['headline'])}**", "",
             f"任务：{_md(plan['task_summary'])}", "", "此计划没有搜索、安装、连接、评测或修改账户。", "",
             "## 下一步", ""]
    lines.extend(f"{i}. {_md(step['purpose'])}（{_md(step['owner'])}）" for i, step in enumerate(plan["steps"], 1))
    if not plan["steps"]:
        lines.append("先澄清具体请求，不创建账户操作。")
    lines.extend(["", "## 判断依据", ""] + [f"- {_md(r)}" for r in plan["reasons"]])
    lines.extend(["", "## 可交接的信息", "", f"状态：{_md(plan['handoff']['status'])}"])
    for key in ("capability_query", "plugin_reference", "requested_action", "requested_permission_mode"):
        if key in plan["handoff"]:
            lines.append(f"- {_md(key)}：{_md(plan['handoff'][key])}")
    lines.extend(["", "## 适用限制", ""] + [f"- {_md(item)}" for item in plan["limitations"]])
    (root / "PLAN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(root / "plan.json"), "md": str(root / "PLAN.md")}
