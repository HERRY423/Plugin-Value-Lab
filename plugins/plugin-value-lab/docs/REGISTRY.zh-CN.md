# 科研 Agent 插件边际价值登记表与选用协议

本次保持 **0.4.0-alpha.1**，Python 包版本仍为 **0.4.0a1**。同版本代码变化用 `engine_sha256` 区分。

产品重点是积累可复核的科研任务、固定条件下的实际边际收益，以及跨时间、跨团队的复核记录。通用 WITH / WITHOUT 评分是测量工具；可积累的资产必须来自真实任务设计、实际运行及真实参与者。本次实现本地积累与交换机制，没有宣称已经取得外部采用或独立科研验证。

## 四类资产及目前边界

| 资产 | 已实现 | 尚需真实积累 |
| --- | --- | --- |
| 科研场景语料 | 8 个可执行的合成种子案例，4 个成对任务族；开发/留出按任务族隔离；答案独立文件与摘要绑定 | 领域专家逐题设计、来源授权、独立任务有效性审查、真正未暴露的留出题 |
| 纵向价值账本 | 插件名称、版本、内容摘要、模型、宿主、观察时间、条件队列、质量/成本差额与双向错误 | 足量匹配实测及完整成本；不能用模拟曲线填补 |
| 交换协议 | suite / runs / lock / usage card / manifest 可携带研究包；完整性验证与离线重算 | 外部插件作者自愿采用；这是项目协议提案，不是行业标准 |
| 独立复核 | 绑定不可覆盖的研究快照；作者/组织/冲突申报；保留支持、异议、不确定及复现实验链接 | 真实外部评审与身份核验；目前认证独立复核数为零 |

## 1. 建立场景集

```sh
python scripts/value_lab.py corpus-seed --output work/corpus-private
python scripts/value_lab.py init --output work/corpus-study
python scripts/value_lab.py corpus-prepare work/corpus-private/corpus.json --template work/corpus-study/suite.json --output work/corpus-study/public-suite.json
```

在新研究目录中使用生成的 `public-suite.json` 作为 `suite.json`；填写真实插件、模型、宿主、环境与预算后，先 `freeze` 再采集。命令拒绝覆盖已有输出。`corpus-prepare` 只读取公开的 `corpus.json`，生成 `sealed` grader，不把预期决定、答案或答案解释放进 suite。答案文件是 `answers.private.json`，只交给离线评分进程。

**种子案例全是公开的合成练习。** 代码中可见其答案，它们只能验证留出流程，不能充当真实保密 benchmark。真实研究应由独立维护者保管答案，运行宿主不得访问答案目录；命名为 private、摘要承诺和 split 标签都不提供访问控制，也不证明从未泄露。修改答案、提示或划分必须形成新语料发布及新研究锁。

公开文件采用严格字段集：`schema_version: 1`、`id`、`evidence_type`、`authors`、`sources`、`truth_sha256`，以及 `cases: [{id,family,split,prompt}]`。`split` 为 `development|heldout`；同一任务族不得跨集合，重复规范化提示拒绝。

答案文件为 `{schema_version:1, answers:{case_id:{decision,result,rationale}}}`。`decision` 是 `allow|withhold`；`result` 是非空对象，按完整对象及 JSON 类型精确比较。答案文件的规范化摘要必须等于公开承诺，且恰好覆盖全部案例。案例响应为 `{decision,result}`；可附加解释，但自动判据不审查解释的科学语义。真实复杂任务仍应组合产物验证和人工评审，不把精确 JSON 匹配称为生物学真值。

```sh
python scripts/value_lab.py evaluate work/corpus-study/suite.json work/corpus-study/runs.jsonl --lock work/corpus-study/protocol.lock.json --corpus work/corpus-private --output work/corpus-report
```

两类错误分别报告，且按开发集/留出集、WITH/WITHOUT 分列：

- `unsupported_acceptance`：应保留结论的任务被放行。
- `over_refusal`：允许的合理分析被拒绝。

每类输出计划数、可解析数、错误数、未知数、错误率及上下界。缺失、失败、重复记录或格式错误保留为未知；存在未知时完整错误率为 `null`，上下界为 `errors/planned` 到 `(errors+unknown)/planned`。没有该类案例时为 `null`。增量是 WITH 减 WITHOUT，越低越好；结果正确性另外计分。错误率是响应决定的描述统计，研究条件、成本等阻断仍由总评保留。

不支持将 `sealed` grader 降格为 Claude 原生文本/模型裁判，因此当前原生 Claude 导出会拒绝此类型。Codex 可采集公开任务；采集后的离线 `evaluate --corpus` 完成评分。不得把答案放进插件快照或运行输入。

## 2. 登记每次研究

研究目录至少包含 `suite.json`、`runs.jsonl`、`protocol.lock.json`；可选 `cost-ledger.json`。元数据格式见 [模板](../examples/registry-metadata.json)。`observed_at` 必须含时区；插件内容摘要由提交方申报，软件不会将其认证为真实加载证明。

```sh
python scripts/value_lab.py registry-add work/my-study --metadata my-metadata.json --registry work/value-registry --artifacts work/my-study --corpus work/corpus-private
python scripts/value_lab.py registry-view --registry work/value-registry --output work/value-registry-view-1
```

非 sealed 研究省略 `--corpus`。可执行产物验证器必须显式传 `--verifiers TRUSTED_DIR`，这会运行本地受信代码，不是安全沙箱。未提供时保留未决结果。

登记操作从原始输入重新计算 report 和 usage card，不采信提交目录中的预制成功报告；只复制记录中明确引用且摘要匹配的产物，不递归收集整个研究目录。缺失或被修改的文件导致评分未决，原始引用和失败保留。私有答案不进入研究包。所有产物位于按 manifest 摘要命名的 `entries/` 下；写锁和暂存目录避免并发覆盖，读取核对完整清单。中断留下的 `.writer.lock` 需检查进程和现场后人工恢复，不自动抢锁。

同一 suite/records 不可换时间标签或重排 JSONL 后重复登记；新增研究复用旧 session 时，两侧都显示 `overlapping_entries`，且禁止当作独立比较，回填更早观察时间也不能绕过。

补交产物、答案、费用或人工判定时，使用 `--parent ENTRY_ID --revision-reason "实际补证说明"`。修订必须保持原冻结 suite、观察时间、作者和插件内容身份；改协议应建新研究。系统重新计算全部材料，没有新增评估证据的空修订会被拒绝。旧快照保留，显示 `superseded_by`；新旧归入一个 `lineage_root`，以 `study_lineages` 与 `evidence_revisions` 区分研究历史和修订数量。原始 `registered_studies` 字段仍是快照数量，不能当作独立研究样本量。

```sh
python scripts/value_lab.py registry-add work/my-study --metadata my-metadata.json --registry work/value-registry --artifacts work/my-study --parent ENTRY_ID --revision-reason "补交先前缺失的原始产物"
```

祖先记录的异议在新修订中显示为 `ANCESTOR_DISPUTED`，暂停描述性增益比较，不把旧意见误当成针对新结果的实际评审。当前没有自动解决异议机制；新增支持意见不会抹去它。存在共用会话的旁支修订也不会作为独立比较。零运行、失败和不完整研究可以登记，但不会制造可用的质量差额。缺少或与 suite 不符的锁拒绝登记；软件不能鉴别伪造的匹配锁或事后冻结。

队列比较固定任务、判据、策略、重复数、宿主、工具、环境、预算、语料、证据类型与评分代码。插件修订和模型是显式比较轴；两者同时变动不做单因素归因。不同宿主或任务队列不合并。每行成本差额保留 `null`，不跨研究汇总不同成本口径。记录的观察时间由作者申报，登记时间由本机生成，都不是第三方见证的预注册时间。

## 3. 交换与重算

```sh
python scripts/value_lab.py registry-export ENTRY_ID --registry work/value-registry --output work/submission-1
python scripts/value_lab.py registry-verify work/submission-1
python scripts/value_lab.py registry-replay work/submission-1 --corpus work/corpus-private
```

需要交接复核意见时，使用包含复核快照的导出：

```sh
python scripts/value_lab.py registry-export ENTRY_ID --registry work/value-registry --with-reviews --output work/review-submission-1
python scripts/value_lab.py registry-verify work/review-submission-1 --expected-id PACKET_ID
python scripts/value_lab.py registry-replay work/review-submission-1 --corpus work/corpus-private
```

`pvl-review-packet-1` 包含 `study/` 原快照和 `review-history.json`，后者保留直接复核、祖先异议、申报作者关系及当时观察到的会话重叠/后继版本引用。它不复制其他研究的私有产物；祖先和复现实验只提供引用，不冒充已经重算这些研究。外层 manifest 绑定全部文件，`packet_id` 用于核对整个交接包；原始 `entry_id` 不变。请通过另一份可信记录保留 packet ID，避免只依赖包内自行生成的摘要。`--expected-id` 对普通研究包使用 entry ID，对复核交接包使用 packet ID。

复核包反映导出时刻，不包含之后的新意见，也不证明导出方没有隐瞒其他记录。普通导出明确返回 `review_history_included: false`；不能拿它宣称没有异议。重算返回 `REPRODUCED` 只表示评分一致，复核包中 `DISPUTED`/`ANCESTOR_DISPUTED` 仍保留，不等于争议已解决。

研究包格式 `pvl-study-bundle-1` 包含 suite、runs、lock、metadata、report、usage card、registration、可选费用账本/公开语料，以及明确引用的 artifacts。`manifest.json` 记录各文件字节摘要，manifest 的规范化摘要就是 `entry_id`。接收方应另行保留该 ID；攻击者重写整个目录和清单不能靠自带摘要检测。

`registry-verify` 只核对字节完整性。`registry-replay` 重新评分，不自动执行包内代码；同报告且同引擎返回 `REPRODUCED`/退出码 0，其余 `REPLAY_DIFFERS`/退出码 2，并显示新报告及阻断。缺答案、缺受信验证器和引擎变化不会冒充可重复。这里的重复是计算重算，不是独立实验复制。

外部研究包可以作为 `registry-add` 的 study 输入再次重算登记（产物目录用 `--artifacts BUNDLE/artifacts`，独立答案经授权另行提供）。登记和导出只操作本地文件，不上传、发布或发送邀请。

## 4. 复核与异议

模板见 [review JSON](../examples/registry-review.json)。填写真实信息后：

```sh
python scripts/value_lab.py registry-review review.json --registry work/value-registry
```

复核必须绑定 `entry_id`，声明 reviewer、organization、relationship（author/collaborator/independent/unknown）、conflicts、verdict（support/dispute/inconclusive）、rationale、reviewed_at、证据引用及摘要；无复现实验时 `replication_entry_id: null`。作者本人、同组织或已申报冲突不能标 independent。引用只登记，不自动读取或联网核验，其哈希也不证明审稿者身份。与研究作者相符的别名无法可靠自动识别。

所有意见保留，新增支持意见不会覆盖异议；任何异议使记录显示 `DISPUTED` 并退出可比较增益集合。复现实验链接另查固定条件、模型、插件、会话、合成/不完整状态及作者/组织重叠；符合者也只叫“申报的可比较复现”，不认证独立性。没有真实评审时保持 `UNREVIEWED`，不生成机器人冒充专家的复核。

## 本地验收与演示

```sh
python scripts/check_registry.py --output work/registry-check-new
```

该命令生成一个明确标为 synthetic 的研究、缺失费用的原快照、补证修订、未复核交接包及 HTML 登记页，并检查固定摘要和离线重算。没有模型调用、真实费用观察或模拟专家签字；输出目录必须不存在。

本轮完整本地测试 **271 项通过**，其中登记/语料测试 34 项、命令行测试 5 项；还通过了新增代码的静态检查、wheel 隔离导入与复核包重算，22 个运行模块与源码字节一致。受限进程无法读取隔离安装目录，隔离导入验收在具有该目录读取权限的环境中完成。完整记录见 [VERIFICATION.json](../VERIFICATION.json)。这些验证不代表外部采用、独立评审或实际科研收益。

## 积累顺序

先招募领域作者提供授权且可执行的真实任务，由非作者审查任务有效性和两类错误的适用性；随后在固定条件下收集 WITH/WITHOUT 全部运行与成本；最后邀请另一团队用相同冻结协议复现。每一步通过上述接口留下独立可审查的记录。只有这些真实贡献持续积累，登记工具才可能形成难复制的资产。
