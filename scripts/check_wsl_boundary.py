"""Explicit Windows -> existing WSL Linux isolation acceptance, no paid calls.

This is an alternative Linux evidence path, never automatic fallback from a
Windows study. Re-freeze runtime/platform conditions before collecting a study.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distribution', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Run this wrapper on Windows; use check_kernel_acceptance.py on Linux')
    if not args.distribution or args.distribution.startswith('-'):
        parser.error('Select an existing WSL distribution by name')
    output = Path(args.output).resolve()
    if output.exists():
        parser.error('Output already exists; retain prior acceptance evidence')
    script = Path(__file__).resolve().with_name('check_kernel_acceptance.py')
    wsl = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/wsl.exe')
    prefix = [wsl, '--distribution', args.distribution, '--exec']
    def translate(path):
        result = subprocess.run([*prefix, '/usr/bin/wslpath', '-a', str(path)],
                                capture_output=True, timeout=20, check=True)
        return result.stdout.decode('utf-8').strip()
    linux_script, linux_output = translate(script), translate(output)
    result = subprocess.run([*prefix, '/usr/bin/python3', '-S', linux_script, '--output', linux_output],
                            timeout=300, check=False)
    receipt_path = output / 'acceptance.json'
    # The underlying checker is authoritative; exit zero is not enough.
    if not receipt_path.is_file():
        raise SystemExit('WSL acceptance receipt missing; inspect output; no fallback')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if result.returncode or receipt.get('status') != 'PASS':
        raise SystemExit('WSL kernel acceptance failed; no fallback')
    print(json.dumps({'status': 'PASS', 'execution_platform': 'linux-wsl2',
                      'native_windows_verified': False, 'real_model_calls': 0,
                      'receipt': str(receipt_path)}))


if __name__ == '__main__':
    main()
