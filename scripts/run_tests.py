"""Fast (<120 s wall time) or full tests, with explicit optional-dependency skips."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
FAST = ('core', 'core_adversarial', 'usage', 'report', 'value_metrics',
        'maintenance_regressions', 'sample_size', 'confirmatory', 'evidence_pool', 'gateway_budget', 'action_decision')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tier', choices=('fast', 'full'))
    parser.add_argument('--require-all', action='store_true', help='Release gate: reject any skips')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.tier == 'fast' and not args.worker:
        command = [sys.executable] + (['-S'] if sys.flags.no_site else [])
        command += [str(Path(__file__).resolve()), *sys.argv[1:], '--worker']
        try:
            return subprocess.run(command, cwd=ROOT, timeout=120).returncode
        except subprocess.TimeoutExpired:
            print('FAIL: fast tier exceeded 120 seconds', file=sys.stderr)
            return 1
    start = time.monotonic()
    loader = unittest.TestLoader()
    suite = (loader.loadTestsFromNames(['tests.test_' + name for name in FAST])
             if args.tier == 'fast' else loader.discover(str(ROOT / 'tests')))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    elapsed = time.monotonic() - start
    summary = {'tier': args.tier, 'seconds': round(elapsed, 3), 'tests': result.testsRun,
               'failures': [t.id() for t, _ in result.failures],
               'errors': [t.id() for t, _ in result.errors],
               'skipped': [{'test': t.id(), 'reason': reason} for t, reason in result.skipped],
               'requires_all': args.require_all}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{args.tier}: {result.testsRun} tests, {len(result.skipped)} skipped, {elapsed:.2f}s')
    return 0 if (result.wasSuccessful() and result.testsRun and
                 not (args.require_all and result.skipped) and (args.tier != 'fast' or elapsed < 120)) else 1


if __name__ == '__main__':
    raise SystemExit(main())
