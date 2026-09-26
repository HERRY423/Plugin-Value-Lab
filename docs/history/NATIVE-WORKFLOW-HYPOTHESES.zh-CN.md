> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# 既有原生用例的附加采集与可检验修复假设

本轮衔接“准备 → 官方执行 → 保留目录绑定 → 科研产物检查 → 可证伪诊断”。原生汇总导入仍不推定缺失的会话、加载或人工审阅，科研评分也不转换为关键词匹配。版本保持 0.5.0。

## 1. 直接沿用既有用例

已使用 `prepare-native-evidence` 冻结原有用例与附加科研合同的作者，不需要重写 prompt、case.yaml 或官方 graders。新增入口接收原命令的参数数组、既有计划及其外部保存的摘要。

```sh
python scripts/value_lab.py prepare-native-session PLAN --plan-sha256 PLAN_DIGEST --plugin EXISTING_PLUGIN --invocation argv.json --references SCORERS --output NEW_SESSION
```

`argv.json` 可以是参数数组，也可以是含 `argv` 的对象。命令形式为 `claude plugin eval CANDIDATE ...`。本轮受支持的集成配置：Linux/WSL、Claude Code 2.1.278、显式模型、完整双臂、每个案例相同且明确的 `--runs`、`--max-cost-usd`、并发 1、MCP mocks record；可保留已有 Write/Edit/Bash 授权与 scaffold 选择。不会自动增加工具授权或 `--trust-plugin`。

工具只增加保留工作区、不发布和新的输出位置；原用例及选定插件字节保持不变。过滤单个失败案例、真实服务器、其他版本或不支持的参数会在付费执行前拒绝，并提示保留原命令走已有离线采集路径，不偷偷降低原实验要求。

准备阶段只调用本地版本检查和隔离探测，不调用模型。`COLLECTION.md` 与 `COLLECTION.json` 解释：采集什么、为什么采集、将使用哪个原生命令、预计会话数量、费用估算阈值、在途超出风险、可写目录及证据边界。原生估算不是结算；未知费用不记成零。

审阅并获得执行授权后：

```sh
python scripts/value_lab.py run-native-session NEW_SESSION --session-sha256 SESSION_DIGEST --execute
```

这仍然只启动官方 `claude plugin eval` 一次。工具复核源文件、执行器和隔离后端，保存独占启动标记与进程日志，等待进程及其子进程结束，再自动沿原生 tracePath/init.cwd 绑定工作目录并独立评分。不存在结果文件时明确记录缺失；存在失败、部分结果、缺失 trace 或工作目录时继续保留未知，不补造输出或会话。

如果模型执行已结束、采集阶段中断：

```sh
python scripts/value_lab.py finish-native-session NEW_SESSION --session-sha256 SESSION_DIGEST
```

这个入口只做离线收集，可恢复已经封存但尚未写完成标记的采集包；不会重启模型。进程终止状态不明时拒绝恢复和再次执行，须先查明。重复执行同一个冻结计划也被拒绝。无法封存的半成品目录保留供检查，不自动删除或覆盖。

已完成但证据不全的旧采集包不会被新解释覆盖。更新兼容性后可使用 `native-bindings RESULT --retained-root RETAINED --output NEW_BINDINGS.json`，再用 `capture-native-evidence` 写入新的采集目录；始终保留旧包与摘要。本轮补齐的 Linux 2.1.278 目录迁移仅在 `tracePath` 精确位于同一 `claude-eval-*/out/trace.jsonl`、`init.cwd` 精确指向该目录的 `home/cwd`、该原位置已不存在而 `sealed/home/cwd` 存在时接受。两个位置同时存在则拒绝。目录名不证明封存成功，内容继续视为不可信，只读取声明的文件，不执行其中脚本、Git 或配置。

## 2. 评分参考的实际访问边界

集成入口使用现有 bubblewrap，将宿主文件系统只读挂载，仅放行当前原生输出、临时工作区及已存在的 Claude 配置目录所需写入；评分参考与冻结计划映射为空的只读目录。评分引擎在外层父进程中，模型进程结束后才接触参考进行复算。

私有 PID/proc 命名空间避免通过父进程的 `/proc/PID/root` 访问原路径。WSL 的 `/init`、互操作目录及 WSL_INTEROP 入口另外遮蔽。准备时与真正启动前都会实际检查指定文件的读取、既有文件写访问、替代文件创建，并尝试无害的 Windows 命令作为互操作探测。检查失败时不启动模型。

准备阶段还会在相同隔离环境中运行执行器版本检查，防止宿主上可用的 Windows 包装器在隔离内无法启动。评估目录出现未冻结的用例时也会拒绝准备，以免原命令启动额外工作。

本地已对 **9 个目标（冻结计划与 8 个评分参考）**完成这三类访问测试，全部不可访问或替换，宿主字节保持不变，Windows 互操作测试未启动成功。这证明的是这组指定路径在所测试命名空间中的访问限制，不认证全部宿主配置、未声明的副本、先前暴露、模型训练数据、独立盲法或科学有效性。未来环境必须重新探测，不能沿用本机结果。

## 3. 六级事实与可证伪假设

准备一个小型 `expectations.json`，覆盖全部原案例：

```json
{
  "cases": {
    "csv-bh": {
      "expected_skills": ["ngs-analysis-pvl-canary:understand-ngs-results", "understand-ngs-results"],
      "conclusion_grader_ids": []
    }
  }
}
```

技能映射是操作者的诊断预期，不是事后新增的科研评分。结论层只能指向已经冻结的检查；没有检查或真实审阅时保持“未评估”，不对模型文字自动判定生物学真伪。

```sh
python scripts/value_lab.py native-hypotheses CAPTURE --receipt-sha256 CAPTURE_DIGEST --expectations expectations.json --output NEW_HYPOTHESES
```

`hypotheses.json` 和 `HYPOTHESES.md` 逐项区分：

| 层级 | 使用的事实 | 不作的推断 |
| --- | --- | --- |
| 加载 | init 中实际插件列表 | 缺失 init 不等于未加载 |
| 触发 | Skill 调用、ID、事件行与返回记录 | 不完整日志不能证明没有调用 |
| 能力选择 | 实际调用与明确预期的差别 | 调用其他技能不自动证明选错方法 |
| 执行 | 原生失败、命令及工具返回 | 正确的部分文件不抹去运行失败 |
| 产物 | 冻结规则的通过、失败、未知及文件收据 | 计算通过不等于生物学真值 |
| 结论 | 被明确指定的已有决策/结论检查 | 不捏造专家审阅或主张有效性 |

每项假设包含事实引用、尚未检验的解释、单因素干预、预期结果、反证条件和必须保留的任务/对照。原有 `usage-card` 的作者改进清单也加入预期与反证条件，原协议与全部失败仍保留。

## 4. 明确调用只用于定位

```sh
python scripts/value_lab.py prepare-trigger-diagnostic NATURAL_PLAN --plan-sha256 NATURAL_PLAN_DIGEST --expectations expectations.json --references SCORERS --output NEW_PROBE
```

探针只复制已冻结的选定候选与用例，在原 prompt.md 后追加固定的明确调用指令。原 prompt 及参考保留；不改模型、方法、评分阈值或用例列表。`case.yaml` 内嵌提示不被猜测性改写。探针合同绑定原计划并标记 `explicit_invocation`，不能冒充普通修复研究。

实际获得自然与明确调用两份采集包后：

```sh
python scripts/value_lab.py compare-trigger-diagnostic NATURAL_CAPTURE EXPLICIT_CAPTURE --natural-receipt NATURAL_DIGEST --explicit-receipt EXPLICIT_DIGEST --expectations expectations.json --output NEW_CONTRAST
```

只有精确指令追加、候选/输入/参考/上下文不变、不同且完整的会话、真实 Skill 成功返回以及原产物检查通过，才可能建议“下一步检验触发描述”。重放、模型变化、丢输入、失败返回、无绑定探针或其他提示改写均不会形成这条建议。它仍是诊断性对照；提示帮助和采样波动仍是替代解释，没有建立触发描述的因果根因。

比较结果始终 `comparison_eligible=false`、`natural_use_value_replaced=false`。应在自然提示下重新完整复测，才讨论用户实际使用的效果。若自然条件本来已经产物正确，也不能仅因缺少 Skill 调用而声称插件有应修复的价值缺陷。

## 5. 本次真实材料与边界

历史 P0 CSV 包在新路径下复核得到：WITH 已加载插件但未观察到 Skill 调用，产物计算通过；WITHOUT 未加载插件，BH 产物检查失败；两臂结论层均未接受额外审阅。这保留了历史事实，并没有把一次差异归因为插件增益。

这份历史报告与未执行的明确调用探针位于 `C:/Test/native-workflow-diagnosis-20260924`。四案例隔离与执行交接计划位于 `C:/Test/native-workflow-session-20260924`。另已准备原 CSV 案例不改写的两会话验收计划 `C:/Test/native-workflow-canary-20260924`，是否实际执行及其结果以单独运行记录为准，准备完成不代表运行成功。

### 已授权的真实两臂验收

2026-09-24，用户明确授权 deepseek-flash、WITH/WITHOUT 各 1 次、原生估算阈值 US$0.30（允许在途超出），保留日志、不发布。先前 Windows 包装器在 Linux 隔离内启动失败，发生在模型请求前，记录保留。随后下载同版本 Linux 执行器并按官方发布的 SHA-512 校验，在任务独立的账户运行目录内完成两臂；没有重复已完成的模型会话。

实际运行位于 `C:/Test/native-workflow-canary-linux-20260924`，原用例和选定插件字节未改写。官方 `file_exists` 两臂均通过；独立 BH、p 值保留、效应值保留检查 **6/6 通过**。WITH 观察到指定插件加载，WITHOUT 未加载，**两臂 Skill 调用均为 0**；不据此宣称增益或已定位触发缺陷。明确调用探针尚未实跑。

原生报告估算 **US$0.116281**；提供方实际结算未知，历史未知结算也没有被冲销。新付费目录调用为 0。主进程正常退出，两会话结束；实际科学输入为公开的三基因合成算术控制，不是新生物学实验。

本机 Windows 挂载目录收到官方的“保留目录无法可靠封存”警告。原采集因此保留缺失，补齐已观察的目录迁移兼容后，从同一原始会话离线形成 `recovered/collected`，原采集包完整保留。迁移到 `C:/Test/native-workflow-replay-20260924` 后复算为 `REPRODUCED`。这验证了离线兼容修复与证据重算，不证明目录封存安全或独立执行真实性。

最终回归与机器验收见 [native-workflow-20260924.json](../evidence/native-workflow-20260924.json)。交付包仅包含明确选定的源码和公开材料；凭据、临时账户目录和下载的执行器不包含在内。

自动测试的调用、故障和对照事件均为明确制造的工程数据。尚未建立独立外部作者采用、独立专家审阅、跨宿主泛化或真实人工时间收益。此前未知费用结算继续保留，不用本轮离线工作将其冲销。

### 2026-09-25 明确调用探针实跑

用户授权发送选定技能、三基因构造输入和运行内容到 api.deepseek.com，WITH/WITHOUT 各一次。两会话完成，原生估算 US$0.16332，超过 US$0.12 启动阈值但属于已明确允许的在途超出；提供方结算仍未知，没有重试。材料在 `C:/Test/trigger-diagnostic-20260925`。

真实 Skill 返回省略了可选 `is_error` 字段，暴露 PVL 将正常返回误记为 UNKNOWN 的解析缺陷。按 [Anthropic 工具返回协议](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)修正后，使用同一原始记录离线重算；缺失结果、顺序错误、重复返回和非法标志仍保持 UNKNOWN。原比较报告保留，新报告位于 `comparison-parser-fixed/trigger-comparison.json`。

重算观察到明确调用条件中 1 次成功 Skill 返回；自然条件为 0 次，二者产物均通过。结论仍为 `TRIGGER_EXPLANATION_NOT_ESTABLISHED`、`comparison_eligible=false`。这闭合了 PVL 自身解析器的真实记录修复与重放，没有闭合插件错误产出、修复、自然使用成功的价值链。
