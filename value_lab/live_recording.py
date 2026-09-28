"""Opt-in stdio MCP recording. Live calls are explicit; replay has no fallback.

Only a tools-only session over public/de-identified data is supported. No raw
transcript or server stderr is persisted. Unexpected protocol or credential-like
content prevents publication of a cassette, without inventing missing responses.
"""
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import threading
import time

from .core import ValidationError, write_json
from .replay import record_tools, replay_message

LIMIT = 8 * 1024 * 1024
LINE_LIMIT = 1024 * 1024
_SECRET_KEY = re.compile(r'^(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret|private[_-]?key|cookie)$', re.I)
_SECRET_TEXT = re.compile(r'(?i)(?:bearer\s+[A-Za-z0-9._~+/=-]{8,}|sk-[A-Za-z0-9_-]{12,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:api[_-]?key|password|access[_-]?token)\s*[:=]\s*\S+)')


def _public(value):
    """Conservative credential tripwire, not a PHI/PII anonymization guarantee."""
    if isinstance(value, dict):
        for key, item in value.items():
            if _SECRET_KEY.match(key) and item not in (None, ''):
                raise ValidationError('Credential-like content detected; cassette withheld')
            _public(item)
    elif isinstance(value, list):
        for item in value:
            _public(item)
    elif isinstance(value, str):
        if _SECRET_TEXT.search(value):
            raise ValidationError('Credential-like content detected; cassette withheld')
        # Detect credentials embedded inside JSON text blocks too.
        if value.lstrip().startswith(('{', '[')):
            try:
                parsed = replay_message(value)
            except ValueError:
                return
            _public(parsed)


def _id(value):
    if type(value) not in (str, int):
        raise ValidationError('MCP recording requires a string or integer request id')
    return (type(value).__name__, value)


def record_live(command, output, selected_tools, source, sink, *, public_data=False,
                timeout_seconds=300, environment=None):
    """Proxy one bounded session and automatically publish its exact cassette.

    Backend execution is trusted local execution, NOT an OS sandbox. The caller
    selects the server, tools and explicit environment. No retries or paid-provider
    discovery. Inputs/responses reach the client live; persistence is all-or-none.
    """
    if (not public_data or not command or not selected_tools or len(set(selected_tools)) != len(selected_tools)
            or any(not isinstance(name, str) or not name for name in selected_tools)
            or not 0 < timeout_seconds <= 3600):
        raise ValidationError('Select tools, acknowledge public data, and supply a bounded server command')
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    receipt = {'format': 'pvl-live-recording-1', 'status': 'RECORDING_STARTED',
               'mode': 'LIVE_TOOL_RECORDING', 'backend_calls_started': 0, 'responses_recorded': 0,
               'cost': 'UNKNOWN', 'scientific_execution': 'NOT_INFERRED_FROM_TOOL_PROTOCOL',
               'independent_validation': False}
    write_json(root / 'recording.json', receipt)
    proc, server_reader, candidate, stop = None, None, None, threading.Event()
    events = queue.Queue(maxsize=32)
    deadline = time.monotonic() + timeout_seconds
    def feed(kind, stream):
        try:
            while not stop.is_set():
                line = stream.readline(LINE_LIMIT + 1)
                item = (kind, line)
                while not stop.is_set():
                    try:
                        events.put(item, timeout=.1)
                        break
                    except queue.Full:
                        continue
                if not line or len(line) > LINE_LIMIT:
                    break
        except (OSError, ValueError):
            try:
                events.put_nowait(('broken', ''))
            except queue.Full:
                pass
    def send(stream, message):
        # Writes run off the event loop, with a deadline even for a stalled peer.
        done = queue.Queue(maxsize=1)
        def write():
            try:
                stream.write(json.dumps(message, ensure_ascii=True, allow_nan=False) + '\n')
                stream.flush()
                done.put(True)
            except (OSError, ValueError):
                done.put(False)
        threading.Thread(target=write, daemon=True).start()
        try:
            ok = done.get(timeout=max(.001, deadline - time.monotonic()))
        except queue.Empty:
            raise ValidationError('MCP recording peer write timed out') from None
        if not ok:
            raise ValidationError('MCP recording peer disconnected')
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='strict', bufsize=1,
            env=environment, close_fds=True, start_new_session=os.name != 'nt')
        threading.Thread(target=feed, args=('client', source), daemon=True).start()
        server_reader = threading.Thread(target=feed, args=('server', proc.stdout), daemon=True)
        server_reader.start()
        pending, ids, exchanges, catalogue = {}, set(), [], None
        initialized, ready, client_closed, server_closed, total = False, False, False, False, 0
        while True:
            if client_closed and not pending:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValidationError('MCP recording timed out; incomplete cassette withheld')
            try:
                kind, line = events.get(timeout=min(.2, remaining))
            except queue.Empty:
                continue
            if kind == 'broken':
                raise ValidationError('MCP recording transport failed')
            if not line:
                if kind == 'client':
                    client_closed = True
                else:
                    server_closed = True
                    if pending:
                        raise ValidationError('MCP server exited with pending requests')
                continue
            if server_closed:
                raise ValidationError('MCP server exited before session completion')
            total += len(line.encode('utf-8'))
            if len(line) > LINE_LIMIT or total > LIMIT or not line.endswith('\n'):
                raise ValidationError('MCP recording exceeded framing or byte budget')
            msg = replay_message(line)
            if not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0':
                raise ValidationError('Expected MCP JSON-RPC object')
            if kind == 'client':
                method = msg.get('method')
                if 'id' not in msg:
                    if method == 'notifications/initialized' and initialized and not ready:
                        ready = True
                    elif method == 'notifications/cancelled':
                        raise ValidationError('Cancelled recording cannot publish a complete cassette')
                    else:
                        raise ValidationError('Unsupported client notification in tools-only recording')
                    send(proc.stdin, msg)
                    continue
                identity = _id(msg['id'])
                if identity in ids or len(ids) >= 10000:
                    raise ValidationError('Duplicate request id or request budget exceeded')
                ids.add(identity)
                params = msg.get('params', {})
                if not isinstance(params, dict):
                    raise ValidationError('Expected MCP object parameters')
                entry = {'method': method}
                if method == 'initialize' and not initialized and not pending:
                    # Server cannot initiate sampling, roots or elicitation on this proxy.
                    version = params.get('protocolVersion')
                    if version not in ('2024-11-05', '2025-03-26', '2025-06-18'):
                        version = '2025-06-18'
                    msg = {**msg, 'params': {**params, 'capabilities': {}, 'protocolVersion': version}}
                elif method == 'tools/list' and ready:
                    if params.get('cursor'):
                        raise ValidationError('Paginated catalogue is not supported by this recorder')
                elif method == 'tools/call' and ready and catalogue is not None:
                    if params.get('name') not in selected_tools or not isinstance(params.get('arguments', {}), dict):
                        raise ValidationError('Tool call is outside the selected recording boundary')
                    request = {'name': params['name'], 'arguments': params.get('arguments', {})}
                    _public(request)
                    entry['index'] = len(exchanges)
                    exchanges.append({'request': request})
                    receipt['backend_calls_started'] += 1
                    # Persist an attempt before dispatch: after a hard kill its
                    # outcome stays unknown, rather than looking like zero calls.
                    write_json(root / 'recording.json', receipt)
                else:
                    raise ValidationError('Unsupported request or incomplete MCP initialization/catalogue')
                pending[identity] = entry
                send(proc.stdin, msg)
            else:
                if 'method' in msg:
                    if 'id' not in msg and msg['method'] == 'notifications/progress':
                        send(sink, msg)
                        continue
                    raise ValidationError('Server requests or catalogue changes are unsupported during recording')
                identity = _id(msg.get('id'))
                entry = pending.pop(identity, None)
                if entry is None or ('result' in msg) == ('error' in msg):
                    raise ValidationError('Unmatched or malformed MCP response')
                if entry['method'] == 'initialize':
                    result = msg.get('result')
                    if not isinstance(result, dict) or result.get('protocolVersion') not in ('2024-11-05', '2025-03-26', '2025-06-18'):
                        raise ValidationError('MCP initialization failed or protocol is unsupported')
                    initialized = True
                    msg = {**msg, 'result': {**result, 'capabilities': {'tools': {}}}}
                elif entry['method'] == 'tools/list':
                    result = msg.get('result')
                    if not isinstance(result, dict) or result.get('nextCursor') or not isinstance(result.get('tools'), list):
                        raise ValidationError('Incomplete MCP catalogue')
                    listed = [t for t in result['tools'] if isinstance(t, dict) and t.get('name') in selected_tools]
                    if len(listed) != len(selected_tools) or {t['name'] for t in listed} != set(selected_tools):
                        raise ValidationError('Selected tool catalogue is missing or ambiguous')
                    _public(listed)
                    if catalogue is not None and catalogue != listed:
                        raise ValidationError('MCP catalogue changed during recording')
                    catalogue = listed
                    msg = {**msg, 'result': {**result, 'tools': listed}}
                else:
                    response = {k: msg[k] for k in ('result', 'error') if k in msg}
                    _public(response)
                    exchanges[entry['index']]['response'] = response
                    receipt['responses_recorded'] += 1
                send(sink, msg)
        if not ready or not catalogue or not exchanges:
            raise ValidationError('Recording contains no complete initialized tool exchanges')
        if proc.poll() not in (None, 0):
            raise ValidationError('MCP server failed at session completion')
        candidate = (catalogue, exchanges)
        receipt.update(status='RECORDING_CAPTURED')
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        # Do not persist exception text: server responses, argv and paths can contain secrets.
        receipt.update(status='RECORDING_FAILED', reason='Transport, protocol, privacy or completeness check failed; no replay cassette accepted')
    finally:
        stop.set()
        if proc is not None:
            if os.name != 'nt':
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif proc.poll() is None:
                proc.kill()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                receipt.update(status='RECORDING_FAILED', reason='Server cleanup failed')
            if server_reader is not None:
                server_reader.join(timeout=1)
            # Avoid blocking on a stream lock held by a stalled descendant.
            if server_reader is None or not server_reader.is_alive():
                proc.stdout.close()
                proc.stdin.close()
    if receipt['status'] == 'RECORDING_CAPTURED' and candidate is not None:
        try:
            saved = record_tools(root / '.pending-cassette', *candidate,
                provenance={'origin': 'recorded', 'description': 'Automatically captured live stdio MCP session; public-data acknowledgement',
                            'capture': 'tools-only-stdio', 'scientific_validity': 'NOT_ESTABLISHED'})
            (root / '.pending-cassette').rename(root / 'cassette')
            receipt.update(status='RECORDING_COMPLETE', cassette='cassette', cassette_sha256=saved['cassette_sha256'])
        except (OSError, ValueError):
            receipt.update(status='RECORDING_FAILED', reason='Cassette publication failed; pending files are not an accepted recording')
    write_json(root / 'recording.json', receipt)
    return receipt
