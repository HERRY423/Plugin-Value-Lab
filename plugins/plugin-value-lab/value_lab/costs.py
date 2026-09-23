"""Cost allocation and sensitivity with unknowns, estimates and overhead retained."""
from collections import Counter
import math
from statistics import median

CATEGORIES = ("model", "tool", "human", "judge", "setup", "retry", "other")
SUPPLEMENTAL = ("judge", "setup", "retry", "other")


def cash_evidence(index, plan):
    """Check settlement declarations and line references, not invoice authenticity."""
    gaps, refs = [], set()
    for key in plan["extras"]:
        cost = index.get(key, {}).get("cost", {})
        if not isinstance(cost, dict):
            cost = {}
        ref = cost.get("evidence_ref")
        if cost.get("basis") != "settled" or not isinstance(ref, str) or not ref.strip():
            gaps.append(f"{key}: model/tool settlement basis and evidence_ref required")
        elif ref in refs:
            gaps.append(f"{key}: reused settlement line reference")
        else:
            refs.add(ref)
    for category, state in plan["coverage"].items():
        if state not in ("not_applicable", "itemized"):
            gaps.append(f"{category}: explicit itemization or not_applicable declaration required")
    for entry in plan["entries"]:
        if plan["coverage"].get(entry["category"]) == "not_applicable":
            gaps.append(f"{entry['id']}: itemized expense contradicts not_applicable")
        if entry["category"] != "human" and entry["treatment"] == "additional":
            if entry["basis"] != "settled" or entry["amount_usd"] is None:
                gaps.append(f"{entry['id']}: supplemental cash settlement required")
            if entry["evidence_ref"] in refs:
                gaps.append(f"{entry['id']}: reused base settlement line reference")
            refs.add(entry["evidence_ref"])
        elif entry["category"] != "human":
            gaps.append(f"{entry['id']}: included breakdown is not independently reconciled")
    return {"settlement_references_complete": not gaps, "gaps": gaps,
            "status": "SETTLEMENT_REFERENCES_PRESENT" if not gaps else "ESTIMATED_DECLARED_OR_MISSING",
            "limitations": "Settlement and not-applicable states are submitted declarations, not authenticated invoices. "
            "Human labor remains timer-valued at the frozen hourly rate, never settled cash."}


def allocation(suite, ledger=None):
    from .core import ValidationError, _number, _stamp
    keys = [(c["id"], r, a) for c in suite["cases"] for r in range(1, suite["runs_per_case"] + 1) for a in ("with", "without")]
    extras = {k: 0.0 for k in keys}
    issues, normalized = [], []
    if ledger is None:
        return {"extras": extras, "issues": issues, "entries": normalized, "coverage_complete": False,
                "coverage": {k: "unknown" for k in SUPPLEMENTAL}, "provided": False}
    if not isinstance(ledger, dict) or type(ledger.get("schema_version")) is not int or ledger["schema_version"] != 1:
        raise ValidationError("成本账本 schema_version 必须为 1")
    if set(ledger) - {"schema_version", "entries", "coverage"}:
        raise ValidationError("成本账本含不支持的字段")
    entries, coverage = ledger.get("entries"), ledger.get("coverage", {})
    if not isinstance(entries, list) or not isinstance(coverage, dict) or set(coverage) - set(SUPPLEMENTAL):
        raise ValidationError("成本条目或覆盖声明格式错误")
    for category in SUPPLEMENTAL:
        state = coverage.get(category, "unknown")
        if state not in ("unknown", "included", "not_applicable", "itemized"):
            raise ValidationError("不支持的成本覆盖状态")
        if state == "unknown":
            issues.append(f"成本类别 {category} 尚未确认是否覆盖")
    ids, refs = set(), set()
    human_intervals = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"id", "category", "arm", "amount_usd", "basis", "evidence_ref", "treatment", "case_id", "repetition", "with_fraction", "human_intervals"}:
            raise ValidationError("成本条目格式错误或含不支持字段")
        for name in ("id", "evidence_ref"):
            if not isinstance(entry.get(name), str) or not entry[name].strip():
                raise ValidationError("每项成本需要标识与来源，不能用空白代替凭据")
        if entry["id"] in ids or entry["evidence_ref"] in refs:
            raise ValidationError("成本标识或凭据行引用重复，可能重复计费；同一账单请使用不同明细行引用")
        ids.add(entry["id"])
        refs.add(entry["evidence_ref"])
        category = entry.get("category")
        if category not in CATEGORIES or entry.get("arm") not in ("with", "without", "shared"):
            raise ValidationError("成本类别或分配组错误")
        if entry.get("basis") not in ("estimate", "settled", "declared") or entry.get("treatment") not in ("additional", "included"):
            raise ValidationError("必须区分估计/结算/声明及新增/已包含成本")
        amount = entry.get("amount_usd")
        if amount is not None:
            _number(amount, "amount_usd")
        if category == "human":
            intervals = entry.get("human_intervals")
            if not isinstance(intervals, list) or not intervals:
                raise ValidationError("补充人工成本必须包含原始计时间隔")
            minutes = 0
            for timer in intervals:
                if not isinstance(timer, dict) or not isinstance(timer.get("actor"), str) or not timer["actor"].strip():
                    raise ValidationError("人工计时缺少操作者")
                start, end = _stamp(timer.get("start")), _stamp(timer.get("end"))
                if end < start:
                    raise ValidationError("人工计时结束早于开始")
                minutes += (end - start).total_seconds() / 60
                human_intervals.append((timer["actor"], start, end))
            expected_amount = minutes * suite["policy"]["human_hourly_usd"] / 60
            if amount is not None and not math.isclose(amount, expected_amount, abs_tol=1e-6):
                raise ValidationError("人工金额与原始计时及冻结时薪不符")
        if category in SUPPLEMENTAL and coverage.get(category) == "not_applicable":
            raise ValidationError(f"{category} 标为不适用却含成本条目")
        if category in SUPPLEMENTAL and coverage.get(category) == "included" and entry["treatment"] == "additional":
            raise ValidationError(f"{category} 声明已含在原记录却又新增计费")
        target = keys
        if "case_id" in entry:
            if not isinstance(entry["case_id"], str) or entry["case_id"] not in {c["id"] for c in suite["cases"]}:
                raise ValidationError("成本引用了计划外任务")
            target = [k for k in target if k[0] == entry["case_id"]]
        if "repetition" in entry:
            if "case_id" not in entry or type(entry["repetition"]) is not int or not 1 <= entry["repetition"] <= suite["runs_per_case"]:
                raise ValidationError("成本重复次序超出计划或缺少任务")
            target = [k for k in target if k[1] == entry["repetition"]]
        shares = {"with": 0, "without": 0}
        if entry["arm"] == "shared":
            fraction = _number(entry.get("with_fraction"), "共同成本中有插件组比例", 0, 1)
            shares = {"with": fraction, "without": 1 - fraction}
        else:
            if "with_fraction" in entry:
                raise ValidationError("单组成本不能同时指定共同分摊比例")
            shares[entry["arm"]] = 1
        if entry["treatment"] == "additional":
            for arm, share in shares.items():
                arm_keys = [k for k in target if k[2] == arm]
                if not share:
                    continue
                for k in arm_keys:
                    if amount is None:
                        extras[k] = None
                    elif extras[k] is not None:
                        extras[k] += amount * share / len(arm_keys)
        normalized.append({**entry, "shares": shares})
        if amount is None:
            issues.append(f"成本 {entry['id']} 金额未知，不是零")
    human_intervals.sort(key=lambda x: (x[0], x[1], x[2]))
    latest = {}
    for actor, start, end in human_intervals:
        if actor in latest and start < latest[actor]:
            raise ValidationError("补充人工计时间隔重叠，可能重复核算")
        latest[actor] = max(end, latest.get(actor, end))
    for category in SUPPLEMENTAL:
        if coverage.get(category) == "itemized" and not any(e["category"] == category for e in entries):
            issues.append(f"成本类别 {category} 声明已列明却没有条目")
    if any(x is not None and not math.isfinite(x) for x in extras.values()):
        raise ValidationError("成本分摊金额溢出")
    return {"extras": extras, "issues": issues, "entries": normalized, "coverage_complete": not issues,
            "coverage": {k: coverage.get(k, "unknown") for k in SUPPLEMENTAL}, "provided": True}


def analyze_costs(suite, records, ledger=None, report=None, native_estimate=None):
    from .core import _number, ValidationError, _stamp
    plan = allocation(suite, ledger)
    index, duplicates = {}, []
    for r in records:
        k = (r.get("case_id"), r.get("repetition"), r.get("arm"))
        if not isinstance(k[0], str) or type(k[1]) is not int or not isinstance(k[2], str):
            duplicates.append("invalid execution key")
            continue
        if k not in plan["extras"]:
            continue
        if k in index:
            duplicates.append(str(k))
        else:
            index[k] = r
    arms = {}
    timers = []
    for record in records:
        for t in record.get("human_intervals", []) or []:
            if isinstance(t, dict):
                try:
                    timers.append((t.get("actor"), _stamp(t.get("start")), _stamp(t.get("end"))))
                except (ValueError, TypeError):
                    pass
    for entry in plan["entries"]:
        if entry["category"] == "human" and entry["treatment"] == "additional":
            for timer in entry["human_intervals"]:
                actor, start, end = timer["actor"], _stamp(timer["start"]), _stamp(timer["end"])
                if any(actor == a and start < e and s < end for a, s, e in timers):
                    plan["issues"].append("补充人工计时与原记录重叠；不可重复核算")
    for arm in ("with", "without"):
        expected = [k for k in plan["extras"] if k[2] == arm]
        subtotal = 0.0
        unknown = []
        components = {c: 0.0 for c in CATEGORIES}
        included = {c: 0.0 for c in CATEGORIES}
        basis_totals = {"estimate": 0.0, "settled": 0.0, "declared": 0.0}
        durations, minutes, successful_costs = [], [], []
        failures = 0
        token_totals = Counter()
        observed_tokens = 0
        for key in expected:
            record = index.get(key)
            if not record:
                unknown.append(f"{key}: 缺少计划执行")
                continue
            cost = record.get("cost", {})
            basis = cost.get("basis", "declared") if isinstance(cost, dict) else "declared"
            if basis not in basis_totals:
                unknown.append(f"{key}: 成本来源类型无效")
                basis = "declared"
            base = []
            for field, category in (("model_usd", "model"), ("tool_usd", "tool"), ("human_minutes", "human")):
                try:
                    value = _number(cost.get(field), field)
                    if category == "human":
                        minutes.append(value)
                        value *= suite["policy"]["human_hourly_usd"] / 60
                    components[category] += value
                    basis_totals["declared" if category == "human" else basis] += value
                    subtotal += value
                    base.append(value)
                except (ValidationError, AttributeError):
                    unknown.append(f"{key}: {field} 未知")
            duration = record.get("duration_seconds")
            if type(duration) in (int, float) and math.isfinite(duration) and duration >= 0:
                durations.append(duration)
            if record.get("status") in ("error", "timeout", "aborted"):
                failures += 1
            tokens = record.get("usage")
            if isinstance(tokens, dict):
                valid = {k: v for k, v in tokens.items() if k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens") and type(v) is int and v >= 0}
                if valid:
                    token_totals.update(valid)
                    observed_tokens += 1
            extra = plan["extras"][key]
            if extra is None:
                unknown.append(f"{key}: 分摊成本未知")
            elif len(base) == 3 and record.get("status") == "completed":
                successful_costs.append(sum(base) + extra)
        for entry in plan["entries"]:
            share = entry["shares"][arm]
            if entry["treatment"] == "included" and share and entry.get("amount_usd") is not None:
                included[entry["category"]] += entry["amount_usd"] * share
            if entry["treatment"] == "additional" and share and entry.get("amount_usd") is not None:
                value = entry["amount_usd"] * share
                subtotal += value
                components[entry["category"]] += value
                basis_totals[entry["basis"]] += value
        rows = [r for case in (report or {}).get("cases", []) for r in case["runs"] if r["arm"] == arm]
        success = sum(r["status"] == "completed" and not r["issues"] and r["score"] is not None and r["score"] + 1e-12 >= suite["policy"]["quality_floor"] and
                      not any(g["critical"] and g["passed"] is not True for g in r["grades"]) for r in rows)
        if not math.isfinite(subtotal):
            raise ValidationError("总成本溢出")
        complete = not unknown and not duplicates and not plan["issues"] and plan["coverage_complete"]
        total = subtotal if complete else None
        duration_sorted = sorted(durations)
        arms[arm] = {"planned_runs": len(expected), "observed_runs": sum(k in index for k in expected),
                     "known_subtotal_usd": subtotal, "total_usd": total,
                     "mean_per_planned_run_usd": total / len(expected) if total is not None else None,
                     "components_known_usd": components, "unknown": unknown, "failed_runs": failures,
                     "included_breakdown_usd": included,
                     "known_amounts_by_basis_usd": basis_totals,
                     "successful_outcomes": success if report else None,
                     "cost_per_success_usd": total / success if total is not None and success and report else None,
                     "declared_human_minutes": sum(minutes), "human_time_complete": len(minutes) == len(expected),
                     "latency": {"observed_runs": len(durations), "median_seconds": median(durations) if durations else None,
                                 "p90_seconds": duration_sorted[max(0, math.ceil(.9 * len(durations)) - 1)] if durations else None},
                     "tokens": {"known_counts": dict(token_totals), "runs_with_usage": observed_tokens,
                                "scope": "Only supplied token counters; missing usage is unknown; no pricing inferred"}}
    totals = [arms[a]["total_usd"] for a in ("with", "without")]
    delta = totals[0] - totals[1] if None not in totals else None
    coverage_complete = plan["coverage_complete"] and not plan["issues"] and all(not a["unknown"] for a in arms.values()) and not duplicates
    evidence_ok = bool(report and report["summary"]["comparison_eligible"] and report["evidence_type"] != "synthetic")
    sensitivity = []
    for rate in sorted({0, suite["policy"]["human_hourly_usd"], suite["policy"]["human_hourly_usd"] * 2}):
        values = {}
        for arm, info in arms.items():
            extra_minutes = sum(sum((_stamp(t["end"]) - _stamp(t["start"])).total_seconds()/60 for t in e.get("human_intervals", [])) * e["shares"][arm]
                                for e in plan["entries"] if e["category"] == "human" and e["treatment"] == "additional")
            values[arm] = (info["total_usd"] + (sum([info["declared_human_minutes"], extra_minutes])) * (rate-suite["policy"]["human_hourly_usd"])/60) if info["total_usd"] is not None else None
        sensitivity.append({"hourly_usd": rate, **values, "delta_usd": values["with"]-values["without"] if None not in values.values() else None})
    return {"schema_version": 1, "arms": arms, "cost_delta_usd": delta,
            "cash_evidence": cash_evidence(index, plan),
            "saving_fraction": -delta/totals[1] if delta is not None and totals[1] > 0 else None,
            "coverage": plan["coverage"], "complete_category_coverage": coverage_complete,
            "basis": "Declared base records plus explicitly additional entries; estimates and settlements are not interchangeable",
            "basis_counts": dict(Counter(e["basis"] for e in plan["entries"])),
            "entries": plan["entries"], "issues": plan["issues"] + ["重复执行成本记录: " + k for k in duplicates],
            "native_estimate_usd": native_estimate, "native_estimate_added_to_total": False,
            "budget": {"native_estimate_limit_usd": suite["conditions"]["budget"].get("max_cost_usd"),
                       "native_estimate_over_limit": native_estimate > suite["conditions"]["budget"]["max_cost_usd"]
                           if type(native_estimate) in (int, float) and type(suite["conditions"]["budget"].get("max_cost_usd")) in (int, float) else None,
                       "scope": "Native model/judge estimate only; not a hard settled-spend or all-in human/tool budget"},
            "human_rate_sensitivity": sensitivity, "saving_claim_eligible": coverage_complete and evidence_ok and delta is not None,
            "warnings": ["已知小计不是完整成本；未知项不会填零。", "失败与重试费用保留在分母；每次成功成本包含失败开销。",
                         "原生整批费用可能已含评分调用，只单独展示，不重复加入单次成本。", "已包含条目仅作明细注释，不能再次累加。",
                         "敏感性分析不修改冻结时薪或原结论。成本来源与人工时间仍由提交者声明。"]}
