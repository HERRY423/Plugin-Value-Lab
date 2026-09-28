"""Replay inventory and exact, offline MCP tool cassettes. No live fallback."""
import importlib.metadata
import platform
import sys

from .core import suite_digest


def replay_message(line):
    import json
    from .core import ValidationError, _constant, _unique_object
    try:
        return json.loads(line, parse_constant=_constant, object_pairs_hook=_unique_object)
    except RecursionError as exc:
        raise ValidationError('Replay JSON nesting exceeds parser limit') from exc


def _json_copy(value):
    import json
    from .core import ValidationError
    try:
        return json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValidationError('Replay values must be finite JSON') from exc


def _validate_cassette(data):
    from .core import ValidationError
    if (not isinstance(data, dict) or set(data) != {'format', 'tools', 'exchanges', 'provenance'}
            or data['format'] != 'pvl-tool-cassette-1'
            or not isinstance(data['tools'], list) or not data['tools']
            or not isinstance(data['exchanges'], list) or not data['exchanges']
            or not isinstance(data['provenance'], dict)
            or data['provenance'].get('origin') not in ('manufactured', 'recorded')
            or not isinstance(data['provenance'].get('description'), str)
            or not data['provenance']['description'].strip()):
        raise ValidationError('Invalid tool cassette or missing origin/description')
    names = set()
    for tool in data['tools']:
        if (not isinstance(tool, dict) or not isinstance(tool.get('name'), str)
                or not tool['name'] or tool['name'] in names
                or not isinstance(tool.get('inputSchema'), dict)):
            raise ValidationError('Cassette needs unique MCP tools with inputSchema')
        names.add(tool['name'])
    for entry in data['exchanges']:
        if not isinstance(entry, dict) or set(entry) != {'request', 'response'}:
            raise ValidationError('Each exchange needs request and response')
        request, response = entry['request'], entry['response']
        if (not isinstance(request, dict) or set(request) != {'name', 'arguments'}
                or not isinstance(request['name'], str) or request['name'] not in names
                or not isinstance(request['arguments'], dict)
                or not isinstance(response, dict) or len(response) != 1
                or not set(response) <= {'result', 'error'}):
            raise ValidationError('Invalid tools/call exchange')
        if 'result' in response:
            result = response['result']
            if (not isinstance(result, dict) or not isinstance(result.get('content'), list)
                    or any(not isinstance(c, dict) or not isinstance(c.get('type'), str) for c in result['content'])
                    or ('isError' in result and type(result['isError']) is not bool)
                    or ('structuredContent' in result and not isinstance(result['structuredContent'], dict))):
                raise ValidationError('Invalid MCP CallToolResult')
        else:
            error = response['error']
            if (not isinstance(error, dict) or type(error.get('code')) is not int
                    or not isinstance(error.get('message'), str)):
                raise ValidationError('Invalid recorded JSON-RPC error')
    return data


def record_tools(directory, tools, exchanges, *, provenance):
    """Persist explicitly supplied, sanitized exchanges; never call a backend.

    The caller owns consent/redaction. No environment, credentials or files are
    discovered automatically. A cassette is test material, never a new study run.
    """
    from pathlib import Path
    from .core import ValidationError, write_json
    data = _validate_cassette(_json_copy({'format': 'pvl-tool-cassette-1',
        'tools': tools, 'exchanges': exchanges, 'provenance': provenance}))
    import json
    if len(json.dumps(data, ensure_ascii=True).encode('ascii')) > 8 * 1024 * 1024:
        raise ValidationError('Tool cassette exceeds 8 MiB')
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / 'cassette.json', data)
    return {'cassette_sha256': suite_digest(data), 'exchanges': len(exchanges),
            'new_observations': 0, 'backend_calls': 0, 'mode': 'OFFLINE_CONTRACT_REPLAY'}


class ToolReplay:
    """One ordered session, exact JSON arguments, no best-match or live lookup."""
    def __init__(self, directory, expected_id):
        from pathlib import Path
        from .core import ValidationError, load_json
        path = Path(directory) / 'cassette.json'
        if path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024:
            raise ValidationError('Cassette must be a bounded regular snapshot')
        data = _validate_cassette(load_json(path))
        if not isinstance(expected_id, str) or suite_digest(data) != expected_id:
            raise ValidationError('Cassette commitment missing or changed')
        self.data, self.expected_id = _json_copy(data), expected_id
        self.position, self.violations, self.ids = 0, [], set()
        self.initialized, self.ready = False, False

    def handle(self, message):
        """Bounded MCP JSON-RPC subset; transport IDs are not semantic keys."""
        from .core import ValidationError
        message = _json_copy(message)
        if (not isinstance(message, dict) or message.get('jsonrpc') != '2.0'
                or not isinstance(message.get('method'), str)):
            self.violations.append('invalid_message')
            raise ValidationError('Invalid JSON-RPC message')
        method, params = message['method'], message.get('params', {})
        if 'id' not in message:
            if method != 'notifications/initialized' or not self.initialized or self.ready:
                self.violations.append('unsupported_notification')
                raise ValidationError('Unsupported replay notification')
            self.ready = True
            return None
        rid = message['id']
        if type(rid) not in (int, str):
            self.violations.append('invalid_id')
            raise ValidationError('JSON-RPC id must be integer or string')
        identity = suite_digest(rid)
        if identity in self.ids:
            self.violations.append('duplicate_id')
            raise ValidationError('Duplicate JSON-RPC id')
        self.ids.add(identity)
        envelope = {'jsonrpc': '2.0', 'id': rid}
        if not isinstance(params, dict):
            self.violations.append('invalid_params')
            return dict(envelope, error={'code': -32602, 'message': 'params must be an object'})
        if method == 'initialize':
            version = params.get('protocolVersion')
            if not isinstance(version, str) or not version or self.initialized:
                self.violations.append('unsupported_protocol')
                return dict(envelope, error={'code': -32602, 'message': 'Missing protocol version or repeated initialization'})
            if version not in ('2024-11-05', '2025-03-26', '2025-06-18'):
                version = '2025-06-18'
            self.initialized = True
            return dict(envelope, result={'protocolVersion': version, 'capabilities': {'tools': {}},
                        'serverInfo': {'name': 'pvl-offline-replay', 'version': '1'},
                        'instructions': 'OFFLINE_CONTRACT_REPLAY. No backend, model, scientific validation or new observations.'})
        if method == 'ping':
            return dict(envelope, result={})
        if not self.ready:
            self.violations.append('not_initialized')
            return dict(envelope, error={'code': -32600, 'message': 'Initialize and acknowledge before tool requests'})
        if method == 'tools/list' and not params:
            return dict(envelope, result={'tools': _json_copy(self.data['tools'])})
        if method == 'tools/call':
            # Only _meta is transport context. Do not drop default/null fields,
            # normalize paths, reorder arrays or coerce booleans/numbers.
            semantic = {k: v for k, v in params.items() if k != '_meta'}
            if self.position < len(self.data['exchanges']):
                entry = self.data['exchanges'][self.position]
                if suite_digest(semantic) == suite_digest(entry['request']):
                    self.position += 1
                    return dict(envelope, **_json_copy(entry['response']))
            self.violations.append('unexpected_call_at_' + str(self.position))
            return dict(envelope, error={'code': -32602, 'message': 'Cassette mismatch/exhaustion; live fallback forbidden'})
        self.violations.append('unsupported_method_or_params')
        return dict(envelope, error={'code': -32601, 'message': 'Method/params outside frozen replay contract'})

    def receipt(self):
        complete = self.position == len(self.data['exchanges']) and not self.violations
        return {'status': 'REPLAY_COMPLETE' if complete else 'REPLAY_INCOMPLETE',
                'mode': 'OFFLINE_CONTRACT_REPLAY', 'cassette_sha256': self.expected_id,
                'consumed': self.position, 'expected': len(self.data['exchanges']),
                'violations': list(self.violations), 'new_observations': 0,
                'backend_calls': 0, 'scientific_execution': False}


def serve_tools(directory, expected_id, source, sink):
    """JSON-lines stdio server using only the standard library; EOF must finish."""
    import json
    from .core import ValidationError
    replay = ToolReplay(directory, expected_id)
    while True:
        line = source.readline(1024 * 1024 + 1)
        if not line:
            break
        if len(line) > 1024 * 1024 or not line.endswith('\n'):
            raise ValidationError('Incomplete or oversized replay message')
        response = replay.handle(replay_message(line))
        if response is not None:
            sink.write(json.dumps(response, ensure_ascii=True, allow_nan=False) + '\n')
            sink.flush()
    return replay.receipt()


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
