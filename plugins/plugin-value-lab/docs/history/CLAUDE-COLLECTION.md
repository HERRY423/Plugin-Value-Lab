> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# Read-only native Claude Code collection

This collector supports one bounded profile: scientific audit questions answered as JSON with only `Read` and `Skill` available. It does not execute a generated analysis script. The final native answer becomes the `answer` artifact and is graded from its original bytes.

```sh
python scripts/value_lab.py prepare-claude-collection suite.json --plugin candidate-plugin --inputs task-inputs --output study
python scripts/value_lab.py run-claude-collection study --plan-sha256 PLAN_SHA256 --auth-home EXISTING_CLAUDE_CONFIG
python scripts/value_lab.py verify-claude-collection study
```

Preparation makes no model calls. It freezes the suite, protocol, plugin files, input hashes, executable, collector source, complete alternating-arm schedule and run/time/turn/native-budget limits. Use a new directory for each protocol. An exclusive execution marker prevents a restart from repeating possibly charged calls. Execution stops on an unsuccessful native result and retains failures and missing scheduled runs.

After inspecting a known terminated prefix, an operator can explicitly add `--continue-unstarted` to run only the remaining scheduled sessions. Recorded sessions are never repeated. Timeouts, missing exit status, unknown price evidence and any unrecorded run directory block this recovery. If the recovery implementation changed, `--previous-collector PATH` must point to retained source bytes matching the original frozen collector hash; a separate continuation receipt records the new implementation fingerprint and prior summary. The original protocol, observations and six-session denominator remain unchanged. This option is not automatic retry and does not confer additional spending authorization.

Each session has a separate workspace and Claude configuration directory, no configured MCP servers, no shell tool, no inherited settings sources, and a skill-only plugin without startup hooks. WITH receives the frozen plugin; WITHOUT does not. Existing credentials are passed only to the configured provider after matching its HTTPS hostname to the frozen suite. Unrelated MCP credentials are never copied. A temporary first-party OAuth copy, when used, is removed after the process returns.

This is local native collection, not an operating-system security boundary. Do not use private data with untrusted skills. Native initialization records the observed model, plugin list and tool list; mismatches, permission denials and missing price evidence leave conditions unresolved. Built-in host skills can remain available to both arms. Loading a plugin and invoking its skill are recorded separately. Neither native metadata nor local hashes independently attest the provider's model weights, researcher expertise or biological validity.

For a custom provider, native USD estimates may use unknown model pricing. A frozen `pricing` object may declare `input_miss_usd_per_million`, `input_hit_usd_per_million`, `output_usd_per_million`, `source`, `checked_at` and `basis`. Pricing uses the conservative per-token-category envelope of aggregate usage and the single observed model's ledger: some native error results omit the last turn from aggregate usage. Both original ledgers and the original native USD remain in the receipt. This is an estimate, never an invoice. The native budget flag can stop a session using its own different estimate and may overshoot while a request is in flight.

Automated sessions declare no human interaction and no paid local tools. Setup, retries, judge costs, unrelated overhead and account settlement are not silently zeroed. A complete supplementary cost ledger is required for an efficiency or cost-saving verdict.

The offline verifier checks protocol, schedule, plugin/input hashes, event bytes, independently parsed native receipts, session uniqueness, process completion, answer bytes, and temporary credential removal. Retain the entire study directory as the native evidence archive. Registry export separately carries scored artifacts and supports offline recomputation; it is not a second independent execution.

`scripts/prepare_rnaseq_audit_pilot.py` prepares a public-source RNA-seq BH-table audit with a correct complete table, an injected wrong adjustment, and a missing-family control. All derive from one source and are development cases. They must not be counted as independent biological studies or heldout validation. See the actual run record in `VERIFICATION.json` for the current evidence boundary.
