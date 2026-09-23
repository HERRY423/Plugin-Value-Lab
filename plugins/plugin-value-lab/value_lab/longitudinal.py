"""Explicit matched-study contrasts. Host changes never silently become upgrades."""
from itertools import combinations

from .core import suite_digest
from .registry import _entries, _timestamp, registry_view
from .core import load_json, ValidationError


def _basis(suite):
    # Only the named axes may vary. Preserve every other task/policy/extension.
    return {k: v for k, v in suite.items() if k not in ("id", "plugin", "conditions")}


def _cohort(row, suite, axis):
    varying = {"model", "model_version"} if axis == "model" else set()
    return suite_digest({"protocol": _basis(suite), "engine": row["engine_sha256"],
                         "conditions": {k: v for k, v in suite["conditions"].items() if k not in varying},
                         "plugin": suite["plugin"]["name"] if axis == "plugin" else (suite["plugin"], row["plugin_sha256"])})


def contrast(left, right, suites, *, axis):
    if axis not in ("host", "plugin", "model"):
        raise ValidationError("Contrast axis must be host, plugin or model")
    a, b = suites[left["entry_id"]], suites[right["entry_id"]]
    reasons = []
    if suite_digest(_basis(a)) != suite_digest(_basis(b)):
        reasons.append("Task, input, truth, policy, repeats or evidence type changed")
    if a["plugin"]["name"] != b["plugin"]["name"]:
        reasons.append("Different plugin identity")
    plugin_same = a["plugin"] == b["plugin"] and left["plugin_sha256"] == right["plugin_sha256"]
    if axis != "plugin" and not plugin_same:
        reasons.append("Plugin version/content changed outside the target axis")
    if axis == "plugin" and plugin_same:
        reasons.append("No plugin revision change")
    allowed = {"host", "host_version"} if axis == "host" else {"model", "model_version"} if axis == "model" else set()
    ca = {k: v for k, v in a["conditions"].items() if k not in allowed}
    cb = {k: v for k, v in b["conditions"].items() if k not in allowed}
    if suite_digest(ca) != suite_digest(cb):
        reasons.append("Other execution conditions changed")
    if axis in ("host", "model") and (a["conditions"].get(axis), a["conditions"].get(axis + "_version")) == (b["conditions"].get(axis), b["conditions"].get(axis + "_version")):
        reasons.append("No target-axis change")
    if left["engine_sha256"] != right["engine_sha256"]:
        reasons.append("Scoring engine changed")
    if left["lineage_root"] == right["lineage_root"]:
        reasons.append("Evidence revisions are not new observations")
    for row in (left, right):
        if not row["descriptive_comparison_eligible"]:
            reasons.append("Incomplete, synthetic, superseded, reused-session or disputed evidence")
        if row["quality_delta"] is None:
            reasons.append("Unknown marginal value")
    if axis != "host" and _timestamp(right["observed_at"]) <= _timestamp(left["observed_at"]):
        reasons.append("Longitudinal observations must be strictly ordered in time")
    eligible = not reasons
    def change(field):
        return right[field] - left[field] if eligible and left.get(field) is not None and right.get(field) is not None else None
    gain_change = change("quality_delta")
    return {"before": left["entry_id"], "after": right["entry_id"], "axis": axis,
            "status": "COMPARABLE_DESCRIPTIVE" if eligible else "NOT_COMPARABLE",
            "blockers": sorted(set(reasons)), "plugin_gain_change": gain_change,
            "baseline_quality_change": change("without_score"), "with_quality_change": change("with_score"),
            "alert": "DESCRIPTIVE_GAIN_DROP" if axis != "host" and gain_change is not None and gain_change < 0 else None,
            "claim_limit": "Descriptive difference of WITH-minus-WITHOUT deltas; not causal, statistically significant or publication-ready by itself"}


def analyze_registry(registry, view=None):
    view = view if view is not None else registry_view(registry)
    suites = {p.name: load_json(p / "suite.json") for p, _, _ in _entries(registry)}
    rows = view["entries"]
    hosts, trends = [], []
    # Keep failed candidate comparisons visible; never cherry-pick a better baseline.
    for a, b in combinations(rows, 2):
        if a["plugin"]["name"] == b["plugin"]["name"] and a["host"] != b["host"]:
            hosts.append(contrast(a, b, suites, axis="host"))
    for i, b in enumerate(rows):
        if b["superseded_by"]:
            continue
        for axis in ("plugin", "model"):
            candidates = [a for a in rows[:i] if not a["superseded_by"] and a["plugin"]["name"] == b["plugin"]["name"]
                          and a["host"] == b["host"] and a["lineage_root"] != b["lineage_root"]
                          and ((a["plugin"], a["plugin_sha256"]) != (b["plugin"], b["plugin_sha256"]) if axis == "plugin" else
                               (a["model"], suites[a["entry_id"]]["conditions"].get("model_version")) != (b["model"], suites[b["entry_id"]]["conditions"].get("model_version")))]
            if candidates:
                matching = [a for a in candidates if _cohort(a, suites[a["entry_id"]], axis) == _cohort(b, suites[b["entry_id"]], axis)]
                # Choose the latest within a fixed cohort. Keep a diagnostic
                # comparison when no matching cohort exists; never pool them.
                trends.append(contrast((matching or candidates)[-1], b, suites, axis=axis))
    return {"host_contrasts": hosts, "longitudinal_contrasts": trends,
            "alerts": [r for r in trends if r["alert"]], "automatic_actions": False}
