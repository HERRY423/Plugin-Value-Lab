# 团队使用记录

> 实验性扩展：团队决定和采用记录不能替代科研插件边际价值的实测证据。

`usage-card` 是一次评测的条件性参考；`team-card` 将连续评测、研究背景和团队选择组成可复查的修订史。每轮都从方案和原始运行记录重新计算使用卡，不接受预先写好的“获益结论”。历史保留在新目录，旧版不会被覆盖。

在本地工作台也可打开“团队使用记录”，选择已有评估、填写实际团队决定，并可载入从研究方向诊断下载的上下文 JSON。保存后，工作台在自己的数据目录下创建新修订，显示当前卡片状态，并可下载完整记录。再次保存时选定要接续的记录；程序会保留旧版并标记需要重评的变化。模拟评估只会产生演示级使用卡。

## 第一轮

准备 `decision.json`，由实际团队成员填写，例如：

```json
{"actor":"项目负责人（提交者声明）","choice":"undecided","rationale":"尚待核对真实任务和成本。"}
```

`choice` 可为 `undecided`、`trial`、`keep`、`pause`、`retire`。姓名及授权均是提交者声明；程序不会从高分推断采用。若已形成研究方向上下文，可一起绑定：

```powershell
python scripts/value_lab.py team-card .\study\suite.json .\study\runs.jsonl --lock .\study\protocol.lock.json --decision .\decision.json --research .\research-context.json --output .\team\revision-1
```

研究上下文可省略；若评测有追加成本账本，使用 `--cost-ledger`。生成 `record.json`（完整历史）和 `TEAM.md`（当前状态与修订摘要）。模拟证据仍只能生成演示级使用卡。

## 后续修订

保留上轮目录。新证据、新方案或团队选择产生后，运行：

```powershell
python scripts/value_lab.py team-card .\new-study\suite.json .\new-study\runs.jsonl --lock .\new-study\protocol.lock.json --decision .\new-decision.json --research .\revised-context.json --previous .\team\revision-1\record.json --output .\team\revision-2
```

新记录会保留旧使用卡和决定，标出条件、任务、研究上下文和运行证据的变化。研究上下文变化时附带结构性方向比较，旧建议标为需要重评；它不声称研究有进展或缺口已关闭。后续省略 `--research` 时沿用上轮上下文，避免无意中切断研究范围。需要改变研究任务时应显式提供新的上下文并审阅可比性。

每个版本只覆盖其自身任务和条件；当前修订是最新提交记录，不会自动废除团队已经执行的现实决定。文件摘要只帮助发现本地记录被意外改动，不能证明评审者身份、来源真实性、模型执行、结算费用或持续收益。记录中可能有原始任务和研究背景，分享前请审阅敏感内容。
