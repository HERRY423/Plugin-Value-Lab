"""Explicit online provisioning of a NEW curated Linux runtime; never used by replay.

Dependency resolution is recorded by pip; freeze-runtime must subsequently hash
the installed bytes. This is local provisioning, not an external rebuild claim.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    p.add_argument('--minimal', action='store_true', help='Only packaging for standard-library execution calibration')
    args = p.parse_args()
    if sys.platform != 'linux' or not Path(sys.executable).resolve().is_relative_to('/usr'):
        p.error('Use the Linux system Python under /usr so its standard library is mounted')
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / 'bin').mkdir()
    shutil.copyfile(sys.executable, root / 'bin/python')
    (root / 'bin/python').chmod(0o755)
    version = f'{sys.version_info.major}.{sys.version_info.minor}'
    (root / 'pyvenv.cfg').write_text(f'home = {Path(sys.executable).parent}\ninclude-system-site-packages = false\n')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-compile', '--report', str(root / 'install-report.json'),
                    '--target', str(root / f'lib/python{version}/site-packages'),
                    *(['packaging'] if args.minimal else ['packaging', 'pydeseq2==0.5.4'])], check=True)


if __name__ == '__main__':
    main()
