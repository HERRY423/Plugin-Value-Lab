# Advanced guide / 高级指南

PVL 的核心始终是：**配对、冻结、可复算地判断插件对一项具体任务有没有增益。** 先完成[一次单插件比较](../../README.zh-CN.md)；仅在研究问题需要时使用以下能力。

The core remains one paired plugin comparison with a frozen plan and recomputable results. The optional capabilities below support specific follow-up questions. They do not relax the core evidence requirements. Detailed topic documents retain their original language and scope.

## Research design / 研究设计

- [Methods and sample-size planning](../METHODOLOGY.md)：围绕目标效应量，规划独立任务族、任务数和每臂重复次数；报告适用条件下的置信区间。规划假设不是实测方差，重复不能冒充独立任务。
- [Conversational study authoring](RESEARCH-AUTHORING.zh-CN.md)：将具体问题转为可审阅案例、成功标准和冻结方案。
- [Component comparisons](COMPONENT-METHODOLOGY.zh-CN.md) and [metamorphic checks](METAMORPHIC-GRADERS.zh-CN.md)：定位阶段差异及有限的计算性质，不替代完整任务比较或科学真值。

## Optional evaluation capabilities / 按需扩展

| 问题 / Question | 高级文档 / Guide | 范围 / Boundary |
| --- | --- | --- |
| 多个插件是否需要组合？ | [组合评估](PLUGIN-COMBINATIONS.zh-CN.md) | 基线、A、B、A→B、可选 B→A；仅比较冻结阶段与已测试候选，保留并列和未知。 |
| 质量之外多花了什么？ | [负担视图](BURDEN-VIEW.zh-CN.md) | 分开报告上下文压力、费用和耗时；缺失记录不填零，不改原选择规则。 |
| 下一步需要看哪些证据？ | [决策视图](DECISION-VIEW.zh-CN.md) | 先展示问题、取舍和缺失项；离线 EVIDENCE.html 可展开依据，不改评分。 |
| 现有工具或较少阶段是否够用？ | [任务方案选择](TASK-SELECTION.zh-CN.md) | 根据冻结记录比较完整方案；局部阶段通过不能证明组合有效。 |
| 旧证据能否用于新输入？ | [证据桥接](TASK-SELECTION.zh-CN.md#证据迁移与桥接) | 保留旧研究，检查变化并冻结独立目标验证；输入等价不能自动迁移增益结论。 |
| 哪批新证据可能改变选择？ | [前瞻补证据](TASK-SELECTION.zh-CN.md) | 先固定候选、检查、预算和停止规则；保留每批完整矩阵与费用，筛选不能替代留出确认。 |
| 如何控制自适应补证据的风险？ | [风险控制补证据](RISK-CONTROLLED-ACQUISITION.zh-CN.md) | 以文档中的适用条件为准；费用优先级不是成功概率，普通固定样本区间不是序贯保证。 |
| 如何接续已有交付？ | [连续性交付](CONTINUITY-DELIVERABLES.zh-CN.md) | 接续记录不自动成为新的执行或有效性证据。 |
| 如何保留解读变化？ | [解读历史](INTERPRETATION-HISTORY.zh-CN.md) | 保留旧结论、理由和版本；修改解读不改写原始观察。 |

## Execution and integration / 执行与集成

- [Operations](../OPERATIONS.md)：费用硬边界、Windows/WSL 与 HPC 验收、失败恢复；未结算费用保持未知。当前付费原生启动仍受预算门禁阻断。
- [Controlled artifact handoff](ARTIFACTS.md#controlled-mcp-file-handoff-080)：经授权读取真实文件并核对摘要；默认不开放文件访问，MCP 不执行验证程序。
- [CLI / Python SDK](ENGINEERING-USABILITY.zh-CN.md) · [Workflow examples](../../examples/workflow-integration/README.md) · [Community workflows and RO-Crate](../../examples/community/README.md).
- [Online isolation](ONLINE-ISOLATION.zh-CN.md) · [Environment locks and replay](ENVIRONMENT-RECORDING.zh-CN.md) · [Evidence dependency rechecks](EVIDENCE-DEPENDENCIES.zh-CN.md).
- [Official Claude eval comparison](RESEARCH-EXECUTION.zh-CN.md)：原生 WITH 通过线与配对增益判断分别解释；退出成功不等于新增收益。
- [First-use usability protocol](FIRST-USE-TRIAL.md)：非作者计时与求助记录；维护者／AI 冒烟不能代替真实参与者。

这些文档保留能力与细节，不代表它们都经过真实宿主或外部研究验证。验收范围见[当前证据](../EVIDENCE.md)，接口边界见[冻结说明](../FREEZE.md)。
