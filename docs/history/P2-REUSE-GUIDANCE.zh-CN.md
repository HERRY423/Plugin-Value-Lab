> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# 独立复用交接与条件化使用建议

P2 沿着原建议只推进“外部重跑、限定条件比较、按场景使用建议”。不扩建公共登记平台，不增加统一认证分数或新的宿主适配器。无需登记、上传材料或调用模型即可使用下面的流程。

## 1. 准备可以交给别人复核的材料

准备已有真实研究目录中的 `suite.json`、`runs.jsonl`、`protocol.lock.json` 和可选 `cost-ledger.json`，以及实际产物目录。不要删掉失败、补造缺失记录或改写旧锁。

```sh
python -B scripts/value_lab.py reuse-prepare STUDY --artifacts ARTIFACTS --output HANDOFF
python -B scripts/value_lab.py reuse-replay HANDOFF --expected-id SAVED_PACKAGE_ID --output NEW_REPLAY
python -B scripts/value_lab.py reuse-inspect HANDOFF --expected-id SAVED_PACKAGE_ID --receipt NEW_REPLAY
```

生成时打印的 package ID 应另行保存；接收人用可信交接渠道取得它，而不是仅从收到的文件自行重新计算。哈希只能发现相对于已保存摘要的更改，不能认证作者身份。

产物按运行记录的文件清单收集，不递归复制整个工作区。评分参考默认不进入交接包；需要时，在准备和重跑时显式传 `--verifiers SCORERS`，并使用下列命令另行交付必要的评分材料：

```sh
python -B scripts/value_lab.py reuse-scorers HANDOFF --expected-id SAVED_PACKAGE_ID --verifiers SCORERS --output SEPARATE_SCORERS
```

只复制冻结依赖清单中引用的文件；不会把无关文件夹一起带走。评分材料不得放进 Agent 工作目录；分目录不是操作系统隔离。重跑入口只支持内置离线评分器，拒绝直接或隐藏在 scenario 内的 executable/exec/sealed 评分器，不执行收到的程序。

重跑会留下 `receipt.json`、`report.json` 和 `dependencies.json`：

| 状态 | 含义 |
| --- | --- |
| REPRODUCED | 相同材料、评分引擎、运行环境下重算报告一致 |
| REPLAY_DIFFERS | 引擎、环境或报告发生变化；保留逐字段差异 |
| MATERIALS_REQUIRED | 有材料缺失、变化或缺依赖；不能声称完整重跑 |

`assessment_complete` 另行显示原研究是否满足比较条件。重现一个“证据不足”报告仍然是证据不足，不会变成有效性结论。重跑返回 `new_observations=0`、`new_independent_samples=0`，即使另一位使用者操作，也不会把旧观察计成新独立样本。

实际参与者可以提供 `--participant declaration.json`：字段为 `operator`、`relationship`（same_team/self_reported_external/unknown）及真实原文 `feedback`。不要预填他人的反馈。`reuse-inspect` 检查回执与产物是否自洽，**不认证参与者身份、独立性或真实执行**；外部声明仍是未认证声明。公开发布或发送材料仍需另行授权。

## 2. 科研场景的一次性交接

```sh
python -B scripts/prepare_reuse_delivery.py STUDY --artifacts ARTIFACTS --pseudobulk-reference PSEUDOBULK_REFERENCE --output DELIVERY
```

这会生成上述研究重跑包，以及供体差异分析的 public inputs、separate scorers、实际依赖版本和复算说明。它不运行参考拟合、不安装依赖、不邀请参与者、不上传数据。交接文档同时提供“只复核已有产物”和“显式重新运行 PyDESeq2”的路径。

依赖版本来自实际运行记录，不等于其他平台安装成功。不同环境下的数值差异应保留诊断；不能为追求一致只报告成功重跑。重新分析同一份数据不增加独立供体数。材料可交接不等于独立审阅已经发生。

## 3. 限定宿主、模型或插件的一项变化

`compare-studies --axis host|model|plugin|replicate` 增加显式边界；不提供 `--axis` 时保持原有行为。

两个 JSON 输入各包含完整 `suite`、`records`、`lock`，可选 `cost_ledger`，以及以下真实来源的 `context`：

```json
{
  "plugin_sha256": "完整的已采集插件内容摘要",
  "engine_sha256": "评分引擎源码摘要",
  "lineage_id": "该次新研究的谱系标识",
  "observed_at": "实际观察时间，含时区"
}
```

上述只是字段说明，不可直接当作合格输入。`conditions` 必须同时包含明确的 `host_version` 和 `model_version`，由实际记录支持，不能靠别名猜测。只放行指定轴上的变化；输入、任务、真值、政策、预算、其他环境和引擎变化均保留阻断。同一谱系补证、复用会话或模拟资料不能变成新的实际比较。版本和身份字段本身仍不能认证服务商。

报告同时显示基线变化、启用插件后的变化和有/无插件差值的变化。基线改善且启用结果不降时，可描述“边际增益缩小”；启用结果下降时，显示下降观察。两者都不自动构成原因证明。

## 4. 先冻结决策边界，再收集结果

新研究的 `suite.policy` 可加入：

```json
"use_decision": {
  "version": 1,
  "scope_rationale": "写明具体任务及允许据此试用的条件",
  "minimum_gain": 0.10,
  "maximum_quality_loss": 0.05,
  "maximum_cost_increase_usd": 0.10,
  "maximum_failure_rate": 0,
  "require_settled_costs": true
}
```

数字只是结构示例，应在观察前依据真实需求确定。修改这些字段会改变协议摘要，旧研究不补写新阈值。成本上限指相对于另一个臂的每计划运行平均完整成本增加；不等于 API 消费硬上限。要求结算时，两项研究都须具备完整结算引用；引用不认证账单。

目标文件包含完整 `plugin`、`plugin_sha256`、`conditions` 和拟使用的完整 `cases` 定义。目标必须精确匹配已测试条件；只匹配任务名称或主题不够。目标可以选择已测试任务子集，但报告保留原研究的全部案例和负结果。

```sh
python -B scripts/value_lab.py conditional-guidance BEFORE.json AFTER.json --axis model --target TARGET.json --output NEW_GUIDANCE
```

文件产物可分别用 `--before-artifacts`、`--after-artifacts`、`--before-verifiers`、`--after-verifiers` 指定。程序重新评分原始记录，不信任预先填写的总分或推荐。

输出 `GUIDANCE.md` 和 JSON，逐场景给出“优先试用插件并复核”“试用基线并复核”或“先复核”。任何试用建议都需完整可比证据、质量下限、关键检查、成本与风险界限。选择基线还要求每次已观察重复的最大质量损失不超过预设值；均值接近零不够，未发现增益也不等于无用。

**有限样本上的最大损失不是未来损失的置信上界，更不是确认性非劣效证明。** 建议只适用于已测试的具体任务和固定条件，不自动推荐新数据集，不自动升级、关闭、卸载或改变权限。旧研究继续使用原有 `usage-card` 做诊断；没有新可比记录时不生成推广结论。
# 冻结范围与指标适用性（2026-09-26）

本次按用户明确提出的三项改进深化既有使用卡，版本保持 0.6.0；未新增 CLI、MCP、技能、评分器或运行时模块，也未修改冻结接口清单。以下两个可选 suite 字段必须在冻结前写入，纳入原 suite 摘要；已有研究不补写、不重封为新证据。

```json
{
  "usage_scopes": [{
    "id": "bounded-transform",
    "families": ["table-transformation"],
    "rationale": "仅对这一类预先指定的转换任务提供局部参考，不外推",
    "min_clusters": 1,
    "min_complete_pairs": 6
  }],
  "metric_applicability": {
    "table-transformation": {
      "over_refusal": {
        "status": "not_applicable",
        "reason": "填写任务为何没有拒答决策端点；不要照抄示例充当复核",
        "review": {"reviewer": "实际复核者", "basis": "实际审阅的任务与输出契约依据", "accepted": true}
      }
    }
  }
}
```

必测声明写为 `{"status":"required"}`；未声明时误拒答仍按必测处理。当前可声明适用性的指标仅为 over_refusal；其他质量、关键判据、成本、执行要求保持原规则。不适用必须包含非空理由、有名有据的接受复核，且不能与该族的直接决策判据、scenario/sealed 决策容器或冻结 decision_error_limits 矛盾。复核记录属于声明，程序不能认证评审身份或替代其科学判断。

范围选择以完整 `cluster` 为单位，禁止案例子集、重复范围与相互重叠的范围。最低证据数是事前门槛，少于两族的范围只能给该狭窄范围的描述性参考，不能称统计独立或泛化已证实。质量下限、增益阈值、单案例回退限制、目标及费用要求继承原 policy；两方向决策错误上限按该范围的原始案例、原 split 重新核对，不能省略某个方向。原研究的锁、来源、条件、会话唯一性、时间完整性等共享问题会阻断所有范围。结算策略若启用，仍须满足完整结算引用要求。

范围比较复用原研究全部逐次评分和原先分摊到每次运行的成本，不重写记录摘要、不制造子研究锁、不把共同设置费用转给范围外案例。范围外的执行缺失或负向结果继续出现在全研究和对应任务族中；仅当范围内全部材料完整、共同成本覆盖已明确、最低样本数及原判据都满足时，局部结论才可独立成立。声明但未满足范围门槛时，也不能回退到全研究绿灯绕开该门槛。

`card.json.scope_assessments` 保存范围声明、所有 case ID、完整/计划配对数、继承规则、原始 suite/records 摘要、成本差、范围阻断与负向证据。`source`、顶层 `verdict` 和整项改进清单不被局部结果覆盖；顶层 `status=REVIEW_REQUIRED` 与某范围 `LIMITED_TRIAL` 可以同时存在。`use_when` 中局部条目带 `scope_id`，表明是范围层结论，不宣称每个案例各自证明了增益。

HTML 和 Markdown 使用同一文字结论：基线优先、观察到退步、观察到风险、证据不足、限域试用、尚未测试。基线优先为蓝色，不与风险共用红色。无负向项的提醒框用中性色；一个范围有退步不会把其中没有退步观察的任务族也涂成“观察到退步”。局部范围详情显示自身门槛与阻断，整项负向证据仍优先展示。

指标状态单列在 `envelope.rows[].metric_status`：`MEASURED`、`NOT_MEASURED`、`UNKNOWN`、`NOT_APPLICABLE`。后两者和未测均不以零错误率代替；不适用保留原因与复核。自然发生“没有拒答”不等于已测误拒答；没有 grader 也不自动等于不适用。

`diagnose` 的普通研究目录分支读取固定文件名 `cost-ledger.json`；不搜索其他账本、不推断成本为零。端到端回归将它与已有 `usage-card --cost-ledger` 的整个 card JSON 比较，覆盖额外设置费改变建议、未知金额、无账本和损坏账本。

这些是本地决策逻辑和展示修正。冻结摘要不认证预注册时间、独立评审、运行真实性或真实用户收益；本次没有新增真实效益研究。
