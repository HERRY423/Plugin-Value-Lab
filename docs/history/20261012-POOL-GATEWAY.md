# 公共池与网关实现记录

状态：ENGINEERING_IMPLEMENTED；专家、真实文献快照、第三方托管与真实付费验收待接入。
当前入口仍是 [一页决策树](../../README.md)。本记录不修改历史评测证据。

## 文献检索公共池

首轮范围：通用生物医学文献检索。用户已选择“先搭建，专家与托管方待定”。
[候选库](../../examples/literature-pool/candidates.json) 有 30 个采集方向，每个附输入快照、参考答案草稿、合法改写和禁区样例。
它们是同类结构的合成教学样本，**不是 30 个已验收的独立真实任务族**。真实文献采集、许可检查、任务族独立性判断、专家签署尚未执行。

```sh
python scripts/evidence_pool.py inspect --pool examples/literature-pool/candidates.json
python scripts/evidence_pool.py seed --output work/my-literature-pool.json
python scripts/evidence_pool.py export --pool work/my-literature-pool.json --output work/pool-public.json
python scripts/evidence_pool.py review-statement --pool work/my-literature-pool.json --family randomized-trial --output work/expert-statement.json
```

输出路径必须不存在，避免覆盖已有记录。`--trust` 接受由维护者线下核验的信任文件，`--suite` 接受冻结方案对应的 suite。
签署前须用有许可的真实记录替换候选快照，保留来源、采集时间、原文与精确证据片段；修改任何输入、答案、变体或禁区后，都要重新审阅签署。

专家通过 `value_lab.signatures.sign(statement, key, 'pvl-literature-review-1')` 签署完整任务族的摘要承诺，使用 `domain_reviewer` 角色。
本工具不会生成专家身份或代签。密码学签名只核验声明来源，专家资质和科学正确性由维护者与专家承担。

开发集条目含完整 family 与 `expert_signature`；保留集只接收 `family_id`、`family_sha256`、`expert_statement`、`expert_signature` 四字段承诺，拒绝夹带输入或答案。
保留集专家声明必须是 `public_snapshot`，由托管方在私有环境中用 `review_statement` 从完整任务族生成。
第三方保管完整材料，以 `holdout_custodian` 角色、`pvl-holdout-custody-1` 域对 `custody_statement(pool)` 签名。信任表中的组织必须与库维护者和专家组织不同；同组织换一把密钥不算第三方。
托管签名绑定整份保留集与库身份，变更成员必须重新出具回执。签名是托管声明，不能独立证明服务器隔离或从未泄露。

公共导出采用字段白名单：只导出开发输入、承诺和状态，不包含参考答案、禁区标签或保留集输入。
候选库目标至少 30 族；确认评估要求**独立托管保留集**达到 `max(30, 功效所需族数, 显式 min_clusters)`。
开发族、同族改写和重复运行不填补保留集族数。示例功效参数 SD=.2、delta=.1、alpha=.05、power=.8 要求 32 族；30 不是普适功效下限。
达到入库数量也不自动升级裁决，仍须由既有评估器检查实际任务匹配、独立性、完整结果与所有门槛。

## 网关费用边界

现有父进程 `ModelGateway` 已接入 SQLite `RequestBudget`：每个请求在发送前以事务预留；同任务的多个进程共享账本；请求摘要绑定目的地、正文、路径和价目表；相同冻结会话和序号只能发送一次。
超单次或累计额度在网络请求前拒绝。崩溃、超时、取消、HTTP 错误、重定向和成功响应均不自动释放预留；成功响应中的 usage 不冒充结算账单。
现有显式 `settle`/历史对账接口仍由可信维护者根据账单操作，缺历史记录保持阻断。不能新建账本抹掉旧消费。

```sh
python scripts/gateway_budget.py
python scripts/gateway_budget.py --sandbox work/sandbox.json
```

第一个命令显示本地固定价目表摘要；第二个只读检查现有配置与账本，不创建账本、读凭据、启动子进程或调用模型。
在既有 sandbox JSON 的 gateway 中增加 `budget`：

```json
{"ledger":"C:/PVL-private/task-budget.sqlite","task_id":"existing-task-id","tariff_sha256":"COPY_FROM_READ_ONLY_INSPECTION"}
```

账本须由父控制器管理并保持在所有客体挂载目录之外。初始化使用既有 `RequestBudget.create`，必须显式提供历史库存和覆盖依据；恢复必须打开原账本。
配置和价目表绑定冻结会话。没有 budget 的旧在线配置、直接 Claude CLI 及未知模型仍保持阻断。执行还需既有 `--execute`、隔离预检与数据授权。

当前支持固定 `https://api.anthropic.com` 和快照模型 `claude-haiku-4-5-20251001`，标准 Messages API 的文本与客户端工具。
服务端工具、MCP、缓存、图片/PDF、thinking、beta、区域/快速计费、额外路径和未知字段均拒绝，不默默切换模型或价格。
该窄配置未完成真实 Claude CLI 兼容性验收；CLI 若发送这些额外字段会被拒绝。

计费依据核对于 2026-10-12：[官方模型规格](https://platform.claude.com/docs/en/models/haiku-4-5/overview) 为 200K 上下文、输入 $1/MTok、输出 $5/MTok。
[官方 token 计数说明](https://platform.claude.com/docs/en/build-with-claude/token-counting) 明确预先计数是估计，因此不用其结果充当最坏费用上界。
本版本保守预留 `200000 × 1 + max_tokens × 5` USD micros，覆盖完整输入窗口和最大输出，不依赖缓存命中或短提示词估计。
这是**以公开价目和上下文契约成立为条件的网关准入限制**，不是 Anthropic 账户侧硬支出上限，也不涵盖该凭据在网关外的其他消费者。
价目表在 2026-10-15 UTC 到期后拒绝请求，需重新核对源码价目、上下文契约并冻结，不能只延长日期。

当前用户授权仍是单次 $0.10、累计 $1。上述保守输入预留本身为 $0.20，所以本轮**没有解除当前模型的实际付费阻断**，没有提高额度或进行模型调用。
要在 $0.10 内启用，仍需提供方可强制的更小计费包络/定价合约，或另行批准适用的费用边界；不能用估计加任意百分比替代保证。

## 本地验证记录

完整层运行 1590 项，0 跳过；初次有 2 项旧原生采集测试仍模拟旧预算入口而报错。
已将这两处夹具接到新入口，原生采集、网关、账本、公共池与隔离桥共 77 项复测通过。
快速层 155 项通过，约 38 秒；不加载可选依赖时 16 项按 requires 跳过，其余通过。
另验证 CLI 可创建新输出目录、拒绝覆盖、正确报告 30 个候选；签名/并发/真实 HTTPS 代码路径均使用本地模拟响应。
完整层原始日志仍保留失败记录，不改写成一次全绿；这些检查不代表真实提供方、隔离内核、专家或托管方的验收。
