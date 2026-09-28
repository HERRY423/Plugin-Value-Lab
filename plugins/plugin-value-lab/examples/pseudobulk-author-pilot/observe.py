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
import re
import time
import uuid

PHASES = ('installation', 'reading', 'preparation', 'reference', 'controls', 'execution',
          'diagnosis', 'false_positive_review', 'repair', 'retest_preparation', 'retest', 'pause')
ARMS = ('with_pvl', 'without_pvl')


def validate_session(config):
    if not isinstance(config, dict):
        raise ValueError('Session must be an object')
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
    if not isinstance(events, list) or not events or any(not isinstance(e, dict) for e in events) or events[0].get('event') != 'start':
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
        'started_at': events[0].get('at'),
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
            events = [_read_json_line(line) for line in path.read_text(encoding='utf-8').splitlines()]
            runs.append({'journal': path.name, 'journal_sha256': evidence(path)['sha256'], **summarize(events)})
        except (ValueError, KeyError, TypeError, OSError) as exc:
            invalid.append({'journal': path.name, 'error': str(exc)})
    # Deliberately no speed-only benefit verdict. All attempts, including broken logs, remain visible.
    result = {'status': 'OBSERVATIONS_REQUIRE_REVIEW' if runs or invalid else 'AWAITING_REAL_PARTICIPANT',
        'attempts': len(runs) + len(invalid), 'runs': runs, 'invalid_journals': invalid,
        'non_maintainer_participants_declared': len({r['session']['participant'] for r in runs if not r['session']['maintainer_or_ai']}),
        'independently_verified_participants': None, 'pvl_benefit': 'NOT_ESTABLISHED',
        'comparison_rule': 'Review quality, false positives, full preparation and both matched arms before interpreting time differences'}
    result['burden_comparison'] = compare_burden(base, runs, invalid)
    return result


def _read_json(path):
    return _read_json_line(Path(path).read_text(encoding='utf-8-sig'))


def _read_json_line(line):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate JSON key: ' + key)
            value[key] = item
        return value
    def invalid(value):
        raise ValueError('Nonfinite JSON: ' + value)
    return json.loads(line, object_pairs_hook=unique, parse_constant=invalid)


def _amount(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('Expected finite nonnegative amount')
    return value


def _stamp(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Timer timestamps need a timezone')
    return stamp.timestamp()


def _pin(base, ref):
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
        raise ValueError('Evidence needs path and SHA-256')
    base = Path(base).resolve()
    path = (base / ref['path']).resolve()
    if not path.is_relative_to(base) or not path.is_file() or path.is_symlink():
        raise ValueError('Evidence must be a file inside the observation packet')
    if evidence(path)['sha256'] != ref['sha256']:
        raise ValueError('Evidence changed: ' + ref['path'])
    return path


def validate_burden_plan(plan):
    if not isinstance(plan, dict) or plan.get('format') != 'pvl-author-burden-plan-1' or plan.get('status') != 'FROZEN':
        raise ValueError('Complete and freeze the burden plan before observation')
    for key in ('study_id', 'baseline', 'pairing_rationale', 'quality_rule', 'allocation_rationale'):
        if not isinstance(plan.get(key), str) or not plan[key].strip():
            raise ValueError('Plan needs ' + key)
    _amount(plan.get('hourly_usd'))
    if _amount(plan.get('shared_with_fraction')) > 1:
        raise ValueError('Invalid shared allocation')
    pairs = plan.get('pairs')
    if not isinstance(pairs, list) or not pairs:
        raise ValueError('Plan needs matched pairs')
    ids = set()
    for pair in pairs:
        if not isinstance(pair.get('id'), str) or not re.fullmatch('[A-Za-z0-9_-]+', pair['id']) or pair['id'] in ids:
            raise ValueError('Pair identifiers must be unique and safe')
        ids.add(pair['id'])
        if not isinstance(pair.get('participant'), str) or not pair['participant'].strip():
            raise ValueError('Declare participant pseudonym')
        if pair.get('order') not in (list(ARMS), list(reversed(ARMS))):
            raise ValueError('Freeze arm order')
        if not isinstance(pair.get('problems'), dict) or set(pair['problems']) != set(ARMS) or any(
                not isinstance(v, str) or not v.strip() for v in pair['problems'].values()):
            raise ValueError('Freeze the problem assigned to each arm')
        if type(pair.get('max_attempts')) is not int or pair['max_attempts'] < 1:
            raise ValueError('Freeze maximum attempts per arm')
        if _amount(pair.get('active_limit_seconds')) <= 0:
            raise ValueError('Freeze a positive active time limit per arm')
        _amount(pair.get('cash_limit_usd'))


def compare_burden(base, runs, invalid):
    """All-attempt paired descriptive burden; never a speed-only benefit verdict.

    Sidecars bind a prospective plan, supplemental timers/cash and outcome review.
    Digests check bytes, not human identity, review independence or preregistration.
    """
    base = Path(base)
    result = {'status': 'AWAITING_PLAN', 'pairs': [], 'blockers': [], 'pvl_benefit': 'NOT_ESTABLISHED',
              'independent_review': 'NOT_ESTABLISHED', 'mean_active_seconds_saved': None,
              'mean_total_usd_saved': None, 'new_human_observations_created': 0}
    if not (base / 'burden-plan.json').exists():
        return result
    try:
        plan = _read_json(base / 'burden-plan.json')
        if plan.get('status') == 'DRAFT':
            result['status'] = 'DRAFT_NOT_MEASUREMENT'
            return result
        validate_burden_plan(plan)
        digest = evidence(base / 'burden-plan.json')['sha256']
        result['plan_sha256'] = digest
        result['scope'] = 'Submitted timer and review evidence, not authenticated human activity. Sum of journal wall durations is not calendar makespan. Paired differences are descriptive, not causal or population estimates.'
        if not runs and not invalid:
            result['status'] = 'AWAITING_REAL_PARTICIPANT'
            return result
        ledger, review = (_read_json(base / name) for name in ('burden-ledger.json', 'burden-reviews.json'))
        for obj, fmt in ((ledger, 'pvl-author-burden-ledger-1'), (review, 'pvl-author-burden-reviews-1')):
            if obj.get('format') != fmt or obj.get('plan_sha256') != digest:
                raise ValueError('Ledger/review must bind the exact frozen plan')
        coverage, entries = ledger['coverage'], ledger['entries']
        if not isinstance(coverage, dict) or not isinstance(entries, list) or not isinstance(review['entries'], list):
            raise ValueError('Malformed ledger/review collections')
        result['input_hashes'] = {name: evidence(base / name)['sha256'] for name in ('burden-ledger.json', 'burden-reviews.json')}
        pairmap = {p['id']: p for p in plan['pairs']}
        buckets = {(p, a): [] for p in pairmap for a in ARMS}
        hashes, reviewmap, intervals = set(), {}, []
        blockers = result['blockers']
        if invalid:
            blockers.append('Invalid journals remain in the attempt inventory')
        for row in review['entries']:
            key = row['journal_sha256']
            if key in reviewmap or row.get('decision') not in ('usable', 'unusable', 'unknown'):
                raise ValueError('Duplicate or invalid outcome review')
            if not isinstance(row.get('reviewer'), str) or not row['reviewer'].strip():
                raise ValueError('Reviewer pseudonym is required')
            for field in ('false_alarms', 'confirmed_defects'):
                if row.get(field) is not None and (type(row[field]) is not int or row[field] < 0):
                    raise ValueError('Review counts must be nonnegative integers or unknown')
            _pin(base, row['evidence'])
            reviewmap[key] = row
        for run in runs:
            s, sha = run['session'], run['journal_sha256']
            if sha in hashes:
                blockers.append('Duplicate journal bytes; cannot count repeated evidence as another attempt')
            hashes.add(sha)
            pair = pairmap.get(s['task_pair'])
            if pair is None:
                blockers.append('Unplanned attempt: ' + run['journal'])
                continue
            arm = s['arm']
            buckets[pair['id'], arm].append(run)
            if (s['participant'] != pair['participant'] or s['problem_id'] != pair['problems'][arm]
                    or s['order'] != pair['order'].index(arm) + 1):
                blockers.append('Task/participant/order differs from plan: ' + run['journal'])
            if s.get('burden_plan_evidence', {}).get('sha256') != digest:
                blockers.append('Journal not bound to frozen burden plan: ' + run['journal'])
            if run['unobserved_tail_unknown']:
                blockers.append('Interrupted observation has unknown tail: ' + run['journal'])
            judged = reviewmap.get(sha)
            if judged is None or judged['decision'] == 'unknown' or any(judged.get(k) is None for k in ('false_alarms', 'confirmed_defects')):
                blockers.append('Outcome or false-alarm review unresolved: ' + run['journal'])
            if judged and judged['decision'] == 'usable' and run['outcome'] != 'completed':
                blockers.append('Uncompleted attempt cannot be reviewed as a usable delivery')
            start = _stamp(run['started_at'])
            source = _pin(base, {'path': 'observations/' + run['journal'], 'sha256': sha})
            events = [_read_json_line(line) for line in source.read_text(encoding='utf-8').splitlines()]
            phase, last = 'reading', 0
            for event in events:
                current = event['elapsed_seconds']
                if phase != 'pause' and current > last:
                    intervals.append((s['participant'], start + last, start + current))
                if event['event'] == 'phase':
                    phase = event['phase']
                last = current
        if set(reviewmap) - hashes:
            blockers.append('Review references a missing journal')
        groups = {(p, a, c): [] for p in pairmap for a in (*ARMS, 'shared') for c in ('pre_journal', 'post_journal_review', 'cash')}
        ids, refs = set(), set()
        for entry in entries:
            key = (entry['pair_id'], entry['arm'], entry['category'])
            if key not in groups or not isinstance(entry.get('id'), str) or not entry['id'].strip() or entry['id'] in ids:
                raise ValueError('Duplicate entry or unplanned ledger allocation')
            ids.add(entry['id'])
            _pin(base, entry['evidence'])
            ref = (entry['evidence']['sha256'], entry.get('evidence_line'))
            if not isinstance(ref[1], str) or not ref[1].strip() or ref in refs:
                raise ValueError('Every ledger item needs a unique evidence line to prevent double counting')
            refs.add(ref)
            if entry['category'] == 'cash':
                if entry.get('basis') not in ('estimate', 'settled'):
                    raise ValueError('Cash needs estimate/settled basis')
                value = entry.get('amount_usd')
                if value is not None:
                    _amount(value)
            else:
                if not isinstance(entry.get('intervals'), list) or not entry['intervals']:
                    raise ValueError('Supplemental labor requires raw intervals')
                value = 0
                for timer in entry['intervals']:
                    if not isinstance(timer.get('actor'), str) or not timer['actor'].strip():
                        raise ValueError('Supplemental timer needs actor pseudonym')
                    start, end = _stamp(timer['start']), _stamp(timer['end'])
                    value += _amount(end - start)
                    intervals.append((timer['actor'], start, end))
            groups[key].append((value, entry.get('basis')))
        intervals.sort()
        for previous, current in zip(intervals, intervals[1:]):
            if current[0] == previous[0] and current[1] < previous[2] - 1e-6:
                blockers.append('Overlapping timer intervals for the same actor')
        expected_coverage = {'/'.join(k) for k in groups}
        if set(coverage) != expected_coverage:
            raise ValueError('Coverage must include every planned pair/arm/category, including shared work')
        totals, settled = {}, True
        for key, values in groups.items():
            status = coverage['/'.join(key)]
            if status not in ('itemized', 'not_applicable', 'in_journal', 'unknown') or (status == 'in_journal' and (key[1] == 'shared' or key[2] == 'cash')):
                raise ValueError('Invalid burden coverage state')
            if (status == 'itemized') != bool(values):
                raise ValueError('Coverage contradicts itemized entries')
            if status == 'unknown' or any(v is None for v, _ in values):
                blockers.append('Unknown full burden: ' + '/'.join(key))
                totals[key] = None
            else:
                totals[key] = sum(v for v, _ in values)
            if key[2] == 'cash' and (totals[key] is None or any(b != 'settled' for _, b in values)):
                settled = False
        for pair in plan['pairs']:
            arms = {}
            first, second = (buckets[pair['id'], a] for a in pair['order'])
            if first and second and max(_stamp(r['started_at']) + r['observed_wall_seconds'] for r in first) > min(_stamp(r['started_at']) for r in second):
                blockers.append('Observed arm order differs from the frozen sequence: ' + pair['id'])
            for arm in ARMS:
                selected = buckets[pair['id'], arm]
                if not selected:
                    blockers.append('Missing arm: ' + pair['id'] + '/' + arm)
                if len(selected) > pair['max_attempts']:
                    blockers.append('Attempt limit exceeded: ' + pair['id'] + '/' + arm)
                fraction = plan['shared_with_fraction'] if arm == 'with_pvl' else 1 - plan['shared_with_fraction']
                supplements = {}
                for cat in ('pre_journal', 'post_journal_review', 'cash'):
                    own, shared = totals[pair['id'], arm, cat], totals[pair['id'], 'shared', cat]
                    supplements[cat] = own + fraction * shared if own is not None and shared is not None else None
                observed = sum(r['observed_active_seconds'] for r in selected)
                active = (observed + supplements['pre_journal'] + supplements['post_journal_review']
                          if selected and None not in (supplements['pre_journal'], supplements['post_journal_review'])
                          and not any(r['unobserved_tail_unknown'] for r in selected) else None)
                cash = supplements['cash']
                if active is not None and active > pair['active_limit_seconds']:
                    blockers.append('Active-time limit exceeded: ' + pair['id'] + '/' + arm)
                if cash is not None and cash > pair['cash_limit_usd']:
                    blockers.append('Cash limit exceeded: ' + pair['id'] + '/' + arm)
                usable = sum(reviewmap.get(r['journal_sha256'], {}).get('decision') == 'usable' and r['outcome'] == 'completed' for r in selected)
                arms[arm] = {'attempts': len(selected), 'reviewed_usable_deliveries': usable,
                    'outcomes': [r['outcome'] for r in selected], 'observed_active_seconds': observed,
                    'summed_journal_wall_seconds': sum(r['observed_wall_seconds'] for r in selected),
                    'full_active_seconds': active, 'cash_usd': cash,
                    'known_cash_subtotal_usd': sum(v for v, _ in groups[pair['id'], arm, 'cash'] if v is not None) +
                        fraction * sum(v for v, _ in groups[pair['id'], 'shared', 'cash'] if v is not None),
                    'total_usd_at_frozen_rate': active * plan['hourly_usd'] / 3600 + cash if active is not None and cash is not None else None,
                    'by_phase_seconds': {p: sum(r['by_phase_seconds'][p] for r in selected) for p in PHASES},
                    'help_requests': sum(r['help_requests'] for r in selected),
                    'reviewed_defect_counts_by_attempt': [reviewmap.get(r['journal_sha256'], {}).get('confirmed_defects') for r in selected],
                    'false_alarms': sum(reviewmap[r['journal_sha256']]['false_alarms'] for r in selected)
                        if selected and all(reviewmap.get(r['journal_sha256'], {}).get('false_alarms') is not None for r in selected) else None}
            result['pairs'].append({'id': pair['id'], 'participant': pair['participant'], 'arms': arms,
                                    'active_seconds_saved': None, 'total_usd_saved': None})
        result['blockers'] = list(dict.fromkeys(blockers))
        result['cash_basis'] = 'SETTLEMENT_REFERENCES_DECLARED' if settled else 'ESTIMATED_OR_INCOMPLETE'
        for row in result['pairs']:
            a, b = row['arms']['with_pvl'], row['arms']['without_pvl']
            if not blockers and a['reviewed_usable_deliveries'] and b['reviewed_usable_deliveries']:
                row['active_seconds_saved'] = b['full_active_seconds'] - a['full_active_seconds']
                row['total_usd_saved'] = b['total_usd_at_frozen_rate'] - a['total_usd_at_frozen_rate']
        complete = not blockers and all(r['active_seconds_saved'] is not None for r in result['pairs'])
        result['status'] = 'DESCRIPTIVE_PAIRED_BURDEN' if complete else 'INCOMPLETE_OR_QUALITY_NOT_COMPARABLE'
        if complete:
            result['mean_active_seconds_saved'] = sum(r['active_seconds_saved'] for r in result['pairs']) / len(result['pairs'])
            result['mean_total_usd_saved'] = sum(r['total_usd_saved'] for r in result['pairs']) / len(result['pairs'])
        if any(r['session']['maintainer_or_ai'] for r in runs):
            result['status'] = 'MAINTAINER_OR_SIMULATION_ONLY'
        return result
    except (ValueError, KeyError, TypeError, OSError, AttributeError, OverflowError) as exc:
        result['status'] = 'INCOMPLETE_OR_INVALID_BURDEN_EVIDENCE'
        result['blockers'].append(str(exc))
        return result


def main(base, output):
    base = Path(base)
    config = json.loads((base / 'session.json').read_text(encoding='utf-8-sig'))
    validate_session(config)
    config['preparation_plan_evidence'] = evidence(base / config['preparation_plan'])
    if config.get('burden_plan'):
        plan_path = base / config['burden_plan']
        plan = _read_json(plan_path)
        validate_burden_plan(plan)
        config['burden_plan_evidence'] = evidence(plan_path)
        pair = next((p for p in plan['pairs'] if p['id'] == config['task_pair']), None)
        if pair is None or (pair['participant'], pair['problems'][config['arm']], pair['order'].index(config['arm']) + 1) != (
                config['participant'], config['problem_id'], config['order']):
            raise ValueError('Session must match a planned participant, problem, arm and order')
        destination = Path(output) / 'burden-plan.json'
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if evidence(destination)['sha256'] != config['burden_plan_evidence']['sha256']:
                raise ValueError('Preserve existing observations; revised plan needs a new packet')
        else:
            with destination.open('xb') as stream:
                stream.write(plan_path.read_bytes())
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
