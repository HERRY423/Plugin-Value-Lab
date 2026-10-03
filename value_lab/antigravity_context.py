"""Bounded Antigravity SQLite/protobuf metadata reader, with no prompt export.

The wire profile was inspected in the locally installed 2.19.1 language server.
This proves field mapping, not that every database was produced by that version.
Native input/cache fields do NOT share CLI JSON semantics. Normalization remains
unqualified; no quota, cost, cumulative total or absent scalar becomes occupancy.
"""
from contextlib import closing
import sqlite3
from pathlib import Path

from .core import ValidationError
from .native_host_context import LIMIT, digest, label, sample, capabilities

BINARY_SHA256 = 'd569b7a0fb5c2e3eb6dc867be17e6cde1ad1fac94c7dcda2909d6612c7c31532'
DESCRIPTORS = {
    'CortexStepGeneratorMetadata': 'cc3c33ded137e3e7385ccf647f2b4076a90bee550facceddf6e6442f099f6213',
    'ChatModelMetadata': 'bf63488d15aaa1c0857e74cbe10eed359536a657b0b76b286a73f55efa9a913a',
    'ModelUsageStats': '9ce2f3e673907740fdb4302802adfd3d8f5fe865944152ebb411ab93d80155cf',
}


def _varint(raw, pos):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(raw):
            raise ValidationError('TRUNCATED_PROTOBUF')
        byte = raw[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            if value > 2**64 - 1:
                break
            return value, pos
    raise ValidationError('INVALID_PROTOBUF_VARINT')


def _wire(raw):
    if not isinstance(raw, bytes) or len(raw) > 8 * 1024 * 1024:
        raise ValidationError('INVALID_PROTOBUF_SIZE')
    result, pos = {}, 0
    while pos < len(raw):
        tag, pos = _varint(raw, pos)
        field, wire_type = tag >> 3, tag & 7
        if not 1 <= field < 2**29:
            raise ValidationError('INVALID_PROTOBUF_FIELD')
        if wire_type == 0:
            value, pos = _varint(raw, pos)
        else:
            if wire_type == 2:
                size, pos = _varint(raw, pos)
            elif wire_type in (1, 5):
                size = 8 if wire_type == 1 else 4
            else:
                raise ValidationError('UNSUPPORTED_PROTOBUF_WIRE_TYPE')
            if size > len(raw) - pos:
                raise ValidationError('TRUNCATED_PROTOBUF')
            value, pos = raw[pos:pos + size], pos + size
        result.setdefault(field, []).append(value)
    return result


def _one(fields, number, kind):
    values = fields.get(number, [])
    if len(values) > 1 or (values and type(values[0]) is not kind):
        raise ValidationError('CONFLICTING_PROTOBUF_SCALAR')
    return values[0] if values else None


def _text(fields, number):
    value = _one(fields, number, bytes)
    if value is None:
        return None
    try:
        value = value.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValidationError('INVALID_PROTOBUF_TEXT') from exc
    if not label(value):
        raise ValidationError('INVALID_METADATA_LABEL')
    return value


def capture(path, expected_session_id, *, schema_binary):
    if not label(expected_session_id):
        raise ValidationError('EXPLICIT_SESSION_ID_REQUIRED')
    binary = Path(schema_binary)
    if binary.stat().st_size > 512 * 1024 * 1024 or digest(binary.read_bytes()) != BINARY_SHA256:
        raise ValidationError('ANTIGRAVITY_BINARY_NOT_QUALIFIED: requalify, never guess protobuf field numbers')
    path = Path(path).resolve()
    # immutable=1 is safe only for an offline, stable DB without a WAL. Never
    # silently ignore live uncheckpointed pages or create files in account homes.
    def check_sidecars():
        for suffix in ('-wal', '-journal'):
            sidecar = Path(str(path) + suffix)
            if sidecar.exists() and sidecar.stat().st_size:
                raise ValidationError('LIVE_DATABASE_REQUIRES_COHERENT_OFFLINE_SNAPSHOT')
    check_sidecars()
    before = path.read_bytes() if path.stat().st_size <= LIMIT else None
    if before is None:
        raise ValidationError('SOURCE_TOO_LARGE')
    source_hash = digest(before)
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            metadata = db.execute('SELECT trajectory_id,cascade_id FROM trajectory_meta').fetchall()
            if len(metadata) != 1 or metadata[0][1] != expected_session_id:
                raise ValidationError('SESSION_MISMATCH')
            native_rows = db.execute('SELECT idx,data,size FROM gen_metadata ORDER BY idx').fetchall()
    except sqlite3.Error as exc:
        raise ValidationError('ANTIGRAVITY_DATABASE_SCHEMA_NOT_QUALIFIED') from exc
    check_sidecars()
    if digest(path.read_bytes()) != source_hash:
        raise ValidationError('SOURCE_CHANGED_DURING_CAPTURE')
    source = {'database_sha256': source_hash, 'read_bytes': len(before), 'offline_snapshot': True}
    session_ref = {'table': 'trajectory_meta', 'database_sha256': source_hash}
    report = {'format': 'pvl-native-host-context-1', 'host': 'antigravity-db',
              'expected_session_id': expected_session_id, 'source': source,
              'qualification': {'profile': 'antigravity-db-protobuf-2.19.1-reader',
                  'schema_qualified': True, 'producer_version': None,
                  'inspected_reader_version': '2.19.1', 'schema_binary_sha256': BINARY_SHA256,
                  'descriptor_sha256': DESCRIPTORS, 'parser_sha256': digest(Path(__file__).read_bytes()),
                  'provider_authenticated': False, 'counter_normalization_qualified': False},
              'session_event': session_ref, 'samples': [], 'raw_native_usage': [],
              'latest_context_sample': None, 'state': 'RAW_COUNTERS_ONLY_CACHE_SEMANTICS_UNQUALIFIED',
              'diagnostics': [], 'settled_cost_usd': None, 'execution_authorized': False}
    responses = set()
    for index, raw, size in native_rows:
        if type(index) is not int or index < 0 or not isinstance(raw, bytes) or size != len(raw):
            raise ValidationError('INVALID_NATIVE_METADATA_ROW')
        ref = {'table': 'gen_metadata', 'index': index, 'sha256': digest(raw), 'database_sha256': source_hash}
        outer = _wire(raw)
        chat_raw = _one(outer, 1, bytes)
        if chat_raw is None:
            report['diagnostics'].append({'code': 'NON_MODEL_GENERATION', 'event': ref})
            continue
        chat = _wire(chat_raw)
        usage_raw = _one(chat, 4, bytes)
        if usage_raw is None:
            report['diagnostics'].append({'code': 'NATIVE_USAGE_MISSING', 'event': ref})
            continue
        usage = _wire(usage_raw)
        response = _text(usage, 11) or _text(usage, 7)
        if response is None or response in responses:
            raise ValidationError('DUPLICATE_OR_MISSING_NATIVE_RESPONSE')
        responses.add(response)
        counts = {name: _one(usage, num, int) for name, num in (
            ('input_tokens', 2), ('output_tokens', 3), ('cache_write_tokens', 4), ('cache_read_tokens', 5),
            ('thinking_output_tokens', 9), ('response_output_tokens', 10))}
        # Proto3 omission cannot distinguish an absent observation from zero.
        report['raw_native_usage'].append({'response_id': response, 'native_counts': counts,
                                           'normalized': False, 'event': ref})
        row = sample(expected_session_id, response, None, _text(chat, 19), None, ref, phase='native-generator-metadata')
        report['samples'].append(row)
    report['capabilities'] = capabilities(report)
    return report
