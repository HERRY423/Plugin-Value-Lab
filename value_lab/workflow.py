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


def plan_plugin_use(context, now=None, *, artifact_root=None, verifier_root=None):
    if not isinstance(context, dict) or type(context.get("schema_version")) is not int or context["schema_version"] != 1:
        raise ValidationError("context.schema_version must be 1")
    intent = context.get("intent")
    if intent not in ("choose", "use", "evaluate", "manage"):
        raise ValidationError("intent must be choose, use, evaluate or manage")
    if "plugin_combination" in context:
        if (intent not in ("choose", "evaluate") or context.get("selected_plugin") is not None
                or any(k in context for k in ("task_selection", "evidence_acquisition", "evidence_bridge"))):
            raise ValidationError("Plugin combination needs a separate choose/evaluate request without a selected provider")
        from .plugin_combinations import route
        result = route(context['plugin_combination'], artifact_root=artifact_root, verifier_root=verifier_root)
        from .decision_view import brief
        preparing = 'design' in result
        stage = result['design']['spec']['stage'] if preparing else result['stage']
        headline = ('已冻结插件对照计划，等待真实观察' if preparing else
                    '合成演示：已重算插件组合，不构成真实采用建议' if result['evidence_status'] == 'SIMULATION_ONLY' else
                    '已重算插件组合；建议仅限本阶段已测试候选')
        return {'schema_version': 1, 'type': 'plugin_use_plan', 'route': 'ASSESS_PLUGIN_COMBINATION',
                'owner': LAB, 'headline': headline,
                'task_summary': stage['summary'], 'reasons': [result['status']], 'combination': result,
                'evidence_brief': brief(result),
                'steps': [{'owner': 'host', 'purpose': '独立保留计划与摘要，按随机顺序采集各臂原始结果、成本和暴露记录。'
                           if preparing else '复核交互量、逐任务结果、未知候选和最小组合范围；另行验证宿主执行。'}],
                'handoff': {'status': 'NO_AUTOMATIC_ACTION'},
                'limitations': ['保留原有单插件评估。合成材料不是现实收益证据。',
                                '交互量是描述性结果，负交互不等于冲突；配置声明不证明真实暴露或调用。',
                                '不自动安装、卸载、扩大权限、执行宿主或调用付费服务。']}
    if "evidence_acquisition" in context and "task_selection" not in context:
        raise ValidationError("Evidence acquisition requires an explicit task_selection catalog")
    if "evidence_bridge" in context and ("task_selection" not in context or "evidence_acquisition" in context):
        raise ValidationError("Evidence bridge requires a target task_selection and a separate mode from screening acquisition")
    if "task_selection" in context:
        if intent != "choose" or context.get("selected_plugin") is not None:
            raise ValidationError("Task selection requires a general choose request; do not replace an explicit provider or management request")
        from .task_selection import select_task_plan
        if "evidence_bridge" in context:
            from .evidence_bridge import plan_bridge
            bridge = plan_bridge(context["task_selection"], context["evidence_bridge"], artifact_root=artifact_root, verifier_root=verifier_root)
            labels = {"NEW_STUDY_REQUIRED": "研究设计或证据条件已改变，需要新建研究",
                      "INPUT_EVIDENCE_REQUIRED": "先核实新旧输入的真实差异", "SOURCE_EVIDENCE_REQUIRED": "旧证据尚不足以作为桥接起点",
                      "SAME_SCOPE_REPLAY": "可继续引用原范围证据；重放不增加新观察", "BRIDGE_REQUIRED": "已定位差异并生成独立桥接协议",
                      "BRIDGE_EVIDENCE_REQUIRED": "桥接记录尚不完整，保留未知", "BRIDGE_REJECTED": "新输入上的桥接未通过，不能迁移原采用结论",
                      "TARGET_OBSERVATION_SUPPORTED": "新输入上的完整观察通过，支持范围单独记录"}
            purpose = ("在新研究中重新规定任务、判据和对照；保留旧记录，不沿用原采用结论。" if bridge["state"] == "NEW_STUDY_REQUIRED" else
                       "独立保存返回的桥接协议与摘要，再采集目标输入的完整两臂记录及成本。" if bridge["state"] == "BRIDGE_REQUIRED" else
                       "核对差异、原始验证收据和当前证据状态；旧观察与目标观察保持分开。")
            return {"schema_version": 1, "type": "plugin_use_plan", "route": "BRIDGE_TASK_EVIDENCE", "owner": "host",
                    "headline": ("合成演示：" if bridge["evidence_status"] == "SIMULATION_ONLY" else "") + labels[bridge["state"]],
                    "task_summary": context["task_selection"]["task"]["summary"], "reasons": [bridge["state"], *bridge["new_study_barriers"]],
                    "steps": [{"owner": LAB, "action": "review_bridge_scope", "purpose": purpose}]
                             + [{"owner": "researcher", "action": "required_review", "purpose": r} for r in bridge["required_reviews"]],
                    "handoff": {"kind": "none", "status": "PROPOSED_NOT_EXECUTED", "execute": False},
                    "evidence_status": bridge["evidence_status"], "bridge": bridge, "limitations": bridge["limits"]}
        if "evidence_acquisition" in context:
            from .evidence_acquisition import plan_acquisition
            acquisition = plan_acquisition(context["task_selection"], context["evidence_acquisition"],
                                           artifact_root=artifact_root, verifier_root=verifier_root)
            labels = {"NEXT_BATCH": "只补当前可能改变选择的一批证据", "STOP_CHOICE_STABLE": "当前筛选范围内选择已稳定，停止追加筛选",
                      "STOP_BUDGET": "已到预先规定的预算边界，停止并保留不确定性",
                      "STOP_NO_RELEVANT_CHECK": "没有剩余检查能改变当前候选去留，停止并报告缺口",
                      "WAIT_FOR_BATCH": "已有一批检查待完成，保留原批次与费用预留",
                      "REPAIR_EVIDENCE": "先补齐已有批次的证据，不启动新试验", "REPAIR_CATALOG": "先补齐候选目录",
                      "CLARIFY_TASK": "先核实会改变适用性的任务条件", "STOP_BUDGET_OVERRUN": "观察成本超过冻结上限，停止新增检查",
                      "REVIEW_CONFLICT": "候选证据存在冲突，先复核再作选择"}
            if acquisition["state"] == "NEXT_BATCH":
                action, purpose = "review_next_batch", "核对下方补证据计划、不同结果的影响及剩余预算；并列批次只选一个。"
            elif acquisition["state"] == "WAIT_FOR_BATCH":
                action, purpose = "wait_for_original_batch", "等待原批次完成，保留费用预留和已有记录。"
            elif acquisition["state"] in ("REPAIR_EVIDENCE", "REPAIR_CATALOG", "CLARIFY_TASK", "REVIEW_CONFLICT"):
                action, purpose = "resolve_acquisition_blocker", "核对缺失材料、任务条件或冲突；保留已有证据，解决前不启动新批次。"
            else:
                action, purpose = "retain_stopped_decision", "保留停止结果、未解决候选和剩余不确定性；当前不启动额外检查。"
            acquisition_steps = [{"owner": LAB, "action": action, "purpose": purpose}]
            chosen = next((p for p in acquisition["candidate_plans"] if p["plan_sha256"] == acquisition["selected_plan_sha256"]), None)
            if chosen:
                acquisition_steps.extend({"owner": s["component_id"], "action": "proposed_stage", "purpose": f"{s['stage_id']}：{s['capability']}"}
                                         for s in chosen["manifest"]["steps"])
            acquisition_steps.extend({"owner": "researcher", "action": "required_review", "purpose": r} for r in acquisition["required_reviews"])
            return {"schema_version": 1, "type": "plugin_use_plan", "route": "ACQUIRE_DECISION_EVIDENCE", "owner": "host",
                    "headline": ("合成演示：" if acquisition["evidence_status"] == "SIMULATION_ONLY" else "") + labels[acquisition["state"]],
                    "task_summary": context["task_selection"]["task"]["summary"],
                    "reasons": [acquisition["state"], "先比较当前最精简候选；只把有可能改变去留的检查列入下一批。"],
                    "steps": acquisition_steps,
                    "handoff": {"kind": "none", "status": "PROPOSED_NOT_EXECUTED", "execute": False},
                    "evidence_status": acquisition["evidence_status"], "acquisition": acquisition,
                    "limitations": acquisition["limits"]}
        selection = select_task_plan(context["task_selection"], artifact_root=artifact_root, verifier_root=verifier_root)
        selected = next((p for p in selection["plans"] if p["plan_sha256"] == selection["selected_plan_sha256"]), None)
        headlines = {
            "MINIMUM_IN_DECLARED_CATALOG": "在当前任务和已声明候选中，找到有证据支持的最小方案",
            "SUPPORTED_OPTION_MINIMUM_UNRESOLVED": "已有可用方案的局部证据，更简单的候选仍待核验",
            "CHOICE_REQUIRED": "多个同样精简的方案通过检查，保留选择而不任意排名",
            "SIMULATION_ONLY": "已完成方案选择演示；合成记录不能支持真实推荐",
            "EVIDENCE_REQUIRED": "目前证据不足以推荐完整方案，先补齐具体缺口",
        }
        steps = [{"owner": "host", "action": "verify_current_capabilities",
                  "purpose": "核对候选的当前工具、版本、输入访问和权限；计划不代表已连接或获准执行。"}]
        if selected:
            steps.extend({"owner": step["component_id"], "action": "proposed_stage",
                          "purpose": f"{step['stage_id']}：{step['capability']}"} for step in selected["manifest"]["steps"])
        else:
            steps.append({"owner": LAB, "action": "resolve_evidence_gaps",
                          "purpose": "按保留的失败、未知项及完整流程检查准备补测；不从局部通过推断组合有效。"})
        steps.extend({"owner": "researcher", "action": "required_review", "purpose": review}
                     for review in selection["required_reviews"])
        reasons = [selection["status"], *selection["baseline_coverage_gaps"]]
        if selected:
            reasons.append(f"所选完整方案在提交记录中通过任务与整合检查；新增插件 {selected['size'][0]} 个，全部插件 {selected['size'][1]} 个。")
            reasons.append("依赖数量按预先指定的政策比较；这不证明费用更低、速度更快或科学结论成立。")
        if selection["unbound_studies"]:
            reasons.append(f"仍有 {len(selection['unbound_studies'])} 份未绑定研究，不能确认最小性。")
        return {"schema_version": 1, "type": "plugin_use_plan", "route": "SELECT_TASK_PLAN", "owner": "host",
                "headline": headlines[selection["status"]], "task_summary": context["task_selection"]["task"]["summary"],
                "reasons": reasons, "steps": steps,
                "handoff": {"kind": "none", "status": "PROPOSED_NOT_EXECUTED", "execute": False},
                "evidence_status": selection["status"], "selection": selection,
                "limitations": selection["limits"]}
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
    notice = ("本计划重算已有记录与授权产物；没有运行新的模型或插件、搜索、安装、连接或修改账户。"
              if any(k in plan for k in ("selection", "acquisition", "bridge", "combination")) else "此计划没有搜索、安装、连接、评测或修改账户。")
    lines = ["# 证据迁移与桥接" if "bridge" in plan else "# 最小补证据计划" if "acquisition" in plan else "# 任务方案选择" if "selection" in plan else "# 插件使用计划", "", f"**{_md(plan['headline'])}**", "",
             f"任务：{_md(plan['task_summary'])}", "", notice, "",
             "## 下一步", ""]
    lines.extend(f"{i}. {_md(step['purpose'])}（{_md(step['owner'])}）" for i, step in enumerate(plan["steps"], 1))
    if not plan["steps"]:
        lines.append("先澄清具体请求，不创建账户操作。")
    if 'combination' in plan:
        from .decision_view import markdown as evidence_markdown
        # Put the evidence strip before generic next steps and full tables.
        offset = lines.index('## 下一步')
        lines[offset:offset] = evidence_markdown(plan['combination'])
    lines.extend(["", "## 判断依据", ""] + [f"- {_md(r)}" for r in plan["reasons"]])
    if 'combination' in plan:
        result = plan['combination']
        lines += ['', '## 最小有效插件组合', '']
        if 'design' in result:
            lines += [f"计划 {len(result['design']['assignments'])} 次运行；未执行。",
                      f"独立保留设计摘要：{result['design_sha256']}。",
                      '按 BASELINE、A、B、AB（可选 BA）的随机分配采集新会话。完整设计保留在 plan.json。']
        else:
            lines += [f"证据：{result['evidence_status']}；观察 / 计划：{result['observed_runs']} / {result['planned_runs']}。",
                      '', '实验臂 | 可行性 | 质量 | 成功率 | 完整声明成本（美元） | 耗时（秒）', '--- | --- | --- | --- | --- | ---']
            for arm in result['arms']:
                values = [arm['metrics'][m]['mean'] for m in ('quality', 'success', 'cost_usd', 'duration_seconds')]
                lines.append(' | '.join(_md(str(v)) for v in [arm['arm'], arm['status'], *values]))
            for arm in result['arms']:
                if arm['reasons']:
                    lines.append(f"\n{arm['arm']}：{_md('; '.join(arm['reasons']))}\n")
            lines += ['', '交互量 = Q(组合) − Q(A) − Q(B) + Q(基线)，没有除以二。']
            for contrast in result['contrasts']:
                lines.append(f"- {contrast['arm']}：质量交互量 {contrast['interaction']['quality']['mean']}；{contrast['observed_quality_pattern']}。")
            if result['order_effect_AB_minus_BA'] is not None:
                lines.append(f"- 顺序差 AB − BA：{result['order_effect_AB_minus_BA']['quality']['mean']}（质量）。")
            rec = result['recommendation']
            lines += ['', f"建议状态：{rec['status']}；候选：{', '.join(rec['candidate_arms']) or '尚无'}。",
                      '最小范围仅限本阶段的已声明候选；并列候选保留。合成结果仅演示选择逻辑。',
                      '能力暴露、原始结果判据、逐任务差异和事件证据保留在 plan.json。',
                      '诊断类别：重复工作、信息覆盖、参数传递错误、错误证据传播；未评估不等于没有发生。']
            lines += [f"- 待解决：{_md(issue)}" for issue in result['issues']]
            if 'burden_view' in result:
                from .burden_presentation import markdown
                lines += markdown(result['burden_view'])
    if "bridge" in plan:
        bridge = plan["bridge"]
        labels = {"DESCRIPTIVE_ONLY": "描述变化，保留原范围", "VERIFY_INPUT_DIFFERENCE": "核验输入变化",
                  "BRIDGE_REQUIRED": "需要目标输入桥接", "NEW_STUDY_REQUIRED": "必须新建研究"}
        lines += ["", "## 差异与行动", "", "变化位置 | 处理", "--- | ---"]
        lines.extend(f"{_md(d['path'])} | {labels[d['classification']]}" for d in bridge["changes"])
        lines += ["", f"实际输入检查：{_md(bridge['input_check']['status'])}",
                  "行重排或编码等价只说明输入身份、内容可复核；不能证明插件运行与顺序无关。",
                  "旧证据重算新增观察数：0。旧采用结论不会自动迁移。"]
        if bridge["input_check"].get("reason"):
            lines.append(f"待恢复的输入证据：{_md(bridge['input_check']['reason'])}")
        for side, failures in bridge["input_reference_issues"].items():
            lines.append(f"{'旧任务' if side == 'source' else '目标任务'}的输入派生参考与实际文件不符：{_md(', '.join(failures))}。先核实参考，不据此判定方案失败。")
        for failures in bridge["target_applicability_issues"].values():
            lines.append(f"目标数据不满足原方案或对照的声明适用条件：{_md('; '.join(failures))}。需要重新设计研究。")
        if bridge["proposed_protocol"]:
            lines += [f"独立桥接批次：{bridge['proposed_protocol']['planned_runs']} 个计划运行，保留两臂、所有任务阶段及整合检查。",
                      "完整协议、摘要、原始收据和目标范围保留在 plan.json；执行前独立保存协议。"]
        if bridge["bridge_result"]:
            lines.append(f"目标输入上的样本检查：{_md(bridge['bridge_result']['sample_outcome'])}；证据：{_md(bridge['evidence_status'])}。")
        lines.append("桥接只覆盖此次新输入与条件，未测候选仍未知，不证明目标任务中的最小方案或普遍科学有效。")
    if "acquisition" in plan:
        acquisition = plan["acquisition"]
        budget = acquisition["budget"]
        lines += ["", "## 下一批与停止条件", "", f"证据：{_md(acquisition['evidence_status'])}；已启动 {budget['batches_started']} 批。",
                  f"累计记录或预留 {budget['spent_or_reserved_usd']} USD，剩余 {budget['remaining_usd']} USD。不是已核实账单或付费授权。",
                  "", "检查 | 用途 | 涉及当前候选数 | 整批费用上限（USD） | 安排", "--- | --- | --- | --- | ---"]
        proposed = {b["check_id"] for b in acquisition["next_batch_options"]}
        reasons = {"already_observed": "已有记录，不重复", "screening_closed": "已进入确认，筛选关闭",
                   "cannot_change_current_frontier": "不影响当前最精简候选，暂缓"}
        for row in acquisition["agenda"]:
            decision = "下一批候选（并列时仅选一批）" if row["check_id"] in proposed else reasons.get(row["deferred_reason"], "暂缓，保留候选")
            lines.append(f"{_md(row['check_id'])} | {'筛选' if row['phase'] == 'screening' else '完整确认'} | {len(row['affected_plans'])} | {row['cost_upper_bound_usd']} | {decision}")
        lines += ["", "筛选通过：保留候选，尚不能采用。筛选失败：只从本次筛选名单移除。结果未知：先修复已有批次。",
                  "完整确认必须保留所有任务阶段及整合检查；首次确认后不再使用确认结果安排新的筛选。",
                  "达到预算、选择稳定或没有相关检查时均可停止，不要求得到绿色结论。完整批次锁、结果分支与未解决候选见 plan.json。"]
    if "selection" in plan:
        selection = plan["selection"]
        labels = {"SUPPORTED": "完整观察支持", "FAILED": "未通过", "UNKNOWN": "尚未确定", "INAPPLICABLE": "声明条件不适用",
                  "CONFLICTING_EVIDENCE": "证据冲突", "SIMULATION_ONLY": "仅合成演示"}
        lines += ["", "## 方案比较", "", "编号 | 阶段能力 | 新增插件 / 全部插件 | 证据状态 | 各次试验本臂总成本（USD）", "--- | --- | --- | --- | ---"]
        for index, row in enumerate(selection["plans"], 1):
            label = "；".join(f"{s['stage_id']} → {s['component_id']} ({s['capability']})" for s in row["manifest"]["steps"])
            costs = "；".join("未知" if o["observed_total_evaluation_cost_usd"] is None else str(o["observed_total_evaluation_cost_usd"])
                              for o in row["observations"]) or "未知"
            status = labels[row["status"]]
            if row["status"] == "SIMULATION_ONLY":
                status += "（样例" + {"SUPPORTED": "通过", "FAILED": "失败", "UNKNOWN": "未知", "CONFLICTING_EVIDENCE": "冲突"}[row["sample_outcome"]] + "）"
            lines.append(f"{index} | {_md(label)} | {row['size'][0]} / {row['size'][1]}{'（下界）' if row['size_is_lower_bound'] else ''} | {_md(status)} | {_md(costs)}")
        lines += ["", "只在声明的候选范围内比较新增插件数，再比较全部插件数；未证明最低费用或最快速度。",
                  "成本是各份研究完整计划运行的总额，不是下一次任务的费用预测；估算和声明不代表已结算。",
                  "完整方案标识、成本、逐项收据、原始研究绑定与阶段结果保留在 plan.json。", "", "## 使用条件与复核", ""]
        for row in selection["plans"]:
            if row["plan_sha256"] not in selection["choice_plan_sha256s"]:
                continue
            for option in row["manifest"]["steps"]:
                conditions = "；".join(f"{key} ∈ {json.dumps(values, ensure_ascii=False)}" for key, values in option["requires"].items())
                lines.append(f"- {_md(option['stage_id'])} / {_md(option['component_id'])}：{_md(conditions) or '按冻结任务契约'}")
        lines.extend(f"- 仍需复核：{_md(review)}" for review in selection["required_reviews"])
        lines += ["", "## 尚需核验", ""]
        for gap in selection["evidence_gaps"]:
            lines.append(f"- {_md(gap['plan_sha256'][:12])}：{_md('; '.join(gap['needed']))}")
        if not selection["evidence_gaps"]:
            lines.append("本轮没有生成具体补测项；请同时核对候选覆盖缺口、未绑定研究与最低范围声明。")
    lines.extend(["", "## 可交接的信息", "", f"状态：{_md(plan['handoff']['status'])}"])
    for key in ("capability_query", "plugin_reference", "requested_action", "requested_permission_mode"):
        if key in plan["handoff"]:
            lines.append(f"- {_md(key)}：{_md(plan['handoff'][key])}")
    lines.extend(["", "## 适用限制", ""] + [f"- {_md(item)}" for item in plan["limitations"]])
    (root / "PLAN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    files = {"json": str(root / "plan.json"), "md": str(root / "PLAN.md")}
    if 'combination' in plan:
        from .decision_view import render
        (root / 'EVIDENCE.html').write_text(render(plan['combination'], plan['task_summary']), encoding='utf-8')
        files['html'] = str(root / 'EVIDENCE.html')
    return files
