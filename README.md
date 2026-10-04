# Plugin Value Lab

**Determine whether a plugin improves a specific task through paired comparisons, frozen plans, and recomputable results.**

Compare the same task with and without the plugin, fix the evaluation rules before collecting results, and recompute the difference from original records. Missing evidence remains unknown.

**Version 0.9.0.** Start in chat once PVL is installed and callable. Give the plugin name and one concrete task; the host handles plans and records.

[中文](README.zh-CN.md) · [Getting started](docs/START.md) · [Advanced guide](docs/history/ADVANCED.md) · [Current evidence](docs/EVIDENCE.md)

## Start with one question

> Use Plugin Value Lab to determine whether [plugin] improves [specific task]. Check the available tools, propose a paired with/without comparison, and freeze the inputs, success criteria and run conditions before collecting results. Recompute the difference from original records and show the uncertainty, failures and missing evidence. Use existing records where suitable; follow existing authorization for new runs.

For example: does a literature-search plugin find more verifiable primary papers for the same research question, with fewer unsupported claims?

## One evaluation, three steps

| Step | What it means |
| --- | --- |
| **Pair** | Compare with-plugin and no-plugin runs on the same tasks and authorized inputs, under comparable models and budgets, with independent records. |
| **Freeze** | Fix cases, success criteria, conditions and the sampling plan before observation. Plan task counts and repetitions for a meaningful effect size. |
| **Recompute** | Score original records using the frozen rules. Report differences, failures, costs and confidence intervals where the design supports them. |

The host coordinates execution; PVL checks supplied plans and analyzes supplied records. A plugin name alone does not launch isolated sessions or recover historical logs. Alternating “use the plugin” and “do not use it” in one chat does not establish independent arms. Freezing already observed data is a retrospective check, not preregistration.

## What you receive

A task-level comparison: **with plugin → without plugin → difference → uncertainty → evidence**. Read it as an answer about the tested task, plugin, model and conditions.

| Finding | Interpretation |
| --- | --- |
| A positive observed difference | A gain was observed under the reported conditions; uncertainty and evidence limits still apply. |
| No difference or a regression | No added gain was observed, or performance worsened; retain the original failures. |
| Incomplete or incomparable evidence | Benefit remains unestablished. Missing baselines and costs are unknown, not zero. |
| Synthetic example | Demonstrates the calculation and report, not real plugin benefit. |

Files and independent execution depend on host capabilities. Existing-record analysis can proceed locally. Paid native eval launches remain blocked until a reliable spend boundary is available; see [operations](docs/OPERATIONS.md).

## Install

Plugin installation does not install the Python package. Running Plugin Value Lab analyses, `doctor` checks, or the local stdio MCP server requires Python 3.11+.

### 1. ChatGPT / Codex repo marketplace

Add the repository marketplace:

```bash
codex plugin marketplace add HERRY423/Plugin-Value-Lab --ref main
```

Restart the ChatGPT desktop app, open the Plugins Directory, select **Plugin Value Lab Marketplace**, and install **Plugin Value Lab**. Repo marketplaces are for development, team distribution, and testing; they are separate from the universal public Plugins Directory.

When the public submission is approved and published, search the universal Plugins Directory for **Plugin Value Lab** instead; one public listing is shared by supported ChatGPT and Codex surfaces.

### 2. Claude Code marketplace

```bash
claude plugin marketplace add HERRY423/Plugin-Value-Lab
claude plugin install plugin-value-lab@plugin-value-lab-marketplace
```

Start a fresh session after installation:

```bash
claude
```

## Developer appendix: local reproduction and file reports

Ordinary users of the installed plugin do not need this section. It is for maintainers, local archival and troubleshooting.

Use Python 3.11+ from the unpacked project root. These five commands process **synthetic records**, without calling a model or target plugin. To repeat them, consistently replace `work/first-run` with a fresh directory.

```sh
python scripts/value_lab.py doctor
python scripts/value_lab.py freeze examples/first-run/suite.json --lock work/first-run/protocol.lock.json
python scripts/value_lab.py evaluate examples/first-run/suite.json examples/first-run/runs.jsonl --lock work/first-run/protocol.lock.json --cost-ledger examples/first-run/cost-ledger.json --output work/first-run/report
python scripts/value_lab.py usage-card examples/first-run/suite.json examples/first-run/runs.jsonl --lock work/first-run/protocol.lock.json --cost-ledger examples/first-run/cost-ledger.json --output work/first-run/usage
python scripts/value_lab.py compare-studies examples/first-run/before.json examples/first-run/after.json --output work/first-run/comparison.json
```

Start with `work/first-run/usage/USAGE.md` or `ENVELOPE.html`. Full scores are in `work/first-run/report/report.html`, `report.md` and `report.json`; the comparison is `work/first-run/comparison.json`. The expected tutorial verdict is `SIMULATION_ONLY`. `freeze` collects no sessions, and `evaluate` scores supplied records; your own study needs real observations first.

- [Local tutorial](docs/START.md) · [Research methods](docs/METHODOLOGY.md) · [Advanced guide](docs/history/ADVANCED.md)
- [Current evidence](docs/EVIDENCE.md) · [Operations and troubleshooting](docs/OPERATIONS.md) · [Interface freeze](docs/FREEZE.md)

[![CI](https://github.com/HERRY423/Plugin-Value-Lab/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/HERRY423/Plugin-Value-Lab/actions/workflows/ci.yml)

The badge reports the main branch, not unpushed changes. Source checks do not establish installed-host acceptance or scientific benefit.

Project policies: [citation](CITATION.cff) · [maintenance and owner](CONTRIBUTING.md#minimum-maintenance-commitment) · [security reports](SECURITY.md) · [contributing](CONTRIBUTING.md) · [compatibility scope](docs/API-STABILITY.md#maintained-environments) · [data governance](docs/DATA-GOVERNANCE.md). Identifiable patient data must not enter ordinary records or prompts; de-identified derivatives still require data-owner approval.

Maintainer: **@HERRY423**. Report vulnerabilities through the **[private GitHub channel](https://github.com/HERRY423/Plugin-Value-Lab/security/advisories/new)**; do not include exploit details or sensitive material in public issues. P0/P1 acknowledgement commitments are 1/2 working days, with scope and escalation in [SECURITY.md](SECURITY.md#serious-issue-response).

The [v0.9.0 maintenance and paid-execution addendum](docs/history/MAINTENANCE-AND-PAID-BOUNDARY-20261003.md) records the release-specific policy. Paid native execution remains blocked; local accounting has `provider_cap_verified: false` and `paid_launch_authorized: false`.
