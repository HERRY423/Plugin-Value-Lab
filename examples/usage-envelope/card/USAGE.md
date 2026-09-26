# 插件使用卡

**example\-plugin · 0.0.0\-demo**

研究：synthetic\-usage\-envelope

状态：仅供设计试用，不能据此推荐实际使用

重新计算的结论：SIMULATION\_ONLY

仅对记录中的具体任务提供条件性参考。评分不会产生安装、权限或卸载操作。

## 单页使用包络

**负向证据优先**：delivery：启用组 1 次执行失败（未归因）；negative\-control：1 个 harmed pairs；negative\-control：平均质量下降；negative\-control：1 个关键判据失败

证据：synthetic；研究阻断 0 项；身份缺口：\[&quot;plugin\_sha256&quot;, &quot;host\_version&quot;, &quot;model\_version&quot;\]。

绿：限域试用；黄：调查／证据不足；红：暂不推广或基线优先；灰：未测。

| 任务族 | 决策 | 质量 Δ | harmed pairs | over-refusal W / B | 每成功 USD W / B | 执行失败率 W / B | 样本量 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| delivery | 红 · 暂不推广：先处理负向证据 | 0.500 | 0/3；0 未知 | 未测 / 未测 | 1.530 / 无成功，未定义 | 1/3 \(33%\) / 0/3 \(0%\) | 1 案例；3 / 3 次；3/3 配对可判 |
| negative\-control | 红 · 暂不推广：先处理负向证据 | \-0.167 | 1/3；0 未知 | 未测 / 未测 | 1.530 / 2.010 | 0/3 \(0%\) / 0/3 \(0%\) | 1 案例；3 / 3 次；3/3 配对可判 |
| evidence\-boundary | 黄 · 仅供调查／试用：证据不足或收益未明确 | 0.667 | 0/3；0 未知 | 未测 / 未测 | 1.020 / 6.030 | 0/3 \(0%\) / 0/3 \(0%\) | 1 案例；3 / 3 次；3/3 配对可判 |
| ligand\-receptor\-analysis | 灰 · 未测：无运行观察 | 未知 | 0/0；0 未知 | 未测 / 未测 | 未知 / 未知 | 未测 / 未测 | 0 案例；0 / 0 次；0/0 配对可判 |
| ontology\-mapping | 灰 · 未测：无运行观察 | 未知 | 0/0；0 未知 | 未测 / 未测 | 未知 / 未知 | 未测 / 未测 | 0 案例；0 / 0 次；0/0 配对可判 |

W / B = 启用 / 基线；质量 Δ = 启用 − 基线；harmed 为已判定计数，未知配对不作零伤害。失败率范围保留缺失／跳过；每成功成本包含失败与分摊开销。

绑定 plugin_sha256：未知；宿主 offline\-tutorial / 未知；模型 SIMULATED\-NO\-MODEL / 未知。

**失效条件**：plugin\_sha256 改变，即使版本号未变。 host/model 名称或版本、工具、环境、配置或预算改变。 任务族之外的新任务、输入分布、参考答案、质量目标或评分规则改变。 新增失败、harmed pairs、误拒答、成本或人工复核证据；必须生成新修订，旧卡保留。

颜色是保守展示规则，不是新统计检验。harmed pairs 为基线成功而启用失败的已观察配对，不证明因果伤害。重复不是独立任务族；未测误拒答与未知成本不填零；合成数据不能获绿灯。哈希不认证执行或来源。

## 适用范围

- 决策范围：仅限本次提交的具体任务及固定条件；不会自动外推到同类或新任务。
- 目标：quality
- 固定条件：{&quot;budget&quot;: {&quot;max\_turns&quot;: 10}, &quot;environment&quot;: &quot;synthetic\-fixture\-v1&quot;, &quot;host&quot;: &quot;offline\-tutorial&quot;, &quot;model&quot;: &quot;SIMULATED\-NO\-MODEL&quot;, &quot;tools&quot;: \[\]}
- 方案 SHA-256：9809025862b8af3b8c352c82a09aaf59e2f6d78029290847ee1552a38a975f13
- 运行记录 SHA-256：bd6344a9462fdb1531675ec4d464266433ea64ad5ad5faf778feea980b27b243
- 条件 SHA-256：eb9bd8566defb2dc67fee1852aa7d39c2d8a1034d43f3b6ee95b0c483265c5ec

## 何时可优先试用

当前证据不能给出优先使用建议。

## 何时基线可能已足够

尚无可支持的基线优先观察。

## 先调查什么

### structured\-delivery

任务：Deliver a task result with a source reference and explicit limitations.

包含合成演示，不能转化为实际使用建议；保留 1 次失败、0 次缺失、0 次跳过和 0 次有问题的运行，不能删去后重算收益。

质量差（启用 − 未启用）：0.5；平均成本差（USD）：\-0.9899999999999998。

运行计数：{&quot;failed\_runs&quot;: 1, &quot;missing\_runs&quot;: 0, &quot;observed\_runs&quot;: 6, &quot;planned\_runs&quot;: 6, &quot;runs\_with\_issues&quot;: 0, &quot;skipped\_runs&quot;: 0}

### unrelated\-request

任务：What is 2 \+ 2? Give only the number.

包含合成演示，不能转化为实际使用建议。

质量差（启用 − 未启用）：\-0.16666666666666663；平均成本差（USD）：\-0.9899999999999998。

运行计数：{&quot;failed\_runs&quot;: 0, &quot;missing\_runs&quot;: 0, &quot;observed\_runs&quot;: 6, &quot;planned\_runs&quot;: 6, &quot;runs\_with\_issues&quot;: 0, &quot;skipped\_runs&quot;: 0}

### insufficient\-science

任务：Do passing local software tests prove clinical effectiveness? Explain the evidence limit.

包含合成演示，不能转化为实际使用建议；基线未通过关键判据或关键结果尚未知，不能仅凭平均分达到下限就建议优先使用基线。

质量差（启用 − 未启用）：0.6666666666666667；平均成本差（USD）：\-0.9899999999999998。

运行计数：{&quot;failed\_runs&quot;: 0, &quot;missing\_runs&quot;: 0, &quot;observed\_runs&quot;: 6, &quot;planned\_runs&quot;: 6, &quot;runs\_with\_issues&quot;: 0, &quot;skipped\_runs&quot;: 0}

## 作者改进清单

可直接本地使用，无需登记或公开评分。以下是诊断线索，不是已证实的因果缺陷。

状态：SIMULATION\_ONLY

- structured\-delivery / with / 第 1 次 / execution：Synthetic failure for display verification only 核对原始会话、加载记录与执行错误；保留失败，在新研究中复测，不覆盖原运行。
  预期观察：补充的实际会话、产物或复核记录能明确原缺口；保留原有失败记录。 反证条件：新增记录仍缺失或与原记录冲突；不能把执行恢复等同于科研结果修复。
- insufficient\-science / without / 第 2 次 / limit：Literal content check \(not semantic truth verification\) 对照冻结判据检查实际产物；修复相关行为后同时复测正确处理和不应拒绝的任务。
  预期观察：在原输入、评分参考与阈值不变时，失败判据转为通过，且正常与不应拒答对照不退步。 反证条件：失败仍存在、对照退步，或只有修改输入、阈值或删减案例才通过。
- insufficient\-science / without / 第 3 次 / limit：Literal content check \(not semantic truth verification\) 对照冻结判据检查实际产物；修复相关行为后同时复测正确处理和不应拒绝的任务。
  预期观察：在原输入、评分参考与阈值不变时，失败判据转为通过，且正常与不应拒答对照不退步。 反证条件：失败仍存在、对照退步，或只有修改输入、阈值或删减案例才通过。
- unrelated\-request / with / 第 1 次 / over\-trigger：Literal absence check \(not semantic truth verification\) 对照冻结判据检查实际产物；修复相关行为后同时复测正确处理和不应拒绝的任务。
  预期观察：在原输入、评分参考与阈值不变时，失败判据转为通过，且正常与不应拒答对照不退步。 反证条件：失败仍存在、对照退步，或只有修改输入、阈值或删减案例才通过。
- structured\-delivery / without / 第 1 次 / limits：Literal content check \(not semantic truth verification\) 对照冻结判据检查实际产物；修复相关行为后同时复测正确处理和不应拒绝的任务。
  预期观察：在原输入、评分参考与阈值不变时，失败判据转为通过，且正常与不应拒答对照不退步。 反证条件：失败仍存在、对照退步，或只有修改输入、阈值或删减案例才通过。
- structured\-delivery / without / 第 2 次 / source：Literal content check \(not semantic truth verification\) 对照冻结判据检查实际产物；修复相关行为后同时复测正确处理和不应拒绝的任务。
  预期观察：在原输入、评分参考与阈值不变时，失败判据转为通过，且正常与不应拒答对照不退步。 反证条件：失败仍存在、对照退步，或只有修改输入、阈值或删减案例才通过。
- structured\-delivery / without / 第 2 次 / limits：Literal content check \(not semantic truth verification\) 对照冻结判据检查实际产物；修复相关行为后同时复测正确处理和不应拒绝的任务。
  预期观察：在原输入、评分参考与阈值不变时，失败判据转为通过，且正常与不应拒答对照不退步。 反证条件：失败仍存在、对照退步，或只有修改输入、阈值或删减案例才通过。
- structured\-delivery / without / 第 3 次 / source：Literal content check \(not semantic truth verification\) 对照冻结判据检查实际产物；修复相关行为后同时复测正确处理和不应拒绝的任务。
  预期观察：在原输入、评分参考与阈值不变时，失败判据转为通过，且正常与不应拒答对照不退步。 反证条件：失败仍存在、对照退步，或只有修改输入、阈值或删减案例才通过。
- structured\-delivery / without / 第 3 次 / limits：Literal content check \(not semantic truth verification\) 对照冻结判据检查实际产物；修复相关行为后同时复测正确处理和不应拒绝的任务。
  预期观察：在原输入、评分参考与阈值不变时，失败判据转为通过，且正常与不应拒答对照不退步。 反证条件：失败仍存在、对照退步，或只有修改输入、阈值或删减案例才通过。

### 修复后的复测

一次只改待测插件的一个行为，记录内容摘要；无需改版本号。冻结新研究，重跑完整的两组任务，再用 compare\-studies 检查可比性与回退。

保留原研究、失败、负面与未知结果；修复用例后的重测仅是开发集诊断，泛化需新的未暴露任务。

完整复测：18 次计划运行；案例：\[&quot;structured\-delivery&quot;, &quot;unrelated\-request&quot;, &quot;insufficient\-science&quot;\]。费用与人工耗时尚未知；不会自动执行。

## 接下来怎么做

- 先冻结真实任务、两组相同的授权输入及比较条件，再收集真实运行和完整成本。
- 合成案例只用于演练记录和判读流程。
- 安装、连接、权限或卸载需求交由宿主及 Plugin Management 处理；本卡不授予任何变更权限。

## 何时重新核验

- 插件版本、配置、权限或依赖变化时重新核验。
- 模型、宿主、工具、运行环境或资源预算变化时重新核验。
- 任务、输入数据、数据访问范围、评分标准或质量与效率目标变化时重新比较。
- 出现新的失败、回退、人工纠正或成本证据时复核；此清单不创建定时监控。

## 证据阻断

未记录；不代表证据已获独立认证。

## 需要关注

- \(&\#x27;structured\-delivery&\#x27;, 1, &\#x27;with&\#x27;\): timeout retained as operational failure with score zero
- Costs must include retries, model judges, setup, correction and review allocated consistently; omitted categories cannot be inferred
- Cost savings are conditional on submitted estimates/declarations; settled savings are not established

## 限制

- 使用卡是观察范围内的临时参考，不是插件的通用质量认证或长期有效承诺。
- 来源、外部参与者、任务独立性与人工计时均为提交者声明；程序重算和哈希不证明数据真实性、实际执行或独立验证。
- 本地增益信号不建立因果收益、外部适用性或科学与临床有效性；科研结论仍需领域证据和研究者判断。
- 成本来自提交记录及人工费率折算；均值按每个案例每组的计划运行计算，估算费用不等于已结算支出。
- 基线足够的观察不构成自动停用、卸载、扩权或修改其他插件的授权。
- 原始任务文字保留在本地卡片中；向他人分享前应由用户检查其中的私有资料。

## 来源与完整性

- 证据类型：synthetic
- 证据层级：SIMULATION\_ONLY
- 运行计数：{&quot;failed\_runs&quot;: 1, &quot;missing\_runs&quot;: 0, &quot;observed\_runs&quot;: 18, &quot;planned\_runs&quot;: 18, &quot;runs\_with\_issues&quot;: 0, &quot;skipped\_runs&quot;: 0}
- 来源记录：{&quot;cost\_ledger\_sha256&quot;: &quot;42c97b9fff93da8d15015cf51e7cb6504819185e9eae0bb50d98b64ab3779fa2&quot;, &quot;engine&quot;: &quot;plugin\-value\-lab/0.6.0&quot;, &quot;hash\_scope&quot;: &quot;Byte consistency only; no proof of execution, authorship, or preregistration time&quot;, &quot;local\_lock&quot;: {&quot;suite\_sha256&quot;: &quot;9809025862b8af3b8c352c82a09aaf59e2f6d78029290847ee1552a38a975f13&quot;}, &quot;records\_sha256&quot;: &quot;bd6344a9462fdb1531675ec4d464266433ea64ad5ad5faf778feea980b27b243&quot;, &quot;suite\_sha256&quot;: &quot;9809025862b8af3b8c352c82a09aaf59e2f6d78029290847ee1552a38a975f13&quot;}

来源真实性未获独立验证。完整字段保存在同目录的 `card.json`。
