# Methodology for evaluating research plugins

**Source version 0.9.0; methodology revision 2026-10-03.**

Plugin Value Lab (PVL) evaluates submitted evidence about a plugin under a specified task and comparison protocol. Its central question is: **what changes when the plugin is available, for which tasks, at what cost, and with which unresolved risks?** A plugin installation, a successful tool call, a high standalone score and an incremental benefit are different findings.

This document describes the current evaluation method in English. It is intended for researchers designing a study, reviewers assessing its claims, and laboratories reproducing an analysis. Historical receipts retain their original dates, versions and limitations; this document does not retrospectively upgrade them. See [current evidence](EVIDENCE.md), [operational instructions](OPERATIONS.md), and the [implementation contract](../CONTRACT.md).

## 1. Define the claim before collecting outcomes

Specify the intended users, task distribution, permitted materials, success criteria, main endpoint, independent sampling unit, comparison, and decision thresholds. Freeze plugin bytes, rubric, reference artifacts, model and host conditions, repetition plan, failure rules, cost allocation, and stopping rule before examining study outcomes.

Include ordinary tasks, tasks where the baseline should suffice, and tasks requiring justified abstention. Avoid evaluating only demonstrations selected by the plugin author. Group related cases into task families using `cluster`; paraphrases and multiple stochastic completions of the same case are not independent task families. A declared cluster label is not verified independence.

A protocol hash binds a particular local specification. It does not prove independent preregistration, a valid scientific design, or an independent investigator. Keep development and rubric-calibration examples separate from held-out confirmation cases. Rules constructed by the evaluator are manufactured controls until supported by an appropriate scientific reference or actual domain review.

## 2. Collect matched WITH and WITHOUT arms

Use fresh sessions with the candidate plugin present and absent. Match the task, model configuration, host version, available non-candidate tools, data snapshot, permissions, environment and execution budget. Record actual observations separately from planned settings. Randomize or counterbalance execution order, and specify how repetition identifiers pair the arms. Check that the candidate is not otherwise available to the baseline.

If the plugin retrieves evidence unavailable to the baseline, the experiment may measure access enablement. It cannot isolate reasoning improvement on the same information. Supply an equivalent authorized snapshot to both arms when that is the intended claim. A simultaneous model, host and plugin change requires a different design; it is not a single-plugin effect.

Record provider-supported seeds when available. Otherwise describe repetitions as independent stochastic samples, with the request settings and native identifiers actually observed. Do not rename repetition numbers as controlled seeds. Matching numerical seeds does not guarantee shared randomness across different tools, providers or execution paths.

Three repetitions per condition can expose collection failures and initial variability. They do not establish general effectiveness or adequate statistical power. Increasing repetitions of four cases does not create more than four independent task families.

## 3. Retain every planned slot and each attempt

The planned case × condition × repetition matrix defines the denominator. Keep missing runs, timeouts, aborted runs, retries, refusals, condition deviations and incomplete reviews visible. Assign unique run/session identifiers, retain original outputs and receipts, and record retry ancestry rather than overwriting an unsuccessful attempt. Do not select the best completion from several attempts unless that selection rule was part of the frozen task and all its costs are included.

The current evaluator distinguishes known operational failure from missing evidence. An observed `error`, `timeout` or `aborted` execution receives operational score zero; an absent observation or unresolved completed-run outcome remains unknown. Both can prevent a complete comparison. Operational failure is not automatically scientific incorrectness or a defect caused by the plugin.

Observed outcomes are bounded by the available records. A native run aggregate alone cannot establish clean arm assignment, candidate loading, output-to-run identity, independent review or settled cost. Retain the underlying records needed to check each claim separately.

## 4. Assess task outcomes separately from process compliance

Use outcome graders for the researcher's actual deliverable. Reserve process checks for matters such as input integrity, environment identity or observed tool invocation. Process checks do not earn outcome credit, although a critical process failure can block a claim.

For a completed, fully assessed run, the quality score is the fraction of outcome-grader weight that passes. **Task success is a separate gate:** completion, the frozen quality floor, critical checks, and required decision, delivery and correctness evidence must all hold. A good average cannot compensate for a required correctness failure. Legacy text checks establish their configured predicates, not comprehensive semantic or biological correctness.

Where human judgment is required, retain the actual reviewer, decision and rationale. A model judge is a model assessment, not completed human review. Record its model, prompt, rubric and run identity; disclose overlap with the execution model and potential dependence. A reviewer packet that omits explicit arm labels is not proof of effective blinding: content may reveal the condition.

Calibrate graders with positive and negative examples, including reasonable output variants. Label similarity is not named-label correctness; arithmetic consistency is not correct donor assignment; a valid output file is not authenticated execution. Keep unsupported acceptance and excessive refusal separate. Neither approving unsupported science nor refusing an adequately supported result is desirable.

## 5. Estimate differences and report variability

Let `q[c,a,r]` denote the assessed quality for case `c`, arm `a`, and repetition `r`. For a complete case, compute each arm's mean over its frozen repetitions and the case difference:

```text
d[c] = mean_r(q[c,WITH,r]) - mean_r(q[c,WITHOUT,r])
```

The default primary summary weights cases equally. A prospectively selected `quality_weighting: family` first averages cases within each family and then weights families equally. The evaluator reports both views, but the frozen weighting controls its primary gate; do not choose the more favorable one after seeing results. See [quality summary implementation](../value_lab/value_metrics.py).

Study reports should also retain the repetition-level observations and report, for each case and arm, the sample size, mean, sample variance and standard deviation. For `n >= 2` observed values:

```text
s² = sum_r((q[r] - mean(q))²) / (n - 1)
SD = sqrt(s²)
```

With fewer than two values, variance is unknown. Label a variance calculated only among completed runs as conditional on completion; show operational failures and missing observations alongside it. Report paired-difference variability only for the prospectively defined complete pairs. Zero observed variance in a small sample is not proof of determinism. These reporting calculations supplement the core report; the presence of a bootstrap field does not mean per-arm sample variances were automatically computed.

The current core uncertainty calculation resamples whole task families, retaining their member cases, for 2,000 bootstrap draws with a fixed **analysis** seed. It reports an exploratory percentile 95% interval using the frozen weighting. That analysis seed is unrelated to model sampling seeds. Incomplete or confounded evidence makes the interval unavailable; fewer than two family labels cannot support it. The interval is explicitly `DESCRIPTIVE_ONLY`, unstable with few families, and not a causal test or a sequential guarantee. See [the implemented bootstrap and gates](../value_lab/core.py).

Prospective power planning requires an externally justified variability assumption, a meaningful target difference and independent sampling units. The optional normal-approximation family-mean plan is a planning aid, not achieved power or a confirmatory test. A confirmatory study needs an appropriate prespecified analysis, enough independent tasks, multiplicity control where applicable and independent replication. A nonsignificant difference does not establish equivalence or noninferiority.

### Plan task counts and repetitions before collection

The existing `plan-use` / `plan_plugin_use` entry accepts an evaluate context with `sample_size_plan`; [the runnable example](../examples/sample-size-plan.json) contains explicitly manufactured assumptions. `suite-check` and `validate_value_suite` also return planning results before any records exist. Copy the reviewed plan into `suite.policy.power_plan` and freeze it before collecting data; the full assumptions are included in the suite digest. The legacy four-field plan remains supported.

The v2 plan distinguishes **F independent task families**, **K sampled tasks per family**, and **R repetitions per task per arm**. Specify three standard deviations of WITH-minus-WITHOUT differences: between families, between tasks within families, and within-task repetition noise. These are not per-arm SDs. Under independent nested random components, the variance of a family mean is `family_sd² + task_sd²/K + repeat_sd²/(K*R)`. Increasing repetitions reduces the last term, not the family term. A 0.10 effect means ten absolute percentage points on the outcome quality score, not a 10% relative gain or an exact binary-success effect.

The planner compares the supplied K/R grid, returns F, total tasks `F*K`, generation runs `2*F*K*R`, conditional power, expected interval half-width and SD sensitivity scenarios. It searches for the smallest integer F satisfying the target; an insufficient search limit returns no feasible design. Optional effort weights account for family setup, task setup and generation. Without them, the recommendation minimizes generation runs within the grid; it is not a universal optimal design or cost estimate. Repeated judge votes do not increase the generation sample size.

`normal_approximation` works without additional dependencies. `paired_t` uses the noncentral t distribution and requires the optional `planning` dependency (`scipy`); missing support is reported, never silently replaced. Both test a two-sided null difference of zero against the chosen nonzero alternative, not a superiority margin. `comparisons` applies Bonferroni adjustment; optional stopping, choosing a favorable endpoint or post-hoc variance/effect tuning are not covered. SDs need an independent pilot, external estimate or explicit sensitivity assumption. With unknown SDs, PVL requests assumptions rather than inventing an exact number. For scarce or skewed/discrete family means, refine the design with task-specific simulation.

### Conditional confidence intervals

With a matching frozen v2 plan, declared independent representative family sampling, equal-family primary weighting and complete comparable observations, results include a fixed-sample **Hoeffding interval** for the bounded family differences in `[-1,1]`. Its half-width is `sqrt(2*log(2/adjusted_alpha)/F)` before intersecting the known parameter range. This is conservative and remains nonzero when all observed scores are equal. It needs independence, but not normality. A fixed convenience benchmark or unknown sampling basis does not get a population confidence claim.

When `paired_t` was selected, balanced family task counts and nonzero observed family variance additionally allow a model-based t interval over family means, with `F-1` degrees of freedom. Unequal family precision, zero variance, missing/confounded records or an unbound plan leave it unavailable with a reason. Repetition and judge counts never inflate degrees of freedom. Local hashes bind settings but do not establish prospective timing or independence. Synthetic results remain `SIMULATION_ONLY`; confidence intervals neither change adoption gates nor establish causality or biological validity. Detection of a nonzero effect is distinct from the interval's lower bound exceeding a practical gain threshold.

Methods: [paired t inference (NIST)](https://www.itl.nist.gov/div898/handbook/prc/section3/prc312.htm), [power reference (statsmodels)](https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestPower.html), [Hoeffding's bounded-sum inequality](https://doi.org/10.1080/01621459.1963.10500830), and [task/repetition allocation for algorithm comparisons](https://arxiv.org/abs/1808.02997). The three-level design is PVL's stated random-components model; reference citations do not validate its assumptions for a particular laboratory.

## 6. Preserve costs and time as separate quantities

Include failed attempts, retries, model judges, tool calls, setup, correction and review. Allocate shared overhead once under a frozen rule. Record model/tool cash, human labor and elapsed time separately. Human labor requires actual time intervals; overlapping intervals for one person must reconcile. Parallel actors' work time cannot be summed and described as elapsed task time.

Distinguish provider estimates, locally calculated prices, submitted settlement references and authenticated invoices. Category coverage is not settlement. A native USD field with unknown pricing basis is not a bill. Unknown cost remains unknown, never zero. The optional settled-cost gate requires the specified references and coverage but does not authenticate their issuer. Any labor-to-currency conversion must use the declared hourly valuation and remain distinguishable from cash expenditure.

Cost per successful outcome includes costs of unsuccessful attempts in its numerator. With no successful outcomes, it is undefined. Report mean cost differences with their sign convention: WITH minus WITHOUT, so a positive difference costs more. Lower reported cost is not a complete saving claim when relevant categories or reconciliation are missing.

## 7. Interpret the decision without changing the question

| Core result | Interpretation within the frozen scope |
| --- | --- |
| `SIMULATION_ONLY` | Manufactured observations can exercise the method; they do not measure real plugin benefit. |
| `INSUFFICIENT_EVIDENCE` | Required observations, comparability or evidence are incomplete. Inspect blockers instead of treating unknowns as passes. |
| `REGRESSION_DETECTED` | A critical failure, excessive case regression or configured error-limit violation blocks a positive result. |
| `NO_DEMONSTRATED_GAIN` | The supplied complete comparison does not meet its positive decision rule. This is not proof of equivalence. |
| `PROMISING_LOCAL_SIGNAL` | All configured evidence and success gates pass within the submitted scope. This is not general effectiveness, scientific validation or adoption. |

Under the default quality objective, a positive signal requires a strictly positive quality difference meeting the frozen threshold and quality floor, the applicable cost condition, all WITH task-success gates and no blocking regressions. The optional efficiency objective requires non-decreasing mean quality, the quality floor and strictly lower complete costs, while retaining the other gates. It is descriptive; it is not a statistical noninferiority design. Never switch objectives after observing a tie.

Success uplift, task-family summaries and observed failure-to-success or success-to-failure transitions are useful descriptive measures. They do not identify individual causal rescue or harm. A positive overall result cannot erase a negative case or an unresolved scientific requirement.

## 8. Treat host telemetry as another evidence layer

Keep request usage, response-time context samples, cumulative usage, cached tokens, compaction, model identity and execution identity distinct. Counter names are not portable semantics. An installed host version does not establish the producer version of an older log; a file hash binds bytes, not provider authenticity.

The [current multi-host acceptance record](history/MULTI-HOST-CONTEXT-20261003.zh-CN.md) distinguishes qualified Claude Code 2.1.288 and DSH session-v4 response samples from Antigravity's raw SQLite counters. Antigravity's normalized context remains unknown. These are local format-specific observations, not certification of every version, continuously measured live occupancy or installed-plugin behavior. Detailed, language-neutral counts and source bindings are in the [machine-readable receipt](evidence/multi-host-context-20261003.json).

## 9. Reproduce and update a study without rewriting its history

Retain the frozen suite and its digest, candidate bytes, input snapshots, run/attempt ledger, native identifiers, output artifacts, grader definitions, actual reviews, cost records, environment inventory and analysis outputs. Keep private scorer material outside the evaluated agent's inputs and out of public exports. Inspect permissions and data-sharing scope separately from a run budget. The [data-governance policy](DATA-GOVERNANCE.md) excludes identifiable patient information from ordinary records and sets the requirements for reviewed derivatives.

An offline replay checks retained evidence under a specified interpreter and implementation. Rescoring changes the assessment of existing observations. A new model run or scientific computation creates new execution evidence. None may be relabeled as another. Changes to the task, inputs, oracle, conditions or decision rule require the corresponding scope review or a new protocol; a newer parser does not retroactively authenticate an older result.

Start reproduction with the [English tutorial](START.md) and its supplied synthetic dataset. Real collection needs authorized materials and actual execution, followed by the same frozen scoring process. Paid execution gates, kernel isolation and host availability are separate operational requirements; a written method does not override them.

Only the root `docs/` and `docs/evidence/` are maintained sources. Repository marketplace entries resolve the canonical root. Packaging generates a complete installable tree under ignored `build/marketplace/` and archives under `dist/`, with member hashes. Generated copies are disposable transport artifacts, not additional evidence to maintain or independent observations. See [build and verification instructions](OPERATIONS.md#contributing-and-verifying-ci).

## Minimum reporting checklist

- Research question, target users/tasks, frozen protocol, candidate and baseline identities.
- Independent task-family count, repetitions, actual seed support, execution order and complete planned denominators.
- Actual conditions, original outputs, all failures/retries, unresolved observations and contamination checks.
- Outcome and process criteria, reference provenance, grader calibration, and the nature of human/model review.
- Prespecified primary endpoint and weighting, per-condition variability, paired effects, uncertainty method and its limitations.
- Complete or explicitly incomplete cash, labor and elapsed-time records, with settlement distinguished from estimates.
- Case-level regressions, successful and unsuccessful tasks, the exact supported claim, and remaining independent validation.
- Reproduction materials, private-material exclusions, software/environment identity, and a preserved revision history.
