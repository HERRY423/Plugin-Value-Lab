> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# Phase 2: cross-host studies and the Scientific Plugin Value Registry

This is an unversioned implementation revision; PVL remains **0.4.0-alpha.1**. It adds local collection receipts, explicit host designs, matched contrasts, review admission and signed static registry snapshots. A public service, real cross-host benefit and independent scientific replication are not established by this implementation.

## 1. Freeze the same study across hosts

```sh
python scripts/value_lab.py prepare-host-matrix suite.json --hosts hosts.json --output work/host-matrix
```

`hosts.json` is a list of `{ "host": "codex-cli", "host_version": "ACTUAL_VERSION" }` objects. Supported design labels are `codex-cli`, `claude-code`, `gemini-cli`, and `opencode`. Every cell preserves the exact plugin, actual model target/version, cases, input commitments, scorer commitments, repeats, policy and resource budget. Only host identity/version changes. Cells get separate immutable suite locks; matrix preparation makes zero model calls. The version supplied here is a request/declaration until observed by a collector.

Execution support is deliberately explicit:

| Host | Current boundary |
| --- | --- |
| Codex CLI | `prepare-codex` and `run-codex` exist. Per-run collection receipts bind native events, output artifacts, CLI bytes/version, requested design and native session IDs. Actual model/plugin loading, human review and settled costs still require evidence. |
| Claude Code | Existing native text/LLM diagnostic export. Scientific artifact graders are not silently converted; their validated native collector remains outstanding. |
| Gemini CLI | Matrix cell supported; execution adapter not implemented. The official [headless protocol](https://geminicli.com/docs/cli/headless/) exposes JSON/streaming events; event-shape, extension isolation and collection tests must precede implementation claims. |
| OpenCode | Matrix cell supported; execution adapter not implemented. The official [CLI](https://opencode.ai/docs/cli/) exposes JSON events and session export; packaging, permissions and baseline contamination need native validation. |

No adapter is selected merely from a executable filename or a compatible-looking JSON stream. Host wrappers can alter scientific tool availability, authentication, network and filesystem behavior. Matching model aliases alone does not establish identical actual models.

For Codex, run `verify-codex-collection STUDY` before registering a study. It checks source/event/receipt/output hashes and record binding, while retaining incomplete planned runs. Native completion without a session and answer is not successful collection; duplicate completion/identity is rejected. A rehashed edited plan cannot duplicate the frozen schedule or enlarge its run/time limits. A crash or unknown account charge never triggers automatic retry. Receipts are local consistency evidence, not digital signatures or native-host authentication.

## 2. Compare Δ without conflating changed conditions

```sh
python scripts/value_lab.py registry-contrasts --registry registry --output contrasts.json
```

Host contrasts compare verified registry entries using `ΔB − ΔA`, and separately report baseline-quality and WITH-quality changes. Both studies must retain the same task/input/scorer/policy/repetition contract, plugin bytes, actual model/version, all other conditions and scoring-engine digest. Missing runs, synthetic evidence, reused sessions, disputed entries and superseded revisions cannot produce an eligible contrast. The full original suite hashes differ when a host changes; the shared scientific protocol is compared explicitly rather than pretending those complete hashes match.

Longitudinal contrasts consider plugin revision/content or model revision as the single changing axis. Model-version drift is detected even when its alias stays the same. Same-version plugin content changes count as a revision. Within each fixed cohort, use the latest previous differing revision; an unrelated recent task cannot conceal a matched regression, and an invalid latest matched study is not silently replaced by a favorable older one. Simultaneous model/plugin changes remain non-comparable. Evidence supplements within one lineage are not additional experiments.

An eligible negative change emits `DESCRIPTIVE_GAIN_DROP`. This is a visible, snapshot-based alert with original entry links; it is not a significance test, causal conclusion, upgrade recommendation or autonomous notification. Failures and negative cards remain visible. Different host deltas can motivate research, but are not automatically a publication-ready finding.

## 3. Bind an actual non-author review

Legacy reviews remain readable, but do not qualify a positive public card. Extend the review with:

```json
{
  "version": "pvl-independent-review-1",
  "role": "domain_reviewer",
  "plugin_version": "ACTUAL_PLUGIN_VERSION",
  "plugin_sha256": "ACTUAL_PLUGIN_CONTENT_SHA256",
  "suite_sha256": "ACTUAL_SUITE_SHA256",
  "disagreements": [],
  "false_refusals": []
}
```

This object is the review's `protocol` field. `role` can also be `reproducer`. False-refusal observations contain `case_id`, `arm`, `repetition`, `note`; they must reference an actual planned case/repetition. Record real disagreement and false refusal even when inconvenient. An unresolved disagreement prevents unambiguous support. Existing disputes and ancestor dissent continue to block positive admission; a supportive new review does not erase them. Reviews of old revisions never imply review of a new revision.

The reviewer signs their own complete review using their own Ed25519 key:

```sh
python scripts/value_lab.py registry-sign-review review.json --key reviewer.pem --output review.signed.json
python scripts/value_lab.py registry-review review.signed.json --registry registry
```

Signing does not submit or publish a review. Never sign in someone else's name or auto-generate expert reviews. `registry-sign-review` requires an existing unencrypted Ed25519 PEM key; store it outside studies, source control and public output with operating-system access controls. The key is not copied into output. Public-key enrollment is a separate human procedure: check the person's identity, role, relationship, conflicts and consent, then enroll their public key with that identity. One signature cannot prove they are a real expert or independent.

The trust file is exactly `{ "keys": [...] }`. Each entry has `key_id` (SHA-256 of the raw 32-byte public key), base64 `public_key`, `identity`, `organization`, `roles` (publisher/domain_reviewer/reproducer), and boolean `revoked`. An embedded key is never trusted automatically. Matching author or organization declarations, conflicts, wrong-role keys, identity mismatches, revoked keys, unsigned reviews and mismatched suite/plugin versions cannot qualify. Maintain the trust file out of band and disclose its limitations.

## 4. Generate a signed, read-only public snapshot

Install the optional signing dependency with `python -m pip install ".[registry]"`. Then:

```sh
python scripts/value_lab.py registry-public --registry registry --publisher-key publisher.pem --trust trust.json --heldout heldout.json --output public-snapshot
python scripts/value_lab.py registry-public-verify public-snapshot --trust trust.json --expected-snapshot SAVED_SNAPSHOT_SHA256
```

`heldout.json` maps entry IDs to `{suite_sha256, split_sha256, status, statement}`. Status is `declared_unexposed`, `exposed` or `unknown`. `split_sha256` commits the mapping `{case_id: {family, split}}`, using public corpus cases when present and otherwise suite cases (`cluster` is the suite's family). Missing splits are `unspecified`. Changing the suite or split invalidates the declaration. Structural separation and a declaration do not establish absence of training contamination, donor overlap, prior disclosure or hidden label leakage.

Every card includes suite/usage-card/report/plugin/engine digests, model/host/version, observed date, paired counts, both arm scores, Δ, error metrics, exposure declaration, review roles/versions/disagreements/false refusals and explicit claim limits. Only an eligible non-synthetic positive study with at least one valid, locally trusted non-author signed review, explicit host/model versions, and declared-unexposed heldout cases gets `REVIEWED_LOCAL_SIGNAL`. A known task family crossing development and heldout splits blocks admission, even with an unexposed declaration. A review predating the submitted observations cannot qualify. Other entries stay in the registry with `PENDING_REVIEW` or `OBSERVATION_ONLY`; none are silently discarded. Even an admitted card grants no scientific authorization.

The builder writes static HTML and signed JSON summaries only. It does not copy raw prompts, outputs, transcripts, private truth, private keys, credentials or complete usage-card prose. Review protocol notes and heldout statements are intentionally included; inspect them for sensitive content before any actual publication. The webpage has no scripts, forms, model invocation or remote assets. Its HTML bytes are bound by the signed index, and every card is separately signed. Ed25519 uses the established [cryptography signing and verification API](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/), not custom cryptographic arithmetic.

The signed message is ASCII `context + "\n" + suite_digest(payload)`. Context is distinct for public cards, index and reviews. `suite_digest` uses PVL's existing sorted compact UTF-8 JSON serialization with finite numbers; this is not a claim of RFC 8785 canonicalization or a standardized cross-language protocol. Public snapshot identity is the digest of the signed index envelope. Verification checks the independently supplied publisher trust, signed index/card payloads, exact file membership and HTML/file hashes. The optional saved snapshot digest detects substitution with an older correctly signed snapshot. Signatures alone do not establish freshness.

`--previous PREVIOUS_PUBLIC_DIRECTORY` binds a prior verified snapshot when its trust policy is unchanged. Trust-file changes, including role changes or revocations, require rebuilding and re-evaluating review admission; an old positive snapshot is not silently accepted under a changed trust policy. Keep the old snapshot as historical evidence. Hosting, DNS, access policy, independent key enrollment and actual public deployment are separate tasks; no upload occurs here.

## 5. External pilot intake

The [external pilot intake](EXTERNAL-PILOT-INTAKE.md) records three source-verified candidates and an unsent invitation draft. No candidate is counted as a participant, reviewer or adopter. Real consent, frozen plugin/tool boundaries, license review, independent task design and actual matched runs are needed before adding external benefit data.

## Local acceptance boundary

The phase-two acceptance creates three synthetic cards, no positive listings, no reviewer identity, and no model calls. Its demo publisher key exists only in memory. The isolated wheel can verify the signed snapshot and replay all three synthetic studies. On the development machine, OpenCode 1.18.29 answered version/help using temporary isolated XDG directories; Gemini CLI was absent from PATH. These observations establish CLI availability only. No Gemini/OpenCode execution adapter, authentication, scientific artifact collector or actual cross-host benefit is claimed.
