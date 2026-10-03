"""Read-only Codex desktop rollout adapter, qualified for engine 0.159.2.

Usage events are local host observations, not provider attestation. This adapter
never reads prompts into its output, launches a model, estimates missing counts,
or turns token counters into monetary charges. It samples completed responses;
it does not measure the continuously changing prompt between responses.
"""
import hashlib
import json
from datetime import datetime
from pathlib import Path

from .core import ValidationError

SUPPORTED_VERSIONS = frozenset({'0.159.2'})
FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
          'output_tokens', 'reasoning_output_tokens', 'total_tokens')
MAX_BYTES = 64 * 1024 * 1024


def _usage(value):
    value = value if isinstance(value, dict) else {}
    result = {}
    for key in FIELDS:
        n = value.get(key)
        if n is not None and (type(n) is not int or not 0 <= n <= 2**53 - 1):
            raise ValidationError('Invalid native token counter: ' + key)
        result[key] = n
    return result


def _text(value):
    return value if isinstance(value, str) and value.strip() else None


def _timestamp(value):
    try:
        return value if isinstance(value, str) and datetime.fromisoformat(value).utcoffset() is not None else None
    except ValueError:
        return None


def capture(path, expected_session_id, *, prefix_bytes=None):
    """Capture one explicit local rollout, optionally replaying an exact prefix.

    No directory discovery, configuration writes, external calls or background
    polling. The caller retains the source privately. Exported references bind
    offsets and hashes without exporting conversation text or local paths.
    """
    if not _text(expected_session_id):
        raise ValidationError('An explicit expected session ID is required')
    if prefix_bytes is not None and (type(prefix_bytes) is not int or not 0 < prefix_bytes <= MAX_BYTES):
        raise ValidationError('Invalid native capture prefix length')
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1 if prefix_bytes is None else prefix_bytes)
    if len(raw) > MAX_BYTES or (prefix_bytes is not None and len(raw) != prefix_bytes):
        raise ValidationError('Native capture exceeds limit or retained prefix is unavailable')
    complete = raw[:raw.rfind(b'\n') + 1]
    trailing = len(raw) - len(complete)
    if not complete:
        raise ValidationError('No complete native events')
    result, _ = parse_events(complete, expected_session_id)
    return render_capture(result, len(raw), trailing, hashlib.sha256(complete).hexdigest())


def parse_events(complete, expected_session_id, checkpoint=None):
    """Adapter-private state machine; parse only complete new lines.

    The durable layer binds checkpoint bytes to the parser identity. A carried
    pending sample is an upsert, never a second independent request.
    """
    samples, transitions, issues = [], [], []
    meta, turn, model, turn_ref = None, None, None, None
    pending, current, last_measured = None, None, None
    state, epoch, offset = 'NO_MEASUREMENT', 0, 0
    seen, completed_turns = set(), set()
    stream_cumulative = _usage(None)
    thread_cumulative, turn_cumulative = _usage(None), _usage(None)
    cumulative_ref = None
    number = 0
    if checkpoint is not None:
        from copy import deepcopy
        c = deepcopy(checkpoint)
        meta, turn, model, turn_ref = c['meta'], c['turn'], c['model'], c['turn_ref']
        current, last_measured, state = c['current'], c['last_measured'], c['state']
        epoch, offset, number = c['epoch'], c['offset'], c['line']
        seen, completed_turns = set(c['seen']), set(c['completed_turns'])
        stream_cumulative = c['stream_cumulative']
        thread_cumulative, turn_cumulative = c['thread_cumulative'], c['turn_cumulative']
        cumulative_ref = c['cumulative_ref']
        if c['pending_sample'] is not None:
            samples, pending = [c['pending_sample']], 0
    for number, line in enumerate(complete.splitlines(keepends=True), number + 1):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            raise ValidationError('Malformed complete native event at line ' + str(number)) from exc
        if not isinstance(event, dict) or not isinstance(event.get('payload'), dict):
            raise ValidationError('Invalid native event envelope')
        payload, kind = event['payload'], event.get('type')
        ordinal = event.get('ordinal')
        if ordinal is not None and (type(ordinal) is not int or not 0 <= ordinal <= 2**53 - 1):
            raise ValidationError('Invalid native event ordinal')
        ref = {'line': number, 'byte_start': offset, 'byte_end': offset + len(line),
               'sha256': hashlib.sha256(line).hexdigest(), 'timestamp': _timestamp(event.get('timestamp')),
               'ordinal': event.get('ordinal')}
        offset += len(line)
        if kind == 'session_meta':
            if meta is not None or number != 1 or payload.get('id') != expected_session_id:
                raise ValidationError('Native session metadata differs from expected session')
            meta = {k: payload.get(k) for k in ('id', 'originator', 'cli_version', 'source', 'model_provider')}
            if any(value is not None and not isinstance(value, str) for value in meta.values()):
                raise ValidationError('Invalid native host metadata')
            meta['event'] = ref
            continue
        if meta is None:
            raise ValidationError('Native session metadata must precede events')
        if kind == 'turn_context':
            if (turn, model) != (payload.get('turn_id'), payload.get('model')):
                pending, current, state = None, None, 'AWAITING_RESPONSE'
            turn, model, turn_ref = _text(payload.get('turn_id')), _text(payload.get('model')), ref
        elif kind == 'event_msg' and payload.get('type') == 'task_started':
            current, pending, state = None, None, 'AWAITING_RESPONSE'
            turn, model, turn_ref = None, None, None
        elif kind == 'event_msg' and payload.get('type') == 'task_complete':
            if _text(payload.get('turn_id')):
                completed_turns.add(payload['turn_id'])
        elif kind == 'compacted':
            response = payload.get('compaction_response_id')
            if pending is not None and samples[pending]['response_id'] == response:
                samples[pending]['kind'] = 'COMPACTION_RESPONSE'
                samples[pending]['status'] = 'EXCLUDED_FROM_MAIN_REQUESTS'
            epoch += 1
            transitions.append({'kind': 'COMPACTION', 'event': ref, 'epoch': epoch,
                                'response_id': response})
            pending, current, state = None, None, 'UNKNOWN_AFTER_COMPACTION'
        elif kind == 'token_usage_record':
            if payload.get('session_id') != expected_session_id or payload.get('thread_id') != expected_session_id:
                raise ValidationError('Native usage session/thread binding differs')
            response = _text(payload.get('response_id'))
            if not response or response in seen:
                raise ValidationError('Native response identity is missing or duplicated')
            seen.add(response)
            usage = _usage(payload.get('usage'))
            core = [usage[k] for k in ('input_tokens', 'output_tokens', 'total_tokens')]
            if None not in core and core[0] + core[1] != core[2]:
                raise ValidationError('Native response total differs from input plus output')
            if (usage['cached_input_tokens'] is not None and usage['input_tokens'] is not None
                    and usage['cached_input_tokens'] > usage['input_tokens']):
                raise ValidationError('Native cached input is not a subset of input')
            bound = bool(turn and model and ref['timestamp'] and turn_ref['timestamp']
                         and payload.get('turn_id') == turn
                         and payload.get('root_turn_id') == turn)
            if not bound:
                issues.append({'kind': 'UNBOUND_TURN_OR_MODEL', 'event': ref})
            sample = {'kind': 'MAIN_REQUEST' if bound else 'UNBOUND_REQUEST',
                      'status': 'AWAITING_CONTEXT_EVENT', 'session_id': expected_session_id,
                      'turn_id': payload.get('turn_id'), 'model': model if bound else None,
                      'response_id': response, 'epoch': epoch, 'event': ref,
                      'turn_context_event': turn_ref if bound else None,
                      'phase': 'response_usage_recorded', 'request_usage': usage,
                      'context_event': None, 'context_window_tokens': None,
                      'request_input_fraction': None, 'context_tokens_at_sample': None,
                      'context_fraction_at_sample': None}
            samples.append(sample)
            pending, current, state = len(samples) - 1, None, 'AWAITING_CONTEXT_EVENT'
            thread_cumulative = _usage(payload.get('thread_token_usage'))
            turn_cumulative = _usage(payload.get('turn_token_usage'))
            cumulative_ref = ref
        elif kind == 'event_msg' and payload.get('type') == 'token_count':
            info = payload.get('info')
            if not isinstance(info, dict):
                pending, current, state = None, None, 'UNKNOWN_CONTEXT_EVENT'
                continue
            stream_cumulative = _usage(info.get('total_token_usage'))
            last = _usage(info.get('last_token_usage'))
            window = info.get('model_context_window')
            if window is not None and (type(window) is not int or not 0 < window <= 2**53 - 1):
                raise ValidationError('Invalid native context window')
            sample = samples[pending] if pending is not None else None
            measured = (sample is not None and sample['kind'] == 'MAIN_REQUEST'
                        and ref['timestamp'] is not None
                        and sample['request_usage'] == last
                        and all(last[k] is not None for k in ('input_tokens', 'output_tokens', 'total_tokens')))
            if measured:
                sample.update({'status': 'MEASURED_RESPONSE_BOUND', 'context_event': ref,
                               'context_window_tokens': window,
                               'request_input_fraction': last['input_tokens'] / window if window else None,
                               'context_tokens_at_sample': last['total_tokens'],
                               'context_fraction_at_sample': last['total_tokens'] / window if window else None})
                current = {'response_id': sample['response_id'], 'turn_id': sample['turn_id'],
                           'model': sample['model'], 'phase': 'post_response_token_count',
                           'as_of': ref['timestamp'], 'event': ref,
                           'request_input_tokens': last['input_tokens'],
                           'context_tokens': last['total_tokens'], 'context_window_tokens': window,
                           'context_fraction': sample['context_fraction_at_sample']}
                last_measured, state = dict(current), 'MEASURED_AT_SAMPLE'
            else:
                pending, current, state = None, None, 'UNMATCHED_OR_ESTIMATED_CONTEXT'
                transitions.append({'kind': state, 'event': ref, 'epoch': epoch,
                                    'host_reported_last_usage': last, 'context_window_tokens': window,
                                    'measured_context_tokens': None})
    checkpoint = dict(meta=meta, turn=turn, model=model, turn_ref=turn_ref,
        current=current, last_measured=last_measured, state=state, epoch=epoch,
        offset=offset, line=number, seen=sorted(seen), completed_turns=sorted(completed_turns),
        stream_cumulative=stream_cumulative, thread_cumulative=thread_cumulative,
        turn_cumulative=turn_cumulative, cumulative_ref=cumulative_ref,
        pending_sample=samples[pending] if pending is not None else None)
    result = dict(checkpoint=checkpoint, samples=samples, transitions=transitions, issues=issues)
    return result, checkpoint


def render_capture(parsed, read_bytes, trailing, prefix_sha256):
    """Legacy snapshot presentation; never mutate resumable parser state."""
    from copy import deepcopy
    c = deepcopy(parsed['checkpoint'])
    meta, state, current = c['meta'], c['state'], c['current']
    last_measured = c['last_measured']
    samples = deepcopy(parsed['samples'])
    transitions, issues = parsed['transitions'], parsed['issues']
    thread_cumulative, turn_cumulative = c['thread_cumulative'], c['turn_cumulative']
    stream_cumulative, cumulative_ref = c['stream_cumulative'], c['cumulative_ref']
    completed_turns = c['completed_turns']
    if trailing:
        current, state = None, 'INCOMPLETE_TRAILING_EVENT'
    supported = meta['originator'] == 'codex_work_desktop' and meta['cli_version'] in SUPPORTED_VERSIONS
    if not supported:
        current, state = None, 'UNSUPPORTED_HOST_VERSION'
        for sample in samples:
            sample['status'] = 'UNSUPPORTED_HOST_VERSION'
    return {'format': 'pvl-codex-context-capture-1', 'host': meta,
            'adapter_supported': supported, 'source': {
                'read_bytes': read_bytes, 'complete_bytes': c['offset'], 'trailing_bytes': trailing,
                'complete_prefix_sha256': prefix_sha256},
            'state': state, 'latest_context_sample': current,
            'last_measured_context_sample': last_measured if supported else None,
            'thread_cumulative_usage': thread_cumulative, 'turn_cumulative_usage': turn_cumulative,
            'usage_ledger_event': cumulative_ref, 'context_stream_cumulative_usage': stream_cumulative,
            'settled_cost_usd': None, 'samples': samples, 'transitions': transitions,
            'completed_turns': sorted(completed_turns), 'issues': issues,
            'scope': 'Local Codex desktop rollout, engine 0.159.2; response-bound samples only.',
            'definitions': {
                'request_input': 'usage.input_tokens includes cached input; never add cache again.',
                'context_at_sample': 'Matched last_token_usage.total_tokens after a response; input plus output, not cumulative spend.',
                'burden_input': 'Use request_input_fraction for the existing main-agent input-peak metric; do not substitute post-response total.',
                'cumulative': 'Separate host ledgers. Never divide cumulative usage by context capacity or infer monetary charges.',
                'unknown': 'Absent/mismatched/estimated observations remain unknown, including after compaction.',
                'freshness': 'As-of event snapshot, not the live prompt after later tools, messages or compaction.'},
            'claim_limits': ['Local file observations are not independent provider attestation.',
                             'No other host or engine version is qualified by this capture.',
                             'No complete experiment, plugin benefit, settled fee or recommendation follows.']}
