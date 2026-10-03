"""Validate community metadata offline; this is not a privacy or security audit."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('CITATION.cff', 'SECURITY.md', 'CONTRIBUTING.md',
            'docs/API-STABILITY.md', 'docs/DATA-GOVERNANCE.md')


def check(root=ROOT):
    import yaml
    from jsonschema import Draft7Validator, FormatChecker

    root = Path(root).resolve()
    for name in REQUIRED:
        path = root / name
        if not path.is_file() or not path.resolve().is_relative_to(root) or not path.read_text(encoding='utf-8').strip():
            raise ValueError('Required community file missing, empty or outside root: ' + name)
    schemas = root / 'schemas/citation-file-format/1.2.0'
    sources = json.loads((schemas / 'SOURCES.json').read_text(encoding='utf-8'))
    if sorted(entry['file'] for entry in sources['files']) != ['LICENSE', 'schema.json']:
        raise ValueError('Incomplete CFF schema provenance')
    for entry in sources['files']:
        path = schemas / entry['file']
        if not path.resolve().is_relative_to(schemas) or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('CFF schema provenance checksum mismatch')
    schema = json.loads((schemas / 'schema.json').read_text(encoding='utf-8'))
    Draft7Validator.check_schema(schema)
    citation = yaml.safe_load((root / 'CITATION.cff').read_text(encoding='utf-8'))
    # YAML dates become date objects; the upstream JSON schema requires strings.
    def normalize(value):
        if isinstance(value, datetime.date):
            return value.isoformat()
        raise TypeError('Unsupported citation value')
    citation = json.loads(json.dumps(citation, default=normalize))
    Draft7Validator(schema, format_checker=FormatChecker()).validate(citation)
    manifest = json.loads((root / 'plugin.json').read_text(encoding='utf-8'))
    if citation.get('version') != manifest['version']:
        raise ValueError('Citation and plugin version drift')
    if citation.get('license') != 'Apache-2.0' or citation.get('repository-code') != 'https://github.com/HERRY423/Plugin-Value-Lab':
        raise ValueError('Citation license or repository identity drift')
    return {'status': 'PASS', 'citation_format': citation['cff-version'],
            'source_version': citation['version'], 'required_files': list(REQUIRED),
            'schemas_loaded_offline': True, 'privacy_enforcement_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', default=str(ROOT))
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.root), indent=2))
    except Exception as exc:
        print(f'Community metadata validation failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
