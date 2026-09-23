"""Release acceptance: unavailable optional features cannot silently skip tests."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if result.skipped:
        print("Release rejected: skipped tests are not release acceptance", file=sys.stderr)
    return 0 if result.wasSuccessful() and result.testsRun and not result.skipped else 1

if __name__ == "__main__":
    raise SystemExit(main())
