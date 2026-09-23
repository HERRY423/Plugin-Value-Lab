# Artifact and executable outcome verification

The optional `de_table.testing_family` reference now binds a separate frozen `{ids:[...]}` JSON file and checks exact tested-entity coverage before BH. Missing or changed scorer material is unresolved; legacy tables without this reference verify submitted rows only. See the [rigor workflow](RIGOR.zh-CN.md) for configuration and portable replay preflight.

Add an `artifact` or `executable` grader to the existing suite. Its `artifact` is a logical ID; each run maps that ID to collected bytes:

```json
{"artifacts":{"de":{"path":"run-001/results.tsv","sha256":"<collected-file-SHA-256>"}}}
```

Paths are relative to the explicitly supplied `--artifacts` root. Absolute paths, parent traversal and links are rejected. Files above 64 MiB are unresolved in this implementation; partition large study artifacts or extend the reviewed limit explicitly. Hash mismatches and missing files remain unresolved, never silently replaced with model assertions.

A DE table rule:

```json
{
  "id":"de-correctness", "type":"artifact", "artifact":"de",
  "dimension":"outcome", "weight":1, "critical":true,
  "verifier": {
    "kind":"de_table", "id_column":"gene", "p_column":"p_value",
    "q_column":"q_value", "effect_column":"log2_fold_change",
    "min_rows":3, "bh_tolerance":0.000001
  }
}
```

CSV and `.tsv` are supported. The verifier recomputes Benjamini-Hochberg values over **every submitted row**, checks unique nonblank IDs, finite effects and probabilities in [0,1]. Supply the complete prespecified testing family, not a filtered significant-gene list. This checks arithmetic and artifact integrity, not donor independence, model assumptions or biological truth.

Other `verifier` contracts:

```json
{"kind":"labels","id_column":"cell_id","label_column":"cell_type","expected":{"cell-1":"T","cell-2":"B"}}
```

```json
{"kind":"h5ad","n_obs":2,"n_vars":3,"obs_columns":["cell_type"],"var_names_unique":true}
```

```json
{"kind":"json_fields","expected":{"result.accepted":false,"result.count":2}}
```

Labels require exactly the frozen IDs and reference labels, independent of row order. Reference quality is the researcher's responsibility. h5ad requires `anndata`; absent dependencies remain unresolved. JSON comparison preserves types, so `true` is not `1`.

## Custom Python verifiers

Use `type: "executable"` with:

```json
{"path":"check_result.py","sha256":"<reviewed-code-SHA-256>","timeout_seconds":10}
```

An explicit `--verifiers trusted-checks` authorizes running those local Python files. They receive the absolute artifact path as their sole argument and must print exactly one JSON object:

```json
{"passed":false,"rationale":"Adjusted p-values do not match the frozen testing family"}
```

Example [check_nonempty_json.py](../examples/verifiers/check_nonempty_json.py) shows the interface; replace it with a scientifically appropriate verifier before freezing your own suite. The code hash is pinned before collection. The evaluator copies and verifies the exact script bytes before running, records code/artifact/rule hashes, uses no shell, and limits execution to 1–60 seconds. Exit errors, timeouts, malformed output and missing code mean **unresolved**, while a valid `passed:false` is a measured failure.

This is trusted local code, **not a security sandbox**: review it and its dependencies first. Do not point it at model-produced programs. Dependency versions and reference data should be frozen in the study environment. The return message is limited to 64 KiB; filesystem output is not a quota-enforced sandbox.

```sh
python scripts/value_lab.py evaluate suite.json runs.jsonl --lock protocol.lock.json --artifacts collected-files --verifiers trusted-checks --output report
```

`report.json` includes per-rule verification receipts. Re-evaluation reads the bytes again. `usage-card` accepts the same `--artifacts` and `--verifiers` options; `compare-studies` accepts `--before-artifacts`, `--after-artifacts` and `--verifiers`. The MCP object-only interface, text calibration, and other APIs without explicit artifact roots leave these rules unresolved; they never execute arbitrary files. The older Claude aggregate export refuses these unsupported graders rather than lowering them to text checks. The separate [read-only Claude collector](CLAUDE-COLLECTION.md) captures native final output as artifact ID `answer`. Codex collection also captures the final answer as `answer`; additional file outputs can be declared in its suite.
