"""Explicit-invocation diagnostic probes kept outside natural-use value estimates."""
from copy import deepcopy
from pathlib import Path
import re

from .core import ValidationError, load_json, suite_digest, write_json
from .native_evidence import _fresh, _plan, _put, _separate, prepare_native_evidence, verify_native_evidence
from .native_hypotheses import validate_expectations, skill_events


def _suffix(skill):
    return ('\n\n[PVL explicit-invocation diagnostic, not a natural-use value trial]\n'
            f'Explicitly invoke the Skill named "{skill}" before solving the unchanged task. '
            'If that skill is unavailable, report it; do not pretend it was invoked.\n').encode('utf-8')


def prepare_trigger_probe(directory, plan_digest, expectations, output, *, references=None):
    root, plan = _plan(directory, plan_digest)
    if 'diagnostic_intent' in plan['contract']:
        raise ValidationError('Probe source must be the original natural-use plan')
    validate_expectations(expectations, plan)
    selected = {}
    for name, value in expectations['cases'].items():
        if not value['expected_skills'] or not re.fullmatch(r'[A-Za-z0-9_.:-]+', value['expected_skills'][0]):
            raise ValidationError('Each diagnostic case needs an explicit safe primary skill name')
        selected[name] = value['expected_skills'][0]
    output = _fresh(output)
    _separate(root, output)
    if references is not None:
        _separate(references, output)
    files = {}
    for field, prefix in (('plugin_files', 'plugin'), ('case_files', 'cases')):
        for relative in plan[field]:
            files[relative] = (root / prefix / relative).read_bytes()
    for case in plan['contract']['cases']:
        prompt = case['case_directory'] + '/prompt.md'
        if prompt not in plan['case_files']:
            raise ValidationError('Automatic probe requires an existing prompt.md; case.yaml-only prompts are not rewritten')
        files[prompt] += _suffix(selected[case['name']])
    contract = deepcopy(plan['contract'])
    contract['diagnostic_intent'] = {'mode': 'explicit_invocation', 'source_plan_sha256': plan_digest,
                                     'expected_skills': selected}
    candidate = output / 'candidate'
    candidate.mkdir(parents=True)
    for relative, content in files.items():
        _put(candidate, relative, content)
    result = prepare_native_evidence(candidate, contract, output / 'plan', references=references)
    write_json(output / 'contract.json', contract)
    write_json(output / 'probe.json', {'source_plan_sha256': plan_digest, 'probe_plan_sha256': result['plan_sha256'],
                                      'expectations': expectations, 'execution_authorized': False, 'model_calls': 0,
                                      'comparison_eligible': False, 'purpose': 'diagnostic contrast only'})
    return {'output': str(output), 'plan_sha256': result['plan_sha256'], 'model_calls': 0,
            'comparison_eligible': False, 'scope': 'Original cases retained; only the explicit diagnostic instruction is appended. Do not replace the natural-use study.'}


def compare_trigger_probe(natural, natural_digest, explicit, explicit_digest, expectations, output):
    roots = [Path(natural).resolve(), Path(explicit).resolve()]
    output = _fresh(output)
    for root in roots:
        _separate(root, output)
    reports = [verify_native_evidence(root, digest)['diagnosis'] for root, digest in zip(roots, (natural_digest, explicit_digest))]
    plans = [load_json(root / 'plan.json') for root in roots]
    records = [load_json(root / 'records.json') for root in roots]
    validate_expectations(expectations, plans[0])
    problems = []
    original, probe = [p['contract'] for p in plans]
    intent = probe.get('diagnostic_intent', {})
    source_pin = load_json(roots[0] / 'receipt.json')['plan_sha256']
    if (intent.get('mode') != 'explicit_invocation' or intent.get('source_plan_sha256') != source_pin
            or 'diagnostic_intent' in original):
        problems.append('Explicit probe is not bound to this original natural-use plan')
    if {k: v for k, v in probe.items() if k != 'diagnostic_intent'} != original:
        problems.append('Contract changed beyond the diagnostic intent')
    for field in ('plugin_files', 'plugin_identity', 'references'):
        if plans[0][field] != plans[1][field]:
            problems.append(field + ' changed')
    expected_files = dict(plans[0]['case_files'])
    import hashlib
    for case in original['cases']:
        name = case['name']
        skills = expectations['cases'][name]['expected_skills']
        chosen = intent.get('expected_skills', {}).get(name)
        if not skills or chosen != skills[0]:
            problems.append(name + ': probe skill differs from diagnostic expectation')
            continue
        relative = case['case_directory'] + '/prompt.md'
        path = roots[0] / 'cases' / relative
        if not path.is_file():
            problems.append(name + ': natural prompt.md unavailable')
        else:
            expected_files[relative] = hashlib.sha256(path.read_bytes() + _suffix(chosen)).hexdigest()
    if plans[1]['case_files'] != expected_files:
        problems.append('Case bytes changed beyond the exact diagnostic suffix')
    all_sessions = []
    contexts = []
    for raw_records, report in zip(records, reports):
        if report.get('native_partial') is not False:
            problems.append('Native completion partial or unknown')
        current = set()
        for record, run in zip(raw_records, report['runs']):
            case = next(c for c in original['cases'] if c['name'] == run['case_id'])
            if set(record['inputs']) != set(case['inputs']):
                problems.append('Declared input evidence missing')
            obs = run.get('observations') or {}
            if not record.get('session_id') or not obs.get('trace_complete') or run['status'] != 'completed':
                problems.append('Incomplete observed session or failed execution')
            else:
                all_sessions.append(record['session_id'])
            context = [obs.get('model'), obs.get('claude_code_version'), obs.get('tools')]
            if any(v is None for v in context):
                problems.append('Observed model, host or tools missing')
            current.add(suite_digest(context))
            if run['arm'] == 'without' and obs.get('plugins') != []:
                problems.append('Baseline plugin exposure missing or contaminated')
        contexts.append(current)
    if len(all_sessions) != len(set(all_sessions)) or natural_digest == explicit_digest:
        problems.append('Sessions or original evidence reused')
    if contexts[0] != contexts[1] or len(contexts[0]) != 1:
        problems.append('Observed execution context changed')
    def input_fingerprints(raw_records):
        return {(r['case_id'], r['arm'], r['repetition']): {k: v['sha256'] for k, v in r['inputs'].items()} for r in raw_records}
    if input_fingerprints(records[0]) != input_fingerprints(records[1]):
        problems.append('Observed input bytes changed')
    rows = []
    plugin_name = (plans[0].get('plugin_identity') or {}).get('name')
    for case in original['cases']:
        counts = []
        for side, report in enumerate(reports):
            runs = [r for r in report['runs'] if r['case_id'] == case['name'] and r['arm'] == 'with']
            count = {'runs': len(runs), 'expected_calls': 0, 'successful_skill_results': 0, 'artifact_pass': 0, 'artifact_fail': 0, 'unknown': 0}
            for run in runs:
                obs = run.get('observations') or {}
                plugins = obs.get('plugins')
                names = [p.get('name') for p in plugins if isinstance(p, dict)] if isinstance(plugins, list) else None
                if not plugin_name or names != [plugin_name]:
                    problems.append('Expected plugin exposure not observed')
                calls = obs.get('skill_calls')
                if not isinstance(calls, list) or any(not isinstance(c, dict) or not isinstance(c.get('skill'), str) for c in calls):
                    count['unknown'] += 1
                elif any(c['skill'] in expectations['cases'][case['name']]['expected_skills'] for c in calls):
                    count['expected_calls'] += 1
                index = report['runs'].index(run)
                path = roots[side] / f'runs/{index}/events.jsonl'
                if path.is_file():
                    traced = skill_events(path.read_text(encoding='utf-8-sig'), f'runs/{index}/events.jsonl')
                    matching = [c for c in traced if c['skill'] in expectations['cases'][case['name']]['expected_skills']]
                    count['successful_skill_results'] += bool(matching) and all(c['result_status'] == 'TOOL_REPORTED_SUCCESS' for c in matching)
                values = [g['passed'] for g in run['grades']]
                count['artifact_pass'] += all(v is True for v in values)
                count['artifact_fail'] += any(v is False for v in values)
                count['unknown'] += any(v is None for v in values)
                if any(v != 'MATCH' for v in run.get('input_integrity', {}).values()):
                    count['unknown'] += 1
                if 'execution' in run and (run['execution']['status'] != 'TOOL_REPORTED_SUCCESS'
                        or run['execution']['terminal_status'] != 'SUCCESS' or run['execution']['model_conflict_observed']):
                    count['unknown'] += 1
            counts.append(count)
        a, b = counts
        supported = (not problems and a['runs'] == b['runs'] == case['repetitions'] and a['expected_calls'] == 0
                     and a['artifact_fail'] > 0 and b['expected_calls'] == b['artifact_pass'] == b['successful_skill_results'] == b['runs']
                     and a['unknown'] == b['unknown'] == 0)
        rows.append({'case_id': case['name'], 'natural': a, 'explicit': b,
                     'finding': 'TEST_TRIGGER_DESCRIPTION_NEXT' if supported else 'TRIGGER_EXPLANATION_NOT_ESTABLISHED'})
    if problems:
        for row in rows:
            row['finding'] = 'TRIGGER_EXPLANATION_NOT_ESTABLISHED'
    report = {'schema_version': 1, 'status': 'CONTROLLED_DIAGNOSTIC_CONTRAST' if not problems else 'INCOMPARABLE_DIAGNOSTIC',
              'natural_receipt': natural_digest, 'explicit_receipt': explicit_digest, 'cases': rows,
              'problems': sorted(set(problems)), 'comparison_eligible': False, 'natural_use_value_replaced': False,
              'scope': 'Even a controlled explicit-invocation success only prioritizes a falsifiable trigger hypothesis; prompt assistance and sampling remain competing explanations.'}
    output.mkdir(parents=True)
    write_json(output / 'trigger-comparison.json', report)
    return report
