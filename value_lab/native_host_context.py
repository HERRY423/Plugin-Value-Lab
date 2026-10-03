"""Read-only, explicitly selected native logs; no account discovery or model calls.

Claude's persisted blocks and DSH's settlements have different replacement rules.
Only qualified response counters enter the shared capability vocabulary. Raw
Antigravity counters remain raw until their cache semantics are qualified.
"""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path

from .core import ValidationError
from .host_capabilities import FORMAT, SEMANTICS, fact, validate

LIMIT = 64 * 1024 * 1024
PROFILES = {'claude-code': 'claude-persisted-2.1.288', 'dsh': 'dsh-session-v4',
            'antigravity-transcript': 'antigravity-text-transcript-unqualified'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def number(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def label(value):
    return isinstance(value, str) and 0 < len(value) <= 256 and not any(ord(c) < 32 for c in value)


def counters(raw, names):
    """Input buckets are disjoint in these two qualified profiles."""
    values = [raw.get(k) for k in names]
    if not all(number(v) for v in values):
        return None
    uncached, read, write, output = values
    total_input = uncached + read + write
    if total_input + output > 2**53 - 1:
        return None
    return {'input_tokens': total_input, 'uncached_input_tokens': uncached,
            'cached_input_tokens': read, 'cache_write_input_tokens': write,
            'output_tokens': output, 'total_tokens': total_input + output}


def read_events(path, prefix_bytes=None):
    path = Path(path)
    with path.open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValidationError('SOURCE_TOO_LARGE')
    compressed_hash = None
    if path.suffix in ('.zstd', '.zst'):
        compressed_hash = digest(raw)
        compressed = raw
        try:
            import zstandard
        except ImportError as exc:
            raise ValidationError('DSH_ZSTANDARD_REQUIRED: decompress locally or install the optional zstandard reader') from exc
        try:
            with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)) as stream:
                chunks, size = [], 0
                while size <= LIMIT:
                    chunk = stream.read(min(1024 * 1024, LIMIT + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                raw = b''.join(chunks)
        except zstandard.ZstdError as exc:
            raise ValidationError('INVALID_ZSTD_SOURCE') from exc
        if len(raw) > LIMIT:
            raise ValidationError('DECOMPRESSED_SOURCE_TOO_LARGE')
        # stream_reader can finish a truncated frame without raising. Verify
        # EOF for every concatenated frame after bounded decompression; a
        # second decode cannot expand beyond the already checked source bytes.
        remaining = compressed
        while remaining:
            decoder = zstandard.ZstdDecompressor().decompressobj()
            try:
                decoder.decompress(remaining)
            except zstandard.ZstdError as exc:
                raise ValidationError('INVALID_ZSTD_FRAME') from exc
            if not decoder.eof or len(decoder.unused_data) >= len(remaining):
                raise ValidationError('INCOMPLETE_ZSTD_FRAME')
            remaining = decoder.unused_data
    if prefix_bytes is not None:
        if type(prefix_bytes) is not int or not 0 < prefix_bytes <= len(raw):
            raise ValidationError('INVALID_PREFIX_BOUNDARY')
        raw = raw[:prefix_bytes]
    complete = raw.rfind(b'\n') + 1
    events, offset = [], 0
    for line_no, line in enumerate(raw[:complete].splitlines(keepends=True), 1):
        ref = {'line': line_no, 'byte_start': offset, 'byte_end': offset + len(line), 'sha256': digest(line)}
        offset += len(line)
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValidationError(f'INVALID_JSON_EVENT: line {line_no}') from exc
        if not isinstance(event, dict):
            raise ValidationError('EVENT_MUST_BE_OBJECT')
        timestamp = event.get('timestamp', event.get('time'))
        if label(timestamp) or number(timestamp):
            ref['native_timestamp'] = timestamp
        events.append((event, ref))
    return events, {'read_bytes': len(raw), 'complete_bytes': complete,
                    'trailing_bytes': len(raw) - complete,
                    'complete_prefix_sha256': digest(raw[:complete]),
                    'compressed_source_sha256': compressed_hash,
                    'offset_domain': 'decompressed-jsonl' if compressed_hash else 'jsonl'}


def envelope(host, session_id, source):
    if not label(session_id):
        raise ValidationError('EXPLICIT_SESSION_ID_REQUIRED')
    return {'format': 'pvl-native-host-context-1', 'host': host,
            'expected_session_id': session_id, 'source': source,
            'qualification': {'profile': PROFILES[host], 'schema_qualified': False,
                              'provider_authenticated': False,
                              'parser_sha256': digest(Path(__file__).read_bytes())},
            'session_event': None, 'samples': [], 'latest_context_sample': None,
            'state': 'NO_BOUND_RESPONSE', 'diagnostics': [], 'raw_native_usage': [],
            'settled_cost_usd': None, 'execution_authorized': False}


def sample(session, response, turn, model, counts, ref, *, phase, window=None):
    return {'session_id': session, 'response_id': response, 'turn_id': turn,
            'model': model if label(model) else None, 'request_usage': counts,
            'context_tokens': counts['total_tokens'] if counts else None,
            # These captures have no atomic response-to-capacity binding.
            'context_window': None, 'context_fraction': None,
            'phase': phase, 'event': ref}


def _claude(events, report):
    session = report['expected_session_id']
    versions, bound, ids, blocks = set(), [], set(), {}
    latest = None
    for event, ref in events:
        sid = event.get('sessionId', event.get('session_id'))
        if sid is not None:
            if sid != session:
                raise ValidationError('SESSION_MISMATCH')
            if report['session_event'] is None:
                report['session_event'] = ref
        version = event.get('version', event.get('claude_code_version'))
        if version is not None:
            versions.add(str(version))
        if event.get('type') == 'system' and event.get('subtype') in ('compact_boundary', 'microcompact_boundary'):
            latest = None
            report['state'] = 'COMPACTION_PENDING_RESPONSE'
        if event.get('type') != 'assistant':
            continue
        message = event.get('message', {})
        if not isinstance(message, dict):
            raise ValidationError('INVALID_ASSISTANT_MESSAGE')
        if event.get('isSidechain') is True or event.get('parent_tool_use_id') is not None:
            report['diagnostics'].append({'code': 'SUBAGENT_EXCLUDED', 'event': ref})
            continue
        response = message.get('id')
        # SDK stream blocks often have output=0 and no stop_reason. Do not
        # reconcile a session-wide result back to one request by subtraction.
        if message.get('stop_reason') not in ('end_turn', 'tool_use', 'max_tokens', 'stop_sequence', 'pause_turn', 'refusal'):
            latest = None
            report['state'] = 'UNSETTLED_RESPONSE'
            report['diagnostics'].append({'code': 'UNSETTLED_RESPONSE', 'event': ref})
            continue
        if sid != session or version != '2.1.288' or not label(response):
            latest = None
            report['state'] = 'UNBOUND_RESPONSE'
            continue
        uuid = event.get('uuid')
        if not label(uuid) or uuid in ids:
            raise ValidationError('DUPLICATE_OR_MISSING_EVENT_ID')
        ids.add(uuid)
        raw = message.get('usage', {})
        counts = counters(raw, ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'output_tokens')) if isinstance(raw, dict) else None
        row = sample(session, response, None, message.get('model'), counts, ref, phase='persisted-final-assistant')
        if response in blocks:
            previous = blocks[response]
            # Multiple native apiBlockIndex records share a final response.
            index = event.get('apiBlockIndex')
            if (not bound or bound[-1]['response_id'] != response or not number(index) or index in previous['indices'] or
                    previous['row']['request_usage'] != counts or previous['row']['model'] != row['model']):
                raise ValidationError('CONFLICTING_RESPONSE_BLOCKS')
            previous['indices'].add(index)
            previous['row']['block_events'].append(ref)
            continue
        index = event.get('apiBlockIndex')
        if not number(index):
            latest = None
            report['state'] = 'MISSING_NATIVE_BLOCK_ID'
            continue
        row['block_events'] = [ref]
        blocks[response] = {'indices': {index}, 'row': row}
        bound.append(row)
        latest = row if counts and row['model'] else None
        report['state'] = 'POST_RESPONSE_SAMPLE' if latest else 'MISSING_OR_INVALID_COUNTERS'
    qualified = versions == {'2.1.288'} and report['session_event'] is not None
    report['qualification'].update(schema_qualified=qualified, observed_versions=sorted(versions))
    report['samples'] = bound if qualified else []
    report['latest_context_sample'] = latest if qualified else None
    if not qualified:
        report['state'] = 'HOST_VERSION_NOT_QUALIFIED'


def _dsh(events, report):
    if not events or events[0][0].get('type') != 'session':
        raise ValidationError('DSH_SESSION_HEADER_REQUIRED')
    header, ref = events[0]
    if header.get('id') != report['expected_session_id']:
        raise ValidationError('SESSION_MISMATCH')
    qualified = type(header.get('version')) is int and header['version'] == 4
    report['session_event'] = ref
    report['qualification'].update(schema_qualified=qualified, observed_format_version=header.get('version'),
                                    application_version=None)
    model, turn, step, last_seq, retry, slot = None, None, None, -1, 0, None
    slots = {}
    for event, ref in events[1:]:
        seq = event.get('seq')
        if not number(seq) or seq <= last_seq:
            raise ValidationError('DSH_SEQUENCE_NOT_STRICTLY_INCREASING')
        last_seq = seq
        ref = {**ref, 'seq': seq}
        kind, data = event.get('type'), event.get('data', {})
        if not isinstance(kind, str) or not isinstance(data, dict):
            raise ValidationError('INVALID_DSH_EVENT')
        if kind == 'session':
            raise ValidationError('MULTIPLE_SESSION_HEADERS')
        if 'compact' in kind or event.get('surfaceOp') == 'replace' or kind in ('turn/start', 'model/selection', 'request/context'):
            report['latest_context_sample'] = None
            report['state'] = 'CONTEXT_CHANGED_PENDING_RESPONSE'
        if kind == 'model/selection':
            model = None
        if kind == 'request/context':
            model = data.get('model')
        if kind == 'turn/start':
            turn, step = data.get('turn'), None
        if kind == 'step/start':
            turn, step, retry = data.get('turn'), data.get('step'), 0
        if kind == 'llm/retry-started':
            if data.get('turn') != turn or data.get('step') != step:
                raise ValidationError('DSH_UNBOUND_RETRY')
            retry += 1
            slot = None
        if kind not in ('assistant/message', 'assistant/attempt'):
            continue
        if not number(turn) or not number(step) or data.get('turn') != turn or data.get('step') != step:
            raise ValidationError('DSH_UNBOUND_SETTLEMENT')
        raw = data.get('usage') if kind == 'assistant/message' else None
        if raw is None:
            stream = data.get('stream', [])
            if not isinstance(stream, list):
                raise ValidationError('INVALID_DSH_STREAM')
            raw = next((chunk.get('usage') for chunk in reversed(stream) if isinstance(chunk, dict) and chunk.get('type') == 'usage'), None)
        if not isinstance(raw, dict):
            report['latest_context_sample'] = None
            report['state'] = 'MISSING_OR_INVALID_COUNTERS'
            report['diagnostics'].append({'code': 'SETTLEMENT_WITHOUT_USAGE', 'event': ref})
            continue
        counts = counters(raw, ('inputTokens', 'cacheReadTokens', 'cacheWriteTokens', 'outputTokens'))
        if counts and raw.get('totalTokens') is not None and (not number(raw['totalTokens']) or raw['totalTokens'] != counts['total_tokens']):
            counts = None
        key = (turn, step, retry)
        row = sample(report['expected_session_id'], f'settlement:{turn}:{step}:{retry}', turn, model, counts, ref,
                     phase='settled-assistant-message' if kind == 'assistant/message' else 'failed-or-partial-attempt')
        row['step'] = step
        row['settlement_kind'] = kind
        if slot == key:
            report['samples'][slots[key]] = row
        else:
            if key in slots:
                raise ValidationError('DSH_NONADJACENT_SETTLEMENT_REUSE')
            slots[key] = len(report['samples'])
            report['samples'].append(row)
        slot = key
        good = counts and row['model'] and kind == 'assistant/message'
        report['latest_context_sample'] = row if good else None
        report['state'] = 'POST_RESPONSE_SAMPLE' if good else 'PARTIAL_OR_INVALID_RESPONSE'
    if not qualified:
        report['samples'], report['latest_context_sample'] = [], None
        report['state'] = 'HOST_FORMAT_NOT_QUALIFIED'


def capabilities(report):
    rows = {name: fact(name, 'NOT_PROVIDED', reason='This capture does not establish this capability') for name in SEMANTICS}
    qualified = report['qualification']['schema_qualified']
    def put(name, value, refs, reason):
        status = 'OBSERVED' if value is not None else 'UNKNOWN'
        if not qualified:
            status, value = 'UNSUPPORTED', None
        rows[name] = fact(name, status, value, evidence=refs if status == 'OBSERVED' else (), reason=reason)
    put('session_identity', {'session_id': report['expected_session_id']} if report['session_event'] else None,
        [report['session_event']], 'Session ID bound to native source, not filename or operator assertion')
    last = report['samples'][-1] if report['samples'] else None
    identity = {k: last[k] for k in ('session_id', 'turn_id', 'response_id')} if last else None
    refs = [last['event']] if last else []
    put('request_identity', identity if identity and identity['turn_id'] is not None else None, refs,
        'Native response and turn binding' if identity and identity['turn_id'] is not None else
        'Native response ID may be retained in samples, but complete response/turn semantics are unavailable')
    put('model_identity', last['model'] if last else None, refs, 'Native model label, not authenticated provider identity')
    put('request_usage', {'identity': identity, 'counts': last['request_usage']} if last and last['request_usage'] else None,
        refs, 'Normalized input includes cache exactly once; raw unknowns are never zero-filled')
    current = report['latest_context_sample']
    put('context_sample', current, [current['event']] if current else [],
        'Post-response input plus output sample; capacity and live occupancy unknown' if current else report['state'])
    return validate({'format': FORMAT, 'adapter': report['host'], 'qualification': deepcopy(report['qualification']),
                     'source': deepcopy(report['source']), 'capabilities': rows, 'execution_authorized': False})


def capture(path, expected_session_id, *, host, prefix_bytes=None):
    if host not in PROFILES:
        raise ValidationError('UNKNOWN_NATIVE_HOST_PROFILE')
    events, source = read_events(path, prefix_bytes)
    report = envelope(host, expected_session_id, source)
    if host == 'claude-code':
        _claude(events, report)
    elif host == 'dsh':
        _dsh(events, report)
    else:
        # Text-only Antigravity transcripts contain no session/version/model/
        # usage binding. Their directory names cannot establish these facts.
        report['state'] = 'TRANSCRIPT_LACKS_NATIVE_USAGE_AND_IDENTITY'
        report['diagnostics'] = [{'code': report['state'], 'event_count': len(events)}]
    if source['trailing_bytes']:
        report['latest_context_sample'] = None
        report['state'] = 'INCOMPLETE_TRAILING_EVENT'
    report['capabilities'] = capabilities(report)
    return report
