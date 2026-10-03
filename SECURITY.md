# Security policy

Report suspected vulnerabilities privately. Do not attach patient data, credentials, full host transcripts or a working exploit to a public issue or pull request. 中文：漏洞细节先走私密渠道；患者数据、密钥和完整会话不得作为公开复现材料。

## Reporting a vulnerability

Open the repository's [Security advisories](https://github.com/HERRY423/Plugin-Value-Lab/security/advisories) and use **Report a vulnerability** if that option is available. The presence of this file does not enable GitHub private reporting, and its availability has not been verified for this repository.

If the private option is unavailable, open a [minimal contact request](https://github.com/HERRY423/Plugin-Value-Lab/issues/new) asking the maintainer to provide a private security channel. Include no vulnerability details, affected private systems, logs, secrets or sensitive attachments. Wait for that channel before sending the report. This fallback follows [GitHub's reporting guidance](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately). No security email address, response SLA or bounty program is currently promised.

Through the private channel, provide the affected release or commit, host and dependency versions, a synthetic minimal reproduction, expected and observed behavior, impact and any known mitigation. Limit testing to systems and data you are authorized to use. Coordinate disclosure with the maintainer; a public correction or advisory should describe affected versions, the fix or mitigation and remaining limitations.

## Supported versions

| Version or artifact | Security maintenance policy |
| --- | --- |
| Latest published minor release, at its newest patch | Primary target for investigation and fixes; best effort, without a response-time guarantee. |
| Older minor releases | No routine backports promised. Upgrade or apply a specifically documented mitigation. |
| Default branch and local unreleased changes | Reports accepted; development snapshots are not supported release artifacts. |
| Experimental extensions and host integrations | Reports accepted within their documented scope; no host-wide security certification. |

Check [published releases](https://github.com/HERRY423/Plugin-Value-Lab/releases) for the actual release identity. A source version, local tag, passing test or package build alone does not prove publication or security maintenance status. A security fix may disable unsafe behavior immediately; see the [compatibility exception](docs/API-STABILITY.md#security-and-correctness-exceptions).

## Scope and limitations

Relevant reports include path escape, arbitrary execution through untrusted inputs, unintended network access, credential exposure, unsafe HTML rendering, replay contamination and bypasses of documented isolation or evidence gates. Incorrect scientific scoring without an exploit can be reported as a correctness issue using synthetic material.

PVL is not a security boundary around every plugin, model or host. Local files and host logs can contain sensitive material. A loopback service is not an authenticated multi-user service; do not expose it publicly. Live tool recording can send requests to the selected backend before a cassette is rejected. Credential-pattern checks are not a patient-data detector or an anonymizer. Linux, Windows and individual host boundaries require their own acceptance evidence.

Follow [data governance](docs/DATA-GOVERNANCE.md) for collection, storage, incident handling and exports. This policy does not assert a security audit or regulatory certification.
