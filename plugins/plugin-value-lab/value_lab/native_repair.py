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


def compare_native_repair(before, before_digest, after, after_digest, output, *, repair_record=None):
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
    report['repair_chain'] = _repair_chain(roots, plans, reports, report, repair_record)
    output.mkdir(parents=True)
    write_json(output / "repair.json", report)
    lines = ["# 原生修复复测", "", status, "", "保留全部案例、对照臂和失败；数组位置不当作配对样本。", ""]
    lines += ['修复链：' + report['repair_chain']['status'], '',
              *['- ' + gap for gap in report['repair_chain']['gaps']], '']
    for row in rows:
        lines.append(f"- {row['case_id']} / {row['arm']} / {row['grader_id']}: {row['before']} → {row['after']}")
    lines.extend(["", "## 条件变化与证据缺口", "", *["- " + s for s in protocol_changes + gaps], "", report["scope"], ""])
    (output / "REPAIR.md").write_text("\n".join(lines), encoding="utf-8")
    return {"output": str(output), "report_sha256": suite_digest(report), "report": report}


def _repair_chain(roots, plans, diagnoses, comparison, record):
    """A local chain is additional evidence, never implied by a passing artifact.

    Operator mapping of diagnosis to edit is retained as a claim. Trace support
    cannot certify natural use, execution authenticity or causal effectiveness.
    """
    from .artifacts import confined
    from .native_hypotheses import skill_events
    gaps, links = [], []
    if comparison['status'] != 'LOCAL_RETEST_IMPROVEMENT':
        gaps.append('Complete comparable repair improvement has not been observed')
    if record is None:
        gaps.append('Missing author repair record linking the prior diagnosis to changed plugin files and natural-use intent')
    else:
        fields = {'before_receipt_sha256', 'before_diagnosis_sha256', 'use_mode', 'evidence_type', 'repairs'}
        if not isinstance(record, dict) or set(record) != fields:
            raise ValidationError('Repair record needs before receipt/diagnosis digests, use_mode, evidence_type and repairs')
        if record['use_mode'] not in ('natural', 'explicit_probe') or record['evidence_type'] not in ('synthetic', 'local', 'external'):
            raise ValidationError('Declare use mode and evidence type; declarations are not authenticated')
        if record['before_receipt_sha256'] != comparison['before_receipt_sha256'] or record['before_diagnosis_sha256'] != suite_digest(diagnoses[0]):
            raise ValidationError('Repair record is not bound to the verified before diagnosis')
        if record['use_mode'] != 'natural':
            gaps.append('Explicit invocation probe is not a natural-use retest')
        if record['evidence_type'] == 'synthetic':
            gaps.append('Manufactured traces cannot establish an observed real repair chain')
        if not isinstance(record['repairs'], list) or not record['repairs']:
            raise ValidationError('Repair record requires at least one diagnosis-to-edit link')
        seen = set()
        for item in record['repairs']:
            if not isinstance(item, dict) or set(item) != {'case_id', 'grader_id', 'skill', 'changed_files', 'rationale'}:
                raise ValidationError('Each repair needs case_id, grader_id, skill, changed_files and rationale')
            if any(not isinstance(item[k], str) or not item[k].strip() for k in ('case_id', 'grader_id', 'skill', 'rationale')):
                raise ValidationError('Repair link text must be nonempty')
            key = (item['case_id'], 'with', item['grader_id'])
            if key in seen or key not in comparison['repaired_checks']:
                raise ValidationError('Repair link must name a unique actually repaired failed check')
            seen.add(key)
            if (not isinstance(item['changed_files'], list) or not item['changed_files']
                    or any(not isinstance(p, str) or p not in comparison['changed_selected_plugin_files'] for p in item['changed_files'])):
                raise ValidationError('Repair link must identify changed selected candidate bytes')
            plugin_name = plans[0]['plugin_identity']['name']
            # Namespaced Skill identity is required; an unrelated tool cannot close the chain.
            if not item['skill'].startswith(plugin_name + ':') or item['skill'] == plugin_name + ':':
                gaps.append('Expected skill must be namespaced to the tested plugin: ' + item['case_id'])
            observations = []
            for side, (root, diagnosis) in enumerate(zip(roots, diagnoses)):
                for index, run in enumerate(diagnosis['runs']):
                    if run['case_id'] != item['case_id'] or run['arm'] != 'with':
                        continue
                    # Before evidence must connect the actual failed result to a call.
                    grades = [g for g in run['grades'] if g['id'] == item['grader_id']]
                    if side == 0 and not any(g['passed'] is False for g in grades):
                        continue
                    trace = confined(root, f'runs/{index}/events.jsonl')
                    text = trace.read_text(encoding='utf-8-sig') if trace.is_file() else ''
                    calls = skill_events(text, f'runs/{index}/events.jsonl')
                    matching = [c for c in calls if c['skill'] == item['skill'] and c['result_status'] == 'TOOL_REPORTED_SUCCESS']
                    numbered = [n for n, line in enumerate(text.splitlines(), 1) if line.strip()]
                    executions = [e for e in (run.get('execution') or {}).get('calls', []) if e['status'] == 'TOOL_REPORTED_SUCCESS']
                    command_line = min((numbered[e['call_event']] for e in executions), default=0)
                    ordered = [c for c in matching if c['result_evidence']['line'] < command_line]
                    if not ordered:
                        gaps.append(f"{'before' if side == 0 else 'after'}:{run['case_id']}/{run['repetition']}: plugin result before artifact-producing script not established")
                    observations.append({'revision': 'before' if side == 0 else 'after',
                                         'case_id': run['case_id'], 'repetition': run['repetition'], 'calls': matching})
                    if not matching:
                        gaps.append(f"{'before' if side == 0 else 'after'}:{run['case_id']}/{run['repetition']}: successful tested-plugin invocation not observed")
            links.append({**item, 'observations': observations, 'causal_attribution': 'AUTHOR_HYPOTHESIS'})
        if seen != set(comparison['repaired_checks']):
            gaps.append('Repair record does not cover every repaired check')
    if any('diagnostic_intent' in p['contract'] for p in plans):
        gaps.append('Frozen protocol identifies an explicit diagnostic probe')
    for side, (root, plan, diagnosis) in enumerate(zip(roots, plans, diagnoses)):
        plugin = (plan.get('plugin_identity') or {}).get('name')
        for index, run in enumerate(diagnosis['runs']):
            trace = confined(root, f'runs/{index}/events.jsonl')
            if run['arm'] != 'without' or not trace.is_file():
                continue
            calls = skill_events(trace.read_text(encoding='utf-8-sig'), f'runs/{index}/events.jsonl')
            if any(plugin and isinstance(c['skill'], str) and c['skill'].startswith(plugin + ':')
                   and c['result_status'] == 'TOOL_REPORTED_SUCCESS' for c in calls):
                gaps.append(f"{'before' if side == 0 else 'after'}:{run['case_id']}: baseline invoked tested plugin")
    return {'status': 'OPEN' if gaps else 'TRACE_SUPPORTED_LOCAL_CHAIN', 'gaps': gaps, 'links': links,
            'repair_record': record, 'repair_record_sha256': suite_digest(record) if record is not None else None,
            'natural_use_independently_verified': False, 'causal_plugin_benefit_established': False,
            'use_recommendation': 'INSUFFICIENT_EVIDENCE',
            'scope': 'Skill-call traces plus an author-declared diagnosis/edit mapping. Does not authenticate declarations, execution, naturalness, adoption, cost savings or generalization.'}
