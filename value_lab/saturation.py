"""Prospective model-series ceiling diagnostics, regrading original records."""
from copy import deepcopy

from .core import ValidationError, evaluate, suite_digest, validate_suite
from .science import keys


def comparable_digest(suite):
    validate_suite(suite)
    fixed = deepcopy(suite)
    fixed['conditions']['model'] = 'MODEL_SERIES_VARIABLE'
    return suite_digest(fixed)


def plan(suite, models, minimum_versions=3, minimum_repetitions=3):
    validate_suite(suite)
    if (not isinstance(models, list) or not 2 <= len(models) <= 100
            or any(not isinstance(m, str) or not m.strip() for m in models) or len(set(models)) != len(models)):
        raise ValidationError('Supply a chronological series of distinct pinned model identifiers')
    if type(minimum_versions) is not int or not 2 <= minimum_versions <= len(models):
        raise ValidationError('Require at least two consecutive planned model versions')
    if type(minimum_repetitions) is not int or not 2 <= minimum_repetitions <= suite['runs_per_case']:
        raise ValidationError('Require at least two planned repeats per model')
    return {'format': 'pvl-saturation-design-1', 'comparable_suite_sha256': comparable_digest(suite),
            'models': list(models), 'minimum_versions': minimum_versions, 'minimum_repetitions': minimum_repetitions}


def analyze(design, studies, expected_id, *, artifact_root=None, verifier_root=None):
    keys(design, 'format comparable_suite_sha256 models minimum_versions minimum_repetitions')
    if suite_digest(design) != expected_id or design['format'] != 'pvl-saturation-design-1':
        raise ValidationError('Saturation plan differs from separately retained expected ID')
    if not isinstance(studies, list) or not studies or len(studies) > len(design['models']):
        raise ValidationError('Supply bounded original studies; missing planned versions remain unknown')
    indexed, case_ids, synthetic, session_ids = {}, None, False, set()
    for study in studies:
        keys(study, 'suite records lock')
        suite = study['suite']
        expected = plan(suite, design['models'], design['minimum_versions'], design['minimum_repetitions'])
        if suite_digest(expected) != expected_id:
            raise ValidationError('Task, graders, repetitions, plugin or non-model conditions changed across model versions')
        model = suite['conditions']['model']
        if model not in design['models'] or model in indexed:
            raise ValidationError('Unplanned or duplicate model version')
        for record in study['records']:
            sid = record.get('session_id')
            if isinstance(sid, str) and sid:
                if sid in session_ids:
                    raise ValidationError('Reused execution session across model versions')
                session_ids.add(sid)
        report = evaluate(suite, study['records'], study['lock'], artifact_root=artifact_root, verifier_root=verifier_root)
        indexed[model] = report
        synthetic |= report['evidence_type'] == 'synthetic'
        case_ids = [c['id'] for c in suite['cases']]
    cases = []
    for identity in case_ids:
        versions, streak = [], 0
        for model in design['models']:
            report = indexed.get(model)
            case = next((c for c in report['cases'] if c['id'] == identity), None) if report else None
            baseline = [r for r in case['runs'] if r['arm'] == 'without'] if case else []
            full = [r for r in case['runs'] if r['arm'] == 'with'] if case else []
            # Do not inherit the legacy text-rubric floor as scientific correctness.
            def correct(r):
                outcome = r.get('task_outcome', {})
                return (outcome.get('mode') == 'task' and outcome.get('passed') is True
                        and outcome.get('layers', {}).get('correctness', {}).get('passed') is True)
            valid = bool(report and not report['blockers'] and len(baseline) >= design['minimum_repetitions']
                         and all(r.get('task_outcome', {}).get('mode') == 'task' for r in baseline))
            ceiling = all(r['score'] == 1 and correct(r) for r in baseline) if valid else None
            streak = streak + 1 if ceiling is True else 0
            versions.append({'model': model, 'baseline_ceiling': ceiling,
                'baseline_scores': [r['score'] for r in baseline],
                'full_scores': [r['score'] for r in full], 'quality_delta': case['delta'] if case else None,
                'baseline_costs_usd': [r['cost_usd'] for r in baseline],
                'full_costs_usd': [r['cost_usd'] for r in full],
                'baseline_durations_seconds': [r.get('duration_seconds') for r in baseline],
                'full_durations_seconds': [r.get('duration_seconds') for r in full],
                'blockers': report['blockers'] if report else ['Planned model version not observed']})
        saturated = streak >= design['minimum_versions']
        cases.append({'case_id': identity, 'status': 'SATURATION_REVIEW' if saturated else 'NOT_ESTABLISHED',
                      'latest_window_complete': all(v['baseline_ceiling'] is not None
                          for v in versions[-design['minimum_versions']:]),
                      'consecutive_latest_versions': streak, 'versions': versions})
    return {'format': 'pvl-saturation-report-1', 'design_sha256': expected_id,
        'studies_sha256': suite_digest(studies), 'cases': cases,
        'saturation_index': sum(c['status'] == 'SATURATION_REVIEW' for c in cases) / len(cases),
        'index_meaning': 'Fraction of all planned cases flagged; unknown cases remain in denominator, not evidence of non-saturation',
        'unknown_cases': sum(not c['latest_window_complete'] for c in cases),
        'evidence_type': 'synthetic' if synthetic else 'submitted_observations',
        'scope': 'OBSERVED_BASELINE_QUALITY_CEILING_UNDER_FIXED_TASKS',
        'action': 'Review harder held-out cases in a new prospective protocol; retain original cases and cost/latency comparisons',
        'automatic_case_removal': False, 'model_version_order': 'OPERATOR_DECLARED_NOT_VERIFIED',
        'claim_limit': 'No claim of universal model ability, plugin obsolescence, population saturation or causal benefit'}
