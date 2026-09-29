"""Report-only model localization study; human usability remains unmeasured."""
import math
from pathlib import Path

from .artifacts import sha
from .core import ValidationError, load_json, suite_digest, write_json

FIELDS = ('producer_call', 'skill_call', 'replacement_component')


def prepare(cases, output):
    """Separate de-identified reports from an author-created, committed answer key."""
    if not isinstance(cases, list) or not cases:
        raise ValidationError('Nonempty report cases required')
    ids = set()
    for case in cases:
        if (set(case) != {'id', 'report', 'answer', 'source'} or case['id'] in ids
                or not isinstance(case['report'], str) or set(case['answer']) != set(FIELDS)
                or any(not isinstance(v, str) or not v for v in case['answer'].values())):
            raise ValidationError('Unique case IDs, reports, sources and exact answer fields required')
        ids.add(case['id'])
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    packet = {'format': 'pvl-diagnostic-blind-packet-1', 'cases': [{k: c[k] for k in ('id', 'report')} for c in cases],
              'instructions': 'Read only these reports. For each id return producer_call, skill_call, replacement_component. Use UNKNOWN when the report does not establish it. Return a JSON object with a cases array. Do not infer source-code causes or fill gaps.'}
    key = {'format': 'pvl-diagnostic-answer-key-1', 'packet_sha256': suite_digest(packet),
           'cases': [{k: c[k] for k in ('id', 'answer', 'source')} for c in cases],
           'label_origin': 'AUTHOR_CONSTRUCTED_DIAGNOSTIC_ORACLE', 'independent_expert': False}
    write_json(root / 'reviewer/packet.json', packet)
    write_json(root / 'private/answer-key.json', key)
    commitment = {'packet_sha256': suite_digest(packet), 'key_sha256': suite_digest(key),
                  'human_validation': 'PENDING', 'human_accuracy': None, 'human_reading_seconds': None,
                  'blindness': 'Report only; fresh model session with tool access denied; no knowledge independence attestation'}
    write_json(root / 'commitment.json', commitment)
    return commitment


def score(directory, response, *, elapsed_seconds, response_metadata):
    root = Path(directory)
    packet, key, commitment = (load_json(root / p) for p in ('reviewer/packet.json', 'private/answer-key.json', 'commitment.json'))
    if suite_digest(packet) != commitment['packet_sha256'] or suite_digest(key) != commitment['key_sha256']:
        raise ValidationError('Blind packet or precommitted diagnostic key changed')
    if (type(elapsed_seconds) not in (int, float) or not math.isfinite(elapsed_seconds) or elapsed_seconds < 0):
        raise ValidationError('Nonnegative measured wall duration required')
    if not isinstance(response, dict) or set(response) != {'cases'} or not isinstance(response['cases'], list):
        raise ValidationError('Expected cases array; malformed output is not a correct response')
    answers = {}
    ids = {c['id'] for c in key['cases']}
    for c in response['cases']:
        if (not isinstance(c, dict) or set(c) != {'id', *FIELDS} or c['id'] not in ids or c['id'] in answers
                or any(not isinstance(c[k], str) for k in FIELDS)):
            raise ValidationError('Malformed, duplicate or foreign response case')
        answers[c['id']] = c
    rows = []
    for c in key['cases']:
        observed = answers.get(c['id'], {})
        checks = {f: observed.get(f) == c['answer'][f] for f in FIELDS}
        rows.append({'id': c['id'], 'returned': c['id'] in answers, 'expected': c['answer'],
                     'observed': {f: observed.get(f) for f in FIELDS}, 'correct': checks, 'all_correct': all(checks.values())})
    return {'format': 'pvl-diagnostic-model-review-1', 'reviewer_kind': 'EXTERNAL_MODEL',
            'packet_sha256': suite_digest(packet), 'key_sha256': suite_digest(key), 'rows': rows,
            'case_count': len(rows), 'returned_count': len(answers),
            'exact_case_accuracy': sum(r['all_correct'] for r in rows) / len(rows),
            'field_accuracy': {f: sum(r['correct'][f] for r in rows) / len(rows) for f in FIELDS},
            'model_request_wall_seconds': elapsed_seconds, 'per_case_reading_seconds': None,
            'human_validation': 'PENDING', 'human_accuracy': None, 'human_reading_seconds': None,
            'metadata': response_metadata, 'scope': 'One model report-only test against an author-created frozen key; no human usability or independent scientific validation.'}
