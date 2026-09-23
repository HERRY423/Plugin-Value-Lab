---
name: use-plugin-well
description: Help choose the simplest available capability for a task and explain when or how to use a plugin. Use for task-fit guidance, "which capability should I use", or "is this worth trying"; use assess-value for designing or interpreting measured plugin comparisons. Discovery, connections, permissions, dependencies, and removal remain with Plugin Management or the host.
---

# Use a plugin well

Help the user complete their task with the smallest useful amount of setup. A routine task does not need a value study. Keep advice proportional to the decision: a one-time summary may need a direct answer; adopting a plugin across a team may justify a matched trial.

Build any structured context yourself from the user's natural request and actual host observations. Do not ask users to fill JSON or memorize state codes. Keep missing information unknown, continue independent work, and ask only when a task-critical clarification is needed.

## Start with the user's task

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

If available, `plan_plugin_use` accepts the context object in [WORKFLOW-CONTRACT.md](../../docs/WORKFLOW-CONTRACT.md). `build_plugin_usage_card` accepts the suite, raw records, and optional lock; it recomputes the assessment and returns bounded guidance. Call only tools actually exposed by the current host.

For files, resolve the plugin root from the actual location of this skill, verify `scripts/value_lab.py` and `CONTRACT.md`, and use Python 3.11+:

```text
python scripts/value_lab.py plan-use <context.json> --output <new-plan-directory>
python scripts/value_lab.py usage-card <suite.json> <runs.jsonl> --lock <lock.json> --output <new-card-directory>
```

Use absolute paths when outside the plugin root. `plan-use` writes `plan.json` and `PLAN.md`; `usage-card` writes `card.json` and `USAGE.md`. Both operate locally and do not execute the proposed actions. Availability observations are supplied records, not live verification; stale, missing, or untrusted readiness remains uncertain. The handoff contains only public capability keywords, an exact selected reference, and any explicitly requested management action/mode; it omits the private task summary.

For a team adoption decision that must persist across evaluations, use `team-card` with the current suite, raw records, an explicit `decision.json`, optional research context, and a new output directory. Pass the preceding `record.json` as `--previous` for each later revision. The team record retains prior cards and decisions, while changed conditions, tasks, evidence or research context trigger reassessment of old guidance. The declared team choice is not inferred from a score and does not authorize management actions. See [TEAM-RECORD.zh-CN.md](../../docs/TEAM-RECORD.zh-CN.md).

## Leave lifecycle controls with their owner

Use Plugin Management for discovery, dependency inspection, and user-requested inspection or changes to a named ChatGPT plugin. Permission inspection itself must correspond to an explicit user request for that plugin. A permission change or removal needs an explicit exact target and requested action; evaluation scores and recommendations provide no such authorization. Broad references such as "Google", "all", or "my plugins" are insufficient for per-plugin changes. App action permission modes do not themselves establish OAuth data-access scopes. Local code plugins use their own host's management flow; ChatGPT app permission and removal tools are not their lifecycle interface.

See the [complement guide](../../docs/PLUGIN-MANAGEMENT.zh-CN.md) for Chinese task examples, verified source boundaries, and the distinction between access value and quality gain.
