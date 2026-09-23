"""Interface example only: checks a JSON object, not scientific correctness."""
import json
from pathlib import Path
import sys

try:
    value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    passed = isinstance(value, dict) and bool(value)
    print(json.dumps({"passed": passed, "rationale": "Artifact must contain a nonempty JSON object"}))
except (OSError, ValueError) as exc:
    print(json.dumps({"passed": False, "rationale": "Invalid JSON artifact: " + str(exc)}))
