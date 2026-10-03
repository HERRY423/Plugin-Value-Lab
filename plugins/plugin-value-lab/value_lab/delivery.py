"""Publish complete local bundles; incomplete attempts are retained, never read as results."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .core import ValidationError, suite_digest

FORMAT = "pvl-delivery-1"


def _member(name):
    return isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name) is not None and name != "COMMITTED.json"


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _write(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def read_bundle(output):
    """Verify all delivered bytes before returning a committed manifest."""
    output = Path(output)
    try:
        manifest = json.loads((output / "COMMITTED.json").read_bytes())
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or not isinstance(manifest.get("files"), dict) or not manifest["files"]:
            raise ValueError("Unsupported/empty manifest")
        for name, digest in manifest["files"].items():
            if not _member(name):
                raise ValueError("Invalid bundle member")
            path = output / name
            if path.is_symlink() or _hash(path.read_bytes()) != digest:
                raise ValueError("Bundle bytes changed: " + name)
        if suite_digest(manifest["files"]) != manifest["request_sha256"]:
            raise ValueError("Manifest binding changed")
        return manifest
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValidationError("Uncommitted or damaged delivery: " + str(output)) from exc


def publish_bundle(output, files, *, resume=False):
    """Same bytes replay the committed delivery. Explicit resume retains failed staging.

    Publication is a same-filesystem directory rename. This is local crash recovery,
    not a distributed transaction or a guarantee against hardware/filesystem loss.
    """
    output = Path(output).absolute()
    if not files or any(not _member(n) for n in files):
        raise ValidationError("Bundle members must be plain filenames")
    expected = {name: _hash(data) for name, data in sorted(files.items())}
    digest = suite_digest(expected)

    def completed():
        manifest = read_bundle(output)
        if manifest["request_sha256"] != digest:
            raise ValidationError("Preserve old evidence; output belongs to a different request")
        return {"status": "COMMITTED", "request_sha256": digest, "output": str(output)}

    if output.exists():
        return completed()
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = "." + output.name + ".pvl-" + digest + "-"
    pending = sorted(p for p in output.parent.iterdir() if p.name.startswith(prefix) and p.is_dir())
    if pending and not resume:
        return {"status": "INCOMPLETE", "request_sha256": digest,
                "pending": [str(p) for p in pending], "output": None}
    stage = Path(tempfile.mkdtemp(prefix=prefix, dir=output.parent))
    # Every attempt has a unique staging directory; no failed bytes are overwritten.
    for name, data in files.items():
        _write(stage / name, data)
    manifest = {"format": FORMAT, "request_sha256": digest, "files": expected}
    _write(stage / "COMMITTED.json", (json.dumps(manifest, sort_keys=True) + "\n").encode())
    read_bundle(stage)
    try:
        stage.rename(output)
    except OSError:
        # Another writer may have committed this same logical request first.
        if output.exists():
            return completed()
        raise
    return completed()
