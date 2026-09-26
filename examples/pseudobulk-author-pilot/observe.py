"""Opt-in local stopwatch for this author pilot; human activity is self-declared.

Every invocation creates a new raw journal. No human timing is backfilled and no
diagnosis mark is treated as an adjudicated defect. No network or model calls.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import os
import time
import uuid

PHASES = ('installation', 'reading', 'preparation', 'reference', 'controls', 'execution',
          'diagnosis', 'false_positive_review', 'repair', 'retest_preparation', 'retest', 'pause')
ARMS = ('with_pvl', 'without_pvl')


def validate_session(config):
    for key in ('participant', 'problem_id', 'task_pair', 'previous_exposure', 'preparation_plan'):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError('Fill session.json: ' + key)
    if config.get('arm') not in ARMS or config.get('order') not in (1, 2) or type(config.get('order')) is not int:
        raise ValueError('Declare with_pvl/without_pvl and order 1 or 2 before starting')
    if type(config.get('maintainer_or_ai')) is not bool:
        raise ValueError('Declare maintainer_or_ai explicitly')


def evidence(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def summarize(events):
    if not events or events[0].get('event') != 'start':
        raise ValueError('Journal must begin with start')
    validate_session(events[0]['session'])
    totals = {p: 0.0 for p in PHASES}
    phase, previous, end = 'reading', 0.0, None
    milestones, help_count, errors = {}, 0, []
    for index, event in enumerate(events):
        if end is not None:
            raise ValueError('Journal contains events after end')
        current = event.get('elapsed_seconds')
        if type(current) not in (int, float) or not math.isfinite(current) or current < previous:
            raise ValueError('Invalid or decreasing stopwatch time')
        if index == 0 and current != 0:
            raise ValueError('Start must be zero')
        totals[phase] += current - previous
        previous = current
        kind = event['event']
        if kind == 'phase':
            phase = event['phase']
            if phase not in PHASES:
                raise ValueError('Unknown phase')
        elif kind == 'milestone':
            if event.get('name') not in ('understood', 'credible_retest') or not event.get('explanation') or not event.get('evidence'):
                raise ValueError('Milestone needs an explanation and evidence reference')
            if event['name'] == 'credible_retest' and 'understood' not in milestones:
                raise ValueError('Retest must follow a recorded understanding milestone')
            if event['name'] in milestones:
                raise ValueError('Do not replace a milestone; retain a new attempt')
            milestones[event['name']] = {'wall_seconds': current,
                'active_seconds': sum(v for p, v in totals.items() if p != 'pause'),
                'by_phase_seconds': dict(totals), 'explanation': event['explanation'],
                'evidence': event['evidence'], 'adjudication': 'PENDING'}
        elif kind == 'help':
            help_count += 1
        elif kind == 'end':
            end = event.get('outcome')
            if end not in ('completed', 'blocked', 'abandoned'):
                raise ValueError('Unknown end outcome')
        elif kind == 'error':
            errors.append(event.get('note'))
        elif kind != 'start' or index:
            raise ValueError('Unknown or repeated journal event')
    active = sum(v for p, v in totals.items() if p != 'pause')
    understood, retest = milestones.get('understood'), milestones.get('credible_retest')
    additional = None if not understood or not retest else {
        'active_seconds': retest['active_seconds'] - understood['active_seconds'],
        'wall_seconds': retest['wall_seconds'] - understood['wall_seconds'],
        'by_phase_seconds': {p: retest['by_phase_seconds'][p] - understood['by_phase_seconds'][p] for p in PHASES}}
    return {'session': events[0]['session'], 'outcome': end or 'INTERRUPTED_OR_OPEN',
        'observed_active_seconds': active, 'observed_wall_seconds': previous,
        'unobserved_tail_unknown': end is None, 'by_phase_seconds': totals,
        'milestones': milestones, 'diagnosis_to_retest': additional,
        'help_requests': help_count, 'errors': errors,
        'time_basis': 'SELF_DECLARED_PHASES_MONOTONIC_STOPWATCH; activity not independently observed',
        'before_journal_time': 'UNKNOWN_UNLESS_SEPARATELY_OBSERVED',
        'confirmed_defects': None, 'pvl_benefit': 'NOT_ESTABLISHED'}


def summarize_folder(base):
    runs, invalid = [], []
    for path in sorted((Path(base) / 'observations').glob('*.jsonl')):
        try:
            events = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            runs.append({'journal': path.name, 'journal_sha256': evidence(path)['sha256'], **summarize(events)})
        except (ValueError, KeyError, TypeError, OSError) as exc:
            invalid.append({'journal': path.name, 'error': str(exc)})
    # Deliberately no speed-only benefit verdict. All attempts, including broken logs, remain visible.
    return {'status': 'OBSERVATIONS_REQUIRE_REVIEW' if runs or invalid else 'AWAITING_REAL_PARTICIPANT',
        'attempts': len(runs) + len(invalid), 'runs': runs, 'invalid_journals': invalid,
        'non_maintainer_participants_declared': len({r['session']['participant'] for r in runs if not r['session']['maintainer_or_ai']}),
        'independently_verified_participants': None, 'pvl_benefit': 'NOT_ESTABLISHED',
        'comparison_rule': 'Review quality, false positives, full preparation and both matched arms before interpreting time differences'}


def main(base, output):
    base = Path(base)
    config = json.loads((base / 'session.json').read_text(encoding='utf-8-sig'))
    validate_session(config)
    config['preparation_plan_evidence'] = evidence(base / config['preparation_plan'])
    journal_dir = Path(output) / 'observations'
    journal_dir.mkdir(parents=True, exist_ok=True)
    path = journal_dir / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex + '.jsonl')
    start = time.monotonic()
    events = []
    with path.open('x', encoding='utf-8') as stream:
        def append(kind, **fields):
            event = {'event': kind, 'at': datetime.now(timezone.utc).isoformat(),
                     'elapsed_seconds': 0.0 if kind == 'start' else time.monotonic() - start, **fields}
            summarize(events + [event])  # Validate before append; flush each event for interruption recovery.
            stream.write(json.dumps(event, ensure_ascii=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
            events.append(event)
        append('start', session=config)
        print('Local journal: ' + str(path))
        print('Phase names: ' + ', '.join(PHASES))
        print('Other entries: help, error, understood, credible_retest, completed, blocked, abandoned')
        print('Current phase: reading. Use pause whenever not actively working; keep this terminal open.')
        while True:
            try:
                command = input('phase/event> ').strip()
                if command in PHASES:
                    append('phase', phase=command)
                elif command in ('help', 'error'):
                    append(command, note=input('What happened (no secrets): ').strip())
                elif command in ('understood', 'credible_retest'):
                    explanation = input('Your explanation, remaining uncertainty and reviewer status: ').strip()
                    ref = evidence(input('Local evidence file path: ').strip())
                    append('milestone', name=command, explanation=explanation, evidence=ref)
                elif command in ('completed', 'blocked', 'abandoned'):
                    append('end', outcome=command)
                    break
                else:
                    print('Unknown entry; timer continues. Use pause to stop active-time counting.')
            except (ValueError, OSError) as exc:
                print('Not recorded: ' + str(exc))
    print(json.dumps(summarize(events), ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main(Path(__file__).resolve().parent, Path(__file__).resolve().parents[2] / 'work/author-pilot')
