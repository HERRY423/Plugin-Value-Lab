"""Manufactured stopwatch/review inputs exercise accounting, not user benefit."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import contextlib
import io

from tests.test_author_pilot import observe


class BurdenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'observations').mkdir()
        self.plan = {'format': 'pvl-author-burden-plan-1', 'status': 'FROZEN', 'study_id': 'manufactured',
            'baseline': 'Same agent, tools, script and budget without PVL', 'pairing_rationale': 'Matched teaching tasks',
            'quality_rule': 'Both deliverables reviewed against the same requirement',
            'allocation_rationale': 'Equal allocation of reusable setup', 'hourly_usd': 60, 'shared_with_fraction': .5,
            'pairs': [{'id': 'p1', 'participant': 'manufactured', 'problems': {'with_pvl': 'a', 'without_pvl': 'b'},
                       'order': ['with_pvl', 'without_pvl'], 'max_attempts': 3, 'active_limit_seconds': 600, 'cash_limit_usd': 5}]}
        self.planref = self.save('burden-plan.json', self.plan)
        self.proof = self.save('review-evidence.json', {'scope': 'Manufactured unit-test assertions, not human review'})
        self.ledger = {'format': 'pvl-author-burden-ledger-1', 'plan_sha256': self.planref['sha256'],
            'coverage': {'/'.join(('p1', a, c)): 'not_applicable' for a in (*observe.ARMS, 'shared')
                         for c in ('pre_journal', 'post_journal_review', 'cash')}, 'entries': []}
        self.reviews = {'format': 'pvl-author-burden-reviews-1', 'plan_sha256': self.planref['sha256'], 'entries': []}
        self.journal('with_pvl', 100, 20)
        self.journal('without_pvl', 140, 21)
        self.labor('with_pvl', 'pre_journal', 60)
        self.labor('without_pvl', 'pre_journal', 10)
        self.labor('shared', 'pre_journal', 40)
        self.labor('with_pvl', 'post_journal_review', 40)
        self.labor('without_pvl', 'post_journal_review', 10)
        self.cash('with_pvl', 1)
        self.cash('without_pvl', .5)

    def save(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, allow_nan=False) + '\n', encoding='utf-8')
        return {'path': name, 'sha256': observe.evidence(path)['sha256']}

    def journal(self, arm, seconds, hour, outcome='completed'):
        name = arm + '-' + str(hour) + '.jsonl'
        events = [{'event': 'start', 'elapsed_seconds': 0, 'at': f'2026-09-28T{hour:02d}:00:00Z', 'session': {
            'participant': 'manufactured', 'arm': arm, 'problem_id': 'a' if arm == 'with_pvl' else 'b',
            'task_pair': 'p1', 'order': 1 if arm == 'with_pvl' else 2, 'previous_exposure': 'unit-test only',
            'maintainer_or_ai': True, 'preparation_plan': 'plan.md', 'burden_plan_evidence': self.planref}},
            {'event': 'end', 'elapsed_seconds': seconds, 'outcome': outcome}]
        path = self.root / 'observations' / name
        path.write_text('\n'.join(json.dumps(e) for e in events) + '\n', encoding='utf-8')
        self.reviews['entries'].append({'journal_sha256': observe.evidence(path)['sha256'], 'reviewer': 'fixture-only',
            'decision': 'usable' if outcome == 'completed' else 'unusable', 'false_alarms': 0, 'confirmed_defects': 0, 'evidence': self.proof})
        return path

    def labor(self, arm, category, seconds):
        index = len(self.ledger['entries'])
        start = datetime(2026, 9, 28, 1, index, tzinfo=timezone.utc)
        row = {'id': 'labor' + str(index), 'pair_id': 'p1', 'arm': arm, 'category': category,
            'intervals': [{'actor': 'reviewer', 'start': start.isoformat(), 'end': (start + timedelta(seconds=seconds)).isoformat()}],
            'evidence': self.proof, 'evidence_line': 'timer-' + str(index)}
        self.ledger['entries'].append(row)
        self.ledger['coverage']['/'.join(('p1', arm, category))] = 'itemized'

    def cash(self, arm, amount):
        row = {'id': 'cash-' + arm, 'pair_id': 'p1', 'arm': arm, 'category': 'cash',
            'amount_usd': amount, 'basis': 'estimate', 'evidence': self.proof, 'evidence_line': 'cash-' + arm}
        self.ledger['entries'].append(row)
        self.ledger['coverage']['p1/' + arm + '/cash'] = 'itemized'

    def report(self):
        self.save('burden-ledger.json', self.ledger)
        self.save('burden-reviews.json', self.reviews)
        return observe.summarize_folder(self.root)['burden_comparison']

    def blocked(self, result):
        self.assertIsNone(result['mean_active_seconds_saved'])
        self.assertIsNone(result['mean_total_usd_saved'])
        self.assertTrue(result['blockers'], result)

    def test_faster_journal_can_mean_greater_full_burden(self):
        result = self.report()
        self.assertFalse(result['blockers'], result)
        self.assertEqual(result['status'], 'MAINTAINER_OR_SIMULATION_ONLY')
        a, b = (result['pairs'][0]['arms'][x] for x in observe.ARMS)
        self.assertEqual((a['full_active_seconds'], b['full_active_seconds']), (220, 180))
        self.assertEqual(result['mean_active_seconds_saved'], -40)
        self.assertAlmostEqual(result['mean_total_usd_saved'], -40 / 60 - .5)
        self.assertEqual(result['cash_basis'], 'ESTIMATED_OR_INCOMPLETE')
        self.assertEqual(result['pvl_benefit'], 'NOT_ESTABLISHED')

    def test_failed_attempt_cost_is_retained_before_success(self):
        self.journal('with_pvl', 30, 19, 'abandoned')
        result = self.report()
        self.assertFalse(result['blockers'], result)
        a = result['pairs'][0]['arms']['with_pvl']
        self.assertEqual(a['attempts'], 2)
        self.assertIn('abandoned', a['outcomes'])
        self.assertEqual(result['mean_active_seconds_saved'], -70)

    def test_fast_unusable_arm_cannot_claim_savings(self):
        self.reviews['entries'][0]['decision'] = 'unusable'
        result = self.report()
        self.assertIsNone(result['mean_active_seconds_saved'])
        self.assertIsNone(result['pairs'][0]['active_seconds_saved'])

    def test_missing_or_unknown_review_blocks_comparison(self):
        original = deepcopy(self.reviews)
        for field, value in (('decision', 'unknown'), ('false_alarms', None), ('confirmed_defects', None)):
            self.reviews = deepcopy(original)
            self.reviews['entries'][0][field] = value
            self.blocked(self.report())
        self.reviews['entries'] = []
        self.blocked(self.report())

    def test_unknown_cash_is_not_zero(self):
        self.ledger['entries'][-1]['amount_usd'] = None
        result = self.report()
        self.blocked(result)
        self.assertIsNone(result['pairs'][0]['arms']['without_pvl']['cash_usd'])

    def test_uncovered_preparation_blocks_comparison(self):
        self.ledger['coverage']['p1/shared/post_journal_review'] = 'unknown'
        self.blocked(self.report())

    def test_duplicate_evidence_lines_and_overlapping_timers_are_rejected(self):
        original = deepcopy(self.ledger)
        self.ledger['entries'][1]['evidence_line'] = self.ledger['entries'][0]['evidence_line']
        self.blocked(self.report())
        self.ledger = original
        self.ledger['entries'][1]['intervals'] = deepcopy(self.ledger['entries'][0]['intervals'])
        self.blocked(self.report())

    def test_changed_frozen_plan_does_not_relabel_old_journals(self):
        self.plan['hourly_usd'] = 120
        self.save('burden-plan.json', self.plan)
        self.blocked(self.report())

    def test_missing_or_tampered_source_blocks_comparison(self):
        (self.root / self.proof['path']).write_text('changed', encoding='utf-8')
        self.blocked(self.report())

    def test_duplicate_journal_is_not_another_observation(self):
        source = next((self.root / 'observations').glob('*.jsonl'))
        (self.root / 'observations/duplicate.jsonl').write_bytes(source.read_bytes())
        self.blocked(self.report())

    def test_interrupted_tail_and_invalid_logs_are_retained(self):
        self.journal('with_pvl', 10, 18)
        path = self.root / 'observations/with_pvl-18.jsonl'
        path.write_text(path.read_text(encoding='utf-8').splitlines()[0] + '\n', encoding='utf-8')
        self.blocked(self.report())
        (self.root / 'observations/invalid.jsonl').write_text('{', encoding='utf-8')
        report = observe.summarize_folder(self.root)
        self.assertEqual(report['attempts'], 4)
        self.assertEqual(len(report['invalid_journals']), 1)

    def test_unplanned_and_out_of_sequence_attempts_block_comparison(self):
        self.journal('with_pvl', 10, 22)
        self.blocked(self.report())

    def test_planned_limits_are_not_silently_relaxed(self):
        self.plan['pairs'][0]['max_attempts'] = 1
        self.planref = self.save('burden-plan.json', self.plan)
        self.ledger['plan_sha256'] = self.reviews['plan_sha256'] = self.planref['sha256']
        self.reviews['entries'] = []
        self.journal('with_pvl', 100, 20)
        self.journal('without_pvl', 140, 21)
        self.journal('with_pvl', 30, 19, 'blocked')
        self.blocked(self.report())

    def test_empty_draft_never_invents_participants(self):
        self.plan['status'] = 'DRAFT'
        self.save('burden-plan.json', self.plan)
        result = self.report()
        self.assertEqual(result['status'], 'DRAFT_NOT_MEASUREMENT')
        self.assertIsNone(result['mean_active_seconds_saved'])

    def test_frozen_empty_packet_still_awaits_real_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            packet = Path(directory)
            (packet / 'burden-plan.json').write_bytes((self.root / 'burden-plan.json').read_bytes())
            report = observe.summarize_folder(packet)
            self.assertEqual(report['attempts'], 0)
            self.assertEqual(report['burden_comparison']['status'], 'AWAITING_REAL_PARTICIPANT')
            self.assertIsNone(report['burden_comparison']['mean_active_seconds_saved'])

    def test_malformed_and_duplicate_key_journals_are_not_dropped(self):
        (self.root / 'observations/list.jsonl').write_text('[]\n', encoding='utf-8')
        (self.root / 'observations/duplicate-key.jsonl').write_text('{"event":"start","event":"end"}\n', encoding='utf-8')
        self.report()
        report = observe.summarize_folder(self.root)
        self.assertEqual(report['attempts'], 4)
        self.assertEqual(len(report['invalid_journals']), 2)
        self.blocked(report['burden_comparison'])

    def test_supplemental_labor_cannot_duplicate_journal_time(self):
        self.ledger['entries'][0]['intervals'] = [{'actor': 'manufactured',
            'start': '2026-09-28T20:00:00Z', 'end': '2026-09-28T20:01:00Z'}]
        result = self.report()
        self.blocked(result)
        self.assertTrue(any('Overlapping' in b for b in result['blockers']))

    def test_invalid_plan_does_not_authorize_start(self):
        for key, value in (('hourly_usd', None), ('shared_with_fraction', 2), ('baseline', '')):
            plan = deepcopy(self.plan)
            plan[key] = value
            with self.assertRaises(ValueError):
                observe.validate_burden_plan(plan)

    def test_stopwatch_binds_plan_before_recording_and_refuses_replacement(self):
        source = self.root / 'observations/with_pvl-20.jsonl'
        config = json.loads(source.read_text(encoding='utf-8').splitlines()[0])['session']
        config.update(burden_plan='burden-plan.json', preparation_plan='review-evidence.json')
        self.save('session.json', config)
        output = self.root / 'live-smoke'
        with patch('builtins.input', return_value='completed'), contextlib.redirect_stdout(io.StringIO()):
            observe.main(self.root, output)
        self.assertEqual((output / 'burden-plan.json').read_bytes(), (self.root / 'burden-plan.json').read_bytes())
        self.assertEqual(len(list((output / 'observations').glob('*.jsonl'))), 1)
        self.plan['hourly_usd'] = 90
        self.save('burden-plan.json', self.plan)
        with self.assertRaisesRegex(ValueError, 'revised plan'):
            observe.main(self.root, output)
        self.assertEqual(len(list((output / 'observations').glob('*.jsonl'))), 1)


if __name__ == '__main__':
    unittest.main()
