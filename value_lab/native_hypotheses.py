"""Evidence-linked, falsifiable hypotheses; never infer causes from correlations."""
from pathlib import Path
import json

from .artifacts import confined
from .core import ValidationError, load_json, suite_digest, write_json
from .native_evidence import _fresh, _separate, verify_native_evidence


STAGES = ('load', 'trigger', 'selection', 'execution', 'artifact', 'conclusion')


def skill_events(text, path):
    calls, replies = [], {}
    terminal_line = len(text.splitlines()) + 1
    for line, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        event = json.loads(raw)
        if event.get('type') == 'result':
            terminal_line = min(terminal_line, line)
        message = event.get('message')
        if not isinstance(message, dict) or not isinstance(message.get('content'), list):
            continue
        for block in message['content']:
            if not isinstance(block, dict):
                continue
            if event.get('type') == 'assistant' and block.get('type') == 'tool_use' and block.get('name') == 'Skill':
                arg = block.get('input')
                calls.append({'skill': arg.get('skill') if isinstance(arg, dict) else None, 'tool_use_id': block.get('id'),
                              'evidence': {'path': path, 'line': line}, 'result_status': 'UNKNOWN'})
            if event.get('type') == 'user' and block.get('type') == 'tool_result' and isinstance(block.get('tool_use_id'), str):
                replies.setdefault(block['tool_use_id'], []).append((line, block))
    for call in calls:
        key = call['tool_use_id']
        matches = replies.get(key, []) if isinstance(key, str) else []
        if key and len(matches) == 1 and sum(c['tool_use_id'] == key for c in calls) == 1:
            line, result = matches[0]
            if call['evidence']['line'] < line < terminal_line and type(result.get('is_error')) is bool:
                call['result_status'] = 'TOOL_ERROR' if result['is_error'] else 'TOOL_REPORTED_SUCCESS'
                call['result_evidence'] = {'path': path, 'line': line}
    return calls


def validate_expectations(expectations, plan):
    if not isinstance(expectations, dict) or set(expectations) != {'cases'} or not isinstance(expectations['cases'], dict):
        raise ValidationError('Expectations require a cases mapping')
    cases = {c['name']: c for c in plan['contract']['cases']}
    if set(expectations['cases']) != set(cases):
        raise ValidationError('Expectations must retain every frozen case')
    for name, expected in expectations['cases'].items():
        if not isinstance(expected, dict) or set(expected) != {'expected_skills', 'conclusion_grader_ids'}:
            raise ValidationError('Each case requires expected_skills and conclusion_grader_ids')
        for field in ('expected_skills', 'conclusion_grader_ids'):
            values = expected[field]
            if (not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values)
                    or len(values) != len(set(values))):
                raise ValidationError('Expectations must be unique nonempty strings')
        if not set(expected['conclusion_grader_ids']) <= {g['id'] for g in cases[name]['graders']}:
            raise ValidationError('Conclusion checks must name existing frozen graders; prose is not automatically graded')


def _fact(stage, status, observed, refs):
    return {'stage': stage, 'status': status, 'observed': observed, 'evidence': refs,
            'causal_explanation': None}


def _hypothesis(stage, facts):
    text = {
        'load': ('Candidate exposure may be missing or misconfigured.', 'Change only the candidate-loading configuration in a separate diagnostic run.',
                 'The expected plugin appears in the init record.', 'The expected plugin was already observed loaded or remains absent after the configuration change.'),
        'trigger': ('Natural wording may not trigger the intended skill.', 'Test a separate explicit-invocation prompt, retaining the original natural run and all artifact checks.',
                    'An observed expected Skill call and passing artifacts appear under explicit invocation.', 'Explicit invocation is observed but artifacts still fail, or the natural trace already contains the expected call.'),
        'selection': ('Skill descriptions may overlap or the expected capability mapping may be wrong.', 'Review the declared skill mapping, then change one selection cue in a separate diagnostic condition.',
                      'Observed calls move to the expected capability without degrading control tasks.', 'The alternative skill is appropriate on review or changing the cue does not change selection.'),
        'execution': ('A runtime or permission/resource problem may precede scientific analysis.', 'Inspect the exact failed tool result; vary only the suspected runtime condition in a diagnostic run.',
                      'The same command completes and artifacts become available.', 'The same failure persists, or the command completes but the artifact error remains.'),
        'artifact': ('The producing method or data handling may violate a frozen computational rule.', 'Inspect the named failed criterion and producing file, change one relevant implementation step, then retest all cases and controls.',
                     'The failed frozen check passes with unchanged inputs and no control regression.', 'The check still fails, a control regresses, or success requires changing the input/reference/threshold.'),
        'conclusion': ('The submitted decision may exceed the declared evidence boundary.', 'Restrict the claim or decision to the frozen evidence contract and obtain actual domain review where needed.',
                       'The same conclusion check passes and a reviewer can trace the claim to its supporting evidence.', 'The claim still lacks support or only passes after weakening the rule; computational pass alone cannot confirm biological truth.'),
    }[stage]
    return {'stage': stage, 'status': 'UNTESTED_EXPLANATION', 'hypothesis': text[0],
            'fact_refs': facts, 'intervention': text[1], 'prediction': text[2], 'falsifier': text[3],
            'preserve': ['original natural-use observations', 'input and reference bytes', 'all original graders and thresholds',
                         'all cases, repetitions and both arms', 'negative and non-refusal controls', 'failed and unknown outcomes'],
            'value_estimate_eligible': False, 'execution_authorized': False}


def build_native_hypotheses(directory, receipt_digest, expectations):
    root = Path(directory).resolve()
    report = verify_native_evidence(root, receipt_digest)['diagnosis']
    plan = load_json(root / 'plan.json')
    records = load_json(root / 'records.json')
    validate_expectations(expectations, plan)
    plugin_name = (plan.get('plugin_identity') or {}).get('name')
    rows = []
    for index, run in enumerate(report['runs']):
        expected = expectations['cases'][run['case_id']]
        obs = run.get('observations') or {}
        base = [{'path': 'records.json', 'pointer': f'/{index}'},
                {'path': 'diagnosis.json', 'pointer': f'/runs/{index}'}]
        events_path = f'runs/{index}/events.jsonl'
        trace_refs, called = [], []
        if confined(root, events_path).is_file():
            text = confined(root, events_path).read_text(encoding='utf-8-sig')
            called = skill_events(text, events_path)
            for line, raw in enumerate(text.splitlines(), 1):
                if not raw.strip():
                    continue
                event = json.loads(raw)
                if event.get('type') == 'system' and event.get('subtype') == 'init':
                    trace_refs.append({'path': events_path, 'line': line})
        supported = bool(obs.get('session_id'))
        plugins = obs.get('plugins')
        names = ([p['name'] for p in plugins] if isinstance(plugins, list) and
                 all(isinstance(p, dict) and isinstance(p.get('name'), str) and p['name'] for p in plugins) else None)
        load = 'UNKNOWN' if not supported or names is None or not plugin_name else 'OBSERVED' if plugin_name in names else 'NOT_OBSERVED'
        if run['arm'] == 'without':
            load = 'BASELINE_CONTAMINATED' if load == 'OBSERVED' else 'EXPECTED_ABSENCE' if load == 'NOT_OBSERVED' else 'UNKNOWN'
        expected_calls = [c for c in called if c['skill'] in expected['expected_skills']]
        # A truncated or unsupported stream cannot establish absence.
        complete = supported and obs.get('trace_complete') is True and all(isinstance(c['skill'], str) and c['skill'] for c in called)
        trigger = ('NOT_APPLICABLE' if run['arm'] == 'without' or not expected['expected_skills'] else
                   'UNKNOWN' if not supported else 'OBSERVED' if expected_calls else 'NOT_OBSERVED' if complete else 'UNKNOWN')
        alternatives = [c for c in called if isinstance(c['skill'], str) and c['skill'] not in expected['expected_skills']]
        selection = ('NOT_ASSESSED' if not expected['expected_skills'] or run['arm'] == 'without' else
                     'UNKNOWN' if not supported else 'EXPECTED_SKILL_OBSERVED' if expected_calls else
                     'OTHER_SKILL_OBSERVED' if alternatives else 'UNKNOWN')
        execution = run.get('execution')
        state = 'REPORTED_FAILURE' if run['status'] in ('error', 'aborted', 'timeout') else 'UNKNOWN'
        if execution and state != 'REPORTED_FAILURE':
            state = execution['status']
        elif run['status'] == 'completed':
            state = 'NATIVE_REPORTED_COMPLETION'
        conclusion_ids = set(expected['conclusion_grader_ids'])
        artifact_checks = [g for g in run['grades'] if g['id'] not in conclusion_ids]
        conclusion_checks = [g for g in run['grades'] if g['id'] in conclusion_ids]
        def checks_state(checks):
            return ('NOT_ASSESSED' if not checks else 'FAILED' if any(g['passed'] is False for g in checks)
                    else 'UNKNOWN' if any(g['passed'] is None for g in checks) else 'PASSED_COMPUTATIONAL_CHECKS')
        facts = [_fact('load', load, {'plugin_name': plugin_name, 'observed_plugins': names}, base + trace_refs),
                 _fact('trigger', trigger, {'expected_skills': expected['expected_skills'], 'calls': called}, base + trace_refs),
                 _fact('selection', selection, {'other_calls': alternatives, 'mapping_is_operator_declared': True}, base),
                 _fact('execution', state, {'native_status': run['status'], 'execution': execution}, base),
                 _fact('artifact', checks_state(artifact_checks), artifact_checks, base),
                 _fact('conclusion', checks_state(conclusion_checks), conclusion_checks, base)]
        candidates = {'load': load in ('NOT_OBSERVED', 'BASELINE_CONTAMINATED'), 'trigger': trigger == 'NOT_OBSERVED',
                      'selection': selection == 'OTHER_SKILL_OBSERVED', 'execution': state in ('REPORTED_FAILURE', 'TOOL_ERROR'),
                      'artifact': facts[4]['status'] == 'FAILED', 'conclusion': facts[5]['status'] == 'FAILED'}
        hypotheses = [_hypothesis(stage, [f'/runs/{index}/facts/{STAGES.index(stage)}']) for stage in STAGES if candidates[stage]]
        rows.append({'case_id': run['case_id'], 'arm': run['arm'], 'repetition': run['repetition'],
                     'session_id': records[index].get('session_id'), 'facts': facts, 'hypotheses': hypotheses,
                     'input_integrity': run.get('input_integrity'), 'actual_review': None})
    return {'schema_version': 1, 'type': 'native_falsifiable_hypotheses', 'receipt_sha256': receipt_digest,
            'expectations': expectations, 'expectations_sha256': suite_digest(expectations), 'runs': rows,
            'comparison_eligible': False, 'scientific_claim_review': 'NOT_ESTABLISHED',
            'scope': 'Observed facts and operator-declared diagnostic expectations; absence of a call is not a proven trigger defect. Explicit invocation is diagnostic only.'}


def write_native_hypotheses(directory, receipt_digest, expectations, output):
    output = _fresh(output)
    _separate(directory, output)
    report = build_native_hypotheses(directory, receipt_digest, expectations)
    output.mkdir(parents=True)
    write_json(output / 'hypotheses.json', report)
    lines = ['# 可检验的修复假设', '', '已观察事实与待检验解释分列；明确调用实验不能替代自然使用结果。', '']
    for row in report['runs']:
        lines.extend([f"## {row['case_id']} / {row['arm']} / {row['repetition']}", ''])
        for fact in row['facts']:
            lines.append(f"- {fact['stage']}: {fact['status']}；证据位置见 hypotheses.json。")
        for hypothesis in row['hypotheses']:
            lines.extend(['', hypothesis['hypothesis'], '- 检验：' + hypothesis['intervention'],
                          '- 预期观察：' + hypothesis['prediction'], '- 反证：' + hypothesis['falsifier']])
        lines.append('')
    lines.append(report['scope'])
    (output / 'HYPOTHESES.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'output': str(output), 'report_sha256': suite_digest(report), 'report': report}
