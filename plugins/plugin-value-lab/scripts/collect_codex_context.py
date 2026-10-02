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
    args = parser.parse_args()
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
