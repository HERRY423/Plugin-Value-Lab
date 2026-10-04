# Codex 配对执行交接与本地复算

本入口是**事前冻结、持久尝试日志和规范化操作员采集的本地合同**。它不会启动 Codex、打开浏览器、发送提示或调用模型；还不是已具备真实 Codex 执行能力的适配器。即使所有本地材料一致，`live_host_accepted` 仍为 false。

2026-10-03，用户明确将目标改为 **Codex**。本路径限定 **Codex 桌面端**，合同使用 `product: "codex"`、`surface: "desktop"`。当前对话已由线程接口识别为 `kind=codex`、`hostId=local`，但这只确认宿主类别；真实 build、模型版本、完整有效工具暴露、独立两臂和第三人人类复算仍须分别验收。

本次迁移同时更换模块、示例与格式标识。此前其他宿主的计划、捕获与复核包不自动导入或改写为 Codex 证据；保留旧材料与原评分源码，Codex 研究必须使用新合同重新冻结。合成示例中的 build、模型和摘要仅供合同测试，不是当前宿主的实测身份。现有 `codex.py` 原生执行路径与此处的持久尝试协调器各有验收边界，不能仅凭名称推定已接通。

本次范围迁移的检查与证据边界见[迁移记录](../evidence/codex-target-migration-20261003.json)。

## 本地已能做什么，以及哪些结论仍不可用

| 本地能力 | 限制 |
| --- | --- |
| 冻结 suite、宿主/插件/工具合同和完整运行槽位 | 显式写下版本与摘要不认证它们；`prepare` 不复制或安装实际插件，也不认证宿主上下文。 |
| 在外部发送前预留尝试，保留状态、证据、失败和中断 | SQLite日志不启动宿主、不证明外部请求发生，也不认证操作员证据。 |
| 接纳并封存规范化采集包，核对时序、身份、暴露和原始输出 | `operator_capture` 是来源类型，不是原生宿主认证；模型自报“没用插件”不能证明基线未暴露插件。 |
| 从保留的原始文本重新评分、生成完整槽位报告 | 当前只支持 `contains`、`not_contains`、`json_equals`，不会信任导入的通过标记，也不支持复杂科学文件验证。 |
| 导出带外部保留摘要的复核目录，在匹配本地源码上复算 | 字节一致和新进程复算不等于另一位人类独立完成；不会执行包内程序。 |

当前报告保留 `host_transport_qualified: false`、`live_host_accepted: false`、`benefit_claim_supported: false`、`third_person_recomputed: false`。冻结的 `power_plan.version == 3` 现在经 `core.evaluate()` 调用现有 `confirmatory.assess()`，`confirmed_decision` 返回实际确认性评估状态；没有 v3 计划时仍为 `NOT_EVALUATED`。未提供完整结算材料时费用仍为 `UNKNOWN`，不会推定为零。统计评估不解除真实宿主验收门槛。

## 1. 事前准备输入

先准备普通PVL `suite.json` 和独立 `contract.json`。suite必须通过现有校验，当前任务输入须全部内联在冻结 `prompt` 中，不使用 case 的外部 `inputs` 映射。任务内容只应包含用户已授权的公开材料；采用其他材料前必须重新处理数据授权与支持范围。

`contract.json` 的顶层仅有以下六项：

| 字段 | 必须保留的内容 |
| --- | --- |
| `host` | `product: "codex"`、`surface: "desktop"`，以及真实可追溯的 `build`、`model`。本路径只接受桌面端；CLI 和云端需独立合同及验收。不能用 `latest`、`auto`、`unknown` 填版本，也不能把为示例造的版本写为真实观察。 |
| `plugin` | `id`、`version`、精确插件字节 `sha256`；名称与版本必须匹配 suite。 |
| `common_tools` | 两臂共同有效工具的完整列表，每项含 `name`、`definition_sha256`；名字须与 suite 的 `conditions.tools` 一致。 |
| `candidate_tools` | 插件带来的独立工具定义列表，格式相同；不能与共同工具重名。 |
| `context_sha256` | 两臂共同指令与输入上下文的摘要。摘要由提交者提供，完整性仍需真实宿主来源支持。 |
| `max_attempts_per_slot` | 事前固定1至5次；首次尝试仍是主分析，后续只是诊断。 |

suite的 `conditions.host` 必须为 `codex`；`conditions.host_version`、`conditions.model` 分别匹配合同的 build 和 model。缺少真实版本或完整工具定义时先保留缺口，不能让模型猜测一个值来通过格式校验。

确认性研究须在采集前把已有先导材料、方差策略、样本量规划参数和确认规则完整写入 `suite.policy.power_plan` v3，再执行 `prepare`。本路径所有任务输入均为内联提示，因此每个 case 的 `input_sha256` 必须是其 `prompt` 原始 UTF-8 字节的 SHA-256；不能另填一个无关摘要来绕过先导重叠检查。先导任务、任务族和输入重叠会在准备阶段拒绝；执行/会话身份在采集后再核对。不得给已采集的旧研究事后补上 v3 规则。

`prepare` 会按已有成对顺序平衡规则列出全部 case×重复×两臂槽位，并记录每条确切提示的UTF-8摘要。此顺序平衡不是随机抽样，也不承诺供应商支持随机种子。重复应描述为独立随机采样意图，实际会话独立性仍需要证据。

## 2. 冻结计划并保留带外摘要

以下命令是在源码根目录执行的操作模板。文件路径和变量要替换为实际审核后的本地材料；它们不构成真实宿主已经可用的证明。

```powershell
python -m value_lab.codex_study prepare .\suite.json .\contract.json .\work\codex-study-new
```

输出包含实际 `plan_sha256`、槽位数和 `model_calls: 0`。将返回的摘要保存在研究目录之外的已有受控研究记录中，之后每一步都传入同一个值。不要从可疑的新计划重新计算摘要来替换原承诺。

```powershell
$pvlStudy = '.\work\codex-study-new'
$pvlPlanPin = '<prepare实际返回并另外保留的64位摘要>'
```

研究目录包括 `suite.json`、`contract.json`、`protocol.lock.json`、`plan.json`、`attempts.sqlite`、`.control.lock`、`submissions/` 和 `captures/`。输出目录必须不存在；未来复核会检查计划、suite、lock、合同、顺序和首次尝试规则。已有研究通过 `AttemptJournal(..., create=False)` 打开；缺失、空或截断日志均拒绝，不以新数据库重置尝试历史。

协调器用操作系统文件锁 `.control.lock` 覆盖reserve、state、capture、review和export的检查与操作，避免不同进程跨槽位同时预留，以及采集/导出看到不一致快照。被其他控制器占用时拒绝，先核查原状态；进程退出由操作系统释放锁。锁不证明宿主隔离，也不能替代原请求的结果对账。

## 3. 正常路径：先登记，再记录发送，再采集

读取冻结 `plan.json`，使用其中实际 `slot_id`；不要推测顺序、跳槽位或在一个有上下文的聊天里交替两臂。只有在宿主执行、数据发送和费用等所需条件已实际满足且用户授权范围允许时，才由合格的外部控制器执行发送。本模块自身没有该发送能力。

```powershell
python -m value_lab.codex_study reserve $pvlStudy 'slot-0001' '<本逻辑调用唯一key>' --plan-sha256 $pvlPlanPin
```

记录返回的真实 `attempt_id`。首次注册返回 `created: true`；同key/同参数恢复只返回原尝试，`dispatch: false`，绝不能据此再次发送。`dispatch: true` 只是本地首次预留标志，**不是执行、收费或数据外发授权**。

```powershell
$pvlAttempt = '<reserve实际返回的attempt_id>'
python -m value_lab.codex_study state $pvlStudy $pvlAttempt dispatched .\dispatch-evidence.json --plan-sha256 $pvlPlanPin
```

证据文件为非空JSON对象，保留实际来源引用，例如 `source_ref` 以及请求身份或控制器事件引用。发送状态应在外部操作之前持久保存；不得事后补造一个早于真实发送的状态。随后可记录 `running`。未观察到中间运行态但收到可信终态时，允许从 dispatched 直接接纳终态材料。

```powershell
python -m value_lab.codex_study state $pvlStudy $pvlAttempt running .\running-evidence.json --plan-sha256 $pvlPlanPin
python -m value_lab.codex_study capture $pvlStudy .\observation.json --plan-sha256 $pvlPlanPin
python -m value_lab.codex_study review $pvlStudy --plan-sha256 $pvlPlanPin
```

有效采集包由 `capture` 封存并以捕获文件摘要写入终态事件。仅手工 `state completed` 不会补齐原始输出或捕获摘要绑定，复核仍会报告证据不足。按冻结顺序完成每个槽位；缺失不缩小计划分母。

## 4. 采集包必须保留什么

采集格式为 `pvl-codex-study-observation-1`，来源 `origin` 只能为 `synthetic` 或 `operator_capture`。制造例子必须用 synthetic；把字段改为 operator_capture 不能把它升级为真实宿主记录。

| 材料 | 核对内容 |
| --- | --- |
| 绑定 | `plan_sha256`、`attempt_id`、`slot_id`，独立 `session_id`、`request_id`；不同尝试不能复用会话/请求身份。 |
| 宿主 | 与冻结计划一致的完整 `host`，以及 `host_source_ref` 指向保留的原始来源。 |
| 输入和时间 | 确切 `prompt`、`input_sha256`、带时区 `started_at`/`finished_at`；不能早于冻结，且运行区间应落在已记录发送至终态之间。 |
| 上下文 | `context` 保留 `fresh_session: true`、`parent_session_id: null`、`prior_messages: 0`、`memory_enabled: false`、`project_id: null`、`shared_artifacts: false`、冻结 `context_sha256`，并有完整性及来源字段。缺失不能猜成false/零。 |
| 实际暴露 | `exposure.source_kind: "host_effective_inventory"`；完整 tools含定义摘要、完整plugins列表。WITH只增加冻结候选，WITHOUT不得暴露候选，即使没有调用过也不合格。 |
| 原始结果 | `raw_output` 是原始字符串；无输出时显式null。completed必须有原始文本；程序从它重评分，不消费额外导入的 `grades`。 |
| 终态 | `terminal_state` 为 completed、failed或cancelled，必须与最后终态事件相同。 |
| 来源 | `sources` 为来源引用到保留原文字符串的映射，覆盖宿主、上下文、初始/变化工具库存的每项引用。该映射及原文仍由操作方提供，未认证；字段存在、引用可解析或原文自称“原生”都不是宿主真实性证据。 |

上下文与暴露需 `inventory_complete: true`、非空 `source_ref`。有分页、截断或剩余游标时不得声明完整。工具列表必须是**宿主有效暴露全集**，不是插件目录、某次搜索结果、用户勾选项或模型记得的工具。

`events` 连续从seq=1开始，支持以下事件：

- `tool_call`：独立 `call_id`、冻结库存内的 `name`；若保留定义摘要则必须匹配。
- `tool_result`：匹配前面调用的 `call_id`，明确 `is_error`；不能重复返回或保留悬空调用。
- `inventory`：完整变化后的 `exposure`，仍满足冻结两臂条件。
- `final`：原始输出 `output_sha256`，只能在所有工具结果已完成后出现。
- `terminal`：唯一、最后的终态，与 `terminal_state` 一致；completed需要唯一final。

这些是规范化材料的一致性检查。若缺少能证明真实版本、完整有效工具和上下文隔离的宿主传输层，应继续报告缺口，不能让被测模型自报来填真。声明隔离也不能证明隐藏记忆、额外工具或共享状态不可访问。

每个文件当前上限16MiB，不接受符号链接。能够解析且指向已登记尝试的JSON提交，先按原始字节SHA保存到 `submissions/`，再追加 `journal.note` 的 `capture_received` 回执；相同字节恢复不重复追加，已有提交不覆盖。结构或来源缺口不升级终态，原提交与其拒绝原因继续可复核。无法读取、非法JSON或没有已登记attempt的输入不会成为合格捕获，原提交方需另外保留这些失败材料。

不完整提交可以在后来从**同一原请求**获得完整材料后补齐：使用原attempt再次capture，保存新的submission，首次完整且合格的材料才封存到 `captures/<attempt_id>.json` 并对账终态。补齐不是重新发起模型请求，也不删除首轮失败；原拒绝问题仍展示并阻断 `local_contract_complete`。已封存完整capture后，相同字节可恢复，冲突字节不能覆盖。不能把后来补齐写成首轮材料一直完整。

## 5. 中断、未知结果与诊断重试

状态路径为 prepared→dispatched→running→completed/failed/cancelled；可未观察running而直接到终态。dispatched/running可转unknown。每个事件有递增序号、时间和payload；旧事件不能通过API更新或删除。

```powershell
python -m value_lab.codex_study state $pvlStudy $pvlAttempt unknown .\disconnect-evidence.json --plan-sha256 $pvlPlanPin
```

超时、断线、页面关闭、进程退出都不能证明外部请求失败或未收费。保留原attempt、原key并找回原会话/请求的终态；unknown、running、dispatched不可用新key重派。若后来收到原尝试完整捕获包，向同一个attempt执行 `capture` 对账；这不新增尝试。

unknown只能带非空 `evidence.source_ref` 对账至 completed、failed或cancelled，不能退回prepared或假称not_dispatched。prepared后本地崩溃也不能推断没有外部发送；须有明确未发送证据才能转not_dispatched。

```powershell
python -m value_lab.codex_study state $pvlStudy $pvlAttempt not_dispatched .\not-dispatched-evidence.json --plan-sha256 $pvlPlanPin
```

上条仅适用于原状态prepared且有真实未发送依据。已发送/未知不可走此路径。已确认 failed/cancelled/not_dispatched、符合冻结次数限制时，才可显式创建诊断重试：

```powershell
python -m value_lab.codex_study reserve $pvlStudy 'slot-0001' '<明确新诊断尝试key>' --retry-of $pvlAttempt --plan-sha256 $pvlPlanPin
```

**每槽位第一次注册的attempt永久属于主分析。** 重试不能替换首次失败，不能挑最好答案，也不能把后一次成功填回原主结果。全部尝试、失败、取消、未知和成本缺口一起保留；主尝试未完成时配对delta为null。不完整submission可按上一节补齐同一原请求的证据，首轮拒绝仍保留；只有实际进行了新执行才属于新attempt，且必须先处理原未知状态，再在授权范围内作明确诊断重试。

## 6. 复核、导出与第三人交接

`review` 对完整计划分母、全部attempt、原始捕获、原始评分与身份/时序重新核对。制造材料返回 `SIMULATION_ONLY`；其他材料仍返回 `LIVE_HOST_ACCEPTANCE_BLOCKED`。`local_contract_complete: true` 只表示提交的本地合同材料未检出缺口，不解除真实宿主阻断。命令退出成功意味着本地处理成功，不能当作插件收益门禁绿色。

```powershell
python -m value_lab.codex_study export $pvlStudy .\work\codex-review-bundle-new --plan-sha256 $pvlPlanPin
```

导出必须是研究目录之外的新目录。包保留suite、合同、lock、plan、全部 `submissions/`（含被拒绝的原提交）、合格封存 `captures/`、日志快照 `journal.json`、复核结果 `review.json` 和 `manifest.json`。原可变SQLite仍在研究目录中；分享的是有明确时点的完整快照。manifest记录文件摘要与评分相关源码摘要。另行保存实际返回的 `manifest_sha256`，不要只把它和可改包放在一起。

```powershell
$pvlManifestPin = '<export实际返回并另外保留的64位摘要>'
python -m value_lab.codex_study verify .\work\codex-review-bundle-new --manifest-sha256 $pvlManifestPin
```

verify要求文件集合、所有摘要、冻结计划与评分源码一致，并从保留原始输出重新计算review；不会运行包内程序、工具或模型。缺失/增加文件、删除失败记录、改动原输出、修改封存结果或使用不同评分源码都会拒绝。成功是 `RECOMPUTED_LOCALLY`，仍不声明第三人身份或真实宿主通过。

给另一位获授权复核者的交接应包括：经数据审查后的完整包、通过独立渠道保留的manifest摘要、确切源码版本/内容及环境要求、原任务/评分解释和已知缺口。让其自己验证并解释一项失败或未知，保留其实际输出、运行环境及署名方式；不要用本机另开进程替代此人。程序当前不自动认证“第三人”身份。

分享之前应用[数据治理](../DATA-GOVERNANCE.md)：来源原文、会话身份和路径可能含私有材料，不直接上传完整宿主日志。去标识分享副本是新材料，不冒充原始全量证据。

## 7. 从采集接入确认性评估

`review` 在 v3 计划上将首次登记尝试的原始输出转换成既有 `core.evaluate()` 记录，传入原 `protocol.lock.json`。完整冻结矩阵、先导隔离、时间和输入绑定、样本量目标、质量判据、结算费用及预算上界均由现有评估器执行；不复制一套确认统计，也不读取捕获包中自报的评分。缺失槽位仍在原计划分母，失败/取消保留原状态，重试不能替换主记录。重试的会话和请求身份同样参与先导隔离检查。

默认不提供费用时也会评估，结果保留费用缺口。结算到齐后，以独立文件提供晚到的材料，不改写已封存捕获：

```powershell
python -m value_lab.codex_study review $pvlStudy --plan-sha256 $pvlPlanPin --settlement .\settlement.json
python -m value_lab.codex_study export $pvlStudy .\work\codex-confirmation-bundle-new --plan-sha256 $pvlPlanPin --settlement .\settlement.json
```

结算文件使用 `format: "pvl-codex-settlement-1"`，仅含以下字段：

| 字段 | 内容与约束 |
| --- | --- |
| `plan_sha256` | 原始冻结计划摘要。 |
| `journal_sha256` | 当前完整日志快照的规范 JSON 摘要；可从不带费用的 `review` 输出 `evaluation.journal_sha256` 取得。新尝试或后续对账事件会改变它，旧结算文件不得覆盖新历史。 |
| `attempts` | 全部登记尝试各一行，含 `attempt_id`、原 `request_id`、`cost`、`human_intervals`；包括失败、取消和诊断重试，不能只交成功项。明确未发送的尝试使用 null 请求身份，其零费用仍须明确凭据。 |
| `cost`（每行内） | `model_usd`、`tool_usd`、`human_minutes`、`basis`、`evidence_ref`。仅 `basis: "settled"` 和可解析的唯一账单行引用满足现金结算条件。缺失/未知金额不填零；人工时间另按原计时区间核算。 |
| `human_intervals`（每行内） | 原始 `actor/start/end` 计时区间；确实没有人工投入时显式传空数组和零分钟。声明不等于独立测量。 |
| `cost_ledger` | 沿用现有 `schema_version/entries/coverage` 合同，明确 judge/setup/retry/other 的覆盖。存在重试时 `retry` 必须声明 `itemized`；重试金额由对应尝试自动转入，不可重复填 ledger 的 retry 条目。 |
| `sources` | 所有尝试及补充成本 `evidence_ref` 到保留原文的映射；仅保留获授权且经过数据审查的凭据内容。 |

费用按原尝试和请求精确对账，全部诊断重试的模型/工具现金和计时人工另行分配到对应槽位，不新增确认性样本。重复凭据、缺失尝试、未结算估价、未核清请求或相互重叠的人工区间不能取得确认支持。`actual_settled_usd` 仅在完整材料通过费用检查时记录提交的现金合计；人工折价单列，未结算上界仍不推定为零。这些引用不认证发票真伪。

`review.evaluation` 保留转换后的原始 `records`、合并后的 `cost_ledger`、完整 `report` 和转换缺口；正式结果在 `report.confirmatory_analysis`。导出包额外保留结算文件的原始字节 `settlement.json`，`verify` 从原始捕获、日志、冻结规则和结算材料重新构造输入并复算全结果。变更结算、删除失败或重试、替换评分源码都会破坏既定包的核验。

`operator_capture` 仍是未认证操作员材料：转换记录明确加入 `HOST_TRANSPORT_NOT_QUALIFIED`，不能仅把来源标签写为 Codex 就取得支持。合成材料可以验证同一条确认链及数值判据，但仍返回 `SIMULATION_ONLY`。取得真实宿主传输证据是独立要求，不能通过更改结论字段补齐。

2026-10-03 的[接入验收记录](../evidence/codex-confirmatory-integration-20261003.json)保留 20 个制造任务族、40 条制造采集记录的完整链路摘要，以及导出后的新进程复算结果；146 项相关测试通过。该记录验证工程接入，未增加真实先导、真实模型调用、已认证账单或第三人人类复核。

## 验收仍需补齐的实际材料

真实验收必须另行取得可核对的Codex版本和模型记录、原生有效工具全集、独立两臂会话与上下文隔离、完整的请求到终态链、全部尝试费用对账，以及第三人人类复算记录。在这些材料缺失时，不把结构字段、哈希、模型自报或模拟测试变成宿主事实。

本入口不启动真实会话、不产生模型请求，也不替用户核实历史账单。v3 确认性评估已接入，真实验收仍需上述证据；整条本地准备、模拟采集、中断恢复、导出和复算演练不能称为 Codex 真实执行验收。确认路径继续遵守[先导与事前确认合同](PILOT-CONFIRMATION.zh-CN.md)，原始文本、结构字段和操作员来源声明不能直接升级成确认成功。

实现入口：[codex_study.py](../../value_lab/codex_study.py)、[观测检查](../../value_lab/codex_evidence.py)、[持久尝试日志](../../value_lab/attempt_journal.py)。
