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

Scope binds suite_sha256, records_sha256, plugin/version, model/host/tools/environment/budget; observed case prompts remain local. Refresh triggers version/configuration/model/task/data changes, not a scheduled monitor. `write_usage_card(card, output_dir)` writes card.json and USAGE.md to a new or empty directory. No recommendations to broaden permissions or uninstall are inferred from scores.

Public planning functions never import or call Plugin Management's private runtime. The host may carry a proposed handoff forward only using currently available tools and the actual user request. Offline evaluation remains usable when Plugin Management is absent.
