"""Trusted action entry point; import only the pinned action checkout."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.ci_gate import main

if __name__ == '__main__':
    raise SystemExit(main())
