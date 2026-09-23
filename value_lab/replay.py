"""Read-only replay preflight and material inventory. Never execute a verifier."""
import importlib.metadata
import platform
import sys

from .core import suite_digest


def replay_contract(suite, records, *, verifier_root=None, corpus_root=None, artifact_root=None):
    from .science import read_reference, reference_json, REFERENCE_FIELDS
    from .scenarios import validate_private
    materials, libraries, images = [], set(), set()
    outputs = {case["id"]: set() for case in suite["cases"]}
    backend_cases = set()

    def material(ref, kind, owner):
        row = {"kind": kind, "owner": owner, **ref, "status": "MISSING_OR_CHANGED"}
        try:
            read_reference(verifier_root, ref)
            row["status"] = "BYTES_MATCH"
        except (OSError, ValueError):
            pass
        materials.append(row)
        return row["status"] == "BYTES_MATCH"

    def rule(g, owner, case_id):
        spec = g.get("verifier", {})
        kind = g["type"]
        if "artifact" in g:
            outputs[case_id].add(g["artifact"])
        if kind == "backend_identity":
            backend_cases.add(case_id)
        if kind == "scenario":
            ref = {k: spec[k] for k in ("path", "sha256")}
            if material(ref, "private_scenario", owner):
                scenario_row = materials[-1]
                try:
                    private = reference_json(verifier_root, ref)
                    validate_private(private, spec["case_id"], spec["evidence_type"])
                    for child in private["graders"]:
                        rule(child, owner + "/" + child["id"], case_id)
                except (OSError, ValueError):
                    scenario_row["status"] = "INVALID_PRIVATE_CONTRACT"
            else:
                materials.append({"kind": "undiscovered_private_dependencies", "owner": owner, "status": "UNKNOWN"})
        elif kind == "executable":
            material({k: spec[k] for k in ("path", "sha256")}, "trusted_python", owner)
        else:
            for field in REFERENCE_FIELDS:
                if field in spec:
                    material(spec[field], field, owner)
            if kind == "exec":
                images.add(spec["image"])
            if kind == "artifact" and spec.get("kind") == "h5ad":
                libraries.update(("anndata", "numpy", "scipy", "h5py"))

    for case in suite["cases"]:
        for g in case["graders"]:
            rule(g, case["id"] + "/" + g["id"], case["id"])
    for i, record in enumerate(records):
        for artifact_id in sorted(outputs.get(record.get("case_id"), set())):
            refs = record.get("artifacts", {})
            ref = refs.get(artifact_id) if isinstance(refs, dict) else None
            row = {"kind": "output_artifact", "owner": f"record/{i}/{artifact_id}", "status": "MISSING_OR_CHANGED"}
            if isinstance(ref, dict) and set(ref) == {"path", "sha256"}:
                row.update(ref)
                try:
                    read_reference(artifact_root, ref)
                    row["status"] = "BYTES_MATCH"
                except (OSError, ValueError):
                    pass
            materials.append(row)
        ref = record.get("backend_receipt")
        if isinstance(ref, dict) and set(ref) == {"path", "sha256"}:
            material(ref, "backend_receipt", "record/" + str(i))
        elif record.get("case_id") in backend_cases:
            materials.append({"kind": "backend_receipt", "owner": "record/" + str(i), "status": "MISSING_OR_CHANGED"})
    if suite.get("corpus") is not None:
        row = {"kind": "private_corpus", "owner": "suite", "commitment": suite["corpus"], "status": "MISSING_OR_CHANGED"}
        try:
            from .corpus import load_material
            from .core import load_json
            from pathlib import Path
            if corpus_root is not None:
                load_material(corpus_root)
                public = load_json(Path(corpus_root) / "corpus.json")
                truth = load_json(Path(corpus_root) / "answers.private.json")
                if suite["corpus"] == {"release_sha256": suite_digest(public), "truth_sha256": suite_digest(truth)}:
                    row["status"] = "BYTES_MATCH"
        except (OSError, ValueError):
            pass
        materials.append(row)
    versions = {}
    for name in sorted(libraries):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    runtime = {"python": platform.python_version(), "implementation": sys.implementation.name,
               "system": platform.system(), "machine": platform.machine(), "libraries": versions,
               "container_images": sorted(images)}
    return {"format": "pvl-replay-contract-1", "runtime": runtime, "materials": materials,
            "material_bytes_ready": all(r["status"] == "BYTES_MATCH" for r in materials),
            "required_packages_present": all(v is not None for v in versions.values()),
            "verifier_execution": False,
            "limits": "Package versions are inventory, not import/execution proof. Container availability is not checked. "
            "Private scorers and truth remain separate and are never copied automatically. Matching bytes does not authenticate their author."}


def report_changes(before, after):
    """Bounded field-path diagnostics; distinguish absent fields from JSON null."""
    paths = []
    def walk(a, b, path):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(a.keys() | b.keys()):
                child = path + "/" + str(k).replace("~", "~0").replace("/", "~1")
                if k not in a or k not in b:
                    paths.append(child)
                else:
                    walk(a[k], b[k], child)
        elif suite_digest(a) != suite_digest(b):
            paths.append(path or "/")
    walk(before, after, "")
    return {"changed_field_count": len(paths), "paths": paths[:200], "truncated": len(paths) > 200}


def plan_replay(bundle, *, corpus_root=None, verifier_root=None, expected_id=None):
    from pathlib import Path
    from .core import load_json, load_records, validate_suite
    from .registry import verify_submission, engine_digest
    receipt = verify_submission(bundle, expected_id)
    root = Path(bundle) / "study" if receipt["format"] == "pvl-review-packet-1" else Path(bundle)
    suite = load_json(root / "suite.json")
    validate_suite(suite)
    contract = replay_contract(suite, load_records(root / "runs.jsonl"), artifact_root=root / "artifacts",
                               verifier_root=verifier_root, corpus_root=corpus_root)
    previous = load_json(root / "replay-contract.json") if (root / "replay-contract.json").exists() else None
    same_runtime = suite_digest(previous["runtime"]) == suite_digest(contract["runtime"]) if previous else None
    return {**receipt, "contract": contract, "same_runtime": same_runtime,
            "runtime_changes": report_changes(previous["runtime"], contract["runtime"]) if previous else None,
            "same_engine": load_json(root / "registration.json")["engine_sha256"] == engine_digest(),
            "status": "MATERIALS_READY" if contract["material_bytes_ready"] and contract["required_packages_present"] else "MATERIALS_REQUIRED",
            "model_calls": 0, "verifier_execution": False}
