"""Deterministic scientific checks. References are scorer inputs, never model text.

Identity receipts are supplied by a separately trusted collector. Digests bind
bytes; they do not authenticate a collector or establish biological validity.
"""
from collections import Counter
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid

from .core import ValidationError, load_json

KINDS = {"pseudobulk_chain", "artifact_schema", "numeric_tolerance", "abstention_correct", "over_refusal", "backend_identity", "exec", "replicate_effect"}
REFERENCE_FIELDS = ("truth", "program", "testing_family", "design", "data")


def keys(obj, expected):
    if not isinstance(obj, dict) or set(obj) != set(expected.split()):
        raise ValidationError("Unexpected or missing scientific verifier fields")


def number(value):
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValidationError("Expected a finite number, not a boolean")
    return value


def reference(ref):
    from .artifacts import confined
    keys(ref, "path sha256")
    confined(Path.cwd(), ref["path"])
    if not isinstance(ref["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", ref["sha256"]):
        raise ValidationError("Reference requires a SHA-256 digest")


def validate_spec(kind, spec):
    if kind == "pseudobulk_chain":
        from .pseudobulk import validate_spec as validate_pseudobulk
        validate_pseudobulk(spec)
    elif kind == "replicate_effect":
        from .replicates import validate_spec as validate_replicates
        validate_replicates(spec)
    elif kind == "artifact_schema":
        keys(spec, "format fields allow_extra min_rows")
        if spec["format"] not in ("json", "csv") or type(spec["allow_extra"]) is not bool:
            raise ValidationError("Schema format must be json/csv and allow_extra boolean")
        if type(spec["min_rows"]) is not int or spec["min_rows"] < 1:
            raise ValidationError("min_rows must be positive")
        if not isinstance(spec["fields"], dict) or not spec["fields"]:
            raise ValidationError("Schema requires named fields")
        for name, field in spec["fields"].items():
            if not isinstance(name, str) or not name.strip():
                raise ValidationError("Schema fields require names")
            keys(field, "type nullable")
            if field["type"] not in ("string", "number", "integer", "boolean") or type(field["nullable"]) is not bool:
                raise ValidationError("Unsupported scalar field contract")
    elif kind == "numeric_tolerance":
        keys(spec, "metric truth id_column value_column threshold absolute relative")
        reference(spec["truth"])
        if spec["metric"] not in ("absolute_relative", "ari", "nmi", "pearson"):
            raise ValidationError("Unsupported numeric metric")
        if any(not isinstance(spec[k], str) or not spec[k].strip() for k in ("id_column", "value_column")) or spec["id_column"] == spec["value_column"]:
            raise ValidationError("Distinct entity and value columns are required")
        for k in ("absolute", "relative"):
            if number(spec[k]) < 0:
                raise ValidationError("Tolerances must be nonnegative")
        threshold = number(spec["threshold"])
        if not (-1 <= threshold <= 1) or (spec["metric"] == "nmi" and threshold < 0):
            raise ValidationError("Invalid metric threshold")
        if spec["metric"] == "absolute_relative" and threshold != 1:
            raise ValidationError("Elementwise tolerances require full coverage and threshold 1")
        if spec["metric"] != "absolute_relative" and (spec["absolute"] or spec["relative"]):
            raise ValidationError("ARI/NMI/Pearson use a threshold, not elementwise tolerances")
    elif kind in ("abstention_correct", "over_refusal"):
        keys(spec, "truth")
        reference(spec["truth"])
    elif kind == "backend_identity":
        keys(spec, "backend version entrypoint")
        if any(not isinstance(spec[k], str) or not spec[k].strip() for k in ("backend", "version", "entrypoint")):
            raise ValidationError("Backend contract requires exact backend, version and entrypoint")
    elif kind == "exec":
        keys(spec, "program image timeout_seconds")
        reference(spec["program"])
        if not spec["program"]["path"].endswith(".py"):
            raise ValidationError("Sandbox verifier must be Python")
        if not isinstance(spec["image"], str) or not re.fullmatch(r"[a-z0-9./:_-]+@sha256:[a-f0-9]{64}", spec["image"]):
            raise ValidationError("Sandbox requires an immutable image digest, never a tag")
        if type(spec["timeout_seconds"]) is not int or not 1 <= spec["timeout_seconds"] <= 60:
            raise ValidationError("Sandbox timeout must be 1..60 seconds")
    else:
        raise ValidationError("Unsupported scientific verifier")


def read_reference(root, ref):
    from .artifacts import MAX_BYTES, confined
    import hashlib
    if root is None:
        raise OSError("Separate scorer root is required")
    path = confined(root, ref["path"])
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != ref["sha256"]:
        raise OSError("Scorer reference missing, oversized or changed")
    return data


def reference_json(root, ref):
    from .core import _constant, _unique_object
    import json
    try:
        return json.loads(read_reference(root, ref), parse_constant=_constant, object_pairs_hook=_unique_object)
    except ValueError as exc:
        raise OSError("Invalid scorer reference JSON") from exc


def _scalar(value, field, csv=False):
    if value is None or (csv and value == ""):
        return field["nullable"]
    kind = field["type"]
    if csv:
        if kind == "string":
            return True
        if kind == "boolean":
            return value in ("true", "false")
        if kind == "integer":
            return bool(re.fullmatch(r"-?(0|[1-9][0-9]*)", value))
        try:
            return math.isfinite(float(value))
        except ValueError:
            return False
    if kind == "number":
        try:
            number(value)
            return True
        except ValidationError:
            return False
    return {"string": isinstance(value, str), "boolean": type(value) is bool,
            "integer": type(value) is int}[kind]


def schema_check(path, spec):
    from .artifacts import _table
    if spec["format"] == "json":
        data = load_json(path)
        rows = data if isinstance(data, list) else [data]
    else:
        rows = _table(path)
    if len(rows) < spec["min_rows"]:
        return False
    for row in rows:
        if not isinstance(row, dict) or not set(spec["fields"]).issubset(row):
            return False
        if not spec["allow_extra"] and set(row) != set(spec["fields"]):
            return False
        if not all(_scalar(row[k], v, spec["format"] == "csv") for k, v in spec["fields"].items()):
            return False
    return True


def cluster_score(actual, truth, metric):
    """ARI or arithmetic-normalized MI; label permutations are equivalent."""
    n = len(actual)
    if n < 2:
        raise ValueError("Clustering comparison needs at least two entities")
    a, b, cells = Counter(actual), Counter(truth), Counter(zip(actual, truth))
    choose = lambda x: x * (x - 1) / 2
    if metric == "ari":
        pairs = choose(n)
        x, y = sum(map(choose, a.values())), sum(map(choose, b.values()))
        expected = x * y / pairs
        denominator = (x + y) / 2 - expected
        return (sum(map(choose, cells.values())) - expected) / denominator if denominator else 1.0
    ha = -sum(v / n * math.log(v / n) for v in a.values())
    hb = -sum(v / n * math.log(v / n) for v in b.values())
    mi = sum(v / n * math.log(v * n / (a[x] * b[y])) for (x, y), v in cells.items())
    return max(0., min(1., 2 * mi / (ha + hb))) if ha + hb else 1.0


def numeric_check(path, spec, root):
    from .artifacts import _table
    with tempfile.TemporaryDirectory() as directory:
        truth_file = Path(directory) / Path(spec["truth"]["path"]).name
        truth_file.write_bytes(read_reference(root, spec["truth"]))
        try:
            expected = _entities(_table(truth_file), spec)
        except (ValueError, KeyError) as exc:
            raise OSError("Invalid reference table") from exc
    observed = _entities(_table(path), spec)
    if set(observed) != set(expected):
        return False, {"metric": spec["metric"], "coverage_complete": False, "value": None}
    x, y = [observed[k] for k in sorted(expected)], [expected[k] for k in sorted(expected)]
    metric = spec["metric"]
    if metric in ("ari", "nmi"):
        value = cluster_score(x, y, metric)
    else:
        try:
            y = [float(v) for v in y]
            if not all(math.isfinite(v) for v in y):
                raise ValueError("nonfinite")
        except ValueError as exc:
            raise OSError("Invalid numeric reference") from exc
        x = [float(v) for v in x]
        if not all(math.isfinite(v) for v in x):
            raise ValueError("Nonfinite submitted values")
        if metric == "absolute_relative":
            def within(a, b):
                difference = abs(a - b)
                bound = spec["absolute"] + spec["relative"] * abs(b)
                if not math.isfinite(difference) or not math.isfinite(bound):
                    raise ValueError("Numeric tolerance calculation overflow")
                return difference <= bound
            value = sum(within(a, b) for a, b in zip(x, y)) / len(x)
        else:
            # Scale before centering to avoid overflow on finite extreme inputs.
            sx, sy = max(1., max(map(abs, x))), max(1., max(map(abs, y)))
            x, y = [v / sx for v in x], [v / sy for v in y]
            mx, my = math.fsum(x) / len(x), math.fsum(y) / len(y)
            x, y = [v - mx for v in x], [v - my for v in y]
            divisor = math.sqrt(math.fsum(v*v for v in x) * math.fsum(v*v for v in y))
            if len(x) < 2 or not divisor:
                return None, {"metric": metric, "coverage_complete": True, "value": None, "reason": "Undefined correlation"}
            value = max(-1., min(1., math.fsum(a*b for a, b in zip(x, y)) / divisor))
    return value >= spec["threshold"], {"metric": metric, "coverage_complete": True, "entities": len(x), "value": value}


def _entities(rows, spec):
    result = {}
    for row in rows:
        entity, value = row[spec["id_column"]], row[spec["value_column"]]
        if not entity.strip() or not value.strip() or entity in result:
            raise ValueError("Missing/duplicate entity or blank value")
        result[entity] = value
    return result


def sandbox_check(path, spec, root):
    """Docker is mandatory. No pull, shell, host fallback, or scorer-root mount."""
    from .core import write_json
    docker = shutil.which("docker")
    if not docker:
        raise OSError("Docker is unavailable; exec has no unsandboxed fallback")
    program = read_reference(root, spec["program"])
    name = "pvl-verifier-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory) / "inputs"
        stage.mkdir()
        (stage / "verify.py").write_bytes(program)
        shutil.copyfile(path, stage / "artifact")
        write_json(stage / "contract.json", {"artifact_filename": path.name})
        command = [docker, "run", "--pull=never", "--name", name, "--network=none", "--read-only",
                   "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=65534:65534",
                   "--pids-limit=32", "--memory=256m", "--memory-swap=256m", "--cpus=1",
                   "--log-driver=none", "--ulimit", "fsize=65536:65536",
                   "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "--workdir=/tmp",
                   "--mount", f"type=bind,source={stage},target=/inputs,readonly",
                   "--entrypoint=python", spec["image"], "-I", "/inputs/verify.py", "/inputs/artifact"]
        log, err = Path(directory) / "out", Path(directory) / "err"
        try:
            with log.open("wb") as out, err.open("wb") as errors:
                proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=out, stderr=errors, shell=False)
                try:
                    deadline = time.monotonic() + spec["timeout_seconds"]
                    while proc.poll() is None:
                        if time.monotonic() >= deadline or max(log.stat().st_size, err.stat().st_size) > 65536:
                            raise OSError("Sandbox timed out or exceeded output limit")
                        time.sleep(.02)
                finally:
                    if proc.poll() is None:
                        proc.kill()
                    proc.wait(timeout=5)
            if proc.returncode or max(log.stat().st_size, err.stat().st_size) > 65536:
                raise OSError("Sandbox unavailable, verifier failed, or response too large")
            try:
                verdict = load_json(log)
                keys(verdict, "passed rationale")
                if type(verdict["passed"]) is not bool or not isinstance(verdict["rationale"], str) or not verdict["rationale"].strip():
                    raise ValueError("Invalid verdict")
            except ValueError as exc:
                raise OSError("Malformed sandbox verdict") from exc
            return verdict["passed"], {"image": spec["image"], "isolation": "DOCKER_RESTRICTED", "rationale": verdict["rationale"]}
        finally:
            # Only this invocation's randomly named container can be removed.
            subprocess.run([docker, "rm", "--force", name], capture_output=True, timeout=10, check=False)


def check(kind, path, spec, root, record, artifact_sha):
    if kind == "pseudobulk_chain":
        from .pseudobulk import check as check_pseudobulk
        return check_pseudobulk(path, spec, root)
    if kind == "replicate_effect":
        from .replicates import check as check_replicates
        return check_replicates(path, spec, root)
    if kind == "artifact_schema":
        return schema_check(path, spec), {"schema_scope": "Required scalar JSON/CSV fields; not general JSON Schema"}
    if kind == "numeric_tolerance":
        return numeric_check(path, spec, root)
    if kind in ("abstention_correct", "over_refusal"):
        truth = reference_json(root, spec["truth"])
        expected = "withhold" if kind == "abstention_correct" else "allow"
        if not isinstance(truth, dict) or set(truth) != {"decision", "rationale"} or truth["decision"] != expected or not isinstance(truth["rationale"], str) or not truth["rationale"].strip():
            raise OSError("Invalid decision reference for this metric")
        obj = load_json(path)
        decision = obj.get("decision") if isinstance(obj, dict) else None
        if decision not in ("allow", "withhold"):
            decision = None
        return decision == expected, {"metric": "unsupported_acceptance" if expected == "withhold" else "over_refusal",
                                     "decision": decision, "error": decision != expected if decision else None}
    if kind == "backend_identity":
        ref = record.get("backend_receipt")
        try:
            reference(ref)
        except ValidationError as exc:
            raise OSError("Collector receipt reference missing") from exc
        receipt = reference_json(root, ref)
        required = {"backend", "version", "entrypoint", "fallback", "session_id", "artifact_sha256", "collector", "basis"}
        if not isinstance(receipt, dict) or set(receipt) != required or receipt["basis"] != "runtime_observation" or not isinstance(receipt["collector"], str) or not receipt["collector"].strip() or type(receipt["fallback"]) is not bool:
            raise OSError("Independent runtime collector receipt required")
        if not record.get("session_id") or receipt["session_id"] != record["session_id"] or receipt["artifact_sha256"] != artifact_sha:
            raise OSError("Backend receipt does not bind this session and output artifact")
        passed = all(receipt[k] == spec[k] for k in ("backend", "version", "entrypoint")) and not receipt["fallback"]
        return passed, {"collector": receipt["collector"], "receipt_sha256": ref["sha256"], "identity_scope": "Trusted collector assertion; authenticity not independently verified"}
    if kind == "exec":
        return sandbox_check(path, spec, root)
    raise ValidationError("Unknown scientific verifier")
