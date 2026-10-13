<img src="assets/plugin-value-lab.png" alt="Plugin Value Lab scientific balance icon" width="88" height="88">

# Plugin Value Lab

**Does this plugin actually improve your task?**

[中文](README.md) · English

Plugin Value Lab helps you decide whether a plugin is worth using for a **specific task**, through paired comparisons, frozen plans, and recomputable records. Compare runs with and without a plugin while keeping failures, costs, uncertainty, and missing evidence visible. **Version 1.0.0-rc.5.** This is a release candidate.

[Download rc5](https://github.com/HERRY423/Plugin-Value-Lab/releases/tag/v1.0.0rc5) · [Five-step quickstart](#five-step-quickstart-no-model-calls) · [Methods and implementation records](docs/history/INDEX.md)

## When to use it

| Your decision | How Plugin Value Lab helps |
| --- | --- |
| Whether to add a plugin to a task | Define the task, baseline, success criteria, and paired conditions; freeze the plan before evaluation |
| Whether a plugin update is better | Recompute differences from existing records, compare studies, and retain regressions and critical failures |
| Which candidate plugin to choose | Combine evidence with user-supplied losses for false adoption, missed benefit, and time to recommend a scoped action |
| How to explain a result to colleagues | Produce a usage card, HTML report, and machine-readable records with scope, validity window, and next steps |

The host orchestrates task execution. Supplying a plugin name alone does not start independent experimental arms or recover historical logs. Results apply only to the tasks, models, and conditions represented in the records.

## Install in Codex

You need Python **3.11+**, available as `python` when Codex starts the plugin. The MCP server requires an additional dependency. From the repository or extracted plugin root, install it into the Python environment used by the host:

```sh
python -m pip install -r requirements-mcp.txt
```

On the Codex plugins page, choose **Add plugin marketplace** and enter:

| Field | Value |
| --- | --- |
| Source | `HERRY423/Plugin-Value-Lab` |
| Git reference | `v1.0.0rc5` to pin rc5; use `main` for subsequent source updates |
| Sparse paths | Leave blank |

Then select and install **Plugin Value Lab** from the marketplace. The repository includes the balance icon and its manifest configuration.

Alternatively, download `plugin-value-lab-marketplace-1.0.0-rc.5.zip` from the [Release](https://github.com/HERRY423/Plugin-Value-Lab/releases/tag/v1.0.0rc5), extract it, and add the marketplace from a local folder. Select the **root containing `.agents/plugins/marketplace.json`** and preserve the full directory structure. The Python wheel is a separate CLI/library distribution; installing it does not register the plugin in Codex.

After installation, try this prompt:

> Assess whether [plugin] improves [specific task]. First inspect available tools, the baseline, and existing records; propose a paired design and freeze the conditions. Respect data permissions and the budget when collecting new records, then report differences, uncertainty, and failures.

## Five-step quickstart: no model calls

Download and extract the repository source, then run these commands from its root. This example processes bundled synthetic records only. Core recomputation uses the Python standard library and does not require MCP dependencies. For another run, replace every occurrence of `work/first-run` with a new directory to preserve existing records.

```sh
python scripts/value_lab.py doctor
python scripts/value_lab.py freeze examples/first-run/suite.json --lock work/first-run/protocol.lock.json
python scripts/value_lab.py evaluate examples/first-run/suite.json examples/first-run/runs.jsonl --lock work/first-run/protocol.lock.json --cost-ledger examples/first-run/cost-ledger.json --output work/first-run/report
python scripts/value_lab.py usage-card examples/first-run/suite.json examples/first-run/runs.jsonl --lock work/first-run/protocol.lock.json --cost-ledger examples/first-run/cost-ledger.json --output work/first-run/usage
python scripts/value_lab.py compare-studies examples/first-run/before.json examples/first-run/after.json --output work/first-run/comparison.json
```

Open `work/first-run/usage/USAGE.md` or `ENVELOPE.html` in the same directory. Full fields are in `card.json`; the study comparison is in `work/first-run/comparison.json`. The expected result is **`SIMULATION_ONLY`**: it demonstrates the workflow, not real plugin benefit. Locking data after observing it checks consistency; it is not preregistration.

## Interpret the result

```text
What do you have?
├─ A plugin name or idea → Define the task, success criteria, and baseline first.
│  └─ Before new runs → Set effect thresholds, variance sources, independent
│                       task-family counts, and budget; then freeze the plan.
├─ Real paired records → Check completeness, comparability, failures, and cost.
│  ├─ Missing, confounded, or incomplete → Insufficient evidence; keep UNKNOWN.
│  ├─ Regression or critical failure → Retain the negative result and investigate.
│  ├─ Positive difference, too few families → At most a trial-only signal.
│  └─ Plan and all gates met → A local signal within the tested conditions.
└─ Synthetic examples only → SIMULATION_ONLY; no claim of real benefit.
```

**Repeated runs do not replace independent task families.** When `min_clusters` is omitted, the descriptive floor is 3. With a frozen `power_plan`, the requirement is the larger of that floor and the planned family count. Explicitly lowering `min_clusters` cannot bypass the power plan. Unknown required counts or unmet planning conditions prevent upgrading a positive conclusion. Meeting a power target alone does not demonstrate effectiveness; v3 confirmatory rules have additional independent gates.

## Advanced capabilities and status

| Capability | Current status and limits |
| --- | --- |
| [Action decision layer](docs/history/20261012-ACTION-DECISION.md) | Implements four recommendations: scoped adoption, guarded trial, baseline by default, and avoid. Includes multi-candidate rotation, shrinkage displays, and simultaneous rank intervals. Shrinkage cannot replace independent confirmation; example losses are not user preferences. |
| [Public evidence pool and gateway](docs/history/20261012-POOL-GATEWAY.md) | All [30 candidate slots](examples/literature-pool/candidates.json) are synthetic placeholders. Expert review and third-party custody are pending. A real held-out set needs at least `max(30, families required by the power plan)` independent families; variants within a family do not increase this count. |
| [L0–L3 evidence ladder](docs/history/20261012-EVIDENCE-LADDER-DESIGN.md) | **Design only, not implemented** (`DESIGN_FOR_REVIEW / NOT_IMPLEMENTED`). Current v3 rules use a fixed sample and do not provide the design's sequential-stopping guarantees. |

## Data, costs, and security

- The local example makes no model calls. Real runs require explicit data permissions, a provider, and a budget. Keep sensitive data out of public examples and reports.
- The parent-process gateway reserves cumulative costs before sending requests and rejects over-budget calls. The conservative envelope in the rc5 tariff configuration exceeds the $0.10 per-call limit, so actual paid calls remain blocked; expired configurations are also rejected. Gateway limits are separate from provider account limits.
- Use provider login or an operating-system credential manager. Keep credentials out of repositories, command lines, cards, and logs. Ignore rules do not remove secrets from existing commits; revoke and replace exposed credentials at the provider.
- Report vulnerabilities through the [private reporting channel](https://github.com/HERRY423/Plugin-Value-Lab/security/advisories/new). See the [security policy](docs/history/20261011/SECURITY.md) and [data governance](docs/history/20261011/docs/DATA-GOVERNANCE.md).

## Development and verification

```sh
python scripts/run_tests.py fast
python scripts/run_tests.py full
python scripts/run_tests.py full --require-all
```

The fast tier covers core decisions, cards, power planning, and selected regressions, and fails if it exceeds 120 seconds. The full tier discovers all tests. Missing optional dependencies cause explicit skips; **a skipped test is not acceptance of that feature**. Release validation uses `full --require-all` and rejects every skip.

Optional dependencies are listed in [pyproject.toml](pyproject.toml): `dev`, `mcp`, `planning`, `registry`, `science`, and `pseudobulk`. Install only what your task requires. Native isolation, real backends, and workflows have separate CI checks. Passing engineering tests does not establish real plugin benefit or scientific validity.

[Contributing](docs/history/20261011/CONTRIBUTING.md) · [API stability](docs/history/20261011/docs/API-STABILITY.md) · [rc5 release notes](docs/history/RELEASE-v1.0.0rc5.md) · [Historical documentation index](docs/history/INDEX.md)

Some linked implementation records are in Chinese. Archiving documents does not revoke maintenance or security policies. Licensed under [Apache-2.0](LICENSE); citation metadata is available in [CITATION.cff](CITATION.cff).
