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
