"""Validate a bound conclusion citation; out-of-scope reuse exits with an error."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import load_json, write_json, ValidationError
from value_lab.claim_scope import cite

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('report', 'sha256', 'request', 'output'):
        p.add_argument('--' + name, required=True)
    a = p.parse_args()
    try:
        result = cite(load_json(a.report), load_json(a.request), a.sha256)
    except ValidationError as exc:
        write_json(a.output, {'status': 'ERROR', 'error': str(exc)})
        raise SystemExit(2)
    write_json(a.output, result)
    print(json.dumps({'status': result['status']}))
