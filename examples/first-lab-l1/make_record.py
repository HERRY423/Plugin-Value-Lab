"""Trial-packet worksheet helper: fill identities only, never scores or approvals."""
import argparse
import json
from pathlib import Path

from value_lab.core import load_json, suite_digest
from value_lab.screening import schedule


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    plan = load_json(args.plan)
    assert plan['format'] == 'pvl-screen-plan-1'
    assert suite_digest({k: v for k, v in plan.items() if k != 'plan_sha256'}) == plan['plan_sha256'], 'Changed frozen plan'
    rows = [{**row, 'plan_sha256': plan['plan_sha256'], 'status': 'not_run', 'score': None,
             'critical_failure': None, 'critical_verified_ref': None, 'evidence_ref': None,
             'scoring_ref': None, 'cost_micros': None, 'cost_ref': None, 'correction_seconds': None}
            for row in schedule(plan)]
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump({'plan_sha256': plan['plan_sha256'], 'runs': rows}, stream, ensure_ascii=False, indent=2)
    print(f'{len(rows)} NOT_RUN rows; no scores, approvals or model calls were generated.')


if __name__ == '__main__':
    main()
