# Scope freeze / 六周范围冻结（当前版本 0.8.0）

**Version 0.8.0.** The freeze started on 2026-09-25, with review planned for 2026-11-06. Expiry does not automatically authorize new features. The `version_series: 0.6.x` field in `feature-freeze.json` identifies the original freeze, not the current package.

Correctness, security, compatibility, tests, translations and simpler instructions for existing behavior are allowed. New CLI/MCP surfaces, graders, runtime modules or product scope require an explicitly recorded scope decision. Run `python scripts/check_feature_freeze.py`; passing that structural check does not replace semantic review. Keep the eight main documents and historical receipts; do not update historical versions to imply newer validation.

The 2026-09-30 onboarding repairs keep version 0.8.0 and existing interfaces: correct current version declarations, add English sections and scheduler examples for existing acceptance scripts, block unbounded native paid execution, and repair hosted CI failures. Kernel probes remain mandatory and cannot fall back to unsandboxed execution. The budget gate blocks launches pending a genuinely bounded transport; it does not claim to meter requests. These are fixes to existing paths requested by the project owner.

2026-09-30，负责人明确要求“认真完成具体入口缺口的修复”，授权补齐两个既有 MCP 工具的产物交接参数。限定范围记录在 `mcp_artifact_handoff_scope_change`：仅增加 `artifact_root` / `verifier_root` 可选选择器，以及宿主启动环境中的对应目录授权；不增加工具、CLI、运行时模块、评分类型或版本号。原有四个参数保持兼容；MCP 禁止执行验证程序，文件缺失与摘要不符仍未验证，使用卡保留本次重算收据。接口快照只追加这两个工具的两个参数，不覆盖其他冻结基线。

2026-09-30，负责人进一步明确要求完成“从评价一个插件变成为一个任务选择最小必要方案”。本次按新增能力记录 `task_selection_scope_change`，不是普通修错：允许一个任务选择模块、既有规划 MCP 的两个目录选择器、既有 `plan-use` 的两个材料选项，以及制造案例与回归测试。保留六个 MCP 工具、旧路由、评分器、版本 0.8.0 和八份主线文档；不自动运行、付费、安装，不放松原有证据边界。详见[任务选择契约](history/TASK-SELECTION.zh-CN.md)。

生效 **2026-09-25**，计划复盘 **2026-11-06**，共 42 天。冻结最初针对 **0.6.0**，当前项目版本为 **0.8.0**。到期不自动解冻，需要项目负责人明确记录决定。

2026-09-30，负责人进一步要求建立“证据迁移与桥接”。按 `evidence_bridge_scope_change` 增加一个限定矩阵任务的桥接模块，通过已有规划上下文识别差异、验证真实输入、保留旧研究并生成独立目标协议。精确引用门槛不放宽；研究设计、判据、模型／宿主或插件内容变化默认新建研究，输入等价不认证生产程序的运行等价。不新增工具、CLI 参数或版本。

2026-09-30，负责人继续明确要求“从运行一整套测试变成只补能改变选择的证据”。按 `decision_evidence_acquisition_scope_change` 增加一个序贯补证据模块及既有规划上下文模式：母协议预先绑定目录、检查、预算和停止规则，逐批冻结；已启动批次保留全部分母，筛选和预留确认材料分开。新增能力不宣称统计停止保证、现实节省或科学有效性，不增加工具、命令或版本号。

`docs/feature-freeze.json` 的 `version_series: 0.6.x` 保留冻结的起始身份，不代表当前软件版本。后续经明确授权的范围变化分别记录在该文件的 `*_scope_change` 中；当前允许的接口以其中 `surface` 与检查结果为准。历史验收不随版本或范围变化自动升级。2026-09-28 的 P0 工作只整理证据、简化现有交接与重验已有路径，不增加运行时接口、评分器或版本号。

目标是降低真实非作者首次使用门槛，完成一个可信修复闭环，验证检出边界。冻结期间不以更多入口、文档或仪表盘代替证据。

2026-09-28 用户明确要求继续完成三项 P1，限定增加既有判据的校准、冻结前可选的质量汇总口径，以及现有作者试跑脚本的完整负担账本。语义范围例外记录于 `p1_calibration_decision_burden_scope_change`；不新增运行时模块、评分类型、主 CLI 或 MCP 接口，现有全部任务成功门槛保持不变。具体边界见 [P1 交付记录](history/P1-DELIVERY-20260928.zh-CN.md)。

| 允许 | 禁止 |
| --- | --- |
| 有复现证据的正确性、安全、兼容修复 | 新 CLI 子命令或选项、MCP 工具、自动发现技能 |
| 同一已有行为的文案、帮助、错误处理、步骤简化 | 新评分器、指标体系、集成、宿主、研究／团队产品面 |
| 补测试、真实运行、非作者计时、上游反馈 | 新运行时模块或与验收无关的重构 |
| 归档实施记录、修复引用、减少阅读量 | 主线文档扩张至八份以上 |

必要例外先记录问题、复现、无法在既有接口修复的原因、影响范围、复测和负责人明确同意。不得把新功能改称修复或擅改冻结清单以让检查通过；普通既有路径修错无需额外审批。

## 落地约束

2026-09-29 用户明确要求“深度改进工程易用性”，授权本次限定例外：新增 `pvl` 六命令入口与 `value_lab.sdk`、三个工作流示例；README 增加一命令起步。旧 CLI、五条完整评估命令、MCP、评分语义与八份主线文档保持。新增接口独立加入冻结检查，不覆盖旧接口基线；细节见 `engineering_usability_scope_change` 和[工程易用性记录](history/ENGINEERING-USABILITY.zh-CN.md)。下段的默认推荐约束对新增便捷入口按本例外执行。

2026-09-29 用户明确将首次使用场景纠正为“PVL 已作为插件安装在 ChatGPT 中，并可被调用以评估其他插件”。据此，README 和技能引导优先使用自然语言任务及已有 MCP 工具；五条 `doctor → freeze → evaluate → usage-card → compare-studies` 命令保留在开发者补充中，默认 CLI 帮助保持原样。本次只调整既有入口的说明顺序，不新增接口，不把对话理解或可调用状态当作真实两臂采集。旧高级接口不删除，研究／团队扩展仍默认关闭。

`docs/feature-freeze.json` 固定 CLI 命令／参数、MCP 工具、技能、运行时模块和评分类型清单；CI 检查功能面扩张、主线文档超限及五步入口漂移。检查不因日期自动失效。它不能理解所有代码语义，既有函数内新增产品行为仍需人工审阅，不能宣称机械禁止全部新功能。

冻结文件使用 `pvl-feature-freeze-2`。MCP 签名按参数顺序记录名称、传参方式、规范化注解、默认值是否存在及其带类型的值，并固定返回注解与同步／异步方式；不比较解释器的 AST 字符串表示。默认值和注解只解析、不执行，未支持的语法拒绝通过。旧快照的表示迁移须核对原有参数，不能用当前源码直接覆盖基线。参见[发布阻断修复记录](history/RELEASE-BLOCKERS-20260926.md)。

冻结期改动说明复现问题、既有路径怎样改善、验证结果和历史证据影响；实施细节放 `docs/history/`，旧运行与判断不覆盖。发布、付费和联系他人仍遵守具体授权。

## 到期复盘

负责人查看 [证据状态](EVIDENCE.md)、真实首次使用记录、剩余失败与维护负担，决定延长冻结、仅修错或明确批准下一项功能，并说明范围与依据。没有同事回执就保留缺失，打包完成不能算作采用。
