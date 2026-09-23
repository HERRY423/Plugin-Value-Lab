# Install

Requires Python 3.11+. The deterministic core has no third-party runtime dependencies. MCP integration additionally needs `mcp>=1.12,<2`; h5ad checks need the optional `science` extra.

From a source checkout:

```sh
python -m pip install ".[mcp,science]"
python scripts/value_lab.py doctor
```

For a desktop marketplace, extract the marketplace ZIP or use the actual checkout directory. Select the absolute directory containing `.agents/plugins/marketplace.json`. Leave the Git reference and sparse path empty for a local source. Install and enable the plugin after adding the marketplace.

Use your actual accessible Git remote and an existing revision for a Git source. A local archive or configured remote does not mean a public release exists. The portable Agent Plugins archive contains `plugin.json`, `mcp.json`, two default skills and the bundled runtime. The research skill is retained under `extensions/` outside automatic discovery; research/team tools need explicit `--enable-extensions` before the CLI command. Resolve paths from the extracted location; no developer-machine path is required. See [scope and opt-in](STRUCTURAL-RISKS.zh-CN.md).

Run `doctor` with the same Python used by the host. This establishes local dependency availability only. A fresh host session and an actual MCP tool call are separate checks.

Claude workbench execution needs an existing Claude account. Codex CLI execution needs an existing Codex login and separate authorization to send task/plugin contents to its provider. Installation by itself starts neither kind of model evaluation.

See [中文安装指南](INSTALL.zh-CN.md) for host-specific manifests and [Codex collection](CODEX.md) for execution limits.
