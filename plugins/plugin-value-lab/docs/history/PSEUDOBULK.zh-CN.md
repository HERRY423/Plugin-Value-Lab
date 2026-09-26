> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# 供体感知差异分析场景包

这是一个可运行、可离线检查的科研开发场景。它连接细胞与供体、计数聚合、预设过滤、归一化、设计与对比、完整检验集合、效应与不确定性。当前只有 PyDESeq2 参考适配器；没有重新实现 DESeq2 或 edgeR。独立专家审阅仍待完成，不是生物学真值库。

## 使用

核心离线验证只用标准库。运行参考拟合另需安装可选依赖 `pip install '.[pseudobulk]'`；后端必须与设计中的版本严格一致。不会自动下载数据或调用模型。

```powershell
python -B scripts/prepare_kang_pseudobulk.py PUBLIC_CACHE.h5ad --min-cells 10 --output study/inputs
python -B scripts/value_lab.py pseudobulk-reference study/inputs/design.json study/inputs/data.json --output study/reference
python -B scripts/value_lab.py pseudobulk-check submission/result.json --spec study/reference/verifier.json --verifiers study/reference
python -B scripts/value_lab.py pseudobulk-corpus study/reference/verifier.json --verifiers study/reference --output study/corpus
python -B scripts/value_lab.py pseudobulk-scenario study/reference/verifier.json --verifiers study/reference --output study/scenario
```

各输出目录必须是新目录，保留失败与旧修订。`pseudobulk-reference` 是显式运行参考后端；`pseudobulk-check` 只读冻结参考与提交文件，不拟合模型、不执行提交脚本。校验通过返回 0，失败或待审阅返回 2。场景可以继续使用既有 `scenario-validate`、`scenario-prepare` 和 `scenario-stage`；其中 public inputs 与 private scorers 分开放置，开发集不能冒充留出集。分目录不是操作系统隔离。

## 冻结契约

设计包含 `format=pvl-pseudobulk-design-1`、`task_mode`、`cell_type`、`control`、`treatment`、`min_cells`、`min_total_count`、`backend_version`、`reference_workflow`。在看差异结果之前选定细胞类型、过滤、方向与方法。不要通过丢弃不足样本来补齐配对。

输入 `pvl-cell-counts-1` 包含唯一 `genes`、`provenance` 和 `cells`。每个细胞必须有 `id/sample/donor/condition/cell_type/counts`；稀疏 `counts` 是 `[基因索引, 非负整数]` 列表，省略值表示零。重复细胞、重复基因索引、分数/负/非有限计数、供体缺失、样本归属冲突、同供体条件的多份技术样本均拒绝。当前边界为单一细胞类型、至少三个完整供体配对；技术重复合并、复杂批次或其他设计需要单独契约。

先逐样本求原始计数和，再按全部计划样本总计数过滤基因；输出保留每个样本细胞数、完整矩阵和被排除的基因。供体编号仍是声明，不认证真实独立性。设置与数据摘要绑定每个结果。

参考流程固定为 `~donor + condition`，对比 `treatment/control`，median-of-ratios 归一化，Cook's 检查和重拟合，关闭 independent filtering 以显式保留预过滤后的整个检验集合。所有基因均含零而无法采用该归一化时拒绝运行，要求另行冻结方法，不静默改用 iterative。后端产生不可估值时保留 null，不能按显著性筛掉行。保留请求与实际离散度趋势、全部拟合警告、参考适配器源码快照和依赖版本；实际后端运行的回执与结果文件及会话绑定，回执提供者身份尚未经独立认证。

## 结果格式与评分边界

`pvl-pseudobulk-result-1` 的序列化由 `value_lab/pseudobulk.py:fit_reference` 定义：

| 字段 | 内容与检查 |
| --- | --- |
| `pseudobulk` | genes、samples（id/donor/condition/cells/counts）、excluded_genes、输入与设计摘要、聚合方法、声明独立单位数；从原始细胞重新聚合后核对 |
| `method` | 后端/版本、formula、contrast、normalization、filter/Cook's 设置、alpha、请求与实际 dispersion trend |
| `normalization` | 样本 ID → size factor |
| `design_matrix` | 有序 columns 和样本 ID → 数值行 |
| `testing_family` | 预设过滤后的完整基因集合，不仅显著结果 |
| `results` | 每基因 gene/effect/standard_error/ci95_lower/ci95_upper/p_value/q_value；允许参考中不可估值的 null |
| `conclusion_scope` | `within_supplied_donors_and_cell_type` |
| `uncertainty` | `unshrunk_log2_fold_change_Wald_95_percent; not simultaneous intervals` |

基因行、样本行以及与计数同步的基因列重排不影响结论；冻结容差内的序列化精度变化被接受。重复或缺失实体不能借重排通过。

- `fixed_method`：逐阶段核对指定方法的参考输出。通过表示计算协议一致，不等于科学结论成立。
- `acceptable_solution`：同一原始计数聚合违反契约仍失败；其他方法差异与参考相同均进入人工审阅，返回 unknown，不能用精确数值相等判定所有合理方案。
- `pseudobulk_chain` 不把结果中的包名当作实际执行证明。场景另有 `backend_identity` 评分器，要求收集器提供绑定会话/产物的运行回执。未提供时仍未解决。
- 成本、供体真实性、专家审阅和新数据泛化各自保留状态，不随数值通过而升级。

## 验证器自己的检验

`pseudobulk-corpus` 固定生成 4 个等价/精度变体与 13 个定向错误产物，保存所有产物、摘要、逐阶段结果、误接受/误拒绝计数和 unknown 数。标签来自受控变换；这不是独立专家标注，更不代表真实错误分布上的准确率。新增后端、宽松输出格式或科学容许方法，需要新的有效变体与真实审阅。

参考来源：[PyDESeq2 官方工作流](https://pydeseq2.readthedocs.io/en/stable/auto_examples/plot_minimal_pydeseq2_pipeline.html)提供计数、元数据、设计和统计接口；[muscat](https://code.bioconductor.org/browse/muscat/)提供多样本细胞群聚合与现有批量差异后端的工作流依据。这里的配对设计、过滤门槛与错误语料由本项目实现，不能称为这两项目对本场景的背书。数据来源记录为 [GSE96583](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE96583) 的本地公开缓存派生物；原始 count matrix 未在本轮重新下载核验。发布数据前仍需核对数据许可。
