"""Optional local MCP adapter. Tools process supplied objects, never execute evals."""
from .core import ValidationError, demo_suite, evaluate, suite_digest, validate_suite


def create_server(*, enable_extensions=False):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise ValidationError('MCP SDK missing from this Python. Install with the host Python: python -m pip install "mcp==1.28.1"; then restart the plugin connection. See docs/INSTALL.zh-CN.md.') from exc
    mcp = FastMCP("Plugin Value Lab", instructions=(
        "Compare paired runs, locate failures and plan a bounded repair/retest for plugin authors. Registration is optional. "
        "All tools are local and read-only. "
        "No tool runs a model, certifies external value or publishes results. Synthetic data remain synthetic."
    ), log_level="ERROR")

    @mcp.tool()
    def validate_value_suite(suite: dict, samples: dict | None = None) -> dict:
        """Validate a proposed paired study. This does not freeze it or attest observations."""
        validate_suite(suite)
        from .scoring import inspect_rules
        return {**inspect_rules(suite, samples), "suite_sha256": suite_digest(suite),
                "expected_runs": len(suite["cases"]) * suite["runs_per_case"] * 2}

    @mcp.tool()
    def evaluate_plugin_value(suite: dict, records: list[dict], lock: dict | None = None, cost_ledger: dict | None = None) -> dict:
        """Compute paired quality and declared total cost; fail closed on missing evidence."""
        return evaluate(suite, records, lock, cost_ledger)

    @mcp.tool()
    def inspect_claude_eval(result: dict) -> dict:
        """Inspect Claude native schemaVersion 1 diagnostics without upgrading them to a value claim."""
        from .native import native_report
        return native_report(result)

    @mcp.tool()
    def example_value_suite() -> dict:
        """Return a synthetic study template with zero observed executions."""
        return {"suite": demo_suite(), "records": [], "real_observations": 0}

    @mcp.tool()
    def plan_plugin_use(context: dict) -> dict:
        """Plan native/connected/discovery/evaluation use; no registry lookup, account action or external call."""
        from .workflow import plan_plugin_use as plan
        return plan(context)

    @mcp.tool()
    def build_plugin_usage_card(suite: dict, records: list[dict], lock: dict | None = None, cost_ledger: dict | None = None) -> dict:
        """Recompute evidence into scoped usage guidance; never infer install, connection, permission or removal authority."""
        from .usage import build_usage_card
        return build_usage_card(suite, records, lock, cost_ledger)

    def research_direction_advisor(action: str, context: dict | None = None,
                                   before: dict | None = None, after: dict | None = None) -> dict:
        """Diagnose task-specific research gaps and rank evidence-linked next tests supplied by the host Agent.

        Actions: example returns synthetic context; diagnose validates context and plans within declared
        resources; compare compares before/after contexts. Read the research-directions skill to form
        substantive contextual directions. This tool alone performs structural reasoning, not literature
        search or semantic/scientific validation. No models, installations, file reads or external calls.
        """
        from .research import compare_research, diagnose_research, research_example
        if action == "example" and all(x is None for x in (context, before, after)):
            return research_example()
        if action == "diagnose" and context is not None and before is None and after is None:
            return diagnose_research(context)
        if action == "compare" and context is None and before is not None and after is not None:
            return compare_research(before, after)
        raise ValidationError("Use example without inputs, diagnose with context, or compare with before and after")

    if enable_extensions:
        mcp.tool()(research_direction_advisor)
    return mcp


def serve(*, enable_extensions=False):
    create_server(enable_extensions=enable_extensions).run(transport="stdio")
