# 组件消融、模型饱和度与统计等价性

本次按用户提出的三项策略扩展 0.7.0。五条主流程命令保持不变；下面的开发者工具生成计划和重新评测材料，不启动模型或自动切换宿主组件。

## 1. 将插件拆成可审查的实验因素

`scripts/component_eval.py plan` 接受现有 JSON 或目录式 suite，以及三个组件的内容摘要：`prompt`、`tools`、`context`。`context: null` 明确表示不测试、也不注入动态上下文，生成四臂；提供 context 摘要则生成完整八臂。组件摘要应覆盖实际指令、工具定义和配置、上下文内容及生成规则。背景工具、模型、宿主、数据、环境与预算仍由 suite.conditions 固定。

```powershell
python scripts/component_eval.py plan study/suite.json --components components.json --output component-plan
python scripts/component_eval.py analyze component-plan/design.json --expected-id RETAINED_DESIGN_SHA256 --observations component-observations.json --artifacts artifacts --verifiers scorer-only --output component-report
```

`RETAINED_DESIGN_SHA256` 取自计划生成时的 commitment.json，在运行前另行保存。摘要证明内容绑定，不证明预注册时间。组件设计必须保持完整，不允许删掉表现不佳的臂或换入重试结果。

研究者按生成的 `assignments` 顺序启动隔离的新会话，并记录各组件的实际暴露声明。观察文件格式：

```json
{
  "format": "pvl-component-observations-1",
  "design_sha256": "预先保留的设计摘要",
  "runs": [{
    "case_id": "用例标识", "repetition": 1, "arm": "10", "execution_index": 1,
    "components": {"prompt": "计划中的内容摘要", "tools": null, "context": null},
    "record": {"说明": "完整的现有 PVL 原始运行记录，而非导入分数"}
  }]
}
```

上面是字段说明，实际值应从计划逐项复制；`record` 是常规 PVL 记录，包含原始 output/artifacts、suite_sha256、conditions、source、status、session_id、费用和人工计时。基线为 `arm: without, plugin_loaded: false`；其他臂为 `arm: with, plugin_loaded: true`，这里 with 表示启用了**该臂指定的组件组合**。分析器不篡改这些字段来制造匹配。组件开放状态仍是研究者声明，未经过宿主认证；工具可见也不等于工具被调用。

同一用例×重复次数内随机安排全部臂，固定种子和计划。重新调用现有评测器检查原始交付与正确性，而不是接受预填 success。缺失、身份污染、配置漂移、未知成本保留并阻断完整效应估计；任务失败保留为失败。基线可在多个臂的计算中复用，但它仍是同一次观察，不增加样本数、不重复计算总花费。

主效应为启用与关闭某因子时、对其他因子平均后的差。标准二阶因子效应为 `E[(2P−1)(2T−1)Y]×2`，等于差中之差的一半；三因素时对剩余因素平均。报告同时给出任务成功率效应、质量分效应和逐用例结果。重复在用例内平均，用例等权；不把重复会话或同一任务族当成独立样本，不输出未经设计支持的显著性或“组件导致收益”结论。定义参照 [NIST 因子效应与交互作用](https://itl.nist.gov/div898/handbook/pri/section6/pri615.htm)。

宿主层自动移除 SKILL、MCP 工具及上下文、执行隔离与签名认证尚未由这个入口实现。因此这版交付是**完整计划生成与证据受限的多臂分析**，不是已经完成真实 Agent 的组件级因果实验。固定工具描述本身含有指令性信息，TOOLS_ONLY 也不意味着语言信息完全为零。

## 2. 饱和度是用例复核信号

```powershell
python scripts/component_eval.py series-plan study/suite.json --models model-version-1 model-version-2 model-version-3 --output series-plan
python scripts/component_eval.py saturation series-plan/design.json --expected-id RETAINED_DESIGN_SHA256 --observations studies.json --artifacts artifacts --verifiers scorer-only --output saturation-report
```

`studies.json` 是 `{suite, records, lock}` 对象组成的数组；每个版本保留原始输入并重新评分。模型标识和顺序由操作者预先声明，工具不猜测版本先后，也不能识别可变模型别名背后的权重更新。

除 `conditions.model` 外，整个 suite 内容必须一致，包括用例输入、规则、参考文件摘要、重复数、插件版本、环境和预算。默认最新连续三个版本、每版至少三次完整重复；每次 WITHOUT 必须得分严格为 1 且满足 task 模式的交付与正确性门禁。仅 Regex 满分、过程检查通过或 metamorphic 单独通过均不能触发科学正确性饱和结论。计划中的缺失版本/重复、失败、参考漂移和协议缺失会阻断或打断连续性。

指数为“被标记用例 / 全部计划用例”；未知用例留在分母，并单独报告 `unknown_cases`。低指数不能解释成证明不饱和。WITH 的质量差、费用和耗时同时保留；WITHOUT 达到质量上限仍可能存在效率收益。触发 `SATURATION_REVIEW` 只建议研究者在**新的前瞻协议**中增加未见过的困难用例，原用例和历史结果继续保留，不自动删题、不追着失败调阈值、不宣告插件过时。

## 3. 等价性需要均值与逐项偏差两道检查

标准 Grader `type: equivalence` 可直接用于现有 `evaluate`、目录式用例、私有 scenario 和参考材料回放。`verifier` 使用分别固定的 `design` 与 `truth` 文件：

```json
{
  "id": "paired-agreement", "type": "equivalence", "dimension": "outcome",
  "weight": 1, "critical": true, "artifact": "replicate-matrix",
  "verifier": {
    "design": {"path": "equivalence/design.json", "sha256": "文件字节摘要"},
    "truth": {"path": "equivalence/truth.json", "sha256": "文件字节摘要"}
  }
}
```

完整可运行数据见 [设计](../../examples/equivalence/design.json)、[参考矩阵](../../examples/equivalence/truth.json)、[观察矩阵](../../examples/equivalence/observed.json)。它们是人工构造的工程校准材料，示例阈值不适用于真实生物结论。正式项目须在观察结果前根据研究目的说明每个指标的等价界限与最大个体偏差。

矩阵每行是一个声明独立的配对数据集或生物学重复，每列是一个预先规定的指标。程序按行列标识对齐，要求全集完整、无重复、数值有限；不支持将同一矩阵内的基因、细胞或元素展平成独立重复。独立性由研究者解释，字符串标签不能证明真实抽样独立。

对每列的 `actual − truth` 做配对 TOST：分别检验差值高于下界、低于上界，两侧 p 值的最大值用于判定。按全部预定指标做 Bonferroni 校正，支持保守的逐指标等价声明；输出对应 `1−2α/m` 区间。全局要求每个指标都通过。全局交并检验本身不要求这项额外校正；这里为同时报告逐指标结论而有意采用保守方案。方法参见 [Statsmodels 配对 TOST 契约](https://www.statsmodels.org/stable/generated/statsmodels.stats.weightstats.ttost_paired.html)；分布函数来自 [SciPy Student t](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.t.html)。

另有每列固定的 `max_abs_difference`，任何配对单位偏差超限均失败，防止正负误差抵消。Pearson 相关性完全不作为等价门禁；加常数或成倍缩放仍可产生完美相关。TOST 对均值的检验也不等价于联合分布、每个元素或生物学结论相同。

适用前提包括独立配对单位、配对差值近似正态、前瞻界限；不从数据自动选择更宽界限。样本少时可能无法证实等价，这不证明存在差异。零差值方差时不伪造 t 检验显著性：在界内仍返回 UNKNOWN，可按研究目的另外使用确定性的严格数值一致性 Grader。缺少 SciPy、参考丢失或摘要不符也保留 UNKNOWN。TOST 使用现有可选 science 依赖，不给默认安装增加科学计算包。

## 本地复核

```powershell
python -S -m unittest discover -s tests -p test_component_studies.py -v
python -m unittest discover -s tests -p test_equivalence.py -v
python scripts/check_component_methods.py --output NEW_ACCEPTANCE_DIRECTORY
```

校准报告明确标记 synthetic。软件测试、配置摘要、合成系列及报告截图均不代表真实模型跃迁、插件收益、宿主认证或独立科学验证。未调用付费服务或真实 LLM API。
