"""Offline replay plus explicitly selected live tool recording; no live fallback."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import ValidationError, load_json
from value_lab.native_session import run_offline
from value_lab.replay import record_tools, serve_tools


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    record = subs.add_parser('record', help='Import explicitly sanitized MCP exchanges; never contact a backend')
    record.add_argument('transcript')
    record.add_argument('--output', required=True)
    live = subs.add_parser('record-live', help='Proxy a real stdio MCP server and automatically capture selected public tool calls')
    live.add_argument('--output', required=True)
    live.add_argument('--tool', action='append', required=True)
    live.add_argument('--public-data', action='store_true', help='Acknowledge that selected tool inputs/outputs are public or already de-identified')
    live.add_argument('--timeout', type=float, default=300)
    live.add_argument('command', nargs=argparse.REMAINDER)
    serve = subs.add_parser('serve', help='Strict ordered MCP stdio replay')
    serve.add_argument('cassette')
    serve.add_argument('--expected-id', required=True)
    run = subs.add_parser('run', help='Linux/WSL offline allowlist sandbox')
    run.add_argument('--inputs', required=True)
    run.add_argument('--file', action='append', required=True)
    run.add_argument('--output', required=True)
    run.add_argument('--cassette')
    run.add_argument('--expected-id')
    run.add_argument('--timeout', type=float, default=30)
    run.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.action == 'record':
            value = load_json(args.transcript)
            result = record_tools(args.output, value['tools'], value['exchanges'], provenance=value['provenance'])
        elif args.action == 'record-live':
            from value_lab.live_recording import record_live
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            result = record_live(command, args.output, args.tool, sys.stdin, sys.stdout,
                public_data=args.public_data, timeout_seconds=args.timeout)
            print(json.dumps(result, ensure_ascii=True), file=sys.stderr)
            return 0 if result['status'] == 'RECORDING_COMPLETE' else 2
        elif args.action == 'serve':
            result = serve_tools(args.cassette, args.expected_id, sys.stdin, sys.stdout)
            # stdout belongs exclusively to JSON-RPC messages.
            print(json.dumps(result, ensure_ascii=True), file=sys.stderr)
            return 0 if result['status'] == 'REPLAY_COMPLETE' else 2
        else:
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            result = run_offline(args.inputs, args.file, command, args.output,
                cassette=args.cassette, expected_id=args.expected_id, timeout_seconds=args.timeout)
        print(json.dumps(result, ensure_ascii=True))
        return 0 if result.get('status', 'COMPLETED') == 'COMPLETED' else 2
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'error': str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
