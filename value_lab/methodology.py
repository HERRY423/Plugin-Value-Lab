"""Frozen two-direction decision-error limits, separate from task quality."""

METRICS = {"unsupported_acceptance", "over_refusal"}


def validate_limits(policy):
    from .core import ValidationError, _number
    if "decision_error_limits" not in policy:
        return
    limits = policy["decision_error_limits"]
    if not isinstance(limits, dict) or set(limits) != METRICS:
        raise ValidationError("decision_error_limits must specify unsupported_acceptance and over_refusal")
    for name, threshold in limits.items():
        _number(threshold, name, 0, 1)


def assess_limits(policy, sources):
    limits = policy.get("decision_error_limits")
    result = {"status": "NOT_CONFIGURED", "limits": limits, "blockers": [], "violations": [],
              "scope": "Frozen per-split WITH-arm error ceilings; both arms require complete observations. No significance claim."}
    if limits is None:
        return result
    rows = [dict(row, source=name) for name, source in sources.items() if source for row in source["metrics"]]
    for metric in sorted(METRICS):
        for arm in ("with", "without"):
            matching = [row for row in rows if row["metric"] == metric and row["arm"] == arm and row["planned"] > 0]
            if not matching:
                result["blockers"].append(f"Decision limit requires planned {metric} observations for {arm}")
            for row in matching:
                label = f"{row['source']}/{row['split']}/{arm}/{metric}"
                if row["unknown"] or row["rate"] is None:
                    result["blockers"].append("Decision error rate unresolved: " + label)
                elif arm == "with" and row["rate"] > limits[metric] + 1e-12:
                    result["violations"].append({"metric": metric, "split": row["split"], "source": row["source"],
                                                "observed_rate": row["rate"], "maximum": limits[metric]})
    result["status"] = "UNRESOLVED" if result["blockers"] else "VIOLATED" if result["violations"] else "WITHIN_FROZEN_LIMITS"
    return result
