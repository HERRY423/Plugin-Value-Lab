"""Durable, read-only Codex adapter qualification and incremental capture.

Only new complete events are parsed. Mutable local files still require a streamed
prefix rehash; bounded memory is not a claim of constant-I/O prefix verification.
Checkpoint bundles are private local evidence, not authenticated attestations.
"""
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path

from . import codex_context
from .core import ValidationError, suite_digest
from .delivery import publish_bundle, read_bundle
from .host_capabilities import FORMAT, SEMANTICS, fact, validate, resolve_requirements

PARSER_VERSION = 'codex-rollout-state-1'
MAX_NEW_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 2 * 1024 * 1024
CLAIMS = {
    'request_input_usage': {'request_usage': SEMANTICS['request_usage']},
    'sampled_context': {'context_sample': SEMANTICS['context_sample']},
    'settled_charge': {'settled_cost': SEMANTICS['settled_cost']},
    'observed_plugin_execution': {k: SEMANTICS[k] for k in ('plugin_identity', 'tool_invoked')},
    'matched_arm_comparison': {'comparable_execution': SEMANTICS['comparable_execution']},
    'resume_local_capture': {'incremental_resume': SEMANTICS['incremental_resume']},
}


def qualification():
    names = ('codex_context.py', 'context_stream.py', 'host_capabilities.py')
    return {'adapter': 'codex-desktop-rollout', 'parser_version': PARSER_VERSION,
            'parser_sha256': suite_digest({n: hashlib.sha256(files('value_lab').joinpath(n).read_bytes()).hexdigest() for n in names}),
            'qualified_originator': 'codex_work_desktop',
            'qualified_engine_versions': sorted(codex_context.SUPPORTED_VERSIONS),
            'qualification_scope': 'LOCAL_LOG_FIELD_SEMANTICS_NOT_PROVIDER_AUTHENTICATION',
            'upgrade_rule': 'Exact parser and host schema qualification required; never infer from similar field names',
            'fallback': 'Preserve prior bundle; requalify/replay into a separate lineage; existing artifact checks remain independent'}


def capabilities(capture, *, cursor=None):
    """Map one qualified adapter to host-independent facts, one at a time."""
    rows = {name: fact(name, 'NOT_PROVIDED', reason='This read-only log adapter does not establish this capability') for name in SEMANTICS}
    qualified = capture['adapter_supported']
    def put(name, value, evidence, reason):
        status = 'OBSERVED' if value is not None else 'UNKNOWN'
        if not qualified:
            status, value, reason = 'UNSUPPORTED', None, 'HOST_VERSION_NOT_QUALIFIED'
        rows[name] = fact(name, status, value, evidence=evidence if status == 'OBSERVED' else (), reason=reason)
    host = capture['host']
    put('session_identity', {'session_id': host['id']}, [host['event']], 'Local session metadata; not authenticated identity')
    sample = next((s for s in reversed(capture['samples']) if s['kind'] == 'MAIN_REQUEST'), None)
    # Response-bound usage is independent of availability of the context event.
    if sample:
        identity = {k: sample[k] for k in ('session_id', 'turn_id', 'response_id')}
        put('request_identity', identity, [sample['event']], 'Observed response/turn/session binding')
        put('model_identity', sample['model'], [sample['turn_context_event']], 'Observed turn model label, not provider authentication')
        measured = sample['request_usage']
        known = measured['input_tokens'] is not None
        put('request_usage', {'identity': identity, 'counts': measured} if known else None, [sample['event']],
            'Missing counters remain null; cached input is already included in input')
    else:
        for name in ('request_identity', 'model_identity', 'request_usage'):
            put(name, None, [], 'No bound main request available at this boundary')
    current = capture['latest_context_sample']
    put('context_sample', current, [current['event']] if current else [],
        'Response-time snapshot only; not live prompt occupancy' if current else capture['state'])
    for name, key, ref in (
            ('thread_usage', 'thread_cumulative_usage', capture['usage_ledger_event']),
            ('turn_usage', 'turn_cumulative_usage', capture['usage_ledger_event']),
            ('stream_usage', 'context_stream_cumulative_usage', None)):
        value = capture[key]
        # The stream ledger's direct event is not retained by legacy captures.
        # Bind its derived value to the exact source prefix, not an invented event.
        refs = [ref or {'complete_prefix_sha256': capture['source']['complete_prefix_sha256']}]
        put(name, value if any(v is not None for v in value.values()) else None, refs,
            'Separate cumulative ledger; never divide by context capacity or infer currency')
    if cursor is not None:
        # Resume verifies local bytes even if host measurement semantics are unqualified.
        rows['incremental_resume'] = fact('incremental_resume', 'OBSERVED', cursor,
            evidence=[{'complete_prefix_sha256': capture['source']['complete_prefix_sha256']}],
            reason='Complete event checkpoint verified against exact parser and local file identity')
    qualified_host = qualification() | {'observed_originator': host['originator'],
        'observed_engine_version': host['cli_version'], 'host_schema_qualified': qualified}
    result = {'format': FORMAT, 'adapter': 'codex-desktop-rollout',
              'qualification': qualified_host, 'source': deepcopy(capture['source']),
              'capabilities': rows, 'execution_authorized': False}
    return validate(result)


def _file_id(stat):
    if not stat.st_ino:
        raise ValidationError('Stable local file identity is unavailable; cursor reuse is disabled')
    return {'device': stat.st_dev, 'inode': stat.st_ino}


def _prefix(stream, size):
    stream.seek(0)
    h = hashlib.sha256()
    remaining = size
    while remaining:
        block = stream.read(min(1024 * 1024, remaining))
        if not block:
            raise ValidationError('SOURCE_TRUNCATED: preserve previous capture')
        h.update(block)
        remaining -= len(block)
    return h


def read_checkpoint(directory):
    manifest = read_bundle(directory)
    if set(manifest['files']) != {'checkpoint.json', 'report.json'}:
        raise ValidationError('Unsupported capture bundle members')
    checkpoint = json.loads((Path(directory) / 'checkpoint.json').read_bytes())
    if not isinstance(checkpoint, dict) or set(checkpoint) != {'format', 'qualification', 'session_id', 'file_identity', 'offset', 'prefix_sha256', 'state', 'parent_bundle_sha256'}:
        raise ValidationError('Unsupported checkpoint envelope')
    if checkpoint['format'] != 'pvl-context-checkpoint-1' or checkpoint['qualification'] != qualification():
        raise ValidationError('PARSER_CHANGED: preserve history and requalify before replaying into a new lineage')
    if type(checkpoint['offset']) is not int or checkpoint['offset'] <= 0 or checkpoint['offset'] != checkpoint['state'].get('offset'):
        raise ValidationError('Invalid complete-event cursor')
    return checkpoint, manifest['request_sha256']


def capture_incremental(path, expected_session_id, output, *, previous=None, max_new_bytes=MAX_NEW_BYTES, resume=False):
    """Create an immutable checkpoint/report bundle; no configuration discovery.

    `previous` must be a committed bundle. Read-only retries reuse source/request
    identity. Resume is local publication recovery, never a new model execution.
    """
    if not codex_context._text(expected_session_id):
        raise ValidationError('An explicit expected session ID is required')
    if type(max_new_bytes) is not int or not 1 <= max_new_bytes <= MAX_NEW_BYTES:
        raise ValidationError('Invalid incremental read budget')
    old, parent = read_checkpoint(previous) if previous is not None else (None, None)
    if old and old['session_id'] != expected_session_id:
        raise ValidationError('SESSION_CHANGED: cursor belongs to a different session')
    offset = old['offset'] if old else 0
    source = Path(path)
    with source.open('rb') as stream:
        before = os.fstat(stream.fileno())
        identity = _file_id(before)
        if old and identity != old['file_identity']:
            raise ValidationError('SOURCE_ROTATED: do not reuse a cursor on another file')
        if before.st_size < offset:
            raise ValidationError('SOURCE_TRUNCATED: preserve previous capture')
        hashed = _prefix(stream, offset)
        if old and hashed.hexdigest() != old['prefix_sha256']:
            raise ValidationError('PREFIX_CHANGED: do not reuse prior parser state')
        raw = stream.read(min(max_new_bytes, before.st_size - offset))
        complete = raw[:raw.rfind(b'\n') + 1]
        trailing = len(raw) - len(complete)
        if any(len(line) > MAX_LINE_BYTES for line in complete.splitlines(keepends=True)) or trailing > MAX_LINE_BYTES:
            raise ValidationError('EVENT_TOO_LARGE: no cursor advancement')
        if not complete and raw and len(raw) == max_new_bytes and offset + len(raw) < before.st_size:
            raise ValidationError('READ_BUDGET_TOO_SMALL_FOR_EVENT: increase the bounded batch size')
        if old is None and not complete:
            raise ValidationError('No complete native metadata event')
        hashed.update(complete)
        new_offset = offset + len(complete)
        # Recheck bytes and identity after the read. Detect concurrent replacement
        # and mutation; a later change will be caught by the next resume.
        if _prefix(stream, new_offset).hexdigest() != hashed.hexdigest():
            raise ValidationError('SOURCE_CHANGED_DURING_READ')
        after = source.stat()
        if identity != _file_id(after) or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValidationError('SOURCE_CHANGED_DURING_READ')
    previous_state = old['state'] if old else None
    parsed, state = codex_context.parse_events(complete, expected_session_id, previous_state)
    snapshot = codex_context.render_capture(parsed, offset + len(raw), trailing, hashed.hexdigest())
    more = offset + len(raw) < before.st_size
    if more:
        snapshot['state'], snapshot['latest_context_sample'] = 'MORE_EVENTS_AVAILABLE', None
    checkpoint = {'format': 'pvl-context-checkpoint-1', 'qualification': qualification(),
                  'session_id': expected_session_id, 'file_identity': identity,
                  'offset': new_offset, 'prefix_sha256': hashed.hexdigest(), 'state': state,
                  'parent_bundle_sha256': parent}
    old_pending = previous_state['pending_sample'] if previous_state else None
    updates = [s for s in snapshot['samples'] if old_pending is None or s != old_pending]
    old_seen = set(previous_state['seen']) if previous_state else set()
    new_ids = sorted(set(state['seen']) - old_seen)
    contract = capabilities(snapshot, cursor={'complete_bytes': new_offset, 'parser_version': PARSER_VERSION})
    report = {'format': 'pvl-incremental-context-report-1', 'state': snapshot['state'],
              'parent_bundle_sha256': parent, 'checkpoint_sha256': suite_digest(checkpoint),
              'capabilities': contract, 'claims': resolve_requirements(contract, CLAIMS),
              'new_response_ids': new_ids, 'new_response_count': len(new_ids),
              'total_unique_response_ids': len(state['seen']), 'sample_upserts': updates,
              'transitions': snapshot['transitions'], 'issues': snapshot['issues'],
              'source': snapshot['source'], 'parser_events_processed': state['line'] - (previous_state['line'] if previous_state else 0),
              'new_bytes_parsed': len(complete), 'prefix_bytes_rehashed': offset + new_offset,
              'more_events_available': more, 'pending_tail_bytes': trailing,
              'model_calls': 0, 'settled_cost_usd': None, 'provider_authenticated': False,
              'limits': ['Local integrity only; hashes do not authenticate the source or checkpoint author.',
                         'Sample upserts revise the same response identity; never add them to sample counts.',
                         'Prefix verification is linear I/O; parser work covers only new complete events.',
                         'Checkpoint identity/deduplication state grows with unique responses; source text is not stored.',
                         'As-of response sampling, not live context occupancy or independent scientific validation.']}
    encode = lambda value: (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    delivery = publish_bundle(output, {'checkpoint.json': encode(checkpoint), 'report.json': encode(report)}, resume=resume)
    return {'delivery': delivery, 'report': report}
