# Contributing to Plugin Value Lab

Start with the [English methodology](docs/METHODOLOGY.md), [implementation contract](CONTRACT.md), [API policy](docs/API-STABILITY.md) and [data governance](docs/DATA-GOVERNANCE.md). 中文：欢迎代码、文档和可复现缺陷报告；使用合成或经批准的公开材料，不提交患者数据、密钥或完整宿主会话。

## Minimum maintenance commitment

Effective **2026-10-03**, **[@HERRY423](https://github.com/HERRY423)** is the primary maintainer and security responder for Plugin Value Lab: issue triage, compatibility decisions, release approval, remediation and private-report follow-up. This account's repository administration permission was verified when the policy was introduced. [.github/CODEOWNERS](.github/CODEOWNERS) routes review requests to that account; it does not itself enforce branch protection or prove review occurred. There is **no appointed backup maintainer** or institutional support team.

The maintenance baseline is the latest non-prerelease minor line at its newest published patch (v0.9.0 as checked on 2026-10-03). It covers defects, security problems and regressions in the [maintained environments](docs/API-STABILITY.md#maintained-environments) and documented public contracts. Older lines receive no routine backports. Experimental extensions, unpublished changes and unqualified host versions are not implicitly supported releases. Feature requests carry no delivery commitment.

- Check public issues and the private security advisory inbox each working day. Acknowledge ordinary defects within 5 working days; [P0/P1 incidents](SECURITY.md#serious-issue-response) have shorter deadlines and explicit update intervals.
- Before every release, review unresolved P0/P1 incidents, verify that private reporting remains enabled and the public Security page exposes its report link, and inspect the exact-commit CI and applicable environment evidence. A release with an unresolved P0/P1 affecting its supported use must be held or explicitly withdraw/disable that use with documented mitigation.
- Recheck owner availability, support scope, dependency bounds and channel accessibility at least every 90 days; the first review is due **2027-01-01**. Record the review and any scope change. This document assigns an obligation; it does not schedule an automated monitor.
- Announce a planned support reduction or end of maintenance at least 30 calendar days ahead in this policy and release notes, with last supported artifact, migration/stop-use advice and unresolved risks. The normal public-API deprecation notice remains separate. An emergency security withdrawal may be immediate. A planned absence needs a consenting named replacement or a visible support-pause notice and a release hold; an unfilled backup role must remain explicit.

General defects: [repository issues](https://github.com/HERRY423/Plugin-Value-Lab/issues). Vulnerabilities: **[private report](https://github.com/HERRY423/Plugin-Value-Lab/security/advisories/new)**. The [security policy](SECURITY.md) defines severity, response clocks, containment, repair, disclosure and escalation. These are prospective operating commitments, not a claim of measured response performance or a commercial SLA.

## Propose a focused change

For a reproducible defect, describe the concrete input, expected result, actual result and affected version or commit. Use a small synthetic fixture. For a new interface, scoring rule, scientific claim or runtime capability, first describe the intended scope and obtain the maintainer's scope decision. Existing correctness fixes and documentation improvements do not require a separate proposal. Security reports follow [SECURITY.md](SECURITY.md), not a public defect report.

The current [feature freeze](docs/FREEZE.md) is an explicit project boundary, not a calendar-based unfreeze. A new scope requires a dated decision in `docs/feature-freeze.json`; do not regenerate the frozen API inventory just to make a check pass. Preserve existing signatures and semantics unless the approved change and migration plan explicitly cover them.

## Set up and verify

Use Python 3.11 or later in a dedicated environment. From a source checkout:

```text
python -m pip install ".[dev,mcp,science,registry]"
python scripts/check_community.py
python scripts/check_feature_freeze.py
python scripts/validate_agent_plugin.py
python scripts/build_marketplace.py --check
```

During development, run tests relevant to the changed behavior. For example, the community metadata checks run with `python -m unittest discover -s tests -p test_community.py`. Before release acceptance, run `python scripts/check_release_tests.py`; skipped or zero tests are failures, not a release pass. Optional science, notebook, workflow-engine and real isolation checks have separate [CI jobs](https://github.com/HERRY423/Plugin-Value-Lab/actions/workflows/ci.yml). Missing optional runtimes must remain explicit; do not substitute a mock or unsandboxed run for native acceptance. Use a project-local writable temporary directory when the operating environment requires one.

Ordinary local tests need no patient data or model account. A proposed test that launches a model, sends data to a provider, incurs charges or changes an external system needs authorization for that action and data. Do not put credentials in test fixtures or CI logs.

## Preserve evidence and keep one source

Edit root source files, `docs/` and `docs/evidence/`. Do not edit or commit generated `build/marketplace/`, `dist/` or the retired `plugins/plugin-value-lab/` mirror. Build reviewable archives with `python scripts/build_marketplace.py --package`, then check them with `python scripts/build_marketplace.py --check`. Packaging includes the community policies and citation file from their canonical paths.

Do not rewrite an old receipt to claim newer validation. Add a dated correction or new result with its own source identity. Retain failures, unknowns, original denominators and method changes. Replay, rescoring, new model execution and scientific execution are different activities. Sensitive-data incidents are the exception to ordinary retention: quarantine and follow the [incident procedure](docs/DATA-GOVERNANCE.md#retention-deletion-and-incidents), rather than preserving an unlawful or unauthorized disclosure for provenance.

## Submit a pull request

Explain the problem and resulting behavior, relevant validation and remaining limitations. For interface or serialized-format changes, identify affected consumers, compatibility tests, the migration path and any deprecation entry. For evidence changes, distinguish observations from interpretation and name the exact material that supports the new claim. Tests should target actual failure modes rather than repeat implementation details.

Keep patches focused and respect existing uncommitted work. Review all files and generated artifacts for sensitive content before submission. Disclose external dependencies, copied material and their licenses. If AI tools helped, you remain responsible for correctness, attribution, permitted data use and reviewing their output. Do not submit secrets or private research to an assistant without the appropriate authorization.

Contributions are made under the repository's [Apache-2.0 license](LICENSE); only submit material you are entitled to contribute. There is no separate CLA or mandatory signed-off-by process defined here. Communicate respectfully, give actionable technical reasons, and avoid personal attacks or discriminatory conduct.

## Release checklist and citation

Update package/plugin versions consistently, including [CITATION.cff](CITATION.cff), and run the checks above. Inspect the exact-commit CI results and draft release artifacts before any publication. A locally built archive is not a published release. Security support applies as described in [SECURITY.md](SECURITY.md).

The citation file names the contributor collective; it invents no personal authorship, ORCID or DOI. Cite the actual version and commit used. Add `date-released` or a DOI only when that release or identifier exists and is verified; an unreleased checkout needs its commit and modifications described separately. Follow the [Citation File Format specification](https://github.com/citation-file-format/citation-file-format/blob/main/schema-guide.md) when editing metadata; the pinned schema is checked offline.
