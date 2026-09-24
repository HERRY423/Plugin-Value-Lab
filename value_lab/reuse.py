"""Registry-free, offline handoffs. A replay never becomes a new observation.

Only built-in, non-executing graders are allowed. Scorer material is a separate,
explicit export. No source program, model, network or plugin installation runs.
"""
from pathlib import Path
import json
import shutil
import tempfile
from datetime import datetime, timezone

from .artifacts import MAX_BYTES, confined, sha
from .core import ValidationError, evaluate, load_json, load_records, suite_digest, write_json, validate_suite
from .registry import engine_digest
from .replay import replay_contract, report_changes

FORMAT = "pvl-reuse-package-1"


def _safe_rules(suite, verifier_root):
    from .science import reference_json
    from .scenarios import validate_private
    validate_suite(suite)
    if suite.get("corpus") is not None:
        raise ValidationError("Sealed corpora require the existing registry replay path; this handoff supports explicit references only")
    def visit(grader):
        if grader["type"] in ("executable", "exec", "sealed"):
            raise ValidationError("Reuse replay never executes supplied programs or sealed keys")
        if grader["type"] == "scenario":
            spec = grader["verifier"]
            try:
                private = reference_json(verifier_root, {k: spec[k] for k in ("path", "sha256")})
            except OSError:
                return  # Unavailable bytes cannot execute; evaluation retains unknown grades.
            validate_private(private, spec["case_id"], spec["evidence_type"])
            for rule in private["graders"]:
                visit(rule)
    for case in suite["cases"]:
        for grader in case["graders"]:
            visit(grader)


def _fresh(output, sources):
    output = Path(output).resolve()
    if output.exists():
        raise ValidationError("Choose a new handoff/replay directory; preserve original evidence")
    for source in sources:
        if source is not None:
            source = Path(source).resolve()
            if source == output or output.is_relative_to(source) or source.is_relative_to(output):
                raise ValidationError("Handoff output and source roots must be disjoint")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def prepare_reuse(study, output, *, artifact_root=None, verifier_root=None):
    study = Path(study).resolve()
    output = _fresh(output, (study, artifact_root, verifier_root))
    suite = load_json(study / "suite.json")
    records = load_records(study / "runs.jsonl")
    lock = load_json(study / "protocol.lock.json")
    ledger = load_json(study / "cost-ledger.json") if (study / "cost-ledger.json").exists() else None
    if not isinstance(lock, dict) or lock.get("suite_sha256") != suite_digest(suite):
        raise ValidationError("Handoff requires the unchanged protocol lock")
    _safe_rules(suite, verifier_root)
    artifacts = Path(artifact_root) if artifact_root is not None else study
    with tempfile.TemporaryDirectory(prefix=".reuse-", dir=output.parent) as temp:
        dest = Path(temp) / "package"
        dest.mkdir()
        write_json(dest / "suite.json", suite)
        write_json(dest / "protocol.lock.json", lock)
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
                source = confined(artifacts, ref["path"])
                if verifier_root is not None and source.is_relative_to(Path(verifier_root).resolve()):
                    raise ValidationError("Scorer-only material cannot be exported as an agent artifact")
                if source.is_file() and source.stat().st_size <= MAX_BYTES and sha(source) == ref["sha256"]:
                    target = confined(dest / "artifacts", ref["path"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
        report = evaluate(suite, records, lock, ledger, artifact_root=dest / "artifacts", verifier_root=verifier_root)
        contract = replay_contract(suite, records, artifact_root=dest / "artifacts", verifier_root=verifier_root)
        write_json(dest / "report.json", report)
        write_json(dest / "dependencies.json", contract)
        write_json(dest / "identity.json", {"engine_sha256": engine_digest(), "suite_sha256": suite_digest(suite),
                   "records_sha256": suite_digest(records), "observation_set_sha256": suite_digest({"suite": suite, "records": records}),
                   "evidence_type": report["evidence_type"], "scientific_replication": "NOT_ESTABLISHED"})
        (dest / "HANDOFF.md").write_text(
            "# Offline reuse package\n\nReview these local materials before sharing. Nothing has been uploaded.\n\n"
            "Use the separately retained package ID with `reuse-replay PACKAGE --expected-id ID --output NEW_DIRECTORY`. "
            "Pass a separately delivered scorer root with `--verifiers` where required. "
            "`reuse-scorers` explicitly exports only referenced scorer bytes to a separate directory.\n\n"
            "Replay recomputes these same observations. It is not a fresh host run, an independent sample, scientific replication or adoption. "
            "Changed engine/runtime, missing material, differences and failures remain visible. "
            "Executable graders are not supported. References must not be staged in an agent workspace.\n", encoding="utf-8")
        manifest = {"format": FORMAT, "files": {p.relative_to(dest).as_posix(): sha(p) for p in sorted(dest.rglob("*")) if p.is_file()}}
        write_json(dest / "manifest.json", manifest)
        package_id = suite_digest(manifest)
        verify_reuse(dest, package_id)
        dest.rename(output)
    return {"package_id": package_id, "output": str(output), "reference_materials_included": False,
            "assessment_complete": not report["blockers"], "model_calls": 0, "published": False}


def verify_reuse(package, expected_id):
    root = Path(package).resolve()
    manifest = load_json(confined(root, "manifest.json"))
    if not isinstance(manifest, dict) or set(manifest) != {"format", "files"} or manifest["format"] != FORMAT or not isinstance(manifest["files"], dict):
        raise ValidationError("Invalid reuse manifest")
    if suite_digest(manifest) != expected_id:
        raise ValidationError("Reuse package differs from separately retained expected ID")
    required = {"suite.json", "runs.jsonl", "protocol.lock.json", "report.json", "dependencies.json", "identity.json", "HANDOFF.md"}
    if not required <= manifest["files"].keys():
        raise ValidationError("Incomplete reuse manifest")
    observed = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if observed != set(manifest["files"]) | {"manifest.json"}:
        raise ValidationError("Reuse package contains missing or unlisted files")
    for name, digest in manifest["files"].items():
        path = confined(root, name)
        if not path.is_file() or path.stat().st_size > MAX_BYTES or sha(path) != digest:
            raise ValidationError("Reuse bytes missing, oversized or changed: " + name)
    suite, records = load_json(root / "suite.json"), load_records(root / "runs.jsonl")
    identity = load_json(root / "identity.json")
    if not isinstance(identity, dict) or not {"suite_sha256", "records_sha256", "observation_set_sha256", "engine_sha256"} <= identity.keys():
        raise ValidationError("Incomplete observation identity")
    if (identity["suite_sha256"] != suite_digest(suite) or identity["records_sha256"] != suite_digest(records)
            or identity["observation_set_sha256"] != suite_digest({"suite": suite, "records": records})):
        raise ValidationError("Observation identity differs from package material")
    return {"package_id": expected_id, "integrity": "BYTES_MATCH", "observation_set_sha256": identity["observation_set_sha256"]}


def export_scorers(package, expected_id, verifier_root, output):
    from .science import read_reference
    verify_reuse(package, expected_id)
    root = Path(package)
    _safe_rules(load_json(root / "suite.json"), verifier_root)
    output = _fresh(output, (package, verifier_root))
    refs = {}
    for row in load_json(root / "dependencies.json")["materials"]:
        if row["kind"] == "output_artifact" or "path" not in row or "sha256" not in row:
            continue
        if row["path"] in refs and refs[row["path"]] != row["sha256"]:
            raise ValidationError("Conflicting scorer reference paths")
        refs[row["path"]] = row["sha256"]
    with tempfile.TemporaryDirectory(prefix=".scorers-", dir=output.parent) as temp:
        stage = Path(temp) / "scorers"
        stage.mkdir()
        for name, digest in refs.items():
            raw = read_reference(verifier_root, {"path": name, "sha256": digest})
            target = confined(stage, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        stage.rename(output)
    return {"package_id": expected_id, "files": refs, "output": str(output), "agent_staging_allowed": False,
            "isolation": "SEPARATE_DIRECTORIES_ONLY", "published": False}


def replay_reuse(package, expected_id, output, *, verifier_root=None, participant=None):
    receipt = verify_reuse(package, expected_id)
    root = Path(package)
    output = _fresh(output, (package, verifier_root))
    suite, records = load_json(root / "suite.json"), load_records(root / "runs.jsonl")
    _safe_rules(suite, verifier_root)
    if participant is not None:
        if not isinstance(participant, dict) or set(participant) != {"operator", "relationship", "feedback"}:
            raise ValidationError("Participant needs operator, relationship and actual feedback")
        if not isinstance(participant["operator"], str) or not participant["operator"].strip() or participant["relationship"] not in ("same_team", "self_reported_external", "unknown"):
            raise ValidationError("Invalid declared participant; identity is not authenticated")
        if not isinstance(participant["feedback"], str):
            raise ValidationError("Feedback must be the participant's actual text")
    lock = load_json(root / "protocol.lock.json")
    ledger = load_json(root / "cost-ledger.json") if (root / "cost-ledger.json").exists() else None
    report = evaluate(suite, records, lock, ledger, artifact_root=root / "artifacts", verifier_root=verifier_root)
    current = replay_contract(suite, records, artifact_root=root / "artifacts", verifier_root=verifier_root)
    original, identity = load_json(root / "report.json"), load_json(root / "identity.json")
    same_report = suite_digest(original) == suite_digest(report)
    same_engine = identity["engine_sha256"] == engine_digest()
    same_runtime = suite_digest(current["runtime"]) == suite_digest(load_json(root / "dependencies.json")["runtime"])
    ready = current["material_bytes_ready"] and current["required_packages_present"]
    status = "MATERIALS_REQUIRED" if not ready else "REPRODUCED" if same_report and same_engine and same_runtime else "REPLAY_DIFFERS"
    result = {"format": "pvl-reuse-receipt-1", **receipt, "status": status,
              "same_report": same_report, "same_engine": same_engine, "same_runtime": same_runtime,
              "assessment_complete": not report["blockers"], "differences": report_changes(original, report),
              "engine_sha256": engine_digest(), "runtime": current["runtime"], "replayed_at": datetime.now(timezone.utc).isoformat(),
              "report_sha256": suite_digest(report), "participant": participant,
              "independent_reuse": "SELF_REPORTED_NOT_AUTHENTICATED" if participant and participant["relationship"] == "self_reported_external" else "NOT_ESTABLISHED",
              "new_observations": 0, "new_independent_samples": 0, "model_calls": 0,
              "scientific_replication": "NOT_ESTABLISHED", "scope": "Regraded the same observations; no fresh model study or authenticated adoption"}
    output.mkdir()
    write_json(output / "report.json", report)
    write_json(output / "receipt.json", result)
    write_json(output / "dependencies.json", current)
    return result


def inspect_receipt(package, expected_id, replay_directory):
    """Read an actual received replay result, preserving claims without certifying them."""
    checked = verify_reuse(package, expected_id)
    root = Path(replay_directory)
    receipt = load_json(confined(root, "receipt.json"))
    report = load_json(confined(root, "report.json"))
    dependencies = load_json(confined(root, "dependencies.json"))
    original = load_json(Path(package) / "report.json")
    identity = load_json(Path(package) / "identity.json")
    previous = load_json(Path(package) / "dependencies.json")
    if (not isinstance(receipt, dict) or receipt.get("format") != "pvl-reuse-receipt-1"
            or receipt.get("package_id") != expected_id or receipt.get("observation_set_sha256") != checked["observation_set_sha256"]
            or receipt.get("report_sha256") != suite_digest(report)):
        raise ValidationError("Received receipt does not bind the supplied package and report")
    same_report = suite_digest(report) == suite_digest(original)
    same_engine = receipt.get("engine_sha256") == identity["engine_sha256"]
    same_runtime = suite_digest(dependencies.get("runtime")) == suite_digest(previous["runtime"])
    ready = dependencies.get("material_bytes_ready") is True and dependencies.get("required_packages_present") is True
    status = "MATERIALS_REQUIRED" if not ready else "REPRODUCED" if same_report and same_engine and same_runtime else "REPLAY_DIFFERS"
    for key, expected in (("same_report", same_report), ("same_engine", same_engine), ("same_runtime", same_runtime), ("status", status),
                          ("new_observations", 0), ("new_independent_samples", 0), ("model_calls", 0)):
        if type(receipt.get(key)) is not type(expected) or receipt[key] != expected:
            raise ValidationError("Received replay misstates " + key)
    if suite_digest(receipt.get("runtime")) != suite_digest(dependencies.get("runtime")):
        raise ValidationError("Received runtime contradicts its dependency inventory")
    return {**checked, "receipt_integrity": "INTERNALLY_CONSISTENT", "reported_replay_status": status,
            "participant": receipt.get("participant"), "new_observations": 0, "new_independent_samples": 0,
            "participant_authenticated": False, "execution_authenticated": False, "independent_reuse": "NOT_ESTABLISHED",
            "scope": "Received declarations and artifacts are consistent; independently rerun to check computation, independently establish participant identity"}
