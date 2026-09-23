# Scientific validation and Scenario Packs

Measure and register the marginal value of scientific agent plugins under matched conditions.

The package version stays 0.4.0-alpha.1. These are computational contracts, not expert validation of tasks or biological truth. Existing `artifact`, trusted local `executable`, and sealed teaching corpus contracts remain compatible.

## Graders

Every new artifact grader uses the existing `artifact` ID and `verifier` object. The collector must supply `artifacts[ID] = {path, sha256}`. Files are confined to `--artifacts`; absent files, hash changes and missing scorer material remain unresolved. Text assertions and imported `passed:true` cannot replace file checks.

| Type | Frozen verifier fields | Interpretation |
| --- | --- | --- |
| `artifact_schema` | `format: json/csv`, `fields: {name: {type, nullable}}`, `allow_extra`, `min_rows` | Required scalar columns/keys and exact types. JSON object or array of objects; CSV rows. This is deliberately a bounded contract, not general JSON Schema. |
| `numeric_tolerance` | `metric`, `truth: {path, sha256}`, `id_column`, `value_column`, `threshold`, `absolute`, `relative` | Recomputes against scorer-only CSV/TSV. Exact entity coverage, unique IDs, no blank labels or nonfinite numbers. |
| `abstention_correct` | `truth: {path, sha256}` | Private reference must expect `withhold`; a structured artifact with `decision: allow` counts as unsupported acceptance. |
| `over_refusal` | `truth: {path, sha256}` | Private reference must expect `allow`; `decision: withhold` counts as over-refusal. Passing this check alone does not establish a correct analysis. |
| `backend_identity` | exact `backend`, `version`, `entrypoint` | Reads `record.backend_receipt: {path, sha256}` from the separately trusted scorer root. Requires runtime observation, no fallback, and this session/output hash. |
| `exec` | `program: {path, sha256}`, immutable `image: name@sha256:...`, `timeout_seconds: 1..60` | Docker-only execution of a reviewed verifier; unavailable Docker/image or malformed response stays unresolved. |

Scalar schema types are `string`, `integer`, `number`, `boolean`; JSON booleans are not numbers. CSV booleans must be lowercase `true`/`false`. All fields are required; `nullable` permits JSON null or an empty CSV value, not omission. Remote schemas and `$ref` are not supported.

Numeric metrics:

- `absolute_relative`: every aligned value must satisfy `abs(actual-truth) <= absolute + relative*abs(truth)`, with `threshold: 1`.
- `ari` / `nmi`: adjusted Rand index / arithmetic-normalized mutual information over the complete aligned entity set; compare to `threshold`. At least two entities required. Labels may be permuted, so neither metric establishes correct biological cell-type names. Pair with exact mapped-label checks when semantics matter.
- `pearson`: correlation of aligned numeric effect values, compared to `threshold`. Constant vectors remain unresolved; correlation does not establish calibration, direction correctness for every gene, or valid experimental design.

For ARI/NMI/Pearson, `absolute` and `relative` must both be zero. Thresholds and mappings must be chosen before observations. ARI may be negative. No model-reported ARI or correlation is accepted as a measurement. Definitions follow the [scikit-learn ARI](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.adjusted_rand_score.html) and [arithmetic NMI](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.normalized_mutual_info_score.html) conventions.

Decision reference JSON is exactly `{ "decision": "allow", "rationale": "Curator's evidence-bound criterion" }` (or `withhold`). Malformed decisions fail outcome checking but remain unknown in the decision error denominator. Reports retain all planned repetitions, including missing, failed and duplicate runs, with missingness bounds. Bounds are not confidence intervals; repeated runs are not independent biological samples.

A backend receipt contains exactly `backend`, `version`, `entrypoint`, boolean `fallback`, `session_id`, `artifact_sha256`, `collector`, and `basis: runtime_observation`. Collect it outside the model's writable area after execution, then hash it and reference it from the run. A pre-run installed-package probe is not an execution receipt. PVL checks a trusted collector's assertion; it does not authenticate identities or generate such receipts from model text. A missing critical backend check blocks comparison even when its dimension is `process`.

## Container execution boundary

`exec` uses an already present immutable Linux image; it never pulls an image or substitutes host Python. The reviewed program is copied with the submitted artifact into a dedicated read-only mount. No scorer directory, user home, credential store or Docker socket is mounted. Network is disabled, filesystem read-only, capabilities dropped, privilege escalation disabled, user 65534, memory 256 MiB, CPU 1, process limit 32, and temporary space 16 MiB. Docker resource enforcement is described in the [official documentation](https://docs.docker.com/engine/containers/resource_constraints/).

The image must provide `python`. Program arguments are `/inputs/verify.py /inputs/artifact`; `/inputs/contract.json` contains the original artifact filename. Standard output must be exactly JSON with boolean `passed` and nonempty `rationale`. Timeout, exit failure and excessive output are unresolved; the owned container is force-removed on exit. Output is monitored with a 64 KiB threshold; this is a polling limit, not a hard host disk quota. The container shares the Docker engine kernel and is not an audited VM security boundary. Local tests of command construction do not prove isolation on a deployed Docker engine.

The old `executable` type explicitly runs trusted local code and is **not** this sandbox. Scenario Packs exclude it.

## Public tasks and scorer-only truth

A proposed `pvl-scenario-pack-1` document contains `id`, `evidence_type`, `sources` and `scenarios`. Each source declares `url`, `license` and `provenance`; declarations are not license verification. Each `AgentVisibleScenario` contains:

```json
{
  "type": "AgentVisibleScenario",
  "id": "case-01",
  "family": "annotation-donor-a",
  "split": "heldout",
  "prompt": "Analyze inputs/cells.csv and write predictions.csv.",
  "inputs": {"inputs/cells.csv": "<actual SHA-256>"},
  "outputs": {"predictions": "predictions.csv"},
  "scorer": {"path": "rules/case-01.json", "sha256": "<actual SHA-256>"}
}
```

Scorer files live in a separately supplied root. Each is exactly `type: ScorerOnlyGroundTruth`, matching `case_id` and `evidence_type`, a random 32-byte hexadecimal `nonce`, a curator `rationale`, and nonempty `graders`. Each child grader contains `id`, `type`, `artifact`, `verifier`. Allowed types are the scientific types above and built-in `artifact`. All private criteria must pass; there is at most one decision check per scenario. The random private nonce prevents trivial enumeration of small answer spaces from the public scorer-file hash.

Validation rejects duplicate cases/prompts, families crossing development/heldout splits, undeclared output references, unsafe paths, and scorer-file/reference hashes included among public input hashes. `scenario-stage` requires both roots and copies only explicitly declared inputs plus a minimal `scenario.json`; the latter omits split, family, scorer pointers, rules, nonce and answer. It never recursively copies the source tree. Destinations are new and disjoint from input/scorer roots. A hash check cannot detect labels hidden in a different file encoding, prior model exposure, related donor leakage or a curator's bad labels. These require task review and actual host filesystem isolation; staging alone does not sandbox a host that can read outside its workspace.

```sh
python scripts/value_lab.py scenario-validate pack.json --inputs inputs --scorers scorers
python scripts/value_lab.py scenario-prepare pack.json --template study-template.json --output suite.json
python scripts/value_lab.py freeze suite.json --lock protocol.lock.json
python scripts/value_lab.py scenario-stage pack.json --case case-01 --inputs inputs --scorers scorers --output agent-case-01
python scripts/value_lab.py evaluate suite.json runs.jsonl --lock protocol.lock.json --artifacts collected --verifiers scorers --output report
```

Use `registry-add --verifiers scorers` and `registry-replay --verifiers scorers` for local registration/recomputation. Public bundles preserve commitments and result receipts; scorers must be shared separately with authorized reviewers. Review reports can reveal scoring decisions, so never return them to heldout runs in progress. Synthetic scorer evidence keeps the result synthetic even if the enclosing suite is relabeled.

Codex preparation already understands suite `inputs` and `output_artifacts`; execute only after reviewing data scope, filesystem confinement and account costs. Claude's native exporter rejects these unsupported graders rather than converting them to text regex or model judging. A validated Claude artifact collector is still needed for this scientific study; native diagnostic scores cannot fill that gap. See the [native evaluation contract](https://code.claude.com/docs/en/plugin-evals).

These names adopt the separation suggested for Epistemic Plugin Arena. There is no verified external Arena adapter or adopter; this is a proposed PVL contract, not a claim of byte-compatible integration or an accepted standard.
