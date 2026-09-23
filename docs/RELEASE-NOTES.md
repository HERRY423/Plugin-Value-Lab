# Plugin Value Lab 0.5.0 — executable scientific evidence

Scientific artifacts can contain plausible numbers while using the wrong independent unit, omitting tests or reporting an unsupported conclusion. Version 0.5.0 adds a bounded `replicate_effect` verifier that recomputes scientific results from frozen independent-unit measurements.

- **Independent units and design:** reject repeated donors in independent designs, incomplete pairs, completely confounded batches and declared training/evaluation overlap. Permutations preserve blocks or pairs.
- **Recomputed outcomes:** compare treatment-control effects, exact two-sided p values, complete-family BH values, sample counts, frozen-threshold decisions and leave-one-unit effect ranges. Correct non-significant findings are valid outcomes.
- **Portable evidence:** design/data commitments join replay dependency preflight. Bundle identity, environment checks and field-level differences distinguish recomputation from complete or scientifically valid evidence.
- **Cross-host and methodology:** unified Codex/Claude archive verification; requested settings are not observations; process checks do not add outcome points; unsupported acceptance and over-refusal have separate limits; unknown costs remain unknown.
- **Value measures:** success uplift, rescued and harmed pairs, family-level gains, time and cost per successful task; prospective task-family sample planning remains distinct from a confirmatory test.
- **Release consistency:** Python/runtime/plugin versions are all 0.5.0; Git preserves frozen bytes across operating systems. Research/team extensions remain opt-in. Epistemic Plugin Arena remains future outlook.

## Install

Choose the marketplace ZIP for the Codex/Claude-compatible repository layout, the Agent Plugins ZIP for the portable standard manifest, or the Python wheel. Extract ZIP files before loading them. Python 3.11+ is required; install the `mcp` extra for MCP and `science` for h5ad/SciPy support. Core deterministic verification uses the standard library.

```sh
python -m pip install "plugin_value_lab-0.5.0-py3-none-any.whl[mcp,science]"
```

This command installs a downloaded wheel; this release does not imply PyPI publication. See attached checksums and the repository installation guide.

## Evidence boundaries

Tests include adversarial fixtures and independent SciPy numerical checks. Public examples are synthetic teaching material, not a hidden benchmark. The verifier accepts already prepared unit-level measurements; it does not validate normalization, raw-count models, biological identity, exchangeability or hidden training exposure. Exact enumeration has fixed resource limits and no silent approximate fallback.

No new real model trial, cross-host benefit study, external expert review or biological validation is claimed. The historical native pilot remains evidence-limited and is preserved separately in `VERIFICATION.json`. Computational agreement does not establish scientific truth or plugin efficacy.
