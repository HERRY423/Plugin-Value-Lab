"""Collector adapter for submitted observations; never contacts a host."""
from .burden_contracts import BurdenCollection, ContextRun
from .core import ValidationError, suite_digest
from .science import keys
from .task_selection import _text, _sha


def _integer(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValidationError('Invalid bounded integer in context observations')


def collect(design, observations, submitted=None):
    """Validate and detach submitted samples, without I/O or scoring.

    Design and original observations must pass the combination validator first.
    Future host adapters emit the existing sidecar format. Coverage declarations
    remain unauthenticated; absent input stays absent.
    """
    def snapshot(runs=(), measurement=None):
        suite = design['spec']['suite']
        return BurdenCollection(
            design_sha256=suite_digest(design), observations_sha256=suite_digest(observations),
            context_observations_sha256=suite_digest(submitted) if submitted is not None else None,
            case_ids=tuple(c['id'] for c in suite['cases']), runs_per_case=suite['runs_per_case'],
            measurement=tuple(measurement.items()) if measurement is not None else None,
            runs=tuple(runs))
    if submitted is None:
        return snapshot()
    keys(submitted, 'format design_sha256 measurement runs')
    if submitted['format'] != 'pvl-context-observations-1' or submitted['design_sha256'] != suite_digest(design):
        raise ValidationError('Context observations must bind the original design')
    measurement = submitted['measurement']
    keys(measurement, 'host model host_version source sampling context_window_tokens')
    for name in ('host', 'model', 'host_version', 'source'):
        _text(measurement[name])
    if any(measurement[k] != design['spec']['suite']['conditions'][k] for k in ('host', 'model')):
        raise ValidationError('Context host/model differs from the frozen conditions')
    if measurement['sampling'] != 'each_main_agent_request':
        raise ValidationError('Context sampling must cover each main-agent request')
    _integer(measurement['context_window_tokens'], 1, 2**53 - 1)
    originals = {(r['case_id'], r['repetition'], r['arm']): r for r in observations['runs']}
    runs = submitted['runs']
    if not isinstance(runs, list) or len(runs) > len(originals):
        raise ValidationError('Context observations exceed original runs')
    result, seen, sample_count = [], set(), 0
    for row in runs:
        keys(row, 'case_id repetition arm session_id record_sha256 coverage expected_samples samples')
        _text(row['case_id'])
        _text(row['arm'])
        _text(row['session_id'])
        _sha(row['record_sha256'])
        _integer(row['repetition'], 1, 50)
        key = (row['case_id'], row['repetition'], row['arm'])
        if key not in originals or key in seen:
            raise ValidationError('Unexpected or duplicate context run')
        original = originals[key]['record']
        if row['session_id'] != original['session_id'] or row['record_sha256'] != suite_digest(original):
            raise ValidationError('Context run session or original record digest differs')
        if row['coverage'] not in ('complete', 'partial'):
            raise ValidationError('Declare complete or partial context coverage')
        _integer(row['expected_samples'], 1, 10000)
        samples = row['samples']
        if not isinstance(samples, list) or len(samples) > row['expected_samples']:
            raise ValidationError('Invalid context sample count')
        sample_count += len(samples)
        if sample_count > 100000:
            raise ValidationError('Context sample budget exceeded')
        previous = 0
        for sample in samples:
            keys(sample, 'request_index input_tokens')
            _integer(sample['request_index'], 1, row['expected_samples'])
            _integer(sample['input_tokens'], 0, 2**53 - 1)
            if sample['request_index'] <= previous:
                raise ValidationError('Context request indices must be unique and increasing')
            previous = sample['request_index']
        seen.add(key)
        result.append(ContextRun(
            case_id=row['case_id'], repetition=row['repetition'], arm=row['arm'],
            session_id=row['session_id'], record_sha256=row['record_sha256'],
            coverage=row['coverage'], expected_samples=row['expected_samples'],
            samples=tuple((s['request_index'], s['input_tokens']) for s in samples)))
    return snapshot(result, measurement)
