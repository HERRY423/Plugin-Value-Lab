"""Portable, deterministic authoring trees. Loading never executes plugin code.

Frontmatter is deliberately a small, dependency-free language: one key per
line, JSON values or plain strings. Nested objects/arrays use inline JSON.
Unsupported YAML is an error, never a partially parsed evaluation contract.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re

from .core import (ValidationError, _constant, _unique_object, load_json,
                   suite_digest, validate_suite)

FORMAT = "pvl-evals-v1"


def _json(text):
    return _finite(json.loads(text, parse_constant=_constant, object_pairs_hook=_unique_object))


def _finite(value):
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValidationError('Authoring data must contain finite JSON values only') from exc
    return value


def _read(path):
    try:
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            return stream.read()
    except (OSError, UnicodeError) as exc:
        raise ValidationError(f"{path}: cannot read UTF-8: {exc}") from exc


def _inside(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValidationError(f"{root}: use a nonempty relative POSIX path")
    parts = relative.split("/")
    if any(p in ("", ".", "..") or ":" in p for p in parts):
        raise ValidationError(f"{root}: unsafe reference {relative!r}")
    path = Path(root).joinpath(*parts)
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValidationError(f"{path}: reference escapes authoring root")
    return path


def _name(value, label):
    from .native import _component
    _component(value, label)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", value):
        raise ValidationError(f"{label}: use letters, numbers, underscores or hyphens (max 100)")
    return value


def parse_frontmatter(content: str, *, preserve_body=False) -> tuple[dict, str]:
    if not preserve_body:
        content = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return {}, content if preserve_body else content.strip()
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
    if end is None:
        raise ValidationError("line 1: unclosed frontmatter; add a standalone --- line")
    fields = {}
    for number, raw in enumerate(lines[1:end], 2):
        line = raw.rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line != line.lstrip() or ":" not in line:
            raise ValidationError(f"line {number}: expected key: value; use inline JSON for nested data")
        key, value = line.split(":", 1)
        key, value = key.strip().strip('\"'), value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key) or key in fields:
            raise ValidationError(f"line {number}: invalid or duplicate key {key!r}")
        if not value:
            raise ValidationError(f"line {number}: missing value; use inline JSON or an explicit empty string")
        try:
            parsed = _json(value)
        except json.JSONDecodeError:
            if value[0] in '[{\"' or value in ("NaN", "Infinity", "-Infinity"):
                raise ValidationError(f"line {number}: invalid JSON value for {key}") from None
            if value.startswith("'") and value.endswith("'"):
                parsed = value[1:-1].replace("''", "'")
            elif (value[0] in "'&*!>|" or " #" in value or ": " in value
                  or value.lower() in ("yes", "no", "on", "off", "null", "true", "false")):
                raise ValidationError(f"line {number}: ambiguous YAML value; quote strings with JSON double quotes")
            else:
                parsed = value
        fields[key] = parsed
    body = "".join(lines[end + 1:])
    return fields, body if preserve_body else body.strip()


def _markdown(path):
    try:
        return parse_frontmatter(_read(path), preserve_body=True)
    except ValidationError as exc:
        raise ValidationError(f"{path}: {exc}") from exc


def _format(fields, body=""):
    return "---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False, allow_nan=False)}\n"
                               for k, v in fields.items()) + "---\n" + body


def _ordered(items, order, label):
    if order is None:
        return items
    if (not isinstance(order, list) or any(not isinstance(v, str) for v in order)
            or len(order) != len(set(order)) or set(order) != {v['id'] for v in items}):
        raise ValidationError(f"{label}: order must list every id exactly once; update it after adding/removing files")
    mapping = {v['id']: v for v in items}
    return [mapping[key] for key in order]


def dump_evals(suite, output_dir, overwrite=False):
    """Lossless JSON -> tree migration; never merge with or overwrite an old tree."""
    _finite(suite)
    validate_suite(suite)
    suite_digest(suite)
    if overwrite:
        raise ValidationError("Tree overwrite is unsafe; export to a fresh directory")
    files, cases_seen = {}, set()
    meta = deepcopy(suite)
    del meta['cases']
    if '_case_order' in meta or '_grader_order' in meta:
        raise ValidationError("Suite uses reserved authoring metadata")
    meta['_case_order'] = [c['id'] for c in suite['cases']]
    meta['_grader_order'] = {c['id']: [g['id'] for g in c['graders']] for c in suite['cases']}
    files['suite.json'] = json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    for case in suite['cases']:
        if 'grader_refs' in case:
            raise ValidationError('grader_refs is reserved authoring syntax; resolve references before exporting')
        cid = _name(case['id'], 'case id')
        if cid.casefold() in cases_seen or cid.casefold() in ('graders', 'evals'):
            raise ValidationError(f"Case id collision/reserved name: {cid}")
        cases_seen.add(cid.casefold())
        fields = {k: v for k, v in case.items() if k not in ('prompt', 'graders', 'rules')}
        files[f'{cid}/prompt.md'] = _format(fields, case['prompt'])
        if 'rules' in case:
            files[f'{cid}/case.yaml'] = json.dumps({'rules': case['rules']}, ensure_ascii=False, indent=2) + '\n'
        seen = set()
        for grader in case['graders']:
            gid = _name(grader['id'], 'grader id')
            if gid.casefold() in seen:
                raise ValidationError(f"{cid}: grader ids collide on a case-insensitive filesystem")
            seen.add(gid.casefold())
            human = grader['type'] == 'human'
            fields = {k: v for k, v in grader.items() if k != 'rubric' or not human}
            files[f'{cid}/graders/{gid}.md'] = _format(fields, grader.get('rubric', '') if human else '')
    root = Path(output_dir)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValidationError(f"{root}: destination must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        path = _inside(root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
    return root


def load_evals(evals_dir, suite_meta=None):
    root = Path(evals_dir)
    if not (root / 'suite.json').is_file() and (root / 'evals').is_dir():
        root = _inside(root, 'evals')
    meta_path = _inside(root, 'suite.json')
    if meta_path.is_file():
        suite = load_json(meta_path)
    elif suite_meta is not None:
        suite = deepcopy(suite_meta)
    else:
        raise ValidationError(f"{meta_path}: missing suite metadata; use init or supply suite_meta explicitly")
    if not isinstance(suite, dict) or 'cases' in suite:
        raise ValidationError(f"{meta_path}: tree metadata must be an object without embedded cases")
    try:
        _finite(suite)
    except ValidationError as exc:
        raise ValidationError(f'{meta_path}: {exc}') from exc
    case_order, grader_order = suite.pop('_case_order', None), suite.pop('_grader_order', None)
    if grader_order is not None and not isinstance(grader_order, dict):
        raise ValidationError(f"{meta_path}: _grader_order must be an object")
    suite['cases'] = []
    seen = set()
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or directory.name.startswith(('.', '_')) or directory.name == 'graders':
            continue
        directory = _inside(root, directory.name)
        prompt_path = _inside(root, f'{directory.name}/prompt.md')
        if not prompt_path.is_file():
            raise ValidationError(f"{prompt_path}: missing prompt; move unrelated directories outside the evals tree")
        fields, prompt = _markdown(prompt_path)
        if 'prompt' in fields or 'graders' in fields:
            raise ValidationError(f"{prompt_path}: prompt body and graders/ files are the only source of those fields")
        cid = fields.setdefault('id', directory.name)
        _name(cid, str(prompt_path))
        if cid != directory.name or cid.casefold() in seen:
            raise ValidationError(f"{prompt_path}: id must match its directory and be unique ignoring case")
        seen.add(cid.casefold())
        sidecar = _inside(root, f'{cid}/case.yaml')
        if sidecar.exists():
            extra = load_json(sidecar)  # JSON is a YAML subset, no optional parser dependency.
            if not isinstance(extra, dict) or set(extra) & (set(fields) | {'prompt', 'graders'}):
                raise ValidationError(f"{sidecar}: expected non-conflicting case metadata as JSON")
            fields.update(extra)
        refs = fields.pop('grader_refs', [])
        if not isinstance(refs, list) or any(not isinstance(r, str) for r in refs):
            raise ValidationError(f"{prompt_path}: grader_refs must be a list of relative Markdown paths")
        grader_dir = _inside(root, f'{cid}/graders')
        paths = sorted(grader_dir.glob('*.md')) if grader_dir.is_dir() else []
        paths = [_inside(root, p.relative_to(root).as_posix()) for p in paths]
        for ref in refs:
            path = _inside(root, ref)
            if not ref.startswith('graders/') or path.suffix != '.md':
                raise ValidationError(f"{prompt_path}: shared grader references must use graders/*.md")
            paths.append(path)
        graders, ids = [], set()
        for path in paths:
            grader, body = _markdown(path)
            gid = grader.setdefault('id', path.stem)
            _name(gid, str(path))
            if gid.casefold() in ids:
                raise ValidationError(f"{path}: duplicate grader id {gid} in {cid}")
            ids.add(gid.casefold())
            grader.setdefault('dimension', 'outcome')
            grader.setdefault('weight', 1)
            grader.setdefault('critical', False)
            if grader.get('type') == 'human':
                if 'rubric' in grader and body:
                    raise ValidationError(f"{path}: rubric must be in the body or metadata, not both")
                if body:
                    grader['rubric'] = body
            try:
                probe = deepcopy(suite)
                # These declarations describe the whole suite, not one grader.
                # Validate them unchanged below after all cases are assembled.
                probe.pop('usage_scopes', None)
                probe.pop('metric_applicability', None)
                probe_graders = [grader]
                if grader.get('dimension') == 'process':
                    probe_graders = [grader, {'id': 'authoring_probe_2' if gid == 'authoring_probe' else 'authoring_probe', 'type': 'contains',
                        'dimension': 'outcome', 'weight': 1, 'critical': False, 'value': 'probe'}]
                probe['cases'] = [dict(fields, prompt=prompt, graders=probe_graders)]
                # A case success contract can reference several grader files.
                # Validate it only after the complete case has been assembled.
                probe['cases'][0].pop('success_contract', None)
                validate_suite(probe)
            except ValidationError as exc:
                raise ValidationError(f"{path}: {exc}") from exc
            graders.append(grader)
        fields.update(prompt=prompt, graders=_ordered(graders, (grader_order or {}).get(cid), str(prompt_path)))
        suite['cases'].append(fields)
    if grader_order is not None and set(grader_order) != {c['id'] for c in suite['cases']}:
        raise ValidationError(f"{meta_path}: _grader_order must match the current case ids")
    suite['cases'] = _ordered(suite['cases'], case_order, str(meta_path))
    try:
        return validate_suite(suite)
    except ValidationError as exc:
        raise ValidationError(f"{root}: {exc}") from exc


def inspect_suite(suite):
    _finite(suite)
    validate_suite(suite)
    warnings = []
    kinds = {c['kind'] for c in suite['cases']}
    for kind in ('negative', 'abstention'):
        if kind not in kinds:
            warnings.append(f'No {kind} case; consider a boundary example before freezing')
    if suite['evidence_type'] == 'synthetic':
        warnings.append('Synthetic draft: no real benefit conclusion is possible')
    if any('REPLACE' in str(v) for v in (suite['plugin'], suite['conditions'])):
        warnings.append('Replace placeholder plugin/conditions before real collection')
    if any(g['type'] in ('contains', 'not_contains') and g['dimension'] == 'outcome'
           for c in suite['cases'] for g in c['graders']):
        warnings.append('Text matches establish surface checks only; use artifact checks or human review for correctness')
    if any(g['type'] == 'metamorphic' for c in suite['cases'] for g in c['graders']):
        warnings.append('Metamorphic relations require scientifically justified transformations, complete follow-up runs and a separate task correctness oracle')
    from .value_metrics import power_plan
    return {'status': 'VALID', 'suite_sha256': suite_digest(suite), 'power_plan': power_plan(suite), 'cases': [
        {'id': c['id'], 'kind': c['kind'], 'graders': [g['id'] for g in c['graders']]} for c in suite['cases']],
        'warnings': warnings, 'executed': False, 'frozen': False}
