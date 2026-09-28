"""Freeze/check a local science runtime, or replay its recorded artifacts without it."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import load_json, suite_digest, write_json
from value_lab.science_environment import capture_environment, check_environment, replay_reference


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    freeze = subs.add_parser('freeze')
    freeze.add_argument('--package', action='append', required=True)
    freeze.add_argument('--output', required=True)
    check = subs.add_parser('check')
    check.add_argument('lock')
    check.add_argument('--expected-id', required=True)
    replay = subs.add_parser('replay-reference')
    replay.add_argument('reference')
    replay.add_argument('--expected-id', required=True)
    replay.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'freeze':
            lock = capture_environment(args.package)
            with Path(args.output).open('x', encoding='utf-8') as stream:
                json.dump(lock, stream, ensure_ascii=True, indent=2)
                stream.write('\n')
            result = {'status': 'ENVIRONMENT_LOCKED', 'environment_sha256': suite_digest(lock),
                      'scientific_execution': False}
        elif args.action == 'check':
            result = check_environment(load_json(args.lock), args.expected_id)
        else:
            result = replay_reference(args.reference, args.expected_id, args.output)
        print(json.dumps(result, ensure_ascii=True))
        return 2 if result['status'] == 'ENVIRONMENT_DRIFT' else 0
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'error': str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
