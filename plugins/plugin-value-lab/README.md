# Plugin Value Lab

Help plugin authors locate failures in paired runs and prepare a fair retest after a repair.

[中文](README.zh-CN.md) · [Install](docs/INSTALL.md) · [Artifact verification](docs/ARTIFACTS.md) · [Codex collection](docs/CODEX.md)

Version **0.5.0**. Independent-unit scientific recomputation is now available: [design, methods and limits](docs/REPLICATE-VERIFICATION.zh-CN.md). Paired evaluation supplies the measurements; the durable assets are domain scenarios, actual studies and independent contributions. External adoption and authenticated independent reviews are not yet established.

## Install in Codex desktop

Open **Plugins → Add → Add plugin marketplace** and use the configuration verified in a successful installation:

| Field | Value |
| --- | --- |
| Source | `HERRY423/Plugin-Value-Lab` |
| Git reference | `main` |
| Sparse paths | **Leave empty**; do not enter the gray `plugins/codex` placeholder |

After adding the marketplace, search for **Plugin Value Lab**, then **install and enable** it. Adding a marketplace does not install its plugins. Start a new task, select Plugin Value Lab with `@`, and ask: “Call example_value_suite, then validate the suite. Do not start a model evaluation.”

All six default MCP tools were called from the installed 0.5.0 plugin on 2026-09-23; scientific artifact checks and relocated offline replay also passed. [Acceptance scope and results](docs/INSTALLED-ACCEPTANCE-20260923.zh-CN.md) · [Installation and troubleshooting](docs/INSTALL.md). Python 3.11+ and a compatible MCP SDK are required for MCP; an already working environment needs no reinstall.

## First useful result: an author repair checklist

Use existing paired records to locate execution failures, unresolved evidence and failed criteria in both arms. The usage card now includes an evidence-linked improvement queue and a full retest plan preserving cases, thresholds and negative controls. The workbench displays the same checklist and can copy the frozen protocol for the next study. You do not need to register a study or publish a score.

This is a testable adoption hypothesis, not established time savings. The next product milestone is one consenting external author completing a narrow repair cycle, with actual timing, costs, negative feedback and independent review. See [the three structural risks and scope gate](docs/STRUCTURAL-RISKS.zh-CN.md).

## Optional local ledger

The registry retains immutable studies, failures, review disagreements and portable replay. Its JSON/HTML and signed snapshots now expose a cold-start stage: empty, synthetic-only, local pilot or unverified external submissions. All remain a **provisional local format**, not an established trusted evidence layer. Revisions do not become independent observations; declarations, hashes and signatures do not establish adoption.

[Registry workflow](docs/REGISTRY.zh-CN.md). Local diagnosis works before any external network exists. No external invitations, publication or model calls are required for that workflow.

## Start locally

Requires Python 3.11+. Run from your checkout or extracted plugin directory:

```sh
python scripts/value_lab.py doctor
python scripts/value_lab.py demo --output work/demo-1
python scripts/value_lab.py usage-card work/demo-1/suite.json work/demo-1/runs.jsonl --lock work/demo-1/protocol.lock.json --output work/author-card
```

Open `work/author-card/USAGE.md` for the checklist and `work/demo-1/report.html` for the scores. This first example is explicitly synthetic. For real records, freeze a protocol before collecting both arms:

```sh
python scripts/value_lab.py freeze suite.json --lock protocol.lock.json
python scripts/value_lab.py evaluate suite.json runs.jsonl --lock protocol.lock.json --artifacts collected-files --output report
```

## Outcome checks

| Check | What is verified |
| --- | --- |
| `artifact` / `de_table` | Unique gene IDs, finite effects, probability bounds, BH correction over the supplied full testing family |
| `artifact` / `labels` | Per-cell labels and exact entity coverage against a frozen reference |
| `artifact` / `h5ad` | Shape, unique IDs, required observation fields; needs optional `science` dependencies |
| `artifact` / `json_fields` | Typed values in a collected JSON artifact |
| `executable` | Explicitly trusted, SHA-256 pinned Python verifier with a timeout and structured result |
| Text / JSON / human | Existing literal rules, exact JSON fields, and actual human review |

Missing artifacts, changed hashes, missing dependencies and verifier failures remain unresolved. See the [contracts and executable example](docs/ARTIFACTS.md).

## Host execution

[Executable rigor across hosts, science and replay](docs/RIGOR.zh-CN.md): unified offline native verification, version-bound host contrasts, frozen DE testing universes, bidirectional decision-error ceilings and non-executing replay preflight. These extend evidence discipline without implying a completed cross-host benefit study.

[Phase 2 workflow](docs/PHASE2.md): freeze a shared host matrix, verify Codex collection receipts, inspect matched host contrasts and longitudinal gain drops, and build signed read-only registry snapshots. Positive public cards require a version-bound, trusted-key non-author review. Gemini/OpenCode execution adapters, real external studies and public deployment remain outstanding.

See the [scientific graders and Scenario Pack workflow](docs/SCIENTIFIC-VALIDATION.md), and the [first CellTypePilot study protocol](docs/CELLTYPEPILOT-PILOT.md). The protocol has no real observations yet.

- **Claude:** the local workbench freezes a plugin copy and runs native paired evaluations with explicit execution authorization. Start with `python scripts/value_lab.py workbench`. The separate [read-only native collector](docs/CLAUDE-COLLECTION.md) records per-session plugin/model metadata and grades collected JSON answer artifacts.
- **Codex:** `prepare-codex` freezes a plan; `run-codex` collects separate native sessions, raw events, output files, installation receipts and token usage. Runs have explicit count and time limits; the CLI does not enforce a dollar cap. [Details](docs/CODEX.md).
- Native configuration and installation are recorded separately from observed model identity, actual plugin loading, human review and settled cost. Missing evidence blocks a positive verdict.

## Evidence and scope

[Verification record](VERIFICATION.json) and [remediation status](docs/REMEDIATION.md) distinguish local tests, actual model runs and external studies. Automated tests use fixtures; passing them establishes software behavior, not biological validity or measured user benefit.

The [first real native audit pilot](docs/NATIVE-PILOT-20260923.zh-CN.md) collected all six scheduled Claude Code / DeepSeek sessions: five completed and one retained API failure. Registration, portable export and offline replay are complete. The verdict remains insufficient evidence; no broad plugin benefit or GA is claimed.

Reports now expose task success uplift, rescued versus harmed pairs, productive-task versus abstention outcomes, time saved and full cost per successful outcome. Optional frozen power planning counts independent task families, not repeated runs. Settlement references are distinguished from estimated cost coverage. See [value metrics and confirmation design](docs/VALUE-METRICS.zh-CN.md).

## Future outlook: Epistemic Plugin Arena

**Epistemic Plugin Arena is a proposed future direction**, not an established external project, current dependency or integrated benchmark. It could evaluate offline action selection alongside Value Lab's matched host outcomes if a public specification, implementation and validation become available. The current `link-decision-evidence` command is a generic hash-bound reference mechanism; it does not establish an Arena integration or pool scores. [Current boundary and future conditions](docs/EVIDENCE-LAYERS.md).

## Experimental extensions

Research planning and team records are **disabled by default** in CLI, MCP and the workbench. Use `--enable-extensions` before the CLI command to opt in. The research skill lives under `extensions/`, outside default skill discovery. Compatibility code and old records are retained. The default plugin exposes six MCP tools and two skills; no runtime module was added for this repair.

[Protocol (中文)](docs/PROTOCOL.zh-CN.md) · [Review contract](CONTRACT.md) · [Costs and comparisons (中文)](docs/ANALYSIS.zh-CN.md) · [Research planning (中文)](docs/RESEARCH.zh-CN.md) · [Team records (中文)](docs/TEAM-RECORD.zh-CN.md)

## Development

```sh
python -m pip install ".[dev,mcp,science,registry]"
python scripts/check_release_tests.py
python scripts/build_marketplace.py --generate
python scripts/build_marketplace.py --check --package
```

The checked-in marketplace copy must match the source. CI checks Windows/Linux and Python 3.11/3.13, validates package manifests, and uploads build artifacts. A separate manual workflow can create a **draft** release for an existing version tag. Neither workflow calls a model; no release is automatically published.
