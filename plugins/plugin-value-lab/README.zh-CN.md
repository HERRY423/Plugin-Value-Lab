# Plugin Value Lab

在匹配条件下，测量并登记科研 Agent 插件的边际价值。

Measure and register the marginal value of scientific agent plugins under matched conditions.

[English](README.md) · [安装](docs/INSTALL.zh-CN.md) · [本次修复状态](docs/REMEDIATION.md)

版本保持 **0.4.0-alpha.1**。配对评分提供测量能力，长期积累的是领域任务、实测账本和外部贡献。目前没有认证独立复核，也未建立外部采用。

## 开始积累四类资产

[阶段二已增加](docs/PHASE2.md)：跨宿主方案矩阵、Codex 采集凭据核验、可比条件下的 Δ 差异与纵向下降提醒、非作者签名复核门槛，以及只读签名网页快照。外部候选和未发送的邀请草稿见[试点接入](docs/EXTERNAL-PILOT-INTAKE.md)。这不代表已经完成真实跨宿主研究或公开部署。

- **场景语料**：8 个可执行合成案例、4 个任务族，开发/留出按任务族分隔，答案独立保管；公开种子不是保密 benchmark。
- **价值账本**：按插件、版本与内容摘要、模型、宿主和时间保留研究快照，同时报告“放行不足证据”和“误拒合理分析”。
- **交换协议**：研究包可导出、核验并离线重算；供其他插件作者采用，尚不称为行业标准。
- **复核记录**：真实评审绑定具体快照，保留利益冲突、异议与复现实验链接，自报身份不升级为独立认证。

使用 `corpus-seed`、`registry-add`、`registry-view`、`registry-review` 等本地入口。完整命令、模板和证据边界见[登记表与选用协议](docs/REGISTRY.zh-CN.md)。这些入口不启动模型、不发布结果。

补证可用 `registry-add --parent ... --revision-reason ...` 保存新修订，旧版和异议继续保留；修订数量不充当新增实测。交接时用 `registry-export --with-reviews` 携带复核快照，再用 `registry-verify --expected-id ...` 核对单独保存的摘要。

## 先跑通本地流程

新增[科研验证器与场景包](docs/SCIENTIFIC-VALIDATION.md)：结构、数值、弃答双向错误、后端身份和容器执行检查均接入离线评分；[CellTypePilot 首个真实研究协议](docs/CELLTYPEPILOT-PILOT.md)仍待数据与宿主采集条件就绪。

`research-directions` 与 `team-card` 保留为实验性扩展，不属于核心科研价值测量能力。

需要 Python 3.11+。在实际源码或解压后的插件目录运行，无需固定安装路径：

```sh
python scripts/value_lab.py doctor
python scripts/value_lab.py demo --output work/demo-1
```

打开生成的 `work/demo-1/report.html`。演示明确标记为模拟，不调用模型。

真实评估应先冻结方案，再收集两组独立会话的原始记录：

```sh
python scripts/value_lab.py freeze suite.json --lock protocol.lock.json
python scripts/value_lab.py evaluate suite.json runs.jsonl --lock protocol.lock.json --artifacts collected-files --output report
```

## 直接验证产物

新增评分规则可以读取实际文件：DE 表的基因标识、有限数值和 BH 校正，逐细胞标签与参照的一致性，h5ad 的结构与必要字段，以及 JSON 产物的类型和值。还可显式运行固定 SHA-256 的 Python 验证器。

文件缺失、摘要不符、依赖缺失和验证器超时不会被当作成功；有问题的结果仍保留在分母中。[产物验证说明与例子](docs/ARTIFACTS.md)。

## 两种执行入口

- Claude：`python scripts/value_lab.py workbench` 启动本地工作台，准备后授权一次原生执行。
- Codex：`prepare-codex` 冻结，`run-codex` 执行；保存独立会话、原始事件、输出、安装记录和 token 用量。[执行说明](docs/CODEX.md)。

安装记录不自动等于插件实际加载；原生请求参数不自动等于观测条件。费用、人工复核或条件证据不完整时，不给出正向价值结论。

## 实际完成了什么

以 [VERIFICATION.json](VERIFICATION.json) 和 [修复记录](docs/REMEDIATION.md) 为准。本地测试使用构造数据；真实模型调用、真实研究与独立验证分别记录。审批未放行的执行不会算成已运行。

Arena 等离线决策评测属于决策层，Value Lab 属于宿主运行层。新增 `link-decision-evidence` 可保留两层材料的引用与摘要，不合并分数，也不要求安装另一个仓库。[职责边界](docs/EVIDENCE-LAYERS.md)。

## 深入使用

[完整评估协议](docs/PROTOCOL.zh-CN.md) · [数据契约与人工复核](CONTRACT.md) · [成本与版本比较](docs/ANALYSIS.zh-CN.md) · [研究规划](docs/RESEARCH.zh-CN.md) · [团队记录](docs/TEAM-RECORD.zh-CN.md)

跨平台 CI 和已有版本标签的手动草稿发布流程已经加入；本地添加工作流不代表远端 CI 已运行或 Release 已发布。
