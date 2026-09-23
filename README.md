# Plugin Value Lab

Measure and register the marginal value of scientific agent plugins under matched conditions.

[中文](README.zh-CN.md) · [Install](docs/INSTALL.md) · [Artifact verification](docs/ARTIFACTS.md) · [Codex collection](docs/CODEX.md)

Version remains **0.4.0-alpha.1**. Paired evaluation supplies the measurements; the durable assets are domain scenarios, actual studies and independent contributions. External adoption and authenticated independent reviews are not yet established.

## Accumulate evidence

- `corpus-seed` / `corpus-prepare`: eight synthetic executable scenarios across four task families, with public tasks and separately supplied answer keys. Development and heldout families stay separate; the public seed is not a secret benchmark.
- `registry-add` / `registry-view`: recompute studies, preserve immutable snapshots and display plugin × revision × model × host records, both unsupported acceptance and over-refusal, missing costs and dissent.
- `registry-export` / `registry-verify` / `registry-replay`: portable study submissions, byte verification and offline recomputation.
- `registry-review`: record real reviews, conflicts and replication links without treating declared identities as authenticated independence.

[Registry workflow and proposed interchange contract](docs/REGISTRY.zh-CN.md). These local commands neither run models nor publish submissions. Scenario validity, actual benefit and external participation still require real evidence.

Supplement missing evidence with `registry-add --parent ... --revision-reason ...`; previous snapshots and ancestor dissent remain visible within one study lineage. For review handoffs, use `registry-export --with-reviews` and verify the separately retained packet ID with `registry-verify --expected-id ...`.

## Start locally

Requires Python 3.11+. Run from your checkout or extracted plugin directory:

```sh
python scripts/value_lab.py doctor
python scripts/value_lab.py demo --output work/demo-1
```

Open `work/demo-1/report.html`. This first example is explicitly synthetic. For real records, freeze a protocol before collecting both arms:

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

[Phase 2 workflow](docs/PHASE2.md): freeze a shared host matrix, verify Codex collection receipts, inspect matched host contrasts and longitudinal gain drops, and build signed read-only registry snapshots. Positive public cards require a version-bound, trusted-key non-author review. Gemini/OpenCode execution adapters, real external studies and public deployment remain outstanding.

See the [scientific graders and Scenario Pack workflow](docs/SCIENTIFIC-VALIDATION.md), and the [first CellTypePilot study protocol](docs/CELLTYPEPILOT-PILOT.md). The protocol has no real observations yet.

- **Claude:** the local workbench freezes a plugin copy and runs native paired evaluations with explicit execution authorization. Start with `python scripts/value_lab.py workbench`. The separate [read-only native collector](docs/CLAUDE-COLLECTION.md) records per-session plugin/model metadata and grades collected JSON answer artifacts.
- **Codex:** `prepare-codex` freezes a plan; `run-codex` collects separate native sessions, raw events, output files, installation receipts and token usage. Runs have explicit count and time limits; the CLI does not enforce a dollar cap. [Details](docs/CODEX.md).
- Native configuration and installation are recorded separately from observed model identity, actual plugin loading, human review and settled cost. Missing evidence blocks a positive verdict.

## Evidence and scope

[Verification record](VERIFICATION.json) and [remediation status](docs/REMEDIATION.md) distinguish local tests, actual model runs and external studies. Automated tests use fixtures; passing them establishes software behavior, not biological validity or measured user benefit.

The [first real native audit pilot](docs/NATIVE-PILOT-20260923.zh-CN.md) collected all six scheduled Claude Code / DeepSeek sessions: five completed and one retained API failure. Registration, portable export and offline replay are complete. The verdict remains insufficient evidence; no broad plugin benefit or GA is claimed.

An offline decision benchmark such as Epistemic Plugin Arena asks whether a plugin improves action selection. Value Lab asks whether the plugin improves outcomes in matched host runs. `link-decision-evidence` binds the two evidence layers by hashes without pooling their scores. [Boundary and interchange](docs/EVIDENCE-LAYERS.md).

## Experimental extensions

Research planning and team records remain available for compatibility. They are outside the core scientific plugin measurement workflow and provide no observed plugin benefit by themselves.

[Protocol (中文)](docs/PROTOCOL.zh-CN.md) · [Review contract](CONTRACT.md) · [Costs and comparisons (中文)](docs/ANALYSIS.zh-CN.md) · [Research planning (中文)](docs/RESEARCH.zh-CN.md) · [Team records (中文)](docs/TEAM-RECORD.zh-CN.md)

## Development

```sh
python -m pip install ".[dev,mcp,science,registry]"
python scripts/check_release_tests.py
python scripts/build_marketplace.py --generate
python scripts/build_marketplace.py --check --package
```

The checked-in marketplace copy must match the source. CI checks Windows/Linux and Python 3.11/3.13, validates package manifests, and uploads build artifacts. A separate manual workflow can create a **draft** release for an existing version tag. Neither workflow calls a model; no release is automatically published.
