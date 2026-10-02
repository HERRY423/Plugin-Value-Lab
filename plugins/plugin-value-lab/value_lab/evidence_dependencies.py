"""Local, conservative dependency rechecks beside an immutable usage card.

No registry, signatures, model execution, scientific fitting or external services.
The graph is an operator declaration, not discovery or proof of completeness.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import platform
import re

from .artifacts import MAX_BYTES, confined, grade_artifact, sha, validate_verifier
from .core import ValidationError, load_json, suite_digest, write_json

FORMAT = "pvl-evidence-dependencies-1"
REVISION = "pvl-evidence-recheck-1"
KINDS = {"recommendation", "claim", "rule", "artifact", "dependency"}
CATEGORIES = {"plugin", "tool", "model", "host", "environment", "task_distribution",
              "configuration", "budget", "policy", "new_evidence"}
REQUIRED = CATEGORIES - {"tool"}
MODES = {"artifact_rescore", "model_execution", "scientific_execution"}
EDGES = {"recommendation": {"claim"}, "claim": {"rule"},
         "rule": {"artifact", "dependency"}, "artifact": {"dependency"}, "dependency": set()}


def _require(ok, message):
    if not ok:
        raise ValidationError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _pointers(card):
    """Every decision-bearing row is accounted for; unmapped rows stay unknown."""
    result = {}
    for name in ("use_when", "prefer_baseline_when", "investigate"):
        for index, value in enumerate(card.get(name, [])):
            result[f"/{name}/{index}"] = value
    for index, value in enumerate(card.get("envelope", {}).get("rows", [])):
        result[f"/envelope/rows/{index}"] = value
    return result


def validate_graph(graph, card):
    _require(isinstance(card, dict) and card.get("type") == "plugin_usage_card", "Expected a usage card")
    _require(isinstance(graph, dict) and set(graph) == {"format", "card_sha256", "coverage", "nodes"}, "Invalid graph fields")
    _require(graph["format"] == FORMAT and graph["card_sha256"] == suite_digest(card), "Graph must bind the exact source card")
    coverage = graph["coverage"]
    _require(isinstance(coverage, dict) and set(coverage) == {"complete", "basis"}
             and type(coverage["complete"]) is bool and _text(coverage["basis"]), "Declare coverage and its basis")
    _require(isinstance(graph["nodes"], list) and 1 <= len(graph["nodes"]) <= 2000, "Expected 1..2000 nodes")
    nodes, refs = {}, set()
    for node in graph["nodes"]:
        _require(isinstance(node, dict), "Node must be an object")
        kind, ident = node.get("kind"), node.get("id")
        _require(isinstance(kind, str) and kind in KINDS and isinstance(ident, str)
                 and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", ident) and ident not in nodes, "Invalid or duplicate node ID/kind")
        extra = {"recommendation": {"card_pointer"}, "claim": {"statement"},
                 "rule": {"scope", "mode", "grader", "basis"},
                 "artifact": {"path", "sha256"}, "dependency": {"category"}}[kind]
        _require(set(node) == {"id", "kind", "depends_on"} | extra, "Unexpected node fields: " + ident)
        deps = node["depends_on"]
        _require(isinstance(deps, list) and all(_text(d) for d in deps)
                 and len(set(deps)) == len(deps), "Invalid dependency edges")
        if kind == "dependency":
            _require(isinstance(node["category"], str) and node["category"] in CATEGORIES and not deps, "Invalid dependency category")
        elif kind == "recommendation":
            pointer = node["card_pointer"]
            _require(isinstance(pointer, str) and pointer in _pointers(card) and pointer not in refs, "Unknown/duplicate card pointer")
            refs.add(pointer)
        elif kind == "claim":
            _require(_text(node["statement"]), "Claim needs a bounded statement")
        elif kind == "artifact":
            confined(Path.cwd(), node["path"])
            _require(_digest(node["sha256"]), "Artifact requires its original digest")
        elif kind == "rule":
            _require(node["scope"] in ("historical_artifact", "current_behavior") and isinstance(node["mode"], str) and node["mode"] in MODES
                     and _text(node["basis"]), "Declare rule scope, mode and basis")
            if node["scope"] == "historical_artifact":
                _require(node["mode"] == "artifact_rescore", "Historical checks cannot claim new execution")
                grader = node["grader"]
                _require(isinstance(grader, dict) and set(grader) == {"id", "type", "artifact", "verifier"}
                         and grader["type"] == "artifact", "Only built-in artifact graders can run locally")
                spec = grader["verifier"]
                _require(isinstance(spec, dict) and spec.get("kind") in ("json_fields", "labels", "de_table")
                         and "testing_family" not in spec, "Use a self-contained built-in check; external references require a separate workflow")
                validate_verifier(grader)
            else:
                _require(node["mode"] != "artifact_rescore" and node["grader"] is None,
                         "Old-artifact scoring cannot establish current behavior")
        nodes[ident] = node
    for node in nodes.values():
        deps = node["depends_on"]
        _require(all(d in nodes and nodes[d]["kind"] in EDGES[node["kind"]] for d in deps), "Dangling edge or invalid layer")
        if node["kind"] in ("recommendation", "claim", "rule"):
            _require(bool(deps), "Evidence path must not be empty")
        if node["kind"] == "rule":
            artifacts = [d for d in deps if nodes[d]["kind"] == "artifact"]
            _require(bool(artifacts), "Rule must reference raw artifacts")
            if node["scope"] == "historical_artifact":
                _require(artifacts == [node["grader"]["artifact"]], "Built-in rule must name exactly one artifact node")
    # Strict layers make cycles impossible, including dependency-to-dependency cycles.
    _require(any(n["kind"] == "recommendation" for n in nodes.values()), "Map at least one source recommendation")
    return nodes


def _closure(nodes, ident, historical=False):
    seen, todo = set(), [ident]
    while todo:
        item = todo.pop()
        if item in seen:
            continue
        seen.add(item)
        if not (historical and nodes[item]["kind"] == "artifact"):
            todo.extend(nodes[item]["depends_on"])
    return seen


def _engine():
    # Conservative implementation/runtime binding; unchanged version strings are insufficient.
    root = Path(__file__).parent
    return suite_digest({"python": platform.python_version(), "platform": platform.platform(),
                         "sources": {p.name: sha(p) for p in sorted(root.glob("*.py"))}})


def _observe(nodes, root):
    observed = {}
    for ident, node in nodes.items():
        if node["kind"] != "artifact":
            continue
        try:
            path = confined(root, node["path"])
            _require(path.is_file() and path.stat().st_size <= MAX_BYTES, "Missing or oversized artifact")
            digest = sha(path)
            observed[ident] = {"sha256": digest, "intact": digest == node["sha256"]}
        except (OSError, ValidationError) as exc:
            observed[ident] = {"sha256": None, "intact": False, "reason": str(exc)}
    return observed


def _seal(report):
    report["revision_sha256"] = suite_digest(report)
    return report


def _verify_previous(previous, card):
    _require(isinstance(previous, dict), "Invalid prior revision")
    unsigned = {k: v for k, v in previous.items() if k != "revision_sha256"}
    _require(previous.get("format") == REVISION and previous.get("revision_sha256") == suite_digest(unsigned), "Prior revision changed")
    _require(previous.get("card_sha256") == suite_digest(card), "Prior revision belongs to another card")
    validate_graph(previous["graph"], card)
    # Hashes detect accidental changes only, never authenticate a submitter.


def recheck(card, graph, inventory, artifact_root, *, previous=None, action="plan"):
    """Plan, replay bytes, or rescore only affected historical-artifact checks.

    Model/science execution is always an explicit pending task. Changed guidance
    stays under review even when its narrow computational checks pass.
    """
    _require(action in ("plan", "replay", "rescore"), "Unknown action")
    nodes = validate_graph(graph, card)
    _require(isinstance(inventory, dict) and all(_text(k) and (v is None or _text(v)) for k, v in inventory.items()),
             "Inventory maps dependency IDs to nonempty identity strings or null")
    if previous is not None:
        _verify_previous(previous, card)
    dependencies = {k: n for k, n in nodes.items() if n["kind"] == "dependency"}
    fallback = []
    if not graph["coverage"]["complete"]:
        fallback.append("DEPENDENCY_COVERAGE_INCOMPLETE")
    categories = {n["category"] for n in dependencies.values()}
    if REQUIRED - categories:
        fallback.append("MISSING_CHANGE_CATEGORIES:" + ",".join(sorted(REQUIRED - categories)))
    if set(inventory) - dependencies.keys():
        fallback.append("UNMAPPED_DEPENDENCY:" + ",".join(sorted(set(inventory) - dependencies.keys())))
    unknown = [k for k in dependencies if not inventory.get(k)]
    if unknown:
        fallback.append("UNKNOWN_DEPENDENCY:" + ",".join(sorted(unknown)))
    engine = _engine()
    observed = _observe(nodes, artifact_root)
    changed, changes = set(), []
    if previous is not None:
        old_nodes = {n["id"]: n for n in previous["graph"]["nodes"]}
        if engine != previous["engine_sha256"]:
            fallback.append("CHECK_ENGINE_OR_RUNTIME_CHANGED")
        if graph["coverage"] != previous["graph"]["coverage"]:
            fallback.append("COVERAGE_DECLARATION_CHANGED")
        if set(nodes) != set(old_nodes) or any(
                (n["kind"], n["depends_on"]) != (old_nodes[k]["kind"], old_nodes[k]["depends_on"])
                for k, n in nodes.items() if k in old_nodes):
            fallback.append("GRAPH_TOPOLOGY_CHANGED")
        for ident, node in nodes.items():
            if old_nodes.get(ident) != node:
                changed.add(ident)
                changes.append({"id": ident, "reason": "NODE_CONTRACT_CHANGED"})
        for ident in set(inventory) | set(previous["inventory"]):
            before, after = previous["inventory"].get(ident), inventory.get(ident)
            if before != after:
                changed.add(ident)
                changes.append({"id": ident, "reason": "DEPENDENCY_IDENTITY_CHANGED", "before": before, "after": after})
                if ident not in dependencies:
                    fallback.append("REMOVED_OR_UNMAPPED_DEPENDENCY:" + ident)
        for ident, observation in observed.items():
            if observation != previous["artifacts"].get(ident):
                changed.add(ident)
                changes.append({"id": ident, "reason": "ARTIFACT_OBSERVATION_CHANGED"})
    for ident, observation in observed.items():
        if not observation["intact"]:
            changed.add(ident)
    rules, tasks = {}, []
    for ident, node in nodes.items():
        if node["kind"] != "rule":
            continue
        historical = node["scope"] == "historical_artifact"
        path = _closure(nodes, ident, historical)
        causes = sorted(path & changed)
        prior = previous["rules"].get(ident) if previous else None
        affected = prior is None or bool(fallback or causes)
        row = {"scope": node["scope"], "required_evidence": node["mode"],
               "affected": affected, "causes": causes, "dependency_path": sorted(path),
               "producer_dependencies_excluded": sorted(_closure(nodes, ident) - path),
               "action": "retained", "status": "UNKNOWN", "evidence_kind": None,
               "passed": None, "receipt": None, "origin_revision": None}
        if prior and not affected:
            for key in ("status", "evidence_kind", "passed", "receipt"):
                row[key] = deepcopy(prior[key])
            row["origin_revision"] = prior.get("origin_revision") or previous["revision_sha256"]
            row["retained_result_reason"] = prior.get("retained_result_reason", prior["reason"])
            row["reason"] = "Same rule, engine, artifact bytes and applicable dependency identities; retained only within the declared scope."
        elif not historical:
            row.update(status="REEXECUTION_REQUIRED", action="pending",
                       reason="Current behavior requires a new authorized execution and newly evaluated source card; old bytes or scores cannot close this task.")
        elif any(not observed[a]["intact"] for a in path if a in observed):
            row.update(status="UNKNOWN", action="blocked", reason="Raw artifact missing or differs from its frozen digest; never repin it silently.")
        elif action == "rescore":
            artifact = nodes[node["grader"]["artifact"]]
            passed, reason, receipt = grade_artifact(node["grader"], {"artifacts": {
                artifact["id"]: {"path": artifact["path"], "sha256": artifact["sha256"]}}}, artifact_root)
            row.update(status="PASSED" if passed is True else "FAILED" if passed is False else "UNKNOWN",
                       passed=passed, action="rescored", evidence_kind="artifact_rescore", receipt=receipt, reason=reason)
        elif action == "replay":
            row.update(status="REPLAYED_ONLY", action="replayed", evidence_kind="artifact_replay",
                       reason="Frozen bytes match; no correctness scoring, model execution or scientific recomputation occurred.")
        else:
            row.update(status="RECHECK_REQUIRED", action="pending", reason="Affected check has not been executed.")
        # A pending/failed check must stay pending across repeated unchanged updates.
        if historical and prior and not affected and prior["status"] in ("RECHECK_REQUIRED", "REPLAYED_ONLY", "UNKNOWN") and action == "rescore":
            artifact = nodes[node["grader"]["artifact"]]
            if all(observed[a]["intact"] for a in path if a in observed):
                passed, reason, receipt = grade_artifact(node["grader"], {"artifacts": {
                    artifact["id"]: {"path": artifact["path"], "sha256": artifact["sha256"]}}}, artifact_root)
                row.update(status="PASSED" if passed is True else "FAILED" if passed is False else "UNKNOWN",
                           passed=passed, action="rescored", evidence_kind="artifact_rescore", receipt=receipt,
                           origin_revision=None, reason=reason)
                row.pop("retained_result_reason", None)
        rules[ident] = row
        if row["status"] != "PASSED":
            tasks.append({"rule_id": ident, "required_evidence": node["mode"], "status": row["status"],
                          "execution_authorized": False, "reason": row["reason"]})
    # Reobserve after scoring to avoid retaining a mixed file snapshot.
    after = _observe(nodes, artifact_root)
    _require(after == observed, "Artifacts changed during recheck; retry with a stable snapshot")
    claims, recommendations = {}, []
    for ident, node in nodes.items():
        if node["kind"] == "claim":
            checked = all(rules[r]["status"] == "PASSED" for r in node["depends_on"])
            claims[ident] = {"statement": node["statement"], "rules": node["depends_on"],
                             "status": "LOCAL_CHECKS_PASSED" if checked else "REVIEW_REQUIRED",
                             "claim_truth_established": False}
    mapped = set()
    for ident, node in nodes.items():
        if node["kind"] != "recommendation":
            continue
        pointer = node["card_pointer"]
        mapped.add(pointer)
        # Use each rule's effective scope. Historical file checks stop at the
        # recorded artifact; they do not inherit its producer's current state.
        structural = _closure(nodes, ident)
        path = {ident, *node["depends_on"]}
        for rule_id in structural & rules.keys():
            path.update(rules[rule_id]["dependency_path"])
        affected_rules = [r for r in sorted(path) if r in rules and rules[r]["affected"]]
        old = next((r for r in previous["recommendations"] if r["id"] == ident), None) if previous else None
        needs_review = bool(fallback or path & changed or (old and old["review_required"]))
        recommendations.append({"id": ident, "card_pointer": pointer,
            "source_guidance": deepcopy(_pointers(card)[pointer]), "claims": node["depends_on"],
            "status": "REVIEW_REQUIRED" if needs_review else "SOURCE_GUIDANCE_ONLY",
            "review_required": needs_review, "affected_rules": affected_rules,
            "changed_path": sorted(path & changed),
            "reason": "Changed support stays under review until a newly evaluated card is supplied." if needs_review
                else "Original guidance and its limits are preserved; local checks do not establish the supporting claim."})
    unmapped = sorted(set(_pointers(card)) - mapped)
    report = {"format": REVISION, "card_sha256": suite_digest(card), "graph": deepcopy(graph),
        "parent_revision_sha256": previous["revision_sha256"] if previous else None,
        "source_status": card.get("status"), "source_verdict": card.get("verdict"),
        "inventory": deepcopy(inventory), "inventory_basis": "OPERATOR_SUPPLIED_NOT_LIVE_VERIFIED",
        "engine_sha256": engine, "artifacts": observed, "changes": changes,
        "fallback_reasons": sorted(set(fallback)), "recheck_scope": "FULL" if fallback or previous is None else "LOCAL",
        "rules": rules, "claims": claims, "recommendations": recommendations,
        "unmapped_card_pointers": unmapped, "pending_tasks": tasks,
        "whole_card_renewed": False, "new_model_executions": 0, "new_scientific_executions": 0,
        "local_rescores": sum(r["action"] == "rescored" for r in rules.values()),
        "artifact_replays": sum(r["action"] == "replayed" for r in rules.values()),
        "limits": ["Dependency coverage and current identities are operator declarations, not proven discovery.",
                   "Unmapped guidance is unknown; the legacy whole-card invalidation policy still applies.",
                   "Retained failed and unknown checks are not converted into passes.",
                   "Local checks never establish benefit, scientific validity, independence or adoption.",
                   "Hashes bind local bytes only; no authentication, signature or registry is added."]}
    return _seal(report)


def write_revision(report, output):
    """Write a new sidecar revision; never overwrite old cards or reports."""
    output = Path(output)
    _require(not output.exists(), "Preserve old evidence; choose a new output directory")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "revision.json", report)
    from .usage import _markdown
    lines = ["# 使用依据局部复核", "", "原卡状态：" + _markdown(report["source_status"]),
             "", "复核范围：" + report["recheck_scope"], "", "整卡未重新认证；原结论与证据上限保持。", "",
             "重放旧产物、重新评分旧产物、模型执行、科学计算执行分别记录。", ""]
    for reason in report["fallback_reasons"]:
        lines += ["- 扩大复核：" + _markdown(reason)]
    lines += ["", "| 检查 | 状态 | 本轮动作 | 保留或补测理由 |", "| --- | --- | --- | --- |"]
    for ident, row in report["rules"].items():
        lines += ["| " + " | ".join(_markdown(x) for x in (ident, row["status"], row["action"], row["reason"])) + " |"]
    lines += ["", "## 使用建议", ""]
    for row in report["recommendations"]:
        lines += ["- " + _markdown(row["card_pointer"] + ": " + row["status"] + " — " + row["reason"])]
    lines += ["", "未映射建议：" + _markdown(report["unmapped_card_pointers"]), "",
              "本轮旧产物重评分：" + str(report["local_rescores"]), "",
              "本轮模型／科学计算执行：0／0。待执行任务见 revision.json 的 pending_tasks。", ""]
    (output / "RECHECK.md").write_text("\n".join(lines), encoding="utf-8")
    return {"revision": str(output / "revision.json"), "report": str(output / "RECHECK.md")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "replay", "rescore"))
    parser.add_argument("--card", required=True)
    parser.add_argument("--graph", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--previous")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        output = Path(args.output).resolve()
        inputs = [Path(p).resolve() for p in (args.card, args.graph, args.inventory, args.artifacts)]
        if args.previous:
            inputs.append(Path(args.previous).resolve())
        _require(not output.exists() and not any(p == output or p.is_relative_to(output) for p in inputs), "Output must be fresh and separate from inputs")
        report = recheck(load_json(args.card), load_json(args.graph), load_json(args.inventory), args.artifacts,
                         previous=load_json(args.previous) if args.previous else None, action=args.action)
        print(json.dumps(write_revision(report, args.output), ensure_ascii=True, allow_nan=False))
        return 0
    except (ValidationError, OSError, ValueError) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
