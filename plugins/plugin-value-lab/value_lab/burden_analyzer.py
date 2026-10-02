"""Pure analysis: collected observations plus recomputed task evidence.

No collection, I/O, formatting or candidate reselection. Only collect() output
and a recomputed report belong at this internal boundary. Matching digests
prevent accidental cross-study mixing; they do not authenticate execution.
"""
from copy import deepcopy
from itertools import combinations
from statistics import mean
from .burden_contracts import BurdenCollection
from .core import ValidationError

METRICS = ('context_peak_fraction', 'cost_usd', 'duration_seconds')
EPSILON = 1e-12  # arithmetic tolerance only, not a practical/statistical margin


def analyze(collection: BurdenCollection, report):
    """Use recomputed task feasibility and full per-case denominators; no selection."""
    if (collection.design_sha256 != report['design_sha256'] or
            collection.observations_sha256 != report['observations_sha256']):
        raise ValidationError('Burden collection and recomputed report bindings differ')
    measurement = dict(collection.measurement) if collection.measurement is not None else None
    context = {}
    for row in collection.runs:
        complete = row.coverage == 'complete' and len(row.samples) == row.expected_samples
        peak = max((tokens for _, tokens in row.samples), default=None)
        context[(row.case_id, row.repetition, row.arm)] = {
            'status': 'SUBMITTED_COMPLETE' if complete else 'PARTIAL',
            'observed_samples': len(row.samples), 'expected_samples': row.expected_samples,
            'observed_peak_tokens': peak,
            'value': peak / measurement['context_window_tokens'] if complete else None}
    rows = []
    for arm in report['arms']:
        per_case = []
        for case_id in collection.case_ids:
            samples = [context.get((case_id, rep, arm['arm']), {'status': 'MISSING', 'value': None})
                       for rep in range(1, collection.runs_per_case + 1)]
            values = [s['value'] for s in samples]
            peak = None if report['issues'] or None in values else mean(values)
            metrics = {'context_peak_fraction': peak}
            for name in METRICS[1:]:
                metrics[name] = next(c['value'] for c in arm['metrics'][name]['cases'] if c['case_id'] == case_id)
            per_case.append({'case_id': case_id, 'metrics': metrics, 'context_runs': samples})
        metrics = {m: None if any(c['metrics'][m] is None for c in per_case)
                   else mean(c['metrics'][m] for c in per_case) for m in METRICS}
        rows.append({'arm': arm['arm'], 'eligibility': arm['status'], 'reasons': deepcopy(arm['reasons']),
                     'metrics': metrics, 'cases': per_case,
                     'missing_dimensions': [m for m, value in metrics.items() if value is None]})
    eligible = [r for r in rows if r['eligibility'] == 'FEASIBLE']
    pairs, dominated = [], set()
    for left, right in combinations(eligible, 2):
        deltas, better, worse, missing = [], [], [], []
        for lcase, rcase in zip(left['cases'], right['cases']):
            for metric in METRICS:
                lv, rv = lcase['metrics'][metric], rcase['metrics'][metric]
                delta = None if lv is None or rv is None else lv - rv
                point = {'case_id': lcase['case_id'], 'metric': metric, 'left_minus_right': delta}
                deltas.append(point)
                if delta is None:
                    missing.append(point)
                elif delta < -EPSILON:
                    better.append(point)
                elif delta > EPSILON:
                    worse.append(point)
        relation = ('UNKNOWN' if missing else 'TRADEOFF' if better and worse else
                    'LEFT_DOMINATES' if better else 'RIGHT_DOMINATES' if worse else 'EQUAL')
        if relation == 'LEFT_DOMINATES':
            dominated.add(right['arm'])
        elif relation == 'RIGHT_DOMINATES':
            dominated.add(left['arm'])
        pairs.append({'left': left['arm'], 'right': right['arm'], 'relation': relation,
                      'left_better_on': better, 'right_better_on': worse, 'missing': missing, 'deltas': deltas})
    unresolved = [r['arm'] for r in rows if r['eligibility'] == 'UNKNOWN' or
                  (r['eligibility'] == 'FEASIBLE' and r['missing_dimensions'])]
    return {'format': 'pvl-burden-view-1', 'evidence_status': report['evidence_status'],
            'design_sha256': report['design_sha256'], 'observations_sha256': report['observations_sha256'],
            'context_observations_sha256': collection.context_observations_sha256,
            'context_evidence': 'SUBMITTED_NOT_HOST_ATTESTED' if collection.context_observations_sha256 is not None else 'MISSING',
            'measurement': measurement, 'candidates': rows, 'comparisons': pairs,
            'eligible_arms': [r['arm'] for r in eligible],
            'frontier': {'status': 'NOT_ASSESSED' if not eligible else 'PARTIAL' if unresolved else 'DESCRIPTIVE_COMPLETE',
                         'fully_observed_nondominated': [r['arm'] for r in eligible if not r['missing_dimensions'] and r['arm'] not in dominated],
                         'dominated': sorted(dominated), 'unresolved_arms': unresolved},
            'selection_rule_changed': False, 'automatic_actions': [],
            'definitions': {
                'context_peak_fraction': 'Per-run maximum sampled input tokens / fixed window; repetitions averaged within case, then cases equally weighted. Main agent only.',
                'dominance': 'No greater burden on every case and all three metrics, strictly lower on at least one; all observations required.',
                'tradeoff': 'Opposite observed directions across metrics or cases; descriptive, not statistical significance.',
                'tolerance': EPSILON,
                'cost_scope': report['cost_scope'],
                'duration_scope': 'Original recorded duration_seconds, not inferred end-to-end or human time.'},
            'claim_limits': ['Feasibility uses the unchanged original per-case rules and regression guards.',
                             'Context completeness is submitted, not independently authenticated; sidecar is not prospective registration.',
                             'Sampled context peak is not cumulative token spend, semantic quality, or a causal explanation.',
                             'Missing context never becomes zero; partial traces cannot establish a peak comparison.',
                             'Frontier is limited to eligible observed candidates; unresolved candidates may change it.',
                             'No statistical equivalence, real benefit or recommendation follows from this view.']}

