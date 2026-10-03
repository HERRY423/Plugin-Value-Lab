"""Clean-checkout and artifact integrity checks for single-source packaging."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_marketplace import sync, marketplace_inventory, archive, NAME, MARKET
from distribution import inventory


class MarketplaceBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'source'
        for name, data in inventory().items():
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        for name in ('.agents/plugins/marketplace.json', '.claude-plugin/marketplace.json'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((ROOT / name).read_bytes())

    def test_clean_checkout_checks_without_generating_or_needing_a_mirror(self):
        payload = sync(self.root, check=True)
        self.assertIn('docs/METHODOLOGY.md', payload)
        self.assertFalse((self.root / 'plugins').exists())
        self.assertFalse((self.root / 'build').exists())
        codex = json.loads((self.root / '.agents/plugins/marketplace.json').read_bytes())
        claude = json.loads((self.root / '.claude-plugin/marketplace.json').read_bytes())
        self.assertEqual(codex['plugins'][0]['source']['path'], './')
        self.assertEqual(claude['plugins'][0]['source'], './')

    def test_generated_docs_and_evidence_are_exact_and_source_catalog_unchanged(self):
        before = (self.root / '.agents/plugins/marketplace.json').read_bytes()
        payload = sync(self.root)
        build = self.root / 'build/marketplace'
        for name, data in payload.items():
            self.assertEqual((build / 'plugins' / NAME / name).read_bytes(), data)
        self.assertEqual((self.root / '.agents/plugins/marketplace.json').read_bytes(), before)
        self.assertEqual(json.loads((build / '.agents/plugins/marketplace.json').read_bytes())['plugins'][0]['source']['path'], './plugins/' + NAME)
        self.assertEqual(sync(self.root, check=True), payload)

    def test_changed_source_requires_rebuild_and_removed_source_does_not_linger(self):
        sync(self.root)
        source = self.root / 'docs/METHODOLOGY.md'
        source.write_text(source.read_text(encoding='utf-8') + '\nNew revision\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'stale'): sync(self.root, check=True)
        sync(self.root)
        obsolete = self.root / 'docs/evidence/build-only-fixture.json'
        obsolete.write_text('{}', encoding='utf-8')
        sync(self.root)
        obsolete.unlink()
        sync(self.root)
        self.assertFalse((self.root / 'build/marketplace/plugins' / NAME / 'docs/evidence/build-only-fixture.json').exists())

    def test_unknown_and_modified_obsolete_files_are_preserved(self):
        extra = self.root / 'docs/evidence/old.json'; extra.write_text('{}', encoding='utf-8')
        sync(self.root)
        built = self.root / 'build/marketplace/plugins' / NAME
        extra.unlink()
        (built / 'docs/evidence/old.json').write_text('keep me', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Modified obsolete'): sync(self.root)
        self.assertEqual((built / 'docs/evidence/old.json').read_text(), 'keep me')
        (built / 'unknown.txt').write_text('private', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Unmanaged'): sync(self.root)

    def test_archives_resolve_catalog_and_contain_one_copy_of_each_evidence_file(self):
        payload = sync(self.root)
        expected = marketplace_inventory(self.root, payload)
        notes = expected['INSTALL.zh-CN.md'].decode('utf-8')
        self.assertIn(json.loads(payload['plugin.json'])['version'], notes)
        self.assertIn(f'plugins/{NAME}/docs/METHODOLOGY.md', notes)
        self.assertNotIn('0.6.0.zip', notes)
        output = Path(self.tmp.name) / 'market.zip'
        result = archive(output, MARKET, expected)
        self.assertTrue(result['member_hashes_verified'])
        with zipfile.ZipFile(output) as z:
            catalog = json.loads(z.read(f'{MARKET}/.agents/plugins/marketplace.json'))
            plugin_root = f"{MARKET}/" + catalog['plugins'][0]['source']['path'].removeprefix('./')
            self.assertIn(plugin_root + '/plugin.json', z.namelist())
            for name, data in payload.items():
                if name.startswith(('docs/', 'skills/')):
                    members = [n for n in z.namelist() if n.endswith('/' + name)]
                    self.assertEqual(members, [plugin_root + '/' + name])
                    self.assertEqual(z.read(members[0]), data)
            self.assertFalse(any('/work/' in n or '/build/' in n for n in z.namelist()))


if __name__ == '__main__':
    unittest.main()
