# Plugin Value Lab

**从研究任务与背景识别缺少的方向，设计下一步验证；选择合适能力，再用实际证据评估插件增益。**

版本：`0.4.0-alpha.1`。本项目受 [Claude Code Plugin evals](https://code.claude.com/docs/en/plugin-evals) 启发，提供本地证据完整性检查、成本账本、人工复核和明确的结论边界。它面向通用插件，附带科研审阅教学案例，并与 [Plugin Management](plugin://plugin-management@openai-curated-remote) 的发现、连接和管理流程互补。

已适配 [Agent Plugins 1.0.0](https://agent-plugins.org/specification)，并提供桌面端“添加插件市场”所需的市场结构。**当前电脑的来源填写 `C:\Test\plugin-value-lab`，Git 引用和稀疏路径留空**；添加后再安装 Plugin Value Lab。给其他用户请发送 `dist/plugin-value-lab-marketplace-0.4.0-alpha.1.zip`，解压后填写市场根目录路径。完整步骤、Python/MCP 运行条件与 Git 分发方式见 [安装指南](docs/INSTALL.zh-CN.md)。

插件能加载、技能被触发、任务完成得好、比基线更好、真实用户持续受益，是不同的问题。本工具生成可复查的局部比较，不提供商业价值或科学有效性认证。更完整的产品分析见 [设计说明](docs/DESIGN.zh-CN.md)，实际研究流程见 [评估协议](docs/PROTOCOL.zh-CN.md)。

## 从手头的任务开始

新增 **研究方向诊断**：安装后，直接请 Agent“结合我的研究背景，找出遗漏方向、替代解释和最值得先做的验证”。`research-directions` 技能引导宿主 Agent 阅读授权材料，提出具体方向和反证；本地工具核对证据引用、方向依赖、预算与时间，并保存可供研究者修正的计划。工作台提供结构检查、Agent 交接与修订比较。详见 [研究方向指南](docs/RESEARCH.zh-CN.md)。安装不会自动扫描资料或启动模型，结构检查也不会自行产生科学发现。

新结果回来后，可用 `research-followup` 或工作台中的“有了新结果”入口定位需重审的方向及下游依赖；它保留原计划，不把提交的结果自动判为成功。使用卡可通过 `team-card` 形成逐版保留的团队决定记录，绑定当前研究上下文、评测证据和实际声明的采用选择。见 [团队使用记录指南](docs/TEAM-RECORD.zh-CN.md)。

同版本增强：工作台现支持多规则校验与试评分、插件版本/模型变化比较、追加成本账本和不可覆盖的分析修订。产品版本仍为 `0.4.0-alpha.1`。入口与证据限制见 [评分、比较与成本指南](docs/ANALYSIS.zh-CN.md)。

新增评估工作台：

```powershell
python scripts/value_lab.py workbench --data .\work\workbench --port 8766
```

打开 `http://127.0.0.1:8766`。通过表单选择插件目录、模型、预算和任务，冻结后可启动真实 Claude 原生对照评估，查看日志、原始 JSON、失败、费用估计、报告和使用卡。打开页面、准备方案及模拟示例均不调用模型。真实执行仅在启动时授权；首版为只读工具与 MCP 模拟环境。原生汇总无法建立的逐次会话、加载和成本证据仍显示缺失，不自动宣称插件增益。详见 [工作台指南](docs/WORKBENCH.zh-CN.md)。

- “把这段会议记录整理成待办”：现有能力足够就直接完成，普通任务无需先评测。
- “我需要读取日历，但当前没有可用连接”：交给 Plugin Management 或宿主查找相关能力；等待中的连接不重复建议，已安装不等于已连接。
- “这个插件以后是否值得常用”：先明确采用问题，再比较相同授权材料、模型和预算下的结果，并生成有适用范围的使用卡。

`research-directions` 负责研究缺口与下一步验证；`use-plugin-well` 负责任务选择和使用指导；`assess-value` 负责比较设计与证据解释。Plugin Management 继续负责发现、连接、依赖、用户请求的权限管理与移除。两者没有强制依赖：这里通过宿主与本地交接文件配合，不会因一个分数自动安装、扩权或卸载。

需要保存决定时，先准备一个 [工作流上下文](examples/workflows/native-sufficient.json)：

```powershell
python scripts/value_lab.py plan-use .\examples\workflows\native-sufficient.json --output .\work\my-plan
```

输出 `PLAN.md` 和 `plan.json`，只记录下一步建议，不执行连接或任务。上下文里的连接状态是提交的观察；缺失、过期或仅由本地清单推断的状态仍需宿主核验。交接只包含公开能力关键词和确切插件引用，私有任务材料保留在本地。完整例子与来源说明见 [Plugin Management 互补指南](docs/PLUGIN-MANAGEMENT.zh-CN.md)。

## 先运行一个本地演示

核心只需 Python 3.11+，无需安装第三方库。以下 PowerShell 命令在源码目录执行；其他系统将第一行换成对应目录。`python` 应指向准备使用的 Python 3.11+ 解释器。

```powershell
Set-Location 'C:\Test\plugin-value-lab'
python scripts/value_lab.py doctor
python scripts/value_lab.py demo --output .\work\my-demo
```

打开 `work/my-demo/report.html`，或阅读同目录下的 `report.md` 和 `report.json`。演示同时保存方案、模拟运行和冻结文件；结论必须为 `SIMULATION_ONLY`。**所有演示观测都是生成的，没有调用模型，没有真实用户或人工计时。**

输出目录应为空或尚不存在。下一次演示请换目录，保留前次材料。`doctor` 显示解释器、可选 MCP 依赖和本机 Claude 命令信息；这些检查不代表宿主已加载插件或完成原生评估。

## 评估自己的插件

创建一个带教学用例、没有任何观测的新研究：

```powershell
python scripts/value_lab.py init --output .\work\my-study
```

编辑生成的 `suite.json`：填写被测插件与版本、实际模型与宿主、可用工具、环境、预算、任务和验收规则。默认 `evidence_type` 是 `synthetic`；只有计划收集实际记录时，才在冻结之前设为 `local` 或具有相应来源的 `external`。`external` 是来源声明，工具不能据此认证独立性。

冻结方案后，在独立的新会话中收集 `with` 和 `without` 两侧的全部计划运行。保持除被测插件以外的条件一致，将原始输出、错误、成本和原始人工计时间隔填入 `runs.jsonl`。完整字段见 [CONTRACT.md](CONTRACT.md)。

```powershell
python scripts/value_lab.py freeze .\work\my-study\suite.json --lock .\work\my-study\protocol.lock.json
python scripts/value_lab.py evaluate .\work\my-study\suite.json .\work\my-study\runs.jsonl --lock .\work\my-study\protocol.lock.json --output .\work\my-study\report
```

`init` 不会替你执行任务；空账本被评估时也不会得到正向结论。锁文件检测方案是否一致，不能证明独立预注册。禁止把模拟记录改一个来源标签当作实测，也不能为了补齐表格而虚构会话、费用、评审或实际加载状态。

比较前还应确认两组能访问相同的授权材料。插件独有的数据访问能力可以单独评价；基线缺少材料造成的差异不能直接叫作推理提升。如果无法提供相同材料，应保留这一限制或改问“这个连接让哪些任务成为可能”。

评估后生成一张可以继续使用的卡片：

```powershell
python scripts/value_lab.py usage-card .\work\my-study\suite.json .\work\my-study\runs.jsonl --lock .\work\my-study\protocol.lock.json --output .\work\my-study\usage
```

`USAGE.md` 与 `card.json` 从记录重新计算，列出已测条件下适合使用的任务、基线可能足够的任务和待调查问题，并绑定版本、模型、宿主、工具、预算及记录摘要。模拟、证据缺口或退步不会产生正向使用建议。卡片是局部参考，不会授予账户管理权限；分享前应检查其中保留的原始任务文字。

## 如何读结论

| 结论 | 可以表达的内容 |
| --- | --- |
| `PROMISING_LOCAL_SIGNAL` | 提交记录完整且符合冻结条件，并满足本次质量、退步和成本规则；仅为该任务集内的局部信号 |
| `NO_DEMONSTRATED_GAIN` | 本次没有达到预先选择的质量或效率目标 |
| `REGRESSION_DETECTED` | 出现关键结果失败或超过容忍范围的单例退步 |
| `INSUFFICIENT_EVIDENCE` | 缺基线、缺记录、条件不匹配、未完成评审或其他证据缺口阻止完整比较 |
| `SIMULATION_ONLY` | 方案或记录包含模拟证据，不能据此宣称实际增益 |

冻结前选择 `policy.objective`。默认 `quality` **必须包含大于零的质量提升**，同时达到 `min_quality_delta` 和质量底线；两侧质量相同但成本更低时只展示成本差，不会通过默认质量门槛。若研究问题就是“同等质量下是否更省资源”，可预先设置 `efficiency`：要求平均质量不下降、达到质量底线，并且完整成本严格降低；该目标不使用 `min_quality_delta`。

两种目标都保留关键结果失败、单例退步和证据完整性限制。效率结果只是所提交任务集内的描述性信号，不能写成统计学非劣效性结论。费用未知不能通过任一正向门槛；在质量目标下，`require_cost_saving=false` 仅取消“必须更便宜”，不会取消费用完整性要求。不要看到结果后切换目标来制造通过。

质量分按 outcome 规则计算，process 规则只作诊断。费用差是“有插件减去无插件”的平均每次计划执行成本，负值表示有插件侧更低；包含按预设小时单价折算的人工工时。报告中的任务簇 bootstrap 区间是探索性描述，不是因果检验，也不是自动通过的显著性标准。

添加 `--gate` 可用于本地流水线：退出码 0 表示局部正向信号，1 表示无增益或退步，2 表示证据不足或模拟。输入无效同样返回 2，应同时查看错误信息。这个退出码不是发布、采购或科学审批授权。

## 加入真实人工复核

当 suite 中有 `human` 规则时，先为已有原始输出生成去除显式组别信息的复核包：

```powershell
python scripts/value_lab.py review-pack .\work\my-study\suite.json .\work\my-study\runs.jsonl --output .\work\my-review
```

只将生成的 `reviewer` 目录交给实际复核者，操作者保留 `operator-only` 中的映射。输出文本仍可能泄露组别，因此这不是技术隔离或独立盲评认证。复核者按包内说明填写 `decisions.jsonl`，逐项提供真实 reviewer、rationale，以及 `true`、`false` 或表示争议/不足的 `null`。

```powershell
python scripts/value_lab.py apply-reviews .\work\my-study\suite.json .\work\my-study\runs.jsonl --mapping .\work\my-review\operator-only\mapping.json --decisions .\work\my-review\reviewer\decisions.jsonl --output .\work\my-study\reviewed-runs.jsonl
python scripts/value_lab.py evaluate .\work\my-study\suite.json .\work\my-study\reviewed-runs.jsonl --lock .\work\my-study\protocol.lock.json --output .\work\my-study\reviewed-report
```

合并写入新文件，原始记录保留。已有评审不会被静默覆盖。包内映射不匹配、原输出变动、重复决定或没有真实理由的判断会被拒绝；未解决的判断继续阻止完整结论。

## 连接 Claude 原生评估

原生评估适配器准备任务和转换已有结果，**不会启动模型、自动信任插件、付款或发布**。

```powershell
python scripts/value_lab.py export-claude .\work\my-study\suite.json --output .\work\native-export --plugin C:\path\to\target-plugin
```

检查生成目录中的 `README.md` 与 `export-manifest.json`。它们说明如何审阅并将任务复制到目标插件，以及计划使用的参数。只有显式配置 `conditions.budget.max_cost_usd` 才生成执行参数；原生额度是估算限制，执行中的运行可能造成超出，不能当成结算上限。这里不自动执行任何命令。

`contains` 与 `not_contains` 可转换为原生字面正则检查；`human` 会导出为模型评分诊断，**不代表完成了人工评议**。`json_equals` 没有完全等价的原生规则，因此导出会明确拒绝，而不会用较弱的检查替代。

已有原生结果时，有两条路径：

```powershell
python scripts/value_lab.py native-report C:\path\to\native-result.json --output .\work\native-report
python scripts/value_lab.py import-claude C:\path\to\native-result.json --suite .\work\my-study\suite.json --output .\work\my-study\native-import.jsonl
```

`native-report` 直接展示原生诊断；`import-claude` 转成保留缺失项的本地账本。原生聚合结果缺少的原始输出、实际会话、条件、费用或评分映射不会被推测补齐，导入结果不能自动满足完整评估的证据要求。当前适配目标是文档中的结果 `schemaVersion: 1`。

## 作为插件加载与可选 MCP

源码包含 Agent Plugins 根清单、Claude 和 Codex 兼容清单、`research-directions`、`use-plugin-well` 与 `assess-value` 三个技能，以及本地 MCP 服务。核心 CLI 不依赖 MCP；服务需要为宿主实际调用的 Python 3.11+ 安装 SDK：

```powershell
python -m pip install "mcp==1.28.1"
```

该命令会下载 SDK 及其依赖，已有兼容 SDK 时无需重复安装。源码开发命令仍可使用 `python scripts/value_lab.py ...`。新版清单从插件自身路径运行 `scripts/value_lab.py serve`，不需要提前安装本项目的 Python 包。便携配置位于 `mcp.json`，旧 Codex 清单内嵌兼容配置，Claude 配置位于 `.mcp.json`，分别使用各自的根目录变量。安装 SDK 的 Python 必须与宿主解析到的 `python` 一致。`serve` 启动的是 MCP 标准输入输出服务，不是网页服务器。

| MCP 工具 | 作用 |
| --- | --- |
| `research_direction_advisor` | 核对研究缺口、证据引用与资源约束，比较研究者修订；深度推理由宿主 Agent 完成 |
| `plan_plugin_use` | 根据任务适配与已提交的状态生成使用计划，不执行交接动作 |
| `build_plugin_usage_card` | 从方案、原始记录与可选冻结对象重新计算，生成有范围限制的使用卡 |
| `validate_value_suite` | 检查提交的方案对象，返回摘要与计划运行数 |
| `evaluate_plugin_value` | 评估提交的方案、记录与可选冻结对象 |
| `inspect_claude_eval` | 检查原生结果对象，保留诊断证据边界 |
| `example_value_suite` | 返回教学模板和空观测列表 |

这些工具在本地处理传入对象，不读取任意用户文件，不执行模型或被测插件，不连接或改变外部账户，不发布结果。通过宿主提交给助手的数据仍受该宿主的数据处理方式影响；本地 MCP 不意味着整段对话都只在本地处理。

若要在 Claude Code 交互会话中尝试加载本插件，可以明确指定源码的绝对路径：

```powershell
claude --plugin-dir C:\Test\plugin-value-lab
```

加载后可请求：“评估一个插件相对无插件基线的增益，先帮我设计公平比较。”这个命令只展示手动加载入口，本文没有代你运行或安装。加载测试还需要验证技能发现、MCP 握手与实际工具调用，不能仅凭清单存在就认定成功。

项目已经包含可添加的 Codex/Claude 市场目录；`plugins/plugin-value-lab/` 是通过 `python scripts/build_marketplace.py --generate --package` 从根源码生成的副本。格式、隔离安装和连接的实际验证记录见 [VERIFICATION.json](VERIFICATION.json)。隔离测试不会把插件安装到你的当前账户；桌面端仍按 [安装指南](docs/INSTALL.zh-CN.md) 添加市场并安装。CLI 安装和 MCP 检查不能代替新对话中的技能发现或真实用户收益验收。

## 科研示例和本插件自评

[科研教学 suite](examples/scientific-suite.json) 有四类问题：缺少独立重复、保留合法描述、实测模态来源、软件检查与科学评议的边界。它使用题目明确给出的规则和虚构材料，不包含真实生物学数据，人工规则必须由实际评审者判断。

[原生自评案例](evals/README.md) 检查本插件是否误把满分当增益、忽略基线缺失、把模拟当实证，或拿流程成功掩盖结果退步；另有任务分流案例检查是否强迫普通任务评测、重复建议等待中的连接、混淆访问能力与推理增益，以及由评分擅自发起管理动作。这些案例可能被无插件基线同样答对，因此自评通过本身也不证明本插件增加了价值。

本版本是可检查和运行的本地 alpha 原型。示例、格式检查与本地测试只能支持对应的软件行为；真实宿主接受度、使用者收益、独立外部验证和科学授权需要各自的实际证据。
