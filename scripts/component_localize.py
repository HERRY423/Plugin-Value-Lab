"""Run frozen component replacements in the scientific OS sandbox (Linux/WSL)."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.component_localization import run_interventions

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('design', 'sha256', 'inputs', 'submitted', 'output'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--runtime')
    a = p.parse_args()
    report = run_interventions(a.design, a.sha256, a.inputs, a.submitted, a.output, runtime=a.runtime)
    print(json.dumps({k: report[k] for k in ('status', 'planned_runs', 'recorded_runs')}, ensure_ascii=True))
