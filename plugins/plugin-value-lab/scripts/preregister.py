"""Prepare or locally verify an explicitly obtained RFC3161 timestamp."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.preregistration import prepare_timestamp, verify_timestamp, verify_reviewer
from value_lab.core import load_json, write_json

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    a = sub.add_parser('prepare')
    for name in ('lock', 'output', 'openssl'):
        a.add_argument('--' + name, required=True)
    b = sub.add_parser('verify')
    for name in ('directory', 'lock-sha256', 'ca-file', 'ca-sha256', 'openssl'):
        b.add_argument('--' + name, required=True)
    c = sub.add_parser('verify-review')
    for name in ('statement', 'signature', 'trust', 'expected', 'output'):
        c.add_argument('--' + name, required=True)
    args = p.parse_args()
    if args.action == 'verify-review':
        result = verify_reviewer(load_json(args.statement), load_json(args.signature), load_json(args.trust), load_json(args.expected))
        write_json(args.output, result)
    else:
        result = (prepare_timestamp(args.lock, args.output, args.openssl) if args.action == 'prepare' else
                  verify_timestamp(args.directory, args.lock_sha256, args.ca_file, args.ca_sha256, args.openssl))
    print(json.dumps(result, ensure_ascii=True))
