"""Link decision-benchmark evidence to a host study without merging evidence layers."""
from pathlib import Path

from .core import ValidationError, load_json, load_records, suite_digest
from .artifacts import sha


def link_evidence(study, decision_artifact, reference, evidence_type):
    """Opaque source bytes, not a guess about a different project's schema."""
    if evidence_type not in ("synthetic", "local", "external"):
        raise ValidationError("Declare the decision artifact evidence type")
    if not isinstance(reference, str) or not reference.strip():
        raise ValidationError("Provide a source reference")
    root = Path(study)
    suite, lock = load_json(root / "suite.json"), load_json(root / "protocol.lock.json")
    records = load_records(root / "runs.jsonl") if (root / "runs.jsonl").exists() else []
    if suite_digest(suite) != lock.get("suite_sha256"):
        raise ValidationError("Host study protocol changed")
    source = Path(decision_artifact)
    if not source.is_file() or source.is_symlink():
        raise ValidationError("Decision evidence must be an existing regular file")
    return {"schema_version": 1, "kind": "decision-host-evidence-link",
            "decision_layer": {"reference": reference, "sha256": sha(source),
                               "evidence_type": evidence_type, "interpretation": "OPAQUE_SOURCE_NOT_RESCORED"},
            "host_layer": {"suite_sha256": suite_digest(suite), "records_sha256": suite_digest(records),
                           "evidence_type": "synthetic" if any(r.get("source") == "synthetic" for r in records) else suite["evidence_type"],
                           "host": suite["conditions"]["host"], "observed_records": len(records)},
            "combined_value_verdict": None,
            "claim_limit": "Decision benchmarks and host execution are separate layers. Linking never establishes benefit, independent science, or cross-host replication."}
