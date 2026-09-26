> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# Screenshot remediation — versions unchanged

本页下方是较早修复的历史记录；其中零真实运行和旧测试数量不代表当前状态。三个结构性风险的最新处理见[本次记录](STRUCTURAL-RISKS.zh-CN.md)，当前验收见 `VERIFICATION.json`。本页所述历史修复未增加版本；当前 0.6.0 的验收见 `VERIFICATION.json`。

This revision keeps the product at `0.4.0-alpha.1` and the Python package at `0.4.0a1`.

| Screenshot issue | Implemented change | Remaining evidence gap |
| --- | --- | --- |
| No actual observations | Frozen Codex pilot and native per-run evidence collector; actual subprocess integration tests | Authenticated pilot was rejected by automatic approval review: sending the plugin snapshot to the model provider and unknown account costs need explicit authorization. Actual model runs remain **0**. |
| Only four simple graders | DE-table/BH, per-cell label, h5ad and typed JSON artifact checks; pinned Python executable verifier; CLI evaluation and usage/comparison integration | Computational contracts do not establish biological validity; reference quality and independent scientific review remain external requirements. |
| Product identity drift | Evaluation-focused English/Chinese README and plugin manifests; research and team records moved to optional supporting workflows | Existing auxiliary capabilities are retained for compatibility. |
| Claude-only execution | Codex CLI prepare/run adapter with frozen inputs, isolated per-run homes/workspaces, raw JSONL events, sessions, outputs, failure retention and unknown-cost handling | No completed Codex model evaluation or cross-host study yet. Requested configuration and installation do not prove actual model/plugin loading. |
| Arena reference | Epistemic Plugin Arena is explicitly a future outlook; current evidence boundaries stand independently. `link-decision-evidence` remains generic. | No established external Arena project, integration or compatibility is claimed. |
| Distribution/engineering | Portable installation instructions, bilingual entry docs, Windows/Linux Python 3.11/3.13 CI, manual existing-tag draft release workflow, distribution inventory includes LICENSE | Hosted CI and GitHub Release have not been run/published. Workflows are ready for review; no version, tag or public release was created. |

## Local acceptance

- The original 217-test run exposed two Windows cancellation/deadline failures and two cleanup errors under restricted process control. Replaced reliance on `taskkill` with owned Windows Job Objects and process-tree cleanup. The 17 execution tests now pass in the same restricted environment.
- Final full integration run: **261 tests passed**, with source/test/script/skill hashes unchanged throughout, including artifact corruption, missing/changed files, malformed probabilities, per-entity labels, a real h5ad file containing fixture data, pinned executable code, timeout, malformed verifier response, Codex event parsing, full synthetic subprocess collection, no retry and credential cleanup.
- All test observations are explicitly manufactured. Synthetic subprocess events do not count as real model calls or a with/without benefit study.
- The Codex pilot has two disclosed hypothetical task families and four planned runs, bounded to 120 seconds per run. It is a collection smoke test, not a representative biological validation study. Dollar spend is unknown before execution; no dollar cap is claimed.
- The full test count includes the current sealed-corpus and study-registry checks. These are local software checks; held-out secrecy, authentic participants and independent review are not established by them.

See [VERIFICATION.json](../../VERIFICATION.json) for the current machine-readable acceptance state, [artifact contracts](ARTIFACTS.md) and [Codex execution contract](CODEX.md).

Unified acceptance also completed 11 offline CLI invocations for corpus preparation, immutable registration, portable export, integrity verification and replay. The private answer key stayed out of the export; replay without it remained blocked. All of those records are synthetic. The other writing task was paused at the user's request before final packaging.
