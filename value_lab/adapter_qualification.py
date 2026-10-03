"""Executable single-adapter qualification; synthetic local checks, no certification."""
import argparse
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import tempfile

from . import codex_context, context_stream
from .core import ValidationError, suite_digest
from .delivery import publish_bundle

FORMAT = 'pvl-adapter-qualification-1'
FIXTURE_SHA256 = 'b67ba45e155a9d182bf64ddad10e67fcb7dfae459d19b3ec21706eb85f65ac46'
CHECKS = ('legacy_bytes', 'usage_semantics', 'missing_usage', 'unknown_host', 'unknown_originator',
          'incremental_boundaries', 'unchanged_replay', 'prefix_mutation', 'parser_upgrade')
SCOPE = {'originator': 'codex_work_desktop', 'engine_versions': ['0.159.2'],
         'evidence': 'SYNTHETIC_LOCAL_CONFORMANCE_ONLY'}


def implementation():
    names = ('adapter_qualification.py', 'context_stream.py', 'codex_context.py',
             'host_capabilities.py', 'delivery.py', 'core.py')
    return {n: hashlib.sha256(files('value_lab').joinpath(n).read_bytes()).hexdigest() for n in names}


def qualify(fixture_path, work_root):
    """Run fixed positive/negative controls in a fresh, caller-chosen local directory."""
    raw = Path(fixture_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise ValidationError('Qualification requires the retained, pinned legacy fixture')
    identity = implementation()
    parser = context_stream.qualification()
    if parser['qualified_engine_versions'] != SCOPE['engine_versions']:
        raise ValidationError('Host scope changed; explicit new qualification specification required')
    cases = json.loads(raw)['cases']
    work = Path(work_root)
    work.mkdir(parents=True, exist_ok=False)
    path = work / 'synthetic.jsonl'
    checks = {}

    def encode(events):
        return ''.join(json.dumps(e) + '\n' for e in events).encode()

    def check(name, condition):
        checks[name] = 'PASS' if condition else 'FAIL'

    check('legacy_bytes', True)
    for case in cases:
        path.write_bytes(encode(case['events']) + case['tail'].encode())
        if codex_context.capture(path, 'session') != case['expected']:
            checks['legacy_bytes'] = 'FAIL'
    events = deepcopy(next(c['events'] for c in cases if c['name'] == 'measured'))
    path.write_bytes(encode(events))
    normal = codex_context.capture(path, 'session')
    sample = normal['latest_context_sample']
    check('usage_semantics', sample is not None and sample['context_tokens'] == 210
          and sample['request_input_tokens'] == 200 and normal['thread_cumulative_usage']['total_tokens'] == 10000
          and normal['settled_cost_usd'] is None)
    missing = deepcopy(events)
    missing[3]['payload']['usage'].pop('input_tokens')
    path.write_bytes(encode(missing))
    snapshot = context_stream.capabilities(codex_context.capture(path, 'session'))
    check('missing_usage', snapshot['capabilities']['request_usage']['status'] == 'UNKNOWN'
          and snapshot['capabilities']['request_usage']['value'] is None)
    upgraded = deepcopy(events)
    upgraded[0]['payload']['cli_version'] = 'unqualified-version'
    path.write_bytes(encode(upgraded))
    snapshot = context_stream.capabilities(codex_context.capture(path, 'session'))
    check('unknown_host', snapshot['capabilities']['request_usage']['status'] == 'UNSUPPORTED'
          and snapshot['capabilities']['request_usage']['value'] is None)
    upgraded[0]['payload']['cli_version'] = '0.159.2'
    upgraded[0]['payload']['originator'] = 'unqualified-originator'
    path.write_bytes(encode(upgraded))
    snapshot = context_stream.capabilities(codex_context.capture(path, 'session'))
    check('unknown_originator', snapshot['capabilities']['request_usage']['status'] == 'UNSUPPORTED'
          and snapshot['capabilities']['request_usage']['value'] is None)
    path.write_bytes(encode(events))
    context_stream.capture_incremental(path, 'session', work / 'full')
    full = context_stream.read_checkpoint(work / 'full')[0]['state']
    check('incremental_boundaries', True)
    for split in range(1, len(events)):
        path.write_bytes(encode(events[:split]))
        first, second = work / f'first-{split}', work / f'second-{split}'
        context_stream.capture_incremental(path, 'session', first)
        with path.open('ab') as stream:
            stream.write(encode(events[split:]))
        context_stream.capture_incremental(path, 'session', second, previous=first)
        if context_stream.read_checkpoint(second)[0]['state'] != full:
            checks['incremental_boundaries'] = 'FAIL'
    result = context_stream.capture_incremental(path, 'session', work / 'replay', previous=second)['report']
    check('unchanged_replay', result['new_response_count'] == 0 and result['parser_events_processed'] == 0)
    path.write_bytes(path.read_bytes().replace(b'PRIVATE-TEXT', b'PRIVATE-FAKE'))
    try:
        context_stream.capture_incremental(path, 'session', work / 'damaged', previous=second)
    except ValidationError as exc:
        check('prefix_mutation', 'PREFIX_CHANGED' in str(exc))
    else:
        check('prefix_mutation', False)
    # A committed old parser cursor must remain readable as bytes, but unusable
    # as the new parser's internal state. No source code monkeypatching required.
    checkpoint = json.loads((second / 'checkpoint.json').read_bytes())
    checkpoint['qualification']['parser_sha256'] = '0' * 64
    publish_bundle(work / 'old-parser', {
        'checkpoint.json': json.dumps(checkpoint).encode(),
        'report.json': (second / 'report.json').read_bytes()})
    try:
        context_stream.read_checkpoint(work / 'old-parser')
    except ValidationError as exc:
        check('parser_upgrade', 'PARSER_CHANGED' in str(exc))
    else:
        check('parser_upgrade', False)
    if identity != implementation() or parser != context_stream.qualification():
        raise ValidationError('Implementation changed during qualification')
    return {'format': FORMAT, 'scope': deepcopy(SCOPE), 'qualification': parser,
            'implementation': identity, 'fixture_sha256': FIXTURE_SHA256, 'checks': checks,
            'status': 'PASS' if all(v == 'PASS' for v in checks.values()) else 'FAIL',
            'provider_authenticated': False, 'live_host_verified': False, 'execution_authorized': False}


def assess(receipt, snapshot, expected_sha256):
    """Validate a pinned receipt against this implementation and one capture.

    A submitted digest is an integrity anchor, not independent attestation that
    the checks ran or that the local log belongs to an authentic provider.
    """
    from .host_capabilities import validate
    validate(snapshot)
    reasons = []
    fields = {'format', 'scope', 'qualification', 'implementation', 'fixture_sha256', 'checks',
              'status', 'provider_authenticated', 'live_host_verified', 'execution_authorized'}
    if not isinstance(receipt, dict) or set(receipt) != fields:
        reasons.append('QUALIFICATION_RECEIPT_MISSING_OR_INVALID')
    else:
        if suite_digest(receipt) != expected_sha256:
            reasons.append('QUALIFICATION_ANCHOR_MISMATCH')
        if (receipt['format'] != FORMAT or receipt['scope'] != SCOPE
                or receipt['fixture_sha256'] != FIXTURE_SHA256
                or not isinstance(receipt['qualification'], dict)
                or receipt['checks'] != dict.fromkeys(CHECKS, 'PASS') or receipt['status'] != 'PASS'
                or any(receipt[k] is not False for k in ('provider_authenticated', 'live_host_verified', 'execution_authorized'))):
            reasons.append('QUALIFICATION_CONTROLS_NOT_SATISFIED')
        if receipt['implementation'] != implementation() or receipt['qualification'] != context_stream.qualification():
            reasons.append('QUALIFICATION_IMPLEMENTATION_CHANGED')
        q = snapshot['qualification']
        if (snapshot['adapter'] != 'codex-desktop-rollout'
                or not isinstance(receipt['qualification'], dict)
                or any(q.get(k) != v for k, v in receipt['qualification'].items())
                or q.get('observed_originator') != SCOPE['originator']
                or q.get('observed_engine_version') not in SCOPE['engine_versions']
                or q.get('host_schema_qualified') is not True):
            reasons.append('CAPTURE_OUTSIDE_QUALIFIED_SCOPE')
    return {'status': 'LOCAL_CONFORMANCE_BOUND' if not reasons else 'REQUALIFICATION_REQUIRED',
            'reasons': reasons, 'provider_authenticated': False, 'live_host_verified': False,
            'execution_authorized': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as temp:
        receipt = qualify(args.fixture, Path(temp) / 'checks')
    result = publish_bundle(args.output, {'qualification.json': (json.dumps(receipt, indent=2) + '\n').encode()})
    print(json.dumps({'delivery': result, 'status': receipt['status'], 'receipt_sha256': suite_digest(receipt)}))
    return 0 if result['status'] == 'COMMITTED' and receipt['status'] == 'PASS' else 3


if __name__ == '__main__':
    raise SystemExit(main())
