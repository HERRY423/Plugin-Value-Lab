# Plugin Value Lab 0.6.0 — native workflows and reusable scientific evidence

Version 0.6.0 brings the latest native execution, scientific artifact checks, repair comparisons and evidence handoffs into one versioned release.

## Changes

- **Native workflow:** reuse frozen official cases, probe Linux/WSL isolation and executable startup, authorize a single host attempt, retain failures and partial results, and recover collection without relaunching the model.
- **Analysis and repair:** bind foreground script calls to retained workspaces and frozen inputs; recompute scientific artifacts offline; compare complete before/after repair packages while retaining regressions and unresolved observations.
- **Falsifiable diagnosis:** connect six diagnostic stages to observed evidence and explicit predictions/falsifiers. Explicit-invocation probes remain separate from natural-use value evidence.
- **Scientific evaluation:** add prospectively frozen estimands, explicit failure classes, planned denominators and descriptive uncertainty; add donor-aware raw-count aggregation, a pinned PyDESeq2 backend and controlled error/valid-variation checks.
- **Reuse and guidance:** add registry-free pinned handoffs, separate scorer delivery, non-executing offline replay, scoped host/model/plugin/replicate comparisons and conditional guidance under frozen quality, cost and failure limits.
- **Packaging:** synchronize Python, runtime and all plugin manifests at 0.6.0. The marketplace and portable Agent Plugins packages include the latest documentation, examples and tests. Research/team extensions remain opt-in.

## Install

Use GitHub tag `v0.6.0` to pin this release. Choose the marketplace ZIP for the Codex/Claude-compatible repository layout, the Agent Plugins ZIP for the portable standard manifest, or the Python wheel. Extract ZIP files before loading them.

Python 3.11+ is required. After downloading the wheel:

```sh
python -m pip install "plugin_value_lab-0.6.0-py3-none-any.whl[mcp,science]"
```

Add the `pseudobulk` extra when running the optional PyDESeq2 reference backend. This GitHub release does not imply PyPI publication. Verify downloads using the attached SHA256SUMS.txt.

## Validation and evidence boundaries

Local Windows / Python 3.13 acceptance: **517 tests passed, zero failures, errors or skips**. Manifest validation and byte-identical marketplace checks passed. Current release acceptance is recorded in `VERIFICATION.json`; dated P0/P1/P2 and native-workflow receipts preserve their original versions and observations. The release packages contain public examples and evidence summaries, not private local studies or account configuration.

Prior native canaries and cached public-data computations are bounded observations. Missing Skill calls, uncertain sealing, failures and unknown settled costs remain visible. Offline replay creates no new independent observations. External independent reuse, expert scientific validation, cross-host benefit and researcher time savings remain unestablished. Software publication is not scientific certification or a claim of general availability.
