"""Concise CLI for the public SDK; legacy expert CLI remains compatible."""
import argparse
import inspect
import json
from pathlib import Path
import re
import sys

from . import __version__
from . import sdk


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise sdk.PVLError('USAGE', message, 'Run pvl <command> --help for examples and required options.')


def byte_size(text):
    match = re.fullmatch(r'(\d+)(B|KiB|MiB|GiB|TiB)?', text, re.IGNORECASE)
    if not match:
        raise argparse.ArgumentTypeError('Use integer bytes or a binary unit, e.g. 512MiB or 4GiB')
    scale = {'b': 1, 'kib': 1024, 'mib': 1024**2, 'gib': 1024**3, 'tib': 1024**4}
    return int(match[1]) * scale[(match[2] or 'B').lower()]


def parser():
    p = Parser(prog='pvl', description='Local scientific checks and counts aggregation, without hand-written hashes.',
               epilog='First run: pvl demo --output first-result | Python: from value_lab.sdk import aggregate_counts')
    p.add_argument('--version', action='version', version=__version__)
    p.add_argument('--json', action='store_true', help='One JSON object on stdout; progress stays on stderr')
    sub = p.add_subparsers(dest='command', required=True)
    for name, help_text in [('demo', 'Run a zero-dependency synthetic example'), ('doctor', 'Check only local feature dependencies'),
                             ('inspect', 'Show h5ad shape, columns and matrices without loading counts'),
                             ('aggregate', 'Aggregate donor-paired raw counts from h5ad'),
                             ('check', 'Audit a table using an explicitly selected rule'),
                             ('verify', 'Verify saved result files without rerunning analysis')]:
        child = sub.add_parser(name, help=help_text, description=help_text)
        child.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
        if name in ('inspect', 'aggregate', 'check'):
            child.add_argument('source', type=Path)
        if name in ('demo', 'aggregate', 'check'):
            child.add_argument('--output', required=True, type=Path, help='New result directory; existing files are preserved')
        if name in ('aggregate', 'check'):
            child.add_argument('--reuse', action='store_true', help='Reuse only a complete result with matching input, settings, code and artifact hashes')
        if name == 'aggregate':
            child.add_argument('--config', type=Path, help='Optional saved biological/settings JSON for workflow engines; CLI values override named settings')
            for key in ('cell_type', 'control', 'treatment', 'matrix', 'sample_key', 'donor_key', 'condition_key', 'cell_type_key'):
                child.add_argument('--' + key.replace('_', '-'), default=argparse.SUPPRESS)
            for key in ('min_cells', 'min_total_count', 'block_entries', 'metadata_mb'):
                child.add_argument('--' + key.replace('_', '-'), type=int, default=argparse.SUPPRESS)
            child.add_argument('--disk-budget', type=byte_size, default=argparse.SUPPRESS, help='Maximum working disk bytes, default 4GiB')
            child.add_argument('--reserve-bytes', type=byte_size, default=argparse.SUPPRESS, help='Free disk reserve, default 256MiB')
            child.add_argument('--select-design', action='store_const', dest='selection', const='design', default=argparse.SUPPRESS,
                               help='Explicitly select the declared cell type and contrast; default rejects other cells')
            child.add_argument('--dry-run', action='store_true', help='Check headers and configuration only; write nothing')
            child.epilog = ('Required: --cell-type, --control, --treatment (or config). Default matrix layers/counts; '
                            'use --matrix X only for raw X. Default min-cells=10, min-total-count=10. '
                            'Example: pvl aggregate counts.h5ad --cell-type B --control ctrl --treatment stim --output result')
        elif name == 'check':
            child.add_argument('--rule', required=True, choices=['bh'], help='BH is never inferred from the table')
        elif name == 'verify':
            child.add_argument('directory', type=Path)
            child.add_argument('--expected-id', help='Optional separately retained manifest commitment')
    return p


def _settings(args):
    from .core import load_json
    settings = {}
    if args.config:
        if args.config.stat().st_size > 1048576:
            raise sdk.PVLError('INVALID_CONFIG', 'Settings exceed 1 MiB.', 'Use a small settings document; keep counts in h5ad.')
        settings = load_json(args.config)
        if not isinstance(settings, dict):
            raise sdk.PVLError('INVALID_CONFIG', 'Settings must be an object.', 'Use the settings.json example with named biological choices.')
    allowed = set(inspect.signature(sdk.aggregate_counts).parameters) - {'source', 'output', 'reuse', 'progress', 'dry_run'}
    if set(settings) - allowed:
        raise sdk.PVLError('INVALID_CONFIG', 'Unknown settings: ' + ', '.join(sorted(set(settings) - allowed)), 'Correct the setting name; unknown settings are never ignored.')
    settings = {**settings, **{k: v for k, v in vars(args).items() if k in allowed}}
    missing = {'cell_type', 'control', 'treatment'} - set(settings)
    if missing:
        raise sdk.PVLError('MISSING_DESIGN', 'Missing biological choices: ' + ', '.join(sorted(missing)), 'Pass --cell-type, --control and --treatment, or declare them in --config.')
    return settings


def main(argv=None):
    # Windows terminals may use an encoding that cannot display research paths.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='backslashreplace')
    argv = list(sys.argv[1:] if argv is None else argv)
    json_output = '--json' in argv
    try:
        args = parser().parse_args(argv)
        json_output = args.json
        if args.command == 'demo':
            result = sdk.demo(args.output)
        elif args.command == 'doctor':
            result = sdk.doctor()
        elif args.command == 'inspect':
            result = sdk.inspect_counts(args.source)
        elif args.command == 'aggregate':
            result = sdk.aggregate_counts(args.source, output=args.output, reuse=args.reuse, dry_run=args.dry_run,
                progress=lambda message: print(message, file=sys.stderr), **_settings(args))
        elif args.command == 'check':
            result = sdk.check_bh(args.source, output=args.output, reuse=args.reuse)
        else:
            result = sdk.verify_run(args.directory, expected_id=args.expected_id)
        data = result.to_dict() if isinstance(result, sdk.RunResult) else result
        if json_output:
            print(json.dumps(data, ensure_ascii=True, allow_nan=False))
        elif isinstance(result, sdk.RunResult):
            print(f'{result.status}' + (' (verified reuse)' if result.reused else ''))
            print(f'Report: {result.report}')
            if result.counts:
                print(f'Counts: {result.counts}')
            print(f'Commitment: {result.commitment}')
        elif args.command == 'inspect':
            print(f'Shape: {data["shape"][0]:,} cells x {data["shape"][1]:,} genes')
            print('Columns: ' + ', '.join(data['obs_columns']))
            print('Matrices: ' + ', '.join(data['matrices']))
            print('Headers only; raw counts have not been verified.')
        else:
            print(json.dumps(data, ensure_ascii=True, indent=2, allow_nan=False))
        return 3 if data.get('status') == 'CONTRACT_FAILED' else 4 if data.get('status') == 'UNKNOWN' else 0
    except KeyboardInterrupt:
        error = sdk.PVLError('INTERRUPTED', 'Interrupted by the user.', 'Partial work remains incomplete. Inspect the output and use a new directory for another attempt.')
        code = 130
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        error, code = sdk._translate(exc), 2
    if json_output:
        print(json.dumps(error.to_dict(), ensure_ascii=True, allow_nan=False))
    else:
        print(f'{error.code}: {error}\nNext step: {error.hint}', file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
