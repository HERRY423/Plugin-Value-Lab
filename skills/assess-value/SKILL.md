---
name: assess-value
description: Assess a plugin's incremental benefit with matched with/without baselines, outcome grading, complete cost records, and explicit evidence limits. Use when designing plugin comparisons or interpreting existing plugin evals.
---

# Assess plugin value

Help the user decide what the plugin adds, for which tasks, and at what cost. A working plugin, a triggered skill, and a high standalone score answer different questions from incremental benefit.

## Choose the useful mode

- Keep the default workflow to paired measurement, diagnosis and retesting. Research direction planning is a disabled experimental extension, available only when explicitly requested and enabled; see [scope and opt-in](../../docs/STRUCTURAL-RISKS.zh-CN.md).
- For choosing an available capability or explaining how to use a plugin, use [use-plugin-well](../use-plugin-well/SKILL.md). Do not require a study for an ordinary one-time task. Discovery, connection, dependencies, and requested account management belong to Plugin Management or the host, not this evaluator.
- For an inline comparison or a conceptual question, reason directly from the supplied facts. Do not require shell access or create a study just to explain an obvious result. Identify missing evidence and qualify the conclusion; an aggregate supplied in chat is not an audited run ledger.
- For a new evaluation, build and freeze a suite before collecting fresh runs. Use the CLI and the [protocol](../../docs/PROTOCOL.zh-CN.md).
- For existing artifacts, preserve the originals, evaluate the records, and distinguish observed evidence from declared settings. Do not fill gaps with assumed successful runs.
- For product design and the meaning of different value claims, read the [design rationale](../../docs/DESIGN.zh-CN.md).

## Comparisons that answer the question

For an author repairing a plugin, generate a usage card from the submitted suite, records, lock and available artifact/cost roots. Its `improvement_plan` locates failed or unknown criteria in both arms and preserves the full frozen case set for retesting. Show the most actionable evidence before proposing another run. Execution failures are not proven plugin defects. No registry entry, public score or certification is required. Never claim the checklist saves time without real comparative human timing and cost evidence. Preserve all failures and negative results; use a new study and plugin content hash for the repair, without requiring a version bump.

For rubric calibration, version/model comparisons and detailed costs, read [ANALYSIS.zh-CN.md](../../docs/ANALYSIS.zh-CN.md). Use `check-rules` or `validate_value_suite(..., samples=...)` before freezing; sample grading is not study evidence. Workbench “以此方案准备版本 / 模型对照” copies the protocol, not observations. Compare existing studies in the workbench or with `compare-studies BEFORE AFTER --output JSON`; preserve task/rule/condition changes and never attribute a simultaneous plugin/model change to one factor. For supplemental costs, pass the same `cost_ledger` to evaluation and usage-card generation. Workbench cost revisions preserve original artifacts and bind the new report to source hashes. Do not claim complete costs from a known subtotal, price an unknown token count, double-add native batch estimates, or convert estimated charges into settled bills.

Define the intended users, tasks, and decision before selecting cases. Include ordinary tasks, tasks where the plugin should add little, and cases requiring refusal, uncertainty, or abstention. Use a held-out set for a later claim about generalization. Split related cases by `cluster`; paraphrases and repeated generations of the same task are not independent observations.

Compare fresh sessions with the plugin loaded and absent. Keep model, host, available tools, environment, task prompt, and budget identical except for the evaluated plugin. Record the exact plugin version and evidence type. Randomize or counterbalance execution order when running a study. If the plugin exists elsewhere in the baseline environment, the baseline is contaminated.

Keep authorized input data identical as well. A connector that retrieves otherwise unavailable material may add access value; this does not establish better reasoning on the same material. For quality or efficiency comparisons, provide the same authorized snapshot to both arms. If that is not possible, state the access asymmetry and design a separate access-enablement question. Reading one source does not authorize exporting its private contents to another service.

Grade the user's outcome. Record activation, tool calls, or workflow compliance separately as process diagnostics. Process success contributes no outcome quality. A model that uses the required skill and produces a wrong answer fails the relevant outcome criterion. A model that succeeds without the plugin deserves its full baseline score.

Do not equate a 100% with-plugin score with gain: 100% versus 100% is zero measured quality gain. If cost is lower, report that as a separate cost result when costs are complete and quality floors hold. Missing baseline, mismatched conditions, missing planned records, failed runs, unknown grades, unknown costs, or unreviewed human criteria limit the conclusion; never silently drop them.

## Local execution

For outcome files, use the `artifact` or `executable` graders documented in [ARTIFACTS.md](../../docs/ARTIFACTS.md). Supply collected artifact roots explicitly; a model's text or imported Boolean is not a file verifier receipt. Custom Python verifiers require a reviewed, frozen code hash and explicit trusted verifier root. CLI evaluation, usage cards and comparisons can recheck the actual bytes. Object-only MCP calls leave artifact checks unresolved.

For Codex native sessions, use [CODEX.md](../../docs/CODEX.md): prepare a frozen counterbalanced study with `prepare-codex`, then run the exact plan with `run-codex` within the user's existing authorization. Record code/data egress and account costs. A configured model, installed plugin or synthetic subprocess fixture does not establish observed conditions, actual loading or cross-host benefit. Preserve missing provenance and costs; do not relabel them to make the study pass.

For a visual workflow, launch `python scripts/value_lab.py workbench --data <absolute-writable-study-directory> --port 8766` from the resolved plugin root. Open the printed loopback URL. Read [the workbench guide](../../docs/WORKBENCH.zh-CN.md). The form prepares a frozen plugin copy and exact native command without model calls. The user can then authorize one Claude evaluation with its explicit model and estimated budget. Respect existing authorization; do not create an additional approval flow outside the concrete launch step. Never auto-click execution for a request to merely inspect or demonstrate the UI. The first backend uses read-only tools and mocked MCP, does not publish, and does not retry paid calls. It captures process receipts, native JSON, logs and available artifacts. Native aggregates still cannot authenticate per-run conditions, plugin loading, final output mapping, human review or settled costs. Do not turn an execution receipt into a complete value-study verdict. The six MCP tools remain local analysis tools; they do not launch the workbench or models.

If the plugin's local MCP tools are available, use `validate_value_suite` to check a supplied suite, `evaluate_plugin_value` for supplied records and lock objects, `inspect_claude_eval` for native diagnostic objects, and `example_value_suite` for a template with zero observations. These tools do not read arbitrary files, create a lock or report artifact, or execute a model. Use the CLI when the user needs on-disk study files, a review packet, or reports. Do not call unavailable tool names or claim a configured MCP connection is already verified.

Resolve the plugin root from the actual absolute location of this `SKILL.md`: it is two parent directories above the `assess-value` directory. Verify that the resolved root contains `scripts/value_lab.py` and `CONTRACT.md`. Do not assume the user's current working directory is the plugin root, search the whole drive, or assume an environment variable named `PLUGIN_ROOT` exists. Claude may provide `${CLAUDE_PLUGIN_ROOT}`; use its expanded value only when the host supplies it and verify the same files. If the installed skill is detached from the plugin scripts, explain that the local evaluator is unavailable and continue with the evidence review possible from supplied materials.

Use a Python 3.11+ interpreter available on the host. From the resolved plugin root, the commands are:

```text
python scripts/value_lab.py doctor
python scripts/value_lab.py init --output <study-directory>
python scripts/value_lab.py freeze <suite.json> --lock <lock.json>
python scripts/value_lab.py evaluate <suite.json> <runs.jsonl> --lock <lock.json> --output <report-directory>
```

Pass actual absolute paths when running from another directory. Read [CONTRACT.md](../../CONTRACT.md) for the exact schema. Before a real collection, replace example model, host, environment, tools, budget, plugin identity, and graders with actual study settings. A lock establishes local consistency; it does not prove independent preregistration.

`demo --output <directory>` generates synthetic records for a walkthrough. `export-claude <suite.json> --output <directory> --plugin <plugin-path>` prepares native Claude cases. `import-claude <result.json> --suite <suite.json> --output <runs.jsonl>` preserves import gaps as evidence issues. These operations do not themselves run billable model evaluations. Do not represent an export or import as an actual host execution. Follow the user's existing authorization and budget before any external execution, installation, or publication.

Use `native-report <result.json> --output <directory>` to inspect existing native diagnostics without pretending they are a complete local study. Native export turns human rubrics into model-judge diagnostics, not completed human review; unsupported exact JSON graders are refused rather than weakened. Read the generated export manifest before following its planned execution arguments.

For real human assessment, use `review-pack <suite.json> <runs.jsonl> --output <directory>`. Give the reviewer only the generated `reviewer` folder and retain the `operator-only` mapping separately. This removes explicit arm labels but is not technical blinding; the output may reveal its source. Merge actual decisions with `apply-reviews <suite.json> <runs.jsonl> --mapping <mapping.json> --decisions <decisions.jsonl> --output <new-runs.jsonl>`, then evaluate the new record file. Never fill the human decisions yourself or claim that generated packet IDs establish independence.

## Costs, uncertainty, and reports

For the rigor workflow see [RIGOR.zh-CN.md](../../docs/RIGOR.zh-CN.md). `verify-host-study` checks either supported native collection offline; registration of a recognized native archive rechecks it and requires the actual plugin inventory digest. Cross-host contrasts require explicit model/host versions, not matching aliases alone. For DE tables, freeze an independent `testing_family` reference to detect selective gene reporting before BH verification. Optional `policy.decision_error_limits` must constrain both unsupported acceptance and over-refusal; unknown rates block and WITH-arm violations prevent a positive signal. A critical process check must pass but contributes no outcome credit.

Before replaying an exported study, use `registry-replay-plan BUNDLE --expected-id RETAINED_ID` with separately provided scorer/corpus roots as needed. Preflight never executes verifier code. `registry-replay --expected-id RETAINED_ID --require-same-environment` checks identity and rejects missing/different runtime inventory before scoring. Private scoring material is not automatically exported. Reproducing the same incomplete report is not a complete validation: inspect `assessment_complete`, original verdict, runtime differences and scientific limitations. Never treat a native-verification summary as a replacement for the original native archive.

Keep model charges, tool charges, human work, and wall-clock duration distinct. Human work comes from raw time intervals, with overlap checks. Null costs are unknown, not zero. Native reported dollar amounts can be estimates, not settled invoices. A declared zero human interval list is not independently observed zero effort. Use the user's stated hourly valuation for an explicit cost conversion; do not invent revenue, willingness to pay, or clinical savings.

Use the evaluator's recorded decision rules, case regressions, critical outcome failures, completeness checks, and cluster uncertainty together. Do not override a failed gate because the overall average looks attractive. A small or selected local suite supports a narrow local signal, not a population-wide benefit claim. Synthetic evidence stays a simulation even if every apparent comparison is positive.

Choose `policy.objective` before collecting results. The default `quality` goal requires a strictly positive quality delta as well as the configured threshold and floor. Equal quality with lower costs does not pass that default gate. The optional `efficiency` goal instead requires non-decreasing mean quality, the quality floor, and strictly lower complete costs; `min_quality_delta` does not apply to that goal. Both goals preserve critical-failure and per-case-regression limits. Cost completeness is required even when cost saving is not required. An efficiency signal is descriptive, not a statistical noninferiority claim; the cluster interval is not a significance test or causal claim. Do not switch goals after seeing the result just to obtain a pass.

Deliver the report and explain: outcome difference, cost difference or missingness, failure/regression cases, uncertainty, the limited decision supported, and the next evidence needed. Keep source outputs and review rationales available for inspection. Human grades need an actual reviewer and rationale; never invent approvals or independent reviewers.

To turn completed records into future task guidance, use `build_plugin_usage_card` when actually available, or `usage-card <suite.json> <runs.jsonl> --lock <lock.json> --output <new-directory>`. It recomputes the assessment and binds the result to those records, plugin/version, model, host, tools, environment, and budget. It must not recommend use from synthetic evidence, blocked comparisons, or regressions; unsupported tasks remain investigation or trial guidance. A baseline-sufficient case is not authorization to disable or remove a plugin. A score never authorizes broader permissions. Check the usage card's scope again after inputs or conditions change; no monitor is created automatically.

## Scientific examples

For independent-unit scientific results, use the 0.5.0 `replicate_effect` contract and `replicate-reference` command described in `docs/REPLICATE-VERIFICATION.zh-CN.md`. Freeze units, blocks or pairs, all features, training-unit exclusions, exchangeability justification and thresholds before candidate evaluation. This verifier recomputes prepared unit measurements; it does not normalize raw counts or authenticate donors. Correct non-significant findings pass. Keep reference answers out of heldout agent inputs.

When supplementing a registered study, preserve the frozen suite, observation time, authors and plugin identity; use `registry-add --parent <entry-id> --revision-reason <actual-change>`. Count its lineage once, keep superseded snapshots and surface ancestor dissent. A new protocol requires a new study. For review handoffs use `registry-export --with-reviews`, retain the returned packet ID separately, and verify with `registry-verify --expected-id`. Ordinary study exports omit reviews and cannot establish absence of dissent. A reproduced calculation does not resolve disputes or authenticate reviewers.

For accumulating studies over time, use the local registry workflow in [REGISTRY.zh-CN.md](../../docs/REGISTRY.zh-CN.md): `registry-add` recomputes source observations into an immutable bundle; `registry-view` retains failures, unknown costs, both decision-error types and dissent; `registry-export`/`registry-replay` support another author's inspection. `registry-review` records only actual supplied reviews and never authenticates independence. Do not invent reviewers, adoption, or real runs to populate a registry. `corpus-prepare` produces a public suite; keep `answers.private.json` outside the evaluated host's accessible inputs and supply it only to offline `evaluate --corpus`. The generated seed is synthetic and public, not a genuinely unexposed heldout benchmark. Claude native export currently refuses sealed graders; do not weaken them to a textual check.

The [scientific suite](../../examples/scientific-suite.json) is a tutorial about reviewing evidence and preserving warranted uncertainty. It contains no measured biological data and proves no scientific validity. Correctly identifying absent donor replication or withholding an unsupported conclusion can be a successful outcome. Over-refusal on an adequately specified question is also a failure to retain useful work. Require real domain adjudication before making scientific claims from a real study; neither this plugin, synthetic cases, local tests, nor an LLM grader supplies that authority.
