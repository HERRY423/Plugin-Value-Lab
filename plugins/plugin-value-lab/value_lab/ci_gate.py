"""Offline CI adapter. Never launch a host, model, or submitted executable grader."""
import argparse
import json
from pathlib import Path

from .core import ValidationError, evaluate, load_json, load_records, write_json, load_suite
from .cli import write_records
from .report import _markdown


def gate_code(report):
    verdict = report.get('verdict')
    if report.get('blockers') or verdict in ('SIMULATION_ONLY', 'INSUFFICIENT_EVIDENCE'):
        return 2
    return {'PROMISING_LOCAL_SIGNAL': 0, 'NO_DEMONSTRATED_GAIN': 1,
            'REGRESSION_DETECTED': 1}.get(verdict, 2)


def _no_executables(value):
    if isinstance(value, dict):
        if value.get('type') in ('executable', 'exec'):
            raise ValidationError('CI does not execute submitted graders; use offline built-in graders')
        for child in value.values():
            _no_executables(child)
    elif isinstance(value, list):
        for child in value:
            _no_executables(child)


def summary(report, code, verified):
    def safe(value):
        return _markdown(value).replace('@', '&#64;')
    metrics = report.get('summary', {})
    lines = ['<!-- pvl-gate -->', '## PVL evidence gate', '',
             f'Verdict: **{safe(report["verdict"])}** · exit code **{code}**', '',
             '| Measure | WITH minus WITHOUT |', '| --- | --- |',
             f'| Quality Δ | {safe(metrics.get("quality_delta"))} |',
             f'| Cost Δ (USD) | {safe(metrics.get("cost_delta_usd"))} |', '',
             'Missing values are unknown, never zero. Positive cost Δ means greater cost.', '',
             f'SDK result byte checks: {verified}. These do not establish scientific validity.', '', 'Blockers:', '']
    lines += ['- ' + safe(v) for v in report.get('blockers', [])] or ['- None recorded.']
    lines += ['', 'Scope: submitted frozen comparison only; no causal, independent, or scientific certification.',
              'No model calls. Official Claude aggregate imports remain diagnostic evidence.']
    return '\n'.join(lines)[:60000] + '\n'


def run(suite, lock, output, *, records=None, claude_result=None, artifacts=None,
        corpus=None, cost_ledger=None, verify_results=()):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    verified = 0
    try:
        if (records is None) == (claude_result is None):
            raise ValidationError('Supply exactly one of records and claude_result')
        plan = load_suite(suite)
        _no_executables(plan)
        if claude_result is not None:
            from .native import import_claude
            native = load_json(claude_result)
            observations = import_claude(native, plan)
            write_records(root / 'imported.jsonl', observations)
            write_json(root / 'imported.jsonl.native-source.json', native)
        else:
            observations = load_records(records)
        report = evaluate(plan, observations, load_json(lock),
                          load_json(cost_ledger) if cost_ledger else None,
                          artifact_root=artifacts, corpus_root=corpus)
        write_json(root / 'report.json', report)
        # Preserve the original scoped report; artifact failures belong to the CI layer.
        report = {**report, 'blockers': list(report['blockers'])}
        # A separate byte-consistency check is required even after engine resume.
        from .sdk import verify_run
        for directory in verify_results:
            result = verify_run(directory)
            if result.status in ('CONTRACT_FAILED', 'UNKNOWN'):
                report['blockers'].append('SDK artifact status: ' + result.status)
            verified += 1
        code = gate_code(report)
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        report = {'verdict': 'INSUFFICIENT_EVIDENCE', 'blockers': [str(exc)], 'summary': {}}
        code = 2
        write_json(root / 'error.json', report)
    result = {'exit_code': code, 'verdict': report['verdict'], 'sdk_results_verified': verified,
              'model_calls': 0, 'budget_gate': 'PAID_EXECUTION_BLOCKED'}
    write_json(root / 'gate.json', result)
    (root / 'summary.md').write_text(summary(report, code, verified), encoding='utf-8')
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--suite', required=True)
    p.add_argument('--lock', required=True)
    p.add_argument('--output', required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--records')
    group.add_argument('--claude-result')
    for name in ('artifacts', 'corpus', 'cost-ledger'):
        p.add_argument('--' + name)
    p.add_argument('--verify-result', dest='verify_results', action='append', default=[])
    try:
        result = run(**vars(p.parse_args(argv)))
        print(json.dumps(result))
        return result['exit_code']
    except (OSError, ValueError) as exc:
        print(json.dumps({'exit_code': 2, 'error': str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
