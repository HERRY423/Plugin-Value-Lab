"""Run a frozen local h5ad aggregation plan; print only the small receipt."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.artifacts import confined
from value_lab.core import ValidationError, load_json, suite_digest, _constant, _unique_object
from value_lab.science import keys, reference
from value_lab.science_execution import read_pinned
from value_lab.pseudobulk_backed import aggregate_h5ad


def run(plan, expected_id, inputs, output):
    keys(plan, 'format design data matrix obs_columns selection sample_covariates block_entries metadata_mb max_disk_bytes reserve_bytes')
    if plan['format'] != 'pvl-backed-counts-plan-1' or suite_digest(plan) != expected_id:
        raise ValidationError('Wrong or changed aggregation plan commitment')
    reference(plan['data'])
    design = json.loads(read_pinned(inputs, plan['design']), parse_constant=_constant, object_pairs_hook=_unique_object)
    options = {k: plan[k] for k in ('matrix', 'obs_columns', 'selection', 'sample_covariates',
                                   'block_entries', 'metadata_mb', 'max_disk_bytes', 'reserve_bytes')}
    result = aggregate_h5ad(design, confined(inputs, plan['data']['path']), output,
                           expected_sha256=plan['data']['sha256'], **options)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan')
    parser.add_argument('--expected-id', required=True)
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        result = run(load_json(args.plan), args.expected_id, args.inputs, args.output)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'error': str(exc)}, ensure_ascii=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
