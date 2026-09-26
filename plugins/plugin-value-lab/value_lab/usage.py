"""Turn recomputed paired evidence into narrow, local plugin-use guidance.

No service is contacted and no plugin installation or permission is changed.
These cards describe the submitted cases; hashes do not prove data authenticity.
"""
from __future__ import annotations

import copy
import html
import json
import re
from pathlib import Path
from statistics import mean

from .core import ValidationError, evaluate, suite_digest


def diagnose(source, output, *, check=None, spec=None, audit=False, receipt=None,
             artifact_root=None, verifier_root=None, corpus_root=None, started=None):
    """Small author entry point. Timing is machine latency, never human adoption."""
    import time
    from .core import load_json, load_records, write_json
    from .artifacts import grade_artifact, sha, validate_verifier
    started = time.perf_counter() if started is None else started
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise ValidationError("Preserve earlier diagnoses; choose a new --output directory")
    if not source.exists():
        raise ValidationError("Source missing: supply an artifact file or collected study directory")
    if source == output or source.is_relative_to(output) or (source.is_dir() and output.is_relative_to(source)):
        raise ValidationError("Diagnosis output must be separate from its source")
    modes = int(audit) + int(check is not None) + int(spec is not None) + int(receipt is not None)
    if modes > 1:
        raise ValidationError("Choose one of --audit, --check, --spec or --receipt")
    if audit:
        from .methodology import audit_detector
        result = audit_detector(source, verifier_root=verifier_root)
        findings = [{k: r[k] for k in ('id', 'classification', 'reason', 'label_reason')}
                    for r in result['cases'] if r['classification'] not in ('TP', 'TN')]
        result['next_action'] = 'Review every FN, FP and UNKNOWN with its label basis; collect external adjudicated cases before claiming field accuracy.'
    elif source.is_dir() and (source / 'receipt.json').is_file():
        from .native_evidence import verify_native_evidence
        if not receipt:
            raise ValidationError("Native evidence requires --receipt with the separately retained digest")
        result = verify_native_evidence(source, receipt)['diagnosis']
        findings = [dict(case_id=r['case_id'], arm=r['arm'], repetition=r['repetition'], **g)
                    for r in result['runs'] for g in r['grades'] if g['passed'] is not True]
        from .native_hypotheses import skill_events
        from .artifacts import confined
        plugin = (load_json(source / 'plan.json').get('plugin_identity') or {}).get('name')
        result['invocation_observations'] = []
        for index, run in enumerate(result['runs']):
            if run['status'] != 'completed':
                findings.append({'case_id': run['case_id'], 'arm': run['arm'], 'kind': 'execution', 'reason': run['status']})
            if run['arm'] != 'with':
                continue
            trace = confined(source, f'runs/{index}/events.jsonl')
            calls = skill_events(trace.read_text(encoding='utf-8-sig'), f'runs/{index}/events.jsonl') if trace.is_file() else []
            matching = [c for c in calls if plugin and isinstance(c['skill'], str)
                        and c['skill'].startswith(plugin + ':') and c['result_status'] == 'TOOL_REPORTED_SUCCESS']
            result['invocation_observations'].append({'case_id': run['case_id'], 'repetition': run['repetition'], 'calls': matching})
            if not matching:
                findings.append({'case_id': run['case_id'], 'arm': 'with', 'repetition': run['repetition'],
                                 'kind': 'invocation_evidence_gap',
                                 'reason': 'Successful namespaced plugin Skill call not observed. Passing artifact checks cannot establish plugin use; other invocation mechanisms are not assessed.'})
        result['next_action'] = ('Inspect runtime errors, missing evidence and invocation traces first. '
                                 'Establish whether the failure belongs to the host or plugin before changing plugin bytes. '
                                 'Then repeat the complete frozen natural-use study with the relevant correction; '
                                 'missing evidence and absent Skill events alone do not establish a plugin defect.')
    elif source.is_dir():
        if modes:
            raise ValidationError("Artifact checks require a file; native --receipt requires a captured native directory")
        required = ('suite.json', 'runs.jsonl', 'protocol.lock.json')
        if any(not (source / p).is_file() for p in required):
            raise ValidationError("Study needs suite.json, runs.jsonl and protocol.lock.json; alternatively supply an artifact with --check bh or --spec")
        card = build_usage_card(load_json(source / required[0]), load_records(source / required[1]),
                                load_json(source / required[2]), artifact_root=artifact_root,
                                verifier_root=verifier_root, corpus_root=corpus_root)
        result = {'status': card['status'], 'card': card, 'next_action': card['improvement_plan']['next_experiment']['action']}
        findings = card['improvement_plan']['queue']
    else:
        if receipt:
            raise ValidationError("--receipt requires a captured native directory")
        if check == 'bh':
            grader = {'id': 'bh', 'type': 'artifact', 'artifact': 'result', 'verifier': {
                'kind': 'de_table', 'id_column': 'gene', 'p_column': 'p_value', 'q_column': 'q_value',
                'effect_column': 'log2fc', 'min_rows': 1, 'bh_tolerance': 1e-8}}
        elif spec:
            grader = load_json(spec)
        else:
            raise ValidationError("No statistical method inferred: use --check bh only when BH is required, or supply --spec grader.json")
        if not isinstance(grader, dict) or grader.get('type') != 'artifact':
            raise ValidationError("Quick diagnosis accepts only built-in artifact checks; supplied code is never executed")
        validate_verifier(grader)
        digest = sha(source)
        record = {'artifacts': {grader['artifact']: {'path': source.name, 'sha256': digest}}}
        passed, reason, evidence = grade_artifact(grader, record, source.parent, verifier_root)
        result = {'status': 'CONTRACT_PASSED' if passed is True else 'CONTRACT_FAILED' if passed is False else 'UNKNOWN',
                  'input_sha256': digest, 'grader': grader, 'passed': passed, 'reason': reason, 'evidence': evidence,
                  'rule_basis': 'OPERATOR_SELECTED_CONTRACT', 'plugin_defect_established': False,
                  'blind_spots': ['No plugin invocation or root cause established',
                                 'No scientific method choice, donor design or biological validity judged',
                                 'Submitted rows do not establish the full testing family without a frozen reference',
                                 'Finite effect sizes and input p-values are not independently recomputed'],
                  'next_action': 'Confirm the task actually requires this contract; inspect the linked failure and repeat the same check after repair. A pass alone does not close a native repair loop.'}
        findings = [] if passed is True else [{'passed': passed, 'reason': reason}]
    report = {'format': 'pvl-author-diagnosis-1', 'result': result, 'findings': findings,
              'timing': {'machine_seconds_to_diagnosis': time.perf_counter() - started,
                         'human_time_to_first_diagnosis_seconds': None,
                         'scope': 'CLI entry to computed diagnosis; excludes interpreter startup, installation, preparation, reading and repair'},
              'new_model_calls': 0}
    output.mkdir(parents=True)
    write_json(output / 'diagnosis.json', report)
    lines = ['# 作者诊断', '', _markdown(result.get('status')), '',
             f'待查看项：{len(findings)}。检查通过不代表插件整体正确。', '']
    for finding in findings:
        lines += ['- ' + _markdown(finding)]
    lines += ['', '下一步：' + _markdown(result['next_action']), '',
              '完整判据、证据和盲区见 diagnosis.json。机器耗时与作者首次定位耗时分开记录；后者仍未知。', '']
    (output / 'DIAGNOSIS.md').write_text('\n'.join(lines), encoding='utf-8')
    return {'status': result.get('status'), 'findings': len(findings), 'timing': report['timing'],
            'report': str(output / 'DIAGNOSIS.md'), 'json': str(output / 'diagnosis.json')}


_EPSILON = 1e-12
_FAILURES = {"error", "timeout", "aborted"}
_STATUSES = {
    "TRIAL_GUIDANCE_ONLY": "仅供设计试用，不能据此推荐实际使用",
    "BOUNDED_LOCAL_GUIDANCE": "仅适用于已观察任务及固定条件的使用参考",
    "REVIEW_REQUIRED": "先复核缺失证据或回退，再作使用判断",
}


def _counts(runs):
    return {
        "planned_runs": len(runs),
        "observed_runs": sum(run["status"] != "missing" for run in runs),
        "failed_runs": sum(run["status"] in _FAILURES for run in runs),
        "missing_runs": sum(run["status"] == "missing" for run in runs),
        "skipped_runs": sum(run["status"] == "skipped" for run in runs),
        "runs_with_issues": sum(bool(run["issues"]) for run in runs),
    }


def _case_cost_delta(case):
    """Mean with cost minus mean without cost, never a sum of repetitions."""
    costs = {
        arm: [run["cost_usd"] for run in case["runs"] if run["arm"] == arm]
        for arm in ("with", "without")
    }
    if any(not values or None in values for values in costs.values()):
        return None
    return mean(costs["with"]) - mean(costs["without"])


def _scenario(case, prompt, reason, cost_delta):
    return {
        "case_id": case["id"], "prompt": prompt, "reason": reason,
        "quality_delta": case["delta"], "cost_delta_usd": cost_delta,
        "with_score": case["with_score"], "without_score": case["without_score"],
        "run_counts": _counts(case["runs"]),
    }


def _improvement_plan(suite, report):
    """Locate actionable diagnostics without calling them proven plugin defects.

    Includes BOTH arms and unknown outcomes. Priorities reflect triage order,
    never estimated benefit or causal attribution. No new scoring policy.
    """
    queue = []
    cases = {case["id"]: case for case in suite["cases"]}
    for case in report["cases"]:
        for run in case["runs"]:
            ref = {"case_id": case["id"], "arm": run["arm"], "repetition": run["repetition"]}
            if run["status"] != "completed":
                queue.append({**ref, "priority": 0, "kind": "execution", "status": run["status"],
                    "evidence": run.get("error") or run["issues"] or run["status"],
                    "action": "核对原始会话、加载记录与执行错误；保留失败，在新研究中复测，不覆盖原运行。"})
            if run["issues"]:
                queue.append({**ref, "priority": 0, "kind": "evidence", "evidence": run["issues"],
                    "action": "先补核来源、配对条件、成本或复核缺口；证据阻断不能直接归因于插件实现。"})
            for grade in run["grades"]:
                if run["status"] != "completed" or grade["passed"] is True or not grade["scored"]:
                    continue
                rule = next(g for g in cases[case["id"]]["graders"] if g["id"] == grade["id"])
                queue.append({**ref, "priority": 1 if grade["critical"] else 2,
                    "kind": "outcome", "criterion_id": grade["id"], "criterion_type": rule["type"],
                    "passed": grade["passed"], "critical": grade["critical"], "evidence": grade["rationale"],
                    "action": "对照冻结判据检查实际产物；修复相关行为后同时复测正确处理和不应拒绝的任务。"
                        if grade["passed"] is False else "结果尚未知：补齐产物或真实人工复核，不把未知当作已证实缺陷。"})
    queue.sort(key=lambda item: (item["priority"], item["case_id"], item["arm"], item["repetition"]))
    for item in queue:
        if item["kind"] == "outcome" and item.get("passed") is False:
            prediction = "在原输入、评分参考与阈值不变时，失败判据转为通过，且正常与不应拒答对照不退步。"
            falsifier = "失败仍存在、对照退步，或只有修改输入、阈值或删减案例才通过。"
        else:
            prediction = "补充的实际会话、产物或复核记录能明确原缺口；保留原有失败记录。"
            falsifier = "新增记录仍缺失或与原记录冲突；不能把执行恢复等同于科研结果修复。"
        item["testable_hypothesis"] = {"status": "UNTESTED", "observed_fact": item["evidence"],
            "intervention": item["action"], "prediction": prediction, "falsifier": falsifier,
            "causal_claim": False, "explicit_invocation_is_diagnostic_only": True}
    return {
        "status": "SIMULATION_ONLY" if report["evidence_type"] == "synthetic" else "DIAGNOSTIC_ONLY",
        "registration_required": False, "publication_required": False,
        "suite_sha256": report["provenance"]["suite_sha256"],
        "records_sha256": report["provenance"]["records_sha256"],
        "queue": queue, "study_blockers": list(report["blockers"]),
        "next_experiment": {
            "case_ids": [case["id"] for case in suite["cases"]],
            "planned_runs": len(suite["cases"]) * suite["runs_per_case"] * 2,
            "runs_per_case_per_arm": suite["runs_per_case"],
            "conditions": copy.deepcopy(suite["conditions"]), "policy": copy.deepcopy(report["policy"]),
            "action": "一次只改待测插件的一个行为，记录内容摘要；无需改版本号。冻结新研究，重跑完整的两组任务，再用 compare-studies 检查可比性与回退。",
            "preserve": "保留原研究、失败、负面与未知结果；修复用例后的重测仅是开发集诊断，泛化需新的未暴露任务。",
            "estimated_cost_usd": None, "estimated_human_minutes": None,
            "execution_authorized": False,
        },
        "value_hypothesis": "让作者定位并复现问题、减少下一次试验准备和人工修正；尚未测量这些收益。",
    }


def build_usage_card(suite, records, lock=None, cost_ledger=None, *, artifact_root=None, verifier_root=None, corpus_root=None):
    """Recompute evaluation from inputs; a precomputed verdict is never accepted.

    All recommendations are descriptive and bound to exact inputs and conditions.
    Even user-declared external evidence cannot establish universal effectiveness.
    """
    report = evaluate(suite, records, lock, cost_ledger, artifact_root=artifact_root,
                      verifier_root=verifier_root, corpus_root=corpus_root)
    policy, summary = report["policy"], report["summary"]
    synthetic = report["evidence_type"] == "synthetic"
    eligible = summary["comparison_eligible"] and not report["blockers"]
    non_regressed = report["verdict"] in {"PROMISING_LOCAL_SIGNAL", "NO_DEMONSTRATED_GAIN"}
    can_describe = eligible and not synthetic and non_regressed
    can_support = can_describe and report["verdict"] == "PROMISING_LOCAL_SIGNAL"
    objective = policy.get("objective", "quality")
    cost_required = objective == "efficiency" or policy["require_cost_saving"]
    prompts = {case["id"]: case["prompt"] for case in suite["cases"]}
    use_when, prefer_baseline, investigate = [], [], []

    for case in report["cases"]:
        delta, with_score = case["delta"], case["with_score"]
        cost_delta = _case_cost_delta(case)
        counts = _counts(case["runs"])
        critical_failed = any(
            grade["critical"] and grade["passed"] is not True
            for run in case["runs"] if run["arm"] == "with"
            for grade in run["grades"]
        )
        baseline_critical_failed = any(
            grade["critical"] and grade["passed"] is not True
            for run in case["runs"] if run["arm"] == "without"
            for grade in run["grades"]
        )
        complete = not counts["missing_runs"] and not counts["skipped_runs"] and not counts["runs_with_issues"]
        floor_ok = with_score is not None and with_score + _EPSILON >= policy["quality_floor"]
        regression_ok = delta is not None and delta + _EPSILON >= -policy["max_case_regression"]
        if objective == "efficiency":
            objective_ok = delta is not None and delta >= -_EPSILON
        else:
            objective_ok = delta is not None and delta > _EPSILON and delta + _EPSILON >= policy["min_quality_delta"]
        cost_ok = cost_delta is not None and (not cost_required or cost_delta < -_EPSILON)
        supported = can_support and complete and floor_ok and regression_ok and not critical_failed and objective_ok and cost_ok
        baseline_ok = (
            can_describe and complete and case["without_score"] is not None
            and case["without_score"] + _EPSILON >= policy["quality_floor"]
            and delta is not None and delta <= _EPSILON
            and not supported and not baseline_critical_failed
            # Under an efficiency goal, a cheaper plugin remains a useful signal;
            # do not turn failure of some other gate into a baseline recommendation.
            and (objective != "efficiency" or (cost_delta is not None and cost_delta >= -_EPSILON))
        )

        if supported:
            reason = (
                "本案例保持了基线质量、达到质量下限，并降低了完整记录的平均成本；可在相同条件下优先试用。"
                if objective == "efficiency" else
                "本案例达到预设质量增益和质量下限，未触发关键判据或回退限制，并满足本案例的成本条件；可在相同条件下优先试用。"
            )
            use_when.append(_scenario(case, prompts[case["id"]], reason, cost_delta))
        elif baseline_ok:
            reason = "基线在本案例已达到质量下限，未观察到插件带来更高结果质量；按本次目标可先使用基线。"
            if cost_delta is not None and cost_delta < -_EPSILON:
                reason += "插件成本较低，若实际目标是节省投入，应另按效率目标评估。"
            reason += "这不是永久停用或卸载建议。"
            prefer_baseline.append(_scenario(case, prompts[case["id"]], reason, cost_delta))

        reasons = []
        if synthetic:
            reasons.append("包含合成演示，不能转化为实际使用建议")
        elif not eligible:
            reasons.append("整项比较存在证据阻断，先补足并复核全套材料")
        elif not non_regressed:
            reasons.append("整项比较触发关键判据或回退限制，不能只挑选获益案例推荐")
        elif not supported and not baseline_ok:
            if not floor_ok:
                reasons.append("本案例的插件质量未达到下限或尚未知")
            if not objective_ok:
                reasons.append("本案例未达到所选目标的增益条件")
            if not cost_ok:
                reasons.append("本案例未满足成本条件或成本尚未知")
            if not regression_ok or critical_failed:
                reasons.append("本案例存在回退或关键判据问题")
            if not can_support:
                reasons.append("整项比较尚未显示预设增益，局部差异只能作为下一次试用线索")
        if baseline_critical_failed and not supported:
            reasons.append("基线未通过关键判据或关键结果尚未知，不能仅凭平均分达到下限就建议优先使用基线")
        if counts["failed_runs"] or counts["missing_runs"] or counts["skipped_runs"] or counts["runs_with_issues"]:
            reasons.append(
                f"保留 {counts['failed_runs']} 次失败、{counts['missing_runs']} 次缺失、"
                f"{counts['skipped_runs']} 次跳过和 {counts['runs_with_issues']} 次有问题的运行，不能删去后重算收益"
            )
        if reasons:
            investigate.append(_scenario(case, prompts[case["id"]], "；".join(reasons) + "。", cost_delta))

    if synthetic:
        status = "TRIAL_GUIDANCE_ONLY"
        next_steps = ["先冻结真实任务、两组相同的授权输入及比较条件，再收集真实运行和完整成本。", "合成案例只用于演练记录和判读流程。"]
    elif not can_describe:
        status = "REVIEW_REQUIRED"
        next_steps = ["逐项复核阻断、失败、缺失和关键回退；保留原记录，以明确修订后的新实验重新比较。", "问题解决前，不依据单个高分案例作使用推广。"]
    else:
        status = "BOUNDED_LOCAL_GUIDANCE"
        next_steps = ["将当前任务与原案例、插件版本和执行条件逐项比较；仅在相符时参考本卡。", "对范围外任务先作小规模配对试用，保留失败、成本和人工纠正记录。"]
    next_steps.append("安装、连接、权限或卸载需求交由宿主及 Plugin Management 处理；本卡不授予任何变更权限。")

    all_runs = [run for case in report["cases"] for run in case["runs"]]
    card = {
        "schema_version": 1, "type": "plugin_usage_card",
        "plugin": copy.deepcopy(report["plugin"]), "study_id": report["study_id"],
        "verdict": report["verdict"], "status": status,
        "scope": {
            "plugin": copy.deepcopy(report["plugin"]),
            "suite_sha256": report["provenance"]["suite_sha256"],
            "records_sha256": report["provenance"]["records_sha256"],
            "cost_ledger_sha256": report["provenance"].get("cost_ledger_sha256"),
            "conditions_sha256": suite_digest(suite["conditions"]),
            "conditions": copy.deepcopy(suite["conditions"]),
            "case_ids": [case["id"] for case in suite["cases"]],
            "objective": objective, "policy": copy.deepcopy(policy),
            "decision_scope": "仅限本次提交的具体任务及固定条件；不会自动外推到同类或新任务。",
        },
        "use_when": use_when, "prefer_baseline_when": prefer_baseline,
        "improvement_plan": _improvement_plan(suite, report),
        "investigate": investigate, "next_steps": next_steps,
        "refresh_when": [
            "插件版本、配置、权限或依赖变化时重新核验。",
            "模型、宿主、工具、运行环境或资源预算变化时重新核验。",
            "任务、输入数据、数据访问范围、评分标准或质量与效率目标变化时重新比较。",
            "出现新的失败、回退、人工纠正或成本证据时复核；此清单不创建定时监控。",
        ],
        "source": {
            "evidence_type": report["evidence_type"],
            "evidence_level": "SIMULATION_ONLY" if synthetic else "SUBMITTED_PAIRED_OBSERVATIONS",
            "evaluation_recomputed": True, "comparison_eligible": eligible,
            "measured_verdict": report["measured_verdict"],
            "provenance": copy.deepcopy(report["provenance"]),
            "summary": copy.deepcopy(summary), "run_counts": _counts(all_runs),
            "blockers": list(report["blockers"]), "warnings": list(report["warnings"]),
            "claim_limits": copy.deepcopy(report["claim_limits"]),
            "authenticity_verified": False,
        },
        "limitations": [
            "使用卡是观察范围内的临时参考，不是插件的通用质量认证或长期有效承诺。",
            "来源、外部参与者、任务独立性与人工计时均为提交者声明；程序重算和哈希不证明数据真实性、实际执行或独立验证。",
            "本地增益信号不建立因果收益、外部适用性或科学与临床有效性；科研结论仍需领域证据和研究者判断。",
            "成本来自提交记录及人工费率折算；均值按每个案例每组的计划运行计算，估算费用不等于已结算支出。",
            "基线足够的观察不构成自动停用、卸载、扩权或修改其他插件的授权。",
            "原始任务文字保留在本地卡片中；向他人分享前应由用户检查其中的私有资料。",
        ],
    }
    card["envelope"] = _usage_envelope(suite, records, report, card, artifact_root, verifier_root, corpus_root)
    return card


def _usage_envelope(suite, records, report, card, artifact_root, verifier_root, corpus_root):
    """A conservative presentation policy, not a new outcome or efficacy test."""
    from .value_metrics import _rates
    from .scenarios import decision_metrics as scientific_rates
    families = suite.get("task_families", [])
    if (not isinstance(families, list) or any(not isinstance(f, str) or not f.strip() for f in families)
            or len(set(families)) != len(families)):
        raise ValidationError("task_families must be a unique list of nonempty family names")
    digest = suite["plugin"].get("sha256")
    if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
        raise ValidationError("plugin.sha256 must be a lowercase SHA-256 digest")
    conditions = suite["conditions"]
    binding = {"plugin_sha256": digest, "plugin": copy.deepcopy(suite["plugin"]),
               **{k: conditions.get(k) for k in ("host", "host_version", "model", "model_version")},
               "conditions_sha256": suite_digest(conditions),
               "suite_sha256": card["scope"]["suite_sha256"],
               "records_sha256": card["scope"]["records_sha256"],
               "cost_ledger_sha256": card["scope"]["cost_ledger_sha256"]}
    missing = [k for k in ("plugin_sha256", "host_version", "model_version")
               if not isinstance(binding[k], str) or not binding[k].strip()
               or any(word in binding[k].lower() for word in ("unknown", "unverified", "alias", "未知", "未核验"))]
    supported = {r["case_id"] for r in card["use_when"]}
    baseline = {r["case_id"] for r in card["prefer_baseline_when"]}
    corpus, truth = report.get("corpus_errors"), None
    if corpus is not None:
        from .corpus import load_material
        try:
            _, truth = load_material(corpus_root)
        except (OSError, ValidationError):
            corpus = None  # A changed/unavailable key never upgrades a blocked card.
    groups = {f: [] for f in families}
    for case in report["cases"]:
        groups.setdefault(case["cluster"], []).append(case)
    rows = []
    for family, cases in groups.items():
        ids = {c["id"] for c in cases}
        rates = _rates(cases, suite["runs_per_case"], report["policy"]["quality_floor"])
        raw_cases = [c for c in suite["cases"] if c["id"] in ids]
        # Reuse the existing decision-error denominators, including missing runs.
        scientific = scientific_rates({**suite, "cases": raw_cases}, records, verifier_root, artifact_root)
        refusals = {}
        for arm in ("with", "without"):
            rr = [r for r in scientific["metrics"] if r["metric"] == "over_refusal" and r["arm"] == arm]
            # Sealed corpus rules need their private truth to identify allowed tasks.
            if corpus is not None and any(g["type"] == "sealed" for c in raw_cases for g in c["graders"]):
                cr = [r for r in corpus["runs"] if r["case_id"] in ids and r["arm"] == arm
                      and truth["answers"][r["case_id"]]["decision"] == "allow"]
                rr += [{"planned": len(cr), "errors": sum(r["decision"] == "withhold" for r in cr),
                        "unknown": sum(r["decision"] is None for r in cr)}]
            counts = {k: sum(r[k] for r in rr) for k in ("planned", "errors", "unknown")}
            counts["rate"] = counts["errors"] / counts["planned"] if counts["planned"] and not counts["unknown"] else None
            refusals[arm] = counts
        arms = {}
        for arm in ("with", "without"):
            runs = [r for c in cases for r in c["runs"] if r["arm"] == arm]
            failed = sum(r["status"] in _FAILURES for r in runs)
            unknown = sum(r["status"] not in _FAILURES | {"completed"} for r in runs)
            costs = [r["cost_usd"] for r in runs]
            complete_cost = (bool(costs) and None not in costs and report["cost_analysis"]["complete_category_coverage"])
            success = rates["arms"][arm]
            arms[arm] = {"observed": sum(r["status"] != "missing" for r in runs), "planned": len(runs),
                "failed": failed, "unknown": unknown,
                "failure_rate": failed / len(runs) if runs and not unknown else None,
                "failure_lower": failed / len(runs) if runs else None,
                "failure_upper": (failed + unknown) / len(runs) if runs else None,
                "successes": success["successes"], "success_unknown": success["unknown"],
                "cost_per_success_usd": sum(costs) / success["successes"]
                    if complete_cost and not success["unknown"] and success["successes"] else None}
        deltas = [c["delta"] for c in cases]
        delta = mean(deltas) if deltas and None not in deltas else None
        critical = sum(g["critical"] and g["passed"] is False for c in cases for r in c["runs"]
                       if r["arm"] == "with" for g in r["grades"])
        negatives = []
        if rates["harmed"]:
            negatives.append(f"{rates['harmed']} 个 harmed pairs")
        if delta is not None and delta < -_EPSILON:
            negatives.append("平均质量下降")
        if critical:
            negatives.append(f"{critical} 个关键判据失败")
        if arms["with"]["failed"]:
            negatives.append(f"启用组 {arms['with']['failed']} 次执行失败（未归因）")
        if refusals["with"]["errors"]:
            negatives.append(f"启用组 {refusals['with']['errors']} 次误拒答")
        observed = sum(a["observed"] for a in arms.values())
        if not observed:
            color, decision = "gray", "未测：无运行观察"
        elif negatives:
            color, decision = "red", "暂不推广：先处理负向证据"
        elif ids and ids <= baseline and not missing:
            color, decision = "red", "基线优先：本目标下未见额外收益"
        elif (ids and ids <= supported and not missing and not rates["unknown_pairs"]
              and all(r["rate"] is not None for r in refusals.values())
              and report["cost_analysis"]["complete_category_coverage"]
              and arms["with"]["cost_per_success_usd"] is not None):
            color, decision = "green", "可限域试用：仅限已测案例与绑定条件"
        else:
            color, decision = "yellow", "仅供调查／试用：证据不足或收益未明确"
        rows.append({"family": family, "color": color, "decision": decision, "case_ids": sorted(ids),
            "quality_delta": delta, "harmed_pairs": rates["harmed"],
            "unknown_pairs": rates["unknown_pairs"], "planned_pairs": rates["planned_pairs"],
            "resolved_pairs": rates["planned_pairs"] - rates["unknown_pairs"],
            "over_refusal": refusals, "arms": arms, "negative_evidence": negatives})
    rows.sort(key=lambda r: ({"red": 0, "yellow": 1, "gray": 2, "green": 3}[r["color"]], r["family"]))
    return {"schema_version": 1, "policy": "CONSERVATIVE_DISPLAY_V1", "binding": binding,
        "binding_status": "INCOMPLETE" if missing else "DECLARED_BOUND_NOT_AUTHENTICATED",
        "missing_identity": missing, "rows": rows,
        "negative_evidence": [f"{r['family']}：{n}" for r in rows for n in r["negative_evidence"]],
        "blockers": report["blockers"], "evidence_type": report["evidence_type"],
        "cost_basis": report["cost_analysis"]["saving_claim_basis"],
        "invalidation": ["plugin_sha256 改变，即使版本号未变。", "host/model 名称或版本、工具、环境、配置或预算改变。",
            "任务族之外的新任务、输入分布、参考答案、质量目标或评分规则改变。",
            "新增失败、harmed pairs、误拒答、成本或人工复核证据；必须生成新修订，旧卡保留。"],
        "limits": "颜色是保守展示规则，不是新统计检验。harmed pairs 为基线成功而启用失败的已观察配对，不证明因果伤害。"
                  "重复不是独立任务族；未测误拒答与未知成本不填零；合成数据不能获绿灯。哈希不认证执行或来源。"}


def check_usage_envelope(card, plugin_sha256, conditions):
    """Compare supplied current identity locally; never claim live monitoring."""
    binding = card["envelope"]["binding"]
    changes = []
    if plugin_sha256 != binding["plugin_sha256"]:
        changes.append("plugin_sha256")
    if suite_digest(conditions) != binding["conditions_sha256"]:
        changes.append("conditions")
    return {"status": "STALE" if changes else "UNKNOWN" if card["envelope"]["missing_identity"] else "MATCHED_DECLARATIONS",
            "changed": changes, "live_verified": False}


def _markdown(value):
    """Render user-supplied text literally, without links, images or raw HTML."""
    if value is None:
        return "未知"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = html.escape(str(value), quote=True)
    for character in ("\\", "`", "*", "_", "[", "]", "(", ")", "!", "|", "#", "~", "+", "-"):
        text = text.replace(character, "\\" + character)
    return " ".join(text.splitlines())


def _envelope_cells(row):
    def number(value):
        return "未知" if value is None else f"{value:.3f}"
    def refusal(r):
        if not r["planned"]:
            return "未测"
        return f"{r['errors']}/{r['planned']}" + (f"；{r['unknown']} 未知" if r["unknown"] else "")
    def failures(a):
        if not a["planned"]:
            return "未测"
        rate = f"{a['failure_rate']:.0%}" if a["failure_rate"] is not None else f"{a['failure_lower']:.0%}–{a['failure_upper']:.0%}"
        return f"{a['failed']}/{a['planned']} ({rate})"
    w, b = row["arms"]["with"], row["arms"]["without"]
    def cost(a):
        return "无成功，未定义" if a["planned"] and not a["successes"] and not a["success_unknown"] else number(a["cost_per_success_usd"])
    return [row["family"], {"red": "红", "yellow": "黄", "green": "绿", "gray": "灰"}[row["color"]] + " · " + row["decision"],
            number(row["quality_delta"]), f"{row['harmed_pairs']}/{row['planned_pairs']}；{row['unknown_pairs']} 未知",
            refusal(row["over_refusal"]["with"]) + " / " + refusal(row["over_refusal"]["without"]),
            cost(w) + " / " + cost(b),
            failures(w) + " / " + failures(b),
            f"{len(row['case_ids'])} 案例；{w['observed']} / {b['observed']} 次；{row['resolved_pairs']}/{row['planned_pairs']} 配对可判"]


_ENVELOPE_HEADERS = ["任务族", "决策", "质量 Δ", "harmed pairs", "over-refusal W / B", "每成功 USD W / B", "执行失败率 W / B", "样本量"]


def _envelope_markdown(card):
    env = card["envelope"]
    binding = env["binding"]
    lines = ["## 单页使用包络", "", "**负向证据优先**：" + _markdown("；".join(env["negative_evidence"]) or "未观察到负向项；不等于已证实无风险。"), "",
             f"证据：{_markdown(env['evidence_type'])}；研究阻断 {len(env['blockers'])} 项；身份缺口：{_markdown(env['missing_identity'])}。", "",
             "绿：限域试用；黄：调查／证据不足；红：暂不推广或基线优先；灰：未测。", "",
             "| " + " | ".join(_ENVELOPE_HEADERS) + " |", "| " + " | ".join(["---"] * len(_ENVELOPE_HEADERS)) + " |"]
    for row in env["rows"]:
        lines.append("| " + " | ".join(_markdown(c) for c in _envelope_cells(row)) + " |")
    lines += ["", "W / B = 启用 / 基线；质量 Δ = 启用 − 基线；harmed 为已判定计数，未知配对不作零伤害。失败率范围保留缺失／跳过；每成功成本包含失败与分摊开销。", "",
              f"绑定 plugin_sha256：{_markdown(binding['plugin_sha256'])}；宿主 {_markdown(binding['host'])} / {_markdown(binding['host_version'])}；模型 {_markdown(binding['model'])} / {_markdown(binding['model_version'])}。", "",
              "**失效条件**：" + " ".join(_markdown(s) for s in env["invalidation"]), "",
              _markdown(env["limits"]), ""]
    return lines


def render_usage_envelope(card):
    """Offline, script-free, printable single-page view; untrusted text is escaped."""
    env, plugin = card["envelope"], card["plugin"]
    esc = lambda value: html.escape("未知" if value is None else str(value), quote=True)
    binding = env["binding"]
    negative = "；".join(env["negative_evidence"]) or "尚未观察到负向项；不等于已证实无风险。"
    if env["evidence_type"] == "synthetic":
        negative = "合成演示：以下数值不是实际插件收益。 " + negative
    rows = "".join('<tr class="' + row["color"] + '">' + "".join("<td>" + esc(c) + "</td>" for c in _envelope_cells(row)) + "</tr>" for row in env["rows"])
    identity = " · ".join(f"{key}: {esc(binding[key])}" for key in ("plugin_sha256", "host", "host_version", "model", "model_version"))
    provenance = " · ".join(f"{key}: {esc(binding[key])}" for key in ("suite_sha256", "records_sha256", "conditions_sha256", "cost_ledger_sha256"))
    return f'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{esc(plugin['name'])} · 使用包络卡</title>
<style>
:root{{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#172432;background:#edf1f4}}
body{{margin:0;padding:24px}}main{{max-width:1440px;margin:auto;background:white;padding:26px;border:1px solid #ccd5df;border-radius:14px}}
h1{{font-size:26px;margin:0 0 8px}}p{{line-height:1.5;margin:9px 0}}.sub,footer{{color:#475569;font-size:12px}}.negative{{border-left:5px solid #ad2431;background:#fff0f0;padding:12px;font-size:14px}}
.identity{{font:12px ui-monospace,monospace;overflow-wrap:anywhere}}table{{width:100%;border-collapse:collapse;font-size:12px;margin:16px 0}}th,td{{border-bottom:1px solid #ccd5df;padding:11px 8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{background:#172432;color:white}}
tr.red{{background:#fff1f2}}tr.yellow{{background:#fffae4}}tr.green{{background:#edf8f0}}tr.gray{{background:#f1f3f5;color:#56616e}}tr.red td:first-child{{border-left:5px solid #b32131}}tr.yellow td:first-child{{border-left:5px solid #956000}}tr.green td:first-child{{border-left:5px solid #16743d}}tr.gray td:first-child{{border-left:5px solid #79818c}}.scroll{{overflow:auto}}
@media print{{@page{{size:A4 landscape;margin:10mm}}body{{padding:0;background:white}}main{{padding:0;border:0}}th,td{{padding:7px 5px}}*{{print-color-adjust:exact}}tr{{break-inside:avoid}}}}
</style><main>
<h1>何时值得用 · 使用包络卡</h1><p>{esc(plugin['name'])} · {esc(plugin['version'])} · {esc(card['study_id'])}</p>
<div class="negative"><strong>先看负向证据</strong><br>{esc(negative)}</div>
<p class="sub">证据类型：{esc(env['evidence_type'])} · 研究阻断：{len(env['blockers'])} · 身份缺口：{esc(', '.join(env['missing_identity']) or '无；仅核对声明，未认证来源')} · 所有未列任务均未测。</p>
<p class="identity">{identity}</p>
<p class="sub">🟢 限域试用　🟡 调查／证据不足　🔴 暂不推广／基线优先　⚪ 未测；文字与颜色同时编码。</p>
<div class="scroll"><table><thead><tr>{''.join('<th scope="col">' + esc(h) + '</th>' for h in _ENVELOPE_HEADERS)}</tr></thead><tbody>{rows}</tbody></table></div>
<p class="sub">W / B = 启用 / 基线；质量 Δ = 启用 − 基线（0–1）。harmed pairs = 基线成功、启用失败，未知配对单列。样本量为案例、观察运行与可判配对；重复不是独立任务族。执行失败率按计划次数，缺失／跳过给范围。每成功成本包含失败与分摊开销；未知不填零。成本依据：{esc(env['cost_basis'])}，不据此宣称已结算。</p>
<p><strong>失效条件</strong>　{esc(' '.join(env['invalidation']))}</p>
<footer>{esc(env['limits'])}<p>本卡离线静态生成；不监控环境，不执行安装、卸载或扩权。完整阻断与逐项来源见同目录 USAGE.md / card.json。</p><p class="identity">{provenance}</p></footer>
</main></html>'''


def _render_markdown(card):
    plugin, scope, source = card["plugin"], card["scope"], card["source"]
    lines = ["# 插件使用卡", "", f"**{_markdown(plugin['name'])} · {_markdown(plugin['version'])}**", "",
             f"研究：{_markdown(card['study_id'])}", "",
             f"状态：{_markdown(_STATUSES[card['status']])}", "",
             f"重新计算的结论：{_markdown(card['verdict'])}", "",
             "仅对记录中的具体任务提供条件性参考。评分不会产生安装、权限或卸载操作。", "",
             *(_envelope_markdown(card) if "envelope" in card else []),
             "## 适用范围", "",
             f"- 决策范围：{_markdown(scope['decision_scope'])}",
             f"- 目标：{_markdown(scope['objective'])}",
             f"- 固定条件：{_markdown(scope['conditions'])}",
             f"- 方案 SHA-256：{_markdown(scope['suite_sha256'])}",
             f"- 运行记录 SHA-256：{_markdown(scope['records_sha256'])}",
             f"- 条件 SHA-256：{_markdown(scope['conditions_sha256'])}", ""]
    for title, key, empty in [
        ("何时可优先试用", "use_when", "当前证据不能给出优先使用建议。"),
        ("何时基线可能已足够", "prefer_baseline_when", "尚无可支持的基线优先观察。"),
        ("先调查什么", "investigate", "未产生额外案例调查项；仍须遵守来源限制和适用范围。"),
    ]:
        lines += [f"## {title}", ""]
        for item in card[key]:
            lines += [f"### {_markdown(item['case_id'])}", "",
                      f"任务：{_markdown(item['prompt'])}", "",
                      _markdown(item["reason"]), "",
                      f"质量差（启用 − 未启用）：{_markdown(item['quality_delta'])}；平均成本差（USD）：{_markdown(item['cost_delta_usd'])}。", "",
                      f"运行计数：{_markdown(item['run_counts'])}", ""]
        if not card[key]:
            lines += [empty, ""]
    if plan := card.get("improvement_plan"):
        lines += ["## 作者改进清单", "", "可直接本地使用，无需登记或公开评分。以下是诊断线索，不是已证实的因果缺陷。", "",
                  f"状态：{_markdown(plan['status'])}", ""]
        for item in plan["queue"]:
            lines += [f"- {_markdown(item['case_id'])} / {_markdown(item['arm'])} / 第 {item['repetition']} 次 / {_markdown(item.get('criterion_id', item['kind']))}：{_markdown(item['evidence'])} {_markdown(item['action'])}"]
            if "testable_hypothesis" in item:
                hypothesis = item["testable_hypothesis"]
                lines += [f"  预期观察：{_markdown(hypothesis['prediction'])} 反证条件：{_markdown(hypothesis['falsifier'])}"]
        if not plan["queue"]:
            lines += ["未定位到逐项失败；这不代表已有增益。仍需检查整项研究阻断和成本。"]
        trial = plan["next_experiment"]
        lines += ["", "### 修复后的复测", "", _markdown(trial["action"]), "", _markdown(trial["preserve"]), "",
                  f"完整复测：{trial['planned_runs']} 次计划运行；案例：{_markdown(trial['case_ids'])}。费用与人工耗时尚未知；不会自动执行。", ""]
    for title, items in [("接下来怎么做", card["next_steps"]), ("何时重新核验", card["refresh_when"]),
                         ("证据阻断", source["blockers"]), ("需要关注", source["warnings"]),
                         ("限制", card["limitations"])]:
        lines += [f"## {title}", ""]
        lines += [f"- {_markdown(item)}" for item in items] or ["未记录；不代表证据已获独立认证。"]
        lines += [""]
    lines += ["## 来源与完整性", "",
              f"- 证据类型：{_markdown(source['evidence_type'])}",
              f"- 证据层级：{_markdown(source['evidence_level'])}",
              f"- 运行计数：{_markdown(source['run_counts'])}",
              f"- 来源记录：{_markdown(source['provenance'])}", "",
              "来源真实性未获独立验证。完整字段保存在同目录的 `card.json`。", ""]
    return "\n".join(lines)


def write_usage_card(card, output_dir):
    """Write only explicit local card artifacts, refusing any existing contents."""
    if not isinstance(card, dict) or card.get("schema_version") != 1 or card.get("type") != "plugin_usage_card":
        raise ValidationError("Expected a plugin usage card built from suite and execution records")
    # Render everything before touching the filesystem, including strict JSON.
    json_text = json.dumps(card, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    markdown_text = _render_markdown(card)
    html_text = render_usage_envelope(card) if "envelope" in card else None
    output = Path(output_dir)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValidationError("Usage card output directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    paths = {"json": output / "card.json", "md": output / "USAGE.md"}
    contents = [("json", json_text), ("md", markdown_text)]
    if html_text is not None:
        paths["html"] = output / "ENVELOPE.html"
        contents.append(("html", html_text))
    for key, content in contents:
        try:
            with paths[key].open("x", encoding="utf-8") as stream:
                stream.write(content)
        except FileExistsError as exc:
            raise ValidationError("Usage card artifacts already exist; create a new revision") from exc
    return {key: str(path) for key, path in paths.items()}
