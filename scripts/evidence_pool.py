"""Offline literature pool intake; no searches, signatures, uploads or model calls."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import ValidationError, load_json
from value_lab.evidence_pool import seed_pool, inspect_pool, public_manifest, review_statement, custody_statement


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('seed', 'inspect', 'export', 'review-statement', 'custody-statement'))
    parser.add_argument('--pool', type=Path)
    parser.add_argument('--trust', type=Path)
    parser.add_argument('--suite', type=Path)
    parser.add_argument('--family')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'seed':
            result = seed_pool()
        else:
            if args.pool is None:
                parser.error('--pool is required')
            pool = load_json(args.pool)
            trust = load_json(args.trust) if args.trust else {'keys': []}
            suite = load_json(args.suite) if args.suite else None
            if args.action == 'inspect':
                result = inspect_pool(pool, trust, suite)
            elif args.action == 'export':
                result = public_manifest(pool, trust, suite)
            elif args.action == 'review-statement':
                matches = [r['family'] for r in pool['development'] if r['family']['id'] == args.family]
                if len(matches) != 1:
                    raise ValidationError('Select exactly one development family with --family')
                result = review_statement(pool['id'], matches[0])
            else:
                inspect_pool(pool, trust, suite)
                result = custody_statement(pool)
        text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(text)
        else:
            print(text, end='')
        return 0
    except (ValidationError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
