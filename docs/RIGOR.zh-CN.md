# 可执行的严谨性：跨宿主、科研验证、方法纪律与证据回放

当前实现为 0.6.0；新增[独立样本推断重算](REPLICATE-VERIFICATION.zh-CN.md)。产品的重点是让增益主张接受同一套可检查约束，而不是增加一项笼统的“可信”评分。以下说明区分已实现的软件行为与仍需实际研究建立的证据。

## 1. 比较基准要准确

2026-09-23 核对的 [Claude Code 官方 Plugin evals 文档](https://code.claude.com/docs/en/plugin-evals) 已包含有/无插件比较、产物文件评分、JSON 结果及可发布报告；该页明确没有自定义代码评分器。它描述 Claude Code 工作流，未描述 Codex 适配。这些是当前文档边界，不能表述为官方永远做不到，也不能说官方只有本地 CI。

我们的差异化落在跨宿主一致的证据要求、科学计算契约、强制方法约束和独立于原目录的重算上。已有能力与本轮补强如下。

| 方向 | 可以运行的能力 | 明确不能推导的结论 |
| --- | --- | --- |
| Codex + Claude | 分离会话、冻结计划、实际事件与输入输出核验、统一宿主凭据、同条件的宿主间 Δ 比较 | 两种适配器存在，不等于已完成真实跨宿主收益研究 |
| 科研产物 | DE/BH、逐细胞标签、h5ad、数值容差、弃答、后端身份、固定代码与容器验证 | 结构和数值过关不等于生物学结论正确 |
| 方法纪律 | process 不计结果分、关键流程约束、双向错误上限、固定失败分母、完整成本及结算引用等级 | 局部信号、先导试验和自助区间不等于显著性或普遍效益 |
| 可移植证据 | 独立身份摘要、清单、依赖预检、环境记录、重新评分、差异定位 | 完整哈希和计算重现不等于执行真实性或独立科研复现 |

## 2. 两个宿主接受同一证据标准

```text
python scripts/value_lab.py verify-host-study PATH_TO_NATIVE_STUDY
python scripts/value_lab.py registry-contrasts --registry REGISTRY --output contrasts.json
```

`verify-host-study` 自动选择已经识别的 Codex 或 Claude 采集契约，输出 `pvl-host-evidence-1`：计划数、实际记录数、成功数、观测条件与插件状态覆盖数，以及方案、记录、插件文件清单的摘要。它只离线读取，不调用模型。

Codex 核验现在重新解析原始事件，将输出、会话、token 用量、状态和经过时间与记录逐项对照；核验冻结锁、执行标记、插件快照、输入快照、实际工作目录输入和提示词、答案文件及临时凭据清理。CLI 请求的模型/插件配置不能改写为观测事实；原生缺失的金额和人工时间不能静默补成零。若需要补充观察或成本，应保留原始采集档案，另外提交有来源的评审修订。

Claude 原生采集已有相应的事件重解析和观测元数据检查，当前支持 Read/Skill 及最终 JSON 答案的有界审阅工作流；Codex 支持冻结输入与指定输出文件。两者的适用任务和实际工具必须一致，不能把不同工具权限、模型或预算的结果直接解释为宿主效应。

`registry-add` 识别到上述原生采集计划时，先核验档案，再允许登记；`metadata.plugin_sha256` 必须等于核验返回的 `plugin_files_sha256`。导出包保留 `native-verification.json` 作为登记时的检查记录，不自动复制账户目录、完整原生事件或凭据。要重新检查原生执行轨迹，仍需单独保管原始采集档案；导出包内的该记录不能代替档案或独立签名。

宿主间对比除模型别名外，还必须有明确的 `model_version` 和 `host_version`；其他任务、真值、评分、输入哈希、插件内容、预算及引擎保持一致。同一会话、同一研究的补证修订、争议、缺失、模拟与多个因素同时变化不会生成可归因的宿主增益。版本字段仍是提交的观察声明，不证明提供商权重或路由身份。

## 3. 科研产物要检查原始文件与完整检验范围

原有 DE 验证能重算提交表内的 BH，但仅靠这一步不能发现“先丢掉不利基因，再对剩下部分重算”。现在可给 `de_table` 增加冻结的 `testing_family`：

```json
{
  "kind": "de_table",
  "id_column": "gene",
  "p_column": "p",
  "q_column": "q",
  "effect_column": "effect",
  "min_rows": 3,
  "bh_tolerance": 1e-9,
  "testing_family": {"path": "tested-genes.json", "sha256": "REPLACE_WITH_ACTUAL_SHA256"}
}
```

独立评分目录中的文件内容为 `{"ids": ["gene-a", "gene-b", "gene-c"]}`，应来自实际、预先冻结的检验集合，不从模型输出反推。缺失或变化的参照保持未知；删减或增加基因明确失败；随后才检查有限数值、合法概率及完整集合上的 BH。没有指定参照的旧规则继续兼容，但凭据标为 `SUBMITTED_ROWS_ONLY`，不能宣称验证了实验的全部检验范围。

`evaluate --artifacts OUTPUT_ROOT --verifiers SCORER_ROOT`、登记及回放均使用同一个验证器。Scenario Pack 的评分材料隔离检查也包含新的检验集合。自定义 Python 验证器必须固定摘要并明确提供受信任目录；它不是安全沙箱。容器 `exec` 仍须固定镜像摘要，禁网络，不自动拉取镜像、不回退为宿主执行；本轮没有把模拟的容器测试宣称为实际容器执行验证。

## 4. 方法约束必须能阻止漂亮但错误的结论

`process` 不计入 outcome 分。声明为 `critical` 的流程项如果失败或未解决，阻止正向结论；流程通过依然不能补偿错误结果。普通非关键流程信息仅用于诊断。

可在冻结的 `policy` 中加入双向上限：

```json
"decision_error_limits": {
  "unsupported_acceptance": 0.05,
  "over_refusal": 0.10
}
```

上例只是语法示例，真实阈值由适用场景决定。两种错误、两侧实际观察都必须存在且完整；文字中“看起来很谨慎”不能满足此要求。有插件侧在任一报告的数据切分上超过上限，即使平均分提高也返回退步；缺证返回证据不足。重复的决策评分规则不能膨胀样本分母，模糊定义保持未知。上限是描述性验收规则，不能替代统计设计或证明错误率的总体上界。

成本保持模型、工具、人工、裁判、设置、重试及其他开销的分项；未知不补零，类别声明互相矛盾会被拒绝。已有 `require_settled_costs` 可要求结算引用，但引用仍须人工核对；人工按冻结时薪估值不变成已结算现金。样本量规划和正向指标见 [VALUE-METRICS.zh-CN.md](VALUE-METRICS.zh-CN.md)。

## 5. 带明确依赖的可移植重算

```text
python scripts/value_lab.py registry-replay-plan BUNDLE --expected-id RETAINED_ID
python scripts/value_lab.py registry-replay-plan BUNDLE --expected-id RETAINED_ID --verifiers TRUSTED_SCORER_ROOT --corpus PRIVATE_CORPUS_ROOT
python scripts/value_lab.py registry-replay BUNDLE --expected-id RETAINED_ID --verifiers TRUSTED_SCORER_ROOT --corpus PRIVATE_CORPUS_ROOT --require-same-environment
```

不需要私有语料或外部评分器的研究省略相应参数。`expected-id` 应从独立保留的登记/交接记录取得，不能从收到的可疑包中现读现信。

新登记的证据包包含 `replay-contract.json`，记录 Python、平台、相关数值库版本、容器镜像引用及外部评分材料依赖。预检核对文件摘要，列出缺失/变化的产物、私有评分器、检验集合、答案或后端凭据；不会运行其中任何代码，也不会复制私有真值。尚未取得的私有 Scenario 定义会标出“内部依赖未知”，不会假装材料完整。包版本存在只代表已安装元数据，不保证可导入；容器镜像可用性仍由实际执行检查。

严格环境选项在环境未知或不一致时、执行评分器之前停止。旧证据包仍可默认重算，但没有环境记录时保留 unknown，不能冒充严格环境复现。重放报告分别显示：引擎是否相同、环境是否相同、报告是否相同、哪些字段变化，以及评估本身是否完整。`REPRODUCED` 可以表示成功重现了“证据不足”；务必同时检查 `assessment_complete`、原结论和模拟标记。

报告不相同不覆盖旧包，不重写旧评分；按字段路径列出差异，供审阅者判断是环境、规则、缺失材料还是结果变化。保存的摘要用于完整性，真实作者、独立身份和科学有效性仍需各自的证据。

## 6. 验收边界

本轮对抗测试覆盖：伪造 Codex 输出/身份/费用/时间、工作目录输入替换、插件快照替换、匹配别名但缺少模型版本、删减基因后正确重算 BH、只拒答的评分漏洞、缺失双向错误、成本覆盖矛盾、异地目录重放、环境漂移时提前停止、错误包身份、预检不执行评分器，以及不完整结果的如实重现。

这些证明软件按契约处理材料。本轮没有付费模型调用、没有新增真实跨宿主收益研究、没有独立专家评审或公开发布。严谨性使证据更可检查；它本身不是插件已经有价值的替代证据。
