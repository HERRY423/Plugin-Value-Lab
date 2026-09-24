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

## 本次验收边界

本机 WSL2 内核实 Claude Code 2.1.278、Python 3.14.4、bubblewrap、socat；无网络空命令可启动。四个用例的生成 scaffold 与操作者编写的对照脚本已实际执行，输入摘要一致，十项产物检查通过；两张有效表另外与 SciPy BH 结果交叉核算。此处不是 Claude 生成脚本或新的模型运行，未验证评分参考不可访问。

完整材料位于 `C:/Test/native-analysis-20260924`，实际本地检查位于 `C:/Test/native-analysis-local-validation-20260924`。既有 P0 原生采集包继续重算，原来的科学错误与证据缺口保持。自动测试中的原生事件明确为制造数据，不伪装成宿主执行记录。

独立专家审阅、另一位使用者的外部重跑、完整插件/跨宿主新研究与真实修复时间收益仍待完成。本轮未新增付费模型或目录调用；此前未知结算不改写为零。

完整工程测试 **491 项通过，零失败、错误和跳过**。静态检查与历史原生包复算通过；[机器验收摘要](evidence/native-analysis-20260924.json)保留各层结果。
