# 正向价值指标与验证设计

目标是回答“插件具体增加了哪些成功、节省了多少投入、代价是什么”。新增指标由 `evaluate` 的原始评分结果计算，输出到 JSON、HTML 和 Markdown；不需要另起服务。当前版本 0.6.0。指标定义与软件实现已经提供，真实价值仍须用实际研究测量。

## 一、正向收益与对应代价

| 指标 | 计算与分母 | 能支持的决策 |
| --- | --- | --- |
| 任务成功率提升 | 两侧成功次数 / 各自全部计划运行数之差；成功须完成、达到冻结质量底线且通过所有关键检查 | 相同投入约束下完成更多可验收任务 |
| 每 100 次净新增成功 | 100 ×（基线失败而插件成功的配对 − 基线成功而插件失败的配对）/ 全部计划配对 | 将收益换算为容易理解的交付数量 |
| 观察到的配对改善 / 退步比例 | 改善次数 / 基线失败次数；退步次数 / 基线成功次数 | 配对转移的描述，受重复编号对应关系影响，不是个体因果挽救/损害 |
| 普通任务、负对照、应弃答任务成功率 | 在预先标注的三类任务内分别计算 | 不让“什么都拒绝”伪装成有用；普通任务衡量产出，其他两类衡量边界 |
| 任务族均权质量差、改善/退步族数 | 每族先求配对质量差均值，再给各族相同权重 | 查看收益是否集中于重复很多的少数题目；与原有案例均权分数并列 |
| 节省人工分钟 / 经过秒数 | 完整配对两侧的每次平均投入之差 | 区分实际劳动与等待；运行级人工计时不含补充账本的设置、复核时间 |
| 每次成功成本及差值 | 各臂全部成本（含失败、重试与分摊开销）/ 成功数 | 衡量交付效率；零成功时为未知，不能除零或宣称免费 |

缺失/跳过/不可比配对继续占据计划分母；未知不能当失败来制造挽救。完整率无法计算时保留 null，并给成功率的缺失上下界（不是置信区间）。全局条件混杂或缺证时，仍可检查原始计数，但 `benefit_claim_eligible=false`。模拟永远不是实际增益；关键失败与回退继续阻断正向结论。

## 二、从 3 次先导运行到足量研究

每臂 3 次可以检查采集链路和初步随机性，不足以默认支持普遍有效。增加同题重复不等于增加独立任务族。先确定适用任务分布、最小有意义差异、主要指标与失败约束，再冻结抽样和停止规则。独立留出任务、按顺序随机或交错的配对、盲评和实际外部复现应分别有记录。

在 suite 的 `policy` 中可选加入：

```json
"power_plan": {
  "expected_family_sd": 0.20,
  "minimum_detectable_delta": 0.10,
  "alpha": 0.05,
  "power": 0.80
}
```

这里规划的终点是**任务族均权质量差**，不是成功率、成本或原有案例均权分数。采用双侧正态均值差近似：`ceil((z(1-alpha/2)+z(power))² × SD² / delta²)`；上例得到 **32 个独立任务族**。SD 应由独立先导研究或合理外部依据提供，不用本次观察到的效果回算“事后功效”。公式参考 [NIST 样本量规划](https://www.itl.nist.gov/div898/handbook/prc/section2/prc222.htm)。

报告列出目标、现有任务族数与缺口。满足规划数仅表示计划规模达标，不证明独立性、实际功效或插件有效。方差估计、小样本、族内相关、不等权、二元成功率、多个主要终点及中途查看结果都需要相应设计修正；正式研究应在执行前由统计审阅者确定最终方法，不把这项近似用于自动显著性门槛。

确认性正向主张应要求预先选定的主要终点区间下界超过业务最小有意义提升；效率主张同时要求预设质量非劣效与成本节省的区间条件。最小可检出差异是对零差异的规划参数，不等于证明超过业务阈值的设计。当前 bootstrap 仍是探索性描述，`PROMISING_LOCAL_SIGNAL` 仍仅表示提交范围内的局部信号。独立复现后才能讨论更广泛适用性，不用一个评分把这几级证据合并。

## 三、让完整成本与结算证据分开

`complete_category_coverage` 表示类别覆盖；不表示价格真实或已结算。`cash_evidence` 单独列出每次模型/工具费用是否声明 `basis: "settled"` 且有唯一 `evidence_ref`（账单行或可复查明细引用）。补充现金条目须逐项结算；judge/setup/retry/other 不能仅靠 `included` 通过更强门槛，必须 itemized 或明确 not_applicable。已包含明细未完成对账时仍缺证，不能为过门槛重复记账。

```json
"cost": {
  "model_usd": 0.012,
  "tool_usd": 0,
  "human_minutes": 2,
  "basis": "settled",
  "evidence_ref": "invoice-2026-09:line-001"
}
```

该例仅说明字段，必须填写真实记录，并保留支持 2 分钟的原始计时；不要把估价改名为结算。`policy.require_settled_costs: true` 可在冻结前启用更强成本门槛；估算、缺引用或类别不全时阻止正向结果。默认保留旧研究的估算条件性比较，报告明确展示 `saving_claim_basis`。`settled_saving_claim_eligible` 还要求完整非模拟可比证据及严格负的成本差。

“结算引用齐全”仍不认证账单、执行或提交者身份；人工按冻结时薪折算，永远不伪装成现金支出。已有时薪敏感性分析可检查估价改变时结论是否翻转。缺失 native USD 继续未知；按公开费率计算的价格继续标为 estimate。不得由软件补造账单或人工作业记录。

## 四、完成状态

- 已实现：上述指标、分层与固定分母，前瞻样本量规划，结算引用检查及可选门槛，三种格式的报告。
- 仍需真实材料：足量独立任务、实际模型执行与结算明细、独立评审和确认性研究。新增指标不能把旧先导研究自动升级为已证明有效。
- Epistemic Plugin Arena 仅为[后续展望](EVIDENCE-LAYERS.md)，不是这些指标或证据边界的前提。

## 五、新冻结研究的评价目标与失败处理

旧 `success.rescued/harmed/rescue_rate/harm_rate` 字段仅为兼容历史研究保留，显示名称改为观察到的改善/退步。不会改写旧研究的失败分母或总评。只有在采集前加入并冻结以下完整配置，新报告才增加 `value_interpretation`：

```json
"value_interpretation": {
  "version": 1,
  "primary_estimand": "scientific_correctness",
  "pairing_rationale": "同一任务与随机交错的执行区组；重复编号不是个体反事实",
  "task_distribution": "明确填写计划覆盖的人群、任务族和抽样范围",
  "failure_rules": {
    "scientific_correctness": {"measurement":"unknown","tested_system":"failure","provider":"unknown","infrastructure":"unknown","unclassified":"unknown"},
    "runtime_reliability": {"measurement":"unknown","tested_system":"failure","provider":"failure","infrastructure":"failure","unclassified":"unknown"},
    "full_delivery": {"measurement":"unknown","tested_system":"failure","provider":"failure","infrastructure":"failure","unclassified":"unknown"}
  }
}
```

这个例子将有证据的系统错误记为完整交付失败，同时保留服务商故障对科学正确性的不确定性。可按事先确定的研究问题把允许的 failure 改成 unknown；测量失败和未知归因必须 unknown，服务商/基础设施不能被算成科学错误。所有缺失、跳过、无法信任的观测保持 unknown，仍占计划分母。

单次记录可附 `failure_observation: {"class":"provider", "evidence_ref":"trace.jsonl:42", "rationale":"实际服务端错误"}`。必须指向保留证据；这是提交者归因，不是经过认证的因果判定。旧 `failure_kind` 不被自动推断成新分类。完成运行但评分器不可用可标 measurement：运行完成仍可观察，科学正确性未知。

新报告提供三种评价目标的任务分布成功率差、任务族均权成功率差、固定计划分母的缺失上下界、2000 次固定种子描述性族 bootstrap。少于两族或有未知时不生成区间；家庭标签不证明独立性，重复次数不替代族数。现有 `power_plan` 仍针对质量差，不能冒充新成功率终点的样本量设计。

`check_claims` 保留各项原始评分、验证回执与观测问题，费用不齐不会抹去数值诊断；现金节省、供体独立性、新数据泛化另行标记。任何新端点都不提升既有 `verdict` 或 `comparison_eligible`，模拟数据始终 SIMULATION_ONLY。
