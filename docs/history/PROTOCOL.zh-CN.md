> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# 一次可复查的插件增益评估

本协议适用于 Plugin Value Lab 0.2.0-alpha.1。字段以 [CONTRACT.md](../../CONTRACT.md) 为准。报告是评估辅助材料，不能充当外部认证；日常任务可先按使用规划直接完成，只有明确的评估需要才进入本协议。

## 1. 写清楚要作出的决定

先记下目标用户、被测插件及版本、目标任务范围和采用条件。例如：“判断这个插件是否让内部工单分类在现有模型上达到质量底线，同时减少计入人工复核后的成本。”不要只写“看看插件有没有用”。

选择 `evidence_type`：`synthetic` 是教学或模拟，`local` 是本地实际记录，`external` 是外部实际记录的声明。最后一项仅标示来源，不会让工具自动认证独立性或科学有效性。

## 2. 设计任务与验收条件

每个 case 有稳定的 `id`，相关材料和变体共享 `cluster`。为任务预先写出 `prompt` 和可检查的 outcome graders。覆盖普通任务、负对照与需要保留不确定性的任务。不要为了让插件胜出而刻意只选插件擅长的任务；如果研究范围本来很窄，公开写明范围。

`contains`、`not_contains` 适合明确的字面约束，不代表语义真实性；`json_equals` 适合固定结构和值；`human` 适合必须由评审者理解的判断，必须有 rubric、真实 reviewer 和 rationale。`critical` 指定不允许被其他得分补偿的关键标准。`process` 规则只作诊断，每个任务仍需至少一项 outcome 规则。

配置评估目标、质量提升阈值、插件侧质量底线、允许的最坏单例退步、最少任务簇数、成本要求和人工小时单价。`policy.objective` 默认 `quality`，可明确选择 `efficiency` 来评价保持平均质量时的成本节省。目标与阈值来自业务决策，而非默认值天然正确。看完结果再改目标或阈值，应另开修订后的研究并报告原因。

新增[正向价值指标与验证设计](VALUE-METRICS.zh-CN.md)：报告给出成功率、净新增成功、挽救/损害率、三类任务分层及每次成功成本。可在冻结前设置 `policy.power_plan` 规划独立任务族规模；3 次重复只作先导，不视为足量独立样本。`policy.require_settled_costs=true` 另要求完整类别与结算引用，避免估算费用通过更强成本门槛。

## 3. 冻结实际比较条件

`conditions` 中的模型、宿主、工具、环境和预算必须明确。除了被测插件，其余条件在两侧保持一致。使用独立会话和隔离材料，记录插件实际加载情况，检查 baseline 是否通过其他全局技能、项目指令或已安装副本获得了相同帮助。

```text
python scripts/value_lab.py freeze path/to/suite.json --lock path/to/lock.json
```

冻结后不覆盖原方案与 lock。锁定哈希检测本地一致性，不能证明方案先于所有试验制定，更不能证明独立预注册。若已经看到相关结果，就标明探索性或回顾性分析。

## 4. 收集每一条计划记录

每个 case、repetition 和 `with`/`without` 组合都需要一条记录。`session_id` 必须唯一；`suite_sha256` 对应冻结方案。填写观察到的 `conditions` 和 `plugin_loaded`，不要从期望条件生成“已观察条件”。随机或交错执行两侧可以减少时间、缓存和顺序偏差。

失败仍有记录：`error`、`timeout`、`aborted`、`skipped` 保留状态与原因，不转换为成功，也不从分母消失。当前实现把错误、超时和中断保留为零分运行；跳过或缺失观察阻止完整比较。对于 `error` 和 `aborted`，仅当原始依据支持时，才设置 `failure_kind: "task"`；基础设施故障或未分类故障不能归因于插件价值。保存原始输出与任何人工评审理由。人工评分缺失时保持 null，而不是让助手替人签名。

成本分别记录 `model_usd`、`tool_usd` 和 `human_minutes`。未知金额使用 null。人工分钟只能由 `human_intervals` 的 UTC 起止记录支持；同一人的重叠间隔不能重复计费。空列表仅表示声明没有人工工时，不能证明实际没有工作。`duration_seconds` 是经过时间，不能据此填入人工时间。

有 `human` 规则时，可用 `review-pack SUITE RECORDS --output DIR` 生成去除显式组别的复核包，再用 `apply-reviews SUITE RECORDS --mapping MAPPING --decisions DECISIONS --output NEW_RECORDS` 合并实际判断。只将 reviewer 目录交给评审者，操作者保留解盲映射。原文可能泄露组别，这不构成技术隔离或独立性认证；输出写入新记录文件，已存在的评审不能静默覆盖。完整示例见 [README](../../README.md)。

## 5. 使用 Claude 原生执行时

参考 [Claude 官方原生评估说明](https://code.claude.com/docs/en/plugin-evals) 操作当前宿主。先导出任务，再由实际执行者在明确预算和授权下启动评估。适配层仅生成资料或转换已有结果，不自动支付或运行模型。

```text
python scripts/value_lab.py export-claude path/to/suite.json --output path/to/native-cases --plugin path/to/target-plugin
python scripts/value_lab.py native-report path/to/native-result.json --output path/to/native-report
python scripts/value_lab.py import-claude path/to/native-result.json --suite path/to/suite.json --output path/to/runs.jsonl
```

导入器无法凭空恢复未记录的模型条件、实际隔离、原始输出、会话标识或费用。缺失保存在 `import_issues` 中，阻止强结论；可以查看已有分数，但不能把部分资料宣传为完整比较。人工补录必须依据原始日志，保留来源和修订记录。原生系统报告的费用可能是估计值，不等于已结算账单。

导出的 `human` 规则仅转为模型评分诊断，不能满足人工评议要求；`json_equals` 没有等价原生规则时明确拒绝导出。生成的参数计划需要显式原生预算，且不会自动复制任务到被测插件或执行。`native-report` 可先查看现有原生诊断，不必为了查看结果而伪造完整账本。

## 6. 生成并审阅报告

```text
python scripts/value_lab.py evaluate path/to/suite.json path/to/runs.jsonl --lock path/to/lock.json --output path/to/report
```

依次看 completeness/blockers、关键失败与单例退步、质量差、不确定性、费用差、claim limits。两侧都是满分意味着测得质量差为零；费用完整且更低时，才有额外的效率信号。缺 baseline 不能证明增益。模拟记录无论看起来多好，都不能证明实际插件的价值。

默认 `quality` 目标要求质量差严格大于零，并同时达到预设提升阈值和质量底线；单纯省钱且质量相同不会通过该门槛，成本差仍会展示。预先选择 `efficiency` 目标时，要求平均质量不下降、达到质量底线，且完整成本严格降低；不使用 `min_quality_delta`。两种目标均保留关键失败、单例退步和完整性门槛。效率信号不能解释为统计学非劣效性。

`require_cost_saving=false` 不取消费用完整性要求，效率目标仍强制要求成本降低。费用是平均每次计划执行的总成本，不是整个研究的总账。按任务簇重采样的区间是探索性描述，没有作为显著性门槛，也不能把任务簇标签当作已经证明的统计独立性。

`--gate` 用于受控流程：退出码 0 仅代表完整、非模拟的正向局部信号；1 表示无增益或退步；2 表示证据不足或模拟。它不是发布授权、科学审批或外部效益认证。

## 7. 对外表达与复现

一个合适的结论应限定到具体版本、模型、宿主、任务集和日期，并包含两侧结果、费用是否齐全、失败与退步、任务簇数量、不确定性和筛选方式。共享方案、冻结信息、去敏后的记录和评分依据，让别人能够质疑或重做评估。

如果需要声称实际用户节省时间、科研结论更可靠或商业采用更成功，应另收集对应证据。保存或导出报告不代表获准传输私有代码、未公开稿件、患者资料或向外部对象发送消息。科研示例仅供学习评估流程；真实科学主张由有资质的领域人员依据真实材料裁决。
