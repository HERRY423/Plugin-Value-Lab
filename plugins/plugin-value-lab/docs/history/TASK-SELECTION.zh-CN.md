# 从插件评分到任务方案选择（0.8.0，限定范围增量）

2026-09-30，负责人明确要求实现引用对话中的“为一个任务选择最小必要方案”。这次新增的是证据选择能力，不将其包装成普通修错；范围记录于 `docs/feature-freeze.json` 的 `task_selection_scope_change`。沿用 `plan_plugin_use` / `plan-use`，不增加 MCP 工具，不自动安装、运行或付费。

## 对研究者的交付

研究者描述任务、材料及可用结果，Agent 读取已有上下文与材料，提出会改变方案选择的因素。例如原始计数或变换后数据、是否配对、供者重复是否可用、探索还是计算复核。**因素及适用条件必须由任务证据和研究者判断确定，选择器不从“单细胞分析”等关键词推断科学适用性。** 缺失信息保留未知，不要求研究者填写 JSON。

Agent 应列出每个阶段的原生能力、已有脚本／流程和确有必要的插件能力。一个插件可以只承担一个阶段；同一插件参与多个阶段只计为一个依赖。输出包含：建议的阶段能力、声明的使用条件、必须保留的人工复核、失败方案、尚未验证的更简单方案、完整成本和原始验证收据。

以下是本地回归中的**制造案例，不是现实插件表现**：原生与已有脚本未通过整理判据；插件 A 的整理通过，但其差异表判据失败；A 整理后交给已有脚本核对，且完整流程检查通过。只有最后一个组合有完整匹配证据时，才可能成为有支持的方案。删掉该组合的完整试验，即使 A 的整理和脚本的表核对在其他记录中通过，也只能提出补测，不能合成一个成功结论。

## 最小的定义与证据范围

选择政策固定为先最少新增插件，再最少全部插件。它是**达到预先指定交付与质量门槛后的依赖数量选择**，不是综合评分榜，不声称最低费用或最快速度。所有成本类别仍需完整；缺失成本不当作零，实际测试总成本不外推为下次任务费用。已安装不证明当前可调用，输出始终 `ready_for_execution=false`，执行前仍由宿主检查工具及具体授权。

| 结果 | 含义 |
| --- | --- |
| `MINIMUM_IN_DECLARED_CATALOG` | 在完整声明目录、精确任务和提交观察范围内有唯一最小支持方案；并非全球最优或泛化保证 |
| `SUPPORTED_OPTION_MINIMUM_UNRESOLVED` | 有局部支持的方案，但更简单／同样简单的候选、基线覆盖或未绑定研究仍有缺口 |
| `CHOICE_REQUIRED` | 多个同样精简的支持方案并列，不用候选 ID、输入顺序或未知费用强行排序 |
| `EVIDENCE_REQUIRED` | 暂无完整支持方案，保留明确的补测缺口 |
| `SIMULATION_ONLY` | 只有合成示例，`selected_plan_sha256=null`；演示通过列表不能用于真实采用 |

每阶段缺少原生能力或已有脚本／流程候选，会产生 `baseline_coverage_gaps`。不要求凭空制造一个脚本；缺口意味着最小性尚未建立。候选适用条件不符与观察失败分开；未知条件不能变成不适用来排除竞争者。并列、冲突、负结果、未知结果均保留。未知的较复杂方案仍展示在完整目录内，但不阻止已支持较小方案的目录内最小性。

## 输入契约

在旧工作流上下文中添加 `task_selection`，且 `intent="choose"`、无显式 `selected_plugin`。显式指定服务、评估请求和管理请求仍走原路径，不被自动替换。

`task_selection` 必须包含：

- `format: "pvl-task-selection-1"`。
- `task`：`id, summary, facts, inputs, conditions, stages, cases, integration_case_ids`。`facts` 是有类型的标量或未知 null；`inputs` 是输入快照的 SHA-256 映射；`conditions` 沿用现有模型、宿主、工具、环境、预算契约，并要求明确 `model_version`、`host_version`。快照及版本均为提交绑定，不认证真实访问。
- `stages`：每项 `id, summary, depends_on, decision_factors, case_ids, required_reviews`。按依赖拓扑排序，每个案例必须且只能属于一个阶段或整合检查。多阶段任务必须有完整流程的整合案例；其科学充分性仍需研究者审核。
- `components`：每项 `id, name, kind, version, sha256, installed`，可选 `requires_components: [组件ID]`。种类为 `native|script|workflow|plugin`；前三者描述已有能力。插件安装状态可为 true、false 或 null。脚本／流程依赖的插件必须显式列出，选择器展开完整依赖、共享依赖只计一次，并拒绝缺失或循环依赖；不允许包装成“已有流程”后省略插件数量。本工具不自动审计任意代码，依赖清单的真实完整性仍由宿主与研究者确认。
- `options`：每项 `id, stage_id, component_id, capability, requires, required_reviews`。它表示一个组件在一个阶段的具体能力，而非整个插件的通用适用性。`requires` 必须覆盖该阶段的全部 `decision_factors`，每个因素给出可接受标量值列表；布尔 true 不等于数值 1，null 不是通配符。
- `policy`：`objective="fewest_new_plugins_then_total_plugins"`、`max_new_plugins`、`quality_floor`。条件、目录、判据和决策政策在收集前固定。
- `studies`：完整原始 `{suite, records, lock, cost_ledger?}`，不接受使用卡或预计算“成功”摘要作为证据。

上限为 8 阶段、16 组件、32 阶段能力、32 研究和 256 个完整组合。超过上限明确拒绝；不能截断搜索后报告找到最小值。没有记录的组合保留 UNKNOWN。

准备阶段可先提交 `studies: []`：同一入口会返回完整候选方案、`plan_sha256`、`catalog_sha256` 和所缺检查，供 Agent 编制新试验。它不会把空证据变成推荐。随后将返回绑定写入新的 suite，冻结后收集真实记录，再通过同一入口重算；技术配置由 Agent 负责。

## 冻结绑定和已有评估引擎

`catalog_sha256` 是 `task_selection` 去除 `studies` 后的规范 JSON 摘要。每个完整方案摘要是 `{steps: [按阶段顺序的完整 option], components: [展开依赖后按 ID 排序的身份对象]}` 的摘要；组件身份含 `id,name,kind,version,sha256,requires_components`，最后一项规范化为排序列表，缺省为空列表。声明目录、任务输入、设计、候选能力、依赖、安装观察、选择政策发生变化会使旧绑定不匹配。不要修改旧研究来补这些字段；旧研究保持原样，新选择需要新的前瞻绑定和观察。

用于选择的每份冻结 suite 需包含：

```json
{
  "task_selection": {
    "catalog_sha256": "<冻结目录摘要>",
    "arms": {"with": "<完整方案摘要>", "without": "<完整基线方案摘要>"},
    "treatment_component": "<本次被增减的插件组件 ID>"
  }
}
```

两臂仍遵守已有 WITH/WITHOUT 插件语义：被测试插件存在于 WITH 完整方案，不存在于 WITHOUT 方案，且 suite.plugin 的名称、版本和内容摘要匹配。原生能力／脚本／已有流程以真实 WITHOUT 基线进入比较，**不能把它们伪装成已加载插件**。当前实现不把两个没有插件处理差异的任意观察强行转换成 WITH/WITHOUT；独立方案试验格式不在本次范围内。多处方案因素变化也不能归因成单插件因果收益。

suite 的所有 cases、条件及质量底线必须匹配任务契约。每条原始 record 还需 `selection_plan_sha256`、`observed_components: {组件ID: 内容摘要}`、`input_snapshot`，与所属完整方案和任务输入一致。缺少这些实际采集字段必须 UNKNOWN，不能依据计划事后推填。复用会话、重复研究、缺少原计划记录、陈旧锁、参考漂移和比较成本缺失都阻止推荐。未绑定研究不会悄悄消失。

每份研究通过既有 `core.evaluate` 重算，保留完整配对矩阵、文件验证、失败、成本及原有科学门槛。推荐需全流程所有计划运行成功，且满足冻结的退步限制；不能用平均分掩盖阶段或整合失败。失败与成功的同方案证据冲突时不推荐。报告内 `observations.stage_status` 保留阶段结果，但不会把不同试验的阶段结果拼成完整流程成功。

计划的 `studies.provenance` 保留 suite、records、cost ledger 的摘要，逐方案 `observations.verification_receipts` 保留实际验证收据。文件与参考材料通过已有受控 MCP 授权目录读取，计划过程始终禁止执行 `executable` / `exec`。已有 CLI、旧路由及先前交接边界保持。

## 接入与可复现演示

MCP 使用原有 `plan_plugin_use(context, artifact_root=None, verifier_root=None)`。目录参数只能缩小宿主授权范围；参见 [MCP 文件交接](ARTIFACTS.md#controlled-mcp-file-handoff-080)。Agent 负责构造上下文、收集并绑定真实证据、解释矩阵，不把技术表单交给研究者。

已有 CLI 增加目录参数：

```text
python scripts/value_lab.py plan-use context.json --artifacts collected --verifiers scorer-only --output new-plan
python examples/task-selection/demo.py --output NEW_DIRECTORY
```

第二条命令生成制造的 JSON/CSV 文件、五份配对记录和九个方案的比较，并明确输出 `SIMULATION_ONLY`。没有模型调用、真实插件执行、非作者参与或科研有效性验证。生成的 `plan/PLAN.md` 可阅读，`plan/plan.json` 保留完整方案、阶段结果、成本、未知项及摘要。保留旧输出，使用新的目录。

这次实现闭合了“任务定义→候选完整方案→原始证据重算→最小依赖方案或明确缺口→复核与宿主交接”的本地工程路径。它没有证明科研人员更省时、错误采用更少或真实净收益；这些仍需前瞻、非作者的真实任务比较。

## 序贯补证据

2026-09-30 的第二项明确范围授权实现了“只补能改变选择的证据”。在既有规划上下文中同时提供 `task_selection` 和 `evidence_acquisition`，入口仍为 `plan_plugin_use` / `plan-use`。新增 `value_lab.evidence_acquisition`；默认工具数量、接口参数、版本及评分规则不变。

### 选择什么检查

先排除声明条件明确不适用的候选，再在尚未解决的候选中找出插件依赖数最少的一层。已有完整确认支持的方案时，只继续考虑可能取代它或与它并列的候选。若更简单候选仍未知，不因某个更复杂方案已通过就宣称最小性成立。

每个预先定义的检查绑定两个完整方案及一批决策判据。规划器根据**实际重算的批次结果**更新当前候选，并显示 `pivotal_case_ids`、`observed_gate_outcomes`、受影响方案和 pass/fail/unknown 三种结果的行动差异。相同方案、判据及输入已检查的门槛不因换一个检查 ID 就重新计为信息。费用排序固定为“整批预估费用上限 ÷ 当前可能改变去留的方案数”，同值保留并列；每次只选择一个返回批次。

这是一条可审计的确定性启发式，**不是测量得到的成功概率、预期信息增益或全局最优采样算法**。它不声称预测哪种结果更可能发生，也未证明同等错误选择风险下的真实节省。所有列为相关的检查都只具有条件性的行动影响；声明的科学判据是否足够仍需研究者判断。若完整确认比继续筛选便宜，规则也允许直接进入确认阶段。

### 母协议、批次和预算

`evidence_acquisition` 的字段为 `protocol, protocol_sha256, batches`。母协议结构如下：

```json
{
  "format": "pvl-evidence-acquisition-1",
  "catalog_sha256": "<task_selection 空记录规划返回的目录摘要>",
  "selection_rule": "frontier_gates_then_confirmation_v1",
  "stopping_rule": "stable_choice_or_budget_or_no_relevant_check_v1",
  "budget": {"max_usd": 10, "max_batches": 10},
  "checks": [
    {
      "id": "paired-boundary",
      "phase": "screening",
      "suite": "<实际为完整 suite 对象，绑定 WITH/WITHOUT 完整方案>",
      "inputs": {"screening_dataset": "<真实输入快照摘要>"},
      "decision_case_ids": ["design-boundary", "negative-control"],
      "cost_upper_bound_usd": 0.1
    }
  ]
}
```

`protocol_sha256 = suite_digest(protocol)`，应在观察前独立保留。允许 1–64 项检查、0–64 批上限。每份 suite 都遵守已有验证规则，包括任务族数要求；不能为了声称“只测一项”放松 `min_clusters` 或负对照。`decision_case_ids` 必须覆盖整批所有 cases，不能将负对照列在矩阵里却不参与决定。计费与独立性的科学契约仍由原引擎检查。

初始 `task_selection.studies` 必须为空。现有研究继续由原选择器处理；不得事后把它们重命名为本次预留确认。新协议可分批恢复：每次保留此前全部批次，读取并重算实际观察来选择下一批。序贯补证据不自动迁移旧研究；跨输入桥接使用下述独立的前瞻桥接模式，不能与本模式混合提交。

`next_batch_options` 返回并列可选项，每项含 `check_id, suite, lock, reserved_usd, planned_runs`。其中 suite 新增 `acquisition_batch`，绑定母协议摘要、此前完整历史摘要、批次序号及阶段。宿主在执行前保存选中批次，随后向 `batches` 追加：

```json
{
  "plan": "<原样保存的一个 next_batch_options 对象>",
  "result": {"records": [], "cost_ledger": "<实际完整成本账本>"}
}
```

这里的空 records 仅示意结构，提交后会因缺行停止。尚在运行的批次使用 `result: null`，保留上限预留并返回 `WAIT_FOR_BATCH`，不可启动下一批。真实记录必须逐行绑定 batch suite 摘要、完整方案、观察到的组件和实际输入快照；不能由预期执行计划回填观察身份。记录结构及成本账本沿用既有引擎。

每个已启动批次保留全部计划运行、两臂、失败和重试成本；未启动的检查保留在 `never_started_check_ids`，并不算已运行矩阵中的缺失行。重新锁定删减的批次、重排非并列检查、跨批次复用 session、改写后续批次已绑定的历史均拒绝。完整成本已知时累计两臂含设置、重试、判断、人工与其他项目的成本；未知时预留整批上限并停止；超额保留实际超额，不截断到预算上限。它不会替外部服务执行硬计费限制，费用上限也不构成付费或数据发送授权。

摘要和顺序检查仅支持一致性审计，不认证预注册时间、真实执行、参与者身份或从未查看确认集；最后一批及整份历史应由宿主保留于独立记录中，不能依赖调用方可改写的 JSON 证明“没有删掉整次调用”。

### 筛选、确认和停止

筛选数据摘要必须与任务确认输入不重叠，筛选案例 ID 及除 ID/cluster 外的内容摘要不能与确认案例重复。确认用完整任务 cases、输入和原条件，保留所有阶段与整合检查。改名复制原案例不能作为独立确认。摘要隔离只能检查声明层面的重合，真正材料隔离仍依赖宿主与研究者；不得把这些材料预先暴露给被测候选来优化答案。

筛选通过只保留候选；筛选失败只从本次筛选名单中排除，不能据此宣称该方案在完整科研任务上失败。首次启动确认后关闭筛选，确认结果不再反馈生成新的筛选实验。所有确认仍经真实文件检查和完整质量、成本、方法学门槛。输出的支持范围始终是“筛选存活候选中的完整确认观察”，不升级为原目录全部方案的最小性；若出现前后冲突就返回 `REVIEW_CONFLICT`。

| 状态 | 动作 |
| --- | --- |
| `NEXT_BATCH` | 在并列选项中选一批，保存锁后采集；不是自动执行 |
| `STOP_CHOICE_STABLE` | 观察中不再存在更简单或同样简单的未解决存活候选；停止追加，保留范围限制及并列 |
| `STOP_BUDGET` / `STOP_BUDGET_OVERRUN` | 预算不足、批数耗尽或观察超额，停止；可能没有任何推荐 |
| `STOP_NO_RELEVANT_CHECK` | 剩余预定检查不影响当前候选，停止并保留未解决方案；不是成功 |
| `WAIT_FOR_BATCH` | 等待原批次，保留预留，不重复购买 |
| `REPAIR_EVIDENCE` / `REVIEW_CONFLICT` | 先恢复完整记录／成本或复核冲突；不得补写成功或跳过失败 |
| `CLARIFY_TASK` / `REPAIR_CATALOG` | 先核实适用因素／安装观察或修复候选覆盖；协议变化需新建前瞻设计 |

`evidence_status=SIMULATION_ONLY` 时，无论模拟流程是否达到停止条件，`selected_plan_sha256=null`，不产生真实采用建议。`choice_stable` 也不会为真。研究者仍需履行保留的任务复核要求，宿主仍需检查实时工具可用性。

不对普通置信区间进行“反复看显著就停”，也不输出时间一致的置信序列或保证；`statistical_guarantee=NONE`。本次解决的是受约束的批次规划与审计，错误选择风险保持、净节省和科研有效性需要独立前瞻验证。

可复现合成演示：

```text
python examples/task-selection/acquisition_demo.py --output NEW_DIRECTORY
```

演示包含 5 个设计边界筛选配对和 5 个完整确认配对的预定选项，根据制造结果只启动 5 个筛选批次及 1 个确认批次，共 26 个计划运行；另外 4 个完整确认检查未启动。直接运行全部 5 个完整确认配对需要 30 个计划运行。这只是可重放的分支与计数示例，不能外推为真实节省比例，亦不能说明减少 4 行保持了相同错误风险。`trajectory.json` 展示每次选择，`plan/PLAN.md` 展示最后的停止和剩余检查，`context.json` 保留完整母协议和批次历史。

## 证据迁移与桥接

2026-09-30 的第三项明确范围授权新增 `value_lab.evidence_bridge`。入口仍是 `plan_plugin_use` / `plan-use`，提交空记录的目标 `task_selection` 与 `evidence_bridge`。宿主负责整理这些字段，普通用户只需说明新任务和新数据。此模式不修改严格匹配的使用卡、结论引用或旧记录重评分规则，也不增加默认工具或提高版本。

### 先判断变化，再决定补什么

系统逐项比较旧任务与新任务，重算旧方案在指定研究中的真实文件证据，并核验双方输入。不是让调用方填写一个“相似度足够高”或任意可忽略因素名单。

| 变化 | 处理 |
| --- | --- |
| 仅任务名称或说明变化，绑定材料与计算契约未变 | 保留原范围的重放，新增观察数为零 |
| JSON 编码变化或矩阵行及对应数值同步重排 | 用实际文件证明输入内容等价；仍需新执行才能判断插件行为是否等价 |
| 相同矩阵列、设计和目标下换数据、行数、稀疏程度，或改变执行环境 | 生成独立目标桥接协议，保留原完整方案和原对照 |
| 配对设计、输入种类、推断目标、特征列、评分规则、组件内容、模型、宿主、工具或其他未支持因素变化 | 新建研究，旧成功不能解除边界 |
| 文件、身份、成本、执行绑定或参考答案缺失／不符 | 保留未知，先修复证据；不自动当成失败或成功 |

第一版刻意只支持 `pvl-paired-matrix-bridge-1` 这一明确矩阵契约。它不是所有科研格式的通用迁移器；也没有跨模型或跨插件版本的桥接许可。声明因素只能用于任务约束，不能代替真实材料与研究者复核。

### 真实输入与受限参考重建

双方任务只含一个具名输入，其内容摘要绑定授权产物目录内的文件。文件结构为：

```json
{
  "matrix": {
    "row_ids": ["sample-1", "sample-2"],
    "columns": ["feature-1", "feature-2"],
    "values": [[1, 0], [2, 3]]
  },
  "context": {"paired": true, "input_kind": "raw_counts", "goal": "computational_audit"}
}
```

任务 facts 必须明确 `paired, input_kind, goal`，值与文件 context 一致。双方完整 context 与列身份必须相同。矩阵检查沿用已有变形验证器，验证唯一行列身份、数值和形状；拒绝重复 JSON 键、摘要漂移、超限或越界文件。`data_scale` 若提供，必须是实测行数整数；`sparsity` 若提供，必须等于实际零值比例。行数不是推断独立单位数，配对声明也不证明真实实验设计正确。

换数据时只允许重建 `artifact/json_fields` 的三个明确输入派生参考：`counts` 必须等于实际矩阵，`sample_ids` 必须等于实际行身份，`input_snapshot` 必须等于实际输入摘要。分别核验旧、新两侧后，才允许忽略这些参考值的差异来比较规则。阈值、权重、其他参考、阶段与整合判据仍须原样保留。即使参考值未变，也会检查是否误把旧矩阵答案带入新任务。任意“期望正确结果”都不能借这个通道重新定义。

编码或行顺序等价只复用输入身份／内容检查。哈希与确定性变换不能证明任意插件不依赖输入顺序，更不能证明科学结论正确；这类新字节输入仍生成目标执行协议。

### 保留旧证据，创建新的目标范围

`evidence_bridge` 必填字段：

```json
{
  "source_selection": "<含全部旧 suite、锁、原始记录和成本的完整选择对象>",
  "source_sha256": "<suite_digest(source_selection)>",
  "source_study_sha256": "<指定原始 suite 的摘要>",
  "source_plan_sha256": "<该研究实际一臂的完整方案摘要>",
  "contract": {"format": "pvl-paired-matrix-bridge-1", "input_key": "counts"},
  "contract_sha256": "<suite_digest(contract)>",
  "source_material": {"path": "old-input.json", "sha256": "<旧任务输入摘要>"},
  "target_material": {"path": "new-input.json", "sha256": "<目标任务输入摘要>"}
}
```

对象占位字符串仅用于说明，实际提交必须使用结构化对象。指定方案须在该次原研究中支持，且没有其他旧观察冲突或适用性阻断。方案与对照在目标数据上也必须符合声明适用条件；例如新行数超出任一臂的适用范围，就需重新设计研究。系统返回旧验证收据，但不会改写或重新标记旧研究为目标观察。

`proposed_protocol` 与 `proposed_protocol_sha256` 绑定完整旧证据、原研究、原方案、目标目录、契约及差异摘要；协议含新 suite、锁、目标输入摘要和计划运行数。宿主在执行前独立保留这些内容，然后收集目标数据上的新两臂运行。完整目标 cases、运行重复数、各阶段、整合检查和成本要求全部保留。它减少的是其他候选的重复验证，不通过删减该方案的任务完整性检查换取“通过”。

回传原样协议及其摘要，并附原始 `records` 和完整 `cost_ledger`，放入可选 `bridge_study`。旧执行 session 或旧产物路径不得充当新目标观察。最终目标选择报告只用这份新研究重算；未测替代方案仍为未知，不继承旧目录的最小性。

| 状态 | 含义 |
| --- | --- |
| `SAME_SCOPE_REPLAY` | 原范围可重放，没有新增观察或新采用结论 |
| `INPUT_EVIDENCE_REQUIRED` / `SOURCE_EVIDENCE_REQUIRED` | 先恢复实际输入、对应参考或旧研究支持 |
| `NEW_STUDY_REQUIRED` | 变化超出契约，需要新研究，不能提交桥接结果绕过 |
| `BRIDGE_REQUIRED` | 已提出绑定目标范围的协议，尚未执行 |
| `BRIDGE_EVIDENCE_REQUIRED` | 新观察、成本、身份或文件不足，仍未知 |
| `BRIDGE_REJECTED` | 目标观察未支持原方案，旧成功不能覆盖失败 |
| `TARGET_OBSERVATION_SUPPORTED` | 该目标输入的完整观察支持；不代表其他输入、候选最小性或科研有效性 |

`old_adoption_claim_transferred` 与桥接层 `minimum_established` 始终为 false。合成源或合成桥接导致 `SIMULATION_ONLY`，`target_plan_supported=false`。没有自动运行插件、模型或外部服务；研究者复核要求保留。摘要和路径检查不认证预注册时间或真实新执行，另存旧产物后虚构新记录不能仅靠哈希排除，宿主仍需保留可信执行来源。

可复现演示：

```text
python examples/task-selection/bridge_demo.py --output NEW_DIRECTORY
```

演示构造同列、同设计下从两行到四行的新矩阵，输出 `proposal/PLAN.md`、保存的源承诺和 `observed/PLAN.md`。独立桥接为一个完整方案及对照的 6 个计划运行，而不是重跑源目录全部方案。新文件和新记录全部人为制造，结果明确标为 `SIMULATION_ONLY`；这证明本地协议和验证链可运行，不证明真实科研迁移、真实节省或错误风险保持。
