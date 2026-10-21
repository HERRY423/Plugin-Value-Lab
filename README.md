<img src="assets/plugin-value-lab.png" alt="Plugin Value Lab 科研天平图标" width="88" height="88">

# Plugin Value Lab

**这个插件，真的改善了你的这项任务吗？**

中文 · [English](README.en.md)

Plugin Value Lab 用配对比较、冻结方案和可复算记录，帮助你判断插件是否值得在**具体任务**中使用。比较有插件与无插件的表现，同时保留失败、成本、不确定性和缺失证据。**Version 1.0.0-rc7.** 当前为候选发布版。

[下载 rc7](https://github.com/HERRY423/Plugin-Value-Lab/releases/tag/v1.0.0-rc7) · [五步体验](#五步体验无需模型调用) · [方法与实现记录](docs/history/INDEX.md)

## v1.0 正式版门槛与功能冻结

**停止新增产品功能。v1.0 正式版的使用验收门槛是：1 个外部实验室完成 L1。** 当前已核验记录为 **0/1，正式版门槛未满足**。模块数、测试数量和作者自己的合成演示不能替代它；必要的正确性、安全及现有发布检查继续保留。

外部实验室由非项目作者的研究者实际操作：在机构内批准的数据环境中，冻结软件版本、3–5 个真实任务、两臂条件、评分和预算，完成每臂两次的 12–20 次尝试，保留失败与未知，出具使用卡并由实验室负责人确认完成。**停止／证据不足／进入先导都可成为完整 L1 的结果，不要求正向收益。** 只有静态检查、未补齐的执行矩阵或提前安全停止不能计为完成；不得为凑数量继续不安全执行。作者可提供有记录的支持，但不能代跑后称为外部使用。

机构保留原始证据；项目只接收经批准的完成证明、最小汇总与使用卡。发布负责人核对外部身份、完成范围、支持过程与版本后记录接受，不由模型代填。完成一次 L1 只证明一次外部工作流完成，不证明普遍收益、机构合规或临床有效；达到门槛也不自动发布。

冻结期间只修复现有路径的正确性、安全、安装/恢复问题，澄清文档并支持这一轮试用；不新增模块、模型/宿主适配、分析方法、指标或界面。该里程碑完成后仍须用户明确决定是否解冻。数据处理和可导出范围见[一页数据治理说明](docs/DATA-GOVERNANCE.md)。

首个实验室的[试用步骤、4 个任务模板和完成清单](examples/first-lab-l1/README.md)已整理；离线安装包需连同 wheel 与哈希清单使用。本地合成演练不计为外部 L1，也未向任何实验室发送邀请或材料。

## 适合什么场景

| 你要做的决定 | Plugin Value Lab 帮你做什么 |
| --- | --- |
| 是否给一项任务引入插件 | 明确任务、基线、成功标准和配对条件，先冻结再评估 |
| 插件升级后是否更好 | 从已有记录重算差异，比较前后研究，保留回退与关键失败 |
| 多个候选插件如何选择 | 结合用户填写的误采用、漏用和时间损失，给出限域行动建议 |
| 如何向同事解释结果 | 输出使用卡、HTML 报告和机器可读记录，列出范围、有效期与下一步 |

宿主负责组织任务执行。仅提供插件名不会自动启动独立对照实验，也不会自动找回历史日志。结果只适用于记录中测试过的任务、模型和条件。

源码现增加[本地协作闭环](docs/history/20261020-COLLABORATION.md)：将保留记录的实际复算、绑定结果的审阅、版本纠正、双向交接与检查点恢复连接起来。MCP 写入入口需要宿主显式开启；默认六个分析工具不变。这项改进已纳入 rc7；真人协作、桌面宿主验收和实际收益仍需单独验证。

## 安装到 Codex

需要 Python **3.11+**，且 Codex 启动插件时能找到 `python`。MCP 服务需要额外依赖；在所用 Python 环境中，从仓库或解压后的插件根目录安装：

```sh
python -m pip install -r requirements-mcp.txt
```

在 Codex 的插件页面选择 **添加插件市场**，填写：

| 字段 | 内容 |
| --- | --- |
| 来源 | `HERRY423/Plugin-Value-Lab` |
| Git 引用 | `v1.0.0-rc7`（固定到 rc7）；需要后续源码更新时使用 `main` |
| 稀疏路径 | 留空 |

添加后，在市场中选择并安装 **Plugin Value Lab**。仓库已包含天平图标及对应清单配置。

也可以在 [Release](https://github.com/HERRY423/Plugin-Value-Lab/releases/tag/v1.0.0-rc7) 下载 `plugin-value-lab-marketplace-1.0.0-rc7.zip`，解压后通过本地文件夹添加市场，选择**包含 `.agents/plugins/marketplace.json` 的根目录**。保留完整目录结构。Python wheel 是单独的命令行/库分发，安装 wheel 不会自动向 Codex 注册插件。

安装后可以这样开始对话：

> 评估 [插件] 对 [具体任务] 是否有增益。先检查可用工具、基线和已有记录，提出配对方案并冻结条件；收集新记录遵守费用和数据授权，再报告差异、不确定性及失败。

## 五步体验：无需模型调用

下载并解压仓库源码，在根目录运行以下命令。示例只处理随包合成记录，核心重算使用 Python 标准库，无需安装 MCP 依赖。再次运行时，请将所有 `work/first-run` 换成一个新目录，避免覆盖已有记录。

```sh
python scripts/value_lab.py doctor
python scripts/value_lab.py freeze examples/first-run/suite.json --lock work/first-run/protocol.lock.json
python scripts/value_lab.py evaluate examples/first-run/suite.json examples/first-run/runs.jsonl --lock work/first-run/protocol.lock.json --cost-ledger examples/first-run/cost-ledger.json --output work/first-run/report
python scripts/value_lab.py usage-card examples/first-run/suite.json examples/first-run/runs.jsonl --lock work/first-run/protocol.lock.json --cost-ledger examples/first-run/cost-ledger.json --output work/first-run/usage
python scripts/value_lab.py compare-studies examples/first-run/before.json examples/first-run/after.json --output work/first-run/comparison.json
```

打开 `work/first-run/usage/USAGE.md` 或同目录下的 `ENVELOPE.html`；完整字段在 `card.json`，研究比较在 `work/first-run/comparison.json`。预期结果为 **`SIMULATION_ONLY`**：它演示流程，不证明插件有真实收益。对已经观察过的数据加锁，仅用于一致性检查，不构成事前注册。

## 如何解读结果

```text
你现在有什么？
├─ 只有插件名或想法 → 明确任务、成功标准和基线，先制定方案。
│  └─ 采集新结果前 → 确定效应阈值、方差来源、独立任务族数和费用，再冻结。
├─ 已有真实配对记录 → 检查完整性、条件可比性、失败和成本，再复算。
│  ├─ 缺失、混杂或未完成 → 证据不足；保留 UNKNOWN。
│  ├─ 回退或关键失败 → 保留负向结果，调查原因。
│  ├─ 正向差异但任务族不足 → 最高“仅试用线索”。
│  └─ 达到计划与全部门槛 → 限定条件的本地信号。
└─ 只有合成示例 → SIMULATION_ONLY；不代表真实收益。
```

**独立任务族不能用重复次数替代。** 未填写 `min_clusters` 时，描述性下限为 3；有冻结的 `power_plan` 时，按该下限与计划所需族数的较大值判断。显式降低 `min_clusters` 也不能绕过功效计划。所需族数未知或规划条件不满足时，不能升级正向结论；达到功效目标本身也不证明有效。v3 确认性规则另有独立门槛。

## 进阶能力与状态

| 能力 | 当前状态与边界 |
| --- | --- |
| [行动决策层](docs/history/20261012-ACTION-DECISION.md) | 已实现限域采用、带护栏试用、默认基线、不使用四类建议，以及多候选轮转、收缩展示和同时名次区间。收缩不能替代独立确认，示例损失不代表用户偏好。 |
| [工具证据公共池与网关](docs/history/20261012-POOL-GATEWAY.md) | [30 个候选位点](examples/literature-pool/candidates.json) 均为合成占位，专家审核与第三方托管待接入。真实保留集要求至少 `max(30, 功效计划所需族数)` 个独立族；同族变体不增加族数。 |
| [L0/L1 一键筛查与实验室模型配置](docs/history/20261020-SCREENING-LAB-MODELS.md) | `pvl screen` 输入插件清单与 3–5 个任务，输出停止／证据不足／进入先导及使用卡；支持实验室适配器执行或导入冻结配对记录。L2/L3 新序贯设计仍未实现，当前 v3 保持固定样本规则。 |

## 数据、费用与安全

- 本地示例无需模型调用。真实运行需另行明确数据授权、提供方和预算；不要将敏感数据放进公共示例或报告。
- 父进程网关在发送前预留累计费用。`pvl freeze-models` 允许实验室冻结自定额度、多个模型各自的费率，以及自有 API／本地／内网端点；单次 $0.10、本任务 $1 是默认值。旧内置费率仍因过期及包络超额而阻断。未知费用、过期或未定价功能仍拒绝；网关限制不等于提供方账户侧限额。
- 凭据使用提供方登录或系统凭据管理器，不放入仓库、命令行、卡片或日志。忽略文件不能清除历史提交中的秘密；泄露后需在提供方撤销并更换凭据。
- 漏洞请使用 [私密报告渠道](https://github.com/HERRY423/Plugin-Value-Lab/security/advisories/new)，并参阅 [安全规则](docs/history/20261011/SECURITY.md) 与 [数据治理](docs/history/20261011/docs/DATA-GOVERNANCE.md)。

## 开发与验证

```sh
python scripts/run_tests.py fast
python scripts/run_tests.py full
python scripts/run_tests.py full --require-all
```

快速层覆盖核心裁决、卡片、功效和选定回归，超过 120 秒即失败；完整层发现全部测试。缺少可选依赖会显式跳过相关测试，**跳过不等于验收通过**。发布使用 `full --require-all`，拒绝任何 skip。

可选依赖见 [pyproject.toml](pyproject.toml)：`dev`、`mcp`、`planning`、`registry`、`science`、`pseudobulk`，按任务需要安装。原生隔离、真实后端和工作流有各自的 CI 检查；工程测试通过不代表插件真实增益或科学有效性已经得到验证。

[贡献指南](docs/history/20261011/CONTRIBUTING.md) · [API 稳定性](docs/history/20261011/docs/API-STABILITY.md) · [rc7 发布说明](docs/history/RELEASE-v1.0.0-rc7.md) · [历史文档索引](docs/history/INDEX.md)

文档归档不撤销维护与安全规则。项目使用 [Apache-2.0 许可证](LICENSE)；引用元数据见 [CITATION.cff](CITATION.cff)。
