"""Export and independently anchor a synthetic study; no science/review claims."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import write_json
from value_lab.evidence_crate import export_crate, verify_crate

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    spec = args.study / 'package-selection.json'
    if spec.exists():
        raise ValueError('Choose a fresh synthetic study')
    write_json(spec, {'name': 'Synthetic packaging acceptance', 'license': 'https://spdx.org/licenses/CC0-1.0',
                     'files': {'suite': 'suite.json', 'lock': 'protocol.lock.json', 'records': 'runs.jsonl', 'report': 'report.json'}})
    result = export_crate(spec, args.output)
    assert verify_crate(args.output, result['metadata_sha256']) == result
    write_json(args.output.with_suffix('.acceptance.json'), result)
    print(result['metadata_sha256'])
