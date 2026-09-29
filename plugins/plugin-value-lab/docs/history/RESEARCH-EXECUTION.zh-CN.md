# 研究执行层：修复报告、显式启用扩展、保留实跑缺口

2026-09-29，版本保持 0.7.0。本轮修复已有原生报告和研究评测的准备／核验路径，不新增主 CLI、MCP、运行时模块、科学评分器或默认技能。

## 比较口径

[官方当前契约](https://code.claude.com/docs/en/plugin-evals)已有 WITH、W/OUT、Δ；默认每题两臂各三次。退出通过线使用 WITH 绝对分，Δ 不改变退出码。它有基线，不能描述成“只有一个分数”。PVL 的科学判断另要求匹配条件、任务成功差及充分证据。二者的通过规则与分母应分别解释，不能用 PVL 的规则重命名官方 PASS。

PVL 原生报告此前始终令 `without_score=null`。现按官方字段 `score - delta` 在每个有基线的案例内推导诊断基线；没有 delta、没有基线或计算越界仍未知。只有全部已报告案例都可计算时才汇总 W/OUT，避免把部分案例的 meanDelta 从全部案例的 overallScore 中相减。报告保留 `unverified_native`、`insufficient_evidence`、完整配对数 0 与未核验成本；不从原生分数推断科学任务成功。计划中整项缺失的案例由独立冻结清单核对，不能由结果文件自行定义分母。

## 一个会使研究比较失焦的准备问题

四道教学研究题位于 `evals/research/`。默认 Claude 插件只发现 `skills/`，研究指导位于 `extensions/research-directions/`；直接运行默认包不能等同于研究扩展的比较。本轮接受工具复制明确的发布文件清单至新目录，并仅在该候选副本中把研究指导放入 `skills/research-directions/`。源包、安装缓存和默认技能保持原样。

候选增加独立的 Skill 触发观察项，明确排除在两臂结果分数之外。语义判据与原题保持一致。冻结清单分别保存源发布内容摘要、候选逐文件摘要、原题／候选题摘要、模型、评判模型、次数、限制与 24 个会话槽位。这个副本测试“显式启用研究扩展的 PVL”；不把结果归到默认包。题目已公开，不能充当未见任务或独立科学效能验证。

## 可执行的接受工具

从项目根目录运行，选择新的输出目录。模型值必须由操作者确认；下列值为占位符。准备命令不调用模型。

```text
python scripts/check_research_execution.py prepare --model CONFIRMED_MODEL --judge-model CONFIRMED_JUDGE --estimated-ceiling 0.09 --output work/research-prepared
```

输出包括 `candidate/`、`plan.json`、`plan.sha256`。完整官方参数向量保存在 `plan.json.command`：四题、每臂三次、保留临时轨迹、不发布、不自动信任、不启用真实 MCP 或额外工具。计划名义上需要 24 次 Agent 会话和 72 次 judge 调用；失败、跳过和供应商重试可能使实际计数不同。估算阈值不是结算硬上限，准备工具明确记录 `execution_authorized=false`，不会自行执行参数向量。

费用与隔离条件满足、正式执行后，用已保存的摘要核验结果；不传 `--result` 可输出全部缺失的基线盘点：

```text
python scripts/check_research_execution.py audit --plan work/research-prepared/plan.json --plan-sha256 SAVED_SHA256 --result work/research-prepared/native-results/aggregate-result.json --output work/research-audit.json
```

审查完整 24 个槽位：漏题、缺侧臂、未开始、失败、aborted、未判读、重复 tracePath、超额次数、模型／提示／轮次／评判条件偏离。逐槽保留原生结果和解释；数值通过不能掩盖这些项。缺失分母不缩小，输出语义判据的报告通过率上下界及差值上下界；这些是缺失值边界，不是置信区间，也不是 PVL 科学成功率。

退出码 2 表示覆盖不全；0 只表示准备成功或报告覆盖完整。即使 24 个报告都完整，状态仍为 `INSUFFICIENT_EVIDENCE`：聚合文件没有独立认证真实调用次数、加载字节、轨迹内容、隔离、结算和审阅。局部哈希也不是独立事前登记。原始失败、超限和方案修订不得被新目录替换。

## 本轮实际证据与阻断

- 四道研究题实际模型／评判执行仍为 0；准备与制造数据回归不算实跑。
- 保留的官方检索案例是真实两臂各一次，1／1／0；它不是这四道研究题，也不是严格匹配收益实验。已记录 Glob、轮次和费用偏离。
- 原生报告费用 $0.113755，高于所设 $0.09；此前相关累计报告 $0.2562524，实际结算未知。不能将剩余授权按已结算零元计算，也不能用同一软限再赌一次。
- 本机本地 Docker Windows 引擎管道不可连接。此项是环境预检阻断，Windows Hyper-V 内核、真实 Claude 网关兼容性和在线隔离均未因此获验收；未安装镜像、启动服务、切换引擎或退回 WSL。

本轮落盘核查见[机器证据](../evidence/research-execution-20260929.json)。继续真实模型运行需先核清原费用与可执行的费用限制；Windows 验收还需要可用的原生 Windows 引擎和已固定的兼容镜像。完成本轮代码修复不意味着上述两项经验缺口已关闭。

本地完整测试 927 项通过、零跳过；该批次加载后又收紧费用偏离与重复轨迹检查，最终受影响的原生报告、研究核验与报告呈现共 35 项复测通过。候选清单通过本机官方 CLI 校验，冻结检查通过；这些均为本地工程证据，未增加真实研究会话。
