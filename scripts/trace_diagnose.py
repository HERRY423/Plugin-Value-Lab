"""Produce a versioned lineage view of a verified native sidecar."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.trace_diagnostics import diagnose_retained

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--receipt-sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(diagnose_retained(args.evidence, args.receipt_sha256, args.output), ensure_ascii=True))
