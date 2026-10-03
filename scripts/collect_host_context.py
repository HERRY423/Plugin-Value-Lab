"""Capture explicitly selected native host records without executing a model."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.native_host_context import capture, PROFILES
from value_lab.core import ValidationError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, choices=[*PROFILES, 'antigravity-db'])
    parser.add_argument('--source', required=True)
    parser.add_argument('--session-id', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--prefix-bytes', type=int, help='Exact decompressed JSONL boundary; replay is not a new sample')
    parser.add_argument('--schema-binary', help='Exact qualified Antigravity language server; read only, never executed')
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        parser.error('Output already exists; preserve previous evidence and select a new output')
    try:
        if args.host == 'antigravity-db':
            if args.prefix_bytes is not None or not args.schema_binary:
                parser.error('Antigravity DB requires --schema-binary and forbids JSONL prefix options')
            from value_lab.antigravity_context import capture as capture_db
            result = capture_db(args.source, args.session_id, schema_binary=args.schema_binary)
        else:
            if args.schema_binary:
                parser.error('--schema-binary belongs only to antigravity-db')
            result = capture(args.source, args.session_id, host=args.host, prefix_bytes=args.prefix_bytes)
    except (ValidationError, OSError) as exc:
        parser.exit(2, f'Capture refused: {exc}\n')
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'state': result['state'], 'samples': len(result['samples']),
                      'request_usage': result['capabilities']['capabilities']['request_usage']['status'],
                      'context_sample': result['capabilities']['capabilities']['context_sample']['status'],
                      'model_calls_launched': 0}))


if __name__ == '__main__':
    main()
