"""Real OS acceptance for enlarged output, file/total limits and timeout."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.core import write_json
from value_lab.native_session import run_offline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    rows = {}
    for name, script, total, per_file, timeout in [
        ('large-output', 'with open("large.bin","wb") as f:\n for _ in range(33): f.write(b"x"*1048576)\n', 40, 40, 10),
        ('file-limit', 'with open("large.bin","wb") as f:\n for _ in range(3): f.write(b"x"*1048576)\n', 4, 1, 10),
        ('total-limit', 'from pathlib import Path\nfor i in range(3): Path(str(i)).write_bytes(b"x"*1048576)\n', 2, 1, 10),
        ('timeout', 'import time\ntime.sleep(10)\n', 1, 1, 1),
    ]:
        inputs = root / (name + '-input')
        inputs.mkdir()
        (inputs / 'run.py').write_text(script, encoding='utf-8')
        rows[name] = run_offline(inputs, ['run.py'], ['/usr/bin/python3', '-I', '/inputs/run.py'],
            root / name, timeout_seconds=timeout, memory_mb=128,
            resources={'input_bytes': 1048576, 'output_bytes': total*1048576,
                       'file_bytes': per_file*1048576, 'reserve_bytes': 0})
    assert rows['large-output']['status'] == 'COMPLETED'
    assert (root / 'large-output/artifacts/large.bin').stat().st_size == 33*1048576
    assert all(rows[n]['status'] == 'FAILED' for n in ('file-limit', 'total-limit', 'timeout'))
    assert rows['total-limit']['error'].startswith('RESOURCE_LIMIT:')
    result = {'status': 'PASS', 'real_os_execution': True, 'cases': rows,
              'large_output_bytes': 33*1048576, 'scientific_validity': 'NOT_ESTABLISHED'}
    write_json(root / 'acceptance.json', result)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
