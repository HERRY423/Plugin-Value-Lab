"""Explicit scientific recomputation commands, separate from offline grading."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import suite_digest
from value_lab.science_execution import capture_runtime, execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    freeze = subs.add_parser('freeze-runtime')
    freeze.add_argument('--package', action='append', required=True)
    run = subs.add_parser('run')
    run.add_argument('manifest')
    run.add_argument('--expected-id', required=True)
    run.add_argument('--inputs', required=True)
    run.add_argument('--submitted', required=True)
    for p in (freeze, run):
        p.add_argument('--runtime', help='Optional curated Linux venv with bin/python; mounted read-only at /runtime')
        p.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        if args.action == 'freeze-runtime':
            lock = capture_runtime(args.package, args.output, runtime=args.runtime)
            result = {'status': 'LOCKED', 'environment_sha256': suite_digest(lock)}
        else:
            result = execute(args.manifest, args.expected_id, args.inputs, args.submitted, args.output, runtime=args.runtime)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0 if result['status'] in ('LOCKED', 'REPRODUCED') else 2
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'error': str(exc)}, ensure_ascii=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
