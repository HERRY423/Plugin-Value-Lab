"""Local MCP analysis with opt-in, host-confined read-only artifact access."""
import os
from pathlib import Path

from .core import ValidationError, demo_suite, evaluate, suite_digest, validate_suite


def _configured_root(value):
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute() or not path.is_dir():
        raise ValidationError("MCP material roots must be existing absolute directories")
    # Authorization is pinned at server creation, never supplied by tool arguments.
    return path.resolve(strict=True)


def _material_root(allowed, requested, name):
    if allowed is None:
        if requested is not None:
            raise ValidationError(f"{name} is not authorized by the host; configure PVL_{name.upper()} and restart MCP")
        return None
    from .artifacts import confined
    if requested is None:
        selected = allowed
    else:
        if not requested or ".." in requested.replace("\\", "/").split("/"):
            raise ValidationError(f"{name} must stay within its host-authorized directory")
        candidate = Path(requested)
        if candidate.is_absolute():
            try:
                relative = candidate.relative_to(allowed).as_posix()
            except ValueError as exc:
                raise ValidationError(f"{name} is outside its host-authorized directory") from exc
        else:
            relative = requested
        selected = allowed if relative == "." else confined(allowed, relative)
    # Detect replacement of the authorized root with a link after startup too.
    if allowed.resolve() != allowed or not selected.is_dir():
        raise ValidationError(f"{name} is unavailable or changed since host authorization")
    return selected


def create_server(*, enable_extensions=False, artifact_root=None, verifier_root=None):
    artifacts = _configured_root(artifact_root)
    verifiers = _configured_root(verifier_root)
    if artifacts is not None and verifiers is not None and (
            artifacts.is_relative_to(verifiers) or verifiers.is_relative_to(artifacts)):
        raise ValidationError("MCP artifact and scorer directories must be separate and non-overlapping")

    def analyze(function, suite, records, lock, cost_ledger, artifact_root, verifier_root):
        from .artifacts import read_only_verification
        options = {"artifact_root": _material_root(artifacts, artifact_root, "artifact_root"),
                   "verifier_root": _material_root(verifiers, verifier_root, "verifier_root")}
        with read_only_verification():
            return function(suite, records, lock, cost_ledger, **options)

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise ValidationError('MCP SDK missing from this Python. Install with the host Python: python -m pip install "mcp==1.28.1"; then restart the plugin connection. See docs/history/INSTALL.zh-CN.md.') from exc
    mcp = FastMCP("Plugin Value Lab", instructions=(
        "Compare paired runs, locate failures and plan a bounded repair/retest for plugin authors. Registration is optional. "
        "All tools are local and read-only. "
        "Artifact checks read hash-bound files only under host-configured PVL_ARTIFACT_ROOT and PVL_VERIFIER_ROOT. "
        "Executable graders stay unresolved over MCP. "
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
    def evaluate_plugin_value(suite: dict, records: list[dict], lock: dict | None = None, cost_ledger: dict | None = None,
                              artifact_root: str | None = None, verifier_root: str | None = None) -> dict:
        """Recheck actual files and return digest-bound receipts with paired quality/cost.

        Optional roots select subdirectories within the host-authorized roots; omitted
        roots use host defaults. Without host configuration, object-only checks remain
        available and missing files stay unknown. Never execute submitted programs.
        """
        return analyze(evaluate, suite, records, lock, cost_ledger, artifact_root, verifier_root)

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
    def plan_plugin_use(context: dict, artifact_root: str | None = None, verifier_root: str | None = None) -> dict:
        """Plan ordinary use, or select a minimal task plan from frozen raw evidence in context.task_selection.

        Selection compares native, existing scripts/workflows and scoped plugin capabilities,
        retains unknown alternatives and requires whole-plan evidence for compositions.
        context.evidence_acquisition plans prospective decision-relevant batches under
        a frozen budget/stop rule, retaining separate screening and confirmation.
        context.evidence_bridge compares an immutable source to a target matrix task,
        verifies input differences and prepares/regrades a separate target bridge.
        Optional material roots narrow host-authorized directories, as in evaluation.
        No registry lookup, account action, program execution or external call.
        """
        from .workflow import plan_plugin_use as plan
        from .artifacts import read_only_verification
        with read_only_verification():
            return plan(context, artifact_root=_material_root(artifacts, artifact_root, "artifact_root"),
                        verifier_root=_material_root(verifiers, verifier_root, "verifier_root"))

    @mcp.tool()
    def build_plugin_usage_card(suite: dict, records: list[dict], lock: dict | None = None, cost_ledger: dict | None = None,
                                artifact_root: str | None = None, verifier_root: str | None = None) -> dict:
        """Recheck scoped guidance and file receipts; roots select host-authorized material directories.

        Omitted roots use host defaults; unconfigured file checks remain unknown.
        No program execution or inferred installation, connection or removal authority.
        """
        from .usage import build_usage_card
        return analyze(build_usage_card, suite, records, lock, cost_ledger, artifact_root, verifier_root)

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
    create_server(enable_extensions=enable_extensions,
                  artifact_root=os.environ.get("PVL_ARTIFACT_ROOT"),
                  verifier_root=os.environ.get("PVL_VERIFIER_ROOT")).run(transport="stdio")
