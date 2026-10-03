"""Capture a specified local Codex rollout without launching a model."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.codex_context import capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rollout', required=True)
    parser.add_argument('--session-id', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--prefix-bytes', type=int)
    parser.add_argument('--incremental', action='store_true', help='Publish a private checkpoint/report bundle')
    parser.add_argument('--previous', help='Previous committed incremental bundle')
    parser.add_argument('--max-new-bytes', type=int, default=64 * 1024 * 1024)
    parser.add_argument('--resume-publication', action='store_true')
    args = parser.parse_args()
    if args.incremental:
        if args.prefix_bytes is not None:
            parser.error('--prefix-bytes belongs to the legacy snapshot mode')
        from value_lab.context_stream import capture_incremental
        result = capture_incremental(args.rollout, args.session_id, args.output,
            previous=args.previous, max_new_bytes=args.max_new_bytes, resume=args.resume_publication)
        print(json.dumps({'delivery': result['delivery'], 'state': result['report']['state'],
                          'new_response_count': result['report']['new_response_count'],
                          'model_calls_launched': 0}, ensure_ascii=True))
        return
    if args.previous or args.resume_publication or args.max_new_bytes != 64 * 1024 * 1024:
        parser.error('Checkpoint options require --incremental')
    result = capture(args.rollout, args.session_id, prefix_bytes=args.prefix_bytes)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'output': str(target), 'state': result['state'],
                      'supported': result['adapter_supported'], 'samples': len(result['samples']),
                      'model_calls_launched': 0}, ensure_ascii=True))


if __name__ == '__main__':
    main()
