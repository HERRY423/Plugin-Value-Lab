# PVL 自身的完整负担比较

比较同一研究者使用“现有 Agent＋原生工具＋已有脚本”与“相同条件＋PVL”。所有准备、误报处理、审阅、失败和放弃均需保留。只缩短诊断命令运行时间不能说明研究者获益。

研究者用自然语言确认真实问题、可用结果标准、允许投入和已有暴露；Agent 负责以下技术配置。当前无参与者，模板均为 DRAFT／空值，不能直接当作观察结果。

## 运行前

1. 在本地观察包内从 `burden-plan.template.json` 准备 `burden-plan.json`。填写强基线、匹配依据、统一质量要求、人工费率、共享工作分摊及其依据。使用等价但不重复暴露答案的问题；同一个问题重复时必须披露学习和迁移影响。代码只检查声明、哈希和时序，不能证明任务匹配或独立性。
2. `pairs` 每项包含 `id`（字母／数字／下划线／短横线）、参与者代号 `participant`、`problems`（`with_pvl`、`without_pvl` 各一个真实问题标识）、两臂 `order` 数组、每臂的 `max_attempts`、`active_limit_seconds`、`cash_limit_usd`。多名参与者在运行前安排交错顺序；不能看结果后改配对。
3. 审核方案后才将 `status` 改为 `FROZEN`；保存原字节。为每次实际尝试配置 `session.json`，其中 `burden_plan` 指向该方案。计时器会在记录开始前检查匹配关系，并在观察输出目录保留方案副本。已有副本不同则拒绝覆盖；修订需新包，原失败保留。
4. 在任何阅读／安装／准备之前开启计时；如果已有前置工作，从原始计时间隔单独入账。没有原始观察则保持 unknown，不能倒填一个估算秒数。运行命令沿用 RUNBOOK；脚本只记录时间，不执行模型，不替用户授权外部调用或强制终止任务。触及冻结停止点后实际停止，摘要会标出超限，不能事后提高限制。

## 运行中与运行后

每次尝试生成独立 journal。用 phase 记录安装、阅读、数据准备、参考审阅、对照、诊断、误报复核、修复及复测；离开任务用 pause。完成、blocked、abandoned 如实结束；中断尾部未知，不当作零耗时。求助双方时间分开：操作者等待用 pause，助手工作在补充计时中记录。

观察包内准备 `burden-ledger.json` 和 `burden-reviews.json`，分别从空模板开始，`plan_sha256` 必须等于冻结方案的实际文件 SHA-256。Agent 可以整理证据，不能制造人工计时或代填审阅结论。

账本 `coverage` 必须覆盖每个 `pair_id/arm/category`：arm 为 `with_pvl`、`without_pvl`、`shared`；category 为 `pre_journal`、`post_journal_review`、`cash`。每个组合填 `itemized`、`not_applicable`、`unknown`，人工类别可用 `in_journal` 表示这部分工作实际上已在该臂原始日志内完整计时；共享工作和现金不能标记为 in_journal。未收集费用不能填 not_applicable。复用已有参考仍须说明原始成本及分摊，不把“已有”当作免费。

每笔 `entries` 填唯一 `id`、`pair_id`、`arm`、`category`、`evidence: {path, sha256}`、凭据内的唯一 `evidence_line`。凭据须为观察包内文件，不能指向外部目录。同一凭据行不得重复分配，共享份额由方案 `shared_with_fraction` 统一计算，剩余份额归基线。

- 人工项填写 `intervals`，每段为 `{actor, start, end}`，时间为带时区的 ISO 时间。程序计入所有参与者劳动，拒绝同一人相互重叠的计时（包括运行日志与补充账本）。这些仍是提交的计时证据，不证明人员身份或实际活动。
- 现金项填 `amount_usd`（未知为 null）、`basis: estimate/settled`。包括机器、模型、工具、重试及计时结束后的审阅费用。现金与费率折算劳动分别展示；估算不变成结算。

审阅 `entries` 每项按 journal SHA-256 绑定一次尝试，填写 `reviewer`、`decision: usable/unusable/unknown`、`false_alarms`、`confirmed_defects`（非负整数或 null）、`evidence: {path, sha256}`。审阅材料须包含统一质量要求下的理由和证据；声明 usable 不认证科学有效性或独立审阅。未完成的尝试不能标为可用交付；声称理解／声称可信复测的里程碑仍单独保留 PENDING，不能以最终产物审阅倒推首次理解时间已获确认。

```powershell
python examples/pseudobulk-author-pilot/report.py "你的本地观察包目录" > "另存的观察摘要.json"
```

## 如何解读

所有尝试进入主动时间、阶段时间、求助和经过时间汇总。额外准备、共享投入、终止后审阅按方案加入完整人工时间；现金单列，未知不补零。日志经过时间之和并非并发活动的实际日历耗时。停止限制、日志重复、证据变动、计划不匹配和未审阅误报都会阻断比较。

只有全部计划配对完整、两臂都产生经声明审阅可用的结果、全负担有据可查时，才给出每对 `without_pvl - with_pvl` 差和配对均值。正数是提交材料中的负担减少，负数是负担增加；质量不同不比较速度。全部失败和此前放弃尝试仍在成本中。单名研究者、多次尝试或多个相关问题不构成独立样本，代码不做显著性或因果判定。

维护者／AI／制造记录始终显示 `MAINTAINER_OR_SIMULATION_ONLY`；`pvl_benefit` 始终为 `NOT_ESTABLISHED`。真实独立身份、审阅、科学有效性与推广仍需外部证据。未知材料不会被程序生成补齐。
