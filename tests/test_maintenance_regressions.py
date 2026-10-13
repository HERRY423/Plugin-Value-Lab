"""Rendering and prospective family-count guard regressions; synthetic fixtures."""
from tests.optional import available, requires
import copy
import unittest

from value_lab.markdown_text import literal, key_value_table
from value_lab.core import demo_suite, demo_records, evaluate, suite_digest
from value_lab.value_metrics import family_requirement, positive_signal
from value_lab.usage import build_usage_card, _render_markdown


class RenderingTests(unittest.TestCase):
    def test_structure_is_table_with_literal_scalars(self):
        text = key_value_table({'host': "O'Reilly & <local>", 'counts': {'zero': 0, 'missing': None},
                                'list': [False, 'a|b\n# heading'], 'empty': []})
        self.assertIn('| 字段 | 值 |', text)
        self.assertIn("O'Reilly", text)
        self.assertNotIn('&#', text)
        self.assertNotIn('&lt;', text)
        self.assertIn(r'\<local\>', text)
        self.assertIn('| counts / zero | 0 |', text)
        self.assertIn('| counts / missing | 未知 |', text)
        self.assertNotIn('\n# heading', text)
        self.assertIn(r'a\|b', text)

    @requires('markdown_it')
    @unittest.skipUnless(available('markdown_it'), 'requires: markdown_it')
    def test_actual_markdown_renderer_cannot_activate_evidence(self):
        from markdown_it import MarkdownIt
        attack = '<img src=x onerror="alert(1)">![remote](https://invalid.example/pixel) &lt;script&gt;'
        rendered = MarkdownIt('commonmark').enable('table').render(key_value_table({'host': attack}))
        self.assertIn('<table>', rendered)
        self.assertIn('&lt;img', rendered)
        for active in ('<img', '<script', '<a '):
            self.assertNotIn(active, rendered)

    def test_card_renders_structured_fields_without_json_entities(self):
        suite = demo_suite()
        card = build_usage_card(suite, demo_records(suite), {'suite_sha256': suite_digest(suite)})
        before = copy.deepcopy(card)
        card['scope']['conditions']['note'] = '"quoted" & plain'
        text = _render_markdown(card)
        self.assertIn('| note | "quoted" \\& plain |', text)
        self.assertGreaterEqual(text.count('| 字段 | 值 |'), 3)
        self.assertEqual(card['source'], before['source'])


class FamilyGateTests(unittest.TestCase):
    @staticmethod
    def book():
        return {'schema_version': 1, 'entries': [],
                'coverage': {k: 'included' for k in ('judge', 'setup', 'retry', 'other')}}

    def fixture(self):
        suite = demo_suite()
        suite['evidence_type'] = 'local'
        suite['policy']['power_plan'] = {'expected_family_sd': .2, 'minimum_detectable_delta': .1,
                                         'alpha': .05, 'power': .8}
        suite['policy']['min_clusters'] = 2
        records = demo_records(suite)
        for row in records:
            row['source'] = 'manual'
            row['synthetic'] = False
            if row['arm'] == 'with':
                case = next(c for c in suite['cases'] if c['id'] == row['case_id'])
                row['output'] = {'structured-delivery': 'SOURCE: example LIMITS: simulated', 'no-network': 'NO_NETWORK', 'unknown-evidence': 'NOT_ESTABLISHED'}.get(case['id'], row['output'])
        for row in records:
            row['suite_sha256'] = suite_digest(suite)
        return suite, records

    def test_default_uses_plan_and_explicit_low_floor_cannot_bypass_it(self):
        suite, _ = self.fixture()
        self.assertEqual(family_requirement(suite)['effective_min_clusters'], 32)
        del suite['policy']['min_clusters']
        self.assertEqual(family_requirement(suite)['effective_min_clusters'], 32)
        self.assertFalse(family_requirement(suite)['target_met'])

    def test_underpowered_result_cannot_be_positive_guidance(self):
        suite, records = self.fixture()
        report = evaluate(suite, records, {'suite_sha256': suite_digest(suite)}, self.book())
        self.assertFalse(positive_signal(report))
        self.assertEqual(report['verdict'], 'TRIAL_ONLY_SIGNAL')
        self.assertFalse(report['value_metrics']['benefit_claim_eligible'])
        card = build_usage_card(suite, records, {'suite_sha256': suite_digest(suite)}, self.book())
        self.assertEqual(card['use_when'], [])

    def test_repeats_do_not_supply_families_and_bad_evidence_stays_stricter(self):
        suite, records = self.fixture()
        before = family_requirement(suite)
        suite['runs_per_case'] = 5
        self.assertEqual(family_requirement(suite)['required_families'], before['required_families'])
        report = evaluate(suite, records, {'suite_sha256': suite_digest(suite)}, self.book())
        self.assertEqual(report['verdict'], 'INSUFFICIENT_EVIDENCE')

    def test_meeting_the_frozen_plan_removes_only_the_family_ceiling(self):
        suite, records = self.fixture()
        suite['policy']['power_plan']['expected_family_sd'] = .02
        for row in records:
            row['suite_sha256'] = suite_digest(suite)
        report = evaluate(suite, records, {'suite_sha256': suite_digest(suite)}, self.book())
        self.assertTrue(report['family_requirement']['target_met'])
        self.assertEqual(report['verdict'], 'PROMISING_LOCAL_SIGNAL')
        self.assertTrue(positive_signal(report))
