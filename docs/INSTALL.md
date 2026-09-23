# Install

## Codex desktop: GitHub marketplace

Use **Plugins → Add → Add plugin marketplace** with the configuration observed in the user's successful installation:

| Field | Value |
| --- | --- |
| Source | `HERRY423/Plugin-Value-Lab` |
| Git reference | `main` |
| Sparse paths | Leave empty; `plugins/codex` is a gray placeholder |

The full source URL is `https://github.com/HERRY423/Plugin-Value-Lab.git`. Add the marketplace, search for **Plugin Value Lab**, then **install and enable** it. Its selector is `plugin-value-lab@plugin-value-lab-marketplace`. Adding a marketplace alone does not put its plugins in the installed list.

Start a new task, select the plugin with `@`, and ask it to call `example_value_suite`, then `validate_value_suite`, without starting a model evaluation. Expected fields are `real_observations: 0` and `valid: true`; calibration warnings remain visible. Reopen Codex if the new task does not load the plugin.

`main` was the actual installed reference. To pin the published release instead, use `v0.5.0`. A branch can move; inspect the installed version. [Installed 0.5.0 acceptance, 2026-09-23](INSTALLED-ACCEPTANCE-20260923.zh-CN.md) records 11 calls across all six default MCP tools, scientific checks and offline replay; it is not a plugin-benefit study.

If the marketplace was added but the plugin is missing, clear any installed-only filter and search again. The following fallback was checked against local CLI help; it is not a claim about which commands the user ran:

```powershell
codex plugin marketplace upgrade plugin-value-lab-marketplace
codex plugin add plugin-value-lab@plugin-value-lab-marketplace
```

These commands refresh the configured Git marketplace and install its plugin. Reopen Codex and start a new task afterward. Use the desktop refresh/install controls if your CLI does not offer these commands.

## Runtime requirements

Requires Python 3.11+. The deterministic core has no third-party runtime dependencies. MCP integration additionally needs `mcp>=1.12,<2`; h5ad checks need the optional `science` extra.

An installed plugin bundles its engine; you do not need to install the source project with pip. If the host's Python lacks the MCP SDK, install it in that same environment, for example `python -m pip install "mcp==1.28.1"`. Skip this when tools already work. Dependency installation downloads code from your configured package index; installing the plugin starts no model evaluation and requires no plugin-specific API key.

From a source checkout:

```sh
python -m pip install ".[mcp,science]"
python scripts/value_lab.py doctor
```

For a desktop marketplace, extract the marketplace ZIP or use the actual checkout directory. Select the absolute directory containing `.agents/plugins/marketplace.json`. Leave the Git reference and sparse path empty for a local source. Install and enable the plugin after adding the marketplace.

The public repository already contains the marketplace; creating your own repository or downloading a ZIP first is unnecessary for the GitHub route. Local folders remain an alternative. The portable Agent Plugins archive contains `plugin.json`, `mcp.json`, two default skills and the bundled runtime. The research skill is retained under `extensions/` outside automatic discovery; research/team tools need explicit `--enable-extensions` before the CLI command. Resolve paths from the extracted location; no developer-machine path is required. See [scope and opt-in](STRUCTURAL-RISKS.zh-CN.md).

Run `doctor` with the same Python used by the host. This establishes local dependency availability only. A fresh host session and an actual MCP tool call are separate checks.

Claude workbench execution needs an existing Claude account. Codex CLI execution needs an existing Codex login and separate authorization to send task/plugin contents to its provider. Installation by itself starts neither kind of model evaluation.

See [中文安装指南](INSTALL.zh-CN.md) for host-specific manifests and [Codex collection](CODEX.md) for execution limits.
