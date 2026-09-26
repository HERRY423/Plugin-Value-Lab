# 用自己的供者配对问题试跑一次

这份包只做一件事：帮助作者核对自己的输入和指定分析方法，检查插件实际产物，理解一项有证据的差异，再准备一次同条件复测。它不是新的通用向导，也不是临床或生物学认证。当前真实参与者为 0；你交回的失败、误报和放弃与成功同样重要。

范围沿用已有验证器：单一细胞类型、至少三对完整供者、每个供者每个条件一个样本、原始整数计数、预先指定 PyDESeq2 方法。复杂批次、技术重复合并、非配对设计、其他合理方法不强行套入；记录不适用并停止此试跑。已有 replicate 路径适用于另行冻结的独立单位测量，不把它当作原始计数模型的替代。

## 先记录，再准备

观察者从作者第一次接触材料开始记录时间，包含安装、找数据、格式转换、阅读、求助和失败。计时程序启动前的时间用有时间戳的纸笔／现有计时工具保留；没有记录就写未知，不能补估为零。不要先演示操作。

1. 在本目录 `session.json` 填参与者代号、自己的问题编号、比较任务对编号、顺序 1/2、既有接触、是否维护者或 AI。`arm` 只能填 `with_pvl` 或 `without_pvl`；这是 **PVL 辅助调试与原有调试方式的比较**，不是被测插件的 WITH/WITHOUT 两臂。
2. 在 `STUDY-PLAN.md` 冻结本次目标、任务配对、停止点、成本分摊和审阅规则。`preparation_plan` 填 `STUDY-PLAN.md`。计划未完成不开始；计时器保存该文件摘要，但不会认证其内容或事前性。
3. 在解压后的仓库根目录运行 `python examples/pseudobulk-author-pilot/observe.py`，在第二个终端工作。计时器初始为 reading。输入 preparation、reference、controls、execution、diagnosis、false_positive_review、repair、retest_preparation、retest 切换活动；不工作时输入 pause。help/error 记录帮助和错误。窗口意外关闭也保留原文件；重新启动是另一次尝试。

计时不是屏幕监控：活动与暂停由作者／观察者声明。后台拟合等待应切换 pause，并保留墙钟时间；需要盯守的工作才算主动时间。没有把“终端开着”认证为“人在工作”。

**分配到 without_pvl 的作者到此停止阅读后面的诊断操作。** 只使用相同的中性计时器，按原有调试方式处理自己的匹配问题；不运行准备／参考／PVL 检查工具，也不接触它们的诊断或答案。观察者事先分开提供两臂操作材料，不能把本完整操作页提前交给未暴露的基线作者。两臂最终按预定的相同质量规则审阅；审阅／共同参考准备费用单独保留并按预定规则分摊。以下操作仅供 with_pvl 臂。

## 从真实输入得到待确认契约

编辑相邻的 `author-input.json`。填自己的问题、插件目录、明确的细胞类型／对比／过滤门槛／参考方法来源。不要填写密钥。路径可以是绝对路径，也可相对于本目录。

- 已有 PVL 输入：`data` 使用 `{"kind":"pvl-cell-counts-1","path":"你的数据.json"}`，字段见 `docs/history/PSEUDOBULK.zh-CN.md`。
- 已有 AnnData：只替换 `data` 为以下结构，列名由作者明确映射。`counts_layer` 必须明确选择 `X` 或实际原始计数层，不猜测、不四舍五入、不自动删供者。

```json
{"kind":"h5ad","path":"你的数据.h5ad","counts_layer":"counts","sample_column":"sample","donor_column":"donor","condition_column":"condition","cell_type_column":"cell_type"}
```

AnnData 导入需要已有科学依赖；参考拟合需要与设计一致的可选 pseudobulk 依赖。没有依赖时先记录安装工作量；是否安装由作者环境规定决定。JSON 输入的准备和离线检查不需科学依赖。准备脚本不会安装、联网、运行插件或拟合模型。

```powershell
python examples/pseudobulk-author-pilot/prepare.py
```

每次创建一个新的 `work/author-pilot/attempts/时间-随机标识`，打印实际路径。打开其中 `REVIEW.md` 和 `preparation.json`，核对逐样本供者／条件／细胞数、完整配对、过滤后基因数、输入摘要。待确认项不会自动变成已确认；在原输入中补真实作者声明后重新准备，保留失败尝试。准备成功也没有生成标准答案。日志和生成材料均留在不进入分发包的 work 目录；填写后的作者配置和计划也含本地信息，分享时另做脱敏副本。

作者需明确：这是原始计数；样本与供者身份准确；配对方法适合问题；过滤在结果前决定；为什么选此参考。若已有结果暴露，必须披露，不能追认事前注册。生物学答案、供者独立性和专家审阅不能从哈希推断。

## 显式参考、正常对照、实际插件产物

以下从仓库根目录执行。把 `$study` 改成刚才打印的目录；`$submission` 改成授权宿主真正生成的分析文件。不要使用随包测试文件充当自己的结果。

```powershell
$study = "work/author-pilot/attempts/实际目录名"
python scripts/value_lab.py pseudobulk-reference "$study/design.json" "$study/data.json" --output "$study/reference"
python scripts/value_lab.py pseudobulk-corpus "$study/reference/verifier.json" --verifiers "$study/reference" --output "$study/verifier-controls"
python scripts/value_lab.py pseudobulk-scenario "$study/reference/verifier.json" --verifiers "$study/reference" --output "$study/scenario"
```

参考是明确方法下的本地计算；先查看 `reference/execution.json` 的警告与实际拟合变化，再由具备相关能力的人审阅适用性。`verifier-controls/corpus-report.json` 中的合法重排、精度变体和受控错误检查的是验证器，不是插件的真实误拒答率。若合法变体被拒绝，先保留并调查 PVL 的误报，不能要求插件迎合错误参考。

只向授权宿主提供 `scenario/inputs` 中的输入与 `pack.json` 内公开 prompt；隔离 `reference`、`scenario/scorers`、对照产物和所有答案。分目录不等于操作系统隔离。需要 staging 时用已有 `scenario-stage`，接口见历史 pseudobulk 文档；不得把整个试跑目录交给被测 Agent。

在运行前确定两个正常任务：原始自然问题，以及同一有效输入、只改合理措辞或输出行顺序要求的任务。两者都应完成指定分析，不能因为是科学任务就一律拒绝；它们是同一任务族，不能冒充独立样本。将实际决定、产物、拒答解释和宿主日志保留。不适用或不完整输入另行人工判断，不自动编造“应该拒绝”的标准答案。

通过自己的授权宿主运行待测插件，保留原 prompt、实际加载信息、完整日志、失败／超时、实际文件和成本。输出格式见 `scenario/inputs/output-contract.json`。需要输出适配时保留原始产物与适配代码并计时；不能补造缺失数字或执行回执。

```powershell
$submission = "实际宿主输出/result.json"
python scripts/value_lab.py pseudobulk-check "$submission" --spec "$study/reference/verifier.json" --verifiers "$study/reference" > "$study/diagnosis.json"
```

退出码 2 可能是差异或待审阅，不能把它本身叫作插件缺陷。先定位 aggregation／design／contrast／normalization／testing_family 等具体差异，核对输入、参考和允许变体。作者写下自己的解释、证据文件、可反驳的假设以及是否可能为 PVL 误报；审阅者记录接受／否定／未解决。计时器 `understood` 只记作者声称理解的时点与证据摘要，审阅始终为 PENDING，不能自动充当已确认缺陷。

## 修复和可信复测

保存修复前插件、产物、诊断与失败；写下诊断后新增的准备工作。只修改目标问题，在新目录用相同数据、方法、门槛、宿主条件重新自然运行。复测主要任务及正常对照，保留修复失败、成本和新增问题。只修输出 JSON 或复制参考，不算插件修复。

既有 `compare-native-repair` 适用于已完整收集的原生研究，详细字段沿用 `docs/history/NATIVE-ANALYSIS-REPAIR.zh-CN.md`；本包不把一个独立产物检查伪装成完整原生修复链。供者／方法真实性与解释仍需人审。

把修复前后产物、原始日志、变更摘要、同条件说明、正常对照及审阅状态写入自己的复测记录。输入 `credible_retest` 记录其路径和解释；此标记仍待审阅。最后输入 completed、blocked 或 abandoned。没有缺陷、误报或无法复测都允许如实结束，不能为完成流程而制造缺陷。

```powershell
python examples/pseudobulk-author-pilot/report.py > pilot-observation-summary.json
```

摘要保留全部尝试、坏日志、未闭合计时、主动时间与暂停／墙钟时间；分别报告首次声称理解问题的时间、诊断到复测的额外时间和其中的准备时间。程序不自动判断收益或剔除失败者。

## 交回最小证据

交回摘要、原始观察日志、填写的计划、作者对问题的解释、审阅意见和必要的诊断／复测记录。先保留原件，再制作脱敏分享副本；无需发送完整私有数据、插件代码、密钥或全部账户历史。没有作者与数据授权，不自动上传或联系他人。

这是用户明确要求的限定试跑材料；辅助脚本在 examples 内，不注册为 PVL CLI/MCP/技能或新评分器。冻结快照、版本及八份主线文档保持原边界。能运行的交接包仍不等于有真实观察。
