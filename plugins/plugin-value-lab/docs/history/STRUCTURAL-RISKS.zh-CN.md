> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# 三个结构性问题：可执行修复与尚未取得的证据

2026-09-25 补充：[DETECTION-VALIDITY](../../DETECTION-VALIDITY.md) 已完成八类、每类三个源码种子缺陷的隔离副本执行、采集、诊断和恢复复测。它给出有条件的检出／误报与定位边界；不替代独立标注的真实事故谱，也不关闭自然模型使用修复链或作者耗时门槛。

当前源码版本保持 0.6.0。本页取代早期仅围绕清单、登记处和扩展开关的验收说明。

## 1. 修复链必须逐段有证据

现存真实宿主采集的产物检查通过，但没有观测到 Skill 调用；NGS/BioNexus 的历史组件修复是本地脚本/函数执行，不能拼接成模型自然调用后的修复闭环。

`compare-native-repair` 保留原有完整两轮比较，并新增 `repair_chain`：

- 缺少作者诊断到改动的记录，链保持 `OPEN`。
- 记录必须绑定已核验的修复前 receipt 和重新计算的 diagnosis 摘要；每项引用实际失败后修复的判据、已变更的插件文件、插件命名空间下的 Skill 和改动理由。
- 从两轮原始事件重新提取成功 Skill 调用。只加载插件、文字自称调用、无返回的调用、无关技能、仅产物通过，都不能补足调用证据。
- 原有完整性门槛仍检查全部案例/臂/重复、独立会话、冻结输入与规则、环境及基线变化。显式调用探针与自报 synthetic 记录不得进入真实闭环状态。
- 材料全部满足时，仅为 `TRACE_SUPPORTED_LOCAL_CHAIN`。自然使用是作者声明，改动解释是作者假设；不认证执行真实性、根因或收益，`use_recommendation` 仍为 `INSUFFICIENT_EVIDENCE`。

记录格式（所有摘要和身份须从实际材料获得，不要复制占位值）：

```json
{
  "before_receipt_sha256": "<retained before receipt digest>",
  "before_diagnosis_sha256": "<canonical digest of verified before diagnosis>",
  "use_mode": "natural",
  "evidence_type": "local",
  "repairs": [{
    "case_id": "<repaired case>",
    "grader_id": "<failed then repaired check>",
    "skill": "<plugin-name>:<skill-name>",
    "changed_files": ["<changed selected plugin file>"],
    "rationale": "<which diagnosis informed this edit and why>"
  }]
}
```

```sh
python scripts/value_lab.py compare-native-repair before-capture after-capture --before-receipt BEFORE --after-receipt AFTER --repair-record repair-record.json --output repair-comparison
```

该记录辅助复核，不替代真实实验。当前完整自然使用闭环数量仍为 **0**。下一步必须选定实际任务和候选插件，保留模型自然选择的调用轨迹、真实错误、定位记录、代码差异及完整自然复测。未调用、复测失败、成本未知都必须保留；不得改写为成功。

## 2. 先缩短作者路径，再测量负担

README 改为一个诊断入口和三个步骤。默认 CLI 帮助只显示四个命令；完整兼容命令通过 `--advanced --help` 查看。新增行为放进已有模块，没有新增运行模块。底层命令仍可直接调用，历史模块/文档仍有维护成本，不能把隐藏入口称为删除复杂度。

`diagnose` 接受单个产物、已有配对研究目录或原生采集目录，直接产出 `DIAGNOSIS.md` 与 `diagnosis.json`。单文件检查要求明确判据；原生目录核验保留摘要后重新评分，并单独显示缺失的插件调用证据。研究/团队扩展保持默认关闭，登记处始终可选。

计时分为三层：

| 记录 | 当前可测 | 不包括 |
| --- | --- | --- |
| `machine_seconds_to_diagnosis` | 进入 CLI 到诊断计算完成 | 解释器启动、写报告、安装、准备和阅读 |
| 接受测试的完整进程耗时 | 启动 Python 到写完报告并退出 | 人的安装、理解和修复 |
| `--interactive` 的作者反馈 | CLI 进入到真实操作者反馈；仅 actionable 才记首次可行动诊断时间 | 安装与此前准备 |

`unclear`、`unhelpful`、中断、EOF 保留，不算成功耗时。没有真实作者参与时，相应时间为 null。安装到首次诊断、原有方法对照、作者满意度仍需要真实参与者，不能用机器毫秒数替代。

## 3. 检出审计不能只展示成功例子

运行仓库提供的 18 项公开开发集：

```sh
python scripts/value_lab.py diagnose examples/detector-corpus/manifest.json --audit --output detector-audit
```

标签事先写在 manifest 中，实际调用内置检测器，不从检测结果生成期望标签。四个历史组件输出及构造输入保留原摘要；它们并非独立外部事件。每项区分 `task_contract`、`scientific_adjudication`、`operator_preference`；争议和偏好不进入二元正确率分母，但仍在报告中。

输出包括 TP/FN/FP/TN、UNKNOWN、排除标签、按缺陷族和来源分层、漏检列表和未覆盖族。缺失、摘要变化、依赖不可用不能成为检出或放行；有未知时率为 null，同时给出保留全部计划样本的上下界（不是置信区间）。同一产物与同一判据改名不能增加分母。

当前集故意保留：删除测试家族成员、反转效应、替换原始 p 值、上游重复 ID 覆盖这四类漏检；任务允许 Bonferroni 而检查器限定 BH 的一项误报；一项未采集产物；两项非确定标签。混杂、数据泄漏、工具选择和生物学解释列为未覆盖。

这建立了可复算的失效地图，**没有建立真实缺陷总体检出率**。需要独立作者的实际事故、明确任务约定、独立标注及异议、正常变体、按事故家族隔离的未见测试集，并按场景预定可接受漏检/误报率。不得通过修改标签、删除漏检或把开发集换名为 heldout 获得通过。

## 本次交付的边界

初次本地改动未发布、未更新安装缓存、未发送外部消息、未新增付费模型调用，工程检查见 `docs/evidence/structural-author-20260925.json`。随后按用户授权执行明确调用探针、启动三任务族研究并提交上游补丁；最新逐项记录见 `docs/evidence/real-loop-20260925.json`。版本仍不变，未知费用结算没有归零。

明确调用探针暴露并修复了 PVL 对省略可选 `is_error` 的工具返回解析错误；同一真实日志离线复算通过。自然条件和明确调用条件的产物原本均正确，因此这不是插件产出错误后的自然使用修复闭环。

BioNexus 的 [PR #36](https://github.com/HERRY423/BioNexus/pull/36) 已提交冻结的修复前源码、复测协议、摘要和结果。当前快照的 29 项 CI 检查通过；人工反馈、采纳、人工复测耗时和反驳仍未取得，而且为同一所有者仓库，不能计作独立采用。NGS 的[补丁与冻结包](https://github.com/HERRY423/plugins/tree/fix/pvl-quant-validation)已推送；上游 `openai/plugins` 限制只有协作者能创建 PR，故没有上游 PR 编号，需上游协作者从比较页提交。

首轮三个任务族分别为 CellTypePilot 身份表示映射、NGS Salmon 汇总、BioNexus 对已有 SPP1–CD44 结果的证据审计。它们是三个不同插件/任务组合，每个插件只有一个任务族，不合并为同一插件的三族收益证据。SPP1–CD44 输入来自已有 LIANA 结果的脱敏摘录，审计包由本次派生，不冒充原始生产者认证或新配受体计算。

运行器先发生 DNS 隔离配置错误，未取得模型响应；随后两次付费会话因 Windows 挂载盘不支持沙箱 Unix socket 失败，估算合计 US$1.011872。两类失败均保留；后者是操作者环境错误，不归因于插件。用户另行批准保留两次失败并在修正后的 Linux 文件系统运行完整 18 次，总上限 20 次、首轮估算阈值 US$4.02，允许在途超出；未授权修复后的第二轮。真实自然使用闭环、外部作者 time-to-first-diagnosis、代表性独立检出审计三个经验验收门槛仍需实际结果，不能用准备材料替代。

### 首轮实跑的停止记录

此次首轮实际产生 **8 次 WITH 会话、0 次 WITHOUT 会话**，未完成计划中的 18 次平衡研究，也没有达到每臂至少 3 次。首轮原生估算累计 **US$3.423943**；加上明确调用探针为 **US$3.587263**。它们是原生估算，提供方结算仍未知；没有把未知历史结算归零。

| 实际组 | 会话数 | 观察结果 | 估算 US$ |
| --- | ---: | --- | ---: |
| 初次本体映射 | 2 WITH | Windows 挂载盘不支持沙箱 socket | 1.011872 |
| Linux 本体映射 | 2 WITH | 1 次原生报告完成；系统 Python 缺依赖，封存产物未成功导出，内容评分未知 | 1.161203 |
| NGS 汇总 | 2 WITH | 已观察到技能调用；bridge socket 连续失败后主动中止 | 0.523371 |
| SPP1–CD44 审计 | 2 WITH | 已观察到技能和 Bash 调用；内层 Python 缺 numpy，主动中止 | 0.727497 |

本体映射日志观察到直接读取 CellTypePilot 技能、本体和源码文件。PVL 当前的命名空间 Skill 事件判据只覆盖一种调用方式；不得由缺少 Skill 事件推断完全没有使用插件。SPP1 内层宿主也观察到环境中其他 `/usr/local` 资源，说明外层命名空间探针不能替代原生宿主内的依赖与隔离检查。模型后来借用环境中的科学 Python 库跑通了一个审计探查，但没有形成冻结要求的完整结果，不能改记为成功。

本次失败主要暴露了操作者运行器问题，不是插件效果证据。所有已取得的日志、费用、未知评分和原采集收据保留；停止新增付费调用。再次付费前必须先以无供应商费用的原生宿主工具验收，验证实际 Python、依赖、允许与禁止路径、完整 socket 路径、退出后的封存读取和导出。仅重新通过外层预检不满足这个条件。
