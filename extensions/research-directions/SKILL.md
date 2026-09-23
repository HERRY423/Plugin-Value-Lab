---
name: research-directions
description: Experimental extension for analyzing a research question and its authorized background to identify evidence gaps and feasible investigations. Use only for research planning requests; use assess-value for measured scientific plugin comparisons.
---

# Diagnose research directions (experimental extension)

Help the researcher decide what is worth learning next and what would change that decision. Build the analysis from the actual question, materials, and constraints; a generic checklist or a list of fashionable methods is not a completed diagnosis. Installation makes this skill available for host selection; it does not start a background analysis, monitor files, or contact services.

The host Agent performs the substantive reasoning. `research_direction_advisor` checks and organizes submitted reasoning locally; it does not read the user's files, search the literature, infer scientific truth, or generate a deep diagnosis from keywords. The workbench “研究方向诊断” is a place to inspect and revise that structured analysis. Do not make the user author JSON to receive help.

## Recover the question and the decision

Read only task-relevant materials already supplied or authorized. Preserve the researcher's question verbatim in `task.question`. Distinguish the question from the current preferred explanation, the decision the researcher needs to make, and what the available measurements can identify. Record important context in `task.background`, with `decision` and `domain` when useful. Do not silently replace a descriptive question with a causal one or expand the project into a clinical claim.

Build a compact evidence register before ranking directions. Give each distinct evidence item a stable ID, a factual summary, a locatable source, and a status: `observed`, `reported`, `hypothesis`, `unknown`, or `contradicted`. “Observed” describes what the cited material actually records; it does not independently validate the underlying experiment. Separate a reported result from your interpretation. Mark manufactured teaching contexts `evidence_type="synthetic"`; use `"local"` for actual submitted task material, which still is not independently verified. Missing evidence type remains undeclared. Do not turn an unsearched literature question into “no one has studied this.” Sources can be local file/section references; a generated ID is not provenance by itself.

Assess the dimensions that can affect this task: question, data, measurement, design, alternatives, robustness, generalization, reproducibility, resources, and impact. For each, submit a status (`covered`, `partial`, `missing`, `unknown`, or `not_applicable`), a task-specific rationale, and supporting evidence IDs. “Unknown” means the supplied information does not establish the answer; “missing” needs a reason the absent piece matters to this question. Give a concrete reason for `not_applicable`. These are review judgments, not a completeness score. Read the [research guide](../../docs/RESEARCH.zh-CN.md) for the object contract and local entry points.

## Develop competing, testable directions

For each consequential gap, explain which conclusion or decision it currently limits. Trace evidence IDs to that limitation and use `depends_on` to connect proposed work that cannot be interpreted until another direction is resolved. Avoid treating every missing checklist item as a new project. Consider when a narrower defensible question would remove an unnecessary dependency.

Develop a small set of distinct directions with the fields below. Prioritize the ones that could change the researcher's next decision, including the option to stop, narrow the claim, or retain a simpler explanation.

- `gap`, `dimension`, `kind`, and `why_now`: what is missing here and why it changes this task. Use `knowledge`, `evidence`, `method`, `capability`, or `resource`; a lack of donor replication is an evidence gap, not a plugin gap.
- `evidence_ids`: the actual observations, uncertainties, or contradictions motivating the direction. Preserve a weak or conflicting source as such; do not cite a hypothesis as established support.
- `alternative_explanation`: the strongest plausible rival interpretation or reason the proposed direction could be unnecessary. Describe what each explanation predicts differently. More software output is not automatically a discriminating observation.
- `next_test`: the smallest informative and feasible next step, with its input, comparison, and observable output. Prefer a check using existing authorized data when it can resolve the same uncertainty. Identify cases in which new sampling, measurement, domain review, or lab work is genuinely needed.
- `success_signal` and `stop_signal`: what would justify continuing versus revising, deferring, or abandoning the direction. Choose meaningful signals before looking at new outcomes. Do not invent a numerical threshold without a task-specific basis.
- `impact`, `uncertainty`, and `effort`: transparent 1–5 planning judgments with a rationale in the surrounding analysis. They are not probabilities, expected utility, scientific merit, or evidence of novelty. Enter `cost_usd` and `hours` only when grounded in an explicit estimate; otherwise use null. An unknown estimate cannot establish budget feasibility.

Include an adversarial pass: what plausible result would make the favored explanation less likely, what information is absent from the current measurement, and which uncertainty would survive even if every proposed computation succeeded? Also consider a non-expansion route: a narrower claim or stopping a low-information branch can be the most useful outcome. Do not manufacture an experiment just to fill every dimension.

Use current literature or authoritative methodology sources when the analysis depends on novelty, changing practice, an uncertain technical fact, or an external comparison. Use the tools and discovery rules actually available in the host. Verify citations and state what was checked. Keep source findings separate from your inference. Without a suitable search, retain the literature question as unverified. Do not send private documents, patient data, unpublished results, local paths, or the full context as a public search query.

## Produce a feasible next decision

Record the user's limits in `constraints` when provided: `budget_usd`, `hours_available`, and `max_next_actions` (1–5). Do not invent a budget from a generic preference for efficiency. Offer a small next-action menu, explaining dependencies, unknown estimates, and the decision each step informs. The local heuristic is `impact * uncertainty / effort`, with a bounded greedy selection under dependencies and cumulative resource caps; it is not an estimate of information gain or an optimal portfolio. Under a declared resource cap, a corresponding unknown estimate needs estimation before selection. A dependency selected in the same batch still needs actual verification before its dependent proposal can proceed. Inspect the order and explain its limits.

For a genuine capability gap, first use a sufficient native capability or an already connected plugin. If neither can provide the needed access or operation, hand Plugin Management or the host a minimal public capability query, such as “literature citation search” or “single-cell differential expression,” using `capability_query`. This field is a proposed handoff, not permission to transmit the rest of the context. Follow the host's discovery rules; use only actual available tools. Plugin Management owns discovery, connections, dependencies, and explicitly requested management actions. A plan neither installs a plugin nor proves that it is connected, and a scientific gap is not solved merely by installing one.

When available, call `research_direction_advisor(action="diagnose", context=...)` to validate and organize the context. Its `example` action supplies a teaching context, never observations from this user. For a local artifact, resolve the plugin root from this skill's actual location and run:

```text
python scripts/value_lab.py --enable-extensions research-plan <context.json> --output <new-directory>
```

This writes `research-plan.json` and `RESEARCH.md` to an absent or empty directory. Call only tools exposed by the host. Use absolute paths when outside the plugin root. If the tool is unavailable, still complete the authorized reasoning and clearly label it as an unvalidated draft; do not pretend a local validation ran.

Deliver the preserved question, the few consequential gaps, evidence-linked directions, strongest rival explanations, feasible first actions, and what remains unresolved. Present evidence and assumptions so the researcher can challenge individual items. Avoid an opaque single “research quality” score or claims of exhaustive coverage, novelty certification, biological validity, or independent review. Do not infer permission to launch proposed experiments, spend money, contact others, or publish from a planning request.

## Revise without erasing disagreement

When the researcher corrects a source, rejects a hypothesis, changes the question, or supplies new results, preserve the old context and create a new one with `revision_note`. Use stable IDs for the same items and new IDs for genuinely new items. Keep `proposed`, `accepted`, `deferred`, and `rejected` direction states distinct; do not mark a direction accepted on the researcher's behalf. Acceptance expresses a planning decision, not scientific confirmation.

Revisit directions downstream of changed evidence and dependencies, including directions that should now be withdrawn. Compare versions using `research_direction_advisor(action="compare", before=..., after=...)` or:

```text
python scripts/value_lab.py --enable-extensions research-compare <before-context.json> <after-context.json> --output <comparison.json>
```

Explain why priorities or limits changed and what disagreement remains. A structural difference shows which supplied records changed; it does not prove learning, research progress, or improved outcomes. If the user asks whether this workflow or another plugin actually helps, route to [assess-value](../assess-value/SKILL.md) for a separate matched evaluation.

If a proposed check has produced a new result, first preserve that result and its locatable source as a separate update. Use `research-followup <context.json> <update.json> --output <new-file>` or the workbench followup entry to identify the tested direction, downstream dependencies and other directions citing the same evidence. The submitted signal (`supports_favored`, `supports_rival`, `inconclusive`, or `conflicting`) is an interpretation to review, not a verified outcome. Discuss what changed the researcher's decision and what remains ambiguous, then create and compare a revised context only after correcting the underlying reasoning. Never mark a direction complete or unlock dependents from the signal label alone.
