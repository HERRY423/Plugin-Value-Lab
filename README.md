# Plugin Value Lab — 一页决策树

判断插件是否改善**具体任务**：同任务配对、先冻结规则、从原始记录复算。**Version 1.0.0-rc.5.** 计算结果只适用于报告中的任务、模型和条件。

```text
你现在有什么？
├─ 只有插件名或想法 → 写清任务、成功标准和基线，先制定方案。
│  └─ 打算采集新结果 → 先确定效应阈值、方差来源、独立任务族数和费用边界，再冻结。
├─ 已有真实配对记录 → 检查完整性、条件可比性、失败和成本，再复算。
│  ├─ 缺失/混杂/未完成 → 证据不足；保留 UNKNOWN。
│  ├─ 回退或关键失败 → 保留负向结果，先调查原因。
│  ├─ 正向差异但任务族低于计划 → 最高“仅试用线索”，不可升格为增益支持。
│  └─ 达到计划与全部门槛 → 限定条件的本地信号；达到功效目标本身不证明有效。
└─ 只有合成示例 → SIMULATION_ONLY；用于学习流程，不代表真实收益。
```

**功效与默认值。** 未填写 `min_clusters` 时，有冻结 `power_plan` 就按其所需族数与描述性下限 3 的较大值判断；没有功效计划时，3 仅是描述性下限。显式较低的 `min_clusters` 不能绕过功效计划；无法求得所需族数或设计不满足规划条件，也不能升级正向结论。重复次数不是独立任务族。v3 确认性规则继续有独立门槛。

**工具证据公共池。** 文献检索已有 [30 个候选位点](examples/literature-pool/candidates.json)，含快照、答案草稿、合法变体与禁区；目前均为合成占位，专家与第三方托管待接入。真实评估保留集须达到 `max(30, 功效计划所需族数)`，同族变体不增加族数。接口与网关验收边界见 [实现状态记录](docs/history/20261012-POOL-GATEWAY.md)。

**降低取证成本（设计稿）。** [L0–L3 阶梯与统计设计](docs/history/20261012-EVIDENCE-LADDER-DESIGN.md)：静态适配 → 自有任务筛选 → 公共族先导 → 冻结确认；定义序贯停止、分层先验与人工校正评分。状态为 `DESIGN_FOR_REVIEW / NOT_IMPLEMENTED`，当前 v3 仍为固定样本，不提供序贯保证。

**把证据变成行动。** [决策层实现](docs/history/20261012-ACTION-DECISION.md) 接收研究者填写的误采用、漏用和时间损失，输出“采用(限域) / 带护栏试用 / 默认基线 / 不使用”，附范围、有效期和下一条补证据动作；支持多候选轮转、收缩展示与同时名次区间。收缩不会绕过独立确认，示例损失不代表真实偏好。

**在对话中开始：**“评估 [插件] 对 [具体任务] 是否有增益。先检查可用工具、基线和已有记录，提出配对方案并冻结条件；收集新记录遵守费用和数据授权，再报告差异、不确定性及失败。”

**安装选择。** 本地标准库重算需 Python 3.11+；宿主使用先安装插件和所需 MCP 依赖。安装参考见 [history 状态索引](docs/history/INDEX.md)。宿主负责组织执行；一个插件名不会自动启动独立两臂或找回历史日志。

**只想本地复现？** 以下五步处理随包合成记录，无模型调用。再次执行请把 `work/first-run` 全部换成新目录。

```sh
python scripts/value_lab.py doctor
python scripts/value_lab.py freeze examples/first-run/suite.json --lock work/first-run/protocol.lock.json
python scripts/value_lab.py evaluate examples/first-run/suite.json examples/first-run/runs.jsonl --lock work/first-run/protocol.lock.json --cost-ledger examples/first-run/cost-ledger.json --output work/first-run/report
python scripts/value_lab.py usage-card examples/first-run/suite.json examples/first-run/runs.jsonl --lock work/first-run/protocol.lock.json --cost-ledger examples/first-run/cost-ledger.json --output work/first-run/usage
python scripts/value_lab.py compare-studies examples/first-run/before.json examples/first-run/after.json --output work/first-run/comparison.json
```

阅读 `work/first-run/usage/USAGE.md` 与 `ENVELOPE.html`；完整字段在 `card.json`。预期 `SIMULATION_ONLY`。给已观察数据加锁仅检查一致性，不是事前注册。

**改了代码？** 快速层覆盖核心裁决、卡片、功效与本轮回归，超过 120 秒即失败；完整层发现全部测试。缺可选依赖的测试通过 `skipUnless` 显式跳过，`requires` 标注所需模块；跳过不代表通过该功能验收。

```sh
python scripts/run_tests.py fast
python scripts/run_tests.py full
python scripts/run_tests.py full --require-all
```

发布验收使用最后一条，拒绝任何 skip。可选依赖在 `pyproject.toml`：`dev`、`mcp`、`planning`、`registry`、`science`、`pseudobulk`；仅按任务需要安装。原生隔离、真实后端和工作流验收仍由 CI 独立任务执行。

**凭据与日志。** Git 使用 Git Credential Manager（`credential.helper=manager`）。API 凭据使用提供方登录或操作系统凭据管理器，不放进仓库、命令行、示例卡或日志；本次未迁移或吊销 API 令牌。`.claude/logs/` 已加入忽略规则，日志应留在仓库外；忽略规则不会清除旧提交。历史泄露必须在提供方后台吊销后重新生成，不能靠删除日志替代。

维护与安全规则、方法、旧版指南及历史验收统一见 [history 状态索引](docs/history/INDEX.md)；归档不撤销维护承诺或安全规则。漏洞请走 [私密报告渠道](https://github.com/HERRY423/Plugin-Value-Lab/security/advisories/new)。费用边界：父进程网关已接入发送前累计预留与超额拒绝；当前模型的保守包络仍超出单次 $0.10，实际付费保持阻断。网关限制不等于提供方账户侧上限。
