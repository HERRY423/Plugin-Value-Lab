# Plugin Value Lab

帮助插件作者从配对运行中定位问题，修复后进行公平复测。

Compare plugin runs, locate failures and retest repairs under matched conditions.

[English](README.md) · [安装](docs/INSTALL.zh-CN.md) · [本次修复状态](docs/REMEDIATION.md)

当前版本 **0.5.0**。新增[独立样本科研推断重算](docs/REPLICATE-VERIFICATION.zh-CN.md)：检查供体单位、批次与配对，重算效应、精确检验和完整多重校正。配对评分提供测量能力，长期积累的是领域任务、实测账本和外部贡献。目前没有认证独立复核，也未建立外部采用。

## 先交付一份可用的作者改进清单

已有记录可直接生成逐任务、逐组、逐次运行的失败与未知清单，并保留完整任务、阈值和负面对照来准备复测。工作台同步展示清单，提供复制原方案、比较两轮研究的入口。**无需加入登记处、公开排名或申请认证。**

作者价值仍是假设：是否减少准备和人工修正负担，需要真实对照计时与反馈。下一阶段只推进一个自愿外部作者的窄任务修复循环；证据未建立前，不继续扩张研究规划、团队协作或平台功能。见[三个结构性风险的处理与验收边界](docs/STRUCTURAL-RISKS.zh-CN.md)。

## 登记处是可选本地账本

保留原始研究、负面与失败、补证修订、异议和可重算研究包。现在页面及 JSON 明确显示“空白 / 仅合成 / 本地试点 / 自报外部提交待核验”阶段，始终标为**暂定交换格式**，不自动升级成可信证据层。补证修订不增加独立样本；哈希、签名和自报身份不证明采用。

[登记流程](docs/REGISTRY.zh-CN.md)可在确有保存或交接需求时使用。本地诊断不依赖外部网络已经建成。

## 先跑通本地流程

新增[科研验证器与场景包](docs/SCIENTIFIC-VALIDATION.md)：结构、数值、弃答双向错误、后端身份和容器执行检查均接入离线评分；[CellTypePilot 首个真实研究协议](docs/CELLTYPEPILOT-PILOT.md)仍待数据与宿主采集条件就绪。

研究建议与团队记录默认关闭；CLI、MCP、工作台均需显式添加 `--enable-extensions` 启动。研究技能移至 `extensions/`，退出默认发现；默认保留 6 个 MCP 工具和 2 个技能，兼容源码与旧记录保留。

需要 Python 3.11+。在实际源码或解压后的插件目录运行，无需固定安装路径：

```sh
python scripts/value_lab.py doctor
python scripts/value_lab.py demo --output work/demo-1
python scripts/value_lab.py usage-card work/demo-1/suite.json work/demo-1/runs.jsonl --lock work/demo-1/protocol.lock.json --output work/author-card
```

打开 `work/author-card/USAGE.md` 查看改进清单，`work/demo-1/report.html` 查看原始评分。演示明确标记为模拟，不调用模型。

真实评估应先冻结方案，再收集两组独立会话的原始记录：

```sh
python scripts/value_lab.py freeze suite.json --lock protocol.lock.json
python scripts/value_lab.py evaluate suite.json runs.jsonl --lock protocol.lock.json --artifacts collected-files --output report
```

## 直接验证产物

新增评分规则可以读取实际文件：DE 表的基因标识、有限数值和 BH 校正，逐细胞标签与参照的一致性，h5ad 的结构与必要字段，以及 JSON 产物的类型和值。还可显式运行固定 SHA-256 的 Python 验证器。

文件缺失、摘要不符、依赖缺失和验证器超时不会被当作成功；有问题的结果仍保留在分母中。[产物验证说明与例子](docs/ARTIFACTS.md)。

## 两种执行入口

[跨宿主、科研验证与可回放证据的严谨性](docs/RIGOR.zh-CN.md)：统一原生采集核验、完整检验基因集合、预设双向错误上限，以及不执行评分器的重放预检与环境核对。它们已经接入评估和登记流程，真实跨宿主收益仍须实际研究建立。

- Claude：`python scripts/value_lab.py workbench` 启动本地工作台，准备后授权一次原生执行。
- Codex：`prepare-codex` 冻结，`run-codex` 执行；保存独立会话、原始事件、输出、安装记录和 token 用量。[执行说明](docs/CODEX.md)。

安装记录不自动等于插件实际加载；原生请求参数不自动等于观测条件。费用、人工复核或条件证据不完整时，不给出正向价值结论。

## 实际完成了什么

以 [VERIFICATION.json](VERIFICATION.json) 和 [修复记录](docs/REMEDIATION.md) 为准。本地测试使用构造数据；真实模型调用、真实研究与独立验证分别记录。审批未放行的执行不会算成已运行。

报告新增任务成功率提升、挽救失败与引入失败、普通任务与弃答分层、节省人工时间及每次成功的完整成本。样本量规划按独立任务族计算；成本类别齐全与结算引用分开核验。[正向价值指标与验证设计](docs/VALUE-METRICS.zh-CN.md)。

## 后续展望：Epistemic Plugin Arena

**Epistemic Plugin Arena 是后续研究与产品构想**，不作为已经存在的外部项目、当前依赖或已集成基准。未来若形成公开规范、实现与验证材料，可探索离线行动选择评估与真实宿主结果的互补。当前 `link-decision-evidence` 只是通用材料引用与摘要绑定工具，不能证明 Arena 集成，也不合并两层分数。[当前边界与未来条件](docs/EVIDENCE-LAYERS.md)。

## 深入使用

[完整评估协议](docs/PROTOCOL.zh-CN.md) · [数据契约与人工复核](CONTRACT.md) · [成本与版本比较](docs/ANALYSIS.zh-CN.md) · [研究规划](docs/RESEARCH.zh-CN.md) · [团队记录](docs/TEAM-RECORD.zh-CN.md)

跨平台 CI 和已有版本标签的手动草稿发布流程已经加入；本地添加工作流不代表远端 CI 已运行或 Release 已发布。
