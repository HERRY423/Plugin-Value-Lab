#!/usr/bin/env python3
"""Portable source-tree entry point; no installation required for offline use."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
