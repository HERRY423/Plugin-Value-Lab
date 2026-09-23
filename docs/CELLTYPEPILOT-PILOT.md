# First CellTypePilot marginal-value study

Status: **DRAFT_UNEXECUTED**. There are no real paired observations, real benefit estimates or independent reviews in this study. PVL remains 0.4.0-alpha.1. No release or DOI is claimed.

Question: under the same model, host, input data, tools and resource limits, does CellTypePilot improve valid single-cell analysis outcomes, while avoiding both unsupported acceptance and refusal of justified analysis?

## Protocol to freeze before collection

Target 10 tasks, 3 fresh repetitions per arm: **60 planned sessions**. Keep every failure, timeout, refusal, malformed artifact and negative result. Repetitions estimate run variability; they do not create 30 independent biological tasks. Cluster uncertainty by biological task family/donor, preserve family-level splits, and report small-sample limits. Freeze actual model identity, Claude Code version, plugin content digest, input hashes, policy thresholds, reference mappings and backend versions before the first session.

Both arms receive identical data, tools and permissions. WITH receives the frozen CellTypePilot package; WITHOUT has no CellTypePilot install, cached skill, global instructions, MCP server or residual artifact. Alternate arm order, use fresh workspaces and record native session IDs, actual tool calls, loaded-plugin evidence, output hashes, backend receipts, durations and all cost categories. Cost estimates and actual charges stay distinct. A prepared command or a doctor's package check is not observed loading or use.

The following are task specifications, not invented completed cases. Assign independent donors/families after dataset review; do not place transformed versions of the same source across development and heldout splits.

| Slot | Scientific task | Required scorer evidence |
| --- | --- | --- |
| 01 | Coarse PBMC cell-type assignment, donor A | Heldout orthogonal labels, frozen ontology mapping, full cell coverage, semantic label agreement plus ARI/NMI |
| 02 | Coarse assignment, independent donor B | Same contract, independent donor assignment |
| 03 | Mixed/ambiguous lymphocyte clusters | Predeclared ambiguity reference; justified uncertainty and preserved cell IDs |
| 04 | Rare population with sufficient measured support | Positive acceptance control; complete labels and frozen minimum support |
| 05 | Rare population with insufficient measured support | Unsupported-acceptance control, withhold unsupported subtype claims |
| 06 | RNA-only data asked to establish measured protein | Withhold measurement claim; do not transform RNA into protein evidence |
| 07 | Valid normalized expression asked for a bounded descriptive summary | Over-refusal control; finite, correct computational summary |
| 08 | Missing marker/reference evidence | Withhold the unsupported conclusion, preserve usable data and explicit limitations |
| 09 | Per-cell export after researcher-requested provisional review | h5ad/CSV schema, exact IDs, revision provenance; no invented human signature |
| 10 | Declared annotation backend unavailable or silently substituted | Runtime backend receipt, no hidden fallback; separate operational failure from biological validity |

Each label-based task must combine clustering agreement with semantic checks; ARI/NMI can be perfect when biological names are swapped. Decision criteria require both reasonable-analysis controls and insufficient-evidence controls. A correct refusal alone cannot substitute for successful outcomes on valid tasks.

## Data and truth admission

Candidate public source: [GEO GSE100866](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE100866), which lists PBMC paired RNA and antibody-derived tag material including PBMC-versus-flow files. This is a source candidate, not an ingested PVL dataset. Antibody abundance is a measurement, not automatically a gold cell-type label. Before use, confirm specimen/donor relationships, per-cell barcode alignment, reuse terms, raw measurement provenance, label derivation/gating and ambiguity policy with a domain reviewer. Record original file hashes, source citations, curator identity, rationale and conflicts. Do not infer FACS labels from a filename or promote author annotations into orthogonal experimental truth.

Keep scorer labels and marker-derived label construction out of agent-visible h5ad `obs`, `uns`, filenames, prompts and example outputs. Audit that the plugin's reference source does not duplicate heldout truth. Labels extracted from the same RNA markers cannot establish independent biological validation. If a source supplies no defensible orthogonal labels, revise the claim and dataset rather than filling missing truth with an LLM judgment.

Local preflight on 2026-09-23 UTC: CellTypePilot core dependencies were reported available by `doctor`. Several optional reference backends were unavailable; LLM SDK import did not verify credentials/network. The checked `public_v1/data` directory contained five gut/tumor/lung h5ad files and did not supply the requested PBMC truth pack. This inspection does not rule out suitable data elsewhere. Docker CLI was present but the daemon endpoint was unavailable.

## Remaining launch conditions

1. Freeze an actually acquired, licensed PBMC dataset with defensible scorer-only reference labels and curator-reviewed task validity.
2. Build and independently inspect the 10-case Scenario Pack, ensuring family/donor separation and no truth leakage.
3. Validate Claude artifact collection and runtime identity for both arms. PVL's current native exporter deliberately rejects scientific artifact graders; native regex/LLM grader results do not replace them. Host read access must exclude scorer material.
4. Make the pinned verifier environment available and test actual isolation. The local `exec` failure path is implemented; live container execution has not been established on this machine.
5. Review the precise external data/code scope and account-cost ceiling before model execution. No provider call, plugin upload or model expense has been incurred by this protocol. Set an explicit execution budget; 60 sessions plus any model judges cannot be assumed to fit an arbitrary small cap.

## Report regardless of outcome

Register planned/observed/failed sessions, every paired outcome, both error rates and their unresolved counts, task-family deltas, full cost coverage, backend discrepancies and negative/regressing cases. Include a standalone reproducibility bundle, private-scorer access instructions and review conflicts. Public release is a separate action after the actual report and data rights are reviewable. Zenodo metadata and a DOI follow a real deposit; documentation cannot create them.

The acceptance artifact from `scripts/check_science.py` is labeled synthetic and demonstrates software behavior only. It must never be inserted into this study as observed benefit.
