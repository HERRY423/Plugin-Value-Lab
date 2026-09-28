"""Explicit synthetic adapter. A real analysis can use the same input/result contract."""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('input')
parser.add_argument('output')
parser.add_argument('--fault', choices=['none', 'first-row', 'constant-zero'], default='none')
args = parser.parse_args()
source = json.loads(Path(args.input).read_text(encoding='utf-8'))
matrix = source['matrix']
rows = matrix['values'][:1] if args.fault == 'first-row' else matrix['values']
values = [sum(row[i] for row in rows) for i in range(len(matrix['columns']))]
if args.fault == 'constant-zero':
    values = [0] * len(values)
# Match PVL's canonical commitment; hash observed input, not a caller's claim.
canonical = json.dumps(source, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
result = {'input_sha256': hashlib.sha256(canonical).hexdigest(), 'status': 'completed',
          'output': {'row_ids': ['sum'], 'columns': matrix['columns'], 'values': [values]}}
with Path(args.output).open('x', encoding='utf-8') as stream:
    json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
    stream.write('\n')
