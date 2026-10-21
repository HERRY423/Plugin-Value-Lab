"""Validate community metadata offline; this is not a privacy or security audit."""
import argparse
import datetime
import hashlib
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('CITATION.cff', 'docs/history/20261011/SECURITY.md', 'docs/history/20261011/CONTRIBUTING.md',
            'docs/history/20261011/docs/API-STABILITY.md', 'docs/history/20261011/docs/DATA-GOVERNANCE.md',
            'docs/DATA-GOVERNANCE.md', 'docs/feature-freeze.json')


def external_l1_gate(root, version):
    """Release paperwork check; identity/consent remain human-verification duties.

    Only approved, non-sensitive completion records belong in the source tree.
    Hashes bind those records; they do not authenticate a lab or raw results.
    """
    policy = json.loads((root / 'docs/feature-freeze.json').read_text(encoding='utf-8'))
    gate = policy.get('v1_release_gate', {})
    if gate.get('criterion') != 'ONE_EXTERNAL_LAB_COMPLETES_L1' or gate.get('required_labs') != 1:
        raise ValueError('External L1 release criterion missing or changed')
    records = gate.get('records')
    if not isinstance(records, list):
        raise ValueError('External L1 completion records must be explicit; unknown is not complete')
    labs = set()
    for entry in records:
        if not isinstance(entry, dict) or set(entry) != {'completion_record', 'sha256'}:
            raise ValueError('External L1 requires an approved completion record and its hash')
        path = root / entry['completion_record']
        if Path(entry['completion_record']).is_absolute() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError('External L1 approved record missing or outside release tree')
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('External L1 completion record checksum mismatch')
        record = json.loads(path.read_text(encoding='utf-8'))
        for flag in ('external_operator', 'lab_confirmed_complete', 'release_owner_accepted', 'export_approved'):
            if record.get(flag) is not True:
                raise ValueError('External L1 human attestation missing: ' + flag)
        for name in ('lab_code', 'lab_attestation_ref', 'release_review_ref', 'tested_version', 'use_card_ref'):
            if not isinstance(record.get(name), str) or not record[name].strip() or record[name] == 'UNKNOWN':
                raise ValueError('External L1 completion reference missing: ' + name)
        if not re.fullmatch('[0-9a-f]{64}', record.get('tested_source_sha256', '')):
            raise ValueError('External L1 tested source identity missing')
        if record.get('outcome') not in ('STOP', 'INSUFFICIENT_EVIDENCE', 'ADVANCE_PILOT'):
            raise ValueError('External L1 needs a use-card outcome; positive benefit is not required')
        tasks = record.get('task_ids', [])
        if (not isinstance(tasks, list) or not 3 <= len(tasks) <= 5
                or any(not isinstance(t, str) or not t for t in tasks) or len(set(tasks)) != len(tasks)):
            raise ValueError('External L1 requires 3–5 distinct real-task references')
        expected = {(t, repeat, arm) for t in tasks for repeat in (0, 1) for arm in ('with', 'without')}
        attempts = record.get('attempts', [])
        if (not isinstance(attempts, list) or len(attempts) != len(expected)
                or any(not isinstance(r, dict) or type(r.get('repeat')) is not int
                       or not isinstance(r.get('task_id'), str) or not isinstance(r.get('arm'), str)
                       or r.get('status') not in ('completed', 'failed') for r in attempts)
                or {(r['task_id'], r['repeat'], r['arm']) for r in attempts} != expected):
            raise ValueError('External L1 incomplete/duplicate attempts do not satisfy completion')
        labs.add(record['lab_code'])
    met = len(labs) >= 1
    stable_v1_or_later = re.fullmatch(r'[1-9]\d*\.\d+\.\d+(?:\+[A-Za-z0-9.-]+)?', version) is not None
    if stable_v1_or_later and not met:
        raise ValueError('Formal release blocked: one external laboratory must complete L1 (0/1 records)')
    return {'status': 'RECORDED_COMPLETE' if met else 'WAITING_EXTERNAL_L1',
            'recorded_labs': len(labs), 'required_labs': 1,
            'external_identity_authenticated_by_script': False, 'automatic_release': False}


def check(root=ROOT):
    import yaml
    from jsonschema import Draft7Validator, FormatChecker

    root = Path(root).resolve()
    for name in REQUIRED:
        path = root / name
        if not path.is_file() or not path.resolve().is_relative_to(root) or not path.read_text(encoding='utf-8').strip():
            raise ValueError('Required community file missing, empty or outside root: ' + name)
    schemas = root / 'schemas/citation-file-format/1.2.0'
    sources = json.loads((schemas / 'SOURCES.json').read_text(encoding='utf-8'))
    if sorted(entry['file'] for entry in sources['files']) != ['LICENSE', 'schema.json']:
        raise ValueError('Incomplete CFF schema provenance')
    for entry in sources['files']:
        path = schemas / entry['file']
        if not path.resolve().is_relative_to(schemas) or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('CFF schema provenance checksum mismatch')
    schema = json.loads((schemas / 'schema.json').read_text(encoding='utf-8'))
    Draft7Validator.check_schema(schema)
    citation = yaml.safe_load((root / 'CITATION.cff').read_text(encoding='utf-8'))
    # YAML dates become date objects; the upstream JSON schema requires strings.
    def normalize(value):
        if isinstance(value, datetime.date):
            return value.isoformat()
        raise TypeError('Unsupported citation value')
    citation = json.loads(json.dumps(citation, default=normalize))
    Draft7Validator(schema, format_checker=FormatChecker()).validate(citation)
    manifest = json.loads((root / 'plugin.json').read_text(encoding='utf-8'))
    if citation.get('version') != manifest['version']:
        raise ValueError('Citation and plugin version drift')
    if citation.get('license') != 'Apache-2.0' or citation.get('repository-code') != 'https://github.com/HERRY423/Plugin-Value-Lab':
        raise ValueError('Citation license or repository identity drift')
    release_gate = external_l1_gate(root, manifest['version'])
    return {'status': 'PASS', 'citation_format': citation['cff-version'],
            'source_version': citation['version'], 'required_files': list(REQUIRED),
            'schemas_loaded_offline': True, 'privacy_enforcement_verified': False,
            'v1_release_gate': release_gate}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', default=str(ROOT))
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.root), indent=2))
    except Exception as exc:
        print(f'Community metadata validation failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
