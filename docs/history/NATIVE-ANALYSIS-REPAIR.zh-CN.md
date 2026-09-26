> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# 原生科研分析与完整修复复测

本轮继续落实“原生互通、真实文件分析、可信错误判断和修复流程”，版本仍为 0.5.0。P1 的科研场景与 P2 的限定比较、条件化建议继续使用，不增加指标或公共认证流程。

## 分工与支持范围

`prepare-native-analysis` 将科研文件任务准备成 Claude 原生用例，生成独立候选副本、输入准备脚本、冻结规则和执行参数。执行仍由 `claude plugin eval` 完成；PVL 不再造模型执行器，不在离线采集时运行产物中的脚本。

官方用例中的 `file_exists` 仅检查文件交付。科研评分合同独立保存，运行结束后由 PVL 重算；没有把科研验证器等价翻译为官方评分器。原生汇总导入仍是诊断，不自动晋升为价值研究。

当前准备配置适用于明确选定文件的技能/代码插件，工具为 Read、Skill、Write、Bash；不包含启动 hook、MCP 或 LSP 服务。其他完整插件继续沿用已有原生用例和 `prepare-native-evidence`，不要裁掉实际依赖后声称测过完整插件。

依据 [Claude 官方说明](https://code.claude.com/docs/en/plugin-evals)，shell 分析需要受支持的沙箱，Windows 使用 WSL2；scaffold 在 Agent 沙箱外运行。上述执行边界于 2026-09-24 核对。生成操作只准备文件，不授予或启动执行。

## 准备文件任务

配方含 `schema_version: 1`、`plugin_files`、`execution_context`、`cases`。`execution_context` 必须写明 `host_version`、`model`、`model_version`、`environment`、`tools`、`max_turns`、`timeout_seconds`、`max_cost_usd`。这些是事前声明，精确模型权重与环境真实性不会因为填了字段而得到认证。

每个 case 包含：

- `name`、`prompt`、`repetitions`：明确任务与完整复测次数。
- `inputs`：从输入 ID 到 `{path, sha256}` 的映射；文件会复制到工作目录，摘要在执行前冻结。
- `artifacts`：从产物 ID 到工作目录相对路径的映射；包含分析脚本和结果。
- `execution`：如 `{"script_artifact":"script","command":"python3 analysis.py"}`；对应精确的前台 Bash 调用。
- `graders`：已有内置科研合同；评分参考另设目录。

```sh
python scripts/value_lab.py prepare-native-analysis recipe.json --plugin CANDIDATE --inputs PUBLIC_INPUTS --references SCORERS --output NEW_STUDY
```

先检查 `ANALYSIS.md`、`execution-plan.json` 和候选中的 `fixture.sh`。在实际执行环境生成计划，避免把 Windows 绝对路径直接用于 WSL。生成命令完整保留两个实验臂、用例规定次数、输出目录、保留工作区和不发布选项。费用是原生估算阈值，在途运行可能超出；命令文件本身不是付费执行授权。

本轮另提供四个披露的工程对照：完整检验集合、并列及零/一边界值、越界 p 值、重复 ID。正常输入同时检查 BH、原始 p/效应保留与不应拒答；无效输入只检查声明的拒答边界，不把一个正确拒答字段当作所有文件均无误的保证。

```sh
python scripts/prepare_native_bh_analysis.py --plugin CANDIDATE --selection selected-files.json --context context.json --output NEW_MATERIALS
```

`selected-files.json` 是明确文件列表，也可以是已有原生合同（取其 `plugin_files`）。默认每个案例每臂三次，共 24 个计划会话；未实际完成的会话必须保留为缺失。该脚本生成 `recipe.json`、输入、单独评分参考与 `study/`，不运行模型。这些对照不是生物样本或独立保留集。

## 采集、诊断与复核

运行后沿用 `native-bindings`、`capture-native-evidence`、`verify-native-evidence`，详见[原生采集](NATIVE-EVIDENCE.zh-CN.md)。新增字段按需启用，旧合同和旧采集包保持可重算。

诊断按证据定位下一步：输入变更或缺失 → 运行失败 → 缺少成功脚本记录 → 缺失产物/参考 → 产物合同不满足 → 计算检查通过后待解释审阅。每层保留原始事实和文件，不从错误直接推断插件是原因。

脚本检查只关联原始事件中的精确 Bash 命令、tool_use ID 与对应 tool_result。背景启动、缺少返回、重复 ID、乱序事件、失败尝试和模型冲突都保留；最终回答写“执行成功”不能替代工具记录。最终保存脚本的摘要，也不能证明运行瞬间执行的正是这些字节。`TOOL_REPORTED_SUCCESS` 仅表示提供的日志如此记录，不是受认证执行或科学正确。

输入检查比较采集时的字节和冻结摘要，可以检出最终缺失或改写，不能证明运行中从未改写又恢复。评分参考与计划需要实际访问隔离，目录分开放置本身不是隔离证明。

## 完整修复复测

只修改候选插件，在新目录冻结和重跑原用例；不要修改输入、评分器、阈值、次数、对照臂或执行条件。

```sh
python scripts/value_lab.py compare-native-repair BEFORE_CAPTURE AFTER_CAPTURE --before-receipt BEFORE_PINNED_DIGEST --after-receipt AFTER_PINNED_DIGEST --output NEW_REPAIR_REPORT
```

比较器先复算两个包，再检查全部合同、用例字节、参考材料、选定候选文件变化、输入摘要、完整运行、会话复用、模型/宿主/工具及插件暴露。缺字段不由期望设置补填；仅修改版本清单不算代码修复。

`REPAIR.md` 保留每个案例和两臂各检查的通过、失败、未知次数。原生数组位置不视为随机配对，不计算因果效应。基线变化、正常对照退步、条件变化、缺失及失败各有独立状态。只有条件检查通过、启用臂全部检查通过、原有失败消失、基线未变化，才报告 `LOCAL_RETEST_IMPROVEMENT`；这仍是选定材料的局部复测改善。

价值决策继续使用完整冻结研究和 [P2 条件化建议](P2-REUSE-GUIDANCE.zh-CN.md)。本接口始终保留 `comparison_eligible=false`，不会自动发布、认证、卸载插件或把本机复测计为独立采用。

## 分类修复与作者过程记录（2026-09-26 修正）

以下修正已有比较器行为，版本仍为 0.6.0。历史采集包不改写。每个新 case 可在准备前声明 `repair: {"kind": "execution", "skill": "plugin-name:skill-name"}`，该字段进入冻结合同，两轮必须一致；仅在修复记录中声称类型无效。不声明时沿用 `scientific_artifact`。

| kind | 修复前要求 | 修复后及对照要求 |
| --- | --- | --- |
| `scientific_artifact` | 成功插件调用先于成功脚本执行；实际产物判据失败 | 相同规则下产物通过，调用与执行链完整 |
| `execution` | 完整会话里的工具错误，或原生错误与终止错误相互支持；与被测插件调用尝试相连 | 成功插件调用、脚本成功、全部产物检查通过；失败保留在分母 |
| `trigger` | 已加载被测插件、完整自然任务轨迹、被测插件确实未调用 | 正确技能成功调用且先于产物脚本；全部产物通过；必须包含负对照 |
| `negative_control` | 冻结的不需要插件的自然任务 | 两轮两臂都检查未调用被测插件；调用失败也算多余调用 |

执行观察区分 `OBSERVED_SUCCESS`、`OBSERVED_FAILURE`、`UNKNOWN`。`execution_observations` 保留逐次观察，`reliability_counts` 与 `reliability_denominators` 覆盖计划中的全部运行。缺终止事件、重复调用 ID、日志与汇总矛盾、模型漂移保持未知。仅有“timeout”文字不能替代完整错误轨迹。完整崩溃可以发生在脚本创建前，不要求凭空补出成功脚本。

新增的 `$execution`、`$trigger` 是冻结类型对应的比较端点，不能用作自定义 grader ID；在 `repair_record.repairs[].grader_id` 中引用实际失败端点。原始产物评分单独保留，崩溃后缺产物不改写成科学错误。原生记录失败而产物看似正确也不会成为执行成功。比较状态仍需完整条件、无退步、无基线变化；`LOCAL_RETEST_IMPROVEMENT` 与 `TRACE_SUPPORTED_LOCAL_CHAIN` 不建立因果收益或科学真实性。

这里的调用观察仅覆盖原生 `Skill` 协议。直接读取技能文件或其他调用方式不能据此判为插件未使用；适用性须在冻结任务时确定。自然措辞仍是作者声明，未被独立认证。

作者修复记录现在可以引用仍未修好的失败检查；对应 link 的 `outcome` 为 `NOT_REPAIRED`，修复链保持 `OPEN`。不要删除失败尝试来获得完整链。

可选 `repair_record.process` 包含 `origin` 和 `events`。`origin` 为 `previously_unknown`、`known_seed` 或 `retrospective`。每个事件严格包含：

```json
{
  "stage": "diagnosis_seen",
  "at": "2026-09-26T09:00:00+00:00",
  "details": "实际作者当时看到的诊断与理解；示例不是观察证据",
  "evidence_sha256": "<对应留存材料的真实 SHA-256>",
  "outcome": null
}
```

按 `diagnosis_seen → hypothesis → edit → retest` 记录；失败后追加 `hypothesis → edit → retest`，不覆盖原尝试。时间必须带时区、严格递增。首个摘要必须绑定修复前重新计算的诊断；最终 edit 摘要必须等于比较报告的 `selected_change_sha256`（所选文件两轮摘要映射），最终 retest 必须绑定本次 after receipt。`retest.outcome` 为 `failed`、`unknown` 或 `improved`，且最终改善声明必须符合比较结果，其他事件 outcome 为 null。

作者应实际保留假设文字、有限代码差异和每次原生采集包，再填入相应摘要；先用不含 process 的记录离线比较即可取得 `selected_change_sha256`，随后另建输出目录生成完整过程报告。此操作不会产生新观察。中间尝试摘要和作者时间线当前只被留存，**没有逐包复核或独立时间认证**；字段 `intermediate_evidence_verified`、`all_attempts_independently_verified` 明确为 false。

已知种子标为 `KNOWN_SEED_RESTORATION`，没有过程为 `NOT_RECORDED`，其他合规过程仅为 `AUTHOR_DECLARED_PROCESS`。`pvl_helped_author_established` 始终为 false。真正验证“PVL 帮助作者修复”还需要事前保留的未知缺陷诊断、真实作者假设与改动、完整自然复测及对照；本次软件修正和合成回归测试没有提供这种新实验。

## 历史验收边界

本机 WSL2 内核实 Claude Code 2.1.278、Python 3.14.4、bubblewrap、socat；无网络空命令可启动。四个用例的生成 scaffold 与操作者编写的对照脚本已实际执行，输入摘要一致，十项产物检查通过；两张有效表另外与 SciPy BH 结果交叉核算。此处不是 Claude 生成脚本或新的模型运行，未验证评分参考不可访问。

完整材料位于 `C:/Test/native-analysis-20260924`，实际本地检查位于 `C:/Test/native-analysis-local-validation-20260924`。既有 P0 原生采集包继续重算，原来的科学错误与证据缺口保持。自动测试中的原生事件明确为制造数据，不伪装成宿主执行记录。

独立专家审阅、另一位使用者的外部重跑、完整插件/跨宿主新研究与真实修复时间收益仍待完成。本轮未新增付费模型或目录调用；此前未知结算不改写为零。

完整工程测试 **491 项通过，零失败、错误和跳过**。静态检查与历史原生包复算通过；[机器验收摘要](../evidence/native-analysis-20260924.json)保留各层结果。
