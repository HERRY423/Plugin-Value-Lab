# 0.5.0：从“文件合格”深入到“科研推断可重算”

`replicate_effect` 从冻结的独立样本测量重算结果。它检查提交的效应量、精确置换 p 值、完整检验集合上的 BH、样本数、结论和逐个移除独立样本后的效应范围。文本声称“分析完成”不能替代实际产物。

## 范围与方法

输入是**已经得到的独立样本级数值**，例如每个供体的预先定义的标准化测量。它不是原始单细胞计数分析、伪 bulk 聚合器、DESeq2/edgeR 替代品或通用因果推断工具。聚合、归一化、协变量选择与科学问题的合理性需要各自审阅。

| 冻结设计 | 可执行约束 |
| --- | --- |
| 独立两组 | 每个 `unit` 恰好一个样本，每组至少两个独立单位；在每个 `block` 内保留原组大小枚举分配，每个 block 都必须包含两组 |
| 同单位配对 | 每个 `unit` 恰好一对，两个条件各一个，同一 block；逐对交换条件，不能拆散配对 |
| 样本身份 | 拒绝重复 sample ID、重复独立单位、训练与评估 unit 重叠、缺失配对和批次完全混杂 |
| 检验范围 | 冻结 feature 列表；每个 sample × feature 恰好一条测量，不静默去重、不填补缺失、不删基因 |
| 科学结论 | 固定 treatment − control，双侧精确检验、BH 与最小效应阈值；正确的 `not_supported` 同样是合格输出 |

效应量是组间均值差或配对差的均值，使用输入数值的原单位。双侧 p 值采用两倍较小尾概率、上限 1；精确枚举包含观测分配。浮点并列比较使用缩放空间中 `100 × epsilon × max(1, |statistic|)` 的固定容差。BH 在**全部冻结 feature**上计算。实现用 SciPy 的独立与配对精确置换测试作交叉核对；方法定义可查 [SciPy 官方文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html)。

置换检验依赖组标签在声明的 block／配对内可交换。软件要求提供理由，但不能从一个字符串证明可交换性、供体身份真实或样本独立；观察性数据仍可能有未测混杂。BH 的数学重算也不证明实际 FDR 控制条件满足。

`supported` 仅表示在此冻结契约内同时达到 q 阈值和最小绝对效应，且效应非零。`not_supported` 不等于无效、等效或证明零效应。逐个移除单位的效应范围是敏感性描述，不是置信区间，不重新计算或选择显著性结论。

这里的 p/q 检验针对科研样本对比，**不针对有／无插件的收益差**。一个插件正确算出显著或不显著结果，可以成为任务正确性的观测；插件本身是否带来收益，仍需独立的配对研究与相应统计设计。

## 可运行教学例子

仓库的 `examples/replicates/` 包含独立两组、配对两种固定数据。它们公开、人工制造，仅用于教学与回归检查，不能作为未见保留集或真实插件价值证据。

```sh
python scripts/value_lab.py replicate-reference examples/replicates/independent-spec.json --verifiers examples/replicates --output work/replicate-independent
python scripts/value_lab.py replicate-reference examples/replicates/paired-spec.json --verifiers examples/replicates --output work/replicate-paired
```

输出 `reference.json` 和 `design-audit.json`。用于真实研究时，应在观察候选结果前冻结参考材料，参考答案单独保存；不要把生成的答案放进 Agent 的保留集输入。

在 suite 中加入：

```json
{
  "id": "independent-unit-inference",
  "type": "replicate_effect",
  "dimension": "outcome",
  "weight": 1,
  "critical": true,
  "artifact": "result",
  "verifier": {
    "design": {"path": "design.json", "sha256": "ACTUAL_SHA256"},
    "data": {"path": "measurements.csv", "sha256": "ACTUAL_SHA256"},
    "alpha": 0.05,
    "minimum_effect": 0.2,
    "absolute": 1e-10,
    "relative": 1e-10
  }
}
```

真实参数由领域问题与独立审阅决定，例子不提供通用合理阈值。设计与测量引用位于显式提供的 `--verifiers` 目录，必须与冻结摘要一致。Scenario Pack 可把相同设计和测量声明为任务公开输入；评分定义、答案、决策真值和评分程序仍然禁止混入输入。设计中的 `training_units` 只核查声明的身份重叠，不能检测未披露的历史训练暴露。

## 有边界的执行、回放与诊断

- 最多 32 个 sample、100 个 feature、65,536 个分配，并限制分配 × feature × sample 总工作量为 2,000,000。超限报告验证不可用，不偷偷改成 Monte Carlo，也不让超限冒充任务失败。
- 参考设计混杂、覆盖不全、文件缺失或摘要变化，结果保持 **unknown**；数据本身不能支持计算时不惩罚模型。提交产物伪造样本数、换方向、改 p/q、删 feature 或夸大结论，明确失败并列出差异字段。
- 测量数值在计算前缩放，避免极小效应被绝对并列阈值吞没；非有限数值和计算溢出不产生通过结果。
- CLI、直接评估、Scenario Pack、账本登记和离线回放使用同一个验证器。回放预检列出设计和测量依赖，不会自动执行外来评分代码。
- 只依赖 Python 标准库的验证器可以随证据搬迁。安装包的 `science` extra 提供 h5ad 支持和测试用 SciPy 数值参照；通过测试不等于独立科研复现。

## 需要积累的领域资产

0.5.0 交付可执行契约、公开教学数据和对抗测试。后续可积累经授权的真实错误案例、领域专家审阅的正确结论与拒答边界，以及未暴露任务上的配对研究。当前仍没有真实跨宿主收益、外部专家验证或科研用户收益证据；不能把本次软件发布写成已经建立了这些证据。
