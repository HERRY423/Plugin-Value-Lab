# Embed the same analysis in your workflow

Install the package's science extra in the environment used by the workflow. Examples use the same public SDK, frozen plan and count validator. No models or credentials are needed.

From this directory, create a **synthetic** input once:

```sh
python generate_fixture.py --output counts.h5ad
pvl aggregate counts.h5ad --config settings.json --output cli-result
pvl verify cli-result
snakemake --snakefile Snakefile --cores 1 --keep-incomplete
nextflow run main.nf --input counts.h5ad --settings settings.json --outdir nextflow-results
```

Expected: 72 cells, 3 input genes, 6 samples, 3 paired donors, 2 retained genes. Every output row is `[78, 36]`. Real data requires reviewed column mappings, cell type, contrast and thresholds.

Snakemake owns its declared output directory and may remove it during reruns or after failure. Use `--keep-incomplete` for diagnosis, then archive a failed directory before an intentional retry. The SDK must be installed in the engine's Python environment. Both counts and settings are declared dependencies.

Nextflow uses fixed staged filenames, so input paths are not interpolated into shell code. `stageInMode 'copy'` is intentional: PVL refuses linked sources. Budget for staging copies. Use a new outdir for changed analyses; `overwrite: false` preserves earlier published files. Engine `-resume` is not PVL verification: use `pvl verify` on reused/published outputs and retain the expected commitment separately when needed.

Open `notebook.ipynb` in Jupyter. The first two code cells are read-only; repeating aggregation verifies before reuse.

Local acceptance on 2026-09-29 executed a real Jupyter kernel, Snakemake 9.27.0 and Nextflow 25.10.4, including exact-count comparison and engine reruns. See [the scoped evidence record](../../docs/evidence/engineering-usability-20260929.json). This does not establish compatibility with every engine/library version, cluster deployment or non-author adoption.

Reproduce native engine acceptance after installing PVL and both engines:

```sh
python scripts/check_workflow_integration.py --engine all --output work/workflow-acceptance
```

Run that command from the repository root; the script creates a new synthetic workspace. Missing engines fail the check. Installed-wheel and Jupyter acceptance is available through `scripts/check_engineering_usability.py --wheel <built-wheel> --output <new-directory>` and requires nbclient/ipykernel plus scientific dependencies in the invoking Python environment.

References: [Nextflow process inputs](https://nextflow.io/docs/latest/process.html#input-files-path), [Snakemake rules](https://snakemake.readthedocs.io/en/stable/snakefiles/rules.html). Native engine execution is separate acceptance evidence; running notebook cells or a rule body alone does not establish it.
