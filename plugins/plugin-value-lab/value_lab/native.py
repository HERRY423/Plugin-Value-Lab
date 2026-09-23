"""Conservative interoperability with Claude Code's documented plugin evals v1.

This module plans commands, but never launches a model, executes a plugin, or
publishes a report. Native aggregates are useful diagnostics; they are not a
substitute for the observation/provenance fields required by Value Lab.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from .core import ValidationError, suite_digest, validate_suite


DOC_URL = "https://code.claude.com/docs/en/plugin-evals"
JUDGE_MODEL = "claude-haiku-4-5"
EVAL_DIR = "value-lab-evals"
NATIVE_IMPORT_LIMIT = (
    "The documented native v1 result does not establish observed session IDs, "
    "frozen conditions, suite hash, plugin load receipts, final output, or an "
    "explicit mapping of every local outcome grader. Import is diagnostic only."
)


def _object(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    return value


def _number(value: Any, label: str, *, score: bool = False) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValidationError(f"{label} must be a finite number or null")
    if score and not 0 <= value <= 1:
        raise ValidationError(f"{label} must lie between 0 and 1")
    return float(value)


def _delta(value: Any, label: str) -> float | None:
    number = _number(value, label)
    if number is not None and not -1 <= number <= 1:
        raise ValidationError(f"{label} must lie between -1 and 1")
    return number


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\x00\r\n"):
        raise ValidationError(f"{label} must be a nonempty single-line string")
    return value


def _component(value: Any, label: str) -> str:
    value = _text(value, label)
    # Portable filenames, including Windows reserved device names.
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value)
            or value.endswith(".") or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", value)):
        raise ValidationError(f"{label} is not a portable safe path component: {value!r}")
    return value


def _literal_js_regex(value: str) -> str:
    """Escape regex metacharacters, preserving exact case-sensitive substring semantics."""
    return re.sub(r"([\\^$.*+?()\[\]{}|])", r"\\\1", value)


def _frontmatter(fields: dict, body: str = "") -> str:
    # JSON values are valid YAML values and quote colons, multiline text, etc.
    lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fields.items()]
    return "\n".join(lines) + "\n---\n" + body + "\n"


def build_command(plugin_path, output_dir, model, max_cost_usd, runs=3) -> list[str]:
    """Return an argument vector only. The caller must never pass it to a shell.

    max_cost_usd is a native list-price estimate ceiling; an in-flight run can
    exceed it. It is not a settled-spend cap or an AgentMuxer authorization.
    """
    model = _text(model, "model")
    if model.startswith("-"):
        raise ValidationError("model must not start with '-'")
    amount = _number(max_cost_usd, "max_cost_usd")
    if amount is None or amount <= 0:
        raise ValidationError("max_cost_usd must be positive and explicitly specified")
    if isinstance(runs, bool) or not isinstance(runs, int) or not 1 <= runs <= 50:
        raise ValidationError("runs must be an integer from 1 to 50")
    plugin = str(Path(_text(str(plugin_path), "plugin_path")).resolve())
    output = str(Path(_text(str(output_dir), "output_dir")).resolve())
    return [
        "claude", "plugin", "eval", plugin,
        "--eval-dir", EVAL_DIR,
        "--ablation", "with-without", "--runs", str(runs),
        "--model", model, "--judge-model", JUDGE_MODEL,
        "--concurrency", "1", "--mocks", "record", "--no-scaffold",
        "--no-publish", "--max-cost-usd", format(amount, ".15g"),
        "--output-dir", output,
    ]


def export_claude(suite, output_dir, plugin_path):
    """Stage a portable native suite without changing the plugin under test.

    Copy returned evals_dir to returned install_directory after reviewing it.
    Refuse semantic substitutions (notably JSON equality). A human rubric can
    be exported for model-judge diagnostics, never as completed human review.
    """
    validate_suite(suite)
    files: dict[str, str] = {}
    mappings = []
    warnings = [
        "Native estimated cost may exceed the ceiling by an in-flight run; it is not settled spend.",
        "The generated command is a plan only. No model or plugin has been executed.",
        "Native thresholds do not enforce Value Lab critical-grader and evidence rules.",
        "Observed conditions and plugin load state still require collection; export settings are expectations.",
    ]
    case_names: set[str] = set()
    for case in suite["cases"]:
        name = _component(case["id"], "case id")
        if name.casefold() in case_names:
            raise ValidationError("case ids collide on a case-insensitive filesystem")
        case_names.add(name.casefold())
        fields = {
            "name": name, "runs": suite["runs_per_case"],
            "model": suite["conditions"]["model"],
            "allowed_tools": suite["conditions"]["tools"],
        }
        budget = suite["conditions"]["budget"]
        for key, upper in (("max_turns", 200), ("timeout_seconds", 3600)):
            if key in budget:
                if isinstance(budget[key], bool) or not isinstance(budget[key], int) or not 1 <= budget[key] <= upper:
                    raise ValidationError(f"conditions.budget.{key} must be an integer from 1 to {upper}")
                fields[key] = budget[key]
        files[f"evals/{name}/prompt.md"] = _frontmatter(fields, case["prompt"])
        grader_names: set[str] = set()
        for grader in case["graders"]:
            grader_name = _component(grader["id"], "grader id")
            if grader_name.casefold() in grader_names:
                raise ValidationError(f"grader ids in {name} collide on a case-insensitive filesystem")
            grader_names.add(grader_name.casefold())
            source_type = grader["type"]
            fields = {"weight": grader["weight"], "arm": "with-only" if grader["dimension"] == "process" else "both"}
            body = ""
            if source_type in ("contains", "not_contains"):
                value = grader.get("value")
                if not isinstance(value, str):
                    raise ValidationError(f"{name}/{grader_name}: text grader value must be a string")
                fields.update(type="regex", pattern=_literal_js_regex(value), match=source_type, target="last_message")
            elif source_type == "human":
                fields.update(type="llm", focus="last_message")
                body = grader["rubric"]
                warnings.append(f"{name}/{grader_name}: exported as a model judge, not human review; real human review remains pending.")
            elif source_type == "json_equals":
                raise ValidationError(f"{name}/{grader_name}: json_equals has no exact native grader equivalent; export refused")
            else:
                raise ValidationError(f"Unsupported native grader type: {source_type}")
            files[f"evals/{name}/graders/{grader_name}.md"] = _frontmatter(fields, body)
            mappings.append({"case_id": name, "grader_id": grader_name, "source_type": source_type,
                             "native_type": fields["type"], "dimension": grader["dimension"],
                             "critical": grader["critical"], "human_review_satisfied": False})
    plugin = Path(plugin_path).resolve()
    output = Path(output_dir).resolve()
    command = None
    maximum = suite["conditions"]["budget"].get("max_cost_usd")
    if maximum is None:
        warnings.append("No command generated: set conditions.budget.max_cost_usd explicitly before planning a native run.")
    else:
        command = build_command(plugin, output / "native-results", suite["conditions"]["model"], maximum, suite["runs_per_case"])
        judge = suite["conditions"]["budget"].get("judge_model")
        if judge is not None:
            judge = _text(judge, "conditions.budget.judge_model")
            if judge.startswith("-"):
                raise ValidationError("judge_model must not start with '-'")
            command[command.index("--judge-model") + 1] = judge
    manifest = {
        "schema_version": 1, "suite_sha256": suite_digest(suite), "native_schema_version": 1,
        "docs": DOC_URL, "evals_dir": str(output / "evals"),
        "install_directory": str(plugin / EVAL_DIR), "command": command,
        "executed": False, "mappings": mappings, "warnings": warnings,
        "next_step": f"Review and copy the contents of evals into {plugin / EVAL_DIR}, then review the planned command. No files have been installed into the target plugin.",
    }
    files["export-manifest.json"] = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    files["suite.json"] = json.dumps(suite, indent=2, ensure_ascii=False) + "\n"
    files["README.md"] = (
        "# Native evaluation export\n\n" + manifest["next_step"] + "\n\n"
        "The argument vector in export-manifest.json is a plan, not a shell command. "
        "The plugin must be trusted interactively before running, and tool grants need explicit review. "
        "Real MCP servers, scaffold execution, automatic trust, and publishing are not enabled by this plan.\n\n"
        + "\n".join("- " + item for item in warnings) + "\n"
    )
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValidationError("Native export destination must be absent or empty; existing files will not be overwritten")
    output.mkdir(parents=True, exist_ok=True)
    for relative, contents in files.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(contents)
    return manifest


def _validate_result(result: Any) -> dict:
    result = _object(result, "native result")
    try:
        json.dumps(result, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValidationError("Native result must contain finite JSON values only") from exc
    if type(result.get("schemaVersion")) is not int or result["schemaVersion"] != 1:
        raise ValidationError("Only documented native schemaVersion 1 is supported")
    if not isinstance(result.get("cases"), list):
        raise ValidationError("native cases must be an array")
    if "partial" in result and not isinstance(result["partial"], bool):
        raise ValidationError("native partial must be boolean")
    if "partialReason" in result and result["partialReason"] is not None and not isinstance(result["partialReason"], str):
        raise ValidationError("native partialReason must be a string or null")
    for key in ("costUsd", "durationSeconds"):
        amount = _number(result.get(key), f"native {key}")
        if amount is not None and amount < 0:
            raise ValidationError(f"native {key} cannot be negative")
    if "claudeVersion" in result:
        _text(result["claudeVersion"], "native claudeVersion")
    if "aggregates" in result:
        aggregate = _object(result["aggregates"], "native aggregates")
        _number(aggregate.get("overallScore"), "aggregates.overallScore", score=True)
        _delta(aggregate.get("meanDelta"), "aggregates.meanDelta")
    seen = set()
    for case in result["cases"]:
        case = _object(case, "native case")
        name = _text(case.get("name"), "native case.name")
        if name in seen:
            raise ValidationError(f"Duplicate native case name: {name}")
        seen.add(name)
        arms = _object(case.get("arms"), f"native case {name}.arms")
        # Extra fields are forward-compatible, but unfamiliar arm labels could
        # silently discard a cohort, so those structural changes are refused.
        if set(arms) - {"with", "without"} or "with" not in arms:
            raise ValidationError(f"native case {name} requires with and optional without arms only")
        aggregate = _object(case.get("aggregates", {}), f"native case {name}.aggregates")
        _number(aggregate.get("score"), f"{name}.aggregates.score", score=True)
        _delta(aggregate.get("delta"), f"{name}.aggregates.delta")
        for arm, runs in arms.items():
            if not isinstance(runs, list):
                raise ValidationError(f"{name}.arms.{arm} must be an array")
            for run in runs:
                run = _object(run, f"{name}.{arm} run")
                if "error" not in run or (run["error"] is not None and not isinstance(run["error"], str)):
                    raise ValidationError(f"{name}.{arm} run.error must be explicitly null or a string")
                if "aborted" in run and run["aborted"] is not None:
                    aborted = _object(run["aborted"], "native aborted")
                    for key in ("server", "tool", "reason"):
                        _text(aborted.get(key), f"native aborted.{key}")
                if "skippedPaidGraders" in run and not isinstance(run["skippedPaidGraders"], bool):
                    raise ValidationError("native skippedPaidGraders must be boolean")
    return result


def _issues(result: dict, run: dict) -> list[str]:
    issues = [NATIVE_IMPORT_LIMIT]
    if result.get("partial"):
        issues.append("Native result is partial: " + str(result.get("partialReason") or "reason not supplied"))
    if run.get("skippedPaidGraders"):
        issues.append("Native run skipped paid graders; its native score is not comparable")
    if run.get("aborted"):
        issues.append("Native run aborted: " + run["aborted"]["reason"])
    if run.get("error") is not None:
        issues.append("Native run error: " + run["error"])
    return issues


def _status(run: dict) -> str:
    # Do not infer timeout from a free-form error string or guess unstarted runs.
    if run.get("aborted") is not None:
        return "aborted"
    return "error" if run["error"] is not None else "completed"


def import_claude(result, suite) -> list[dict]:
    """Preserve native observations as explicitly incomplete diagnostic records.

    Unknown additive fields remain in native.run. Only documented structural
    fields are interpreted; no undocumented score/grade/output/session field is
    guessed. Missing arms and unstarted runs are not fabricated.
    """
    validate_suite(suite)
    result = _validate_result(result)
    case_ids = {case["id"] for case in suite["cases"]}
    records = []
    digest = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    for case in result["cases"]:
        if case["name"] not in case_ids:
            raise ValidationError(f"Native case {case['name']!r} has no exact suite case mapping")
        for arm, runs in case["arms"].items():
            for index, run in enumerate(runs, 1):
                issues = _issues(result, run)
                issues.append("Repetition is the native array position; independent paired-run identity is not established")
                records.append({
                    "case_id": case["name"], "arm": arm, "repetition": index,
                    "suite_sha256": None, "session_id": None, "conditions": None,
                    "plugin_loaded": None, "status": _status(run), "error": run["error"],
                    "cost": {"model_usd": None, "tool_usd": None, "human_minutes": None},
                    "duration_seconds": None, "source": "claude", "grades": {},
                    "import_issues": issues,
                    "native": {"schema_version": 1, "result_sha256": digest,
                               "import_target_suite_sha256": suite_digest(suite),
                               "claude_version": result.get("claudeVersion"),
                               "partial": result.get("partial"), "partial_reason": result.get("partialReason"),
                               "total_estimated_cost_usd": result.get("costUsd"),
                               "total_duration_seconds": result.get("durationSeconds"),
                               "case_aggregates": deepcopy(case.get("aggregates", {})),
                               "run": deepcopy(run)},
                })
    return records


def native_report(result) -> dict:
    """Build a report-shaped, explicitly diagnostic view of documented v1 data."""
    result = _validate_result(result)
    cases = []
    observed = 0
    blockers = [NATIVE_IMPORT_LIMIT]
    if result.get("partial"):
        blockers.append("Native suite is partial: " + str(result.get("partialReason") or "unspecified"))
    for case in result["cases"]:
        runs = []
        for arm, arm_runs in case["arms"].items():
            for index, run in enumerate(arm_runs, 1):
                observed += 1
                runs.append({"arm": arm, "repetition": index, "status": _status(run),
                             "score": None, "grades": {}, "cost_usd": None,
                             "issues": _issues(result, run), "native": deepcopy(run)})
        if not case["arms"].get("without"):
            blockers.append(f"{case['name']}: no native baseline runs present")
        aggregates = case.get("aggregates", {})
        cases.append({"id": case["name"], "kind": "native_diagnostic", "cluster": None,
                      "with_score": aggregates.get("score"), "without_score": None,
                      "delta": aggregates.get("delta"), "runs": runs})
    aggregates = result.get("aggregates", {})
    return {
        "schema_version": 1, "study_id": "native-diagnostic", "plugin": {"name": "unbound native result", "version": "unknown"},
        "evidence_type": "unverified_native", "verdict": "insufficient_evidence",
        "summary": {"with_score": aggregates.get("overallScore"), "without_score": None,
                    "quality_delta": aggregates.get("meanDelta"), "expected_runs": None,
                    "observed_runs": observed, "complete_pairs": 0, "clusters": 0,
                    "cost_delta_usd": None, "with_cost_usd": None, "without_cost_usd": None,
                    "native_total_estimated_cost_usd": result.get("costUsd")},
        "blockers": blockers, "warnings": [
            "Displayed aggregate scores are native diagnostics; Value Lab has not recomputed or validated their grader semantics.",
            "Native costUsd is a list-price estimate including judges, not a settled bill or a per-arm total.",
            "Unknown native fields are preserved, not interpreted. No human review or scientific validity is established.",
        ], "cases": cases, "uncertainty": {"status": "unavailable"},
        "claim_limits": ["Diagnostic native result only; cannot establish plugin benefit."],
        "provenance": {"source": DOC_URL, "claude_version": result.get("claudeVersion"),
                       "native_duration_seconds": result.get("durationSeconds"), "native_result": deepcopy(result)},
    }
