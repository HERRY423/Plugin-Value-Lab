"""Frozen full-factorial plans and descriptive matched component contrasts.

Uses the existing evaluator for every original output. Assignment/configuration
receipts are declarations, not host attestation or evidence of actual tool use.
"""
from copy import deepcopy
from itertools import combinations, product
import random
from statistics import mean

from .core import ValidationError, evaluate, suite_digest, validate_suite
from .science import keys, reference

FACTORS = ('prompt', 'tools', 'context')
FORMAT = 'pvl-component-design-1'


def plan(suite, components, seed=20260928):
    validate_suite(suite)
    keys(components, 'prompt tools context')
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValidationError('Assignment seed must be an unsigned 32-bit integer')
    for name in FACTORS:
        if components[name] is None and name == 'context':
            continue
        reference({'path': name + '.json', 'sha256': components[name]})
    factors = [x for x in FACTORS if components[x] is not None]
    arms = []
    for levels in product((False, True), repeat=len(factors)):
        enabled = dict(zip(factors, levels))
        identity = ''.join('1' if x else '0' for x in levels)
        label = ('BASELINE' if not any(levels) else 'FULL_PLUGIN' if all(levels)
                 else '_AND_'.join(x.upper() for x in factors if enabled[x]) + '_ONLY')
        arms.append({'id': identity, 'label': label,
                     'components': {x: components[x] if enabled.get(x) else None for x in FACTORS}})
    if len(suite['cases']) * suite['runs_per_case'] * len(arms) > 10000:
        raise ValidationError('Component plan exceeds 10000 executions')
    rng, assignments = random.Random(seed), []
    for case in suite['cases']:
        for repetition in range(1, suite['runs_per_case'] + 1):
            order = list(arms)
            rng.shuffle(order)
            for arm in order:
                assignments.append({'case_id': case['id'], 'repetition': repetition,
                                    'arm': arm['id'], 'execution_index': len(assignments) + 1})
    return {'format': FORMAT, 'suite': deepcopy(suite), 'components': deepcopy(components),
            'seed': seed, 'factors': factors, 'arms': arms, 'assignments': assignments}


def validate_design(design):
    keys(design, 'format suite components seed factors arms assignments')
    expected = plan(design['suite'], design['components'], design['seed'])
    if suite_digest(design) != suite_digest(expected):
        raise ValidationError('Component design must retain the complete generated factorial assignment')
    return design


def analyze(design, observations, expected_id, *, artifact_root=None, verifier_root=None):
    validate_design(design)
    if suite_digest(design) != expected_id:
        raise ValidationError('Component design differs from separately retained expected ID')
    keys(observations, 'format design_sha256 runs')
    if observations['format'] != 'pvl-component-observations-1' or observations['design_sha256'] != expected_id:
        raise ValidationError('Component observations are not bound to this design')
    if not isinstance(observations['runs'], list) or len(observations['runs']) > len(design['assignments']):
        raise ValidationError('Runs must fit the planned execution budget; do not replace failures with retries')
    suite, arms = design['suite'], {a['id']: a for a in design['arms']}
    baseline = '0' * len(design['factors'])
    expected = {(a['case_id'], a['repetition'], a['arm']): a for a in design['assignments']}
    indexed, sessions, issues = {}, set(), []
    intervals = {}
    for row in observations['runs']:
        keys(row, 'case_id repetition arm execution_index components record')
        if not isinstance(row['case_id'], str) or type(row['repetition']) is not int or not isinstance(row['arm'], str):
            raise ValidationError('Malformed component execution key')
        key = (row['case_id'], row['repetition'], row['arm'])
        if key not in expected or key in indexed:
            raise ValidationError('Unexpected or duplicate component execution')
        if type(row['execution_index']) is not int or row['execution_index'] != expected[key]['execution_index']:
            issues.append('Declared execution order differs from frozen randomized assignment')
        if suite_digest(row['components']) != suite_digest(arms[row['arm']]['components']):
            issues.append('Component exposure missing, changed or contaminated')
        record = row['record']
        if not isinstance(record, dict):
            raise ValidationError('Original execution record is required')
        sid = record.get('session_id')
        if not isinstance(sid, str) or not sid.strip() or sid in sessions:
            issues.append('Missing or reused session across component arms')
        else:
            sessions.add(sid)
        core_arm = 'without' if row['arm'] == baseline else 'with'
        if (record.get('case_id') != row['case_id'] or type(record.get('repetition')) is not int
                or record.get('repetition') != row['repetition'] or record.get('arm') != core_arm):
            raise ValidationError('Original record key does not match its component assignment')
        indexed[key] = record
        # A baseline is not the only shared resource: human time must also be
        # checked between two non-baseline arms, which paired evaluation never sees.
        from .core import _stamp
        if isinstance(record.get('human_intervals'), list):
            for timer in record['human_intervals']:
                try:
                    actor = timer['actor']
                    start, end = _stamp(timer['start']), _stamp(timer['end'])
                    if isinstance(actor, str) and start <= end:
                        intervals.setdefault(actor, []).append((start, end))
                except (ValueError, TypeError, KeyError):
                    pass  # Original evaluator reports malformed timers below.
    for timers in intervals.values():
        latest = None
        for start, end in sorted(timers):
            if latest is not None and start < latest:
                issues.append('Overlapping human intervals across component arms')
            latest = max(latest, end) if latest is not None else end
    cells, comparisons = {}, []
    for arm in arms:
        if arm == baseline:
            continue
        records = [r for (_, _, a), r in indexed.items() if a in (arm, baseline)]
        # The retained component design includes the exact suite. No output or
        # imported grade is rewritten; "with" means the assigned component set.
        report = evaluate(suite, records, {'suite_sha256': suite_digest(suite)},
                          artifact_root=artifact_root, verifier_root=verifier_root)
        comparisons.append({'arm': arm, 'blockers': report['blockers']})
        issues.extend(report['scope_integrity_blockers'])
        for case in report['cases']:
            for run in case['runs']:
                selected = baseline if run['arm'] == 'without' else arm
                key = (case['id'], run['repetition'], selected)
                outcome = run.get('task_outcome', {})
                admitted = not run['issues'] and outcome.get('passed') is not None
                cells[key] = {'case_id': case['id'], 'repetition': run['repetition'], 'arm': selected,
                    'status': run['status'], 'quality': run['score'] if admitted else None,
                    'success': int(outcome['passed']) if admitted else None,
                    'cost_usd': run['cost_usd'], 'duration_seconds': run.get('duration_seconds'),
                    'task_outcome': outcome, 'issues': run['issues'], 'grades': run['grades']}
    complete = not issues and all(c['success'] is not None for c in cells.values())
    contrasts = []
    factors = design['factors']
    for order in range(1, len(factors) + 1):
        for subset in combinations(range(len(factors)), order):
            per_case = []
            for case in suite['cases']:
                values = []
                for rep in range(1, suite['runs_per_case'] + 1):
                    block = [cells[(case['id'], rep, arm)] for arm in arms]
                    def contrast(metric):
                        if issues or any(r[metric] is None for r in block):
                            return None
                        return sum((-1)**sum(r['arm'][i] == '0' for i in subset) * r[metric]
                                   for r in block) / (len(arms) / 2)
                    values.append({metric: contrast(metric) for metric in ('success', 'quality')})
                per_case.append({'case_id': case['id'], 'cluster': case['cluster'],
                    **{m: None if any(v[m] is None for v in values) else mean(v[m] for v in values)
                       for m in ('success', 'quality')}})
            contrasts.append({'factors': [factors[i] for i in subset], 'order': order,
                **{m: mean(v[m] for v in per_case) if complete else None for m in ('success', 'quality')},
                'cases': per_case})
    return {'format': 'pvl-component-report-1', 'design_sha256': expected_id,
            'observations_sha256': suite_digest(observations), 'status': 'COMPLETE' if complete else 'INCOMPLETE',
            'planned_runs': len(expected), 'observed_runs': len(indexed), 'arms': list(arms.values()),
            'cells': list(cells.values()), 'contrasts': contrasts, 'issues': sorted(set(issues)),
            'pair_diagnostics': comparisons, 'evidence_type': 'synthetic' if suite['evidence_type'] == 'synthetic'
                or any(r.get('source') == 'synthetic' for r in indexed.values()) else suite['evidence_type'],
            'contrast_definition': 'mean(product of +/-1 levels * outcome) * 2; pair interaction is half difference-in-differences',
            'weighting': 'Equal cases; repetitions averaged within case; no inferential independence claim',
            'exposure_evidence': 'DECLARED_CONFIGURATION_NOT_HOST_ATTESTED', 'tool_invocation': 'NOT_ESTABLISHED',
            'causal_attribution': 'NOT_ESTABLISHED', 'automatic_component_removal': False}
