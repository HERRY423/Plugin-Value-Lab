"""Regression coverage for missing or inconsistent distributable metadata."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_community import check, REQUIRED
from distribution import inventory


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in (*REQUIRED, 'plugin.json'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, p)
        shutil.copytree(ROOT / 'schemas/citation-file-format', self.root / 'schemas/citation-file-format')

    def test_official_schema_and_identity_validate_offline(self):
        result = check(self.root)
        self.assertEqual(result['status'], 'PASS')
        self.assertTrue(result['schemas_loaded_offline'])
        self.assertFalse(result['privacy_enforcement_verified'])

    def test_citation_version_drift_rejected(self):
        p = self.root / 'CITATION.cff'
        text = p.read_text(encoding='utf-8')
        version = json.loads((self.root / 'plugin.json').read_text(encoding='utf-8'))['version']
        p.write_text(text.replace('version: ' + version, 'version: 99.0.0'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'version drift'):
            check(self.root)

    def test_missing_community_files_rejected(self):
        for name in REQUIRED:
            with self.subTest(name=name):
                p = self.root / name
                original = p.read_bytes()
                p.unlink()
                with self.assertRaisesRegex(ValueError, 'Required community file'):
                    check(self.root)
                p.write_bytes(original)

    def test_invalid_cff_field_rejected_by_upstream_schema(self):
        from jsonschema import ValidationError
        p = self.root / 'CITATION.cff'
        with p.open('a', encoding='utf-8') as f:
            f.write('\nunknown-citation-field: invalid\n')
        with self.assertRaises(ValidationError):
            check(self.root)

    def test_vendored_schema_tampering_rejected(self):
        p = self.root / 'schemas/citation-file-format/1.2.0/schema.json'
        p.write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            check(self.root)

    def test_community_files_ship_in_both_plugin_inventories(self):
        for portable in (False, True):
            with self.subTest(portable=portable):
                files = inventory(portable=portable)
                for name in REQUIRED:
                    self.assertEqual(files[name], (ROOT / name).read_bytes())


if __name__ == '__main__':
    unittest.main()
