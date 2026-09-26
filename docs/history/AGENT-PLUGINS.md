> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# Agent Plugins 1.0.0 mapping

Specification checked 2026-09-22: https://agent-plugins.org/specification

| Contract | Implementation |
| --- | --- |
| Portable root manifest and exact schema ID | `plugin.json`; no inline skills/MCP fields |
| Fixed component discovery | `skills/assess-value`, `skills/use-plugin-well`, root `mcp.json` |
| OpenAI presentation namespace | `extensions.com.openai.interface` |
| Stdio single executable and separate args | `python`, bundled source entry point, `serve` |
| Standard root placeholder and cwd | `${PLUGIN_ROOT}/scripts/value_lab.py`, `cwd: ./` |
| Reserved variables supplied by host | No PLUGIN_ROOT/PLUGIN_DATA env override |
| Package containment | Distribution inventory rejects resolved paths outside plugin root |
| Persistent data | Server processes supplied objects only; no writes to package or host data directories |
| Schema validation without runtime fetch | Official schemas vendored under `schemas/agent-plugins/1.0.0`; URLs/date/SHA-256 in SOURCES.json |

`scripts/validate_agent_plugin.py` uses the official JSON Schemas plus checks specific to this plugin (identity consistency, both skills, bundled launch path, directory containment, reserved environment names). This is package validation, not a general client-conformance certification tool. Install the optional `dev` dependencies to run it. Normal plugin startup never downloads schemas or imports jsonschema.

The standalone Agent Plugins archive omits legacy client manifests/configuration. The marketplace distribution preserves explicitly separate Codex/Claude compatibility entry points. Root portable metadata and fixed locations remain canonical; host-specific legacy fields cannot redefine the portable contract. No invented client namespace is used.

Marketplace discovery and installation are outside the portable standard. The Codex catalog lives at `.agents/plugins/marketplace.json` and resolves `./plugins/plugin-value-lab` relative to the repository root. The Claude catalog uses its own string source shape at `.claude-plugin/marketplace.json`. The repository mirror is generated from an explicit inventory, excludes local `work`, `dist`, caches and result folders, and is checked byte for byte before release.

This package requires a local host with Python 3.11+ available as `python`; MCP additionally needs the SDK. Installing a catalog entry cannot provision a local Python runtime on a web-only host. Current developer testing uses Windows; other operating systems and all listed standard-compatible clients are not implicitly certified.

References: [portable manifest](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json), [portable MCP](https://agent-plugins.org/schemas/1.0.0/mcp.schema.json), [OpenAI packaging and compatibility semantics](https://developers.openai.com/plugins/build/plugins).
