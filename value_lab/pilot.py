"""Independent pilot provenance and balanced paired-variance handoff.

This is a local descriptive calculation, not source authentication or evidence
that declared families really are independent.  Bootstrap percentiles are not
hard bounds on future variance.  No confirmation outcomes are used here.
"""
from collections import defaultdict
from copy import deepcopy
import math
import random
import re
from statistics import mean, variance

from .core import ValidationError, _number, _text, suite_digest


COMPONENTS = ('between_family_sd', 'between_task_sd', 'within_task_sd')
ANALYSIS_SEED = 1729
BOOTSTRAP_RESAMPLES = 2000
_ZERO = 1e-15
_SHA256 = re.compile(r'^[0-9a-fA-F]{64}$')


def _hash(value):
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _validate_packet(packet):
    required = {'version', 'pilot_id', 'evidence_type', 'endpoint', 'task_source',
                'independence_rationale', 'records'}
    if not isinstance(packet, dict) or set(packet) != required:
        raise ValidationError('Pilot packet requires exactly version, pilot_id, evidence_type, '
                              'endpoint, task_source, independence_rationale and records')
    if type(packet['version']) is not int or packet['version'] != 1:
        raise ValidationError('Pilot packet version must be 1')
    for field in ('pilot_id', 'task_source', 'independence_rationale'):
        _text(packet[field], 'Pilot ' + field)
    if packet['evidence_type'] not in ('real', 'synthetic'):
        raise ValidationError('Pilot evidence_type must be real or synthetic')
    if packet['endpoint'] != 'outcome_quality':
        raise ValidationError('Pilot endpoint must be outcome_quality on a [0,1] score scale')
    records = packet['records']
    if not isinstance(records, list) or not records:
        raise ValidationError('Pilot records must be a nonempty list of paired observations')
    required_record = {'family_id', 'task_id', 'input_sha256', 'repetition', 'with_score',
                       'without_score', 'with_run_id', 'without_run_id', 'source_ref'}
    optional = {'with_session_id', 'without_session_id'}
    groups, task_identity, input_tasks, identities = defaultdict(lambda: defaultdict(dict)), {}, {}, {}
    for index, record in enumerate(records):
        if (not isinstance(record, dict) or not required_record <= set(record)
                or set(record) - required_record - optional):
            raise ValidationError(f'Pilot record {index + 1} has missing or unknown fields')
        for field in ('family_id', 'task_id', 'with_run_id', 'without_run_id', 'source_ref'):
            _text(record[field], f'Pilot record {index + 1} {field}')
        if not _hash(record['input_sha256']):
            raise ValidationError('Pilot input_sha256 must identify input bytes with 64 hexadecimal characters')
        family, task, digest = record['family_id'], record['task_id'], record['input_sha256'].lower()
        identity = (family, digest)
        if task in task_identity and task_identity[task] != identity:
            raise ValidationError('Pilot task_id must map to one family and one input_sha256')
        if digest in input_tasks and input_tasks[digest] != task:
            raise ValidationError('Pilot input_sha256 is reused under different task IDs')
        task_identity[task], input_tasks[digest] = identity, task
        repetition = record['repetition']
        if type(repetition) is not int or repetition < 1:
            raise ValidationError('Pilot repetition must be a positive integer')
        if repetition in groups[family][task]:
            raise ValidationError('Duplicate pilot task/repetition pair')
        for field in ('with_score', 'without_score'):
            _number(record[field], 'Pilot ' + field, 0, 1)
        if bool(optional & set(record)) and not optional <= set(record):
            raise ValidationError('Pilot session identifiers must be provided for both arms together')
        for arm in ('with', 'without'):
            owner = (task, repetition, arm)
            for field in (arm + '_run_id', arm + '_session_id'):
                if field not in record:
                    continue
                _text(record[field], 'Pilot ' + field)
                token = record[field]
                if token in identities and identities[token] != owner:
                    raise ValidationError('Pilot run/session identity reused across executions')
                identities[token] = owner
        groups[family][task][repetition] = record
    if len(groups) < 3:
        raise ValidationError('Independent pilot needs at least 3 declared families')
    task_counts = {len(tasks) for tasks in groups.values()}
    repeat_counts = {len(rows) for tasks in groups.values() for rows in tasks.values()}
    if len(task_counts) != 1 or min(task_counts) < 2:
        raise ValidationError('Balanced pilot requires at least 2 tasks in every family')
    if len(repeat_counts) != 1 or min(repeat_counts) < 2:
        raise ValidationError('Balanced pilot requires at least 2 repetitions of every task')
    repetitions = next(iter(repeat_counts))
    if any(set(rows) != set(range(1, repetitions + 1)) for tasks in groups.values() for rows in tasks.values()):
        raise ValidationError('Pilot repetitions must be complete and consecutive from 1')
    return groups, task_identity


def _family_statistics(groups):
    result = []
    for family in sorted(groups):
        tasks = []
        for task in sorted(groups[family]):
            rows = groups[family][task]
            values = [rows[rep]['with_score'] - rows[rep]['without_score'] for rep in sorted(rows)]
            task_mean = mean(values)
            tasks.append((task_mean, math.fsum((v - task_mean)**2 for v in values)))
        family_mean = mean(value for value, _ in tasks)
        result.append({'mean': family_mean,
                       'task_mean_ss': math.fsum((value - family_mean)**2 for value, _ in tasks),
                       'within_ss': math.fsum(value for _, value in tasks)})
    return result


def _anova(families, tasks, repetitions):
    count = len(families)
    grand_mean = mean(item['mean'] for item in families)
    family_ss = tasks * repetitions * math.fsum((item['mean'] - grand_mean)**2 for item in families)
    task_ss = repetitions * math.fsum(item['task_mean_ss'] for item in families)
    within_ss = math.fsum(item['within_ss'] for item in families)
    dfs = (count - 1, count * (tasks - 1), count * tasks * (repetitions - 1))
    mss = (family_ss / dfs[0], task_ss / dfs[1], within_ss / dfs[2])
    raw = ((mss[0] - mss[1]) / (tasks * repetitions),
           (mss[1] - mss[2]) / repetitions, mss[2])
    table = [{'level': level, 'sum_squares': ss, 'degrees_of_freedom': df, 'mean_square': ms}
             for level, ss, df, ms in zip(('family', 'task_within_family', 'repeat_within_task'),
                                         (family_ss, task_ss, within_ss), dfs, mss)]
    return raw, table


def _percentile(values, probability):
    # Linear interpolation, the conventional type-7 empirical quantile.
    index = (len(values) - 1) * probability
    low = int(index)
    fraction = index - low
    return values[low] * (1 - fraction) + values[min(low + 1, len(values) - 1)] * fraction


def summarize_pilot(packet):
    """Validate a complete balanced pilot and recompute its immutable handoff.

The fixed seed is for this local uncertainty calculation only; it is unrelated
to model-generation seeds. Preserve the packet hash in the frozen study plan.
    """
    groups, task_identity = _validate_packet(packet)
    source = deepcopy(packet)
    families = _family_statistics(groups)
    tasks = len(next(iter(groups.values())))
    repetitions = len(next(iter(next(iter(groups.values())).values())))
    raw, table = _anova(families, tasks, repetitions)
    rng = random.Random(ANALYSIS_SEED)
    distributions = {component: [] for component in COMPONENTS}
    for _ in range(BOOTSTRAP_RESAMPLES):
        sampled = [families[rng.randrange(len(families))] for _ in families]
        variances, _ = _anova(sampled, tasks, repetitions)
        for component, value in zip(COMPONENTS, variances):
            distributions[component].append(math.sqrt(max(0., value)))
    intervals, components, warnings, floor_required = {}, [], [], []
    for component, estimate in zip(COMPONENTS, raw):
        values = sorted(distributions[component])
        lower, upper = _percentile(values, .025), _percentile(values, .975)
        # A boundary estimate must not silently turn into a claim of zero risk.
        needs_floor = estimate <= _ZERO or upper <= math.sqrt(_ZERO)
        if needs_floor:
            floor_required.append(component)
            warnings.append(component + ': VARIANCE_FLOOR_REQUIRED; supply a justified positive external floor before planning')
        if estimate < 0:
            warnings.append(component + ': NEGATIVE_ANOVA_COMPONENT_TRUNCATED; raw estimate retained')
        if lower <= math.sqrt(_ZERO):
            warnings.append(component + ': BOOTSTRAP_INTERVAL_TOUCHES_BOUNDARY; small pilots may miss heterogeneity')
        degenerate_bootstrap = upper - lower <= 1e-12
        if degenerate_bootstrap:
            warnings.append(component + ': BOOTSTRAP_UNCERTAINTY_UNRESOLVED; identical empirical family statistics cannot establish precise population variance')
        intervals[component] = {'lower': lower, 'upper': upper, 'planning_upper_sd': upper,
                                'degenerate_bootstrap': degenerate_bootstrap,
                                'fraction_at_zero': sum(value <= math.sqrt(_ZERO) for value in values) / len(values)}
        components.append({'component': component, 'raw_variance': estimate,
                           'variance': max(0., estimate), 'sd': math.sqrt(max(0., estimate)),
                           'truncated': estimate < 0, 'requires_variance_floor': needs_floor})
    records = source['records']
    with_scores, without_scores = [row['with_score'] for row in records], [row['without_score'] for row in records]
    with_mean, without_mean = mean(with_scores), mean(without_scores)
    covariance = math.fsum((a - with_mean) * (b - without_mean)
                           for a, b in zip(with_scores, without_scores)) / (len(records) - 1)
    with_variance, without_variance = variance(with_scores), variance(without_scores)
    difference_variance = variance([a - b for a, b in zip(with_scores, without_scores)])
    reconstructed = with_variance + without_variance - 2 * covariance
    if not math.isclose(difference_variance, reconstructed, rel_tol=1e-10, abs_tol=1e-12):
        raise ValidationError('Paired variance/covariance identity did not reconcile')
    if len(groups) < 10:
        warnings.append('SMALL_PILOT: fewer than 10 declared independent families; variance uncertainty is poorly resolved')
    if not all('with_session_id' in row for row in records):
        warnings.append('SESSION_PROVENANCE_INCOMPLETE: run IDs are declared; separate execution sessions were not all supplied')
    if packet['evidence_type'] == 'synthetic':
        warnings.append('SYNTHETIC_ONLY: this handoff exercises calculations and cannot substantiate a real pilot')
    task_sources = defaultdict(set)
    for row in records:
        task_sources[row['task_id']].add(row['source_ref'])
    return {
        'format': 'pvl-pilot-summary-1', 'status': 'VARIANCE_FLOOR_REQUIRED' if floor_required else 'CONDITIONAL_PILOT_HANDOFF',
        'pilot_id': source['pilot_id'], 'evidence_type': source['evidence_type'], 'endpoint': source['endpoint'],
        'source_packet': source, 'source_packet_sha256': suite_digest(source),
        'task_source': source['task_source'], 'independence_rationale': source['independence_rationale'],
        'design': {'families': len(groups), 'tasks_per_family': tasks, 'repetitions_per_task': repetitions,
                   'paired_observations': len(records), 'generation_runs': 2 * len(records), 'balanced': True},
        'identities': {'family_ids': sorted(groups), 'task_ids': sorted(task_identity),
                       'input_sha256': sorted({value[1] for value in task_identity.values()}),
                       'run_ids': sorted(row[arm + '_run_id'] for row in records for arm in ('with', 'without')),
                       'session_ids': sorted(row[arm + '_session_id'] for row in records
                                             for arm in ('with', 'without') if arm + '_session_id' in row),
                       'tasks': [{'task_id': task, 'family_id': task_identity[task][0],
                                  'input_sha256': task_identity[task][1], 'source_refs': sorted(task_sources[task])}
                                 for task in sorted(task_identity)]},
        'arm_covariance': {'with_sample_variance': with_variance, 'without_sample_variance': without_variance,
                           'paired_sample_covariance': covariance, 'paired_difference_sample_variance': difference_variance,
                           'reconstructed_difference_variance': reconstructed, 'identity_verified': True,
                           'sample_ddof': 1, 'observations': len(records),
                           'basis': 'Pooled paired observations; descriptive covariance, not independent sample count'},
        'anova': table, 'variance_components': components,
        'uncertainty': {'method': 'Independent-family cluster percentile bootstrap; all nested observations retained',
                        'analysis_seed': ANALYSIS_SEED, 'resamples': BOOTSTRAP_RESAMPLES,
                        'confidence_level': .95, 'sd_intervals': intervals,
                        'planning_sd_upper95': {key: value['upper'] for key, value in intervals.items()},
                        'planning_upper_quantile': .975, 'hard_variance_bound': False,
                        'variance_floor_required': floor_required},
        'warnings': warnings,
        'limitations': [
            'The source packet is copied and hashed; hashes bind submitted bytes, not authenticity, task independence or population representativeness.',
            'Pilot task identities, input hashes and execution identities must be disjoint from confirmation data. This check cannot detect hidden semantic duplicates or relabelled families.',
            'ANOVA estimates assume balanced nested random effects and exchangeable independent family samples; paired differences must use the same scoring definition as confirmation.',
            'Raw negative variance components are reported and truncated only for SD calculations. A justified external positive floor is required for boundary components.',
            'Family resampling retains within-family dependence. Percentile intervals are approximate, especially with few families; they have no guaranteed small-pilot coverage.',
            'The 97.5th percentile is an upper endpoint of a nominal 95% two-sided interval, not a guaranteed bound. Separate component intervals are not a simultaneous confidence region.',
            'Even a constant pilot cannot establish absence of future variability. A user-supplied floor remains an explicit assumption, not newly observed variance.',
            'The fixed analysis seed reproduces bootstrap calculations; it does not indicate controlled model-generation seeds or independent sessions.',
            'No pilot mean effect is supplied for selecting the anticipated confirmation effect; predeclare the meaningful threshold and alternative independently.',
            'Real/synthetic and source/session declarations are retained as submitted, not independently verified. This module performs no model or paid calls.'],
        'executed': False,
    }


def validated_source(report_or_packet):
    """Return a copied source packet; refuse stale or edited derived reports.

A packet is authoritative input, never proof of authenticity. A summary is
accepted only when every derived field matches current deterministic replay.
    """
    if isinstance(report_or_packet, dict) and report_or_packet.get('format') == 'pvl-pilot-summary-1':
        packet = report_or_packet.get('source_packet')
        _validate_packet(packet)
        if report_or_packet.get('source_packet_sha256') != suite_digest(packet):
            raise ValidationError('Pilot summary source packet hash mismatch')
        if report_or_packet != summarize_pilot(packet):
            raise ValidationError('Pilot summary differs from recomputed source packet')
    else:
        packet = report_or_packet
        _validate_packet(packet)
    return deepcopy(packet)


def validate_disjoint(report_or_packet, suite, records=None):
    """List fail-closed identity issues between the pilot and confirmation.

Pass records only at evaluation time. At design time the case/family/input
separation is checked; future execution IDs cannot be checked until supplied.
    """
    try:
        packet = validated_source(report_or_packet)
    except ValidationError as exc:
        return ['INVALID_PILOT_SOURCE: ' + str(exc)]
    groups, task_identity = _validate_packet(packet)
    pilot_tasks, pilot_families = set(task_identity), set(groups)
    pilot_inputs = {identity[1] for identity in task_identity.values()}
    pilot_execution_ids = {row[field] for row in packet['records']
                           for field in ('with_run_id', 'without_run_id', 'with_session_id', 'without_session_id') if field in row}
    cases = suite.get('cases') if isinstance(suite, dict) else None
    if not isinstance(cases, list) or not cases:
        return ['MISSING_CONFIRMATION_CASES: cannot verify pilot/confirmation separation']
    issues, seen_tasks, seen_inputs = [], set(), set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            issues.append(f'MALFORMED_CONFIRMATION_CASE: index {index + 1}')
            continue
        task, family, digest = case.get('id'), case.get('cluster'), case.get('input_sha256')
        label = task if isinstance(task, str) else str(index + 1)
        if not isinstance(task, str) or not task.strip() or not isinstance(family, str) or not family.strip() or not _hash(digest):
            issues.append(f'MISSING_CONFIRMATION_IDENTITY: {label} needs id, cluster and input_sha256')
            continue
        digest = digest.lower()
        if task in pilot_tasks:
            issues.append('PILOT_TASK_OVERLAP: ' + task)
        if family in pilot_families:
            issues.append('PILOT_FAMILY_OVERLAP: ' + family)
        if digest in pilot_inputs:
            issues.append('PILOT_INPUT_OVERLAP: ' + label)
        if task in seen_tasks or digest in seen_inputs:
            issues.append('REUSED_CONFIRMATION_TASK_OR_INPUT: ' + label)
        seen_tasks.add(task)
        seen_inputs.add(digest)
    if records is not None:
        if not isinstance(records, list) or not records:
            issues.append('MISSING_CONFIRMATION_EXECUTIONS: no supplied run/session records')
            return issues
        seen_execution_ids = set()
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                issues.append(f'MALFORMED_CONFIRMATION_EXECUTION: index {index + 1}')
                continue
            tokens = set()
            malformed = False
            for field in ('run_id', 'session_id'):
                if field in record:
                    value = record[field]
                    if not isinstance(value, str) or not value.strip():
                        malformed = True
                    else:
                        tokens.add(value)
            if malformed or not tokens:
                issues.append(f'MISSING_CONFIRMATION_EXECUTION_IDENTITY: index {index + 1}')
                continue
            if tokens & pilot_execution_ids:
                issues.append(f'PILOT_EXECUTION_OVERLAP: index {index + 1}')
            if tokens & seen_execution_ids:
                issues.append(f'REUSED_CONFIRMATION_EXECUTION: index {index + 1}')
            seen_execution_ids.update(tokens)
    return issues
