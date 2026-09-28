"""Prepare and grade scientific metamorphic observations without executing model code."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import load_json, suite_digest, ValidationError
from value_lab.metamorphic import catalog, prepare, collect, assess


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    subs.add_parser('catalog')
    for action in ('prepare', 'collect', 'check'):
        sub = subs.add_parser(action)
        sub.add_argument('design')
        sub.add_argument('--expected-id', required=True, help='Frozen canonical design SHA-256')
        if action != 'check':
            sub.add_argument('--output', required=True)
        if action == 'collect':
            sub.add_argument('--results', required=True)
        if action == 'check':
            sub.add_argument('--observations', required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'catalog':
            result = catalog()
        else:
            design = load_json(args.design)
            if suite_digest(design) != args.expected_id:
                raise ValidationError('Metamorphic design commitment changed')
            if args.action == 'prepare':
                result = prepare(design, args.output)
            elif args.action == 'collect':
                result = collect(design, args.results, args.output)
            else:
                _, result = assess(design, load_json(args.observations))
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 2 if result.get('status') in ('FAIL', 'UNKNOWN') else 0
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'error': str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
