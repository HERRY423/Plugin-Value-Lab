# 适用范围与真实价值证据：2026-09-29

本轮用户明确要求外部时间登记、逐结论范围检查和完整修复链，并指定 Life Sciences Literature 与 NGS Analysis Workbench。版本保持 0.7.0，主 CLI/MCP 接口不扩张。机器快照见 [value-evidence-20260929.json](../evidence/value-evidence-20260929.json)。详细原始记录位于本机 `C:/Test/pvl-value-evidence-20260929`，没有作为发布或上游采纳证据。

## 外部时间与单独审阅

`value_lab/preregistration.py` 和 `scripts/preregister.py` 生成 RFC3161 请求并离线验证响应。联网提交是显式步骤，仅发送 SHA256 摘要与 nonce，不发送锁文件内容。校验同时覆盖 TSA 签名、调用方明确固定的 CA 根证书集合、锁文件内容及请求 nonce。Git 作者时间或本地签名 tag 不被当作独立时间证明。

真实 DigiCert 时间戳分别为 2026-09-29 05:11:52 UTC（原方案）和 05:14:32 UTC（首次官方执行未找到案例后、修正安装目录的方案修订）。实际启动器先验证对应收据，再启动观察。修订说明保留原锁摘要、失败尝试与修改理由，不追溯宣称原先观察已事前登记。

时间戳只证明这些字节在该时间已存在，不能证明作者此前未看过结果、真人身份、独立性或账单真实性。CA 吊销状态没有在线检查。控制器启动记录不构成“从未提前执行”的外部证明。

审阅采用单独的 `pvl-study-review-1` 声明，绑定 suite、report 和 registration 三个摘要；使用 Ed25519 的 `pvl-review-1` 域。`verify-review` 要求外部提供有 `domain_reviewer` 角色的可信公钥；声明自带公钥不能建立身份信任。没有真实审阅者签名，本轮仅提供未签名模板，真人验证保持 PENDING。

```powershell
python scripts/preregister.py prepare --lock protocol.lock.json --output registration --openssl <openssl>
# 显式取得 response.tsr 后，使用自己固定的信任根集合验证：
python scripts/preregister.py verify --directory registration --lock-sha256 <digest> --ca-file roots.pem --ca-sha256 <digest> --openssl <openssl>
python scripts/preregister.py verify-review --statement review.json --signature review.sig.json --trust reviewers.json --expected expected.json --output review-receipt.json
```

## 结论绑定与越界引用

方案可在冻结前声明 `claim_context={model_version,host_version,excluded_uses}`，每个 case 可声明 `data_scale={unit,count}`。旧方案缺失值保持 null，不补零或猜版本。`evaluate` 自动附加 `scoped_conclusions`；使用卡带同一绑定，HTML/Markdown 展示条件、数据规模、缺失项和不支持的用途。

每项结论标明 case、family 或 study 单位，固定案例 ID、任务族、模型／宿主及版本、数据单位和数量。总质量、成本、不确定性、任务结果和判据判断分别绑定。单案例不升级为总体；任务族差异仍是 family 结论。默认明确不支持广泛采用、因果收益、独立科学有效性、真人可用性、其他模型／宿主、更大或不同数据、未见任务。

```powershell
python scripts/claim_scope.py --report report.json --sha256 <independently-retained-report-digest> --request citation.json --output citation-result.json
```

引用必须提供 `claim_id/evidence_unit/conditions/data_scale/intended_use`；当前只支持 `describe_observed_result`。任何范围变化返回 ERROR、退出码 2。结论变更、删去范围卡或改变覆盖也会拒绝；报告渲染检查内在一致性，引用接口还要求独立保留的整份报告摘要。声明的版本／规模本身不因此获得真实性认证，人工在接口外误引也不能由程序阻止。

## 真实官方导出与导入

`export_claude → Claude Code 2.1.282 plugin eval → import_claude` 已在真实官方 CLI 上完成；模型是配置供应商的 `deepseek-flash`，不可变模型修订号未知。案例为检索未执行时的诚实报告，字面判据仅检查 `RETRIEVAL_NOT_EXECUTED`。第一轮因为准备者放错 eval 目录，在启动模型前报错；修订方案重新取得外部时间戳后执行第二轮。

两臂各一次、均完成，原生分数 1 与 1，差值 0。轨迹中的 with 臂确实调用 `life-sciences-literature:ncbi-entrez-skill`；这是该官方案例的工具事件，不能移植为下述独立脚本产物的 Skill 生成证明。实际还出现未列入冻结 Read/Skill 集合的 Glob，with 臂报告 4 turns 而方案设置 maxTurns=3，因此不能算严格同条件的收益比较。导入仍保留 `unverified_native` 和缺失字段，不把原生分数升级为 PVL 科学验证。

官方报告估算费用 $0.113755，超过设置的 $0.09 和用户单次 $0.10 限额；宿主在请求完成后报告超限。该参数未形成硬封顶，本轮停止新的付费模型调用。包含此前相关 Grok 盲测的累计报告费用为 $0.2562524，实际结算未知。未使用付费 AgentMuxer offering；不能把未知结算写成零。

## Literature 的真实缺陷与本地修复

通过安装的 0.1.5 版 ncbi-entrez skill 脚本，对公开 Salmon 方法运行真实 ESearch，得到 PMID 28263959。原始结果只包含标识符，却由共享 `literature_source_contract.py` 放入 `sources` 并标 `supports_claim=true`、`kind=evidence`。这违背原插件 source-presentation 既有契约：标识符解析等非实质科学证据应进入 `checked_sources`。

PVL 使用固定摘要的 executable checker 判为失败，随后只在保留的插件副本中将 esearch 归入 metadata；安装缓存未改。相同查询重新调用真实 NCBI，修复后通过。正文 EFetch 和空 ESearch 两个对照在修改前后均通过。三种查询的前后 NCBI 原始响应 SHA256 分别相同，保留请求、响应、运行记录、检查器摘要和 repair.diff。这里没有注入缺陷；判据在发现问题之后按既有契约形式化，不能称为未见事故的盲测。

这是一条实际插件脚本调用→错误分类产物→PVL 判据失败→本地修复→现场复测的有限链。源码定位由作者／Agent 阅读代码完成，不是 PVL 自动 L3。它发生在用户指定的验证任务中；没有非作者科研任务、真人阅读时间或 PVL 有／无配对。完整独立自然使用样本仍为 0，不作为因果收益或上游接受的证据。

## NGS 真实调用尚未进入运行

实际调用得到本地目标、12 项工作流目录、空历史；`get_runtime_environment(local)` 在 300 秒后 MCP 超时，未返回可用快照。额外 local 目标检查被接口拒绝（该接口只检查 SSH）。未据此猜测软件缺失或源码根因，未启动工作流、生成科学产物或捏造运行 ID。

没有宿主快照就不能绑定同一控制器做 readiness 和不可变计划；本轮 NGS 完整链未完成。待运行环境探测恢复后继续真实 readiness 和宿主审批。详见本地 `ngs/REVIEW.zh-CN.md`。

## 验证及失败保留

新增测试覆盖逐结论范围、数据／模型／宿主／单位越界、结论篡改、外部摘要缺失、缺失维度、审阅信任、撤销密钥和签错目标。实际时间戳离线负向验证覆盖锁内容、签名、nonce、信任根篡改，两份响应都拒绝。首次负向测试误改 certReq BOOLEAN 的非零值，未改变 nonce，被正确接受；该错误测试已保留并修正为改变 nonce，不隐藏失败。

真人专家复核、真人诊断准确率／用时、独立自然使用修复、严格同条件 PVL 有／无收益和真实外部环境重建仍未完成。本轮工程和接口证据不解除这些限制，也不自动解冻。
