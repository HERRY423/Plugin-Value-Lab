"""Complete native repair retests; descriptive evidence, never causal promotion."""
from collections import Counter
from pathlib import Path
import math

from .core import ValidationError, load_json, suite_digest, write_json
from .native_evidence import _fresh, _separate, verify_native_evidence


def validate_context(value):
    fields = {"host_version", "model", "model_version", "environment", "tools", "max_turns", "timeout_seconds", "max_cost_usd"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError("execution_context requires explicit host/model versions, environment, tools and run limits")
    for key in ("host_version", "model", "model_version", "environment"):
        if not isinstance(value[key], str) or not value[key].strip() or any(c in value[key] for c in "\x00\r\n"):
            raise ValidationError("Invalid execution_context text: " + key)
    if (not isinstance(value["tools"], list) or not value["tools"]
            or any(not isinstance(t, str) or not t.strip() for t in value["tools"])
            or len(set(value["tools"])) != len(value["tools"])):
        raise ValidationError("execution_context.tools requires unique tool names")
    for key, upper in (("max_turns", 200), ("timeout_seconds", 3600)):
        if type(value[key]) is not int or not 1 <= value[key] <= upper:
            raise ValidationError("Invalid execution_context limit: " + key)
    price = value["max_cost_usd"]
    if type(price) not in (int, float) or not math.isfinite(price) or price <= 0:
        raise ValidationError("Explicit positive finite native estimate ceiling required")


def compare_native_repair(before, before_digest, after, after_digest, output):
    output = _fresh(output)
    roots = [Path(before).resolve(), Path(after).resolve()]
    for root in roots:
        _separate(root, output)
    reports = [verify_native_evidence(root, digest)["diagnosis"]
               for root, digest in zip(roots, (before_digest, after_digest))]
    plans = [load_json(root / "plan.json") for root in roots]
    records = [load_json(root / "records.json") for root in roots]
    natives = [load_json(root / "native-result.json") for root in roots]
    protocol_changes, gaps = [], []
    for field in ("contract", "case_files", "references"):
        if plans[0][field] != plans[1][field]:
            protocol_changes.append(field)
    identities = [p.get("plugin_identity") or {} for p in plans]
    if not identities[0].get("name") or identities[0].get("name") != identities[1].get("name"):
        protocol_changes.append("plugin_name")
    changed = sorted(k for k in set(plans[0]["plugin_files"]) | set(plans[1]["plugin_files"])
                     if plans[0]["plugin_files"].get(k) != plans[1]["plugin_files"].get(k))
    session_sets = []
    for side, (plan, raw_records, native, report) in enumerate(zip(plans, records, natives, reports)):
        label = "before" if side == 0 else "after"
        context = plan["contract"].get("execution_context")
        if context is None:
            gaps.append(label + ": frozen execution context absent")
        elif native.get("claudeVersion") != context["host_version"]:
            gaps.append(label + ": observed host version differs or is missing")
        if native.get("partial") is not False:
            gaps.append(label + ": partial or unknown native completion")
        cases = {c["name"]: c for c in plan["contract"]["cases"]}
        sessions = []
        for record, run in zip(raw_records, report["runs"]):
            key = f"{label}:{run['case_id']}/{run['arm']}/{run['repetition']}"
            case = cases[run["case_id"]]
            if case["inputs"] and "input_sha256" not in case:
                gaps.append(key + ": input bytes not frozen")
            if any(s != "MATCH" for s in run.get("input_integrity", {}).values()):
                gaps.append(key + ": input changed or missing")
            if run["status"] != "completed" or any(g["passed"] is None for g in run["grades"]):
                gaps.append(key + ": failed/missing execution or unresolved grade")
            if "execution" in run and run["execution"]["status"] != "TOOL_REPORTED_SUCCESS":
                gaps.append(key + ": successful script tool result not observed")
            if "execution" in run and (run["execution"]["terminal_status"] != "SUCCESS" or run["execution"]["model_conflict_observed"]):
                gaps.append(key + ": terminal trace failed/unknown or assistant model changed")
            obs = run.get("observations") or {}
            sid = record.get("session_id")
            if not sid or not obs.get("trace_complete"):
                gaps.append(key + ": complete distinct session trace absent")
            else:
                sessions.append(sid)
            plugins = obs.get("plugins")
            names = [p.get("name") for p in plugins if isinstance(p, dict)] if isinstance(plugins, list) else None
            expected_names = [identities[side].get("name")] if run["arm"] == "with" else []
            if names != expected_names:
                gaps.append(key + ": plugin exposure absent or baseline contaminated")
            if context and (obs.get("model") != context["model"] or obs.get("claude_code_version") != context["host_version"]
                            or not isinstance(obs.get("tools"), list) or set(obs["tools"]) != set(context["tools"])):
                gaps.append(key + ": observed host/model/tools differ or are missing")
        if len(sessions) != len(set(sessions)):
            gaps.append(label + ": repeated session identity")
        session_sets.append(set(sessions))
    if before_digest == after_digest or session_sets[0] & session_sets[1]:
        gaps.append("same evidence or native session reused across revisions")
    # Counts are case-level marginals; native array positions are not pairs.
    groups = []
    for report in reports:
        grouped = {}
        for run in report["runs"]:
            for grade in run["grades"]:
                key = (run["case_id"], run["arm"], grade["id"])
                counts = grouped.setdefault(key, Counter())
                counts["pass" if grade["passed"] is True else "fail" if grade["passed"] is False else "unknown"] += 1
        groups.append(grouped)
    rows, regressions, repaired, baseline_changes = [], [], [], []
    for key in sorted(set(groups[0]) | set(groups[1])):
        counts = [{k: group.get(key, {}).get(k, 0) for k in ("pass", "fail", "unknown")} for group in groups]
        previous, current = counts
        row = {"case_id": key[0], "arm": key[1], "grader_id": key[2], "before": previous, "after": current}
        rows.append(row)
        if current["fail"] > previous["fail"] or current["unknown"] > previous["unknown"]:
            regressions.append(key)
        if key[1] == "without" and previous != current:
            baseline_changes.append(key)
        if key[1] == "with" and previous["fail"] > 0 and current["pass"] > 0 and current["fail"] == current["unknown"] == 0:
            repaired.append(key)
    if protocol_changes:
        status = "PROTOCOL_CHANGED"
    elif gaps:
        status = "INCOMPLETE_EVIDENCE"
    elif regressions:
        status = "REGRESSION_OBSERVED"
    elif baseline_changes:
        status = "BASELINE_CHANGED_REVIEW_REQUIRED"
    elif not any(k not in {"plugin.json", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json"} for k in changed):
        status = "NO_CANDIDATE_CHANGE"
    elif repaired and all(row["after"]["fail"] == row["after"]["unknown"] == 0 for row in rows if row["arm"] == "with"):
        status = "LOCAL_RETEST_IMPROVEMENT"
    else:
        status = "NO_COMPLETE_REPAIR_OBSERVED"
    report = {"schema_version": 1, "status": status, "before_receipt_sha256": before_digest,
              "after_receipt_sha256": after_digest, "protocol_changes": protocol_changes,
              "evidence_gaps": gaps, "changed_selected_plugin_files": changed, "checks": rows,
              "repaired_checks": repaired, "regressions": regressions, "baseline_changes": baseline_changes,
              "comparison_eligible": False, "paired_repetition_claim": False,
              "new_observations_by_comparator": 0, "independent_review": "PENDING",
              "scope": "Descriptive full-suite retest of selected candidate bytes; declarations and traces do not authenticate execution, exact model weights, unlisted dependencies, causality or biological truth."}
    output.mkdir(parents=True)
    write_json(output / "repair.json", report)
    lines = ["# 原生修复复测", "", status, "", "保留全部案例、对照臂和失败；数组位置不当作配对样本。", ""]
    for row in rows:
        lines.append(f"- {row['case_id']} / {row['arm']} / {row['grader_id']}: {row['before']} → {row['after']}")
    lines.extend(["", "## 条件变化与证据缺口", "", *["- " + s for s in protocol_changes + gaps], "", report["scope"], ""])
    (output / "REPAIR.md").write_text("\n".join(lines), encoding="utf-8")
    return {"output": str(output), "report_sha256": suite_digest(report), "report": report}
