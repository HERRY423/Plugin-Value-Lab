> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# 已安装插件功能实测：0.5.0

日期：2026-09-23。对象是 Codex 桌面端已安装的 **Plugin Value Lab 0.5.0**，并非只在源码目录运行单元测试。此次按用户要求验证可用功能，未执行新的 WITH/WITHOUT 模型研究。

## 安装与执行来源

- 已安装市场配置：Git 来源 `https://github.com/HERRY423/Plugin-Value-Lab.git`，引用 `main`；插件 `plugin-value-lab@plugin-value-lab-marketplace` 已启用。截图中的稀疏路径为空。
- 本次任务加载了 `assess-value`、`use-plugin-well` 两个技能，以及 6 个默认 MCP 工具；通过宿主实际调用工具。
- 文件验证和回放从宿主安装缓存的 0.5.0 副本加载。34 个 `value_lab/*.py` 文件与 `v0.5.0` 标签内的分发副本逐字节一致。
- `doctor` 检查：Python 3.13.9，离线引擎与 MCP SDK 可用。Codex CLI 为 `0.155.0-alpha.2.6`，Claude Code 为 `2.1.278`；版本查询不算模型执行。
- `doctor` 自身不会确认宿主安装；此处的安装与调用证据来自另行读取的安装状态和本任务实际工具调用。

这是一次已安装插件功能验收。未重新点击安装按钮，也未将“安装方式相同”推断成所有用户环境均可安装。

## 6 个 MCP 工具实调

共调用 11 次：10 次正常返回，1 次用不支持的输入版本验证错误拦截。完整原始回包留在本地验收目录；公开记录是[实际响应字段摘录](../evidence/installed-0.5.0-mcp-20260923.json)，不是独立认证的执行证明。

| 工具 / 场景 | 实际结果 |
| --- | --- |
| `example_value_suite` | 返回教学方案、空记录，`real_observations=0` |
| `validate_value_suite` | `valid=true`，计划 18 次执行，保留 12 条文字判据与校准警告 |
| `evaluate_plugin_value`：空记录 | 观测 0 次；`SIMULATION_ONLY`，内部判断为 `INSUFFICIENT_EVIDENCE` |
| 同工具：18 条合成记录 | 9 对完整配对；质量差 0.5，仍为 `SIMULATION_ONLY` |
| 同工具：两组结果都满分，仅 WITH 有流程标记 | 两组均 1.0，质量差 0；`NO_DEMONSTRATED_GAIN`，流程标记未计为结果收益 |
| 同工具：删除一条成本记录 | WITH 成本为 `null`，保留全部 18 条记录；`INSUFFICIENT_EVIDENCE`，缺失费用未填零 |
| `build_plugin_usage_card`：空记录及合成记录 | 均为 `TRIAL_GUIDANCE_ONLY`，`use_when=[]`；完整合成示例产生 7 条失败判据改进项 |
| `plan_plugin_use`：现有原生能力足够 | `USE_NATIVE`，没有发起安装或外部调用 |
| `inspect_claude_eval`：构造的原生 v1 结果 | 保留诊断，结论 `insufficient_evidence`；未把原生总分或标价估算升级为价值证据 |
| 同工具：不支持的 `schemaVersion=999` | 明确返回错误，拒绝解释未知版本 |

示例里的分数、费用、人工时间均为构造数据。质量差 0.5 **不是 Plugin Value Lab 自身的实测增益**；不能据此宣称节省了真实费用或人工时间。

## 已安装运行时的科研产物与回放

使用插件自带的公开合成样例，通过已安装脚本运行 `replicate-reference`，再调用同一安装副本的产物验证与登记/回放代码。[运行结果](../evidence/installed-0.5.0-runtime-20260923.json)。

| 检查 | 实际结果 |
| --- | --- |
| 独立样本设计，每组 4 个单位 | 效应 4，精确 p=2/70，BH q=4/70；达到冻结阈值 |
| 配对设计，4 对单位 | 效应仍为 4，p=0.125、q=0.25；正确保留 `not_supported` |
| 正确科研结果文件 | 通过计算契约验证 |
| 将 p 值改为 0.000001，重新计算文件摘要 | 验证失败，定位 `signal/p_value`；文件摘要一致不能掩盖错误统计量 |
| 独立设计中重复使用一个单位 | 拒绝伪重复：`Pseudoreplication` |
| 登记、导出到另一目录、离线回放 | 缺少评分材料时预检为 `MATERIALS_REQUIRED`；明确提供原材料后 `REPRODUCED`，结论仍为 `SIMULATION_ONLY` |

首次本地验收脚本误把产物验证器的元组返回值当成字典，脚本报错；修正验收脚本后在新目录完成上述检查。插件代码与安装缓存未修改。

## 结论范围

已建立：当前 Codex 安装可调用默认 MCP 功能；已安装运行时可以检查构造科研产物、保留未知费用和负结果、导出并重算证据包。未建立：真实跨宿主收益、真实科研结论、独立审查、普遍用户收益。本轮新增模型评测调用为 0；未购买外部能力。

安装说明现以本次成功使用的 GitHub 来源、`main` 引用、空稀疏路径为默认流程；另保留本地包和固定版本选项。[安装与排查](INSTALL.zh-CN.md)。
