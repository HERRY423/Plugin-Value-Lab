"""Offline packet-integrity check, not a signature or privacy approval."""
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / 'PACKAGE-MANIFEST.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise SystemExit('PACKAGE_CHECK_FAILED: missing or unsafe member')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit('PACKAGE_CHECK_FAILED: ' + name)
    print('PACKAGE_CHECK_PASS: ' + manifest['packet_id'])
    print('Integrity only; no institutional approval or author identity is authenticated.')


if __name__ == '__main__':
    main()
