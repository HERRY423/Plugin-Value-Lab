> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# External pilot intake — drafts, not invitations sent

Purpose: test whether the registry contract works for scientific tools maintained outside this project. Candidate identification is not consent, adoption, a compatible plugin package or observed benefit. No issue, email or message has been sent.

Primary repositories checked on 2026-09-23 UTC:

| Candidate | Proposed narrow first boundary | Before admitting a study |
| --- | --- | --- |
| [Biomni](https://github.com/snap-stanford/Biomni) | One bounded tool/workflow selected with its maintainer; evaluate its marginal contribution rather than the entire agent | Obtain maintainer-selected entrypoint and data/license terms; freeze a reproducible wrapper, dependencies and task verifier. Do not label the whole agent an interchangeable plugin. |
| [ToolUniverse](https://github.com/mims-harvard/ToolUniverse) | One maintainer-selected scientific tool exposed through its integration surface | Freeze tool registry/revision, actual backend and network responses where permitted; separate tool failures from provider outages and unavailable evidence. |
| [BioMCP](https://github.com/genomoncology/biomcp) | A bounded biomedical retrieval task with known expected identifiers and provenance | Freeze query set, tool/server revision, external source snapshot policy and citation/false-refusal checks; avoid clinical efficacy claims or patient data. |

These are candidates based on public project descriptions. Exact entrypoints, license compatibility, intended hosts and maintenance commitments remain unverified. A community Scanpy skill could be substituted when an actual maintained package, author and executable task contract are identified; the Scanpy library itself is not automatically a plugin or an external adopter.

## Intake record required for each participant

- Consent and responsible maintainer/reviewer contacts supplied by the user or participant; no guessed recipients.
- Public source URL, frozen commit/package hash, license and redistribution decision, declared dependencies and host support.
- One narrow scientific capability and explicit unsupported cases; paired valid-analysis and insufficient-evidence controls.
- Public inputs, separately heldout references, curator rationale, task-family/donor independence, leakage audit and exposure declaration.
- Matched WITH/WITHOUT host/model versions, budgets, verified artifacts, real failure/cost/human-review records.
- A reviewer who is not a study author, with role, conflicts, exact reviewed version, disagreements and false-refusal observations.
- Agreement that negative, incomplete and regressing results remain visible; author response is stored alongside the review rather than erasing it.

## Invitation text for user review

Subject: A small, reproducible marginal-value study of one scientific tool

We are developing Plugin Value Lab to measure and register the marginal value of scientific agent plugins under matched conditions. We would like to discuss a small pilot around one bounded capability from your project, with the exact tool and tasks chosen together.

The proposed design runs identical tasks with and without the frozen tool, preserves failures and negative results, and reports both unsupported acceptance and refusal of justified analysis. Task validity and heldout reference labels would need domain review before execution. Each positive public usage card would require a version-bound non-author review, with conflicts and disagreements retained.

We can provide a Scenario Pack contract, deterministic artifact checks, a review packet, and signed read-only registry summaries. The infrastructure is under local engineering validation; we are not claiming demonstrated tool benefit, external adoption or independent scientific validation. No installation, access to private data or endorsement is presumed.

If this is of interest, please suggest one narrow tool boundary, suitable public tasks, a responsible maintainer and any data/licensing or publication constraints. We would share the frozen protocol and draft report for review before requesting publication permission.

Status: unsent draft; recipient, sender identity, scope and budget still require concrete selection before any external contact.
