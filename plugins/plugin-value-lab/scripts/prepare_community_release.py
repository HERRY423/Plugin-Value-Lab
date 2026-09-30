"""Prepare a hash-pinned Bioconda recipe from an actual sdist; never publish."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile
import tomllib


def prepare(sdist, output):
    sdist = Path(sdist)
    with tarfile.open(sdist, 'r:gz') as archive:
        candidates = [m for m in archive.getmembers() if m.name.count('/') == 1 and m.name.endswith('/pyproject.toml')]
        if len(candidates) != 1 or not candidates[0].isfile() or candidates[0].size > 1048576:
            raise ValueError('Expected one bounded pyproject.toml in the source distribution')
        project = tomllib.loads(archive.extractfile(candidates[0]).read().decode('utf-8'))['project']
    if project['name'] != 'plugin-value-lab':
        raise ValueError('Wrong package')
    version = project['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Community recipe requires a reviewed stable version')
    with sdist.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    url = f'https://pypi.org/packages/source/p/plugin-value-lab/plugin_value_lab-{version}.tar.gz'
    recipe = f'''package:
  name: plugin-value-lab
  version: {version}
source:
  url: {url}
  sha256: {digest}
build:
  number: 0
  noarch: python
  script: "{{{{ PYTHON }}}} -m pip install . --no-deps --no-build-isolation -vv"
  entry_points:
    - pvl = value_lab.easy_cli:main
    - plugin-value-lab = value_lab.cli:main
requirements:
  host:
    - python >=3.11
    - pip
    - setuptools >=68
  run:
    - python >=3.11
    - anndata >=0.10,<0.14
    - scipy >=1.11,<2
    - h5py >=3.10,<4
    - numpy >=1.26,<3
test:
  imports:
    - value_lab.sdk
  commands:
    - pvl --version
    - pvl demo --output smoke-result --json
    - pvl verify smoke-result --json
about:
  home: https://github.com/HERRY423/Plugin-Value-Lab
  license: Apache-2.0
  license_file: LICENSE
  summary: Evidence-bounded scientific checks and donor-paired raw count aggregation
extra:
  recipe-maintainers:
    - HERRY423
'''
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    (root / 'meta.yaml').write_text(recipe, encoding='utf-8')
    receipt = {'version': version, 'sdist_sha256': digest, 'source_url': url,
               'status': 'PREPARED_NOT_PUBLISHED', 'bioconda_build': 'NOT_RUN',
               'pypi_uploaded': False, 'bioconda_accepted': False}
    (root / 'preparation.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sdist', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    print(json.dumps(prepare(args.sdist, args.output)))
