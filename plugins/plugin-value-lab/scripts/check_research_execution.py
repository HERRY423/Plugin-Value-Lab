"""Prepare and audit the existing four research evals; never launch a model.

This is an acceptance utility, not a new public scoring engine. Native grader
reports remain unverified diagnostics. A local hash is not preregistration.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import ntpath
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.core import ValidationError, suite_digest, write_json
from value_lab.native import build_command, native_report

CASES = ('confounded-study', 'measurement-or-mechanism',
         'revision-is-not-progress', 'unknown-budget-and-novelty')
ARMS = ('with', 'without')


def file_hash(data):
    return hashlib.sha256(data).hexdigest()


def trace_identity(path):
    if not isinstance(path, str) or not path:
        return None
    # Normalize reported Windows aliases without reading any supplied path.
    if ntpath.splitdrive(path)[0] or '\\' in path:
        return ntpath.normcase(ntpath.normpath(path))
    from posixpath import normpath
    return normpath(path)


def prepare(output, model, judge_model, estimated_ceiling, root=ROOT):
    # Explicit distribution inventory excludes work/, account files and caches.
    from scripts.distribution import inventory
    output, root = Path(output).resolve(), Path(root).resolve()
    candidate = output / 'candidate'
    command = build_command(candidate, output / 'native-results', model, estimated_ceiling, 3)
    if not isinstance(judge_model, str) or not judge_model.strip() or judge_model.startswith('-') or any(c in judge_model for c in '\r\n\0'):
        raise ValidationError('An explicit judge model is required')
    command[command.index('--judge-model') + 1] = judge_model
    command[command.index('--eval-dir') + 1] = 'evals/research'
    command.extend(['--keep-temp', '--threshold', '1'])
    payload = inventory(root)
    source_digest = suite_digest({p: file_hash(data) for p, data in payload.items()})
    extension = 'extensions/research-directions/'
    for name, data in list(payload.items()):
        if name.startswith(extension):
            target = 'skills/research-directions/' + name[len(extension):]
            if target in payload:
                raise ValidationError('Research skill already present; review candidate scope')
            payload[target] = data
    if 'skills/research-directions/SKILL.md' not in payload:
        raise ValidationError('Research extension is missing')
    cases = []
    for directory in CASES:
        path = f'evals/research/{directory}/case.yaml'
        definition = json.loads(payload[path])
        if definition['runs'] != 3 or definition['name'] != 'research-' + directory:
            raise ValidationError('Research case identity or repetition count changed')
        if len(definition['graders']) != 1 or any(g['type'] != 'llm' or g.get('arm') != 'both' for g in definition['graders']):
            raise ValidationError('Review changed research outcome graders before preparing')
        source_hash = file_hash(payload[path])
        definition['graders'].append({
            'name': 'research-skill-activation', 'type': 'tool_used', 'tool': 'Skill',
            'input_match': r'"skill"\s*:\s*"(?:[\w-]+:)?research-directions"',
            'weight': 1, 'arm': 'with-only'})
        payload[path] = (json.dumps(definition, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        cases.append({'name': definition['name'], 'source_sha256': source_hash,
                      'candidate_sha256': file_hash(payload[path]), 'definition': definition})
    manifest = {p: file_hash(data) for p, data in payload.items()}
    plan = {'format': 'pvl-research-execution-1', 'cases': cases,
            'model': model, 'judge_model': judge_model,
            'source_distribution_sha256': source_digest,
            'candidate_manifest': manifest, 'candidate_sha256': suite_digest(manifest),
            'candidate_change': 'Enable research-directions in isolated copy; activation grader excluded from outcome score',
            'planned_agent_sessions': 24, 'planned_judge_calls_nominal': 72,
            'judge_count_limit': 'Nominal three votes per semantic grader per run; actual calls and retries require provider receipts',
            'native_threshold': 1, 'estimated_cost_ceiling_usd': estimated_ceiling,
            'settled_cost_cap_usd': None, 'execution_authorized': False,
            'command': command, 'independent_preregistration': False,
            'schedule': [{'case': c['name'], 'arm': arm, 'repetition': rep}
                         for c in cases for arm in ARMS for rep in range(1, 4)],
            'limits': ['Authored teaching cases, not held-out scientific tasks',
                       'Native array positions do not prove paired session identity',
                       'No settlement hard cap; resolve authorization and isolation before executing',
                       'Native grader pass is not PVL scientific task success']}
    output.mkdir(parents=True, exist_ok=False)
    for name, data in payload.items():
        destination = candidate / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    write_json(output / 'plan.json', plan)
    pin = suite_digest(plan)
    (output / 'plan.sha256').write_text(pin + '\n', encoding='utf-8')
    return {'plan_sha256': pin, 'planned_agent_sessions': 24,
            'planned_judge_calls_nominal': 72, 'model_calls': 0, 'execution_authorized': False}


def audit(plan, pin, result=None):
    if plan.get('format') != 'pvl-research-execution-1' or suite_digest(plan) != pin:
        raise ValidationError('Research plan pin mismatch')
    definitions = {c['name']: c['definition'] for c in plan['cases']}
    expected = [{'case': name, 'arm': arm, 'repetition': rep}
                for name, c in definitions.items() for arm in ARMS for rep in range(1, c['runs'] + 1)]
    if expected != plan['schedule'] or len(expected) != plan['planned_agent_sessions']:
        raise ValidationError('Frozen schedule is inconsistent')
    diagnostic = native_report(result) if result is not None else None
    reported = {c['name']: c for c in result['cases']} if result is not None else {}
    unexpected = sorted(set(reported) - set(definitions))
    blockers = ['Native reports do not establish host isolation, authenticated session/load provenance, settled costs or independent review']
    if result is None:
        blockers.append('No native result supplied')
    if unexpected:
        blockers.append('Unexpected cases cannot substitute for planned research cases: ' + ', '.join(unexpected))
    if result is not None and result.get('partial'):
        blockers.append('Native result is partial: ' + str(result.get('partialReason')))
    suite = result.get('suite', {}) if result is not None else {}
    if not isinstance(suite, dict):
        raise ValidationError('Native suite must be an object')
    suite_matches = (suite.get('ablation') == 'with-without' and suite.get('judgeModel') == plan['judge_model']
                     and type(suite.get('threshold')) in (int, float) and suite['threshold'] == plan['native_threshold'])
    if not suite_matches:
        blockers.append('Native ablation, judge model or threshold missing/changed')
    reported_cost = (result or {}).get('costUsd')
    cost_overrun = reported_cost is not None and reported_cost > plan['estimated_cost_ceiling_usd']
    if cost_overrun:
        blockers.append('Native reported cost exceeded the planned estimate ceiling; the ceiling is not a hard cap')
    # A repeated path is duplicate reported identity, never another repetition.
    trace_counts = Counter(trace_identity(run.get('tracePath')) for c in reported.values()
                           for runs in c['arms'].values() for run in runs
                           if isinstance(run.get('tracePath'), str) and run['tracePath'])
    rows, extra_runs = [], 0
    for name, definition in definitions.items():
        case = reported.get(name)
        mismatches = []
        if case:
            for key, value in {'model': plan['model'], 'runsPerCase': definition['runs'],
                               'maxTurns': definition['execution']['max_turns'],
                               'timeoutSeconds': definition['execution']['timeout_seconds'],
                               'promptMarkdown': definition['execution']['prompt']}.items():
                if type(case.get(key)) is not type(value) or case.get(key) != value:
                    mismatches.append(key)
            native_graders = case.get('graders', [])
            if not isinstance(native_graders, list) or any(not isinstance(g, dict) for g in native_graders):
                raise ValidationError('Native grader definitions must be an array of objects')
            if Counter(g.get('name') for g in native_graders) != Counter(g['name'] for g in definition['graders']):
                mismatches.append('grader_definitions')
            else:
                for grader in definition['graders']:
                    native = next(g for g in native_graders if g.get('name') == grader['name'])
                    config = native.get('config', {})
                    expected_config = {k: v for k, v in grader.items() if k not in ('name', 'type', 'weight')}
                    if (native.get('type') != grader['type'] or native.get('weight') != grader['weight']
                            or not isinstance(config, dict) or any(config.get(k) != v for k, v in expected_config.items())):
                        mismatches.append('grader:' + grader['name'])
            if mismatches:
                blockers.append(f'{name}: reported conditions missing/changed: {", ".join(mismatches)}')
            extra_runs += sum(max(0, len(case['arms'].get(a, [])) - definition['runs']) for a in ARMS)
        outcome_names = {g['name'] for g in definition['graders'] if g['type'] == 'llm'}
        for arm in ARMS:
            observed = case['arms'].get(arm, []) if case else []
            for rep in range(1, definition['runs'] + 1):
                row = {'case': name, 'arm': arm, 'repetition': rep, 'status': 'missing',
                       'reported_outcome_pass': None, 'activation_reported': None, 'issues': []}
                if rep <= len(observed):
                    run = observed[rep - 1]
                    row['status'] = ('aborted' if run.get('aborted') else 'error' if run['error'] is not None else 'completed')
                    row['native_run'] = deepcopy(run)
                    if not suite_matches:
                        row['issues'].append('suite_conditions_mismatch')
                    if cost_overrun:
                        row['issues'].append('reported_cost_overrun')
                    if mismatches:
                        row['issues'].append('conditions_mismatch')
                    path = run.get('tracePath')
                    if not isinstance(path, str) or not path:
                        row['issues'].append('trace_identity_missing')
                    elif trace_counts[trace_identity(path)] > 1:
                        row['issues'].append('duplicate_trace_identity')
                    if type(run.get('turns')) is not int:
                        row['issues'].append('turns_unknown')
                    elif run['turns'] > definition['execution']['max_turns'] or run['turns'] < 0:
                        row['issues'].append('turn_limit_deviation')
                    if run.get('skippedPaidGraders'):
                        row['issues'].append('skipped_paid_graders')
                    grades = run.get('graders', [])
                    if not isinstance(grades, list) or any(not isinstance(g, dict) for g in grades):
                        raise ValidationError('Native graders must be an array of objects')
                    outcomes = [g for g in grades if g.get('name') in outcome_names]
                    if (Counter(g.get('name') for g in outcomes) != Counter({n: 1 for n in outcome_names})
                            or any(type(g.get('passed')) is not bool or g.get('scored') is not True
                                   or not isinstance(g.get('explanation'), str) or not g['explanation'].strip()
                                   for g in outcomes)):
                        row['issues'].append('outcome_judging_missing_or_unscored')
                    activation = [g for g in grades if g.get('name') == 'research-skill-activation']
                    if len(activation) == 1 and type(activation[0].get('passed')) is bool and activation[0].get('scored') is False:
                        row['activation_reported'] = activation[0]['passed']
                    elif arm == 'with':
                        row['issues'].append('activation_indicator_missing_or_scored')
                    if row['status'] == 'completed' and not row['issues']:
                        row['reported_outcome_pass'] = all(g['passed'] for g in outcomes)
                rows.append(row)
    if extra_runs:
        blockers.append('Extra repetitions are retained in native diagnostic, not substituted into the frozen schedule')
    counts = Counter(r['status'] for r in rows)
    summaries = {}
    for arm in ARMS:
        arm_rows = [r for r in rows if r['arm'] == arm]
        passed = sum(r['reported_outcome_pass'] is True for r in arm_rows)
        failed = sum(r['reported_outcome_pass'] is False for r in arm_rows)
        unknown = len(arm_rows) - passed - failed
        summaries[arm] = {'planned': len(arm_rows), 'reported_pass': passed, 'reported_fail': failed,
                          'unknown': unknown, 'reported_pass_bounds': [passed / len(arm_rows), (passed + unknown) / len(arm_rows)]}
    lower = summaries['with']['reported_pass_bounds'][0] - summaries['without']['reported_pass_bounds'][1]
    upper = summaries['with']['reported_pass_bounds'][1] - summaries['without']['reported_pass_bounds'][0]
    missing = counts['missing']
    judged = sum(r['reported_outcome_pass'] is not None for r in rows)
    if missing or judged != len(rows):
        blockers.append('Planned research coverage/judging is incomplete; missing slots remain in the denominator')
    return {'format': 'pvl-research-execution-audit-1', 'plan_sha256': pin,
            'result_sha256': suite_digest(result) if result is not None else None,
            'status': 'INSUFFICIENT_EVIDENCE',
            'reported_coverage_complete': judged == len(rows) and not extra_runs and not unexpected
                and not (result or {}).get('partial', True) and suite_matches and not cost_overrun,
            'planned_sessions': len(rows), 'reported_slots': len(rows) - missing,
            'missing_slots': missing, 'statuses': dict(counts), 'judged_run_reports': judged,
            'actual_agent_calls': None, 'actual_judge_calls': None,
            'extra_runs': extra_runs, 'unexpected_cases': unexpected, 'arms': summaries,
            'reported_outcome_delta_bounds': [lower, upper],
            'bounds_meaning': 'Missingness bounds over frozen slots, not confidence intervals or scientific success',
            'cost': {'native_reported_usd': (result or {}).get('costUsd'), 'settled_usd': None},
            'rows': rows, 'native_diagnostic': diagnostic, 'blockers': blockers,
            'claim_limits': ['No aggregate field proves actual paid call counts or grader independence',
                             'Reported rubric definitions are compared; loaded plugin bytes and trace contents require separate verification',
                             'Research extension opt-in is a different candidate from default PVL',
                             'Teaching cases and local acceptance do not establish scientific benefit']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--output', required=True)
    prep.add_argument('--model', required=True)
    prep.add_argument('--judge-model', required=True)
    prep.add_argument('--estimated-ceiling', type=float, required=True)
    check = sub.add_parser('audit')
    check.add_argument('--plan', required=True)
    check.add_argument('--plan-sha256', required=True)
    check.add_argument('--result')
    check.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.mode == 'prepare':
        receipt = prepare(args.output, args.model, args.judge_model, args.estimated_ceiling)
    else:
        plan = json.loads(Path(args.plan).read_text(encoding='utf-8'))
        result = json.loads(Path(args.result).read_text(encoding='utf-8')) if args.result else None
        receipt = audit(plan, args.plan_sha256, result)
        with Path(args.output).open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
    print(json.dumps({k: receipt[k] for k in receipt if k in (
        'plan_sha256', 'planned_agent_sessions', 'planned_sessions', 'reported_slots', 'missing_slots',
        'judged_run_reports', 'status', 'reported_coverage_complete', 'model_calls', 'execution_authorized')}, ensure_ascii=True))
    # Zero means successful preparation or complete *reported* coverage only.
    # It is never a scientific-benefit or host-acceptance gate.
    return 0 if args.mode == 'prepare' or receipt['reported_coverage_complete'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
