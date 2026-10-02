# 阶段内最小有效插件组合

组合分析另有[独立负担视图](BURDEN-VIEW.zh-CN.md)：在原规则合格候选之间展示上下文压力、费用和耗时的逐任务取舍，保留缺失信息，不改变推荐。

2026-10-01；版本保持 0.8.0。单插件 WITH/WITHOUT 评估与 prompt/tools/context 四臂、八臂组件消融完整保留。本功能新增一个不同的问题：在当前阶段的同一任务、输入、背景工具和预算下，A、B 和组合分别能做到什么，最少保留哪些能力已经足够。

## 从图中建议到可执行行为

每项研究只选两个具有明确任务依赖的插件，记录选择理由。例如检索结果交给证据核对，而非凭介绍文字相似就断定冲突。每个阶段独立冻结一个研究，不自动搜索插件全集。多阶段端到端方案仍由既有 task_selection 路径处理；各阶段成功不能拼成未经测试的整条工作流成功。

| 实验臂 | 插件暴露与顺序 |
| --- | --- |
| BASELINE | 无被测插件，保留声明的原生／背景工具 |
| A | 只暴露 A 的本阶段能力 |
| B | 只暴露 B 的本阶段能力 |
| AB | A → B |
| BA（可选） | B → A，单独采集、单独报告 |

每个 case/repetition 内随机排序实验臂；各臂使用新会话。AB 与 BA 不合并。质量交互严格为 `Q(AB) - Q(A) - Q(B) + Q(BASELINE)`，与既有组件模块“二阶效应等于差中之差的一半”的定义分开。成功率、费用、耗时也按相同线性对比报告。先平均同一任务的重复，再等权平均任务；不把重复生成或共享基线作为独立样本，不输出显著性或因果结论。

负交互本身不证明干扰：A、B、AB 全成功而基线失败时，交互为 -1，但两个单插件都可能足够。报告另列组合相对最好单插件的质量变化、相对 A/B 的边际变化、AB−BA 顺序差，以及重复工作、信息覆盖、参数传递错误、错误证据传播四类诊断观察。未提供诊断覆盖不代表没有发生事件。

## 既有入口

在已更新的源码／安装包中，通过现有 MCP `plan_plugin_use(context, artifact_root?, verifier_root?)` 或 CLI `plan-use CONTEXT --output NEW_DIR` 使用，无新增工具和 CLI 子命令。Agent 负责把研究者的任务和材料转为对象；无需让研究者填写 JSON。

规划对象：

```json
{
  "schema_version": 1,
  "intent": "choose",
  "plugin_combination": {"action": "plan", "spec": "替换为下面规定的对象"}
}
```

分析时将 `plugin_combination` 替换为 `{action: "analyze", design, expected_id, observations}`。支持 choose/evaluate 意图；不能与 selected_plugin、task_selection、evidence_acquisition 或 evidence_bridge 同时提交，以免覆盖已有明确请求。MCP 授权目录仍由宿主设置，调用参数只能缩小范围。本模块的所有评分（包括 Python 直接调用）都禁止执行验证程序；需要执行的判据保持未知。

Python 接口为 `value_lab.plugin_combinations.plan(spec)` 和 `analyze(design, observations, expected_id, artifact_root=None, verifier_root=None)`（目录参数仅限关键字）。返回设计与摘要需在采集前独立保留。摘要仅绑定内容，不认证预注册时间。

`spec` 的严格字段：

结构化接口另有 [JSON Schema](../../schemas/plugin-combination.schema.json)。Schema 不替代运行时的完整设计、摘要、任务成功、路径与费用验证。

| 字段 | 契约 |
| --- | --- |
| suite | 现有完整 suite；保留所有任务、判据、关键检查、条件与原回归容忍度。suite.plugin 是沿用的研究元数据，真正的被测插件身份在 plugins/exposure 中 |
| stage | `{id, summary}`，只描述本次结论覆盖的阶段 |
| inputs | 非空输入名 → SHA-256；每臂声明必须一致，不证明实际宿主只读了这些输入 |
| plugins | 恰好两个 `{id, version, sha256, capabilities}`；顺序定义 A/B，capabilities 只列本阶段必要能力 |
| rationale | 明确的任务依赖及为什么要比较这一对；是研究者／Agent 的理由，不是已证实关系 |
| policy | `quality_floor`、`success_floor`、`max_mean_cost_usd`、`max_mean_duration_seconds`、`interaction_margin`，有限非负数；比例字段不大于 1，质量底线不得低于原 suite |
| compare_orders | 布尔值；true 增加 BA |
| seed | 0..2³²−1 整数，不能用布尔值 |

质量／成功率下限与费用／耗时上限应用于**每个 case 的重复均值**，不能由总体均值掩盖某项任务退步；所有关键检查必须通过。原 suite 的每任务质量回归护栏继续生效。这是“够用”的描述性规则，不复用单插件收益判定所需的正增益门槛，否则原生基线永远不能成为最小方案。原有单插件收益判定未修改，也不把这里的成功变成原有 benefit verdict。

`observations` 为 `{format: "pvl-plugin-combination-observations-1", design_sha256, runs}`。每个 run 恰含：

- `case_id, repetition, arm, execution_index`：冻结分配中的身份与顺序。
- `exposure`：实际收集到的 `{plugins, order, inputs, background_conditions}` 声明；必须与相应实验臂一致。不要用计划替代真实收集。这里只核对声明，未认证宿主移除、隔离、暴露或实际调用。
- `record`：现有原始运行对象，包含原始输出、条件、suite 摘要、会话、状态、成本、计时等；BASELINE 对应 without，其余对应 with。不能改写原结果或把导入的通过标签当作结果。现有 plugin_loaded 布尔值只表示分配集合，不能代替逐插件暴露声明。
- `additional_cost_usd`：`setup_usd, judge_usd, retry_usd, other_usd` 全部显式填写数值或 null。这些是分配到本次运行、尚未计入原 record 的附加费用；已有费用不能重复添加，真正无附加费用才填 0，未知填 null。重试费用可记录，重试输出不能替换失败槽位。内部逐行转入既有成本账本；共享基线的运行只计一次。声明费用覆盖不是账单结算认证。
- `diagnostics`：`{assessed: [类别], events: [{kind, detail, evidence: {path, sha256}}]}`；类别为 duplicate_work、information_overwrite、parameter_handoff_error、erroneous_evidence_propagation。事件必须属于已评估类别。授权材料根下的最大 8 MiB 相对文件可核验摘要；禁止路径越界。BYTES_VERIFIED 只证明提交字节匹配，不独立判定事件含义或因果关系。

缺失、跳过、基础设施故障、不一致条件、复用会话和跨臂人工计时重叠保留并阻断相应结论。所有计划槽位均出现在 cells 中。已知任务超时／失败作为失败保留。成本未知沿用原评分器的完整性护栏，耗时未知阻断可行性；不补零。原始条件、输出或文件不满足判据时，不能靠填写通过标签绕过。

## 建议边界

先满足逐任务质量／成功率／成本／耗时和关键检查，再按插件数量最小化。允许 BASELINE（零插件）胜出。A/B、AB/BA 同样精简且通过时保留并列，不暗中按名字、价格或排列顺序选一个。更小或同等大小的候选仍未知时，保留候选但不声称最小性已经确定；缺失实验臂也不能删掉分母。

`minimum_within_tested_set` 是有限候选的计算属性。合成材料始终返回 SIMULATION_ONLY，候选仅演示算法。非合成记录最多支持本阶段本输入本条件下的描述性 MINIMUM_OBSERVED；它不认证宿主执行、科学有效性、统计等效、全局最优或未见任务。不同顺序不能外推。“两插件在本阶段足够”也不代表它们全部能力或其内部组件已经最小化。

建议中的 `retain_capabilities` 只是宿主可审阅的暴露计划。`automatic_actions` 始终为空；价值分数不自动授权安装、卸载、权限扩张、联网、付费或新宿主运行。

## 可运行的制造案例

```bash
python examples/plugin-combinations/demo.py --output work/plugin-combination-demo
python scripts/value_lab.py plan-use work/plugin-combination-demo/plan-context.json --output work/plugin-combination-plan
python scripts/value_lab.py plan-use work/plugin-combination-demo/order-context.json --output work/plugin-combination-order
python -m unittest tests.test_plugin_combinations
```

输出目录必须是新目录，原研究不会覆盖。六个演示覆盖互补、可替代、组合退步、顺序敏感、原生能力足够与缺失观察。每项同时保留原始上下文、plan.json 和 PLAN.md；演示输入和观察全部制造，真实模型调用／真实插件收益样本为零。

## English contract summary

This additive feature preserves single-plugin and component-factorial evaluation. One prospectively selected pair is tested against a shared baseline, with separate optional invocation orders. Original outputs are regraded under the unchanged evaluator. Interaction uses the full difference-in-differences, without half scaling. Missing cells, costs and contamination remain explicit; diagnostic event labels are submitted evidence, never inferred from semantic similarity. Selection minimizes plugin count only after per-case feasibility, critical checks and original regression guards. Recommendations are stage-bound and descriptive; synthetic records never establish real benefit or host exposure. Existing planner CLI/MCP signatures and version 0.8.0 are retained.
