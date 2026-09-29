# Plugin Value Lab

**在 ChatGPT 中调用 Plugin Value Lab，评估其他插件是否真正帮助你完成任务。** 你说明要评估哪个插件、想完成什么，以及怎样的结果才有用；ChatGPT 组织评测，PVL 检查方案、分析记录并给出有证据边界的使用建议。

**版本 0.8.0。** 以下主流程面向已经安装且可在当前会话调用 PVL 的用户。直接在对话中开始，无需先提供源码目录、填写 JSON 或打开终端。

[English](README.md) · [当前证据](docs/EVIDENCE.md) · [详细评测操作](docs/OPERATIONS.md)

## 第一次使用：直接这样说

将方括号替换为你的插件和任务：

> 请使用 Plugin Value Lab 评估「[插件名称]」在「[具体任务]」上是否有帮助。先确认当前会话能调用哪些相关工具，再根据我的任务设计评测。已有结果先检查；没有结果就准备一个小规模试跑。能取得可靠的无插件对照时再比较增益，不能时明确说明还缺什么。请直接整理配置和记录，最后告诉我：哪里有帮助、哪里失败、证据在哪里、下一步怎么验证。

例如：

> 请用 Plugin Value Lab 评估我已连接的文献检索插件：它能否为我的研究问题找到可核查的原始研究，并准确说明每篇论文支持什么？先推荐评测题目和成功标准，再在已有授权范围内开展可行的检查。

**首次只需说清“插件名称 + 一个真实任务”。** ChatGPT 应先利用已有上下文，只补问影响判断的信息。你不必知道工具名称、评分器或文件结构。

## 根据手头材料，选一种开始方式

| 你想做什么 | 可以直接对 ChatGPT 说 |
| --- | --- |
| 从零评估一个插件 | “用 PVL 评估「插件名」处理「任务」的效果，先给我评测方案和小规模试跑安排。” |
| 检查刚才的一次结果 | “用 PVL 检查刚才这个插件的输出：哪些结果有依据、哪里不符合任务要求、哪些还无法判断？” |
| 比较插件与不使用插件 | “用 PVL 比较同一任务的两组结果，检查输入、模型和条件是否可比，再分析差值。” |
| 判断修复是否有效 | “这是修复前后的结果和记录，请用 PVL 保留原失败，检查修复是否解决问题、是否引入退步。” |
| 先了解工具是否可用 | “调用 PVL 的示例与校验工具，展示评测结果的结构。没有真实运行就明确标为演示。” |

检查一份输出可以得到局部诊断；证明插件带来额外收益，需要可比的有／无插件证据。这两种请求不应混为一谈。

## 你需要提供什么

- **目标**：插件名称和实际任务，例如“检索支持某个结论的原始论文”，而不是笼统地“给插件打分”。
- **有用的结果**：结果用来做什么判断，哪些错误不可接受。没有标准答案时直接说不知道。
- **可用材料**：已有输入、输出、引用和运行记录。可以使用当前对话或宿主能读取的附件；只在确实需要本地文件时再提供路径。
- **约束**：哪些材料可用于调用其他服务，是否允许新增付费试跑，以及已有费用或时间限制。已有授权应继续沿用。

如果另一个插件尚未连接，ChatGPT 应指出具体缺口，并先完成不依赖连接的准备；无需让你重新安装已可用的 PVL。

## 一次评测应该怎样推进

| 阶段 | ChatGPT 与 PVL 做什么 | 你应看到什么 |
| --- | --- | --- |
| 确认任务与能力 | 核对目标插件和当前可调用工具，理解已有材料 | 要评什么、当前能做什么、缺什么 |
| 设计并检查方案 | 提出贴近任务的正例、反例和缺证据情境；调用 PVL 检查规则 | 可读的题目、成功标准、对照方式和试跑范围 |
| 获取真实结果 | ChatGPT 使用宿主实际支持且已授权的工具执行或整理已有运行 | 实际调用、原始输出、失败记录及可取得的成本／耗时 |
| 分析与建议 | PVL 对已有结构化记录计算比较、检查缺失并生成使用建议 | 两臂表现、具体失败、未知项和适用范围 |
| 修复后复测 | 保留旧结果，在可比条件下重新观察 | 修复了什么、仍缺什么、是否出现退步 |

**ChatGPT 负责理解任务和协调可用工具；PVL 的默认评估工具处理传入的方案与记录。** PVL 不会仅凭插件名称自动启动另一个插件、创建隔离会话或获取全部历史日志。实际执行能力取决于当前宿主与目标插件；缺少执行或采集能力时，先交付方案或已有证据的诊断。

同一聊天里先说“不要用插件”、再说“使用插件”，不能自动构成独立、无污染的两臂实验。可靠比较需要相同任务与授权输入、可比模型／预算、独立运行记录和可核对的插件加载状态。宿主无法提供这些条件时，应保留“尚不能证明增益”。

## 最后应该拿到什么

你可以要求 ChatGPT 直接在会话中交付：

> 请用一张表总结每项任务：有插件结果、无插件结果、差异、失败或缺失、证据位置、使用建议。把已经观察到的事实与尚待验证的判断分开；没有基线或费用时保留未知，不填零。

优先读以下内容：

| 结果 | 如何理解 |
| --- | --- |
| 两臂都很好，Δ = 0 | 当前任务上未显示额外质量增益 |
| 观察到失败或退步 | 查看具体输出与记录；宿主故障不自动等于插件缺陷 |
| 证据不足 | 缺少基线、条件、成本、身份或审阅等必要材料；不等于插件无用 |
| 仅为模拟／演示 | 工具和报告结构可演示，尚无真实插件表现证据 |
| 限域试用建议 | 只适用于报告中的任务、插件、模型与条件，不代表普遍有效 |

默认 MCP 工具返回结构化结果，ChatGPT 可将其整理成表格和说明；文件保存或可下载报告需要宿主具备相应能力，不能承诺每次都自动生成本地文件。

## 常见问题

**已经安装 PVL，为什么 ChatGPT 还说不能调用？**

安装状态与当前会话暴露的工具需要分别确认。请让 ChatGPT 检查当前实际可用工具；若未暴露，使用宿主提供的启用或连接流程。仅凭一段自称“PVL 分析”的回答不能证明工具已调用。

**只有插件输出，没有完整日志，还能评估吗？**

可以先检查输出与任务标准是否相符，并列出需要补的证据。不能据此补造调用记录或宣称已完成严格收益比较。

**是不是所有评测都要新增付费调用？**

已有材料分析和本地计算不需要为了评测再启动模型试跑。当前 ChatGPT 会话、目标插件或另开的模型运行仍可能有各自用量和费用；新调用遵守已有授权，未知费用不当作零。

**官方 Claude eval 已有基线，PVL 增加什么？**

官方已输出 WITH、W/OUT 和 Δ，退出通过线使用 WITH 绝对分。PVL 的科学门禁另看匹配条件下的任务成功差与证据完整性。[比较说明](docs/history/RESEARCH-EXECUTION.zh-CN.md)。

当前四道研究题仍缺真实模型／评判运行，Windows 在线隔离仍待实核验收；已暴露的工具、本地回归或清单校验不证明这些经验门槛已完成。详见[当前证据](docs/EVIDENCE.md)。

## 开发者补充：本地复现与文件报告

已安装插件的普通用户无需执行本节。它供维护者、需要本地归档的人和排查问题的开发者复现评测计算。

需要 Python 3.11+，在解压后的项目根目录运行。下面五条命令使用**合成记录**，不调用模型或目标插件；重复时统一更换 `work/first-run` 为新目录。

```sh
python scripts/value_lab.py doctor
python scripts/value_lab.py freeze examples/first-run/suite.json --lock work/first-run/protocol.lock.json
python scripts/value_lab.py evaluate examples/first-run/suite.json examples/first-run/runs.jsonl --lock work/first-run/protocol.lock.json --cost-ledger examples/first-run/cost-ledger.json --output work/first-run/report
python scripts/value_lab.py usage-card examples/first-run/suite.json examples/first-run/runs.jsonl --lock work/first-run/protocol.lock.json --cost-ledger examples/first-run/cost-ledger.json --output work/first-run/usage
python scripts/value_lab.py compare-studies examples/first-run/before.json examples/first-run/after.json --output work/first-run/comparison.json
```

先看 `work/first-run/usage/USAGE.md` 或 `ENVELOPE.html`；完整评分在 `work/first-run/report/report.html`、`report.md` 和 `report.json`。比较结果在 `work/first-run/comparison.json`。正常演示结论为 `SIMULATION_ONLY`。`freeze` 不采集会话，`evaluate` 只评分已有记录；自己的研究必须先取得真实观察。

- [本地教程与计时](docs/START.md) · [真实评测操作](docs/OPERATIONS.md) · [对话式方案创建](docs/history/RESEARCH-AUTHORING.zh-CN.md)
- [CLI / Python SDK](docs/history/ENGINEERING-USABILITY.zh-CN.md) · [工作流示例](examples/workflow-integration/README.md)
- [在线隔离](docs/history/ONLINE-ISOLATION.zh-CN.md) · [环境锁与回放](docs/history/ENVIRONMENT-RECORDING.zh-CN.md)
- [科学蜕变检查](docs/history/METAMORPHIC-GRADERS.zh-CN.md) · [组件比较](docs/history/COMPONENT-METHODOLOGY.zh-CN.md) · [接口范围冻结](docs/FREEZE.md)
