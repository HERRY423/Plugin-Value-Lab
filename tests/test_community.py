"""Regression coverage for missing or inconsistent distributable metadata."""
from tests.optional import available, requires
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_community import check, REQUIRED, external_l1_gate
from distribution import inventory


@requires("jsonschema", "yaml")
@unittest.skipUnless(available("jsonschema", "yaml"), "requires: jsonschema, yaml")
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
        self.assertEqual(result['v1_release_gate']['status'], 'WAITING_EXTERNAL_L1')

    def test_formal_release_requires_external_l1_even_when_engineering_metadata_passes(self):
        with self.assertRaisesRegex(ValueError, 'Formal release blocked'):
            external_l1_gate(self.root, '1.0.0')
        with self.assertRaisesRegex(ValueError, 'Formal release blocked'):
            external_l1_gate(self.root, '1.0.1')
        self.assertEqual(external_l1_gate(self.root, '1.0.0-rc.5')['recorded_labs'], 0)

    def completion_fixture(self, outcome='STOP'):
        import hashlib
        record = {'lab_code': 'SYNTHETIC_TEST_ONLY', 'external_operator': True,
                  'lab_confirmed_complete': True, 'release_owner_accepted': True, 'export_approved': True,
                  'lab_attestation_ref': 'fixture', 'release_review_ref': 'fixture',
                  'tested_version': 'fixture-rc', 'tested_source_sha256': 'a' * 64,
                  'use_card_ref': 'fixture', 'outcome': outcome, 'task_ids': ['a', 'b', 'c'],
                  'attempts': [{'task_id': t, 'repeat': r, 'arm': a, 'status': 'failed' if t == 'c' else 'completed'}
                               for t in ['a', 'b', 'c'] for r in (0, 1) for a in ('with', 'without')]}
        def save():
            path = self.root / 'completion.json'
            path.write_text(json.dumps(record), encoding='utf-8')
            config = self.root / 'docs/feature-freeze.json'
            policy = json.loads(config.read_text(encoding='utf-8'))
            policy['v1_release_gate']['records'] = [{'completion_record': 'completion.json',
                                                   'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]
            config.write_text(json.dumps(policy), encoding='utf-8')
        save()
        return record, save

    def test_complete_negative_or_inconclusive_outcomes_count_not_only_positive(self):
        for outcome in ('STOP', 'INSUFFICIENT_EVIDENCE', 'ADVANCE_PILOT'):
            self.completion_fixture(outcome)
            result = external_l1_gate(self.root, '1.0.0')
            self.assertEqual(result['recorded_labs'], 1)
            self.assertFalse(result['external_identity_authenticated_by_script'])
            self.assertFalse(result['automatic_release'])

    def test_unaccepted_partial_duplicate_and_tampered_completion_blocked(self):
        for mutation in ('not_external', 'not_accepted', 'not_cleared', 'partial', 'duplicate', 'tampered'):
            record, save = self.completion_fixture()
            if mutation == 'not_external': record['external_operator'] = False
            if mutation == 'not_accepted': record['release_owner_accepted'] = False
            if mutation == 'not_cleared': record['export_approved'] = False
            if mutation == 'partial': record['attempts'].pop()
            if mutation == 'duplicate': record['attempts'][-1] = record['attempts'][0]
            save()
            if mutation == 'tampered': (self.root / 'completion.json').write_text('{}')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                external_l1_gate(self.root, '1.0.0')

    def test_root_alias_is_normalized_but_outside_records_stay_blocked(self):
        self.completion_fixture()
        alias = self.root / '..' / self.root.name
        self.assertEqual(external_l1_gate(alias, '1.0.0')['recorded_labs'], 1)
        with tempfile.TemporaryDirectory(dir=self.root.parent) as outside:
            outside = Path(outside)
            shutil.copyfile(self.root / 'completion.json', outside / 'completion.json')
            config = self.root / 'docs/feature-freeze.json'
            policy = json.loads(config.read_text(encoding='utf-8'))
            policy['v1_release_gate']['records'][0]['completion_record'] = '../' + outside.name + '/completion.json'
            config.write_text(json.dumps(policy), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'outside release tree'):
                external_l1_gate(alias, '1.0.0')

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

    @requires('jsonschema')
    @unittest.skipUnless(available('jsonschema'), "requires: jsonschema")
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
