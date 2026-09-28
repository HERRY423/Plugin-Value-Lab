# 科学蜕变 Grader：比较成组计算之间的科学关系

2026-09-28，根据用户明确请求增加受限的标准 Grader 扩展。版本仍为 0.7.0；五步主流程、六个默认 MCP 工具保持不变。

`type: metamorphic` 已接入 suite 校验、声明式 `evals/graders/*.md`、本地评测、私有 scenario、原生结果离线证据、回放材料清单及 HTML 报告。评分只读取固定版本的设计和实际提交的数值产物，不调用 Regex 或 LLM，也不执行产物中的代码。

## 当前五类标准关系

| relation | 输入变化 | 输出检查 | 使用前提 |
| --- | --- | --- | --- |
| `row_permutation` | 按冻结 ID 顺序重排矩阵行 | 按输出行、列 ID 对齐后数值一致 | 方法对样本顺序不敏感；元数据应按 ID 关联 |
| `feature_permutation` | 重排矩阵列 | 按实体 ID 对齐后数值一致 | 方法对特征顺序不敏感 |
| `positive_scale` | 指定输入列乘正数 | 每个输出列按声明因子变化 | 研究者明确知道该统计量的尺度性质 |
| `partition_invariance` | 重排样本行 | 保持分区成员关系，允许聚类标签改名 | 比较同一组实体；算法随机性须由实验条件控制 |
| `contrast_reversal` | 反转 treatment/control 对比 | 效应取负、区间两端取负并交换；SE、p、q 不变 | 同一次拟合、固定检验家族、未收缩、双侧 Wald 检验 |

对比反转的性质来自线性对比和双侧 Wald 统计量的数学对称性；本实现将适用条件冻结到 `context`。DESeq2 的对比、收缩、过滤流程见[官方说明](https://bioconductor.org/packages/release/bioc/vignettes/DESeq2/inst/doc/DESeq2.html)。不能把单侧检验、不同过滤集合或分别重拟合的两套结果套入这个严格关系。

蜕变测试检查多个输入/输出间应成立的关系，有助于发现缺少完整标准答案时的错误，但不会凭空提供正确性标准。参见[科学软件蜕变测试研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC7252536/)。本次实现和测试均不等同于独立科学验证。

## 研究人员的实际步骤

先确定一个研究上有效的关系，写明 `rationale`，冻结完整实体集合、变换参数和容差，再运行原始输入及全部变换输入。不要看到结果后选择有利的变换或放宽容差。

可运行的入门例子是 [column-sum.design.json](../../examples/metamorphic/column-sum.design.json)。它检查矩阵按列求和：样本重排、特征重排、单列放大。对应 [适配器](../../examples/metamorphic/column-sum.py) 同时提供两种故意错误：只算第一行、始终返回零。

```text
python -S scripts/check_metamorphic.py --output NEW_CALIBRATION_DIRECTORY
```

它实际执行 12 次合成适配器，生成 `inputs/`、运行结果、`evals/`、`assessment.json`、HTML 报告。正确程序通过；只算第一行的程序触发关系失败；全零程序可以满足全部关系，但被独立的基准算术检查拒绝。该示例不调用模型，也不代表插件增益研究。

用于真实研究时，设计是 `pvl-metamorphic-design-1`：

- `source.matrix`：`row_ids`、`columns`、二维有限数值 `values`，严格形状和唯一性。
- `source.context`：固定的方法、对比、元数据、随机种子等条件；这些条件属于声明，仍需执行证据支持。按行关联的元数据应使用 ID 映射，不能依靠未经变换的数组位置。
- `output`：数字矩阵或聚类分区的完整实体/列集合。
- `tolerance`：预先声明的 absolute/relative，范围 0..1e-4。实现按元素使用绝对/相对容差，不接受布尔值、NaN、Infinity 或 null 冒充结果。
- `relations`：1..32 个带唯一 ID、标准 relation、parameters、适用理由的检查。每个变换都必须改变输入；不得以重复的 identity transformation 增加通过次数。

结构规范见 [JSON Schema](../../schemas/science/metamorphic-design.schema.json)；运行时继续检查数学前提、跨字段对应和矩阵预算。结构合法不是科学设计有效。

```text
python -S scripts/metamorphic_eval.py catalog
python -S scripts/metamorphic_eval.py prepare DESIGN.json --expected-id DESIGN_CANONICAL_SHA256 --output NEW_INPUT_DIRECTORY
```

`prepare` 只导出原始输入和变换输入，不执行研究代码。将这些输入交给自己的受信任分析程序或已隔离 Agent。每个结果保存成 `ID.result.json`，格式为：

```json
{
  "input_sha256": "该次实际读取的输入的 canonical JSON SHA-256",
  "status": "completed",
  "output": {"row_ids": ["sum"], "columns": ["gene-x", "gene-y"], "values": [[12, 21]]}
}
```

`status` 可以是 `completed`、`error`、`timeout`。聚类输出使用 `row_ids` 和字符串 `labels`。摘要采用 UTF-8、按键排序、无额外空白的 JSON；不是原文件字节摘要。示例适配器展示了准确计算方式。不要在未实际执行时只复制预期输入摘要作为运行证明。

```text
python -S scripts/metamorphic_eval.py collect DESIGN.json --expected-id DESIGN_CANONICAL_SHA256 --results RESULT_DIRECTORY --output NEW_COLLECTED_DIRECTORY
python -S scripts/metamorphic_eval.py check DESIGN.json --expected-id DESIGN_CANONICAL_SHA256 --observations NEW_COLLECTED_DIRECTORY/observations.json
```

输入清单中的摘要绑定内容，不验证是谁执行，也不认证运行。评分 receipt 明确标记 `SUBMITTED_ARTIFACTS_NOT_ATTESTED`；真实执行仍须配合既有 collector/科学环境记录。Grader 不会补跑缺失任务，不会隐式调用科学包、网络或模型。

## 标准 Grader 配置与结果门槛

```json
{
  "id": "scientific-relations",
  "type": "metamorphic",
  "dimension": "outcome",
  "artifact": "metamorphic_results",
  "weight": 1,
  "critical": true,
  "verifier": {
    "design": {"path": "study/metamorphic-design.json", "sha256": "设计文件的实际字节 SHA-256"}
  }
}
```

`artifact` 指向收集后的 `observations.json`。设计放在 scorer root，提交产物放在 artifact root；设计引用使用实际文件字节摘要，与命令行使用的 canonical design 摘要刻意区分。现有 `freeze/evaluate` 和可共享 `graders/*.md` 均可使用该配置。

每条关系返回 PASS / FAIL / UNKNOWN、变换输入摘要、完整分母、最多 20 个具体反例、错误数及最大绝对误差。已有失败优先于未完成；缺运行、执行失败、输入摘要不匹配保持 UNKNOWN；提交了结构/数值错误的结果则 FAIL。坏的私有设计属于评测不可用，不归咎于被测 Agent。

关系通过只说明一致性。必须另配任务正确性 oracle，例如完整基准结果、受限解析解、已有 `pseudobulk_chain` / `replicate_effect` / 数值参考或真实人工判断。仅含 metamorphic 的案例与私有 scenario，即使质量分 100%，正确性也保留 UNKNOWN；额外加一条文字匹配不能解除这一限制。关系失败也不会因其他 Grader 提供 99% 分数而被掩盖。

对无完整标准答案的问题，可将关系作为错误探测与缩小审查范围的工具，保留正确性未定。未知比伪造 oracle 更合适。

## 扩展协议与适用边界

新增关系需要同时提供：版本化名称和参数验证、确定性输入变换、实体对齐的结果比较、适用条件与不适用情形、正例/缺失例/定向错误测试、更新 schema/catalog/freeze 清单。当前注册表是经审查的源码 allowlist，不从提交内容动态导入第三方 Python，也不解释用户提供的表达式。发生不兼容变更时新增格式版本，不改写已冻结实验。

不能将“打乱标签后必然不显著”作为通用关系：随机结果仍可能出现低 p 值。也不能把 RNA 原始 counts 成倍放大理解成 p 值不变；样本精度和模型估计可能改变。随机模型、非确定性 GPU、聚类局部最优或缺失统计量，需要额外预先声明的重复/分布判据；当前版本没有伪装成覆盖这些情形。null 不被静默丢弃。

当前评分用 Python 标准库即可完成；矩阵每份最多 200,000 元素、32 个变换，避免直接载入任意大型 h5ad。大型科学任务由适配器输出完整、受限的数值统计表；降维摘要的科学充分性需要单独说明。公开开发案例不能当作隐藏评测或泛化检出率证据。
