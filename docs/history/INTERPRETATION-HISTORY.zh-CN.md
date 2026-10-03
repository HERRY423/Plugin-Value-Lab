# 原始证据与解释修订分离

本地决策恢复现在分别保存观察、判断、决策和展示。追加新解释不会修改原始执行、失败记录、费用或历史报告；最近生成的解释也不会自动成为当前使用建议。

这是本地基础设施能力，不是新的科学评估器。`judge` 记录提交的结构化检查，`decide` 记录明确提交的选择；它们不会独立验证作者、运行评分器、确认科学有效性或授权执行。原有 `evaluate`、使用卡和科研门槛继续负责相应评估。

## 四种身份

| 层 | 绑定内容 | 变化后的必要动作 |
| --- | --- | --- |
| 观察 `observation_sha256` | 原执行分组、操作与请求键、终态、收据、原始产物摘要 | 新执行建立新尝试；旧观察保持不变 |
| 判断 `judgment_sha256` | grader、reference、domain 契约与实现身份 | 以同一观察重评分，产生新判断及独立结果摘要 |
| 决策 `decision_sha256` / `policy_sha256` | 指定判断结果、用途、质量门槛、预算、范围、建议 | 明确提交新决策，记录替代对象和理由；不必重评分 |
| 展示 `presentation_sha256` | 渲染器身份与实际报告字节；另绑定来源与生成时状态 | 保存新展示；不新增观察、判断或决策 |

观察身份不包含晚到的费用结算或调用标识补录。原事件日志仍完整保留这些信息。费用变化会使当前建议进入待复核，不能通过重评分清空累计费用。科学样本量仍不从尝试数量推断。

`contract.reference` 必须明确声明参考依据；没有参考时可写 `{"kind":"none"}`，不能省略字段。未知实现可写 `null`，但不能因此产生当前建议。规则契约本身仍是提交材料，不是自动发现的完整依赖清单。

## 建议的生命周期

`current` 表示记录中的当前选择，不表示评估通过、插件收益成立、科学批准或执行授权。建议可以是“使用”“不用”或“继续调查”；失败检查也可能支持一个限制使用的选择。

- 判断修订、同组新尝试、费用依据变化或混入旧式解释时，相关当前建议进入 `review_required`。原判断与原决策对象保持原值，状态从事件历史派生。
- 新 `decide` 必须通过 `replaces` 指向相同范围内最近的建议。替代过程与新记录在同一事务提交；旧建议成为 `superseded`，保存 `superseded_by` 和理由。
- `review` 可标记 `review_required` 或 `not_applicable`。它不能把建议改回 `current`，也不能重新激活已替代或不适用的建议；需要明确的新决策。
- 新评分即使全部通过，也不会自动激活建议。未知检查、待办、实现未知、旧依赖未知、未结算费用、超过决策预算或绑定已修订判断时，请求的 `current` 会保守落为 `review_required`。
- 新尝试还未纳入判断时，不能重新选择旧判断来绕开失败或未知结果。`rescore` 必须使用完全相同的观察；`evaluation` 的有父版本修订不能丢掉父版本包含的观察。

`current_decisions` 才是新状态层的当前选择集合。兼容字段 `current_interpretation` 仅指最近的旧式解释。旧式解释通过 `legacy_interpretations_without_lifecycle` 列出，不自动迁移成建议。

一个范围只维护一条明确替代链。范围摘要要求对象精确一致；系统不宣称能自动识别自然语言中不同描述是否实际重叠。跨范围适用性仍需明确复核。

## 本地入口

继续使用独立的 `python -m value_lab.decision_store`；主 CLI 和六个只读 MCP 工具不变。恢复存储不依赖 MCP Tasks 扩展。

已有依赖复核报告可直接绑定到已保存的执行产物：

```text
python -m value_lab.decision_store --store study.sqlite record-recheck --report revision.json --card card.json --attempt original --judgment-id judgment-1 --key import-judgment-1 --expected-sequence 4
```

再次导入改变规则后的判断时，显式指定 `--parent judgment-1` 和新的判断 ID、请求键、当前序号。该入口核对报告内部摘要、原卡绑定与所选执行的实际产物摘要，把规范化源报告和原卡原子保存为附件；不重新执行评分。来源身份与报告真实性并不由自报哈希认证。

`append` 支持四个新事件（完整字段见 `schemas/decision-event.schema.json`）：

| 事件 | 用途 |
| --- | --- |
| `judge` | 指定观察、规则／参考／领域契约、实现身份、结构化检查、父判断和理由；可附源报告 |
| `decide` | 指定判断、独立策略、精确范围、建议、状态、替代对象和理由 |
| `review` | 明确记录待复核或不适用状态及原因 |
| `present` | 保存判断或决策的展示版本，用 `--artifact report=文件` 交接真实报告字节 |

例如已有 `judgment-1` 后，可保存如下 `decision-event.json`，把序号替换为 `show` 刚读取的值：

```json
{
  "kind": "decide",
  "key": "selection-1",
  "expected_sequence": 5,
  "payload": {
    "decision_id": "choice-1",
    "judgment_id": "judgment-1",
    "policy": {
      "purpose": "在原冻结任务范围内继续调查",
      "quality_thresholds": {"required_checks": ["format"]},
      "budget_micros": 1000000
    },
    "scope": {"task": "原冻结任务", "stage": "资料整理"},
    "recommendation": "保留旧结果，补齐仍缺少的检查后再决定使用范围",
    "reason": "采用新检查规则后重新审视原选择",
    "replaces": null,
    "status": "review_required"
  }
}
```

```text
python -m value_lab.decision_store --store study.sqlite append --event decision-event.json
python -m value_lab.decision_store --store study.sqlite show
python -m value_lab.decision_store --store study.sqlite export --output recovery-revision-2
```

修改用途或预算时，新建 `decide`，复用同一个 `judgment_id` 并明确 `replaces`；不得通过事后改变用途来改写原冻结评估结果。只有新判断契约确实改变且观察不变时使用 `rescore`。

展示保存 `lifecycle_at_render` 和来源摘要；建议后来改变时，旧展示进入 `stale_presentations`。旧报告不改写、不冒充当前建议。`RECOVERY.md` 显示当前派生状态、替代理由和各判断身份；所有旧报告的字节仍在恢复包中。

## 实现变化与保守回退

`evidence_dependencies` 现在提供四层身份。评分实现仍绑定 Python、平台和全部运行模块；唯一有界例外是该模块的 `_revision_files` 渲染函数体。

这个例外经过静态调用边界检查：只允许已审阅的交付路径引用渲染器，渲染器只能使用受限的文本构建／转义／序列化调用，不允许写回输入对象。新增引用、未知调用、输入写入、解析失败等会撤销例外，将完整源文件重新纳入实现摘要。缓存以实际源字节为键，不依靠版本号或修改时间。

因此只改该函数的标题或布局不会重新评分；其他展示函数、公共辅助函数、策略代码和未验证依赖关系仍保守触发复核。这里没有宣称完成任意 Python 程序的依赖证明，也没有放宽已有整卡失效规则。旧报告尚无新的分层摘要时仍可读取；首次与新实现比较会保守复核。

交付恢复仍要求原报告字节与暂存请求一致。若升级渲染器导致旧暂存报告无法完整恢复，不会偷偷重评分或覆盖历史；保留暂存并使用明确的新输出目录。

## 历史兼容与验收

新观察／旧式解释事件继续使用 v2；四个新增解释事件使用 v3。读取 v1/v2/v3 混合历史时保留原事件格式、顺序、摘要和附件，不补造过去不存在的身份或核实记录。未知格式拒绝恢复，不降级猜测。

`tests/fixtures/decision-history-v2.json` 冻结了修改前本地 wheel 实际输出的五类包：正常、失败、结果未知、收集中断、旧规则遗漏字段导致误判。保存的是文件原始字节的 Base64 和原完成清单，测试解包后验证摘要。它们是合成兼容材料，不是公开版本或真人科研验证。

```text
python -m unittest tests.test_interpretation_history tests.test_decision_contracts tests.test_decision_recovery tests.test_evidence_dependencies -q
python scripts/check_interpretation_history.py --output <新的验收目录>
```

端到端验收恢复旧包，在同一旧产物上实际执行内置 JSON 检查，观察旧规则通过、纠正规则失败；保留旧判断与原报告，记录建议待复核和替代关系，然后只改决策用途，确认不增加评分，最后带检查点恢复全部新旧历史。测试另覆盖提交前强制结束进程、并发同键提交、错误来源绑定、未知检查、展示失效提示及不支持格式。

这些结果支持本地恢复与修订契约；不证明真实长期采用、科学结论成立、所有文件系统的断电持久性，或已安装宿主的集成验收。
