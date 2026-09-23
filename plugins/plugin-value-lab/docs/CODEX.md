# Codex CLI paired collection

The adapter uses the locally inspected Codex CLI interface. `prepare-codex` performs local preflight and freezes a plugin snapshot, protocol and counterbalanced schedule without invoking a model.

```sh
python scripts/value_lab.py prepare-codex examples/codex-pilot-suite.json --plugin . --output work/codex-study-1
```

Set the suite's model to one available to your account before preparing. The example consists of two disclosed hypothetical tasks, not biological observations or a representative held-out benefit study. `evidence_type: local` describes the planned model collection, not the truth of the hypothetical scenario. An unexecuted suite is not evidence.

After reviewing the frozen plan, an authorized run is:

```sh
python scripts/value_lab.py run-codex work/codex-study-1 --plan-sha256 <printed-hash> --auth-home <existing-codex-home>
```

This sends task/plugin material to the configured Codex provider and uses its account. The adapter requires existing file-based `auth.json`, temporarily copies it into each isolated home, and removes that copy on normal exit or a handled error. It never prints credentials. A hard machine/process crash can leave a temporary copy: protect the entire study directory and remove `runs/*/home/auth.json` after checking an interrupted run. Keyring-only login is not supported by this adapter.

Each arm gets a fresh home, a fresh workspace/project boundary and a fresh session. Only the WITH home receives the native marketplace installation. The schedule alternates order across pairs. Process counts and per-run timeouts are frozen. A started plan cannot be run again; failures and interruptions require inspection, not automatic retry. Codex CLI has no enforced dollar ceiling, so `max_cost_usd` is rejected instead of presented as a spending guarantee. Token usage is recorded separately from unknown settled charges.

## Inputs and output files

Declare input paths and their SHA-256 values in each case's `inputs` mapping. Pass the actual source directory with `prepare-codex --inputs <root>`. Both arms receive the same frozen bytes. Input paths cannot inject `.git`, `.agents`, `.codex` or `AGENTS.md` configuration.

```json
{
  "inputs": {"data/table.csv":"<SHA-256>"},
  "output_artifacts": {"de":"results/de.tsv"}
}
```

The default execution sandbox is `read-only`. For tasks that must write files, explicitly set `conditions.sandbox` to `workspace-write` before freezing. Artifacts are collected after the process exits and hashed. Missing files remain missing. `answer` is reserved for the final answer collected from native events. Executable grading still requires a subsequent explicit `evaluate --verifiers` call.

## What the records establish

`setup.json`, `launch.json`, `events.jsonl`, `events.stderr`, `receipt.json`, `runs.jsonl` and `execution-summary.json` preserve local process events, raw output, session IDs, token usage and failures. The ordinary evaluator is used for the report.

The adapter does **not** populate observed conditions or `plugin_loaded` from the requested command line. It does not treat installation as activation, assume inherited global skills cannot contaminate baseline, invent human intervals, or price token usage as settled spending. Those missing observations intentionally block a positive value verdict. Session IDs and local files are not independent attestation. Cross-host evidence requires actual comparable studies on both hosts; adding this backend does not supply them.

During the current remediation, authenticated execution was blocked by automatic approval review because code egress and unknown account costs were not explicitly authorized. The frozen pilot has zero actual model runs. See [remediation status](REMEDIATION.md).
