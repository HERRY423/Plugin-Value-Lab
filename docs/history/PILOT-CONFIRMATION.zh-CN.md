# 从先导方差到事前确认 / Pilot-to-confirmation handoff

本路径仍回答一个问题：配对、冻结、可复算地判断插件对一项具体任务有没有增益。它把已有先导材料交给样本量规划，再把**事前固定的实际收益阈值**用于新确认材料。先导摘要、规划成功或统计支持都不自动授权执行、采用插件或作科学结论。

它沿用 `plan-use` / MCP `plan_plugin_use` 的独立 evaluate context，以及 `suite.policy.power_plan`，不增加启动模型的工具。旧四字段计划和 v2 规划保持原意；本页描述 v3。v2 的“检测非零差异”不等于 v3 的“下界超过有实际意义的阈值”。

当前 v3 限定为单插件两臂、完整固定样本设计。多插件组合、组件因子实验和自适应采集批次会明确拒绝直接套用 v3；这些需要另行定义比较与停止设计。已有任务选择和条件使用建议不能覆盖 v3 未确认的结果。确认分支缺失或不完整时保持证据不足，不能退回旧均值判断。

## 1. 先导输入必须可以复核

`sample_size_plan.pilot` 是 version 1 的完整数据包，包含以下字段；不把只有三个标准差的手填表当成先导记录。

| 字段 | 内容与限制 |
| --- | --- |
| `version` | 整数 `1`。 |
| `pilot_id` | 可引用的先导身份。 |
| `evidence_type` | `real` 或 `synthetic`；这是提交者声明，程序不认证来源。 |
| `endpoint` | 当前仅支持 `outcome_quality`，每臂评分在 `[0,1]`。 |
| `task_source` | 任务的来源与抽样过程，足以供研究者复核。 |
| `independence_rationale` | 为什么任务族可视为独立、如何避免近重复或共同来源泄漏。 |
| `records` | 全部完整配对观察，字段见下表。 |

| 每条配对记录 | 要求 |
| --- | --- |
| `family_id`, `task_id`, `input_sha256` | 声明族、任务及输入字节的 SHA-256。一个任务只能属于一个族和输入摘要；相同输入不能换任务名重复计数。 |
| `repetition` | 从 1 开始连续的正整数；不缺槽位，不挑最好的一次。 |
| `with_score`, `without_score` | 同一评分定义下的两臂结果，均在 `[0,1]`。 |
| `with_run_id`, `without_run_id` | 各次执行的不同身份，不跨任务、重复或两臂复用。 |
| `source_ref` | 原始记录或受控证据的引用；摘要器不会自动抓取、认证该引用。 |
| `with_session_id`, `without_session_id` | 可选；提供时必须成对且不能跨执行复用。缺少时明确报告会话来源不完整。 |

当前估计器只接受平衡嵌套设计：至少 3 个声明的任务族，每族至少 2 项任务，每任务至少 2 次配对重复，所有族的任务数相同，所有任务的重复数相同。这是计算可识别性的输入下限，**不是充分先导样本量的建议**。少于 10 个族会提示先导过小；十个族也不自动充分。

未完成、缺失或无法评分的先导不能悄悄删除后包装成完整先导。保留原矩阵和失败记录，重新说明可估计范围；当前接口不提供不平衡或缺失数据的方差估计器。

## 2. 交接报告保留什么

程序从 WITH 减 WITHOUT 的配对差值重新计算族间、族内任务间、任务内重复方差；保留 ANOVA 的原始分量、平方和、自由度和均方。负分量保留原值，只有用于标准差计算时截为零。两臂描述性协方差也保留，并核对 `Var(WITH-WITHOUT) = Var(WITH) + Var(WITHOUT) - 2 Cov(WITH,WITHOUT)`；这不把汇总的所有重复变成独立样本。

不确定性采用整族重抽样，保留族内任务与重复结构。固定分析随机数种子只复现本地 bootstrap，**不是**模型生成的受控种子，也不是独立执行的证明。报告保存原包、原包摘要、任务/输入/执行身份及警告；已有摘要只有在按原包重新计算完全一致时才可作为可信的派生对象继续处理。

`variance_policy` 必须说明：

- `basis: "bootstrap_upper95"`：使用每个标准差名义双侧 95% bootstrap 区间的上端，即 97.5% 分位数。它是近似估计，不是总体方差硬上界；三个分量的单独区间也不是同时置信域。
- `sd_floor`：明确给出 `between_family_sd`、`between_task_sd`、`within_task_sd` 三项下限。边界/退化分量必须有独立依据的正下限；其他分量也可采用事前说明的保守下限。
- `rationale`：说明下限的来源和数值理由。不能用“为了让研究通过”作为理由；相同先导分数不能证明未来方差为零。
- `transfer_rationale`：说明先导与确认的任务总体、评分量尺、插件/模型/宿主和测量条件为何允许迁移方差。输入身份不重叠不代表两个阶段来自可比总体。

规划用的每项 SD 是 bootstrap 上端与声明下限的较大者。先导均值不用于自动选取有利的预期确认效应；有意义阈值和预期效应需要单独事前说明。所有 `real`、来源、时间和独立性声明仍需研究者核查，哈希不认证这些声明。

## 3. 冻结实际要确认的规则

v3 顶层包含 `version: 3`、`alpha`、`power`、`sampling_basis`、`method`、`tasks_per_family`、`repetitions_per_case`、`max_families`、`pilot`、`variance_policy`、`rule`。抽样基础必须声明为 `independent_representative_families`。这是适用条件，不能通过改字符串把便利基准集变为随机样本。

`rule` 中要明确：

| 内容 | 事前选择 |
| --- | --- |
| 主终点 | `primary_endpoint: "equal_family_quality"`；族内先平均，族间等权。 |
| 质量目标 | `objective: "quality"`，`minimum_gain` 为实际有意义的最低质量增益；非劣界值与两项节省目标为零。 |
| 效率目标 | `objective: "efficiency"`，`minimum_gain: 0`，正的 `noninferiority_margin`，以及 `minimum_cost_saving_usd`；质量非劣与总成本节省都须成立。 |
| 规划备择值 | `anticipated_quality_delta` 必须严格大于对应质量边界；效率模式的 `anticipated_cost_saving_usd` 必须严格大于最低节省值。 |
| 任务退步上限 | `max_case_regression`；总体正结果不能抹掉超限任务退步。 |
| 成本范围 | `max_total_cost_usd`、`cost_per_run_bound_usd` 及 `cost_bound_rationale`；说明未来完整成本可落在声明范围内的依据。 |
| 停止规则 | `stopping: "fixed_sample"`，`confirmation_not_started: true`；程序不支持观察结果后改目标、提前成功停止或追加到显著。 |

例如希望确认至少 0.05 的质量增益，而预期 0.15，则规划的距离是 **0.15−0.05=0.10**，不是检验零效应时的 0.15。质量分数 0.05 指量尺上的五个百分点，不是相对提升 5%。最终质量单侧下界必须**严格超过** `minimum_gain`。非劣模式则要求质量下界严格超过 `-noninferiority_margin`，同时节省下界严格超过事前最低节省值；“差异不显著”不是非劣证据。

`suite.policy.quality_weighting` 必须为 `family`，`objective`、`max_case_regression` 与规则一致；质量模式的 `min_quality_delta` 必须等于 `minimum_gain`。保留旧质量底线、任务成功、关键失败、额外方法学限制及已有 `require_cost_saving` 门槛；新推断不会覆盖旧门槛或改写旧结论。

## 4. 两种方法不能事后择优

| 方法 | 规划与最终下界 | 假设与代价 |
| --- | --- | --- |
| `paired_t` | 以先导交接的分量计算族均值 SD，使用单侧非中心 t 功效；结果采用族均值的单侧 t 下界，自由度为族数减一。 | 需要独立、可代表目标总体且适合正态模型的族均值，方差迁移需要依据；小样本下偏斜/离散均值尤其需要审查。需安装可选 `planning` 依赖；依赖缺失不暗中换法。观察到零族间方差时不提供虚假的精确 t 下界。 |
| `hoeffding` | 根据族质量差值 `[-1,1]` 给保守功效下界和单侧置信下界；质量下界扣减 `sqrt(2*log(1/alpha_endpoint)/F)`。 | 需要独立族与可靠的事前取值范围，不要求正态。样本量可能很大；先导 SD 仍展示供审计，但不进入此保守样本量公式。增加任务或重复不能缩窄该方法使用的最坏族取值范围。 |

效率模式有质量和总成本节省两个共同主终点：对 alpha 作 Bonferroni 分配，对漏检概率作联合界分配。总成本节省下界始终使用声明范围下的 Hoeffding 方法，即使质量选用 t。仅观察到本次成本未超界，不能证明未来总体满足该取值范围假设。

规划比较指定的族内任务数 K、每臂重复 R 网格，给出独立族数 F、实际任务数 `F*K`、生成次数 `2*F*K*R`、条件功效及总成本范围。推荐只在可行网格内最少化生成次数；不是所有研究设计中的最优解。超过搜索上限或成本上限时保留不可行结果，不自动增大上限。

功效的范围是 `NAMED_STATISTICAL_ENDPOINTS_ONLY`：例如 80% 仅针对声明的质量检验，或质量与成本的共同主检验。它不表示有 80% 概率同时满足每项任务成功、没有关键错误、所有退步限额及预算等额外门槛。不能把统计功效写成最终产品通过率。

## 5. 现有入口的使用流程

从源码根目录运行制造示例，输出目录必须是新的：

```text
python scripts/value_lab.py plan-use examples/confirmatory-plan.json --output work/confirmation-plan-example
```

MCP 使用同一个对象：把 [示例 JSON](../../examples/confirmatory-plan.json) 作为现有 `plan_plugin_use` 的 `context`。它只有 `schema_version: 1`、`intent: "evaluate"`、`task` 和 `sample_size_plan`；不与选插件、证据桥接等模式混装。

1. 阅读 `PLAN.md` 与完整机器输出中的 `sample_size.pilot_summary`、规则、SD依据、警告和设计网格。示例是 **3族×2任务×2配对重复** 的制造分数，共12对、24次制造的生成记录；不是已执行模型会话。示例的来源引用、运行ID、输入摘要和方差下限只演示契约。
2. 换成经授权的实际先导原包，审查任务独立性、评分和迁移依据；选择确认方法、实际意义阈值、预期效应、成本范围与最终 F/K/R。`paired_t` 示例需可选 SciPy 支持；改为 `hoeffding` 是另一种需要**事前**选择的设计。
3. 构建新确认 suite，把整个审核后的 `sample_size_plan` 复制到 `suite.policy.power_plan`。每个 case 给出新的 `id`、`cluster`、真实输入 `input_sha256`；族、任务、输入不能与先导重叠。确认的每族任务数必须平衡并属于规划网格，`runs_per_case` 也须属于网格。
4. 用现有 `suite-check` 或 MCP `validate_value_suite` 检查真实设计相对所需族数的缺口；在任何确认观察前 `freeze`。只读规划不采集数据。冻结后修改阈值、终点、方法、样本数或输入是新方案，不能给旧结果补一个事前身份。
5. 在已有执行/数据/费用授权范围内采集完整确认矩阵。保存每次执行身份、`started_at`、与 case 一致的 `input_sha256`、原始产物、失败和成本。与先导的执行身份不得重用；两条确认记录也不得复用同一执行身份。声明时间不能认证事前性。
6. 用现有 `evaluate`，提供同一个冻结 lock、records、成本账本及适用的产物根目录；查看报告中的 `confirmatory_analysis`。启用 v3 的使用卡、决策摘要、公开卡及 CI 通过条件同时要求确认成立；未确认不能仅凭均值局部信号生成正向使用建议或 CI 绿色。确认成立仍不单独生成采用授权。

不能靠换族名发现所有语义近重复；字节哈希也不能发现同一问题的改写。源任务划分、真实独立会话、未来任务总体及原始证据仍需外部复核。先导材料不可作为确认新增样本，确认开始后不能再从确认结果校准先导方差或选择有利阈值。

## 6. 成本与结果的解释

这里的总成本是**现金费用加按冻结时薪折价的人力工作**。现金需完整分类和不同结算引用；人力需实际时间区间与冻结折价，不能称为供应商结算现金。费用未知、估算、遗漏重试或审阅成本不能变成“零成本”。效率推断需要可归属具体运行的成本观察；把一张共同设置账单均摊到各族，不能使该账单成为独立样本。

`cost_per_run_bound_usd` 和 `max_total_cost_usd` 是规划与分析的完整成本界限，**不是供应商执行费用硬上限**，不会解锁付费原生执行，也不会设置账户预算。新的执行继续遵守[运维费用门禁](20261011/docs/OPERATIONS.md#native-eval-budget-gate)。

| `confirmatory_analysis.status` | 可支持的解释 |
| --- | --- |
| `SIMULATION_ONLY` | 先导或确认含制造证据；只能展示规则与计算，`statistical_support` 为 false。 |
| `INSUFFICIENT_EVIDENCE` | 缺冻结匹配、事前时间/身份、完整可比矩阵、规划所需族数或完整成本等；先读具体原因。 |
| `NOT_CONFIRMED` | 提供的材料可分析，但一个或多个事前条件未满足；不等于已证明无效或等价。 |
| `CONDITIONALLY_SUPPORTED` | 在所声明的抽样、分布/范围及来源条件下通过事前规则；不是认证因果、科学正确性、独立复现或采用授权。 |

`adoption_authorized` 与 `changes_legacy_verdict` 保持 false。旧 `verdict` 仍是描述性历史字段，不能单独代表 v3 通过；普通描述性结论、各任务失败与证据缺口继续保留。v2 的语义不变。当前交付的是本地方法与制造示例；没有因本文件新增真实先导、真实确认研究、独立评审或付费执行授权。

实现与输入细节：[pilot.py](../../value_lab/pilot.py)、[confirmatory.py](../../value_lab/confirmatory.py)；一般统计范围见[方法学](20261011/docs/METHODOLOGY.md)。

Codex 采集已通过[确认性接入](CODEX-EXECUTION.zh-CN.md#7-从采集接入确认性评估)连接到本评估器：冻结 v3 规则，保留首次尝试与原始输出，按全部尝试对账费用，再通过同一 `core.evaluate()` 复算。该接入不改变上述统计、真实性和采用边界。
