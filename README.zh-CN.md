# Plugin Value Lab

**配对、冻结、可复算地判断插件对一项具体任务有没有增益。**

把同一项任务的有插件与无插件结果配对，在收集结果前固定评测规则，再从原始记录重新计算差异。证据不足时，明确保留未知。

**版本 0.9.0。** 安装且可调用后，直接在对话中提供插件名称和一项具体任务；由宿主处理方案与记录。

[English](README.md) · [入门](docs/START.md) · [高级指南](docs/history/ADVANCED.md) · [当前证据](docs/EVIDENCE.md)

## 从一个问题开始

> 请使用 Plugin Value Lab，判断「[插件名称]」对「[具体任务]」有没有增益。先检查可用工具，提出有插件／无插件的配对方案，在收集结果前冻结输入、成功标准和运行条件。然后从原始记录重算差异，说明不确定性、失败和缺失证据。已有记录合适就先使用；新增运行遵守已有授权。

例如：对于同一个研究问题，文献检索插件能否找到更多可核验的原始研究，并减少没有依据的结论？

## 一次评估，三个步骤

| 步骤 | 具体做什么 |
| --- | --- |
| **配对** | 对相同任务与授权输入，比较有插件和无插件的独立运行记录，保持模型、预算等条件可比。 |
| **冻结** | 在观察结果前固定案例、成功标准、运行条件和抽样方案；围绕有意义的效应量规划任务数与重复次数。 |
| **可复算** | 按冻结规则重新评分原始记录，报告差异、失败、成本，以及设计允许时的置信区间。 |

宿主组织执行，PVL 检查方案并分析提供的记录。一个插件名称不会自动启动隔离会话或取回全部历史日志。同一聊天里先说“用插件”、再说“不用插件”，不等于独立两臂实验。对已观察的数据补做冻结属于回顾性核查，不是预注册。

## 最后得到什么

一份逐任务比较：**有插件 → 无插件 → 差异 → 不确定性 → 证据位置**。结论只适用于已测试的任务、插件、模型与条件。

| 结果 | 如何理解 |
| --- | --- |
| 观察到正向差异 | 在所报告条件下观察到增益，仍需结合不确定性和证据范围判断。 |
| 没有差异或出现退步 | 未观察到额外增益，或表现变差；保留原始失败记录。 |
| 证据缺失或条件不可比 | 尚不能证明增益；没有基线或费用时保留未知，不填零。 |
| 合成示例 | 只演示计算与报告，不代表真实插件收益。 |

文件交付与独立执行取决于宿主能力。已有记录可以本地分析；付费原生 eval 启动仍受费用硬边界阻断，详见[操作说明](docs/OPERATIONS.md)。

## 安装

插件安装不包含 Python 本地包。运行 Plugin Value Lab 本地分析、`doctor` 环境检查或本地 stdio MCP 服务需要 Python 3.11+。

### 1. ChatGPT / Codex 仓库插件市场

添加仓库插件市场：

```bash
codex plugin marketplace add HERRY423/Plugin-Value-Lab --ref main
```

重启 ChatGPT 桌面客户端，打开插件目录（Plugins Directory），选择 **Plugin Value Lab Marketplace** 并安装 **Plugin Value Lab**。仓库市场适用于开发、团队分发与测试，独立于通用的公共插件目录。

当公开市场上架审核通过后，可直接在通用 Plugins Directory 中搜索 **Plugin Value Lab** 安装；支持的 ChatGPT 与 Codex 端共享同一公共条目。

### 2. Claude Code 插件市场

```bash
claude plugin marketplace add HERRY423/Plugin-Value-Lab
claude plugin install plugin-value-lab@plugin-value-lab-marketplace
```

安装完成后开启新会话：

```bash
claude
```

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

- [本地教程](docs/START.md) · [研究方法](docs/METHODOLOGY.md) · [高级指南](docs/history/ADVANCED.md)
- [当前证据](docs/EVIDENCE.md) · [操作与排障](docs/OPERATIONS.md) · [接口范围冻结](docs/FREEZE.md)

源码检查通过不代表已安装宿主验收或已证明科学收益。

项目规范：[引用](CITATION.cff) · [最低维护承诺与维护人](CONTRIBUTING.md#minimum-maintenance-commitment) · [安全报告](SECURITY.md) · [贡献指南](CONTRIBUTING.md) · [兼容范围](docs/API-STABILITY.md#maintained-environments) · [数据治理](docs/DATA-GOVERNANCE.md)。可识别患者数据不得进入普通记录或提示词；去标识化衍生材料仍需数据负责人批准。

首要维护人：**@HERRY423**，目前无备份维护人。私密漏洞请使用 **[GitHub 私密报告入口](https://github.com/HERRY423/Plugin-Value-Lab/security/advisories/new)**（需登录；2026-10-03 已启用并核验入口）。P0/P1 分别在 1/2 个工作日内确认，确认后 2/5 个工作日内给出缓解或停用建议；补丁日期按问题评估，不等于全天候保障。工作日按洛杉矶时间周一至周五计算。完整分级、更新频率与逾期处理见[严重问题流程](SECURITY.md#serious-issue-response)，不要在公开 issue 提交漏洞细节。

[v0.9.0 维护承诺与付费边界补充说明](docs/history/MAINTENANCE-AND-PAID-BOUNDARY-20261003.md)：付费原生执行仍被阻断；后续源码的记账模块仍为 `provider_cap_verified: false`、`paid_launch_authorized: false`。已发布版本的原始安装包与后续源码范围在说明中分别列明。
