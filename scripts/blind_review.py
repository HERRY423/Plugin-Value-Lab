"""Prepare blinded cases or score reviewer labels separately from author labels."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import load_json
from value_lab.blind_review import prepare, score


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    export = sub.add_parser('prepare')
    export.add_argument('manifest')
    export.add_argument('--selection', required=True)
    export.add_argument('--verifiers')
    export.add_argument('--output', required=True)
    report = sub.add_parser('score')
    report.add_argument('controller')
    report.add_argument('--expected-id', required=True)
    report.add_argument('--packet', required=True)
    report.add_argument('--labels', required=True)
    report.add_argument('--output', required=True)
    a = p.parse_args()
    try:
        if a.action == 'prepare':
            result = prepare(a.manifest, load_json(a.selection), a.output, verifier_root=a.verifiers)
        else:
            result = score(a.controller, a.expected_id, a.packet, a.labels)
            with Path(a.output).open('x', encoding='utf-8') as stream:
                json.dump(result, stream, ensure_ascii=True, indent=2)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'error': str(exc)}, ensure_ascii=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
