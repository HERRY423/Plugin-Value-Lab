# API stability and deprecation policy

Policy effective 2026-10-03. The current source version is defined in [plugin.json](../plugin.json); a `0.x` version is pre-1.0. This policy applies prospectively and does not claim that all historical releases followed it. 中文：公开接口需要兼容性说明；实验接口不等于稳定承诺，历史证据格式不得静默改写。

## Which surfaces are covered?

| Surface | Compatibility scope |
| --- | --- |
| Documented CLI commands and options, including `pvl` | Names, accepted argument meanings, documented machine output and exit status. Human prose and terminal layout are not parsing contracts. |
| Default MCP tools and their documented input/output fields | The public tool contract; host connection details and tool visibility also depend on the host/version. |
| `value_lab.sdk.__all__`, `PVLError` codes and `RunResult` public fields | The documented Python SDK. `message` and `hint` prose may change; code-based handling is preferred. |
| Core exports explicitly listed in [CONTRACT.md](../CONTRACT.md) | The documented signatures and semantics. Other importable implementation functions are not automatically public. |
| Serialized schemas and artifacts with explicit `schema_version` or `format` | The stated schema version and meaning of required fields. Version tags must be checked before interpretation. |
| Opt-in research/team extensions, private helpers, diagnostic scripts and host-log parsers | Experimental or internal unless a specific contract says otherwise. Pin exact versions/bytes; changes require release notes when user-visible. |

The frozen inventory in [feature-freeze.json](feature-freeze.json) is an engineering change detector, not proof that every listed module is a stable API. The [freeze policy](FREEZE.md) remains an additional scope restriction. Scientific verdicts, threshold behavior and treatment of failures or unknowns are part of documented semantics, not incidental formatting.

## Maintained environments

The latest non-prerelease minor release at its newest published patch is the maintenance target (v0.9.0 as checked on 2026-10-03). The [maintainer](../CONTRIBUTING.md#minimum-maintenance-commitment) handles security/correctness fixes and regressions within this scope. Environment scope is distinct from the public-interface compatibility promise above.

| Layer | Maintenance scope and acceptance boundary |
| --- | --- |
| Core Python / CLI / offline validation | Package metadata requires Python >=3.11; the release CI matrix targets Python 3.11 and 3.13 on Windows and Ubuntu. These matrix entries are intended support targets, not a claim that this checkout's CI passed. Python 3.12, 3.14+, macOS and other distributions require their own acceptance before support is claimed. |
| Optional dependencies | Use the version bounds in [pyproject.toml](../pyproject.toml) for the relevant extra; MCP currently requires `mcp>=1.12,<2`. Record resolved versions. Bounds permit installation but do not certify every combination. Optional science, registry and planning capabilities require their matching checks. |
| Isolation and scientific execution | The dedicated CI target is Ubuntu 24.04 with approved namespace/bubblewrap support and the curated runtime. Windows core support does not imply native Linux isolation. WSL, Docker and an HPC partition each need their own boundary checks; no real Slurm/PBS/LSF cluster is certified by hosted CI. |
| Codex host telemetry | Pin the exact host, parser and artifact identity. The retained [0.159.2 / codex_work_desktop qualification](evidence/single-host-qualification-20261002.json) explicitly says synthetic local conformance; it is not blanket native-host acceptance or support for newer versions. |
| Other hosts and plugin surfaces | Claude, ChatGPT, other Codex versions and other hosts require exact-version native evidence for the requested workflow. Manifest compatibility, installed visibility or a synthetic adapter test alone does not establish complete execution support. |
| Stored evidence / team use | Versioned files retain their original interpretation; unknown formats fail explicitly. Local SQLite is not a supported shared-network multiwriter database, and a loopback workbench is not an authenticated multi-user service. |

Before adopting an upgrade, retain the source/artifact digest and resolved environment, run the documented checks on that exact candidate, and keep prior evidence intact. Host, dependency or schema drift requires requalification; unavailable checks remain unverified. The [operations guide](OPERATIONS.md) identifies the applicable gates. The metadata's open-ended Python requirement is not an unlimited forward-compatibility guarantee.

## Versioning and consumer expectations

For pre-1.0 releases, compatible fixes belong in a patch release; an intentional public breaking change requires a new minor version, migration notes and the notice process below. After 1.0, intentional public breaking changes require a major version. These are project commitments, not a claim of 1.0 readiness.

Adding an optional field or option can be compatible only when its absence preserves the documented behavior. Consumers should tolerate documented additive report fields, preserve unknown values as unknown and reject unsupported format versions. Do not silently reinterpret `null` as zero or an unfamiliar verdict as success. Removing a field, changing its type or units, adding a required argument or changing a default's meaning is a breaking change.

Host-specific telemetry support is qualified to observed producer formats and versions. An unavailable or ambiguous field remains unknown; host upgrades do not receive automatic compatibility certification. Published artifacts and local changes with the same version number may differ: reproducible studies must retain the commit, source/artifact digest and environment in addition to a version string.

## Normal deprecation process

1. Record the affected public surface, reason, replacement or deliberate removal, migration example, first warning release/date and earliest removal release/date in the table below and the release notes. A development commit alone does not start the notice clock.
2. Where feasible, provide a compatible adapter or alias and an observable warning. Python uses `DeprecationWarning` (enable it in consumer tests); CLI warnings go to stderr, never into JSON stdout; MCP warnings use documented structured metadata or separate diagnostics. Do not invent fields in a closed schema merely to carry a warning.
3. Keep the old public behavior for **at least 90 days after the first published warning release and through at least one subsequent non-prerelease minor release**, whichever ends later. Removal then requires a later permitted breaking release: a new minor before 1.0, a new major after 1.0. The project freeze still applies. If no replacement exists, state that explicitly.
4. Test both the old path during its notice period and the new path, document migration of stored artifacts, and explain remaining incompatibilities. No automatic in-place migration of evidence is allowed.

These are rules for future deprecations; this documentation change adds no runtime warnings or compatibility shim because it deprecates no public API.

| Public surface | First warning release/date | Earliest removal | Replacement / migration |
| --- | --- | --- | --- |
| None newly declared by this policy | Not applicable | Not applicable | Historical removals and restrictions remain described in their original release records. |

## Security and correctness exceptions

An exploitable security issue, unauthorized data disclosure or acceptance of scientifically invalid evidence can require an immediate restriction, even in a patch release and before the normal notice period ends. Preserve a safe alternative where possible. Document the affected versions, reason, new behavior, mitigation and whether existing results need rechecking. A tightened evidence gate is a correctness repair, not proof that an old study has been newly executed. Do not weaken a safety check merely to preserve an unsafe compatibility path.

## Stored evidence and migrations

Write migrated or rescored artifacts to a new location, retaining their source identity and the migration tool/version. Keep old evidence readable under its original scope where feasible; unknown formats must fail explicitly. Never silently overwrite a frozen suite, receipt or signed object to fit a new schema. Recompute dependent claims when semantics change and mark unresolved ones for reassessment. Privacy-required deletion follows [data governance](DATA-GOVERNANCE.md); immutable evidence is not a reason to retain prohibited data.
