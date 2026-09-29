# Plugin Value Lab

**Call Plugin Value Lab in ChatGPT to evaluate whether another plugin helps with your task.** Tell ChatGPT which plugin to assess, what you want to accomplish and what a useful result means. ChatGPT organizes the evaluation; PVL checks the plan, analyzes supplied records and produces evidence-bounded guidance.

**Version 0.7.0.** This guide starts with PVL already installed and callable in the current conversation. Begin in chat—no repository paths, JSON forms or terminal commands are required to get started.

[中文](README.zh-CN.md) · [Current evidence](docs/EVIDENCE.md) · [Detailed operations](docs/OPERATIONS.md)

## Start with this request

Replace the bracketed values:

> Use Plugin Value Lab to assess whether [plugin name] helps with [specific task]. First check which relevant tools are available in this conversation, then design an evaluation around my task. Inspect existing results first; if there are none, prepare a small pilot. Compare incremental benefit when a reliable no-plugin baseline is available; otherwise explain what evidence is missing. Handle configuration and records, and tell me where the plugin helps, where it fails, where the evidence is, and what to verify next.

For example:

> Use Plugin Value Lab to assess my connected literature-search plugin: can it find verifiable primary research for my question and accurately explain what each paper supports? Propose cases and success criteria first, then carry out feasible checks within existing authorization.

**A plugin name and one real task are enough to begin.** ChatGPT should use the existing context and ask only for information that affects the assessment. You do not need to know tool names, graders or file layouts.

## Choose a starting point

| Your situation | What to ask ChatGPT |
| --- | --- |
| Evaluate a plugin from scratch | “Use PVL to assess [plugin] on [task]. Start with an evaluation plan and a small pilot.” |
| Check a result you just received | “Use PVL to inspect that plugin output: what is supported, what fails my requirements, and what remains unknown?” |
| Compare with and without a plugin | “Use PVL to compare these two sets of results. Check whether inputs, models and conditions are comparable before interpreting the difference.” |
| Check a repair | “Here are the before/after results and records. Use PVL to retain the original failures and check what improved or regressed.” |
| See whether PVL is callable | “Call PVL's example and validation tools to show the evaluation structure. Clearly label it a demonstration if there are no real runs.” |

Inspecting one output can support a limited diagnosis. Establishing added benefit requires comparable with/without evidence. These are different requests.

## What to provide

- **The goal:** a plugin name and a concrete task, such as finding primary papers supporting a claim, rather than a generic plugin score.
- **A useful outcome:** what decision the result supports and which errors matter. Say when there is no known answer key.
- **Available materials:** inputs, outputs, citations and run records from the conversation or attachments the host can read. Provide local paths only when file access is actually needed.
- **Constraints:** which materials may be sent to other services, whether new paid trials are allowed, and existing spending or time limits. Existing authorization should be reused.

If the target plugin is not connected, ChatGPT should identify that specific gap and continue independent preparation. An already callable PVL does not need to be installed again.

## How the evaluation proceeds

| Stage | What ChatGPT and PVL do | What you should receive |
| --- | --- | --- |
| Establish the task and capabilities | Check the target plugin, available tools and materials | The evaluation question, current capabilities and gaps |
| Design and check the plan | Propose realistic positive, counterexample and missing-evidence cases; use PVL to check rules | Readable cases, success criteria, comparison design and pilot scope |
| Obtain real results | ChatGPT uses supported, authorized host tools or organizes existing runs | Actual calls, original outputs, failures and available cost/time records |
| Analyze and advise | PVL computes comparisons from supplied structured records and checks missing evidence | Arm results, concrete failures, unknowns and bounded guidance |
| Retest a repair | Preserve old results and collect comparable new observations | What changed, what remains missing and any regressions |

**ChatGPT understands the task and coordinates available tools; PVL's default evaluation tools process supplied plans and records.** A plugin name alone does not make PVL launch another plugin, create isolated sessions or retrieve every historical log. Execution depends on the host and target plugin. Without suitable execution or collection support, deliver a plan or a diagnosis of existing evidence.

Asking “do not use the plugin” and then “use the plugin” in the same chat does not automatically create independent, uncontaminated arms. Reliable comparisons need the same task and authorized inputs, comparable models and budgets, independent run records and verifiable plugin-loading state. When the host cannot provide these, added benefit remains unestablished.

## What the final answer should contain

You can request an inline result:

> Summarize each task in a table: with-plugin result, no-plugin result, difference, failures or missing evidence, evidence location and usage guidance. Separate observations from claims still needing verification. Keep absent baselines and costs unknown rather than setting them to zero.

Read the result this way:

| Result | Meaning |
| --- | --- |
| Both arms perform well; Δ = 0 | No additional quality gain was observed for these tasks |
| Failure or regression | Inspect the output and records; a host fault is not automatically a plugin defect |
| Insufficient evidence | Required baseline, conditions, cost, identity or review evidence is missing; this does not mean the plugin is useless |
| Simulation / demonstration only | The tool and report structure can be demonstrated without measuring real plugin performance |
| Bounded trial guidance | Applies only to the reported tasks, plugin, model and conditions |

The default MCP tools return structured results that ChatGPT can explain as tables and prose. Saving files or providing downloadable reports requires appropriate host capabilities; it is not an automatic output of every tool call.

## Common questions

**PVL is installed, but ChatGPT says it cannot call it.**

Check the tools actually exposed to the current conversation. If they are absent, use the host's supported enablement or connection flow. A reply labeled “PVL analysis” alone does not establish that a tool was called.

**Can I start with an output but no complete logs?**

Yes. Check the output against the task requirements and identify missing evidence. Do not invent call records or treat that inspection as a complete benefit comparison.

**Does every evaluation require new paid calls?**

Existing-material analysis and local computation do not require an additional model pilot. The current ChatGPT conversation, target plugin and separately launched model runs may have their own usage or charges. New calls follow existing authorization; unknown cost is not zero.

**Official Claude evals already have a baseline. What does PVL add?**

Official evals display WITH, W/OUT and Δ; their exit threshold uses the WITH score. PVL's scientific gate separately requires matched task-success differences and sufficient evidence. See [comparison details](docs/history/RESEARCH-EXECUTION.zh-CN.md).

The four research cases still lack real model/judge runs, and Windows online isolation still needs kernel acceptance. Exposed tools, local tests and manifest validation do not establish those empirical outcomes. See [current evidence](docs/EVIDENCE.md).

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

- [Local tutorial and timing](docs/START.md) · [Real-study operations](docs/OPERATIONS.md) · [Conversational study design](docs/history/RESEARCH-AUTHORING.zh-CN.md)
- [CLI / Python SDK](docs/history/ENGINEERING-USABILITY.zh-CN.md) · [Workflow examples](examples/workflow-integration/README.md)
- [Online isolation](docs/history/ONLINE-ISOLATION.zh-CN.md) · [Environment locks and replay](docs/history/ENVIRONMENT-RECORDING.zh-CN.md)
- [Scientific metamorphic checks](docs/history/METAMORPHIC-GRADERS.zh-CN.md) · [Component comparisons](docs/history/COMPONENT-METHODOLOGY.zh-CN.md) · [Interface freeze](docs/FREEZE.md)

Detailed supporting guides are currently primarily in Chinese.
