---
name: use-plugin-well
description: Help choose the simplest available capability for a task and explain when or how to use a plugin. Use for task-fit guidance, "which capability should I use", or "is this worth trying"; use assess-value for designing or interpreting measured plugin comparisons. Discovery, connections, permissions, dependencies, and removal remain with Plugin Management or the host.
---

# Use a plugin well

For users with PVL installed and callable in ChatGPT, follow the conversational [README](../../README.md): start with the named plugin and actual task, use available tools, and do not require terminal setup or file paths by default. The five-command local tutorial is a developer appendix; [START](../../docs/START.md) covers its timing. The [freeze](../../docs/FREEZE.md) permits this onboarding clarification without new interfaces. Never treat a maintainer or AI smoke run as non-author timing.

Help the user complete their task with the smallest useful amount of setup. A routine task does not need a value study. Keep advice proportional to the decision: a one-time summary may need a direct answer; adopting a plugin across a team may justify a matched trial.

Build any structured context yourself from the user's natural request and actual host observations. Do not ask users to fill JSON or memorize state codes. Keep missing information unknown, continue independent work, and ask only when a task-critical clarification is needed.

## Choose a task plan from evidence

When the user wants a reusable task-level choice and has or wants comparative evidence, use the existing `plan_plugin_use` with `context.task_selection` as described in [task selection](../../docs/history/TASK-SELECTION.zh-CN.md). Start with stages, actual data/design factors, output criteria and required researcher review. Inspect the candidate source and existing host capabilities to form native, existing script/workflow, and scoped plugin options. Do not assume a whole plugin is needed when only one stage is useful. Never hide a plugin dependency inside a purported zero-plugin script/workflow.

The planner recomputes complete frozen paired studies, rather than trusting native_fit, imported scores or a usage-card verdict. Keep candidate identities, input snapshot, conditions, decision factors, stage cases, integration cases and selection policy bound before collecting fresh records. Do not backfill observed component/input/plan fields from an intended execution plan, retrofit old studies or fabricate evidence to unlock a choice. Keep absent alternatives and costs unknown.

Explain the selected stages, conditions, required review, negative evidence and untested simpler options. A stage pass does not prove an untested composition. When native or existing scripts meet the same requirements, adding a plugin is unnecessary under the declared size objective. Equally small supported plans stay tied; ask for a meaningful user preference without inventing a performance ranking. A supported option with unresolved alternatives is not an established minimum. Synthetic data may illustrate the decision but never support a real recommendation. No plan establishes scientific truth, live connection, install authority, minimum monetary cost or user benefit.

Use the authorized artifact/scorer handoff for real files. `plan-use` also accepts `--artifacts` and `--verifiers` for local reviewable output. All planning remains read-only and rejects verifier program execution. This mode does not turn an ordinary one-time task into a compulsory study or override an explicitly selected provider.

For a prospective request to spend only on evidence that could change the choice, add `context.evidence_acquisition` using the [batch protocol](../../docs/history/TASK-SELECTION.zh-CN.md#序贯补证据). The Agent prepares and freezes the mother protocol before observations, retains its digest independently, and keeps every started batch and result in order. Use the returned next-batch alternatives, preserve the exact batch suite and lock before collecting, and append original observations; never fill observed identities from the intended plan. Explain the pivotal cases, cost cap, possible result branches and valid stopping state. Do not rerun already-resolved formatting checks merely to increase the number of tests. Do not retrofit old evidence as held-out confirmation, expose reserved confirmation materials during screening, reopen screening after confirmation, or delete unfinished runs. Unknown costs, incomplete batches or conflicts require repair/review, not a fresh purchase. A bound is a planning constraint, not payment authority or a guarantee that an external backend enforces it. No statistical error-control or real savings claim follows from this deterministic policy.

## Start with the user's task

For transfer from an existing study to a new matrix input, use `context.evidence_bridge` with the reviewed contract in [evidence bridging](../../docs/history/TASK-SELECTION.zh-CN.md#证据迁移与桥接). Keep the independently retained source commitment, identify one actually supported source plan and its original paired study, and provide authorized source/target input files. The Agent prepares the structured contract; do not ask researchers to fill JSON. Explain each difference and its handling. Do not infer scientific equivalence from text similarity or row permutation. Freeze the returned target protocol before collecting fresh observations; retain all target stages, integration checks, negative results and costs. Old session IDs, old producer files, cached success or a rewritten source cannot become a fresh target run. Only the built-in input-derived matrix/identity references may be regenerated from actual bytes; other criterion/design changes require a new study. Never put bridge evidence into acquisition screening implicitly, or transfer old adoption claims. Real source/target execution and reviewer identity remain unverified declarations unless separately established.

1. Respect an explicitly chosen provider. Do not silently replace it because a different tool seems sufficient.
2. For a general capability request, use an available native tool when it is sufficient, then an already connected plugin. Check available capabilities if their fit is unknown. These are task-fit judgments, not measured evidence of superiority.
3. If an external account, service, or data source is needed and existing capabilities are insufficient, ask Plugin Management to discover the missing capability. Pass concise, public capability keywords, not the user's full task, private files, research data, or credentials. Request only the smallest useful set, normally three or fewer.
4. Verify the selected plugin's actual connection before its tools are used. Installed, enabled, and connected are different states. A pending suggestion is not a new discovery opportunity: explain the remaining user action and continue independent work without repeating the suggestion.
5. If Plugin Management is unavailable, use the host's supported discovery or connection flow. Do not invent tool names, declare the desired service unavailable, or force installation of Plugin Management. Local Value Lab planning works independently.

The host executes connection and management actions; a Value Lab plan only records a proposed route. Do not claim that a plan connected or installed anything. Follow explicit session authorization for external calls and costs.

## Give useful guidance before demanding evidence

For a one-time task, briefly name the capability, explain why it fits, and do the authorized work. For uncertain fit, suggest one small reversible task the user already needs. Do not require an A/B experiment, package installation, permission inspection, or a formal report merely to proceed.

For "is it better?", "is it faster?", adoption decisions, or existing evaluation records, use [assess-value](../assess-value/SKILL.md). Access to otherwise inaccessible data can be useful, but it is not itself a reasoning improvement. To test quality or efficiency, both arms need the same authorized data snapshot. If this is impossible, frame the question as access enablement and report that limit.

An existing usage card can guide task choice only within its recorded plugin version, model, host, tools, environment, budget, and observed tasks. Do not generalize a successful case to unrelated work. Synthetic evidence, missing evidence, or regression supports investigation and trial guidance, not an endorsed use case. A low score is never authority to remove a plugin or broaden its permissions.

## Optional local artifacts

If available, `plan_plugin_use` accepts the context object in [WORKFLOW-CONTRACT.md](../../docs/history/WORKFLOW-CONTRACT.md). `build_plugin_usage_card` accepts the suite, raw records, and optional lock; it recomputes the assessment and returns bounded guidance. Call only tools actually exposed by the current host.

For files, resolve the plugin root from the actual location of this skill, verify `scripts/value_lab.py` and `CONTRACT.md`, and use Python 3.11+:

```text
python scripts/value_lab.py plan-use <context.json> --output <new-plan-directory>
python scripts/value_lab.py usage-card <suite.json> <runs.jsonl> --lock <lock.json> --output <new-card-directory>
```

Use absolute paths when outside the plugin root. `plan-use` writes `plan.json` and `PLAN.md`; `usage-card` writes `card.json`, `USAGE.md` and the single-page `ENVELOPE.html`. Show the envelope first: negative evidence precedes one row per task family, untested families are gray, and missing identity or unmeasured refusal prevents green guidance. Bind evaluated plugin bytes with frozen `plugin.sha256` and explicit host/model versions; do not rewrite old studies to fill missing identity. See the envelope contract in WORKFLOW-CONTRACT.md for invalidation and exact metric denominators. Both commands operate locally and do not execute the proposed actions. Availability observations are supplied records, not live verification; stale, missing, or untrusted readiness remains uncertain. The handoff contains only public capability keywords, an exact selected reference, and any explicitly requested management action/mode; it omits the private task summary.

For a team adoption decision that must persist across evaluations, use `team-card` with the current suite, raw records, an explicit `decision.json`, optional research context, and a new output directory. Pass the preceding `record.json` as `--previous` for each later revision. The team record retains prior cards and decisions, while changed conditions, tasks, evidence or research context trigger reassessment of old guidance. The declared team choice is not inferred from a score and does not authorize management actions. See [TEAM-RECORD.zh-CN.md](../../docs/history/TEAM-RECORD.zh-CN.md).

For matched studies with a decision policy frozen before collection, `conditional-guidance` can produce scenario-specific trial guidance within an exact target context. Do not invent thresholds after observing results, treat synthetic examples as adoption evidence, or generalize beyond recorded tasks. For reusable handoffs and the required inputs, see [P2 reuse and guidance](../../docs/history/P2-REUSE-GUIDANCE.zh-CN.md). Receipt consistency does not establish independent execution or participant identity.

## Leave lifecycle controls with their owner

Use Plugin Management for discovery, dependency inspection, and user-requested inspection or changes to a named ChatGPT plugin. Permission inspection itself must correspond to an explicit user request for that plugin. A permission change or removal needs an explicit exact target and requested action; evaluation scores and recommendations provide no such authorization. Broad references such as "Google", "all", or "my plugins" are insufficient for per-plugin changes. App action permission modes do not themselves establish OAuth data-access scopes. Local code plugins use their own host's management flow; ChatGPT app permission and removal tools are not their lifecycle interface.

See the [complement guide](../../docs/history/PLUGIN-MANAGEMENT.zh-CN.md) for Chinese task examples, verified source boundaries, and the distinction between access value and quality gain.
