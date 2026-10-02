"""Prospective, bounded two-plugin studies; original single-plugin grading is reused.

Plans and exposure receipts are declarations, never host attestation. A minimum
is descriptive and local to one frozen stage and the four/five tested arms.
"""
from copy import deepcopy
import random
from statistics import mean

from .core import ValidationError, evaluate, suite_digest, validate_suite, _stamp
from .science import keys, number, reference
from .task_selection import _id, _sha, _text
from .artifacts import confined, sha, read_only_verification

FORMAT = 'pvl-plugin-combination-design-1'
METRICS = ('quality', 'success', 'cost_usd', 'duration_seconds')
DIAGNOSTICS = ('duplicate_work', 'information_overwrite', 'parameter_handoff_error',
               'erroneous_evidence_propagation')
BURDEN = ('setup_usd', 'judge_usd', 'retry_usd', 'other_usd')


def plan(spec):
    """Freeze exactly one task-motivated pair, never search the power set."""
    keys(spec, 'suite stage inputs plugins rationale policy compare_orders seed')
    validate_suite(spec['suite'])
    keys(spec['stage'], 'id summary')
    _id(spec['stage']['id'])
    _text(spec['stage']['summary'])
    _text(spec['rationale'])
    if not isinstance(spec['inputs'], dict) or not 1 <= len(spec['inputs']) <= 50:
        raise ValidationError('Freeze explicit input snapshot identities')
    for name, digest in spec['inputs'].items():
        _id(name)
        _sha(digest)
    plugins = spec['plugins']
    if not isinstance(plugins, list) or len(plugins) != 2:
        raise ValidationError('Select exactly two plugins from task dependencies')
    for plugin in plugins:
        keys(plugin, 'id version sha256 capabilities')
        _id(plugin['id'])
        _text(plugin['version'])
        _sha(plugin['sha256'])
        caps = plugin['capabilities']
        if not isinstance(caps, list) or not 1 <= len(caps) <= 20:
            raise ValidationError('Declare the capabilities needed at this stage')
        for cap in caps:
            _text(cap)
        if len(set(caps)) != len(caps):
            raise ValidationError('Duplicate capability')
    if plugins[0]['id'] == plugins[1]['id']:
        raise ValidationError('A and B must be distinct plugin identities')
    policy = spec['policy']
    keys(policy, 'quality_floor success_floor max_mean_cost_usd max_mean_duration_seconds interaction_margin')
    for name, value in policy.items():
        number(value)
        if value < 0 or (name in ('quality_floor', 'success_floor', 'interaction_margin') and value > 1):
            raise ValidationError('Invalid prospective acceptance threshold')
    if policy['quality_floor'] < spec['suite']['policy']['quality_floor']:
        raise ValidationError('Combination policy cannot weaken the original quality floor')
    if type(spec['compare_orders']) is not bool:
        raise ValidationError('compare_orders must be a boolean')
    if type(spec['seed']) is not int or not 0 <= spec['seed'] < 2**32:
        raise ValidationError('seed must be an unsigned 32-bit integer')
    # AB is a prospective order, not an unordered collection. BA is separate.
    members = [('BASELINE', []), ('A', [0]), ('B', [1]), ('AB', [0, 1])]
    if spec['compare_orders']:
        members.append(('BA', [1, 0]))
    arms = [{'id': arm, 'exposure': {
        'plugins': [deepcopy(plugins[i]) for i in positions],
        'order': [plugins[i]['id'] for i in positions],
        'inputs': deepcopy(spec['inputs']),
        'background_conditions': deepcopy(spec['suite']['conditions'])}}
        for arm, positions in members]
    suite = spec['suite']
    if len(suite['cases']) * suite['runs_per_case'] * len(arms) > 10000:
        raise ValidationError('Combination plan exceeds 10000 executions')
    rng, assignments = random.Random(spec['seed']), []
    for case in suite['cases']:
        for repetition in range(1, suite['runs_per_case'] + 1):
            order = list(arms)
            rng.shuffle(order)
            for arm in order:
                assignments.append({'case_id': case['id'], 'repetition': repetition,
                                    'arm': arm['id'], 'execution_index': len(assignments) + 1})
    return {'format': FORMAT, 'spec': deepcopy(spec), 'arms': arms, 'assignments': assignments}


def _diagnostics(row, artifact_root):
    keys(row['diagnostics'], 'assessed events')
    assessed, events = row['diagnostics']['assessed'], row['diagnostics']['events']
    if (not isinstance(assessed, list) or any(type(k) is not str or k not in DIAGNOSTICS for k in assessed)
            or len(set(assessed)) != len(assessed)):
        raise ValidationError('Diagnostic coverage must list unique supported kinds')
    if not isinstance(events, list) or len(events) > 100:
        raise ValidationError('Diagnostic events must be a bounded list')
    result = []
    for event in events:
        keys(event, 'kind detail evidence')
        if event['kind'] not in assessed:
            raise ValidationError('Event must belong to an assessed diagnostic kind')
        _text(event['detail'])
        reference(event['evidence'])
        status = 'UNVERIFIED'
        if artifact_root is not None:
            try:
                path = confined(artifact_root, event['evidence']['path'])
                status = ('BYTES_VERIFIED' if path.is_file() and path.stat().st_size <= 8 * 1024 * 1024
                          and sha(path) == event['evidence']['sha256'] else 'MISSING_OR_CHANGED')
            except (OSError, ValidationError):
                status = 'MISSING_OR_CHANGED'
        result.append({**deepcopy(event), 'evidence_status': status,
                       'interpretation': 'SUBMITTED_OBSERVATION_NOT_INDEPENDENT_ADJUDICATION'})
    return {'assessed': deepcopy(assessed), 'events': result}


def _analyze_tasks(design, observations, expected_id, *, artifact_root=None, verifier_root=None):
    """Regrade originals, preserve every planned cell and bound recommendation scope."""
    keys(design, 'format spec arms assignments')
    if suite_digest(design) != suite_digest(plan(design['spec'])) or suite_digest(design) != expected_id:
        raise ValidationError('Design differs from its complete frozen assignment or retained ID')
    keys(observations, 'format design_sha256 runs')
    if observations['format'] != 'pvl-plugin-combination-observations-1' or observations['design_sha256'] != expected_id:
        raise ValidationError('Observations must bind the retained combination design')
    rows = observations['runs']
    if not isinstance(rows, list) or len(rows) > len(design['assignments']):
        raise ValidationError('Runs exceed the frozen budget; retries cannot replace failures')
    spec, arms = design['spec'], {a['id']: a for a in design['arms']}
    suite = spec['suite']
    planned = {(a['case_id'], a['repetition'], a['arm']): a for a in design['assignments']}
    indexed, sessions, issues, intervals, diagnostics = {}, set(), [], {}, []
    for row in rows:
        keys(row, 'case_id repetition arm execution_index exposure record additional_cost_usd diagnostics')
        if type(row['case_id']) is not str or type(row['repetition']) is not int or type(row['arm']) is not str:
            raise ValidationError('Malformed combination execution identity')
        key = (row['case_id'], row['repetition'], row['arm'])
        if key not in planned or key in indexed:
            raise ValidationError('Unexpected or duplicate combination execution')
        if type(row['execution_index']) is not int or row['execution_index'] != planned[key]['execution_index']:
            issues.append('Declared execution order differs from randomized assignment')
        if suite_digest(row['exposure']) != suite_digest(arms[row['arm']]['exposure']):
            issues.append('Plugin identity, exposure, invocation order, input or background conditions changed')
        record = row['record']
        if not isinstance(record, dict):
            raise ValidationError('Original execution record is required')
        if (record.get('case_id') != row['case_id'] or type(record.get('repetition')) is not int
                or record['repetition'] != row['repetition']
                or record.get('arm') != ('without' if row['arm'] == 'BASELINE' else 'with')):
            raise ValidationError('Original record identity differs from its assignment')
        sid = record.get('session_id')
        if not isinstance(sid, str) or not sid.strip() or sid in sessions:
            issues.append('Missing or reused session across combination arms')
        else:
            sessions.add(sid)
        keys(row['additional_cost_usd'], ' '.join(BURDEN))
        for cost in row['additional_cost_usd'].values():
            if cost is not None and number(cost) < 0:
                raise ValidationError('Additional cost must be nonnegative or null')
        if isinstance(record.get('human_intervals'), list):
            for timer in record['human_intervals']:
                try:
                    actor, start, end = timer['actor'], _stamp(timer['start']), _stamp(timer['end'])
                    if isinstance(actor, str) and start <= end:
                        intervals.setdefault(actor, []).append((start, end))
                except (ValueError, TypeError, KeyError):
                    pass  # The original evaluator reports malformed timers.
        diagnostics.append({**planned[key], **_diagnostics(row, artifact_root)})
        indexed[key] = row
    for timers in intervals.values():
        latest = None
        for start, end in sorted(timers):
            if latest is not None and start < latest:
                issues.append('Overlapping human intervals across combination arms')
            latest = max(latest, end) if latest is not None else end
    cells, comparisons, synthetic = {}, [], suite['evidence_type'] == 'synthetic'
    for arm in arms:
        if arm == 'BASELINE':
            continue
        records = [r['record'] for (_, _, a), r in indexed.items() if a in ('BASELINE', arm)]
        ledger = {'schema_version': 1, 'coverage': {k.removesuffix('_usd'): 'itemized' for k in BURDEN}, 'entries': []}
        for key, row in indexed.items():
            if key[2] not in ('BASELINE', arm):
                continue
            for category, amount in row['additional_cost_usd'].items():
                identity = f"combination-{row['execution_index']}-{category}"
                ledger['entries'].append({'id': identity, 'evidence_ref': identity,
                    'category': category.removesuffix('_usd'), 'amount_usd': amount,
                    'case_id': key[0], 'repetition': key[1], 'arm': row['record']['arm'],
                    'basis': 'declared', 'treatment': 'additional'})
        # No mutation of suite, output, grades or receipt identities. "with" is
        # the explicitly assigned plugin set; full per-arm exposure stays above.
        with read_only_verification():
            report = evaluate(suite, records, {'suite_sha256': suite_digest(suite)}, ledger,
                              artifact_root=artifact_root, verifier_root=verifier_root)
        synthetic |= report['evidence_type'] == 'synthetic'
        issues.extend(report['scope_integrity_blockers'])
        comparisons.append({'arm': arm, 'blockers': report['blockers']})
        for case in report['cases']:
            for run in case['runs']:
                chosen = 'BASELINE' if run['arm'] == 'without' else arm
                key = (case['id'], run['repetition'], chosen)
                outcome = run.get('task_outcome', {})
                admitted = not run['issues'] and outcome.get('passed') is not None
                duration = run.get('duration_seconds')
                try:
                    if number(duration) < 0:
                        duration = None
                except ValidationError:
                    duration = None
                cells[key] = {'case_id': case['id'], 'repetition': run['repetition'], 'arm': chosen,
                    'status': run['status'], 'quality': run['score'] if admitted else None,
                    'success': int(outcome['passed']) if admitted else None,
                    'cost_usd': run['cost_usd'], 'duration_seconds': duration,
                    'task_outcome': outcome, 'grades': run['grades'], 'issues': run['issues']}
    issues = sorted(set(issues))
    # Missing observations remain explicit unknown cells, never a reduced denominator.
    complete = not issues and all(all(c[m] is not None for m in METRICS) for c in cells.values())

    def estimate(weights, metric):
        per_case = []
        for case in suite['cases']:
            values = []
            for rep in range(1, suite['runs_per_case'] + 1):
                block = [cells[(case['id'], rep, arm)][metric] for arm in weights]
                values.append(None if issues or any(v is None for v in block)
                              else sum(weights[a] * v for a, v in zip(weights, block)))
            per_case.append({'case_id': case['id'], 'cluster': case['cluster'],
                             'value': None if None in values else mean(values)})
        return {'mean': None if any(c['value'] is None for c in per_case) else mean(c['value'] for c in per_case),
                'cases': per_case}

    summaries = []
    for arm in arms:
        estimates = {m: estimate({arm: 1}, m) for m in METRICS}
        reasons = []
        if issues or any(e['mean'] is None for e in estimates.values()):
            status = 'UNKNOWN'
            reasons.append('Comparable outcomes, complete declared cost and duration are required')
        else:
            policy = spec['policy']
            for metric, threshold, lower in (
                    ('quality', policy['quality_floor'], True), ('success', policy['success_floor'], True),
                    ('cost_usd', policy['max_mean_cost_usd'], False),
                    ('duration_seconds', policy['max_mean_duration_seconds'], False)):
                # Each task must meet the criterion; means never hide a weak case.
                if any((r['value'] < threshold if lower else r['value'] > threshold) for r in estimates[metric]['cases']):
                    reasons.append(metric + ' violates a frozen per-case mean threshold')
            critical_failed = any(g['critical'] and g['passed'] is not True for (cid, rep, a), c in cells.items()
                                  if a == arm for g in c['grades'])
            if critical_failed:
                reasons.append('A critical check failed or is unknown')
            delta = estimate({arm: 1, 'BASELINE': -1}, 'quality') if arm != 'BASELINE' else None
            if delta is not None:
                if delta['mean'] is None:
                    reasons.append('Baseline comparison unresolved')
                elif any(r['value'] < -suite['policy']['max_case_regression'] - 1e-12 for r in delta['cases']):
                    reasons.append('Original per-case regression guard failed')
            status = 'FAILED' if reasons else 'FEASIBLE'
            if delta is not None and delta['mean'] is None:
                status = 'UNKNOWN'
        summaries.append({'arm': arm, 'plugin_count': len(arms[arm]['exposure']['plugins']),
                          'status': status, 'reasons': reasons, 'metrics': estimates})
    contrasts = []
    for arm in ('AB', 'BA'):
        if arm not in arms:
            continue
        values = {m: estimate({arm: 1, 'A': -1, 'B': -1, 'BASELINE': 1}, m) for m in METRICS}
        q = values['quality']['mean']
        margin = spec['policy']['interaction_margin']
        sign = ('UNRESOLVED' if q is None else 'POSITIVE' if q > margin else 'NEGATIVE' if q < -margin else 'WITHIN_MARGIN')
        qualities = {a: estimate({a: 1}, 'quality')['mean'] for a in ('BASELINE', 'A', 'B', arm)}
        pattern = 'UNRESOLVED'
        if all(v is not None for v in qualities.values()):
            best = max(qualities['A'], qualities['B'])
            pattern = ('JOINT_BELOW_BEST_SINGLE' if qualities[arm] < best - margin else
                       'JOINT_ABOVE_BOTH_SINGLES' if qualities[arm] > best + margin else 'JOINT_WITHIN_MARGIN_OF_BEST_SINGLE')
        contrasts.append({'arm': arm, 'interaction': values, 'quality_interaction': sign,
            'observed_quality_pattern': pattern,
            'marginal_over_A': {m: estimate({arm: 1, 'A': -1}, m) for m in METRICS},
            'marginal_over_B': {m: estimate({arm: 1, 'B': -1}, m) for m in METRICS}})
    feasible = [a for a in summaries if a['status'] == 'FEASIBLE']
    candidates = [] if not feasible else [a['arm'] for a in feasible if a['plugin_count'] == min(x['plugin_count'] for x in feasible)]
    smallest = min((a['plugin_count'] for a in feasible), default=None)
    unresolved_smaller = [a['arm'] for a in summaries if a['status'] == 'UNKNOWN' and
                          (smallest is None or a['plugin_count'] <= smallest)]
    minimum = bool(candidates) and not unresolved_smaller and not issues
    relationship = 'UNRESOLVED'
    states = {r['arm']: r['status'] for r in summaries}
    if complete:
        pair_ok = [a for a in ('AB', 'BA') if states.get(a) == 'FEASIBLE']
        if states['BASELINE'] == 'FEASIBLE':
            relationship = 'BASELINE_SUFFICIENT'
        elif states['A'] == states['B'] == 'FEASIBLE':
            relationship = 'SINGLE_PLUGIN_ALTERNATIVES'
        elif pair_ok and states['A'] == states['B'] == 'FAILED':
            relationship = 'COMBINATION_REQUIRED_WITHIN_TESTED_SET'
        elif any(states[a] == 'FEASIBLE' for a in ('A', 'B')):
            relationship = 'SINGLE_PLUGIN_SUFFICIENT'
    result = {'format': 'pvl-plugin-combination-report-1', 'design_sha256': expected_id,
        'observations_sha256': suite_digest(observations), 'stage': deepcopy(spec['stage']),
        'status': 'COMPLETE' if complete else 'INCOMPLETE',
        'evidence_status': 'SIMULATION_ONLY' if synthetic else 'DESCRIPTIVE_LOCAL_OBSERVATIONS',
        'planned_runs': len(planned), 'observed_runs': len(indexed), 'cells': list(cells.values()),
        'arms': summaries, 'contrasts': contrasts,
        'order_effect_AB_minus_BA': {m: estimate({'AB': 1, 'BA': -1}, m) for m in METRICS} if 'BA' in arms else None,
        'relationship': relationship, 'issues': issues, 'pair_diagnostics': comparisons,
        'recommendation': {'status': 'SIMULATION_ONLY' if synthetic else 'MINIMUM_OBSERVED' if minimum else 'EVIDENCE_REQUIRED',
            'candidate_arms': candidates, 'minimum_within_tested_set': minimum,
            'unresolved_smaller_or_equal_arms': unresolved_smaller,
            'retain_capabilities': {a: arms[a]['exposure'] for a in candidates},
            'scope': 'This frozen stage, inputs, conditions, budget, pair and tested invocation orders only'},
        'diagnostics': diagnostics,
        'contrast_definition': 'Q(AB) - Q(A) - Q(B) + Q(BASELINE); no half scaling',
        'weighting': 'Repetitions averaged within case, then equal case weights; shared baseline is not a new run',
        'exposure_evidence': 'DECLARED_CONFIGURATION_NOT_HOST_ATTESTED',
        'tool_invocation': 'NOT_ESTABLISHED', 'causal_attribution': 'NOT_ESTABLISHED',
        'cost_scope': 'Run costs plus explicitly allocated additional costs; declared coverage is not account settlement',
        'automatic_actions': [],
        'claim_limits': ['No global minimum, causal attribution, statistical equivalence or held-out generalization.',
            'Interaction sign alone does not establish complementarity, substitution or operational interference.',
            'Diagnostic coverage and event labels are submitted observations; byte checks do not adjudicate their meaning.',
            'Unknown duration blocks feasibility; incomplete cost coverage preserves the original evaluator evidence gates.',
            'No installation, unloading, permission change, host execution or paid calls are authorized by this report.']}
    return result


def analyze(design, observations, expected_id, *, artifact_root=None, verifier_root=None):
    """Preserve the existing result shape, including an absent-context view."""
    result = _analyze_tasks(design, observations, expected_id,
                            artifact_root=artifact_root, verifier_root=verifier_root)
    from .burden_view import build
    result['burden_view'] = build(design, observations, result)
    return result


def route(request, *, artifact_root=None, verifier_root=None):
    """Object-only entry through the existing planning CLI/MCP tool."""
    if not isinstance(request, dict):
        raise ValidationError('plugin_combination must be an object')
    if request.get('action') == 'plan':
        keys(request, 'action spec')
        design = plan(request['spec'])
        return {'status': 'AWAITING_OBSERVATIONS', 'design': design, 'design_sha256': suite_digest(design),
                'retention': 'Retain design and ID separately before collection; digest is not timestamp attestation',
                'automatic_actions': []}
    keys(request, 'action design observations expected_id' + (' burden_observations' if 'burden_observations' in request else ''))
    if request['action'] != 'analyze':
        raise ValidationError('Use plan or analyze')
    result = _analyze_tasks(request['design'], request['observations'], request['expected_id'],
                     artifact_root=artifact_root, verifier_root=verifier_root)
    if 'burden_observations' in request:
        if request['burden_observations'] is None:
            raise ValidationError('Omit absent burden observations instead of submitting null')
    from .burden_view import build
    result['burden_view'] = build(request['design'], request['observations'], result,
                                  request.get('burden_observations'))
    return result
