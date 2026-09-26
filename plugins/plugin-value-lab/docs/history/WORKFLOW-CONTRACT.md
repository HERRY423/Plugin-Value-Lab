> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# Task-first complement contract (v0.2)

Value Lab composes with Plugin Management through the host and explicit local handoff artifacts. It does not import another plugin's private runtime, make account changes, or require Plugin Management for offline use.

`value_lab.workflow.plan_plugin_use(context, now=None) -> dict` accepts JSON:

```json
{
  "schema_version": 1,
  "intent": "choose",
  "task": {"summary": "A local task description", "capability": "public concise capability keywords"},
  "native_fit": "insufficient",
  "connected_fit": "insufficient",
  "plugin_management_available": true,
  "selected_plugin": null,
  "evaluation_goal": "quality",
  "baseline_data_access": "unknown",
  "management": null
}
```

Intents: `choose|use|evaluate|manage`. Fit: `sufficient|insufficient|unknown`; these are supplied task-fit assessments, not measured plugin value. PM available is a host-observed boolean, never a connection claim for another plugin. Missing fit values mean unknown.

Optional selected_plugin: `{reference, display_name, version?, kind: chatgpt_plugin|local_code_plugin, installed: bool|null, connection_state: ready|pending|not_connected|unknown, observed_at: ISO-8601 timezone timestamp|null, status_source: plugin_management|host|user|local_manifest}`. Only fresh host/PM observations (within 24h; <=5min future skew) can establish availability for routing; installed is distinct from connection readiness. These timestamps are supplied records, not verified live observations. Pending suggestions must not be repeated.

Optional management: `{action: discover|inspect_permissions|inspect_dependencies|change_permissions|remove, explicit_request: bool, permission_mode?: inherit|always_ask|ask_before_writes|review_important_actions|full_access}`. Changes/removal require explicit exact target. Suggestions carry no mutation authority. Generic Google/all/global/my plugins are not exact per-plugin targets. Local code plugins do not route to ChatGPT permission/removal tools.

Output: `schema_version:1, type: plugin_use_plan, route, owner, headline, reasons:[string], steps:[{owner,action,purpose}], handoff:{kind,capability_query?,plugin_reference?,requested_action?,requested_permission_mode?,status,execute:false}, evidence_status, observations, comparison, limitations`. Handoff contains public capability keywords, an exact chosen reference, and an explicitly requested management action/mode when applicable; never the task's private summary, source files, full records or credentials. Recorded intent does not grant authority; user authorization must remain verifiable in the host conversation. No tool invocation is emitted as an executable action. `write_plan(plan, output_dir)` writes plan.json and PLAN.md to an empty directory.

Routes include USE_NATIVE, USE_CONNECTED, CHECK_EXISTING_CAPABILITIES, DISCOVER_MISSING_CAPABILITY, AWAIT_CONNECTION, VERIFY_CONNECTION, DESIGN_MATCHED_TRIAL, DESIGN_ACCESS_TRIAL, ALIGN_BASELINE_DATA, MANAGE_REQUEST, CLARIFY_MANAGEMENT, LOCAL_PLUGIN_MANAGEMENT. PM absence yields a host handoff, never falsely declares the target service unavailable or forces PM installation. Routine tasks do not require a study. Explicit evaluation/use intent is respected even if an alternative could be enough. Evaluation quality/efficiency requires same authorized input data; unique connector access is an access-enablement question, not automatically reasoning gain.

`value_lab.usage.build_usage_card(suite, records, lock=None) -> dict` recomputes `core.evaluate`; never accepts an arbitrary precomputed positive report. Card fields: schema_version, type=plugin_usage_card, plugin, study_id, verdict, status (TRIAL_GUIDANCE_ONLY|BOUNDED_LOCAL_GUIDANCE|REVIEW_REQUIRED), scope, use_when, prefer_baseline_when, investigate, next_steps, refresh_when, source, limitations. All scenario items are objects `{case_id,prompt,reason,quality_delta,cost_delta_usd}`. Global evidence blockers, regression or simulation prohibit use_when recommendations. Flat high-quality cases may appear as provisional baseline-sufficient observations only if whole study eligible and non-synthetic; no automatic removal. Supported use cases must individually meet the selected goal and applicable cost, floor, critical/regression gates; no claim beyond observed task. State limitations even for positive card.

Scope binds suite_sha256, records_sha256, plugin/version, model/host/tools/environment/budget; observed case prompts remain local. Refresh triggers version/configuration/model/task/data changes, not a scheduled monitor. `write_usage_card(card, output_dir)` writes card.json, USAGE.md and the offline single-page ENVELOPE.html to a new or empty directory. No recommendations to broaden permissions or uninstall are inferred from scores.

## Single-page usage envelope

The existing `usage-card` command and `build_plugin_usage_card` MCP response now include `envelope`. No new command or service is required. [Open the synthetic example](../../examples/usage-envelope/card/ENVELOPE.html); its observations are manufactured and cannot support real adoption.

Freeze optional `plugin.sha256` (lowercase SHA-256 of the evaluated content inventory) and explicit `conditions.host_version` / `conditions.model_version` with the suite. A model alias is not an observed revision. Missing or explicitly unknown/unverified identity prevents green guidance; old studies are not rewritten to fill it. `envelope.binding` also retains suite, records, conditions and cost-ledger digests. Content hashes are supplied bindings, not authentication of actual loading. Hash the evaluated plugin, not PVL itself unless PVL is the treatment.

Optional `task_families: ["family-a", "family-b"]` declares the intended family catalog. Rows use existing `case.cluster`; every observed cluster is retained even if absent from this catalog, and catalog entries with no observations are gray. All unlisted tasks remain outside the envelope. Adding a catalog or identity field changes the suite hash: freeze a new study before new collection, never rewrite past records to match. Repeated cases do not create independent families.

Each row contains quality difference (WITH minus WITHOUT, equal case weight within family), harmed pairs, over-refusal in both arms, full allocated cost per success in both arms, operational failure rates and sample size. Harm follows the existing frozen floor/critical-check success definition; unknown pairs remain unknown, not zero harm. Decision-error counts reuse the scientific and sealed-corpus checks, preserving planned repetitions and missing results. No configured over-refusal test means unmeasured, not zero. Failure rate uses planned arm executions; missing/skipped runs produce bounds, not a deceptively lower point rate. Outcome failures remain separately visible through quality and harmed pairs. Costs include failures and the existing shared-overhead allocation; incomplete coverage is unknown, and no successful outcome leaves cost per success undefined. Estimates/declarations are never relabeled settled cash.

Colors are a conservative presentation policy (`CONSERVATIVE_DISPLAY_V1`), not a change to the frozen study's verdict or statistical thresholds:

- **Gray:** no observed runs in the family, including a wholly unexecuted planned family.
- **Red:** observed harmed pairs, negative quality difference, WITH critical failures, WITH execution failures, or observed over-refusal; also a fully supported baseline-preferred family. The text distinguishes investigation from baseline preference. Red does not prove a causal plugin defect. Negative evidence is placed before the table and red rows sort first.
- **Green:** every case already meets existing positive local guidance; no observed negative item; identity binding is complete; all pairs and both-arm refusal rates are known; cost categories are complete and WITH cost per success is defined. Synthetic, blocked and globally regressed studies cannot be green. Zero baseline successes leaves its per-success cost undefined, not zero, without hiding the measured failure.
- **Yellow:** observed but incomplete, mixed, synthetic or no demonstrated benefit. Unmeasured refusal, missing identity or missing baseline cannot become green.

These stricter display rules do not reinterpret a configured tolerance as a statistical violation: even a tolerated adverse observation is surfaced for review. Each card lists invalidation on changed plugin bytes (even without a version bump), host/model revision, tools/environment/configuration/budget, task/data/rubric/objective, or new negative/cost/review evidence. `check_usage_envelope(card, plugin_sha256, conditions)` returns `STALE`, `UNKNOWN`, or `MATCHED_DECLARATIONS` for locally supplied identity; it does not monitor the environment or establish continued scientific validity. New observations require a new card, preserving the previous revision.

The HTML uses no scripts, network resources or remote fonts; labels accompany colors, text is escaped, and landscape print styling keeps small task catalogs compact. Large catalogs may span printed pages; rows are never silently truncated to claim a single sheet. `USAGE.md` starts with the same envelope and retains full diagnostics below it.

Public planning functions never import or call Plugin Management's private runtime. The host may carry a proposed handoff forward only using currently available tools and the actual user request. Offline evaluation remains usable when Plugin Management is absent.
