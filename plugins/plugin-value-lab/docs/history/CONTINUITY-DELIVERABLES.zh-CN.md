# 跨会话、跨版本和单宿主资格的联合交付

本轮增加恢复后的适用性检查，不改写原事件，不重评分、不调用模型、不释放未知费用。读取成功只证明能恢复材料；`current_decisions` 是历史记录中的当前选择，还要核对本次环境才能借用。

## 三项交付

| 交付 | 已提供 | 仍须区分 |
| --- | --- | --- |
| 跨会话恢复 | 在独立进程恢复原包、核验独立保留检查点；输出绑定最新检查点的 `HANDOFF.md`、环境和检查结果 | 未提供独立检查点时无法排除自洽旧备份；该状态阻止产生兼容建议 |
| 跨版本解释 | 对比 grader、reference、domain 和实现身份；对比决策用途、预算、范围与依赖 | 只改策略不要求重评分；新范围需适用性复核；没有当前身份不能回填旧值 |
| 单宿主适配器资格 | 固定旧样本与九类可执行控制，绑定资格代码、解析器、样本、精确宿主范围；恢复检查逐结论消费 | 仅 Codex Desktop `codex_work_desktop` / `0.159.2` 的本地合成符合性；不等于当前已安装宿主实测或服务商认证 |

原评分门槛、六个 MCP 工具、主 CLI/SDK 和版本 0.9.0 保持兼容。两个独立本地模块不要求宿主支持 MCP Tasks。

## Agent 的恢复步骤

1. 使用 `decision_store restore` 恢复完整事件、产物和费用，用用户另存的检查点核验历史。然后读取最新 `show` 检查点；较早但同链的独立检查点可以验证历史，新环境必须绑定最新头部。
2. 从实际文件和本次任务收集依赖、判断实现、当前策略与范围；缺少的身份保留未知。不要复制旧值冒充实时发现。按每个决策明确声明所依赖的宿主结论。
3. 仅在需要宿主日志结论时运行适配器资格控制、采集用户授权的日志，并绑定会话与前缀。已有独立文件验证不因无关宿主能力缺失而作废。
4. 发布不可覆盖的恢复检查包。需要继续工作时重新核验包与当前数据库、环境和实现；随后根据具体动作补证据、重评分或显式新建决策。

环境材料由 Agent 准备，研究者无需手填 JSON；用途、约束和未知事项用普通语言说明。该环境是提交的事实与依赖清单，PVL 不独立认证其真实性或完备性，不能通过省略真实依赖来声称适用。

## 本地命令

资格控制只读取仓库中固定的合成样本，不读取个人会话。输出目录必须新建；重复的相同结果可幂等读取：

```text
python -m value_lab.adapter_qualification --fixture tests/fixtures/codex-context-v1.json --output work/qualification-1
python -m value_lab.continuity --store work/restored.sqlite --environment work/current-environment.json --checkpoint work/retained-checkpoint.json --output work/handoff-1
python -m value_lab.continuity --store work/restored.sqlite --environment work/current-environment.json --checkpoint work/retained-checkpoint.json --output work/handoff-1 --verify
```

`--verify` 重新读取当前数据库并核验全部字节、版本和输入绑定，不运行评分或资格测试。事件追加、环境变化或本地实现变化后拒绝旧报告；新建输出目录重新检查。生成报告时的状态是一致的数据库快照，不是持续监控或对并发后续写入的锁定。

写入中断后，普通重交返回 `INCOMPLETE`；`--resume-publication` 明确完成相同检查结果的本地交付，保留失败暂存。环境或历史已变化时，应产生新包，不能把旧暂存当成当前结果。恢复检查包不是完整备份；原 `decision_store export` 包仍用于恢复数据库。

`current-environment.json` 的[字段模式](../../schemas/continuity-environment.schema.json)之外，运行时还核对真实历史引用、完整来源和语义绑定。顶层必须恰好包含：

```json
{
  "format": "pvl-continuity-environment-1",
  "checkpoint": {"format": "pvl-decision-checkpoint-1", "sequence": 6, "head_sha256": "原 show 的真实摘要", "plan_sha256": "原计划摘要"},
  "dependencies": {"host": "实际确认的身份", "plugin": null},
  "judgments": {
    "j1": {"contract": {"grader": {"version": "实际规则身份"}, "reference": {"kind": "none"}, "domain": {"scope": "实际科学约束"}}, "implementation": null}
  },
  "decisions": {
    "d1": {"policy": {"purpose": "本次用途", "quality_thresholds": {"required": ["format"]}, "budget_micros": 1000}, "scope": {"task": "本次精确任务"}, "host_requirements": {}}
  },
  "host": null
}
```

上例为字段说明，摘要须来自实际材料。缺少某判断或决策的当前信息会要求复核。空 `host_requirements` 明确表示该决策无宿主测量依赖，不能用来绕过实际需要的能力；省略整个决策对象表示未知。

需要宿主事实时，`host_requirements` 按结论映射精确语义，例如 `{"request_input":{"request_usage":"response-bound-input-includes-cache/v1"}}`。`host` 必须含 `snapshot`（采集报告的完整能力快照）、`receipt`（资格包的 qualification.json 对象）、`receipt_sha256`（工具输出的规范 JSON 摘要）、`expected_session_id`、`expected_prefix_sha256`。源码或字段语义、会话或前缀不匹配均保留缺口，不能由 token 补造美元结算。

资格报告的摘要只绑定本地材料，不能证明提交者真实运行了检查；另存摘要也不是签名认证。把测试结果人工改成 PASS 并重写所有摘要不能获得可信第三方资格。本版没有此类信任根。

## 结果含义与动作

`RECORDED_CURRENT_COMPATIBLE` 只表示原本为 current 的建议通过了本次提交环境的完整性和适用性检查。待复核、已替代或不适用的记录不会自动激活。它也不保证其他缺失证据已经齐全；报告总状态和 `next_steps` 保留整个研究的未完成项。

- `RESCORE_RETAINED_OBSERVATIONS`：规则、参考、领域契约或实现变化；对原观察新建判断，原记录不变。
- `REDECIDE_WITH_RETAINED_JUDGMENT`：仅策略变化时复用判断、显式新建决策；若规则也变化，须先完成重评分，再基于新判断决策。
- `REVIEW_NEW_SCOPE_APPLICABILITY`：范围改变，不能把旧结论直接迁移到新数据或任务。
- `REVIEW_DEPENDENCY_APPLICABILITY`：依赖改变或未知；没有足够信息时不猜测具体哪项科学检查可跳过。
- `REQUALIFY_ADAPTER` / `COLLECT_MISSING_HOST_FACTS`：资格或逐项能力不足；原观察和独立文件检查继续保留。
- 原调用结果未知时仍优先核实原 operation/key/invocation，预留费用保留；不因重开会话创建新请求。

## 验收

```text
python -m unittest tests.test_continuity -q
python scripts/check_continuity.py --output work/continuity-acceptance-1
```

集成演练恢复修改前 wheel 的旧包，在同一原始 JSON 上真实运行旧规则和纠正规则，保留 PASSED → FAILED 两种解释；另起进程恢复数据库并生成/核验交接。演练还验证规则升级、策略变更、未取得资格的新宿主、错误会话、缺少实际费用能力五种变体。匹配环境不能消除原判断中的待复核项。

已保存[联合场景记录](../evidence/continuity-scenarios-20261002.json)与[单宿主资格报告](../evidence/single-host-qualification-20261002.json)。资格记录绑定的是执行控制时的源码；后续源码变化应重新运行控制，不能沿用旧 PASS 标签。

最终[工程验收汇总](../evidence/continuity-deliverables-20261002.json)：全量 1378 项、专项 115 项均通过且零跳过，其中新增 35 项。离线构建的 wheel 在隔离进程中恢复同一检查点、核验源码生成的交接并重新运行资格控制；全部运行文件字节匹配。插件镜像、冻结范围和清单校验通过，未安装或发布。

全部材料为合成，本轮不证明真实研究者长期采用、实验节省、独立科学有效性、当前安装宿主验收或发布资格。
