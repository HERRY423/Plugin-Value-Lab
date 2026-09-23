"""Signed, static registry snapshots. This module never uploads or contacts reviewers."""
from datetime import datetime, timezone
import html
from pathlib import Path
import tempfile
from statistics import mean

from .artifacts import confined, sha
from .core import ValidationError, load_json, suite_digest, write_json
from .longitudinal import analyze_registry
from .registry import _entries, _digest, registry_view
from .review_policy import review_gate
from .signatures import sign, verify, trusted_key, validate_trust


def _heldout(entry, suite, declaration):
    cases = suite["cases"]
    if (entry / "corpus.json").is_file():
        cases = load_json(entry / "corpus.json")["cases"]
    splits = {c["id"]: {"family": c.get("family", c.get("cluster")), "split": c.get("split", "unspecified")} for c in cases}
    families, issues = {}, []
    for case in splits.values():
        if case["split"] in ("development", "heldout"):
            families.setdefault(case["family"], set()).add(case["split"])
    if any(len(values) > 1 for values in families.values()):
        issues.append("A declared task family crosses development and heldout splits")
    unknown = {"status": "unknown", "statement": "No held-out exposure declaration supplied"}
    if declaration is not None:
        if not isinstance(declaration, dict) or set(declaration) != {"suite_sha256", "split_sha256", "status", "statement"}:
            raise ValidationError("Held-out declaration requires suite/split digests, status and statement")
        if declaration["suite_sha256"] != suite_digest(suite) or declaration["split_sha256"] != suite_digest(splits):
            raise ValidationError("Held-out declaration does not match suite and split")
        if declaration["status"] not in ("declared_unexposed", "exposed", "unknown") or not isinstance(declaration["statement"], str) or not declaration["statement"].strip():
            raise ValidationError("Invalid held-out exposure declaration")
        unknown = {k: declaration[k] for k in ("status", "statement")}
    return {**unknown, "split_sha256": suite_digest(splits), "heldout_cases": sum(c["split"] == "heldout" for c in splits.values()), "blocking_issues": issues,
            "scope": "Submitter declaration, not proof of non-exposure or independent ground truth"}


def _card(row, entry, report, suite, trust, declaration):
    heldout = _heldout(entry, suite, declaration)
    reviews = review_gate(row, suite, trust)
    blockers = []
    positive = report["verdict"] == "PROMISING_LOCAL_SIGNAL"
    if not row["descriptive_comparison_eligible"]:
        blockers.append("Study is synthetic, incomplete, disputed, superseded or reuses sessions")
    if not positive:
        blockers.append("No positive marginal-value verdict")
    if reviews["qualifying_reviewers"] < 1:
        blockers.append("At least one version-bound, trusted-key non-author review is required")
    if not heldout["heldout_cases"] or heldout["status"] != "declared_unexposed":
        blockers.append("Held-out cases and an explicit unexposed declaration are required")
    split_results = _split_results(entry, report, suite)
    if not split_results["heldout"]["objective_met"]:
        blockers.append("Held-out outcomes must independently meet the frozen objective and regression gates")
    if (suite["policy"].get("objective") == "efficiency" or suite["policy"]["require_cost_saving"]) and not report["cost_analysis"]["saving_claim_eligible"]:
        blockers.append("Cost-dependent public signal requires complete cost coverage")
    blockers.extend(heldout["blocking_issues"])
    if any(not isinstance(suite["conditions"].get(k), str) or not suite["conditions"][k].strip() for k in ("host_version", "model_version")):
        blockers.append("Explicit observed host and model versions are required")
    status = "REVIEWED_LOCAL_SIGNAL" if not blockers else "PENDING_REVIEW" if positive else "OBSERVATION_ONLY"
    return {"format": "pvl-public-card-1", "entry_id": row["entry_id"], "study_id": row["study_id"],
            "plugin": row["plugin"], "plugin_sha256": row["plugin_sha256"], "suite_sha256": suite_digest(suite),
            "usage_card_sha256": sha(entry / "usage-card.json"), "report_sha256": sha(entry / "report.json"),
            "engine_sha256": row["engine_sha256"], "observed_at": row["observed_at"],
            "model": row["model"], "model_version": suite["conditions"].get("model_version"),
            "host": row["host"], "host_version": suite["conditions"].get("host_version"),
            "conditions_sha256": suite_digest(suite["conditions"]), "evidence_type": row["evidence_type"],
            "verdict": row["verdict"], "status": status, "positive_listing_eligible": not blockers,
            "publication_blockers": blockers, "study_blocker_count": len(report["blockers"]),
            "summary": {k: report["summary"].get(k) for k in ("quality_delta", "with_score", "without_score", "expected_runs", "observed_runs", "complete_pairs", "cost_delta_usd")},
            "heldout": heldout, "split_results": split_results, "review_gate": reviews,
            "cost_evidence": {k: report["cost_analysis"].get(k) for k in ("complete_category_coverage", "saving_claim_eligible", "coverage")},
            "ancestor_review_count": len(row["ancestor_reviews"]), "review_status": row["review_status"],
            "case_results": [{k: c.get(k) for k in ("id", "cluster", "with_score", "without_score", "delta")} for c in report["cases"]],
            "scientific_errors": report.get("scientific_errors"), "corpus_errors": report.get("corpus_errors"),
            "claim_limits": {"scientific_authorization": "NONE", "independent_scientific_validation": "NOT_ESTABLISHED",
                             "identity": "Operator-enrolled public keys; human identity is not automatically authenticated",
                             "signature": "Publisher attests this exact summary; a signature is not an experiment"}}


def _split_results(entry, report, suite):
    """Summarize existing scored runs, never re-label or re-score observations."""
    cases = load_json(entry / "corpus.json")["cases"] if (entry / "corpus.json").is_file() else suite["cases"]
    splits = {c["id"]: c.get("split", "unspecified") for c in cases}
    policy = suite["policy"]
    result = {}
    for split in ("development", "heldout", "unspecified"):
        rows = [c for c in report["cases"] if splits.get(c["id"], "unspecified") == split]
        complete = bool(rows) and all(c["delta"] is not None and all(not r["issues"] for r in c["runs"]) for c in rows)
        scores = {arm: mean(c[arm + "_score"] for c in rows) if complete else None for arm in ("with", "without")}
        delta = scores["with"] - scores["without"] if complete else None
        costs = {arm: [r["cost_usd"] for c in rows for r in c["runs"] if r["arm"] == arm] for arm in ("with", "without")}
        cost_delta = (mean(costs["with"]) - mean(costs["without"])) if complete and all(v is not None for values in costs.values() for v in values) else None
        efficiency = policy.get("objective") == "efficiency"
        quality_ok = complete and scores["with"] + 1e-12 >= policy["quality_floor"] and (
            delta >= -1e-12 if efficiency else delta > 1e-12 and delta + 1e-12 >= policy["min_quality_delta"])
        cost_ok = not (efficiency or policy["require_cost_saving"]) or (
            report["cost_analysis"]["saving_claim_eligible"] and cost_delta is not None and cost_delta < -1e-12)
        regressions = [c["id"] for c in rows if c["delta"] is not None and c["delta"] < -policy["max_case_regression"] - 1e-12]
        critical = [c["id"] for c in rows if any(r["arm"] == "with" and any(g["critical"] and g["scored"] and g["passed"] is False for g in r["grades"]) for r in c["runs"])]
        result[split] = {"cases": len(rows), "with_score": scores["with"], "without_score": scores["without"],
                         "quality_delta": delta, "cost_delta_usd": cost_delta, "regressions": regressions,
                         "critical_failures": critical, "objective_met": bool(quality_ok and cost_ok and not regressions and not critical),
                         "scope": "Descriptive split result; no independent scientific or generalization claim"}
    return result


def _html(cards, analysis, bootstrap):
    esc = lambda v: html.escape("未知" if v is None else str(v), quote=True)
    status = {"REVIEWED_LOCAL_SIGNAL": "已复核的局部信号", "PENDING_REVIEW": "正向展示待复核", "OBSERVATION_ONLY": "仅展示观察"}
    body = ['<section><h2>冷启动状态：' + esc(bootstrap["label"]) + '</h2><p>本地证据账本 · 暂定交换格式；尚未建立可信证据层。</p><p>' + esc(bootstrap["next_milestone"]) + '</p></section>']
    for card in cards:
        summary = card["summary"]
        body.append('<article><div class="tag">' + esc(status[card["status"]]) + '</div><h2>' + esc(card["plugin"]["name"]) + '</h2><p>'
                    + esc(card["plugin"]["version"]) + ' · ' + esc(card["model"]) + ' · ' + esc(card["host"]) + '</p><p>插件边际增益 Δ：<strong>'
                    + esc(summary["quality_delta"]) + '</strong>　完整配对：' + esc(summary["complete_pairs"]) + '</p><p>证据：'
                    + esc(card["evidence_type"]) + '　合格非作者复核：' + esc(card["review_gate"]["qualifying_reviewers"]) + '</p><p>留出声明：'
                    + esc(card["heldout"]["status"]) + '　研究结论：' + esc(card["verdict"]) + '</p><details><summary>证据限制与摘要</summary><ul>'
                    + ''.join('<li>' + esc(b) + '</li>' for b in card["publication_blockers"]) + '</ul><p>suite SHA-256：' + esc(card["suite_sha256"])
                    + '</p><p>宿主版本：' + esc(card["host_version"]) + '</p><p>开发集 Δ：' + esc(card["split_results"]["development"]["quality_delta"])
                    + '；留出集 Δ：' + esc(card["split_results"]["heldout"]["quality_delta"]) + '</p><p>完整成本覆盖：'
                    + esc(card["cost_evidence"]["complete_category_coverage"]) + '</p></details><a href="cards/' + card["entry_id"] + '.json">完整签名摘要</a></article>')
    alerts = ''.join('<li>' + esc(a["axis"]) + ' · Δ 变化 ' + esc(a["plugin_gain_change"]) + ' · ' + esc(a["after"][:12]) + '</li>' for a in analysis["alerts"])
    contrasts = ''.join('<tr><td>' + esc(c["before"][:12]) + '</td><td>' + esc(c["after"][:12]) + '</td><td>' + esc(c["status"]) + '</td><td>' + esc(c["plugin_gain_change"]) + '</td></tr>' for c in analysis["host_contrasts"])
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>Scientific Plugin Value Registry</title><style>body{margin:0;background:#f4f5f0;color:#153631;font:16px/1.65 system-ui}main{max-width:1100px;margin:48px auto;padding:0 24px}h1{font-size:40px;line-height:1.15}header{border-bottom:2px solid #153631;padding-bottom:25px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:20px}article{background:white;border:1px solid #d5dcd5;padding:24px;border-radius:12px}.tag{color:#866127;font-size:14px}a{color:#17685b}strong{font-size:25px}details{overflow-wrap:anywhere}table{width:100%;text-align:left}td{padding:10px;border-bottom:1px solid #d5dcd5}.note{color:#63716a}</style><main><header><p>科研插件 · 可审查证据 · 只读快照</p><h1>Scientific Plugin Value Registry</h1><p>在匹配条件下，测量并登记科研 Agent 插件的边际价值。</p><p class="note">合成、负面、缺失与异议保留。签名证明摘要与持钥者的关联，不证明科学有效性。此页面不收集数据、不运行模型。</p></header><h2>纵向变化提醒</h2><ul>' + (alerts or '<li>没有满足可比条件的下降记录；这不等于已证明无退化。</li>') + '</ul><h2>使用卡</h2><div class="grid">' + ''.join(body) + '</div><h2>跨宿主比较</h2><table><tr><th>研究 A</th><th>研究 B</th><th>可比状态</th><th>ΔB − ΔA</th></tr>' + contrasts + '</table><p class="note">差值仅是描述性观察；不能单凭宿主差异宣称因果效应或发表级发现。</p><p><a href="index.json">签名目录与完整比较</a></p></main></html>'


def build_public(registry, output, key, trust, declarations=None, previous=None):
    validate_trust(trust)
    # Check role before writing any output. The embedded signer is never self-trusted.
    probe = sign({}, key, "pvl-public-index-1")
    trusted_key(probe, trust, "publisher")
    view = registry_view(registry)
    entries = {p.name: (p, report) for p, report, _ in _entries(registry)}
    declarations = declarations if declarations is not None else {}
    if not isinstance(declarations, dict) or set(declarations) - set(entries):
        raise ValidationError("Held-out declarations reference unknown entries")
    cards = []
    for row in view["entries"]:
        path, report = entries[row["entry_id"]]
        cards.append(_card(row, path, report, load_json(path / "suite.json"), trust, declarations.get(path.name)))
    analysis = analyze_registry(registry, view)
    previous_id = verify_public(previous, trust)["snapshot_sha256"] if previous is not None else None
    page = _html(cards, analysis, view["bootstrap"])
    output = Path(output).resolve()
    registry = Path(registry).resolve()
    if output.exists() or output.is_relative_to(registry) or registry.is_relative_to(output):
        raise ValidationError("Use a fresh public directory outside the private registry")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".public-stage-", dir=output.parent) as temp:
        stage = Path(temp) / "site"
        stage.mkdir()
        for card in cards:
            write_json(stage / "cards" / (card["entry_id"] + ".json"), {"payload": card, "signature": sign(card, key, "pvl-public-card-1")})
        (stage / "index.html").write_text(page, encoding="utf-8")
        index = {"format": "pvl-public-index-1", "generated_at": datetime.now(timezone.utc).isoformat(),
                 "previous_snapshot_sha256": previous_id, "trust_policy_sha256": suite_digest(trust),
                 "files": {p.relative_to(stage).as_posix(): sha(p) for p in sorted(stage.rglob("*")) if p.is_file()},
                 "cards": [c["entry_id"] for c in cards], "analysis": analysis, "bootstrap": view["bootstrap"],
                 "positive_cards": sum(c["positive_listing_eligible"] for c in cards),
                 "online_publication": False, "scientific_authorization": "NONE"}
        write_json(stage / "index.json", {"payload": index, "signature": sign(index, key, "pvl-public-index-1")})
        verify_public(stage, trust)
        stage.rename(output)
    return {**verify_public(output, trust), "output": str(output), "published": False}


def verify_public(directory, trust, expected_snapshot=None):
    validate_trust(trust)
    root = Path(directory).resolve()
    envelope = load_json(confined(root, "index.json"))
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
        raise ValidationError("Invalid public index envelope")
    index = envelope["payload"]
    verify(index, envelope["signature"], "pvl-public-index-1")
    trusted_key(envelope["signature"], trust, "publisher")
    if index.get("trust_policy_sha256") != suite_digest(trust):
        raise ValidationError("Trust policy changed; rebuild to re-evaluate reviewer revocations and roles")
    snapshot = suite_digest(envelope)
    if expected_snapshot is not None and snapshot != _digest(expected_snapshot):
        raise ValidationError("Public snapshot differs from the separately retained digest")
    if index.get("format") != "pvl-public-index-1" or not isinstance(index.get("files"), dict) or not isinstance(index.get("cards"), list):
        raise ValidationError("Invalid public index contract")
    expected = {"index.html"} | {"cards/" + _digest(eid) + ".json" for eid in index["cards"]}
    if len(set(index["cards"])) != len(index["cards"]) or set(index["files"]) != expected:
        raise ValidationError("Public snapshot contains unexpected or duplicate card paths")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != expected | {"index.json"}:
        raise ValidationError("Unexpected or missing public snapshot files")
    for path, digest in index["files"].items():
        if sha(confined(root, path)) != _digest(digest):
            raise ValidationError("Public snapshot bytes changed")
    count = 0
    for eid in index["cards"]:
        card = load_json(confined(root, "cards/" + eid + ".json"))
        if not isinstance(card, dict) or set(card) != {"payload", "signature"}:
            raise ValidationError("Invalid signed card")
        verify(card["payload"], card["signature"], "pvl-public-card-1")
        trusted_key(card["signature"], trust, "publisher")
        if card["signature"]["key_id"] != envelope["signature"]["key_id"] or card["payload"]["entry_id"] != eid:
            raise ValidationError("Card signer or identity differs from index")
        count += card["payload"]["positive_listing_eligible"] is True
    if index.get("positive_cards") != count:
        raise ValidationError("Positive-card count disagrees with signed cards")
    return {"snapshot_sha256": snapshot, "cards": len(index["cards"]), "positive_cards": count,
            "signature_status": "VALID_FOR_LOCALLY_TRUSTED_PUBLISHER", "previous_snapshot_sha256": index.get("previous_snapshot_sha256"),
            "freshness": "NOT_ESTABLISHED_WITHOUT_OUT_OF_BAND_SNAPSHOT", "scientific_authorization": "NONE"}
