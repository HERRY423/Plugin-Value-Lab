"""Explicit, local researcher/agent workflow over the durable decision ledger.

This executes PVL's object-only evaluator, not models or scientific programs.
Actor labels are declarations, not authentication or human acceptance evidence.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import platform
import re
import tempfile

from .artifacts import confined, read_only_verification
from .collaboration_state import actor, require
from .core import ValidationError, evaluate
from .decision_store import DecisionStore

ARGUMENTS = {
    "open": {"inputs"}, "status": set(), "result": set(), "execute": {"attempt_id", "reason"},
    "review": {"review_id", "attempt_id", "result_sha256", "verdict", "notes"},
    "correct": {"review_id", "inputs", "reason"},
    "handoff": {"handoff_id", "recipient", "note"}, "receive": {"handoff_id"},
    "cancel_handoff": {"handoff_id", "reason"}, "resolve": {"attempt_id", "reason"},
    "export": {"directory"}, "restore": {"directory", "checkpoint"},
}


def implementation_identity():
    """Fingerprint all local evaluator modules, including uncommitted changes."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return "pvl-python-tree-sha256:" + digest.hexdigest() + ";python:" + platform.python_version()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def capture_inputs(suite, records, lock=None, cost_ledger=None, *, artifact_root=None):
    """Capture only explicitly referenced small artifacts; do not read arbitrary trees.

    Missing files remain missing and digest mismatches remain mismatches for the
    evaluator. Do not repair their declared hashes or replace failed records.
    """
    from .collaboration_state import inputs
    material = {"suite": suite, "records": records, "lock": lock, "cost_ledger": cost_ledger}
    if artifact_root is not None:
        files = {}
        size = 0
        for record in records:
            for reference in record.get("artifacts", {}).values():
                name = reference["path"]
                if name in files:
                    continue
                path = confined(artifact_root, name)
                if not path.exists():
                    continue
                require(path.is_file() and path.stat().st_size <= 6 * 1024**2, "Artifact too large for local handoff")
                data = path.read_bytes()
                size += len(data)
                require(size <= 6 * 1024**2, "Use an external artifact store for larger material")
                files[name] = base64.b64encode(data).decode("ascii")
        material["artifact_files"] = files
    return inputs(material)


def response(store, *, replayed=False, full_result=False):
    snap = store.snapshot()
    require("collaboration" in snap, "This is not a collaboration task")
    result = None
    attempt_id = snap["collaboration_status"]["latest_attempt"]
    if attempt_id:
        digest = snap["attempts"][attempt_id]["artifacts"].get("result")
        if digest:
            with store._connect() as db:
                data = db.execute("SELECT data FROM blobs WHERE digest=?", (digest,)).fetchone()
            require(data is not None and hashlib.sha256(data[0]).hexdigest() == digest, "Result bytes changed")
            result = json.loads(data[0])
            if "report" in result and not full_result:
                report = result.pop("report")
                result["report_summary"] = {k: report.get(k) for k in ("verdict", "summary", "blockers", "warnings", "provenance")}
                result["full_report_action"] = "result"
    return {"format": "pvl-collaboration-response-1", "sequence": snap["sequence"],
            "checkpoint": snap["checkpoint"], "replayed": replayed,
            "status": snap["collaboration_status"], "result": result,
            "result_sha256": snap["attempts"][attempt_id]["artifacts"].get("result") if attempt_id else None}


def dispatch(root, task_id, action, arguments=None, *, who, key=None, expected_sequence=None):
    """One fixed local root and actor are supplied by the caller/host.

    Writes use compare-and-swap and stable request keys. A repeated execute
    request only reads its retained outcome; it never dispatches again.
    """
    root = Path(root)
    require(root.is_absolute() and root.is_dir() and root.resolve() == root,
            "Use an existing absolute, canonical collaboration root")
    require(isinstance(task_id, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", task_id),
            "Task id must contain only letters, numbers, hyphens or underscores")
    who = actor(who)
    arguments = {} if arguments is None else arguments
    require(action in ARGUMENTS and isinstance(arguments, dict) and set(arguments) == ARGUMENTS[action],
            "Invalid action arguments")
    path = confined(root, task_id + ".sqlite")
    # SQLite auxiliary paths must not redirect writes outside the authorized root.
    for suffix in ("-journal", "-wal", "-shm"):
        confined(root, task_id + ".sqlite" + suffix)
    store = DecisionStore(path)
    if action in ("status", "result"):
        return response(store, full_result=action == "result")
    if action == "export":
        directory = confined(root, arguments["directory"])
        require(directory != path and not path.is_relative_to(directory), "Export must be separate from store")
        # Export's transaction pins the bundle. Return its own checkpoint, not
        # a later snapshot that could accidentally be ahead of the bundle.
        store.snapshot()  # Explicitly fail missing tasks; no creation on read.
        store.export(directory, resume=True)
        saved = json.loads((directory / "decision.json").read_bytes())
        require("collaboration" in saved, "Not a collaboration bundle")
        return {"directory": arguments["directory"],
                "checkpoint": json.loads((directory / "checkpoint.json").read_bytes()),
                "status": saved["collaboration_status"], "execution_performed": False}
    if action == "restore":
        require(arguments["checkpoint"] is not None, "Restore requires a separately retained checkpoint")
        directory = confined(root, arguments["directory"])
        # Do not import a legacy task into the collaboration namespace.
        from .delivery import read_bundle
        read_bundle(directory)
        saved = json.loads((directory / "decision.json").read_bytes())
        require("collaboration" in saved, "Not a collaboration bundle")
        restored = store.restore(directory, checkpoint=arguments["checkpoint"])
        return {**response(store, replayed=restored["replayed"]), "execution_performed": False}
    require(isinstance(key, str) and 0 < len(key.strip()) <= 180, "Supply a stable request key (1-180 characters)")
    require(type(expected_sequence) is int and expected_sequence >= 0, "Supply the last read sequence")
    payload = {"actor": who, **arguments}
    if action == "open":
        payload["require_human_review"] = True
    if action != "execute":
        appended = store.append("collab_" + action, payload, key=key, expected_sequence=expected_sequence)
        return response(store, replayed=appended["replayed"])
    identity = implementation_identity()
    started = store.append("collab_start", {**payload, "implementation": identity},
                           key=key + ":start", expected_sequence=expected_sequence)
    if started["replayed"]:
        return {**response(store, replayed=True), "execution_performed": False}
    material = started["collaboration"]["revisions"][-1]["inputs"]
    try:
        with tempfile.TemporaryDirectory(prefix="pvl-retained-", dir=root) as directory, read_only_verification():
            retained = material.get("artifact_files", {})
            for name, encoded in retained.items():
                target = confined(directory, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(base64.b64decode(encoded, validate=True))
            report = evaluate(**{k: material[k] for k in ("suite", "records", "lock", "cost_ledger")},
                              artifact_root=directory if "artifact_files" in material else None)
        result = {"format": "pvl-collaboration-result-1", "report": report,
                  "execution_kind": "LOCAL_EVALUATION_OF_SUBMITTED_RECORDS",
                  "new_observations": 0, "implementation": identity,
                  "inputs_sha256": started["collaboration_status"]["inputs_sha256"],
                  "post_review_revision": started["collaboration_status"]["post_review_revision"]}
        status = "COLLECTED"
    except Exception as exc:
        # Retain failures as evidence. KeyboardInterrupt/process death leaves
        # the committed start unresolved, requiring explicit recovery.
        result = {"format": "pvl-collaboration-result-1", "error_type": type(exc).__name__,
                  "error": str(exc), "implementation": identity, "new_observations": 0,
                  "execution_kind": "LOCAL_EVALUATION_FAILED",
                  "inputs_sha256": started["collaboration_status"]["inputs_sha256"]}
        status = "FAILED"
    finished = store.append("collab_finish", {"actor": who, "attempt_id": arguments["attempt_id"],
        "status": status, "receipt": {"source": "pvl.collaboration.evaluate", "implementation": identity,
                                    "external_calls": 0}, "artifacts": {}},
        key=key + ":finish", expected_sequence=started["sequence"], files={"result": encode(result)})
    return {**response(store, replayed=finished["replayed"]), "execution_performed": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Existing local collaboration directory")
    parser.add_argument("--actor", required=True, help="Declared actor identifier (not authenticated)")
    parser.add_argument("--kind", choices=("agent", "human"), default="agent")
    parser.add_argument("--request", required=True, help="JSON file: task_id, action, arguments, key, expected_sequence")
    args = parser.parse_args(argv)
    try:
        request = json.loads(Path(args.request).read_text(encoding="utf-8-sig"))
        require(isinstance(request, dict) and {"task_id", "action"} <= set(request)
                <= {"task_id", "action", "arguments", "key", "expected_sequence"}, "Invalid request envelope")
        result = dispatch(args.root, **request, who={"id": args.actor, "kind": args.kind})
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except (ValidationError, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
