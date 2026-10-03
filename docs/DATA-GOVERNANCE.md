# Data governance and research records

Policy effective 2026-10-03. **Identifiable patient data must not enter ordinary PVL records, prompts, logs, replay cassettes, reports, issue attachments or distribution packages.** PVL is not an approved patient-record system and does not provide a comprehensive sensitive-data detector. 中文：患者姓名、病历号、联系方式、可识别原始病例等不能写入普通记录或发送给模型；改成编号或做哈希并不自动完成匿名化。

## Permitted material and responsibility

| Material | Policy |
| --- | --- |
| Synthetic examples and non-sensitive public research material | Permitted within its license, terms and stated purpose. Public availability alone does not prove absence of sensitive information. |
| Aggregate results and institutionally reviewed de-identified derivatives | Conditional: the data owner must approve the purpose, recipients and storage; check small groups, rare diagnoses and linkage risks before recording or sharing. |
| Pseudonymized or coded participant-level data with a retained linkage key | Still restricted. Do not place it in ordinary evaluation records, host prompts, public fixtures or exports. Keep it in a separately approved research environment. |
| Identifiable patient records, clinical free text, directly identifying images, raw participant sequences or identifying metadata | Outside the supported ordinary recording workflow. Do not ingest them and rely on a later filter. Any separate scientific processing requires institutional approval and a suitable controlled environment. |
| API keys, passwords, cookies, private keys and authentication headers | Never put them into evidence or prompts. Supply only through the approved execution environment when required, and exclude them from logs and exports. |

The study owner classifies inputs and outputs, documents permission to use them, names recipients and providers, chooses the storage/access controls and retention period, and approves each external sharing purpose. Institutional data stewards or privacy/security staff decide whether a derivative is sufficiently de-identified. PVL cannot make that determination or certify compliance. Model execution approval, a tool budget or plugin installation does not authorize a new data recipient or use.

## What can be recorded?

Use the minimum necessary study metadata: opaque study/run IDs, software identities, declared conditions, non-sensitive outcome summaries, aggregate metrics, permitted artifact references, provenance digests and review rationale cleared for that audience. Prefer relative references inside a controlled study directory; avoid paths containing names, usernames, patient identifiers or private server names. Keep linkage keys outside PVL and outside the evaluated agent's filesystem view.

Do not assume that `output`, `error`, review comments, filenames, timestamps, hashes or model identifiers are harmless. Free text can repeat sensitive inputs, and a stable pseudonym or digest can enable linkage or guessing. A digest establishes an integrity relationship; it is not anonymization or permission to publish the referenced file.

If an evaluation needs restricted raw artifacts, keep them in the separately authorized environment. Export only reviewed derivatives that satisfy this policy, and mark any checks that cannot be reproduced from those derivatives as unavailable or requiring controlled review. Do not label a sanitized summary as a complete raw transcript or fabricate missing evidence.

## Collection and external services

Check the host, selected tools, provider terms, destination and requested data separately before any model or remote-tool call. A local plugin interface can call a remote service; local output storage does not imply that input stayed local. Host histories, provider logs, caches and backups may retain copies independently of PVL.

`record-live` requires an explicit public-data acknowledgment and rejects some credential patterns before accepting a replay cassette. This is an operator attestation and a limited credential tripwire, **not** automatic de-identification, patient-data detection or prevention of prior transmission. Requests and responses pass through the selected live backend before cassette acceptance is decided. Other imports, ordinary records and host collectors do not inherit this particular guard.

Native host captures can retain session identity, timestamps, model names, source paths and raw usage metadata. Treat captures and their source references as confidential until reviewed. Parsing selected metadata does not make the original host log safe to copy or share. Collect only the authorized sessions and fields.

## Storage, access and export

PVL's local JSON/JSONL, Markdown, HTML and other artifacts are ordinary files. It provides no general built-in encryption at rest, user/role access control, automatic retention expiry or comprehensive DLP enforcement. Configure filesystem permissions, encrypted storage and backups through the research environment. Keep work outside shared/synchronized folders unless those services are approved. Do not expose the loopback workbench as an Internet or multi-user service.

Review both input and generated output before sharing. Inspect nested archives, manifests, paths, tool arguments, errors, images, notebook outputs, CSV/HTML exports and source bindings. Publish a separate reviewed export with an explicit audience and data classification; never upload the whole working directory as a shortcut. Apply the same review to Git commits, pull requests, CI artifacts, model-judge packets and support requests.

The package builder uses an allowlisted source inventory and excludes ordinary `work/`, build output and caches. It does **not** inspect content for patient information or secrets. A sensitive file placed under `docs/`, `examples/`, `evals/` or `tests/` can still be packaged. Contributor review is mandatory; passing packaging tests is not data clearance.

## Retention, deletion and incidents

Before collection, document the custodian, authorized readers, storage locations, retention end or review date, backup expiry and deletion procedure in the institution's approved study records. No universal retention duration is imposed by PVL, and no automatic purge is implemented. Apply the responsible organization's requirements rather than assuming a file persists safely forever.

If sensitive material is recorded accidentally, stop further collection or distribution, restrict access and notify the responsible data/security contact through an approved private channel. Rotate exposed credentials when applicable. Inventory affected local artifacts, Git history, releases, CI logs, host/provider histories, synchronized storage and backups; deleting one local file does not remove those copies.

The authorized custodian decides quarantine, retention obligations, takedown and deletion. Follow that decision, including contacting external custodians where necessary; do not copy restricted data into an incident ticket. Keep only a non-sensitive incident note identifying affected artifact IDs, authorized action, date and impact on evidence validity. Sanitized replacements are new artifacts, not byte-identical originals. Mark old claims or links invalid/unavailable where evidence was withdrawn. The rule to preserve scientific history never overrides an authorized sensitive-data removal requirement.

Report product vulnerabilities through [SECURITY.md](../SECURITY.md). This document defines project handling rules and implementation limits; it does not establish institutional approval, a provider agreement or regulatory compliance.
