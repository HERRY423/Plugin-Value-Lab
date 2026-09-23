"""Local append-only evidence registry and portable submissions.

No remote registry, identity authentication, adoption or publication is implied.
Fingerprints detect edits relative to a retained receipt, not a malicious owner
rewriting an entire registry. All mutations serialize and preserve old entries.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import shutil
import tempfile

from .artifacts import confined, sha, MAX_BYTES
from .core import ValidationError, _text, _stamp, load_json, load_records, suite_digest, evaluate, write_json
from .usage import build_usage_card


FORMAT = "pvl-study-bundle-1"
LIMIT = "Local byte integrity; independence and real-world benefit are not authenticated"


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValidationError("Expected a SHA-256 digest")
    return value


def engine_digest():
    """Version labels stay fixed; executable source changes remain distinguishable."""
    source = Path(__file__).resolve().parent
    return suite_digest({p.name: sha(p) for p in sorted(source.glob("*.py"))})


def _metadata(meta):
    if not isinstance(meta, dict) or set(meta) != {"observed_at", "authors", "plugin_sha256", "limitations"}:
        raise ValidationError("Metadata requires observed_at, authors, plugin_sha256, limitations")
    _timestamp(meta["observed_at"])
    _digest(meta["plugin_sha256"])
    _text(meta["limitations"], "limitations")
    if not isinstance(meta["authors"], list) or not meta["authors"]:
        raise ValidationError("Declare study authors and organizations")
    ids = []
    for author in meta["authors"]:
        if not isinstance(author, dict) or set(author) != {"id", "organization"}:
            raise ValidationError("Author requires id and organization")
        ids.append(_text(author["id"], "author.id").strip().casefold())
        _text(author["organization"], "author.organization")
    if len(ids) != len(set(ids)):
        raise ValidationError("Duplicate author identity")


def _timestamp(value):
    try:
        return _stamp(value)
    except (ValueError, TypeError) as exc:
        raise ValidationError("Timestamp must be an ISO datetime with timezone") from exc


@contextmanager
def _writer(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = confined(root, ".writer.lock")
    try:
        stream = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValidationError("Registry writer active or interrupted; inspect .writer.lock before manual recovery") from exc
    try:
        with stream:
            stream.write(datetime.now(timezone.utc).isoformat())
        yield root
    finally:
        lock.unlink()


def verify_bundle(directory):
    root = Path(directory).resolve()
    manifest = load_json(confined(root, "manifest.json"))
    if (not isinstance(manifest, dict) or set(manifest) != {"format", "files"}
            or manifest["format"] != FORMAT or not isinstance(manifest["files"], dict)):
        raise ValidationError("Invalid study bundle manifest")
    required = {"suite.json", "runs.jsonl", "protocol.lock.json", "metadata.json", "report.json", "usage-card.json", "registration.json"}
    if not required <= set(manifest["files"]):
        raise ValidationError("Incomplete study bundle")
    observed = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if observed != set(manifest["files"]) | {"manifest.json"}:
        raise ValidationError("Unexpected or missing bundle files")
    for name, expected in manifest["files"].items():
        if name == "manifest.json" or "answers.private.json" in name.split("/"):
            raise ValidationError("Private answer keys cannot be included in a portable study bundle")
        path = confined(root, name)
        if sha(path) != _digest(expected):
            raise ValidationError(f"Bundle content changed: {name}")
    return {"entry_id": suite_digest(manifest), "format": FORMAT, "files": len(manifest["files"]),
            "integrity": "CONSISTENT", "claim_limit": LIMIT}


def _entries(root):
    entries = []
    directory = confined(root, "entries")
    for path in sorted(directory.iterdir()) if directory.exists() else []:
        if not path.is_dir():
            raise ValidationError("Unexpected registry entry")
        checked = verify_bundle(confined(root, "entries/" + path.name))
        if checked["entry_id"] != path.name:
            raise ValidationError("Entry identity does not match its immutable manifest")
        entries.append((path, load_json(path / "report.json"), load_json(path / "registration.json")))
    return entries


def _cohort(suite, evidence_type):
    # Version and model are displayed axes, never silently pooled. Host, tools,
    # environment, budget, task/rule/policy/split changes make a different cohort.
    conditions = {k: v for k, v in suite["conditions"].items() if k != "model"}
    return suite_digest({"plugin_name": suite["plugin"]["name"], "cases": suite["cases"],
        "conditions": conditions, "policy": suite["policy"], "runs_per_case": suite["runs_per_case"],
        "corpus": suite.get("corpus"), "evidence_type": evidence_type, "engine_sha256": engine_digest()})


def _observations(suite, records):
    # JSONL order is not a new observation. Keep duplicate records in the multiset.
    return suite_digest({"suite": suite, "records": sorted(suite_digest(r) for r in records)})


def _assessment(root):
    names = ("suite.json", "runs.jsonl", "cost-ledger.json", "corpus.json", "report.json", "usage-card.json")
    values = {name: load_records(root / name) if name == "runs.jsonl" else load_json(root / name)
              for name in names if (root / name).exists()}
    values["runs.jsonl"] = sorted(suite_digest(r) for r in values["runs.jsonl"])
    canonical_records = suite_digest(values["runs.jsonl"])
    def normalize(value):
        if isinstance(value, dict):
            return {k: canonical_records if k == "records_sha256" else normalize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [normalize(v) for v in value]
        return value
    values = normalize(values)
    values["artifacts"] = {p.relative_to(root / "artifacts").as_posix(): sha(p)
                           for p in sorted((root / "artifacts").rglob("*")) if p.is_file()}
    return suite_digest(values)


def register_study(study, metadata, registry, *, artifact_root=None, verifier_root=None, corpus_root=None,
                   parent=None, revision_reason=None):
    study = Path(study)
    suite = load_json(study / "suite.json")
    records = load_records(study / "runs.jsonl")
    lock = load_json(study / "protocol.lock.json")
    ledger = load_json(study / "cost-ledger.json") if (study / "cost-ledger.json").exists() else None
    _metadata(metadata)
    if not isinstance(lock, dict) or lock.get("suite_sha256") != suite_digest(suite):
        raise ValidationError("Registry requires the unchanged frozen study protocol")
    if parent is not None:
        _digest(parent)
        _text(revision_reason, "revision_reason")
    elif revision_reason is not None:
        raise ValidationError("A revision reason requires an explicit parent entry")
    artifacts = Path(artifact_root) if artifact_root is not None else study
    with _writer(registry) as root:
        existing = _entries(root)
        if parent is not None and parent not in {p.name for p, _, _ in existing}:
            raise ValidationError("Unknown parent entry")
        if parent is not None:
            original = next(p for p, _, _ in existing if p.name == parent)
            if suite_digest(load_json(original / "suite.json")) != suite_digest(suite):
                raise ValidationError("Evidence revisions must preserve the frozen suite; changed protocols are new studies")
            original_meta = load_json(original / "metadata.json")
            if any(metadata[k] != original_meta[k] for k in ("observed_at", "authors", "plugin_sha256")):
                raise ValidationError("Evidence revisions must preserve observed time, authors and plugin identity")
        observation_digest = _observations(suite, records)
        if parent is None and any(_observations(load_json(p / "suite.json"), load_records(p / "runs.jsonl")) == observation_digest for p, _, _ in existing):
            raise ValidationError("These observations are already registered; add a review instead")
        sessions = {r["session_id"] for r in records if isinstance(r.get("session_id"), str) and r["session_id"].strip()}
        overlaps = sorted(p.name for p, _, _ in existing if sessions & {
            r.get("session_id") for r in load_records(p / "runs.jsonl") if isinstance(r.get("session_id"), str)})
        # Temporary staging never appears as an entry. Interrupted commits have
        # no partially visible manifest; final rename happens under writer lock.
        with tempfile.TemporaryDirectory(prefix=".stage-", dir=root) as tmp:
            dest = Path(tmp) / "bundle"
            dest.mkdir()
            write_json(dest / "suite.json", suite)
            write_json(dest / "protocol.lock.json", lock)
            write_json(dest / "metadata.json", metadata)
            (dest / "runs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in records), encoding="utf-8")
            if ledger is not None:
                write_json(dest / "cost-ledger.json", ledger)
            for record in records:
                refs = record.get("artifacts", {})
                if not isinstance(refs, dict):
                    continue
                for ref in refs.values():
                    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
                        continue
                    try:
                        source = confined(artifacts, ref["path"])
                        if verifier_root is not None and any(g["type"] == "scenario" for c in suite["cases"] for g in c["graders"]) and source.resolve().is_relative_to(Path(verifier_root).resolve()):
                            raise ValidationError("Scorer-only file supplied as a public artifact")
                        if source.is_file() and source.stat().st_size <= MAX_BYTES and sha(source) == ref["sha256"]:
                            target = confined(dest / "artifacts", ref["path"])
                            if "answers.private.json" in Path(ref["path"]).parts:
                                raise ValidationError("Private key supplied as an artifact")
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(source, target)
                    except (OSError, ValidationError):
                        # Preserve the original reference; re-evaluation records
                        # missing/tampered bytes as unresolved, never as success.
                        continue
            options = dict(artifact_root=dest / "artifacts", verifier_root=verifier_root, corpus_root=corpus_root)
            report = evaluate(suite, records, lock, ledger, **options)
            card = build_usage_card(suite, records, lock, ledger, **options)
            if corpus_root is not None:
                write_json(dest / "corpus.json", load_json(Path(corpus_root) / "corpus.json"))
            write_json(dest / "report.json", report)
            write_json(dest / "usage-card.json", card)
            assessment = _assessment(dest)
            if parent is not None and any(_assessment(p) == assessment for p, _, _ in existing):
                raise ValidationError("No new assessment evidence; preserve the existing revision")
            registration = {"registered_at": datetime.now(timezone.utc).isoformat(), "parent": parent,
                "revision_reason": revision_reason, "assessment_sha256": assessment,
                "observation_sha256": observation_digest, "overlapping_entries": overlaps,
                "engine_sha256": engine_digest(),
                "cohort_sha256": _cohort(suite, report["evidence_type"]), "identity_basis": "DECLARED_NOT_AUTHENTICATED",
                "claim_limit": LIMIT}
            for name, value in (("report.json", report), ("usage-card.json", card), ("registration.json", registration)):
                write_json(dest / name, value)
            manifest = {"format": FORMAT, "files": {p.relative_to(dest).as_posix(): sha(p) for p in sorted(dest.rglob("*")) if p.is_file()}}
            write_json(dest / "manifest.json", manifest)
            checked = verify_bundle(dest)
            target = confined(root, "entries/" + checked["entry_id"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise ValidationError("Entry exists; preserve original")
            dest.rename(target)
    return {**checked, "verdict": report["verdict"], "blockers": report["blockers"],
            "overlapping_entries": overlaps, "published": False}


def _review(rev, metadata, entry_ids):
    fields = {"entry_id", "reviewer", "organization", "relationship", "conflicts", "verdict", "rationale", "reviewed_at", "evidence", "replication_entry_id"}
    if not isinstance(rev, dict) or not fields <= set(rev) or set(rev) - fields - {"protocol", "signature"}:
        raise ValidationError("Review must follow the complete review contract")
    if "protocol" in rev or "signature" in rev:
        from .review_policy import validate_protocol
        validate_protocol(rev)
    _digest(rev["entry_id"])
    for field in ("reviewer", "organization", "rationale"):
        _text(rev[field], field)
    _timestamp(rev["reviewed_at"])
    if rev["relationship"] not in ("author", "collaborator", "independent", "unknown"):
        raise ValidationError("Declare reviewer relationship")
    if not isinstance(rev["conflicts"], list) or any(not isinstance(x, str) or not x.strip() for x in rev["conflicts"]):
        raise ValidationError("Declare conflicts explicitly, including an empty list")
    if rev["verdict"] not in ("support", "dispute", "inconclusive"):
        raise ValidationError("Review verdict must be support, dispute or inconclusive")
    if not isinstance(rev["evidence"], list) or not rev["evidence"]:
        raise ValidationError("Review needs evidence references")
    for evidence in rev["evidence"]:
        if not isinstance(evidence, dict) or set(evidence) != {"reference", "sha256"}:
            raise ValidationError("Review evidence needs reference and sha256")
        _text(evidence["reference"], "evidence reference")
        _digest(evidence["sha256"])
    normalize = lambda x: x.strip().casefold()
    authors = metadata["authors"]
    author = normalize(rev["reviewer"]) in {normalize(a["id"]) for a in authors}
    same_org = normalize(rev["organization"]) in {normalize(a["organization"]) for a in authors}
    if rev["relationship"] == "independent" and (author or same_org or rev["conflicts"]):
        raise ValidationError("Independent declaration conflicts with authorship, organization or conflicts")
    replication = rev["replication_entry_id"]
    if replication is not None and (replication not in entry_ids or replication == rev["entry_id"]):
        raise ValidationError("Replication must name a different registered study")


def add_review(registry, review):
    with _writer(registry) as root:
        entries = {p.name: p for p, _, _ in _entries(root)}
        if not isinstance(review, dict) or review.get("entry_id") not in entries:
            raise ValidationError("Review target is not a registered entry")
        _review(review, load_json(entries[review["entry_id"]] / "metadata.json"), set(entries))
        event = {"review": review, "received_at": datetime.now(timezone.utc).isoformat(),
                 "identity_verification": "NOT_VERIFIED", "evidence_reference_verification": "NOT_FETCHED"}
        # Reviewer observations, not receipt time, determine duplicate identity.
        rid = suite_digest(review)
        target = confined(root, "reviews/" + rid + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError("Review already exists; preserve its original event")
        with tempfile.TemporaryDirectory(prefix=".review-stage-", dir=root) as tmp:
            staged = Path(tmp) / "review.json"
            write_json(staged, event)
            staged.rename(target)
    return {"review_id": rid, "entry_id": review["entry_id"], "identity_verification": "NOT_VERIFIED", "published": False}


def registry_view(registry):
    root = Path(registry).resolve()
    entries = _entries(root)
    ids = {p.name for p, _, _ in entries}
    meta = {p.name: load_json(p / "metadata.json") for p, _, _ in entries}
    registrations = {p.name: reg for p, _, reg in entries}
    sessions = {p.name: {r["session_id"] for r in load_records(p / "runs.jsonl")
                        if isinstance(r.get("session_id"), str) and r["session_id"].strip()} for p, _, _ in entries}
    ancestors = {}
    for eid in ids:
        chain, parent = [], registrations[eid]["parent"]
        while parent is not None:
            if parent not in ids or parent == eid or parent in chain:
                raise ValidationError("Invalid or cyclic revision lineage")
            chain.append(parent)
            parent = registrations[parent]["parent"]
        ancestors[eid] = chain
    reviews = []
    directory = confined(root, "reviews")
    for path in sorted(directory.iterdir()) if directory.exists() else []:
        event = load_json(confined(root, "reviews/" + path.name))
        rev = event.get("review", {})
        if path.name != suite_digest(rev) + ".json" or rev.get("entry_id") not in ids:
            raise ValidationError("Review identity or target changed")
        _review(rev, meta[rev["entry_id"]], ids)
        reviews.append(rev)
    rows = []
    for path, report, reg in entries:
        suite = load_json(path / "suite.json")
        m = meta[path.name]
        rr = [r for r in reviews if r["entry_id"] == path.name]
        inherited_reviews = [r for r in reviews if r["entry_id"] in ancestors[path.name]]
        descendants = sorted(eid for eid in ids if path.name in ancestors[eid])
        overlaps = sorted(eid for eid in ids if eid != path.name and sessions[eid] & sessions[path.name])
        unrelated_overlaps = sorted(set(overlaps) - set(ancestors[path.name]) - set(descendants))
        # A linked study is only a replication candidate. Show failures rather
        # than promoting arbitrary links or repeated sessions to replications.
        replication_checks = []
        for review in rr:
            replica = review["replication_entry_id"]
            if replica is None:
                continue
            rp, report2, reg2 = next(e for e in entries if e[0].name == replica)
            rs = load_json(rp / "suite.json")
            sessions_a = {r.get("session_id") for r in load_records(path / "runs.jsonl") if isinstance(r.get("session_id"), str)}
            sessions_b = {r.get("session_id") for r in load_records(rp / "runs.jsonl") if isinstance(r.get("session_id"), str)}
            reasons = []
            if reg2["cohort_sha256"] != reg["cohort_sha256"]:
                reasons.append("Different task, rules, engine, host or fixed conditions")
            if rs["plugin"] != suite["plugin"] or meta[replica]["plugin_sha256"] != m["plugin_sha256"] or rs["conditions"]["model"] != suite["conditions"]["model"]:
                reasons.append("Different plugin revision or model")
            if sessions_a & sessions_b:
                reasons.append("Reused sessions")
            if any(r["evidence_type"] == "synthetic" or not r["summary"]["comparison_eligible"] for r in (report, report2)):
                reasons.append("Synthetic or incomplete evidence")
            author_ids = {a["id"].strip().casefold() for a in m["authors"]}
            author_orgs = {a["organization"].strip().casefold() for a in m["authors"]}
            if any(a["id"].strip().casefold() in author_ids or a["organization"].strip().casefold() in author_orgs for a in meta[replica]["authors"]):
                reasons.append("Overlapping declared authors or organizations")
            replication_checks.append({"entry_id": replica, "status": "NOT_COMPARABLE" if reasons else "COMPARABLE_DECLARED_REPLICATION",
                                       "blockers": reasons, "authenticated_independence": False})
        disputed = any(r["verdict"] == "dispute" for r in rr)
        inherited_dispute = any(r["verdict"] == "dispute" for r in inherited_reviews)
        summary = report["summary"]
        eligible = (summary["comparison_eligible"] and report["evidence_type"] != "synthetic"
                    and not unrelated_overlaps and not descendants and not disputed and not inherited_dispute)
        rows.append({"entry_id": path.name, "study_id": suite["id"], "observed_at": m["observed_at"],
            "plugin": suite["plugin"], "plugin_sha256": m["plugin_sha256"], "model": suite["conditions"]["model"],
            "host": suite["conditions"]["host"], "cohort_sha256": reg["cohort_sha256"],
            "evidence_type": report["evidence_type"], "verdict": report["verdict"],
            "quality_delta": summary["quality_delta"], "cost_delta_usd": summary["cost_delta_usd"],
            "with_score": summary["with_score"], "without_score": summary["without_score"],
            "complete_pairs": summary["complete_pairs"], "expected_runs": summary["expected_runs"],
            "blockers": report["blockers"], "parent": reg["parent"], "overlapping_entries": overlaps,
            "unrelated_session_overlaps": unrelated_overlaps, "superseded_by": descendants,
            "lineage_root": ancestors[path.name][-1] if ancestors[path.name] else path.name,
            "ancestor_entries": ancestors[path.name], "ancestor_reviews": inherited_reviews,
            "revision_reason": reg.get("revision_reason"),
            "engine_sha256": reg["engine_sha256"], "replication_checks": replication_checks,
            "descriptive_comparison_eligible": eligible, "corpus_errors": report.get("corpus_errors"),
            "scientific_errors": report.get("scientific_errors"),
            "review_status": "DISPUTED" if disputed else "ANCESTOR_DISPUTED" if inherited_dispute else "REVIEWS_RECORDED" if rr else "UNREVIEWED",
            "reviews": rr, "independence": "DECLARED_NOT_VERIFIED"})
    rows.sort(key=lambda r: (_timestamp(r["observed_at"]), r["entry_id"]))
    changes = []
    for index, after in enumerate(rows):
        if after["superseded_by"]:
            continue
        candidates = [r for r in rows[:index] if r["cohort_sha256"] == after["cohort_sha256"]
                      and not r["superseded_by"] and r["lineage_root"] != after["lineage_root"]]
        if not candidates:
            continue
        before = candidates[-1]
        plugin_change = (before["plugin"]["version"], before["plugin_sha256"]) != (after["plugin"]["version"], after["plugin_sha256"])
        model_change = before["model"] != after["model"]
        eligible = before["descriptive_comparison_eligible"] and after["descriptive_comparison_eligible"] and not (plugin_change and model_change)
        changes.append({"before": before["entry_id"], "after": after["entry_id"],
            "axis": "combined" if plugin_change and model_change else "plugin" if plugin_change else "model" if model_change else "replicate",
            "quality_gain_change": after["quality_delta"] - before["quality_delta"] if eligible else None,
            "eligible": eligible, "interpretation": "Descriptive change only; no causal attribution or cross-study cost pooling"})
    return {"schema_version": 1, "entries": rows, "changes": changes,
        "counts": {"registered_studies": len(rows), "synthetic_studies": sum(r["evidence_type"] == "synthetic" for r in rows),
                   "study_lineages": len({r["lineage_root"] for r in rows}),
                   "evidence_revisions": sum(r["parent"] is not None for r in rows),
                   "declared_non_synthetic_studies": sum(r["evidence_type"] != "synthetic" for r in rows),
                   "review_events": len(reviews), "authenticated_independent_reviews": 0},
        "external_adoption": "NOT_ESTABLISHED", "scientific_authorization": "NONE", "claim_limit": LIMIT}


def export_entry(registry, entry_id, output):
    _digest(entry_id)
    source = confined(Path(registry).resolve(), "entries/" + entry_id)
    receipt = verify_bundle(source)
    if receipt["entry_id"] != entry_id:
        raise ValidationError("Entry digest changed")
    target = Path(output)
    if target.exists():
        raise ValidationError("Export destination exists")
    shutil.copytree(source, target)
    return {**verify_bundle(target), "review_history_included": False,
            "review_limit": "Study snapshot only; use --with-reviews to carry the current review history"}


def export_review_packet(registry, entry_id, output):
    """Freeze a local review snapshot without silently sharing unrelated studies."""
    _digest(entry_id)
    target = Path(output)
    if target.exists():
        raise ValidationError("Export destination exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    with _writer(registry) as root:
        view = registry_view(root)
        row = next((r for r in view["entries"] if r["entry_id"] == entry_id), None)
        if row is None:
            raise ValidationError("Unknown study entry")
        refs = [entry_id, *row["ancestor_entries"]]
        history = {"entry_id": entry_id, "captured_at": datetime.now(timezone.utc).isoformat(),
            "ancestors": row["ancestor_entries"], "reviews": row["reviews"] + row["ancestor_reviews"],
            "author_declarations": {eid: load_json(root / "entries" / eid / "metadata.json")["authors"] for eid in refs},
            "reported_session_overlaps": row["overlapping_entries"],
            "reported_superseded_by": row["superseded_by"],
            "scope": "Local snapshot at export time; ancestor studies and replication evidence are references only; future reviews are not included"}
        with tempfile.TemporaryDirectory(prefix=".review-export-", dir=target.parent) as tmp:
            stage = Path(tmp) / "packet"
            stage.mkdir()
            export_entry(root, entry_id, stage / "study")
            write_json(stage / "review-history.json", history)
            manifest = {"format": "pvl-review-packet-1", "entry_id": entry_id,
                "files": {p.relative_to(stage).as_posix(): sha(p) for p in sorted(stage.rglob("*")) if p.is_file()}}
            write_json(stage / "manifest.json", manifest)
            receipt = verify_review_packet(stage)
            stage.rename(target)
    return receipt


def verify_review_packet(directory):
    root = Path(directory).resolve()
    manifest = load_json(confined(root, "manifest.json"))
    if (not isinstance(manifest, dict) or set(manifest) != {"format", "entry_id", "files"}
            or manifest["format"] != "pvl-review-packet-1" or not isinstance(manifest["files"], dict)):
        raise ValidationError("Invalid review packet manifest")
    _digest(manifest["entry_id"])
    observed = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if observed != set(manifest["files"]) | {"manifest.json"}:
        raise ValidationError("Unexpected or missing review packet files")
    if not {"study/manifest.json", "review-history.json"} <= set(manifest["files"]):
        raise ValidationError("Review packet is incomplete")
    for name, digest in manifest["files"].items():
        if name != "review-history.json" and not name.startswith("study/"):
            raise ValidationError("Unexpected review packet member")
        if sha(confined(root, name)) != _digest(digest):
            raise ValidationError(f"Review packet content changed: {name}")
    study = verify_bundle(confined(root, "study"))
    if study["entry_id"] != manifest["entry_id"]:
        raise ValidationError("Review packet binds a different study")
    history = load_json(confined(root, "review-history.json"))
    fields = {"entry_id", "captured_at", "ancestors", "reviews", "author_declarations",
              "reported_session_overlaps", "reported_superseded_by", "scope"}
    if not isinstance(history, dict) or set(history) != fields or history["entry_id"] != study["entry_id"]:
        raise ValidationError("Invalid review history binding")
    _timestamp(history["captured_at"])
    for key in ("ancestors", "reported_session_overlaps", "reported_superseded_by"):
        if not isinstance(history[key], list):
            raise ValidationError("Review history references must be lists")
        for eid in history[key]:
            _digest(eid)
        if len(set(history[key])) != len(history[key]) or study["entry_id"] in history[key]:
            raise ValidationError("Invalid duplicate or self reference")
    bound = {study["entry_id"], *history["ancestors"]}
    if not isinstance(history["author_declarations"], dict) or set(history["author_declarations"]) != bound:
        raise ValidationError("Author declarations must cover review targets")
    metadata = load_json(root / "study/metadata.json")
    if history["author_declarations"][study["entry_id"]] != metadata["authors"]:
        raise ValidationError("Review author declarations disagree with the study")
    for authors in history["author_declarations"].values():
        _metadata({**metadata, "authors": authors})
    if not isinstance(history["reviews"], list):
        raise ValidationError("Reviews must be a list")
    seen = set()
    for review in history["reviews"]:
        if not isinstance(review, dict) or review.get("entry_id") not in bound:
            raise ValidationError("Review target outside packet history")
        rid = suite_digest(review)
        if rid in seen:
            raise ValidationError("Duplicate review in packet")
        seen.add(rid)
        allowed = set(bound)
        replica = review.get("replication_entry_id")
        if replica is not None:
            allowed.add(_digest(replica))
        _review(review, {"authors": history["author_declarations"][review["entry_id"]]}, allowed)
    direct_dispute = any(r["verdict"] == "dispute" and r["entry_id"] == study["entry_id"] for r in history["reviews"])
    prior_dispute = any(r["verdict"] == "dispute" and r["entry_id"] != study["entry_id"] for r in history["reviews"])
    return {"format": manifest["format"], "packet_id": suite_digest(manifest), "entry_id": study["entry_id"],
            "integrity": "CONSISTENT", "review_history_included": True, "review_events": len(seen),
            "review_status": "DISPUTED" if direct_dispute else "ANCESTOR_DISPUTED" if prior_dispute else "REVIEWS_RECORDED" if seen else "UNREVIEWED",
            "captured_at": history["captured_at"], "reference_evidence": "NOT_INCLUDED_OR_AUTHENTICATED",
            "claim_limit": LIMIT}


def verify_submission(directory, expected_id=None):
    manifest = load_json(confined(Path(directory).resolve(), "manifest.json"))
    result = verify_review_packet(directory) if isinstance(manifest, dict) and manifest.get("format") == "pvl-review-packet-1" else verify_bundle(directory)
    if expected_id is not None and _digest(expected_id) != result.get("packet_id", result["entry_id"]):
        raise ValidationError("Submission differs from the separately retained expected ID")
    return result


def replay_bundle(bundle, *, corpus_root=None, verifier_root=None):
    receipt = verify_submission(bundle)
    root = Path(bundle) / "study" if receipt["format"] == "pvl-review-packet-1" else Path(bundle)
    suite, records, lock = load_json(root / "suite.json"), load_records(root / "runs.jsonl"), load_json(root / "protocol.lock.json")
    ledger = load_json(root / "cost-ledger.json") if (root / "cost-ledger.json").exists() else None
    report = evaluate(suite, records, lock, ledger, artifact_root=root / "artifacts",
                      corpus_root=corpus_root, verifier_root=verifier_root)
    previous = load_json(root / "report.json")
    engine_same = load_json(root / "registration.json")["engine_sha256"] == engine_digest()
    matches = suite_digest(report) == suite_digest(previous)
    return {**receipt, "status": "REPRODUCED" if matches and engine_same else "REPLAY_DIFFERS",
            "same_engine": engine_same, "same_report": matches, "report": report,
            "scientific_replication": "NOT_ESTABLISHED"}


def write_view(registry, output):
    view = registry_view(registry)
    root = Path(output)
    if root.exists():
        raise ValidationError("Use a fresh registry report directory")
    root.mkdir(parents=True)
    write_json(root / "registry.json", view)
    esc = lambda x: html.escape("未知" if x is None else str(x))
    review_labels = {"DISPUTED": "存在异议", "ANCESTOR_DISPUTED": "前版存在异议", "REVIEWS_RECORDED": "已有复核记录", "UNREVIEWED": "尚未复核"}
    rows = "".join("<tr>" + "".join(f"<td>{esc(value)}</td>" for value in
        (r["study_id"], r["observed_at"], r["plugin"]["name"], r["plugin"]["version"], r["model"], r["host"],
         r["evidence_type"], r["quality_delta"], r["cost_delta_usd"],
         "已有后继修订" if r["superseded_by"] else "补证修订" if r["parent"] else "首次登记",
         review_labels[r["review_status"]], r["verdict"])) + "</tr>" for r in view["entries"])
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>科研插件边际价值登记表</title><style>body{font:16px system-ui;margin:32px;color:#173333;background:#f4f6f4}table{border-collapse:collapse;background:white}th,td{padding:10px;border:1px solid #ccc;text-align:left}pre{white-space:pre-wrap}h1{font-size:28px}</style><h1>科研插件边际价值登记表</h1><p>按插件、内容指纹、模型、宿主及固定研究条件保留历史。缺失、失败、异议和模拟记录均保留；未知成本不等于零。</p>'
    page += f'<p>{esc(LIMIT)}</p><p>研究历史：{view["counts"]["study_lineages"]}；评估快照：{len(view["entries"])}；补证修订：{view["counts"]["evidence_revisions"]}。这些数量不等于独立实测样本量。已认证独立复核：0；外部采用：尚未建立。</p><p><a href="registry.json">完整登记记录</a></p><table><tr>'
    page += ''.join(f'<th>{h}</th>' for h in ['研究', '观察时间', '插件', '版本', '模型', '宿主', '证据类型', '质量增益', '成本差额', '修订状态', '复核', '结论']) + '</tr>' + rows + '</table>'
    page += '<h2>补证与复核记录</h2>'
    for row in view["entries"]:
        page += '<details><summary>' + esc(row["study_id"]) + ' · ' + esc(row["entry_id"][:12]) + ' · ' + review_labels[row["review_status"]] + '</summary>'
        if row["revision_reason"]:
            page += '<p>补证说明：' + esc(row["revision_reason"]) + '</p>'
        if row["unrelated_session_overlaps"]:
            page += '<p>与其他研究或旁支共用会话，不能当作独立比较。</p>'
        for review in row["reviews"] + row["ancestor_reviews"]:
            label = '本版意见' if review["entry_id"] == row["entry_id"] else '前版意见（不代表已审阅本版）'
            page += '<p>' + label + ' · ' + esc(review["reviewer"]) + ' · ' + esc(review["verdict"]) + '：' + esc(review["rationale"]) + '</p>'
        if not row["reviews"] and not row["ancestor_reviews"]:
            page += '<p>尚未收到复核，不推断专家认可。</p>'
        page += '</details>'
    from .report import _corpus_error_html
    for row in view["entries"]:
        if row["corpus_errors"] or row.get("scientific_errors"):
            page += '<h2>' + esc(row["study_id"]) + '</h2>' + _corpus_error_html(row)
    page += '<h2>异议与可比条件</h2><p>复核意见绑定具体研究。所有原始判断和阻断保留。</p><details><summary>展开完整登记记录</summary><pre>' + esc(json.dumps(view, ensure_ascii=False, indent=2)) + '</pre></details></html>'
    (root / "index.html").write_text(page, encoding="utf-8")
    return {"files": [str(root / "registry.json"), str(root / "index.html")], "counts": view["counts"]}
