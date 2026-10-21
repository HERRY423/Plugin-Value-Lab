# Plugin Value Lab v1.0.0-rc7

本次候选发布整理了首个外部实验室 L1 试用所需的现有路径。版本标识：Git tag / Release `v1.0.0-rc7`，插件 `1.0.0-rc7`，Python 包 `1.0.0rc7`。

## 本次变化

- `pvl screen` 接收插件清单与 3–5 个任务，冻结方案、导入配对记录并生成使用卡；结果为停止、证据不足或进入先导。缺失、失败、未知费用和安全早停均保留。
- 实验室在冻结方案中选择模型、逐模型费率和预算，使用自己的账户或明确配置的本地/内网端点。$0.10 为默认单次预算，可由实验室明确设定；不会改变任何外部账户或 AgentMuxer 的授权上限。
- 机构内数据治理说明明确原始数据、受试者数据与未发表材料的存储边界；只有经过人工批准的最小汇总和完成证明可导出。软件本身不是网络隔离或自动脱敏工具。
- 首个实验室试用包提供最短离线安装步骤、4 个任务模板、治理说明、完成验收清单，以及不调用模型的安装演练。真实 L1 使用机构内已有宿主执行并保留原始证据。
- 先前已实现的本地协作闭环纳入本次发布：保留记录复算、绑定结果审阅、版本纠正、双向交接和检查点恢复。MCP 写入入口需显式开启。

## 下载与选择

- 首次 L1 试用：`PVL-first-lab-L1-v1.0.0-rc7.zip`，解压后阅读 `README.md`，先运行 `check_package.py`。
- Codex/Claude 本地市场：`plugin-value-lab-marketplace-1.0.0-rc7.zip`，选择包含市场清单的解压根目录。
- 通用插件：`plugin-value-lab-agent-plugins-1.0.0-rc7.zip`。
- Python CLI/库：`plugin_value_lab-1.0.0rc7-py3-none-any.whl`；源码分发：`plugin_value_lab-1.0.0rc7.tar.gz`。
- `SHA256SUMS.txt` 用于核对附件；`release-verification.json` 记录本次实际工程检查与证据边界。

## 证据边界与下一步

本版是 prerelease。正式 v1.0 门槛为 **1 个非作者外部实验室完成完整 L1**，当前为 **0/1**。停止、证据不足和进入先导均可成为完整 L1 的有效结果；不完整尝试和作者合成演练不计入。工程测试、包校验与 CI 不证明实际收益、真实宿主验收或科学有效性。

功能继续冻结，仅处理既有路径的阻塞问题和试用支持。本次发布不包含向实验室发送邀请或上传其原始数据。

## English

This release candidate packages one-command L0/L1 screening, lab-owned model/rate/budget configuration, institutional data governance, and a first-lab L1 trial kit with four task templates and an offline installation rehearsal. It also includes the previously implemented opt-in local collaboration workflow.

Use the first-lab ZIP for the guided trial, the marketplace ZIP for plugin installation, or the wheel for the CLI/library. Verify assets with `SHA256SUMS.txt`; actual engineering checks are recorded in `release-verification.json`. **External L1 completion remains 0/1.** Engineering checks and synthetic rehearsals do not establish real-world benefit or native-host acceptance. Feature development remains frozen until a separate owner decision.
