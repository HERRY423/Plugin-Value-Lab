"""Opt-in artifact verification. Never execute code embedded in model output."""
from __future__ import annotations

import csv
import hashlib
import io
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

from .core import ValidationError, load_json, suite_digest

KINDS = {"artifact", "executable", "artifact_schema", "numeric_tolerance", "abstention_correct", "over_refusal", "backend_identity", "exec", "replicate_effect"}
MAX_BYTES = 64 * 1024 * 1024


def confined(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValidationError("Artifact paths must be relative POSIX paths")
    part = PurePosixPath(relative)
    if part.is_absolute() or any(p in (".", "..", "") for p in relative.split("/")):
        raise ValidationError("Artifact path escapes root")
    root = Path(root).resolve()
    path = root.joinpath(*part.parts)
    for candidate in [path, *path.parents]:
        if candidate == root:
            break
        if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
            raise ValidationError("Linked artifacts are not accepted")
    if not path.resolve().is_relative_to(root):
        raise ValidationError("Artifact path escapes root")
    return path


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_verifier(g):
    if not isinstance(g.get("artifact"), str) or not re.fullmatch(r"[A-Za-z0-9_-]+", g["artifact"]):
        raise ValidationError("artifact must name an artifact ID")
    spec = g.get("verifier")
    if not isinstance(spec, dict):
        raise ValidationError("verifier must be an object")
    from .science import KINDS as SCIENCE_KINDS, validate_spec
    if g["type"] in SCIENCE_KINDS:
        validate_spec(g["type"], spec)
        return
    if g["type"] == "executable":
        if set(spec) != {"path", "sha256", "timeout_seconds"}:
            raise ValidationError("Executable verifier needs path, sha256, timeout_seconds")
        confined(Path.cwd(), spec["path"])
        if not spec["path"].endswith(".py") or not re.fullmatch(r"[a-f0-9]{64}", str(spec["sha256"])):
            raise ValidationError("Executable verifier must be a SHA-256 pinned Python file")
        if type(spec["timeout_seconds"]) is not int or not 1 <= spec["timeout_seconds"] <= 60:
            raise ValidationError("Verifier timeout must be 1..60 seconds")
        return
    kind = spec.get("kind")
    fields = {
        "json_fields": {"kind", "expected"},
        "de_table": {"kind", "id_column", "p_column", "q_column", "effect_column", "min_rows", "bh_tolerance"},
        "labels": {"kind", "id_column", "label_column", "expected"},
        "h5ad": {"kind", "n_obs", "n_vars", "obs_columns", "var_names_unique"},
    }
    optional = {"testing_family"} if kind == "de_table" else set()
    if kind not in fields or set(spec) - optional != fields[kind]:
        raise ValidationError("Unsupported or incomplete artifact verifier contract")
    if "testing_family" in spec:
        from .science import reference
        reference(spec["testing_family"])
    if kind in ("json_fields", "labels") and (not isinstance(spec["expected"], dict) or not spec["expected"]):
        raise ValidationError("Expected values must be a nonempty mapping")
    if kind == "json_fields" and any(not isinstance(k, str) or not k or any(not p for p in k.split(".")) for k in spec["expected"]):
        raise ValidationError("Expected JSON paths must be nonempty")
    for key in ("id_column", "p_column", "q_column", "effect_column", "label_column"):
        if key in spec and (not isinstance(spec[key], str) or not spec[key].strip()):
            raise ValidationError("Table columns must be named")
    columns = [spec[k] for k in ("id_column", "p_column", "q_column", "effect_column", "label_column") if k in spec]
    if len(set(columns)) != len(columns):
        raise ValidationError("Verifier columns must be distinct")
    if kind == "de_table":
        if type(spec["min_rows"]) is not int or spec["min_rows"] < 1:
            raise ValidationError("min_rows must be positive")
        tolerance = spec["bh_tolerance"]
        if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or not 0 <= tolerance <= .01:
            raise ValidationError("BH tolerance must be finite and in 0..0.01")
    if kind == "labels" and any(not isinstance(k, str) or not k or not isinstance(v, str) or not v for k, v in spec["expected"].items()):
        raise ValidationError("Expected labels require nonempty string IDs and labels")
    if kind == "h5ad":
        if any(type(spec[k]) is not int or spec[k] <= 0 for k in ("n_obs", "n_vars")):
            raise ValidationError("h5ad dimensions must be positive integers")
        if not isinstance(spec["obs_columns"], list) or any(not isinstance(c, str) or not c for c in spec["obs_columns"]) or type(spec["var_names_unique"]) is not bool:
            raise ValidationError("Invalid h5ad observation contract")
    suite_digest(spec)


def _table(path):
    reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig")), delimiter="\t" if path.suffix == ".tsv" else ",")
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("Missing or duplicate columns")
    rows = list(reader)
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError("Empty or malformed table")
    return rows


def _builtin(path, spec, verifier_root=None):
    kind = spec["kind"]
    if kind == "json_fields":
        obj = load_json(path)
        for dotted, expected in spec["expected"].items():
            value = obj
            for key in dotted.split("."):
                value = value[int(key)] if isinstance(value, list) else value[key]
            if suite_digest(value) != suite_digest(expected):
                return False, "JSON artifact field mismatch: " + dotted
    elif kind in ("de_table", "labels"):
        rows = _table(path)
        ids = [row[spec["id_column"]] for row in rows]
        if any(not x.strip() for x in ids) or len(set(ids)) != len(ids):
            return False, "Missing or duplicate entity IDs"
        if kind == "labels":
            actual = {row[spec["id_column"]]: row[spec["label_column"]] for row in rows}
            return actual == spec["expected"], "Exact per-entity label and coverage comparison"
        if "testing_family" in spec:
            from .science import reference_json
            family = reference_json(verifier_root, spec["testing_family"])
            if (not isinstance(family, dict) or set(family) != {"ids"} or not isinstance(family["ids"], list)
                    or not family["ids"] or any(not isinstance(v, str) or not v.strip() for v in family["ids"])
                    or len(set(family["ids"])) != len(family["ids"])):
                raise OSError("Invalid frozen testing-family reference")
            if set(ids) != set(family["ids"]):
                return False, "Submitted DE table omits or adds entities relative to the frozen testing family"
        if len(rows) < spec["min_rows"]:
            return False, "Too few tested entities"
        ps = [float(row[spec["p_column"]]) for row in rows]
        qs = [float(row[spec["q_column"]]) for row in rows]
        effects = [float(row[spec["effect_column"]]) for row in rows]
        if any(not math.isfinite(x) for x in ps + qs + effects) or any(not 0 <= x <= 1 for x in ps + qs):
            return False, "Nonfinite effect or invalid probability"
        order = sorted(range(len(ps)), key=ps.__getitem__)
        expected = [0.] * len(ps)
        bound = 1.
        for rank in range(len(ps), 0, -1):
            i = order[rank - 1]
            bound = min(bound, ps[i] * len(ps) / rank)
            expected[i] = bound
        if any(abs(a - b) > spec["bh_tolerance"] for a, b in zip(qs, expected)):
            return False, "BH adjusted probabilities disagree with the complete submitted testing family"
    elif kind == "h5ad":
        try:
            import anndata
        except ImportError:
            return None, "Optional anndata dependency unavailable"
        obj = anndata.read_h5ad(path, backed="r")
        try:
            ok = obj.shape == (spec["n_obs"], spec["n_vars"]) and obj.obs_names.is_unique
            ok = ok and all(c in obj.obs and not obj.obs[c].isna().any() for c in spec["obs_columns"])
            ok = ok and (not spec["var_names_unique"] or obj.var_names.is_unique)
            return bool(ok), "h5ad shape, unique IDs and required observation completeness"
        finally:
            obj.file.close()
    return True, "Artifact satisfies the frozen computational contract; biological validity not established"


def grade_artifact(g, record, root, verifier_root=None):
    receipt = {"rule_sha256": suite_digest(g), "scope": "LOCAL_COMPUTATIONAL_CHECK"}
    if root is None:
        return None, "Artifact root not supplied; output text cannot substitute for the artifact", receipt
    entry = record.get("artifacts", {}).get(g["artifact"]) if isinstance(record.get("artifacts", {}), dict) else None
    if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
        return None, "Artifact path and collected SHA-256 unavailable", receipt
    try:
        path = confined(root, entry["path"])
        if not path.is_file():
            return None, "Collected artifact missing", receipt
        if path.stat().st_size > MAX_BYTES:
            return None, "Artifact exceeds verification size limit", receipt
        before = sha(path)
        receipt.update(artifact_path=entry["path"], artifact_sha256=before)
        if before != entry["sha256"]:
            return None, "Artifact changed since collection", receipt
        from .science import KINDS as SCIENCE_KINDS, check
        if g["type"] in SCIENCE_KINDS:
            passed, details = check(g["type"], path, g["verifier"], verifier_root, record, before)
            receipt.update(details)
            rationale = "Scientific computational contract checked; inspect verifier receipt and evidence limits"
        elif g["type"] == "artifact":
            passed, rationale = _builtin(path, g["verifier"], verifier_root)
            if g["verifier"]["kind"] == "de_table":
                receipt["testing_family_scope"] = "FROZEN_REFERENCE" if "testing_family" in g["verifier"] else "SUBMITTED_ROWS_ONLY"
                if "testing_family" in g["verifier"]:
                    receipt["testing_family_sha256"] = g["verifier"]["testing_family"]["sha256"]
        else:
            if verifier_root is None:
                return None, "Executable verification requires an explicitly trusted verifier root", receipt
            program = confined(verifier_root, g["verifier"]["path"])
            if sha(program) != g["verifier"]["sha256"]:
                return None, "Verifier code digest mismatch", receipt
            receipt["verifier_sha256"] = sha(program)
            # Local user-approved code, NOT a security sandbox. Output files bound
            # in size below; no shell, no dynamic imports from model artifacts.
            with tempfile.TemporaryDirectory() as directory:
                pinned = Path(directory) / "verifier.py"
                pinned.write_bytes(program.read_bytes())
                if sha(pinned) != receipt["verifier_sha256"]:
                    return None, "Verifier changed before execution", receipt
                log = Path(directory) / "stdout"
                err = Path(directory) / "stderr"
                with log.open("wb") as out, err.open("wb") as errors:
                    result = subprocess.Popen([sys.executable, "-I", str(pinned), str(path)],
                        cwd=directory, stdin=subprocess.DEVNULL, stdout=out, stderr=errors,
                        start_new_session=os.name != "nt", shell=False,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
                    from .processes import bind_tree, close_tree
                    try:
                        bind_tree(result)
                        result.wait(timeout=g["verifier"]["timeout_seconds"])
                    finally:
                        close_tree(result)
                receipt["exit_code"] = result.returncode
                if result.returncode or log.stat().st_size > 65536:
                    return None, "Verifier crashed or exceeded response limit", receipt
                verdict = load_json(log)
                if not isinstance(verdict, dict) or set(verdict) != {"passed", "rationale"} or type(verdict["passed"]) is not bool or not isinstance(verdict["rationale"], str) or not verdict["rationale"].strip():
                    return None, "Malformed executable verifier response", receipt
                passed, rationale = verdict["passed"], verdict["rationale"]
            if sha(program) != receipt["verifier_sha256"]:
                return None, "Verifier changed while running", receipt
        if sha(path) != before:
            return None, "Artifact changed during verification", receipt
        return passed, rationale, receipt
    except subprocess.TimeoutExpired:
        return None, "Verifier timed out", receipt
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        # Portable failures must not depend on the checkout, export directory,
        # or fresh temporary verifier directory. Preserve the collected relative
        # artifact identity and useful parser diagnostics instead.
        message = str(exc)
        for name, label in (("path", entry["path"]), ("program", "<verifier>"), ("log", "<verifier-response>")):
            value = locals().get(name)
            if value is not None:
                message = message.replace(str(value), label)
        # Broken transport or missing code is not evidence of a bad scientific result.
        if g["type"] in ("executable", "exec") or isinstance(exc, OSError):
            return None, f"Verification unavailable: {message}", receipt
        return False, f"Invalid artifact: {message}", receipt
