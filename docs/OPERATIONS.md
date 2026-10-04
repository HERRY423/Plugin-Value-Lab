# Real-study operations / 五步之后，如何做真实评估

The core workflow is [pair, freeze, recompute](../README.md). For optional capabilities, use the [advanced guide / 高级指南](history/ADVANCED.md).

## English operating guide

For L1 community workflow candidates, the L2 offline GitHub Action, and L3 RO-Crate evidence export, use the [workflow delivery guide](../examples/community/README.md). Module entry points preserve the frozen main CLI and SDK. Community acceptance, package publication and scientific replication remain separate gates.

Start with the [synthetic tutorial](START.md). For a real study, define the task, plugin version, outcome rules, negative controls, comparison conditions and budget before collecting results. Freeze the plan, retain independent WITH/WITHOUT sessions and original failures, then evaluate supplied records and read the usage card. Repeated prompts in one chat do not create independent arms. Cost, plugin loading, missing baselines and human review remain unknown when their records are absent.

For existing artifacts, `pvl check`, `pvl aggregate` and `pvl verify` avoid creating a plugin study. Use `pvl --help` and each command's `--help` for inputs. An analysis result supports the declared computational check, not general biological correctness. Preserve old outputs and use fresh directories for revisions.

For optional local dependency rechecks beside an existing usage card, see the [dependency recheck contract and runnable fixture](history/EVIDENCE-DEPENDENCIES.zh-CN.md). It identifies affected paths, retains unchanged historical checks with reasons, and keeps replay, rescoring and new execution separate. Unknown impact widens rechecking; the original whole-card policy remains the default.

### Prospective sample-size guidance

For prospective sample-size guidance, run `python scripts/value_lab.py plan-use examples/sample-size-plan.json --output <new-directory>`. The example uses assumed variances, not real study evidence. Review `PLAN.md`, replace the target effect/variance source/sampling assumptions, and copy the reviewed `sample_size_plan` into `suite.policy.power_plan`. Existing `suite-check` and MCP `validate_value_suite` expose the current design's shortfall before data collection. See [the sampling and confidence-interval methods](METHODOLOGY.md#plan-task-counts-and-repetitions-before-collection). Planning is local and does not authorize model calls.

### Native eval budget gate

The [v0.9.0 dated maintenance and paid-execution addendum](history/MAINTENANCE-AND-PAID-BOUNDARY-20261003.md) distinguishes the original release assets from later source. Current accounting reports `provider_cap_verified: false` and `paid_launch_authorized: false`; it does not enable paid launch. Unknown spending remains UNKNOWN, and cancellation/disconnect/retry must reconcile the original attempt before another dispatch.

The official `--max-cost-usd` parameter is an estimate checked after requests; it cannot bound one in-flight request. The observed $0.114 / $0.09 overrun is retained in [historical evidence](history/VALUE-EVIDENCE-20260929.zh-CN.md). PVL now refuses both direct workbench and sandboxed native paid launches with `BUDGET_BOUNDARY_UNAVAILABLE`, before credentials are read for a model request or a model process starts. Legacy frozen plans and UI/API consent cannot bypass this gate. Exported commands are planning material, not budget-safe execution instructions; manually running one outside PVL bypasses its gate.

This deliberately leaves paid native execution unavailable. A future transport must intercept every model/judge/tool charge, verify an upper bound before each request, reserve it durably against a shared task budget, serialize concurrent admission and keep uncertain reservations until reconciled. Restart, retry and additional study IDs must not reset that budget. Request counts, token limits, reduced estimates and process cancellation alone do not establish a dollar cap. Offline inspection/import remains usable, and historical unsettled costs stay unknown.

The local accounting component is now implemented in `value_lab.request_budget.RequestBudget`: exclusive ledger creation, immutable task identity, integer USD micros, SQLite transactional admission, persistent uncertain reservations, non-dispatching idempotent recovery, append-only history reconciliation and terminal bound-breach reporting. Unknown historical liabilities block admission; native estimates never become settlements. Reconciliation is a trusted operator operation requiring evidence references, not authentication of those invoices. Use the same controller-owned ledger across every study/retry for a task; a new database does not authorize a new budget. This component is **not yet an integrated, provider-enforced paid transport** and does not unlock the native gate. The underlying HTTPS broker also checks that gate when called directly.

### Explicit Linux isolation alternative from Windows

If an existing Ubuntu WSL distribution has Python and bubblewrap, run `python scripts/check_wsl_boundary.py --distribution Ubuntu --output C:\\Test\\pvl-wsl-acceptance-new` from the checkout. The output must not already exist. This invokes the existing offline/online kernel acceptance checks without installing software or making provider calls. Inspect `acceptance.json` and retain failed attempts. Successful fixtures establish the tested Linux kernel/protocol boundary, not native Windows Hyper-V, actual Claude runtime acceptance, model availability or scientific validity. Moving a study to WSL changes its execution conditions and requires a new frozen Linux plan; the Windows launcher does not silently fall back or launch paid work.

### HPC compute-node acceptance

Core scoring and supplied-record analysis work on Windows, macOS and Linux. Scientific re-execution requires Linux (including WSL2) with working bubblewrap user, mount, PID and network namespaces. Slurm, PBS Pro/OpenPBS and LSF are submission integrations, not alternative isolation backends. Apptainer/Singularity, Docker and privileged execution are not automatic fallbacks. If site policy disables required namespaces, retain a blocked result and ask the cluster administrator for an approved execution node; PVL does not change site policy.

Use a checkout visible to the compute node and Python 3.11+ plus a site-provided bubblewrap supporting `--disable-userns`. Load any site modules yourself before submission. Put output on storage that will survive the allocation; account for quotas and scratch cleanup. Run as the ordinary cluster user. No model account, API key, patient data or provider call is needed by these manufactured probes.

```sh
export PVL_SOURCE="$PWD"
export PVL_RESULTS_ROOT="$PWD/work/hpc-acceptance"
mkdir -p "$PVL_RESULTS_ROOT"
# Choose ONE scheduler. Add your site's account and partition/queue flags.
sbatch --export=ALL examples/hpc/slurm.sh
qsub -v PVL_SOURCE,PVL_RESULTS_ROOT examples/hpc/pbs.sh
bsub < examples/hpc/lsf.sh
```

The examples request one node, two CPUs and ten minutes. LSF memory resource units/policies and PBS resource syntax may differ by site; review them before submitting. `PVL_PYTHON` may select an absolute Python executable (also export it via PBS `-v` if used). No modules, queues, accounts or cluster names are guessed. Each job runs both real boundary gates and retains `acceptance.json`, a SHA-256 manifest, raw logs and a `.tar.gz` archive. Receipts record only selected scheduler IDs/queue, node, OS/kernel, UID, bubblewrap version, namespace settings and process restrictions; review node names/paths before sharing externally.

Submission references: [Slurm sbatch](https://slurm.schedmd.com/sbatch.html), [OpenPBS qsub manual](https://github.com/openpbs/openpbs/blob/master/doc/man1/qsub.1B), [IBM LSF resource usage](https://www.ibm.com/docs/en/spectrum-lsf/10.1.0?topic=strings-usage-string). These define submission syntax; site compatibility still requires the actual probe.

Check the scheduler's terminal exit status **and** `acceptance.json`: both `offline` and `online` gates must say `PASS`. A killed job, missing receipt, missing binary, permission denial or nonzero exit is not a pass. A passing compute-node probe applies only to that node image, partition, user and time; rerun after policy/runtime changes and separately run the scientific execution gate with the chosen curated runtime. A login-node test, WSL result or hosted CI result cannot certify a cluster. At present no real Slurm/PBS/LSF cluster has been validated.

### Contributing and verifying CI

See the [contributor guide](../CONTRIBUTING.md), [security policy](../SECURITY.md), [API stability policy](API-STABILITY.md) and [data governance](DATA-GOVERNANCE.md) before preparing a real study or contribution.

From the source root, install `python -m pip install ".[dev,mcp,science,registry]"`, then run `python scripts/check_community.py`, `python scripts/build_marketplace.py --check`, `python scripts/check_feature_freeze.py`, `python scripts/validate_agent_plugin.py` and `python scripts/check_release_tests.py`. A clean checkout needs no generated copy. The release check rejects skips. Optional scientific fitting, data-scale, notebook installation and workflow-engine checks run separately in CI.

Maintain documentation and evidence only in the root `docs/` tree. Repository marketplace catalogs point to `./`, so Git installations use the canonical plugin directly. `python scripts/build_marketplace.py --package` generates the complete installable marketplace under ignored `build/marketplace/` and writes both marketplace and portable archives to `dist/`. `--generate` produces only that build tree; `--check` validates source catalogs and, if a build exists, rejects stale generated bytes. Artifacts include their documentation and evidence without symlinks or references outside the package. Never edit or commit generated copies. The builder removes only obsolete manifest-owned files whose old hashes still match, and refuses unknown files or modified obsolete files.

The [hosted workflow](https://github.com/HERRY423/Plugin-Value-Lab/actions/workflows/ci.yml) has mandatory Windows/Linux tests and Linux kernel/science gates, with retained evidence artifacts. A red gate remains a failure. The ephemeral Ubuntu runner explicitly loads the distribution's scoped bubblewrap AppArmor profile, consistent with [Ubuntu's administrator guidance](https://discourse.ubuntu.com/t/understanding-apparmor-user-namespace-restriction/58007); it does not turn off AppArmor globally or run probes as root. This runner setup is not permission to change an HPC site's security policy. New fixes need a green run on their exact commit before acceptance is claimed.

| Symptom | Next action |
| --- | --- |
| Output already exists | Preserve it and choose a new output directory. |
| `SIMULATION_ONLY` | Expected for the tutorial; collect real evidence for a real claim. |
| `INSUFFICIENT_EVIDENCE` | Read blockers and retain missing/failed observations. |
| `BUDGET_BOUNDARY_UNAVAILABLE` | Use export/import/offline analysis; paid execution needs a bounded transport. |
| `Operation not permitted`, userns or `RTM_NEWADDR` error | Preserve kernel logs; request administrator review of the compute-node policy. |
| No scheduler receipt / killed job | Mark acceptance incomplete; inspect scheduler logs and allocation limits. |

## 中文详细操作

文件处理与已有产物检查可直接使用[简洁 CLI / Python SDK](history/ENGINEERING-USABILITY.zh-CN.md)：`pvl aggregate`、`pvl check`、`pvl verify`，无需先创建插件研究。完整插件收益评估继续使用下方五步流程。

主路径固定为 `doctor → freeze → evaluate → usage-card → compare-studies`。首次使用只读 [START](START.md)，字段查 [CONTRACT](../CONTRACT.md)，不为第一份卡安装宿主或登记研究。

## 准备与冻结

Python 3.11+ 足以运行核心。`doctor` 检查本机可选宿主版本，不发起评估。需要宿主时再安装；[历史安装说明](history/INSTALL.zh-CN.md) 中的已安装状态与版本可能过期。

CLI 的机器 JSON 标准输出及 JSON 错误输出使用 ASCII 转义，管道消费者解析 JSON 后可完整恢复中文和其他 Unicode 字符，不必设置 `PYTHONIOENCODING`。磁盘上的 JSON、JSONL、Markdown 和 HTML 仍显式使用 UTF-8；此约定不改变 MCP 的传输协议或交互式文本显示。

真实研究先确定插件、任务、参考、成本口径和决策目标，再冻结 suite。相关任务变体共享 `cluster`，重复不是独立任务族。保留普通任务、插件可能无益的任务、合理拒答与不应拒答任务。两臂只改变被测插件，模型、宿主、授权数据、工具和预算相同；使用独立会话，记录实际加载与基线污染。

`freeze` 不采集运行，也不证明独立预注册。冻结后通过已授权宿主收集 `runs.jsonl`；费用、材料外发、权限和账号操作仍需相应授权。标准五步不自动执行采集，不能用示例代替真实观察。

针对“看懂示例但准备自己的评估太难”，先使用[限定的 pseudobulk 作者试跑材料](../examples/pseudobulk-author-pilot/RUNBOOK.md)：明确映射 AnnData 原始计数层及样本／供者／条件字段，核对配对设计，显式运行现有参考与验证入口，再检查真实宿主产物。所有科学确认仍由作者／审阅者提供。材料内的计时器保留失败、中断、求助、误报处理和复测准备；[PVL 有／无比较计划](../examples/pseudobulk-author-pilot/STUDY-PLAN.md)另行冻结，不能用被测插件的两臂结果代替 PVL 自己的价值验证。试跑辅助脚本属于交接材料，不增加正式 CLI/MCP/技能或评分类型。

## 评分、成本和使用卡

`evaluate` 与 `usage-card` 使用同一 suite、records、lock、cost-ledger，以及需要的产物和独立评分根目录。文件检查要有真实字节及摘要；失败、跳过、缺失基线、未知结果、人审未完成都保留。人工判据须由真实评审者判断；自定义执行检查须先审阅代码并限定可信评分根目录。

拒答判据只测是否作出正确的拒答决定，`allow` 不代表有效交付。任务应分别冻结交付规则（例如 `artifact_schema` 要求非空数值答案）与正确性规则；缺失或无效 decision 保持未知。命名标签允许用 `labels.aliases` 明确冻结合法别名，歧义及跨类映射会被拒绝；ARI/NMI 继续只比较划分。训练 ID 等仅在 `json_fields.unordered_paths` 明确声明时按无重复集合比较，不能把所有列表都当无序。配置示例见[文件验证契约](history/ARTIFACTS.md#frozen-semantic-variants)。

原生诊断分别展示 Skill 调用与读取候选文件内容。读取响应须完整且匹配冻结字节；有保留文件并核验原始摘要时，只允许换行符规范化，不去除行号、空白、前缀或缺行。未观察到支持的机制仍是使用未知；读取内容也不证明实际执行、收益或满足严格修复链。泄漏判断另需适用的访问观察；当前新增的受控 Python 访问 hook 与阻断实验只服务种子验证，不能宣称覆盖真实宿主或隔离恶意插件。

质量差是启用减基线，两边满分不意味着增益。默认质量目标要求正质量差与既定下限；只有预先选择效率目标，才按质量不降且完整成本下降判读。不得看完结果换目标以取得通过。

每成功成本包含失败、重试和分摊开销；零成功时未定义，未知费用不填零。分开记录模型／工具费用、计时折算人工成本、供应商估算和实际结算。原生整批估算不得重复加进逐次费用。

`usage-card` 输出 `USAGE.md`、`card.json` 和单页 `ENVELOPE.html`。每个 `cluster` 一行：质量差、harmed pairs、over-refusal、每成功成本、执行失败率、样本量。冻结前可用 `task_families` 声明任务族目录；未运行的族标灰，未列任务也不在包络内。

| 主结论（颜色仅辅助） | 含义 |
| --- | --- |
| 基线优先（蓝） | 已有证据支持当前目标先用基线；没有额外收益不等于插件有害。 |
| 观察到退步／风险（红） | 退步指受损配对或质量下降；风险指关键失败、执行失败或误拒答等观察，不自动归因于插件。 |
| 证据不足（黄） | 有观察但证据不足、合成或收益未明确；尚未证明收益不等于证明没有收益。 |
| 限域试用（绿） | 满足冻结范围的质量、配对、成本、身份及必需指标条件；误拒答也可经事前明确声明和复核为不适用。 |
| 尚未测试（灰） | 没有运行观察；未测不是无风险。 |

新研究可在冻结前声明 `usage_scopes`（不重叠的完整任务族、理由、最低任务族数和完整配对数），分别验收局部范围；默认仍使用整项研究门槛。整项研究 verdict、阻断和所有负向证据继续保留，局部结论仅限声明范围。禁止事后挑选成功案例；身份、锁、会话重复、共同成本等问题不能靠缩小范围绕开。字段示例见[使用范围契约](history/P2-REUSE-GUIDANCE.zh-CN.md#冻结范围与指标适用性2026-09-26)。

`metric_applicability` 区分误拒答指标的必测与不适用。报告分别显示已测、应测未测、因缺失而未知、不适用；不适用保留原因与接受复核记录，数值仍为 null，不填零。质量、成本、执行完整性等原有要求不会因此取消。

`diagnose STUDY` 自动读取该目录的 `cost-ledger.json`，与 `usage-card --cost-ledger STUDY/cost-ledger.json` 使用同一材料。无文件时仍按成本未提供处理，坏文件会报错，不忽略账本继续给建议；其他名称的账本使用已有 `usage-card --cost-ledger` 显式指定。

卡绑定冻结的 `plugin.sha256`（显示为 `plugin_sha256`）、明确的 `conditions.host_version`、`model_version` 及条件／记录摘要。别名不等于模型修订；不改写旧 suite 补身份，缺失保持未知，新研究重新冻结。

插件字节变化即使版本不变也使卡失效；宿主、模型、工具、环境、配置、预算、任务分布、规则或新失败／成本／复核证据变化时重新核验。哈希不认证真实执行；颜色不是新统计检验。[历史接口契约](history/WORKFLOW-CONTRACT.md) 保留更细的兼容字段。

可选的[本地依赖复核](history/EVIDENCE-DEPENDENCIES.zh-CN.md)把重新核验细化为逐路径待办：声明完整且可核对时，保留未受影响的旧产物检查并记录理由；影响不明时扩大复核。旧产物重放、旧产物重评分、模型／科学计算重执行分别记录；检查通过不会自动更新整卡建议。

需要跨会话继续研究时，使用[本地决策恢复](history/DECISION-RECOVERY.zh-CN.md)：保存原冻结方案、执行尝试、原始产物、解释历史、未知结果与未结算费用，并从已核验材料生成下一步。重复读取不新增观察；外部调用结果未知时先核实原请求。此状态层不启动模型、科学计算或付费调用。依赖复核和恢复报告使用完成标记与事务式交付，中断暂存材料保持可查。

## 比较与修复

跨会话继续使用旧结论前，运行[恢复、解释和适配器联合检查](history/CONTINUITY-DELIVERABLES.zh-CN.md)：先核验历史检查点，再绑定本次规则、策略、依赖与需要的宿主能力。分别给出重评分、重新决策和补证据动作；匹配环境不会自动激活待复核建议。

目标是减少人工、现金或完整工作负担时，使用独立的[科学约束下负担决策](history/BURDEN-DECISION.zh-CN.md)：事先冻结目标、行动差异阈值、硬上限和隐私要求；通过完整科学检查后再比较。保留准备、复核、返工、失败以及 PVL 自身开销，微小差异不自动触发迁移。未启用此模式时仍采用原最少插件规则。

长期会话的本地日志可使用[宿主能力契约与增量采集](history/HOST-CAPABILITIES.zh-CN.md)：分别报告身份、用量、上下文与恢复证据，按完整事件续读并保留不可覆盖的检查点。宿主升级或日志变化会阻断相关游标／结论，独立文件检查仍按原授权边界进行。

若目标是减少实验负担，使用[风险约束下的补证据](history/RISK-CONTROLLED-ACQUISITION.zh-CN.md)：先冻结错误概率上界、容许效用损失和独立实验单位，再比较分配方式。只有错误风险、有效决策比例及实验节省同时满足验收，才谈效率；预算耗尽但无法决定不计为收益。旧补测模式仍不提供统计风险保证。

规则、用途或展示发生变化时，使用[解释修订与建议生命周期](history/INTERPRETATION-HISTORY.zh-CN.md)：保持原始观察不变，分别记录新判断、新决策和新展示。最近报告不会自动替代当前建议；旧建议需明确标记待复核、不适用或由新建议替代。历史失败、未知费用及旧版原报告继续保留。

`compare-studies` 接收两份包含 `suite`、`records`、`lock` 及可选 `cost_ledger`、`context` 的 JSON。保留旧材料，修复后在新目录采集；实际插件摘要放 `context.plugin_sha256`，只改一个目标因素。缺上下文或同时改插件和模型时，接受不可归因结论。比较已有文件不创造新观察。

已有 `diagnose` 等专用命令保持兼容；BH 检查须由任务明确要求，不替研究者决定方法。原生采集与完整复测边界按需查 [历史原生复测契约](history/NATIVE-ANALYSIS-REPAIR.zh-CN.md)，冻结期不扩展这些路径。

原生修复比较已纠正失败与未知混淆：新研究可在 case 的 `repair` 中预先声明 `kind` 和命名空间 `skill`，分别验收执行、触发、科学产物修复，并保留触发负对照。未声明的旧契约继续使用严格产物规则，不能事后改类型获取通过。`repair_record.process` 可保存诊断、假设、改动与失败复测；种子恢复和作者声明不升级为真实修复收益证据。字段和证据边界见[分类验收说明](history/NATIVE-ANALYSIS-REPAIR.zh-CN.md#分类修复与作者过程记录2026-09-26-修正)。

| 问题 | 下一步 |
| --- | --- |
| 找不到脚本或输入 | 回到含 README 的解压根目录。 |
| 输出已存在 | 保留原尝试，统一换新输出目录。 |
| SIMULATION_ONLY | 合成教程的正常结论，不能据此推广。 |
| INSUFFICIENT_EVIDENCE | 先读 blockers，不删失败求通过。 |
| 缺成本、版本、参考或人审 | 保持未知；补真实证据、新建修订。 |
| 宿主出错或调用缺记录 | 先区分宿主与插件；缺记录不等于没使用，付费不自动重试。 |
