# 科研决策的本地恢复

2026-10-02，按用户明确要求推进 P0-1。源代码功能；版本保持 0.9.0。状态层位于评分核心与只读 MCP 之外，使用 Python 自带 SQLite，不依赖宿主的 MCP Tasks 扩展。五个主入口和六个默认 MCP 工具保持兼容。

## 研究者看到什么

再次打开研究时，Agent 从本地记录读取：冻结方案与原锁文件、每次执行尝试、实际保留的产物、缺失证据、解释版本、未知依赖身份、尚待核实的外部调用和费用，以及下一步。它不会从聊天摘要推测成功。

同一请求重交返回当前已核验状态，标记 replayed；不会新增事件或观察。读取、重评分、重执行是三件事：show / restore 只恢复材料；interpret 保存新的解释及父版本，其中 rescore 必须保持原观察集合；start 才登记新的执行尝试，同一证据项的后续尝试必须明确前次尝试与原因。登记不实际启动任何执行，也不构成科学或付费授权。

材料收集状态使用 COLLECTED，不使用科学“成功”。collected_attempts 仅为保留产物的尝试数，scientific_sample_size 始终 null。失败、取消和重复执行不能用来增加独立样本量；评分仍由原评估器负责。

## 从已有冻结研究接入

Agent 为用户准备依赖身份 JSON（未确认值为 null），然后运行：

~~~powershell
python -m value_lab.decision_store --store work/my-decision.sqlite init --suite work/study/suite.json --lock work/study/protocol.lock.json --dependencies work/dependencies.json --budget-micros 1000000 --key initialize-study
python -m value_lab.decision_store --store work/my-decision.sqlite show
python -m value_lab.decision_store --store work/my-decision.sqlite export --output work/decision-recovery-1
~~~

init 核对原 suite 和 lock，复制两者并据此保留完整 case × arm × repetition 分母。它不修改原研究，也不把导入时间当成真实预注册时间。预算为任务累计整数 USD micros；1 美元 = 1000000 micros。此数只是本地记账边界，不设置服务商预算，不授权付费。

对于任务选型或组合研究，可使用 initialize 事件保存完整原冻结计划和所需证据 ID；plan_sha256 必须匹配原对象。通用模式只绑定输入快照，不代替对应研究类型的冻结校验。依赖身份是提交的历史快照，不是实时检测。

用户不需要手填下面的事件；由 Agent 或宿主适配器从实际材料构造。可运行的完整制造案例与故障演练：

~~~powershell
python scripts/check_decision_recovery.py --output work/decision-recovery-acceptance
~~~

产物包含 decision.sqlite、原 suite/lock、COMMITTED.json 校验的恢复报告、原始记录与评分结果，以及故障测试日志和 acceptance.json。所有研究记录均为合成，所有费用值为模拟账本，没有远端调用。

## 宿主事件契约

入口为 DecisionStore.append，或独立模块的 append --event EVENT.json --artifact ID=PATH。输入形状见 [事件模式](../../schemas/decision-event.schema.json)。每个逻辑提交固定一个 key；新事件带最近一次读取的 expected_sequence。同 key 的相同请求可在旧 sequence 上重放，改参则拒绝。不同 key 的过期写入必须重读，防止多个会话互相覆盖。

| 事件 | 必须保留的信息 | 作用 |
| --- | --- | --- |
| initialize | 原计划、摘要、所需证据、依赖、累计预算 | 创建不可变研究快照 |
| start | attempt_id、requirement、mode、operation、external_key、max_cost_micros | 在真正调用前提交尝试和预留 |
| identify | attempt_id、invocation_id | 保存服务返回的稳定调用标识 |
| unknown | attempt_id、reason | 超时或断线保持 OUTCOME_UNKNOWN |
| cancel_request | attempt_id、reason | 仅记录取消请求，不当作已取消或释放费用 |
| reconcile | 原 operation、external_key、invocation_id、remote_status、源收据 | 绑定原调用的核实记录，不启动查询；not_found 继续未知 |
| finish | attempt_id、COLLECTED/FAILED/CANCELLED、源收据、实际产物 | 原子提交终态与产物；不是科学通过 |
| settle | attempt_id、cost_micros、basis | 根据确认材料结算费用；不覆盖原结算 |
| interpret | 新 ID、父 ID、evaluation/rescore、原因、涉及尝试、规则、依赖、剩余检查、报告 | 保存新解释，旧观察和旧判断都保留 |

CLI 的 --artifact 从用户授权的本地文件读取原始字节（每文件最多 64 MiB）；摘要由程序计算。文件较大时本版拒绝导入，不偷偷改成未核验的路径引用。数据库保存完整敏感原文时适用原数据访问权限，不应默认共享；export 也是本地产物，不自动脱敏或发布。

例：已初始化且 sequence 为 1，登记外部请求：

~~~json
{
  "kind": "start",
  "key": "start-baseline-1",
  "expected_sequence": 1,
  "payload": {
    "attempt_id": "baseline-1",
    "requirement": "case1--without--1",
    "mode": "tool_execution",
    "operation": "provider GET /public-data",
    "external_key": "original-provider-key",
    "max_cost_micros": 100000
  }
}
~~~

requirement 必须使用 show 返回的真实计划 ID。先提交 start，再由有授权的宿主执行；返回 invocationId 后登记 identify。若两者之间断线，仍用原 external_key 查原调用，不能生成新 key 重购。相同 requirement 存在 PENDING/OUTCOME_UNKNOWN/RESULT_AVAILABLE 时，新尝试被拒绝；本地状态本身不会查询供应商。

新协议中，外部模式的 finish 必须有对应的终态 reconcile 记录：COLLECTED 对应 completed，FAILED 对应 failed，CANCELLED 对应 cancelled。远端报告 completed 只进入 RESULT_AVAILABLE，必须实际保存产物后才成为 COLLECTED。查不到请求不能证明它没有执行；申请取消不能证明已经取消。矛盾的终态收据会报错并要求复核，不能覆盖已有确认。核实收据仍是提交材料，不是 PVL 独立向供应商验证过的事实。

同一 requirement 的后续 start 需要 retry_of 指向最近的已终结尝试，并填写 reason；不接受跳过最近失败而指向较早成功的历史。外部 key 不得复用，原失败、产物和费用仍保留。observation_groups 按原计划证据项展示所有尝试，防止把重复执行伪装成新的计划样本。

失败/取消不会自动释放预留，只有明确 settle 才确认成本或零费用。未知上限可记录为 null，但会阻止后续新尝试，直到对账。已确认实际费用超过原预留仍如实保留，并影响剩余预算，不能通过丢弃超限收据维持“预算内”的表象。执行结果和账单是独立状态。

重评分报告须从已有评分器产生，再用 interpret 保留规则身份、原始报告和待办。新协议的 rescore 要求已有父解释、完全相同的 attempt_ids 和原始观察绑定，且规则内容摘要发生变化；加入新执行或删掉失败应使用 evaluation，并保留未评估材料清单。规则没变化只需读取原结果，不应登记为新重评分。系统记录 observations_sha256、rules_sha256 和 result_sha256，但这些摘要不会把提交的报告升级成独立评分认证。新收集结果、失败或取消会重新进入待评估清单；旧解释仍可查看。pending_checks 也是报告方的声明，不能充当人工裁决或科学有效性证明。

## 中断恢复与报告交付

SQLite 使用串行写事务、完整同步和乐观 sequence 检查；事件与原始字节一起提交。被终止的未提交事务恢复为原状态，已经提交但回复丢失的事务可通过原 key 重放。读取可能触发 SQLite 的本地 hot journal 回滚，因此状态库不放进只读 MCP 工具。

报告先在唯一暂存目录写入、同步、核对，再写 COMMITTED.json，核验整包后在同一文件系统重命名到正式目录。正式目录只在完整交付后出现。重复提交相同字节会核验并返回已交付结果；内容不同、旧目录没有完成标记、字节损坏均拒绝覆盖。

中断的暂存目录保留；普通重交返回 INCOMPLETE，不提供可当作正式结果的路径。明确 export --resume 或 evidence_dependencies --resume 会用新暂存目录重新交付，旧失败字节仍保留。此 resume 只恢复本地交付，不重启外部请求。evidence_dependencies 在普通重交和显式恢复时都不再次调用评分器：显式恢复必须有匹配原请求与整包摘要的完整 revision.json，否则拒绝恢复，并要求在新目录明确启动另一项评分修订。改变输入、原文件、运行时或规则时也应新建修订目录。

## 从导出包真正恢复与检查历史缺失

导出现在包含 checkpoint.json，绑定事件序号、历史末端摘要与原计划。把检查点另存到用户控制的独立位置，再恢复到新数据库：

~~~powershell
python -m value_lab.decision_store --store work/restored.sqlite restore --bundle work/decision-recovery-1 --checkpoint work/retained-checkpoint.json
python -m value_lab.decision_store --store work/restored.sqlite show --checkpoint work/retained-checkpoint.json
~~~

restore 核验提交清单、事件链、请求键、实际产物及检查点后，在单个事务内恢复原事件身份和原字节。不运行评估器、不创建执行、不增加观察、不重置费用。恢复中途退出可从同一个包重试。目标已包含相同或更多的同链记录时返回现状，保留后续费用和尝试；不同历史拒绝覆盖，不做静默合并。

show 的检查点允许正确的后续追加，但拒绝丢失检查点之前的历史。缺少独立保留的检查点时只能证明当前包内部一致，不能发现有人将整份历史替换为一个更旧、内部自洽的备份。同包内的检查点也不是外部真实性证明。

新写入使用 pvl-decision-store-2；旧版 pvl-decision-store-1 仍按原语义读取与恢复，原事件不改写。恢复视图明确标示 legacy_history_present 和没有观察绑定的旧解释，不能声称旧记录已通过新版约束。v1 历史上的新写入使用 v2 规则。旧数据库和旧导出包都不需要为了读取而迁移科学结论。

旧版本 revision.json 仍可作为 --previous 使用，旧目录不会被自动补上完成标记。本次没有将所有历史报告写入器改造为事务式交付；当前覆盖依赖复核和决策恢复导出。

## 验收与边界

首次 P0-1 的[本地验收记录](../evidence/decision-recovery-20261002.json)保留全量 1182 项与后续 51 项专项结果。本轮[恢复动作分离与兼容验收](../evidence/decision-recovery-contracts-20261002.json)在最终运行时代码上通过全量 1205 项、零跳过；73 项专项、五处进程中断、真实内置判据的同产物重评分、实际旧版包恢复与新 wheel 独立恢复均通过。收据绑定本轮源码摘要，费用案例仍为模拟，不能推断实际科研收益。

tests/test_decision_recovery.py 和 tests/test_decision_contracts.py 真实启动并终止子进程，验证写报告、等待外部结果、补齐证据、整包恢复与保存评分后中断；同时验证并发旧状态写入、请求去重、篡改拒绝、未知成本、失败保留、同观察重评分、取消请求、终态收据绑定、检查点与 v1 兼容。原依赖复核测试验证已交付请求重放和不同内容不可覆盖。

验收脚本另用现有内置 JSON 评分器对同一份制造产物执行两套规则：旧规则通过、新规则失败，两份解释都保留，观察数仍为 1。随后显式登记失败重执行和下一次重执行，保留失败及 35000 micros 的模拟累计费用。它验证实际评分行为与恢复状态的衔接，没有真实科研执行或付费调用。

这证明本地工程恢复契约，不证明真人采用、独立评价、科研正确性、真实节省、已安装宿主验收或远端 exactly-once。哈希链只能检测与保留摘要不符的更改，不能认证身份、防止恶意重写整库或发现没有外部检查点的尾部截断。事务依赖本机 SQLite 与文件系统；网络共享盘、同步软件竞争、磁盘损坏和突然断电不在本轮验收范围。关闭全部连接后才能直接复制数据库；运行中备份应使用 SQLite backup API，不能只复制活跃数据库文件。

