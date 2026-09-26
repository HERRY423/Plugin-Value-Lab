# Single-page envelope example

All observations here are **synthetic**. The red failures and harmed pair are manufactured display fixtures; no plugin, host, model or person was evaluated. Unknown identity remains unknown. Ontology mapping and ligand–receptor analysis are explicitly unmeasured gray rows, not additional observations.

Open [card/ENVELOPE.html](card/ENVELOPE.html) for the single-page view or [card/USAGE.md](card/USAGE.md) for the same summary with full diagnostics. JSON retains every metric and binding.

Recompute locally from the repository root with a new output directory:

```sh
python scripts/value_lab.py usage-card examples/usage-envelope/suite.json examples/usage-envelope/runs.jsonl --lock examples/usage-envelope/protocol.lock.json --cost-ledger examples/usage-envelope/cost-ledger.json --output envelope-replay
```

No network, model, installation or account changes. For real studies, freeze actual `plugin.sha256`, explicit `conditions.host_version` / `model_version` and intended `task_families` before collection. Never add synthetic values or rewrite historical records to obtain a green cell.
