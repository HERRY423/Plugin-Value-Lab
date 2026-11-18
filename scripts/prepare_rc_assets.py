"""Package the first-lab kit and verify a release candidate entirely offline."""
import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
KIT = Path('examples/first-lab-l1')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(obj):
    return (json.dumps(obj, indent=2, ensure_ascii=False) + '\n').encode()


def tracked_files(directory):
    names = subprocess.check_output(['git', 'ls-files', '-z', '--', directory], cwd=ROOT)
    result = {}
    for name in names.decode().split('\0')[:-1]:
        path = ROOT / name
        if path.resolve() != path or not path.is_file():
            raise ValueError(f'Expected a regular tracked file: {name}')
        result[name] = path.read_bytes()
    if not result:
        raise ValueError(f'Missing tracked files: {directory}')
    return result


def verify_distributions(dist, wheel, sdist, version, runtime):
    with zipfile.ZipFile(dist / wheel) as archive:
        metadata = BytesParser().parsebytes(archive.read(f'plugin_value_lab-{version}.dist-info/METADATA'))
        if metadata['Name'] != 'plugin-value-lab' or metadata['Version'] != version:
            raise ValueError('Wheel metadata version/name mismatch')
        observed = {name: archive.read(name) for name in archive.namelist() if name.startswith('value_lab/')}
        if archive.testzip() is not None or observed != runtime:
            raise ValueError('Wheel runtime differs from the checkout')
    with tarfile.open(dist / sdist, 'r:gz') as archive:
        prefix = f'plugin_value_lab-{version}/'
        for name, expected in {**runtime, 'pyproject.toml': (ROOT / 'pyproject.toml').read_bytes()}.items():
            member = archive.getmember(prefix + name)
            if not member.isfile() or archive.extractfile(member).read() != expected:
                raise ValueError(f'Source distribution differs from the checkout: {name}')


def verify_plugin_zip(path, prefix):
    with zipfile.ZipFile(path) as archive:
        sums = json.loads(archive.read(prefix + '/SHA256SUMS.json'))
        members = {prefix + '/' + name for name in sums} | {prefix + '/SHA256SUMS.json'}
        if sorted(archive.namelist()) != sorted(members):
            raise ValueError(f'Plugin ZIP member inventory mismatch: {path.name}')
        for name, expected in sums.items():
            if sha(archive.read(prefix + '/' + name)) != expected:
                raise ValueError(f'Plugin ZIP member checksum mismatch: {path.name}/{name}')
        plugin_path = ('plugins/plugin-value-lab/' if prefix.endswith('-marketplace') else '') + 'plugin.json'
        if archive.read(prefix + '/' + plugin_path) != (ROOT / 'plugin.json').read_bytes():
            raise ValueError(f'Plugin ZIP manifest differs from the checkout: {path.name}')


def rehearse(packet, work, wheel):
    env_dir = work / 'venv'
    env = dict(os.environ, PIP_NO_INDEX='1', PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK='1')
    def run(args):
        subprocess.run(args, cwd=packet, env=env, check=True)
    run([sys.executable, '-I', 'check_package.py'])
    run([sys.executable, '-I', '-m', 'venv', str(env_dir)])
    python = env_dir / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    run([str(python), '-I', '-m', 'pip', '--isolated', 'install', '--no-index', '--no-deps',
         str(packet / 'wheels' / wheel)])
    run([str(python), '-I', 'rehearsal.py', '--output', str(work / 'rehearsal')])
    result = json.loads((work / 'rehearsal/walkthrough.json').read_bytes())
    if result['status'] != 'REHEARSAL_PASS' or result['source_tree_import'] or result['model_calls'] != 0:
        raise ValueError('Installed wheel offline rehearsal failed')
    return result


def prepare(dist, tag, test_report):
    plugin = json.loads((ROOT / 'plugin.json').read_bytes())['version']
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    if (not re.fullmatch(r'\d+\.\d+\.\d+-rc\d+', plugin) or tag != 'v' + plugin
            or version != plugin.replace('-rc', 'rc')):
        raise ValueError('Expected a candidate tag matching plugin.json and pyproject.toml')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    ref = subprocess.run(['git', 'rev-parse', '--verify', '--quiet', f'refs/tags/{tag}^{{commit}}'],
                         cwd=ROOT, capture_output=True, text=True)
    if ref.returncode not in (0, 1) or (ref.returncode == 0 and ref.stdout.strip() != head):
        raise ValueError('Release tag resolution failed or tag does not match HEAD')
    report_bytes = test_report.read_bytes()
    tests = json.loads(report_bytes)
    if (tests.get('tier') != 'full' or tests.get('requires_all') is not True
            or type(tests.get('tests')) is not int or tests['tests'] <= 0
            or any(tests.get(k) != [] for k in ('failures', 'errors', 'skipped'))):
        raise ValueError('Expected a passing full --require-all test report')
    wheel = f'plugin_value_lab-{version}-py3-none-any.whl'
    sdist = f'plugin_value_lab-{version}.tar.gz'
    market = f'plugin-value-lab-marketplace-{plugin}.zip'
    portable = f'plugin-value-lab-agent-plugins-{plugin}.zip'
    packet_id = f'PVL-first-lab-L1-{tag}'
    kit_zip = packet_id + '.zip'
    input_names = {wheel, sdist, market, portable}
    outputs = {kit_zip, 'release-verification.json', 'SHA256SUMS.txt'}
    members = {p.name for p in dist.iterdir()}
    if not input_names <= members or members - input_names - outputs:
        raise ValueError('Expected exactly the versioned wheel, sdist and two plugin ZIPs in dist')
    if any(p.is_symlink() or not p.is_file() for p in dist.iterdir()):
        raise ValueError('Release assets must be regular files')

    runtime = tracked_files('value_lab')
    verify_distributions(dist, wheel, sdist, version, runtime)
    verify_plugin_zip(dist / market, 'plugin-value-lab-marketplace')
    verify_plugin_zip(dist / portable, 'plugin-value-lab')
    files = {Path(name).relative_to(KIT).as_posix(): data for name, data in tracked_files(KIT).items()}
    if kit_zip.encode() not in files['README.md'] or f'plugin-value-lab=={version}\n' not in files['README.md'].decode().replace('\r\n', '\n'):
        raise ValueError('First-lab README does not identify the candidate ZIP and offline wheel pin')
    files['wheels/' + wheel] = (dist / wheel).read_bytes()
    runtime_sums = {name: sha(data) for name, data in sorted(runtime.items())}
    manifest = {'packet_id': packet_id, 'commit': head, 'wheel_version': version, 'wheel_sha256': sha(files['wheels/' + wheel]),
                'runtime_sha256': sha(encode(runtime_sums)), 'runtime_files': runtime_sums,
                'files': {name: sha(data) for name, data in sorted(files.items())}}
    files['PACKAGE-MANIFEST.json'] = encode(manifest)
    with tempfile.TemporaryDirectory(prefix='pvl-first-lab-') as temporary:
        work = Path(temporary)
        with zipfile.ZipFile(work / kit_zip, 'x') as archive:
            for name, data in sorted(files.items()):
                archive.writestr(zipfile.ZipInfo(name), data, compress_type=zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(work / kit_zip) as archive:
            if archive.testzip() or {name: archive.read(name) for name in archive.namelist()} != files:
                raise ValueError('First-lab ZIP verification failed')
            archive.extractall(work / 'packet')
        rehearsal = rehearse(work / 'packet', work, wheel)
        sums = {name: sha((dist / name).read_bytes()) for name in sorted(input_names)}
        sums[kit_zip] = sha((work / kit_zip).read_bytes())
        receipt = {'tag': tag, 'commit': head, 'local_tag_verified_at_head': ref.returncode == 0,
                   'full_test_report': tests, 'full_test_report_sha256': sha(report_bytes),
                   'asset_sha256': sums, 'wheel_runtime_matches_checkout': True,
                   'installed_wheel_rehearsal': rehearsal}
        (work / 'release-verification.json').write_bytes(encode(receipt))
        sums['release-verification.json'] = sha((work / 'release-verification.json').read_bytes())
        (work / 'SHA256SUMS.txt').write_bytes(''.join(f'{sums[n]}  {n}\n' for n in sorted(sums)).encode())
        for name in outputs & members:
            if (work / name).read_bytes() != (dist / name).read_bytes():
                raise ValueError(f'Existing generated asset differs; use a clean build directory: {name}')
        for name in sorted(outputs - members):
            # Stage the copy on the destination filesystem before exposing the finished artifact.
            with tempfile.NamedTemporaryFile(dir=dist, delete=False) as staging:
                staging.write((work / name).read_bytes())
            Path(staging.name).replace(dist / name)
    print(f'RC_ASSETS_VERIFIED {tag} {head}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--test-report', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.dist.resolve(), args.tag, args.test_report)
