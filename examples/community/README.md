# Community workflow delivery / 社区工作流接入

Version 0.8.0 remains unchanged. These are reviewable integration candidates, not claims of PyPI/Bioconda publication or acceptance by nf-core/Snakemake maintainers. The installed `pvl` CLI and Python SDK remain the L1 entry points. L0 marketplace installation is unchanged.

## L1: package and workflow candidates

Build from the reviewed checkout, validate metadata and prepare a recipe bound to the actual source archive:

```sh
python -m build --outdir /path/to/new-release
python -m twine check /path/to/new-release/*
python scripts/prepare_community_release.py --sdist /path/to/new-release/plugin_value_lab-0.8.0.tar.gz --output /path/to/new-recipe
```

The recipe includes the scientific dependencies needed for counts aggregation. Its future PyPI URL must serve exactly the recorded SHA-256 before submitting it to Bioconda. No script uploads packages, acquires credentials, or starts a release. PyPI ownership/trusted publishing, a real Bioconda build and upstream maintainer acceptance remain required. Never replace an already published version with different bytes.

The [nf-core-style module](nf-core/modules/pvl/aggregate/main.nf) and [Snakemake wrapper](snakemake/pvl/aggregate/wrapper.py) invoke only `aggregate` then `verify`. Run the supplied workflows with an installed reviewed wheel until the pinned conda package is actually available. They do not fit models, normalize counts or infer biological settings. Nextflow stages inputs by copy because linked inputs are deliberately rejected.

```sh
python scripts/check_workflow_integration.py --engine all --community --output /path/to/new-acceptance
```

This runs both engines, checks exact synthetic counts, resumes them, and verifies that a changed published report is rejected. **An engine cache hit is not PVL verification.** After every resume or transfer, run `pvl verify RESULT --expected-id PREVIOUSLY_RETAINED_COMMITMENT`. Keep that commitment separately. The module/wrapper cannot run when the engine chooses to skip them.

## L2: offline CI gate

```sh
python -m value_lab.ci_gate --suite suite.json --lock protocol.lock.json --records runs.jsonl --output gate-result --verify-result sdk-result
```

Alternatively use `--claude-result existing-official-result.json` instead of `--records`. This performs the existing diagnostic import and evaluates the imported records. It does **not** run `claude plugin eval`; paid native execution is blocked until a verified request-level budget boundary exists. Missing plugin loading, outcomes, cost or paired observations remain blockers. A diagnostic import normally cannot yield a positive gate.

Exit codes retain the evaluation meaning: **0** positive local signal with complete supplied evidence; **1** no demonstrated gain or regression; **2** insufficient evidence, simulation, malformed input, failed artifact verification or rejected submitted executable graders. `pvl verify` has its own SDK exit codes; the adapter maps verification failures to gate 2. A valid artifact hash cannot turn a nonpositive comparison green.

The reusable Action lives at `.github/actions/pvl-gate`. Pin its repository reference to a reviewed full commit, set up Python 3.11+, and supply explicit suite/lock/record paths. It publishes a job summary and writes `gate.json`, the original scoped `report.json`, and escaped `summary.md`. An import also retains its native source. Upload the output with `if: always()` even when the gate fails. Never treat `continue-on-error` as the final policy: enforce the returned code after uploading/commenting.

The [PR workflow template](ci/pull-request.yml) keeps model credentials out of CI. PR comments are optional for same-repository PRs; forks use the job summary. The template does not use `pull_request_target`, execute PR-supplied action code or consume arbitrary commands. Configure branch protection to require the gate. A repository contributor can still supply false observations: this is an evidence contract, not authentication of real-world events.

## L3: standards-based publication package

Create a small selection file next to the chosen evidence (all paths relative to that file):

```json
{
  "name": "My scoped plugin comparison",
  "license": "https://spdx.org/licenses/CC-BY-4.0",
  "files": {
    "suite": "suite.json",
    "lock": "protocol.lock.json",
    "records": "runs.jsonl",
    "report": "report.json"
  }
}
```

Select the evidence license yourself; the exporter does not assign the source-code license to research data. Optional roles: `registration`, `timestamp_request`, `timestamp_response`, `timestamp_receipt`, `review_statement`, `review_signature`, `replay_receipt`. A reviewer statement requires its signature and registration. Scope is extracted from the report and rechecked. Missing components are explicitly enumerated; packaging partial evidence does not complete the study.

```sh
python -m value_lab.evidence_crate export package.json --output publication-crate
python -m value_lab.evidence_crate verify publication-crate --expected-id SAVED_METADATA_SHA256
```

The exporter binds the exact suite, lock, observations and scoped report; preserves selected bytes; writes standard `ro-crate-metadata.json` and an **unsigned** in-toto Statement v1. SHA-256 in that statement inventories the payload; the RO-Crate metadata binds the statement. Retain the returned metadata digest outside the package. Without it, validation establishes internal consistency only. Extra files, changed bytes, path traversal, linked payloads, stale review targets and contradictory graph references are rejected. Export uses a new directory and never extracts an archive or executes included code. Limits: 128 MiB per selected file, 512 MiB total.

The Workflow Run Crate describes the **actual evidence packaging workflow**, with W3C PROV Entity/Activity/Agent links. It does not assert that the original scientific workflow was executed again. Original replay receipts remain separate declared evidence. Ed25519 verification checks the original PVL signature domain and target; the embedded key alone cannot authenticate a reviewer. RFC3161 tokens are retained without re-verifying a TSA trust chain. Use the existing preregistration verifier with independently supplied CA/key trust for those stronger checks. The converted in-toto statement is not signed by the original reviewer and is not a DSSE attestation.

Mappings follow [Workflow Run Crate](https://w3id.org/ro/wfrun/workflow/0.5), [W3C PROV-O](https://www.w3.org/TR/prov-o/) and [in-toto Statement v1](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md). The interoperability target is explicitly pinned to RO-Crate 1.1, Process/Workflow Run 0.5 and Workflow RO-Crate 1.0, supported by roc-validator 0.11.2. The newer 1.3/0.6 specifications are not claimed. PVL's structural/byte checks are distinct from external profile validation, scientific replication, independent review and journal acceptance.

## 中文边界

L1 提供实际可执行的模块、wrapper 和绑定源码包哈希的配方；未获得上游接纳前不写“已发布/已收录”。L2 消费已有证据，不绕过付费预算阻断；模拟与证据不足都返回 2。L3 按标准包装并保留原始签名、时间戳、范围卡和重执行回执；缺什么就报告什么，不把打包成功解释为独立审阅或科研复现。原来的五条主线命令、SDK、MCP、评分器以及版本号保持不变。
