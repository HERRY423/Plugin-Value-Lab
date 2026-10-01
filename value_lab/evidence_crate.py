"""Portable RO-Crate for a completed packaging run, never a science certification.

Only explicitly selected files are copied. Original review signatures and RFC3161
tokens are preserved as bytes; the in-toto statement is deliberately unsigned.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from . import __version__
from .artifacts import confined, sha
from .claim_scope import verify_report
from .core import ValidationError, load_json, load_records, suite_digest, validate_suite, write_json

# Pin the interoperable profile family supported by roc-validator 0.11.2.
# A newer web specification does not silently change archived semantics.
RO = 'https://w3id.org/ro/crate/1.1'
PROCESS = 'https://w3id.org/ro/wfrun/process/0.5'
WORKFLOW = 'https://w3id.org/ro/wfrun/workflow/0.5'
WF = 'https://w3id.org/workflowhub/workflow-ro-crate/1.0'
PREDICATE = 'https://github.com/HERRY423/Plugin-Value-Lab/predicates/evidence-packaging/v1'
REQUIRED = {'suite', 'lock', 'records', 'report'}
OPTIONAL = {'registration', 'timestamp_request', 'timestamp_response', 'timestamp_receipt',
            'review_statement', 'review_signature', 'replay_receipt'}
LIMIT = 128 * 1024**2
TOTAL = 512 * 1024**2
BOUNDARY = {
    'scope': 'Packaging and byte consistency only; no analysis rerun during export',
    'statement_signature': 'UNSIGNED', 'reviewer_identity': 'NOT_ESTABLISHED',
    'timestamp_authenticity': 'NOT_REVERIFIED', 'replay_authenticity': 'NOT_ESTABLISHED',
    'scientific_validity': 'NOT_ESTABLISHED', 'causal_benefit': 'NOT_ESTABLISHED',
}


def _bytes(path, maximum=LIMIT):
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValidationError('Missing, non-file or oversized evidence: ' + str(path))
    with path.open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValidationError('Evidence exceeds size limit')
    return data


def _bindings(root, roles):
    paths = {role: confined(root, name) for role, name in roles.items()}
    for path in paths.values():
        _bytes(path)
    suite, lock, report = (load_json(paths[k]) for k in ('suite', 'lock', 'report'))
    validate_suite(suite)
    records = load_records(paths['records'])
    scope = verify_report(report)
    provenance = report['provenance']
    if (lock.get('suite_sha256') != suite_digest(suite)
            or provenance.get('suite_sha256') != suite_digest(suite)
            or provenance.get('records_sha256') != suite_digest(records)
            or provenance.get('local_lock') != lock):
        raise ValidationError('Suite, lock, records and scoped report do not bind the same study')
    if 'scope' in paths and load_json(paths['scope']) != scope:
        raise ValidationError('Detached scope card differs from report')
    paired = {'review_statement', 'review_signature'} & roles.keys()
    if paired and (len(paired) != 2 or 'registration' not in roles):
        raise ValidationError('Review requires original statement, signature and registration together')
    review_status = 'ABSENT'
    if paired:
        from .signatures import verify
        statement, signature = (load_json(paths[k]) for k in ('review_statement', 'review_signature'))
        if statement.get('format') != 'pvl-study-review-1' or statement.get('decision') not in ('accept', 'reject', 'unknown'):
            raise ValidationError('Unsupported review statement')
        expected = {'suite_sha256': suite_digest(suite), 'report_sha256': suite_digest(report),
                    'registration_sha256': suite_digest(load_json(paths['registration']))}
        if any(statement.get(k) != v for k, v in expected.items()):
            raise ValidationError('Review target differs from packaged study')
        verify(statement, signature, 'pvl-review-1')
        review_status = 'KEY_SIGNATURE_VALID_IDENTITY_UNTRUSTED'
    return scope, review_status


def _graph(statement, statement_sha):
    pred = statement['predicate']
    ref = lambda name: {'@id': name}
    subjects = statement['subject']
    files = [s['name'] for s in subjects] + ['statement.json']
    profiles = [PROCESS, WORKFLOW, WF]
    graph = [
        {'@id': 'ro-crate-metadata.json', '@type': 'CreativeWork', 'about': ref('./'), 'conformsTo': ref(RO)},
        {'@id': './', '@type': 'Dataset', 'name': pred['name'], 'description': BOUNDARY['scope'],
         'datePublished': pred['packaged_at'], 'license': ref(pred['license']),
         'conformsTo': [ref(p) for p in profiles], 'mainEntity': ref('workflow.py'),
         'hasPart': [ref(n) for n in files], 'mentions': ref('#packaging')},
        {'@id': pred['license'], '@type': 'CreativeWork', 'name': 'Depositor-selected evidence license'},
        {'@id': '#python', '@type': 'ComputerLanguage', 'name': 'Python', 'identifier': 'https://www.python.org/'},
        {'@id': '#exporter', '@type': ['SoftwareApplication', 'prov:SoftwareAgent'],
         'name': 'Plugin Value Lab evidence exporter', 'softwareVersion': pred['pvl_version']},
        {'@id': '#packaging', '@type': ['CreateAction', 'prov:Activity'], 'name': 'Package selected PVL evidence',
         'instrument': ref('workflow.py'), 'agent': ref('#exporter'),
         'endTime': pred['packaged_at'], 'actionStatus': ref('http://schema.org/CompletedActionStatus'),
         'object': [ref(n) for n in pred['roles'].values()], 'result': ref('statement.json'),
         'prov:used': [ref(n) for n in pred['roles'].values()], 'prov:wasAssociatedWith': ref('#exporter')},
    ]
    graph += [{'@id': p, '@type': 'CreativeWork', 'name': n} for p, n in zip(profiles,
              ['Process Run Crate 0.5', 'Workflow Run Crate 0.5', 'Workflow RO-Crate 1.0'])]
    for subject in subjects + [{'name': 'statement.json', 'digest': {'sha256': statement_sha}}]:
        name = subject['name']
        entity = {'@id': name, '@type': ['File', 'prov:Entity'], 'name': name,
                  'sha256': subject['digest']['sha256']}
        if name == 'workflow.py':
            entity.update({'@type': ['File', 'SoftwareSourceCode', 'ComputationalWorkflow', 'prov:Plan'],
                           'programmingLanguage': ref('#python'), 'version': pred['pvl_version'],
                           'description': 'Executed exporter source; requires the matching installed PVL package.',
                           'conformsTo': ref('https://bioschemas.org/profiles/ComputationalWorkflow/1.0-RELEASE')})
        if name == 'statement.json':
            entity.update({'encodingFormat': 'application/json', 'prov:wasGeneratedBy': ref('#packaging'),
                           'prov:wasDerivedFrom': [ref(n) for n in pred['roles'].values()]})
        graph.append(entity)
    return {'@context': [RO + '/context', 'https://w3id.org/ro/terms/workflow-run/context',
                         {'prov': 'http://www.w3.org/ns/prov#', 'sha256': 'http://schema.org/sha256'}],
            '@graph': graph}


def export_crate(spec_path, output):
    spec_path, root = Path(spec_path).absolute(), Path(output).absolute()
    spec = load_json(spec_path)
    if not isinstance(spec, dict) or set(spec) != {'name', 'license', 'files'}:
        raise ValidationError('Spec requires exactly name, license and files (role to relative path)')
    if not isinstance(spec['name'], str) or not spec['name'].strip():
        raise ValidationError('Evidence name required')
    if not isinstance(spec['license'], str) or urlsplit(spec['license']).scheme not in ('http', 'https'):
        raise ValidationError('Explicit evidence license URI required; source-code license is not inferred')
    roles = spec['files']
    if not isinstance(roles, dict) or not REQUIRED <= roles.keys() or roles.keys() - REQUIRED - OPTIONAL:
        raise ValidationError('Required roles: suite, lock, records, report; optional roles are documented')
    # Validate all selected files and bindings before creating an output directory.
    scope, review_status = _bindings(spec_path.parent, roles)
    payload = {}
    total = 0
    for role, name in sorted(roles.items()):
        source = confined(spec_path.parent, name)
        data = _bytes(source)
        total += len(data)
        if total > TOTAL:
            raise ValidationError('Evidence package exceeds 512 MiB')
        payload['data/' + role + '.bin'] = data
    packaged_roles = {role: 'data/' + role + '.bin' for role in roles}
    packaged_roles['scope'] = 'data/scope.json'
    payload['data/scope.json'] = (json.dumps(scope, ensure_ascii=True, indent=2, allow_nan=False) + '\n').encode()
    payload['workflow.py'] = Path(__file__).read_bytes()
    root.mkdir(parents=True, exist_ok=False)
    for name, data in payload.items():
        dest = confined(root, name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    # Recheck the exact copied bytes, including signature targets.
    _bindings(root, packaged_roles)
    statement = {'_type': 'https://in-toto.io/Statement/v1',
                 'subject': [{'name': n, 'digest': {'sha256': hashlib.sha256(v).hexdigest()}}
                             for n, v in sorted(payload.items())],
                 'predicateType': PREDICATE,
                 'predicate': {'name': spec['name'], 'license': spec['license'],
                               'packaged_at': datetime.now(timezone.utc).isoformat(), 'pvl_version': __version__,
                               'roles': packaged_roles, 'missing_components': sorted(OPTIONAL - roles.keys()),
                               'review_signature': review_status, 'boundaries': BOUNDARY}}
    write_json(root / 'statement.json', statement)
    write_json(root / 'ro-crate-metadata.json', _graph(statement, sha(root / 'statement.json')))
    return verify_crate(root, sha(root / 'ro-crate-metadata.json'))


def verify_crate(directory, expected_id=None):
    root = Path(directory).absolute()
    metadata_path = confined(root, 'ro-crate-metadata.json')
    _bytes(metadata_path, 8 * 1024**2)
    commitment = sha(metadata_path)
    if expected_id is not None and (not re.fullmatch('[a-f0-9]{64}', expected_id) or expected_id != commitment):
        raise ValidationError('Crate differs from separately retained metadata commitment')
    statement_path = confined(root, 'statement.json')
    _bytes(statement_path, 8 * 1024**2)
    statement = load_json(statement_path)
    if (not isinstance(statement, dict) or set(statement) != {'_type', 'subject', 'predicateType', 'predicate'}
            or statement['_type'] != 'https://in-toto.io/Statement/v1' or statement['predicateType'] != PREDICATE):
        raise ValidationError('Unsupported in-toto statement')
    subjects, pred = statement['subject'], statement['predicate']
    if not isinstance(subjects, list) or not 5 <= len(subjects) <= 32 or not isinstance(pred, dict):
        raise ValidationError('Invalid evidence inventory')
    roles = pred['roles']
    if (not isinstance(roles, dict) or not REQUIRED | {'scope'} <= roles.keys()
            or roles.keys() - REQUIRED - OPTIONAL - {'scope'} or len(set(roles.values())) != len(roles)):
        raise ValidationError('Invalid or aliased evidence roles')
    if pred['boundaries'] != BOUNDARY or pred['missing_components'] != sorted(OPTIONAL - roles.keys()):
        raise ValidationError('Evidence boundaries or missing components changed')
    names, total = set(), 0
    for subject in subjects:
        if not isinstance(subject, dict) or set(subject) != {'name', 'digest'}:
            raise ValidationError('Malformed in-toto subject')
        name = subject['name']
        path = confined(root, name)
        if name in names or subject['digest'].keys() != {'sha256'}:
            raise ValidationError('Duplicate subject or unsupported digest')
        names.add(name)
        data = _bytes(path)
        total += len(data)
        if total > TOTAL or hashlib.sha256(data).hexdigest() != subject['digest']['sha256']:
            raise ValidationError('Evidence bytes changed or package exceeds limit')
    if names != set(roles.values()) | {'workflow.py'}:
        raise ValidationError('Subject inventory does not match evidence roles')
    observed = set()
    for path in root.rglob('*'):
        confined(root, path.relative_to(root).as_posix())
        if path.is_file():
            observed.add(path.relative_to(root).as_posix())
    if observed != names | {'statement.json', 'ro-crate-metadata.json'}:
        raise ValidationError('Unexpected or missing files in evidence crate')
    _, review_status = _bindings(root, roles)
    if review_status != pred['review_signature']:
        raise ValidationError('Review signature state changed')
    if load_json(metadata_path) != _graph(statement, sha(statement_path)):
        raise ValidationError('RO-Crate graph, references or provenance changed')
    return {'status': 'CONSISTENT', 'metadata_sha256': commitment,
            'anchor': 'EXTERNAL_COMMITMENT_MATCHED' if expected_id else 'LOCAL_CONSISTENCY_ONLY',
            'profile_validation': 'PVL_MAPPING_CHECKS_ONLY', 'missing_components': pred['missing_components'],
            'review_signature': review_status, **BOUNDARY}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export')
    export.add_argument('spec')
    export.add_argument('--output', required=True)
    verify = sub.add_parser('verify')
    verify.add_argument('directory')
    verify.add_argument('--expected-id')
    args = p.parse_args(argv)
    try:
        result = export_crate(args.spec, args.output) if args.command == 'export' else verify_crate(args.directory, args.expected_id)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(json.dumps({'status': 'INVALID', 'error': str(exc)}, ensure_ascii=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
