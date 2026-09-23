"""Manufactured subprocess fixture. Does not load Claude or call any model."""
import json
from pathlib import Path
import sys
import time

args = sys.argv[1:]
plugin = Path(args[args.index("eval") + 1])
mode = (plugin / "fixture-mode.txt").read_text() if (plugin / "fixture-mode.txt").exists() else "normal"
print("SYNTHETIC SUBPROCESS FIXTURE: no model calls", flush=True)
if mode == "sleep":
    time.sleep(30)
if mode == "failure":
    print("Manufactured authentication failure", file=sys.stderr)
    sys.exit(3)
output = Path(args[args.index("--json") + 1])
if mode == "malformed":
    output.write_text("{invalid", encoding="utf-8")
    sys.exit(0)
runs = int(args[args.index("--runs") + 1])
cases = []
for directory in sorted((plugin / "value-lab-evals").iterdir()):
    cases.append({"name": directory.name, "aggregates": {"score": 1, "delta": 0.5},
                  "arms": {arm: [{"error": None, "fixture_only": True} for _ in range(runs)] for arm in ("with", "without")}})
result = {"schemaVersion": 1, "claudeVersion": "2.1.278", "partial": mode == "partial", "costUsd": 0.03,
          "durationSeconds": 0.1, "aggregates": {"overallScore": 1, "meanDelta": 0.5}, "cases": cases}
if mode == "partial":
    result.update(partialReason="cost_ceiling")
    result["cases"] = result["cases"][:1]
output.write_text(json.dumps(result), encoding="utf-8")
sys.exit(1 if mode == "partial" else 0)
