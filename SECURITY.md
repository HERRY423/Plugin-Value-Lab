# Security policy

Report suspected vulnerabilities privately. Do not attach patient data, credentials, full host transcripts or a working exploit to a public issue or pull request. 中文：漏洞细节先走私密渠道；患者数据、密钥和完整会话不得作为公开复现材料。

## Reporting a vulnerability

Use **[Report a vulnerability](https://github.com/HERRY423/Plugin-Value-Lab/security/advisories/new)** (GitHub sign-in required). This is GitHub private vulnerability reporting, not a public issue. The receiving maintainer is **[@HERRY423](https://github.com/HERRY423)**. Share only a sanitized reproduction; a private GitHub report is not an approved repository for patient data, secrets or unpublished research.

Private reporting was enabled and checked on **2026-10-03 (America/Los_Angeles)**: authenticated and unauthenticated API reads returned `enabled: true`; the public Security page exposed the report link. See the [verification record](docs/evidence/maintenance-channel-20261003.json). This verifies configuration and discoverability, not a submitted report, notification delivery or measured human response. The maintainer checks the private advisory inbox each working day and before every release; notifications alone are insufficient.

If the private option is unavailable, open a [minimal contact request](https://github.com/HERRY423/Plugin-Value-Lab/issues/new) asking @HERRY423 to restore the private channel. Include no vulnerability details, affected private systems, logs, secrets or sensitive attachments. Wait for a verified private channel before sending details. This fallback follows [GitHub's reporting guidance](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately). No alternate security mailbox or bounty program is promised. The public fallback is only a contact request, never a vulnerability submission channel.

Through the private channel, provide the affected release or commit, host and dependency versions, a synthetic minimal reproduction, expected and observed behavior, impact and any known mitigation. Limit testing to systems and data you are authorized to use. Coordinate disclosure with the maintainer; a public correction or advisory should describe affected versions, the fix or mitigation and remaining limitations.

## Serious-issue response

These are the minimum handling commitments, effective 2026-10-03. Working days are Monday-Friday in America/Los_Angeles; this is a single-maintainer project without 24/7 coverage. The acknowledgement clock starts at receipt; assessment and mitigation clocks start at acknowledgement. A substantive acknowledgement names the owner, provisional severity and next update date. Automatic delivery is not acknowledgement. A mitigation deadline is not a guaranteed patch deadline.

| Priority | Examples | Acknowledge within | Assessment and next action within | Updates until contained |
| --- | --- | --- | --- | --- |
| P0 / critical | Active exploitation, exposed credentials/data, arbitrary execution or containment bypass; corruption that silently admits invalid evidence | 1 working day | 2 working days: provide a safe workaround, disable/withdraw the affected path, or explicitly recommend stopping use | Every working day |
| P1 / high | Reproducible exploitable defect, data loss, incorrect scientific acceptance or a supported core workflow blocked without a safe workaround | 2 working days | 5 working days: affected scope, mitigation or stop-use guidance, fix plan and next checkpoint | At least every 5 working days |
| P2 / normal | Other defects and compatibility questions | 5 working days | Triage, scope and next checkpoint within 10 working days; no fixed repair date | On the agreed checkpoint |

1. **Receive and restrict:** @HERRY423 owns intake, severity, remediation and closure. Keep security details in the private advisory. Non-sensitive correctness failures can use a public issue with synthetic inputs; move privately if disclosure or exploitation risk appears. Do not request unrestricted host logs.
2. **Contain:** reproduce only with authorized synthetic/public material; record affected release/commit, environment, impact and uncertainty. Stop affected execution, exports or claim reuse as appropriate. For sensitive data, follow [incident handling](docs/DATA-GOVERNANCE.md#retention-deletion-and-incidents), including the data custodian and credential rotation. Avoid copying the compromised material into tickets.
3. **Repair and verify:** retain a regression reproduction and an exact-commit test result for the affected path and supported environment. Record affected/fixed versions, artifact identity, migration or rollback limits, and claims needing reassessment. Back up before rollback; never overwrite frozen evidence or treat rescoring as a fresh execution. Apply the [security/correctness compatibility exception](docs/API-STABILITY.md#security-and-correctness-exceptions) when necessary.
4. **Release and close:** coordinate disclosure with the reporter, publish a sanitized correction/advisory when safe, and link the fix or documented mitigation. Close only with recorded disposition and verification; lack of reproduction is an explicit unresolved/not-reproduced disposition, not proof of safety. A pending upstream fix retains a named next checkpoint and stop-use guidance where needed.
5. **Missed deadline or absent owner:** follow up in the same private report. After a missed acknowledgement deadline, a public contact request may state only that private contact is pending. The maintainer records missed targets and a revised checkpoint privately; no silent downgrade or deletion. There is currently no independent backup responder. Planned absence or inability to meet this policy requires a named consenting replacement or an explicit support-pause notice and suspension of new releases; never imply continuous coverage. See [maintenance ownership](CONTRIBUTING.md#minimum-maintenance-commitment).

## Supported versions

| Version or artifact | Security maintenance policy |
| --- | --- |
| Latest non-prerelease minor release, at its newest published patch | Maintained for security, correctness and regressions within the documented compatibility scope; response commitments above apply. As checked on 2026-10-03, this is v0.9.0. |
| Older minor releases | No routine backports promised. Upgrade or apply a specifically documented mitigation. |
| Default branch and local unreleased changes | Reports accepted; development snapshots are not supported release artifacts. |
| Experimental extensions and host integrations | Reports accepted within their documented scope; no host-wide security certification. |

Check [published releases](https://github.com/HERRY423/Plugin-Value-Lab/releases) for the actual release identity. A source version, local tag, passing test or package build alone does not prove publication or security maintenance status. A security fix may disable unsafe behavior immediately; see the [compatibility exception](docs/API-STABILITY.md#security-and-correctness-exceptions).

See the [environment compatibility scope](docs/API-STABILITY.md#maintained-environments) for Python, OS, dependency and host boundaries. Reports outside that scope are accepted for triage, without a compatibility or backport promise.

## Scope and limitations

Relevant reports include path escape, arbitrary execution through untrusted inputs, unintended network access, credential exposure, unsafe HTML rendering, replay contamination and bypasses of documented isolation or evidence gates. Incorrect scientific scoring without an exploit can be reported as a correctness issue using synthetic material.

PVL is not a security boundary around every plugin, model or host. Local files and host logs can contain sensitive material. A loopback service is not an authenticated multi-user service; do not expose it publicly. Live tool recording can send requests to the selected backend before a cassette is rejected. Credential-pattern checks are not a patient-data detector or an anonymizer. Linux, Windows and individual host boundaries require their own acceptance evidence.

Follow [data governance](docs/DATA-GOVERNANCE.md) for collection, storage, incident handling and exports. This policy does not assert a security audit or regulatory certification.
