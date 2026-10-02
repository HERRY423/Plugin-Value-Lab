"""Decision-time evidence preserves blockers, provenance and original choices."""
from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_burden_view import example
from value_lab.core import suite_digest
from value_lab.decision_view import brief, render
from value_lab.workflow import plan_plugin_use, write_plan


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids, self.links, self.details, self.scripts, self.meta = [], [], [], [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'a':
            self.links.append(attrs.get('href', ''))
        if tag == 'details':
            self.details.append(attrs)
        if tag == 'script':
            self.scripts.append(attrs)
        if tag == 'meta':
            self.meta.append(attrs)


class DecisionViewTests(unittest.TestCase):
    def setUp(self):
        self.request = example.request('tradeoff')

    def plan(self):
        return plan_plugin_use(self.request)

    def test_brief_identifies_tradeoffs_and_preserves_failed_candidates(self):
        plan = self.plan()
        card = plan['evidence_brief']
        self.assertEqual(card['state'], 'REVIEW_TRADEOFF')
        self.assertEqual(card['original_candidate_arms'], ['A', 'B'])
        self.assertEqual(card['counts']['received'], 30)
        self.assertTrue(any(f['kind'] == 'FAILED' and 'BASELINE' in f['text'] for f in card['flags']))
        self.assertIn('合成', card['evidence_label'])
        self.assertTrue(card['snapshot_only'])
        self.assertFalse(card['selection_rule_changed'])
        self.assertTrue(any('声明费用' in h for h in card['highlights']))

    def test_missing_context_distinct_from_failed_quality(self):
        self.request = example.request('missing')
        card = self.plan()['evidence_brief']
        self.assertEqual(card['state'], 'INCOMPLETE_BURDEN')
        self.assertEqual(card['next_step']['target'], 'gaps')
        self.assertTrue(any(f['kind'] == 'FAILED' for f in card['flags']))
        self.assertTrue(any(f['kind'] == 'BURDEN_GAPS' for f in card['flags']))

    def test_missing_runs_not_called_completed(self):
        request = self.request['plugin_combination']
        request['observations']['runs'].pop()
        request.pop('burden_observations')
        card = self.plan()['evidence_brief']
        self.assertEqual(card['counts']['received'], 29)
        self.assertTrue(any(f['kind'] == 'MISSING_RUNS' for f in card['flags']))
        self.assertIn('已收到', card['summary'])
        self.assertNotIn('已完成', card['summary'])

    def test_condition_mismatch_takes_priority_over_burden(self):
        self.request['plugin_combination']['observations']['runs'][0]['exposure']['inputs'] = {}
        card = self.plan()['evidence_brief']
        self.assertEqual(card['state'], 'CHECK_RECORDS')
        self.assertEqual(card['next_step']['target'], 'conditions')

    def test_all_task_failures_never_get_ready_message(self):
        req = self.request['plugin_combination']
        req.pop('burden_observations')
        for row in req['observations']['runs']:
            row['record']['output'] = '{"source_and_identifier_checked":false}'
        card = self.plan()['evidence_brief']
        self.assertEqual(card['state'], 'NO_ELIGIBLE_CANDIDATE')
        self.assertEqual(card['original_candidate_arms'], [])

    def test_unknown_cost_never_gets_tradeoff_primary(self):
        self.request['plugin_combination']['observations']['runs'][0]['additional_cost_usd']['judge_usd'] = None
        card = self.plan()['evidence_brief']
        self.assertEqual(card['state'], 'CHECK_RECORDS')
        self.assertTrue(any(f['kind'] == 'MISSING_COST' for f in card['flags']))

    def test_planning_stage_is_not_execution(self):
        req = self.request['plugin_combination']
        self.request['plugin_combination'] = {'action': 'plan', 'spec': req['design']['spec']}
        plan = self.plan()
        self.assertEqual(plan['evidence_brief']['state'], 'AWAITING_OBSERVATIONS')
        self.assertEqual(plan['evidence_brief']['counts']['received'], 0)
        self.assertIn('计划不代表已执行', plan['evidence_brief']['summary'])
        self.assert_valid_links(render(plan['combination'], plan['task_summary']))

    def assert_valid_links(self, html):
        doc = Document(html)
        self.assertEqual(len(doc.ids), len(set(doc.ids)))
        self.assertTrue(all(href[1:] in doc.ids for href in doc.links if href.startswith('#')))
        self.assertTrue(all('open' not in d for d in doc.details))
        self.assertTrue(all('src' not in s for s in doc.scripts))
        self.assertTrue(all(not href.startswith(('http:', 'https:', 'javascript:')) for href in doc.links))
        self.assertTrue(any('default-src' in m.get('content', '') for m in doc.meta))

    def test_accessible_native_disclosure_and_offline_links(self):
        plan = self.plan()
        self.assert_valid_links(render(plan['combination'], plan['task_summary']))

    def test_submitted_text_never_becomes_html_or_script(self):
        plan = self.plan()
        poison = '<script>alert("injected")</script><img src="https://private.invalid">'
        plan['combination']['arms'][0]['reasons'].append(poison)
        html = render(plan['combination'], poison)
        self.assertNotIn(poison, html)
        self.assertIn('&lt;script&gt;', html)
        self.assertEqual(len(Document(html).scripts), 1)

    def test_render_does_not_mutate_report_or_recommendation(self):
        plan = self.plan()
        before = deepcopy(plan)
        render(plan['combination'], plan['task_summary'])
        self.assertEqual(plan, before)
        self.assertEqual(brief(plan['combination']), plan['evidence_brief'])

    def test_markdown_starts_with_relevant_evidence_and_html_is_written(self):
        plan = self.plan()
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_plan(plan, Path(tmp) / 'report')
            markdown = Path(paths['md']).read_text(encoding='utf-8')
            self.assertLess(markdown.index('此刻需要看的证据'), markdown.index('## 下一步'))
            self.assertIn('EVIDENCE.html#comparisons', markdown)
            self.assert_valid_links(Path(paths['html']).read_text(encoding='utf-8'))
            stored = json.loads(Path(paths['json']).read_text(encoding='utf-8'))
            self.assertEqual(stored['combination'], plan['combination'])
            self.assertEqual(stored['evidence_brief'], plan['evidence_brief'])

    def test_non_synthetic_still_does_not_claim_authenticated_execution(self):
        report = self.plan()['combination']
        report['evidence_status'] = 'DESCRIPTIVE_LOCAL_OBSERVATIONS'
        self.assertIn('未认证', brief(report)['evidence_label'])

    def test_equal_and_single_eligible_are_review_not_adoption(self):
        for mode in ('equal', 'dominance'):
            self.request = example.request(mode)
            card = self.plan()['evidence_brief']
            self.assertEqual(card['state'], 'REVIEW_COMPARISON')
            self.assertNotIn('采用', card['title'])


if __name__ == '__main__':
    unittest.main()
