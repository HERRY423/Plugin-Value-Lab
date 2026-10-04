# v0.9.0 maintenance and paid-execution addendum

Effective 2026-10-03 (America/Los_Angeles). This dated policy supplements the [published v0.9.0 release](https://github.com/HERRY423/Plugin-Value-Lab/releases/tag/v0.9.0). It does not replace its tag, executable code or original installation assets.

## Maintenance commitment / 最低维护承诺

- **Owner:** [@HERRY423](https://github.com/HERRY423), responsible for intake, compatibility decisions, remediation, releases and closure. **No backup maintainer is appointed.** There is no 24/7 coverage or commercial SLA.
- **Supported line:** the latest non-prerelease minor line at its newest patch, currently v0.9.0. Older minor lines have no routine backport promise. See [maintained environments](../API-STABILITY.md#maintained-environments): Python 3.11/3.13 and Windows/Ubuntu are CI support targets, not a claim that every environment passed. Optional dependencies and native isolation have separate requirements. Codex compatibility requires evidence for the exact build/model/workflow; synthetic telemetry tests do not establish live acceptance.
- **Serious issues:** P0 acknowledgement within 1 working day, assessment/mitigation or stop-use advice within 2 working days after acknowledgement, then daily updates; P1 acknowledgement within 2 working days, next action within 5 after acknowledgement, updates at least every 5 working days. Ordinary defects: acknowledge within 5 working days and triage within 10 after acknowledgement. Working days are Monday-Friday in America/Los_Angeles. These are prospective response commitments, not measured performance or guaranteed patch dates.
- **Procedure:** receive privately where needed, scope and contain, repair with retained regression evidence, publish a sanitized fix/mitigation and close with a recorded disposition. Missed targets receive a revised checkpoint. Planned absence requires a consenting replacement or visible support pause and release hold. See [SECURITY.md](../../SECURITY.md#serious-issue-response).
- **Review:** inspect issue/private-report inboxes each working day and before releases; review support/owner/channel at least every 90 days (first due 2027-01-01). Announce planned support reductions at least 30 calendar days ahead; emergency security withdrawals may be immediate. This is a commitment, not an installed automatic monitor. See [CONTRIBUTING.md](../../CONTRIBUTING.md#minimum-maintenance-commitment).

**私密漏洞入口：** [Report a vulnerability](https://github.com/HERRY423/Plugin-Value-Lab/security/advisories/new)（需 GitHub 登录）。实核 `private-vulnerability-reporting.enabled = true`，且公开安全页可找到入口。未提交测试漏洞报告，未实测通知投递或人工响应；也没有备份维护人。仅发送脱敏、最小复现材料，不提交患者数据、密钥或完整宿主会话。入口失效时只发不含漏洞细节的公开联络请求，等待恢复私密渠道。

The original [channel-check receipt](../evidence/maintenance-channel-20261003.json) is preserved unchanged. Its `policy_files_published_by_this_task: false` describes the earlier check, before this publication; it is not the status of this later addendum. It is evidence of configuration/discoverability, not a completed report-response drill.

## Paid execution / 付费边界

**Paid native evaluation remains unavailable. Neither this release addendum nor permission to spend enables a paid transport.**

| Artifact or source | Verified boundary |
| --- | --- |
| Original v0.9.0 tag, commit `b0ae821d7a7d9a5e2fc962c234206c38e80a0032` | `value_lab/native.py` rejects paid native execution with `BUDGET_BOUNDARY_UNAVAILABLE`. The original tagged assets do not contain the later `request_budget` module. |
| Post-release source, commit `b4f1596968c54e9039c7c3996009a807d48bc1bb`, `value_lab/request_budget.py` | `provider_cap_verified: false`; `paid_launch_authorized: false`. Durable local accounting and reservations are implemented; invoice authenticity and provider-enforced charging limits are not established. The native gate remains closed. |
| Offline preparation, import, validation and replay | These operations do not themselves dispatch paid model evaluations. This does not assert that the user's surrounding Codex session, subscriptions or other tools are free, or that historical liabilities are settled. |

`--max-cost-usd` is checked after requests and is an estimate, not a provider-enforced ceiling for an in-flight request. A lower estimate, token limit, timer, cancellation, user consent, passing local test or a locally reserved amount cannot supply that missing boundary. Exported commands are preparation material; manually executing them outside PVL bypasses its gate.

Before any future paid transport can be enabled, all of the following must be established:

1. Freeze the selected provider, exact model/host, operation, billing units/quantity/price conditions and data destination. Cover generation, judging, tools and any separately charged polling/retries. User spending authorization and authorization to send the specified data to the specified recipient are separate. Account/platform confirmation requirements still apply.
2. Verify an enforceable upper bound before each request and reserve it atomically in the same durable task ledger. Admission counts both settled charges and every unresolved reservation/maximum liability. Concurrent calls, retries, restarts, provider changes and new study IDs must not reset or expand the task budget. Personal agent limits and fixture/example amounts are not project defaults or proof that a provider/account limit is configured.
3. Keep each operation's original idempotency key, invocation/request ID, maximum authorized cost, status and settlement evidence. On timeout, disconnect, cancellation or an unknown result, reconcile that original attempt before another dispatch. Cancellation is not a refund. Never discard a reservation until settlement or release is evidenced; never create a new key merely to recover an unknown attempt.
4. If the verified request bound or remaining task budget is insufficient, stop before dispatch. A new provider, higher limit, subscription, top-up, automatic recharge or broader data destination requires its applicable authorization; do not silently change it. Unknown prior spending blocks new paid admission until reconciled.
5. Report settled cost separately from estimates, known subtotals, unresolved reservations and human time. Missing settlement stays **UNKNOWN**, never zero. Accounting evidence references alone are not authenticated invoices.

中文：当前两个资格标志都为 **false**，不能从“记账已实现”“预算写进计划”或“用户允许付费”推断可以启动付费执行。原版已有阻断门；后续源码的记账模块尚未提供供应商强制限额。断线、取消、重试均先对账原尝试，未结算费用继续保留，不能借新任务或新 key 重置额度。本次维护文档发布不调用付费目录服务，也不启动模型评估；既有评估的未知费用仍为 UNKNOWN。

See the [operations budget gate](../OPERATIONS.md#native-eval-budget-gate) for implementation boundaries. The maintenance response policy does not certify host acceptance, plugin benefit, scientific validity or paid-execution readiness.
