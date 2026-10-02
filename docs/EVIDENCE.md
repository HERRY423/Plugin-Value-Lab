# Current evidence / 当前证据与未完成门槛

2026-10-02 新增[真实宿主上下文 P0 验收](history/NATIVE-CONTEXT-P0.zh-CN.md)：只读当前 Codex 桌面 0.159.2 的原生会话日志，逐响应绑定宿主、模型、会话、采样阶段和原始事件；分离单次占用与累计账本，未知不补零。[验收记录](evidence/native-context-p0-20261002.json)单列真实采集、实际压缩、追加重放和制造的异常测试。这不代表其他宿主验收、持续实时占用、结算费用或插件收益。

2026-10-01 按用户要求完成[采集、分析与展示分层](history/BURDEN-LAYERS.zh-CN.md)：不可变采集快照、独立分析重放、只读展示和旧入口兼容；四个合成场景逐项核对拆分前输出。[本次验收](evidence/burden-layers-20261001.json)独立记录，旧验收摘要保留历史身份。当前采集器接收已提交材料，未新增实时宿主采集。

2026-10-01 增加[按需展开的证据交互](history/DECISION-VIEW.zh-CN.md)：对话返回简短摘要，文字报告前置当前问题，离线 HTML 支持从提示跳转到具体证据。[验收记录](evidence/decision-view-20261001.json)保留本地测试及浏览器观察；这不是实时宿主监控或已验证的真人阅读收益。

2026-10-01 新增[独立负担视图](history/BURDEN-VIEW.zh-CN.md)，逐任务比较合格候选的上下文峰值、费用和耗时，保留取舍与未知，原选择规则不变。[本地记录](evidence/burden-view-20261001.json)区分测试、合成演示和真实宿主观察；本次未建立自动上下文采集或真实插件收益证据。

**Version 0.9.0.** This is the current source version. Historical receipts keep their original versions, hashes and limitations.

2026-10-01 新增[阶段内插件组合评估](history/PLUGIN-COMBINATIONS.zh-CN.md)，保留单插件评估及原组件消融。[本地验收记录](evidence/plugin-combinations-20261001.json)保存源码摘要：全量回归 1072 项通过，收尾后相关路径复验 128 项通过（含 28 项组合专项及真实本地 stdio）。六种制造案例验证互补、替代、组合退步、顺序差异、零插件足够与缺失数据处理；均为 SIMULATION_ONLY，真实组合收益与宿主暴露认证未建立，未发布或替换已安装插件。

## Community readiness (2026-09-30)

| Boundary | Current evidence and remaining work |
| --- | --- |
| Hosted CI | Onboarding fixes passed all 10 jobs at `f39e491`: [run 36723158638](https://github.com/HERRY423/Plugin-Value-Lab/actions/runs/36723158638), including 933 tests and actual Linux isolation. Later workflow-delivery changes require their own exact-commit CI evidence. The earlier [failed run](https://github.com/HERRY423/Plugin-Value-Lab/actions/runs/36580804328) is retained. |
| HPC | Slurm, PBS Pro/OpenPBS and LSF templates run the existing real kernel gates on allocated nodes. No target cluster has been supplied or validated. See [HPC operations](OPERATIONS.md#hpc-compute-node-acceptance). |
| Paid native eval | A historical official run reported $0.114 against a $0.09 estimate. Direct and sandboxed native launches now fail before a paid request because neither adapter supplies an independently enforced USD boundary. Export, import and offline analysis remain available. This blocking fix is not a completed metered execution adapter. |
| Scientific execution | Requires working Linux/WSL2 bubblewrap isolation. An installed binary or a passing login-node probe does not establish compute-node compatibility. Windows kernel acceptance remains unestablished. |
| Adoption and benefit | No complete natural-use plugin repair chain or non-author first-use timing sample is established. Local tests, fixtures, timestamps and packages do not establish scientific validity or independent adoption. |

English entry points: [tutorial](START.md), [operations and costs](OPERATIONS.md), [freeze policy](FREEZE.md). Detailed Chinese records below retain their original evidence scope.

2026-09-29 [研究执行层核查](history/RESEARCH-EXECUTION.zh-CN.md)：修复原生报告不显示可推导 W/OUT 的问题，并避免混用案例分母；研究扩展需在独立副本中显式启用。四题的 24 个计划会话槽位仍无真实研究结果，既有每臂一次的官方检索案例不填入这些槽位。Windows 容器引擎不可用，实核验收仍未完成。工具准备和本地回归均不计入实跑证据。

2026-09-29 的[工程易用性改进](history/ENGINEERING-USABILITY.zh-CN.md)新增简洁 CLI、Python SDK 与工作流示例。[验收记录](evidence/engineering-usability-20260929.json)区分干净安装、真实 Jupyter 内核、工作流引擎、缓存科研数据派生文件与非作者采用；测试通过不增加真人样本数。

截至本轮 2026-09-28 核查，**完整自然使用插件修复闭环 0；非作者从零使用计时样本 0；独立外部采纳未建立。** 本地测试、回放、签名和摘要不能代替这些观察。

本轮判定可靠性修复及原反例的前后对照见 [正确性参考资格与内核 CI 记录](history/CORRECTNESS-RELIABILITY-20260928.zh-CN.md)。状态／格式通过不再补足蜕变结果的正确性参考资格；本地内核通过与尚未复验的托管 CI 分开记录。

## P0 当前能力与证据

2026-09-29 新增[外部时间、结论范围与真实插件观察](history/VALUE-EVIDENCE-20260929.zh-CN.md)：两份 RFC3161 外部时间戳已验证，逐结论范围卡会拒绝越界引用，真实官方 export/import 已走通。Literature 实际标识符分类缺陷在本地副本修复并经现场对照复测；NGS 运行环境接口超时，未启动工作流。官方运行出现条件偏离及费用超限，保留失败；这些观察不增加非作者自然使用或收益样本。下表原 P0 计数仍按其历史口径解释。

本轮新增的 [失败诊断谱系、组件真实替换和报告盲测](history/TRACE-DIAGNOSTICS.zh-CN.md) 分开记录真实宿主写入事件、受控本地干预和外部模型读报告；L3、真人阅读验证及通用宿主监控仍未建立。

当前源码版本为 **0.8.0**；当前接入修复尚未发布。下表区分源码能力、交付验证、实际宿主观察和真人使用；相同版本号不保证字节相同。机器快照见 [P0 状态与来源](evidence/p0-status-20260928.json)，本轮实施与下一步见 [P0 交付记录](history/P0-DELIVERY-20260928.zh-CN.md)。旧收据继续按其原版本、源码摘要及范围解释。

| 能力 | 源码／本地验证 | 实际宿主或真人证据 | 当前可说的结论 |
| --- | --- | --- | --- |
| 核心评分、使用卡与五步入口 | 已实现；本轮交付另行核验 | 历史原生导入有缺口 | 能检查提交的冻结材料；不认证普遍收益 |
| 对话式评测创建与规则校准 | 已实现；宿主 Agent 负责语义设计 | 非作者独立完成未建立 | 可准备研究方案；校准不是实际模型试跑 |
| 可读的作者诊断 | 已用历史真实 CSV 产物复算；失败与未知逐项展示 | 实际阅读反馈与耗时未知 | 能指向产物和规则；不能自动归因插件 |
| 科学产物／蜕变／等效性／组件检查 | 当前工作区已有实现，具体契约不同 | 不能由本地测试推定科学有效性 | 只能支持相应冻结的计算要求 |
| 环境锁与 MCP 录制回放 | 已实现；回放明确没有新增科学计算 | 真实外部环境重建未建立 | 记录漂移和重放材料，不保证重拟合一致 |
| 在线隔离与原生采集 | Linux 边界有历史工程记录；Windows 实核待验收 | 本机 Claude 2.1.282；历史剖面为 2.1.278 | 宿主存在不代表当前版本采集已验收 |
| 安装副本与本次交付 | 包、镜像和安装缓存分别核对 | 未自动更新已安装插件 | 当前源快照不冒充已安装或已发布版本 |
| 真实组件修复 | 本轮重跑 NGS 2/7→7/7，BioNexus 2/5→5/5 | 无完整自然 Agent 修复链 | 真实组件在披露的制造输入上回归通过 |
| 非作者真实问题试跑 | 现有路径已串成[交接页](../examples/pseudobulk-author-pilot/HANDOFF.md) | 用户确认当前暂无参与者 | 可转交；真人验收待完成 |
| 自然使用修复链 | 历史证据已逐环审查，失败记录保留 | 完整链仍为 0 | 不将组件复测、基线错误或回放拼接成闭环 |

P0-1：当前能力与证据表已建立。P0-2：本地流程与交接可验收，缺真实非作者和实际问题。P0-3：组件重验及缺口审查已完成，尚缺同一真实问题的插件调用、错误产物、修复和完整自然复测。三项总体不标为全部完成。

## 历史记录及原证据边界

本轮 P1 已加入三类科学判据的公开开发校准、统一冻结质量口径和作者完整负担比较记录。见 [P1 交付及限制](history/P1-DELIVERY-20260928.zh-CN.md) 与 [机器验收快照](evidence/p1-status-20260928.json)。P0 快照是先前源码的历史证据；真人效率、独立审阅与自然修复闭环仍未建立。

| 材料 | 支持什么 | 不支持什么 |
| --- | --- | --- |
| [8 类 × 3 种子元验证](../DETECTION-VALIDITY.md) | 96 次本地执行；报警 22/24，配对净检出 19/24；保留误报漏检 | 真实总体准确率、自然触发或自动源码根因定位 |
| [已知边界修正复测](evidence/detection-boundaries-acceptance-20260927.json) | 不加访问观察器：净检出 22/24、误报 0/18；加受控观察器：24/24、0/18；保留首轮换行误报 | 未见事故覆盖率、通用宿主泄漏检测、独立审阅或真实收益 |
| [真实先导与运行故障](evidence/real-loop-20260925.json) | 真实调用、部分结果、宿主失败、未知成本 | 完整两臂收益、自然修复或独立上游采纳 |
| [实现验证](../VERIFICATION.json) | 指标、负向项、未测灰色、身份绑定与离线复算 | 作者效率、实际收益或长期有效性 |
| [分类修复验收](history/NATIVE-ANALYSIS-REPAIR.zh-CN.md#分类修复与作者过程记录2026-09-26-修正) | 已观察失败进入冻结执行端点；触发与产物修复分别验收；保留失败尝试与过程声明 | 新的真实作者修复实验或 PVL 帮助修复的因果证据 |
| [首次使用试跑](START.md) | 可转交材料与固定计时口径 | 尚无参与者结果，人工耗时未知 |
| [自己的配对分析问题试跑](../examples/pseudobulk-author-pilot/RUNBOOK.md) | 数据映射、待确认契约、现有参考／验证路径及原始活动计时；PVL 有／无比较协议 | 真实作者样本仍为 0，未确立节省时间或净收益 |

分类修复的[本地工程验收记录](evidence/native-repair-semantics-20260926.json)：合并工作区完整测试 565 项通过、零跳过，其中 32 项原生分析专项测试包含本次新增的 9 项回归；绑定实现与测试文件摘要。没有新增真实作者修复实验。

使用建议的[范围与适用性验收记录](evidence/usage-scope-semantics-20260926.json)：完整测试 579 项通过、零跳过；最终界面调整后 52 项使用建议测试再次通过，另有 8 项诊断测试验证成本账本入口一致性。覆盖基线优先与风险分离、冻结任务范围的独立判定、指标不适用声明及缺失状态；浏览器验收使用制造数据。范围的事前性和复核身份仍未独立认证，未新增真实用户收益实验。详细契约见[范围与指标适用性](history/P2-REUSE-GUIDANCE.zh-CN.md)。

作者试跑包的[本地验收记录](evidence/author-pseudobulk-pilot-20260926.json)：完整测试 591 项通过、零跳过，包含 12 项材料准备与计时回归；中文及空格路径下的迁移试跑通过。迁移检查只使用制造数据和程序输入，没有真实参与者，也未开展 PVL 有／无收益实验。

历史反例包括隐藏参考泄漏、`allow` 但答案为空，以及训练 ID 顺序、合法标签别名、直接读取插件文件误报。2026-09-27 修订在明确冻结的任务契约下处理后四项；隐藏访问仍需额外观察，受控 Python hook 不代表真实宿主已具备这一能力。PVL 偏好不能写成插件缺陷。后端回退检出依赖运行身份证据，仅数值相同或自报名称不够。

历史实跑发生 DNS、Unix socket、解释器依赖与产物留存故障，首先属于运行／采集诊断。已记录的探针加首轮供应商估算合计 US$3.587263，实际结算仍未知。本轮文档与试跑包不新增模型调用。

## 解冻复盘需要的材料

1. 真实自然使用的调用 → 错误产物 → PVL 定位 → 修复 → 同条件自然使用复测，保留正常对照、反驳与失败。
2. 至少一次非作者从零生成并理解 USAGE.md 的完整记录，包括安装、阅读、求助、失败和放弃；不以作者／AI 冒烟替代。
3. 检出修复保留原测试结果，再观察未暴露真实事故和正常变体；不以公开开发集推断总体准确率。

这些材料不自动产生认证、推广或解冻；按 [冻结规则](FREEZE.md) 明确复盘决定。

## 文档范围

主线固定八份：两份 README、CONTRACT、DETECTION-VALIDITY，以及 docs 下 START、OPERATIONS、EVIDENCE、FREEZE。机器证据、示例、技能契约和历史资料不是新增入门阅读任务。

原 36 份 docs 指南与实施记录、根目录变更日志归档到 `docs/history/`。旧版本、旧实验和安装状态是历史快照，兼容接口细节按需查看。[迁移映射和原始摘要](history/migration-20260925.json) 保留，[变更日志](history/CHANGELOG.md) 不再扩张首页导航。
## 可执行验证入口

显式重执行、供体配对 pseudobulk 协变量检查和独立计分的盲评流程见[可执行科学产物验证](history/SCIENTIFIC-EXECUTION.zh-CN.md)。模型复核与人工专家验证分开；重新生成一致不自动证明科学正确性。

大规模 h5ad 的磁盘聚合、流式文件输入输出、资源预算及数据规模验收见[真实数据规模契约](history/DATA-SCALE.zh-CN.md)。计数矩阵保留在 h5ad；JSON 仅承载小型结果与证据引用。
