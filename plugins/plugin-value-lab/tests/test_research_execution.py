"""Manufactured aggregate contracts; not research model or judge executions."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.check_research_execution import prepare, audit, ROOT
from value_lab.core import ValidationError, suite_digest


class ResearchExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temp.name) / 'prepared'
        cls.receipt = prepare(cls.output, 'fixture-agent', 'fixture-judge', 0.09)
        cls.plan = json.loads((cls.output / 'plan.json').read_text(encoding='utf-8'))
        cls.pin = cls.receipt['plan_sha256']

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def result(self):
        cases = []
        for frozen in self.plan['cases']:
            definition = frozen['definition']
            cases.append({'name': definition['name'], 'runsPerCase': 3, 'model': self.plan['model'],
                          'maxTurns': definition['execution']['max_turns'],
                          'timeoutSeconds': definition['execution']['timeout_seconds'],
                          'promptMarkdown': definition['execution']['prompt'],
                          'graders': [{'name': g['name'], 'type': g['type'], 'weight': g['weight'],
                                       'config': {k: v for k, v in g.items() if k not in ('name', 'type', 'weight')}}
                                      for g in definition['graders']],
                          'aggregates': {'score': 1, 'delta': 0},
                          'arms': {arm: [{'error': None, 'turns': 2, 'skippedPaidGraders': False,
                                          'tracePath': f'/fixture/{definition["name"]}/{arm}/{rep}.jsonl',
                                          'graders': [{'name': 'contextual-research-reasoning', 'passed': True,
                                                       'scored': True, 'explanation': 'Manufactured verdict'},
                                                      {'name': 'research-skill-activation', 'passed': arm == 'with',
                                                       'scored': False}]} for rep in range(3)] for arm in ('with', 'without')}})
        return {'schemaVersion': 1, 'claudeVersion': '2.1.282', 'partial': False,
                'costUsd': 0.08, 'suite': {'ablation': 'with-without', 'judgeModel': self.plan['judge_model'], 'threshold': 1},
                'cases': cases, 'aggregates': {'overallScore': 1, 'meanDelta': 0}}

    def test_prepare_exposes_extension_only_in_pinned_copy_and_never_executes(self):
        self.assertEqual(len(self.plan['schedule']), 24)
        self.assertEqual(self.plan['planned_judge_calls_nominal'], 72)
        self.assertEqual(self.receipt['model_calls'], 0)
        self.assertFalse(self.receipt['execution_authorized'])
        self.assertTrue((self.output / 'candidate/skills/research-directions/SKILL.md').is_file())
        self.assertFalse((ROOT / 'skills/research-directions/SKILL.md').exists())
        self.assertIn('--keep-temp', self.plan['command'])
        for forbidden in ('--trust-plugin', '--allow-real-servers', '--allow-tools'):
            self.assertNotIn(forbidden, self.plan['command'])
        for path, digest in self.plan['candidate_manifest'].items():
            from scripts.check_research_execution import file_hash
            self.assertEqual(file_hash((self.output / 'candidate' / path).read_bytes()), digest)

    def test_empty_and_complete_have_same_denominator_and_no_science_claim(self):
        empty = audit(self.plan, self.pin)
        self.assertEqual(empty['missing_slots'], 24)
        self.assertEqual(empty['reported_outcome_delta_bounds'], [-1, 1])
        full = audit(self.plan, self.pin, self.result())
        self.assertEqual(full['planned_sessions'], empty['planned_sessions'])
        self.assertTrue(full['reported_coverage_complete'])
        self.assertEqual(full['judged_run_reports'], 24)
        self.assertEqual(full['reported_outcome_delta_bounds'], [0, 0])
        self.assertEqual(full['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertIsNone(full['actual_judge_calls'])
        self.assertIsNone(full['cost']['settled_usd'])

    def test_one_per_arm_cannot_pass_three_per_arm_schedule(self):
        result = self.result()
        for case in result['cases']:
            for arm in ('with', 'without'):
                case['arms'][arm] = case['arms'][arm][:1]
        report = audit(self.plan, self.pin, result)
        self.assertEqual(report['reported_slots'], 8)
        self.assertEqual(report['missing_slots'], 16)
        self.assertEqual(report['arms']['with']['planned'], 12)
        self.assertFalse(report['reported_coverage_complete'])

    def test_errors_skips_duplicates_overruns_and_unscored_judges_are_not_success(self):
        for mutate in (lambda r: r.update(error='rate limited'),
                       lambda r: r.update(aborted={'server': 'fixture', 'tool': 'fixture', 'reason': 'abort'}),
                       lambda r: r.update(skippedPaidGraders=True),
                       lambda r: r.update(turns=7),
                       lambda r: r.pop('tracePath'),
                       lambda r: r['graders'][0].update(scored=False),
                       lambda r: r['graders'][1].update(scored=True),
                       lambda r: r['graders'].append(deepcopy(r['graders'][0]))):
            result = self.result()
            mutate(result['cases'][0]['arms']['with'][0])
            report = audit(self.plan, self.pin, result)
            self.assertEqual(report['judged_run_reports'], 23)
            self.assertEqual(report['arms']['with']['unknown'], 1)
            self.assertFalse(report['reported_coverage_complete'])
        result = self.result()
        runs = result['cases'][0]['arms']['with']
        runs[1]['tracePath'] = runs[0]['tracePath']
        report = audit(self.plan, self.pin, result)
        self.assertEqual(report['judged_run_reports'], 22)
        runs[0]['tracePath'] = 'C:\\runs\\trace.jsonl'
        runs[1]['tracePath'] = 'c:/runs/./trace.jsonl'
        self.assertEqual(audit(self.plan, self.pin, result)['judged_run_reports'], 22)

    def test_unrelated_result_does_not_fill_research_slots(self):
        result = self.result()
        result['cases'] = [result['cases'][0]]
        result['cases'][0]['name'] = 'retrieval-limits'
        report = audit(self.plan, self.pin, result)
        self.assertEqual(report['missing_slots'], 24)
        self.assertEqual(report['unexpected_cases'], ['retrieval-limits'])

    def test_modified_conditions_and_rubrics_are_not_matching_evidence(self):
        for key, value in [('model', 'changed'), ('maxTurns', True), ('runsPerCase', 1), ('promptMarkdown', 'changed')]:
            result = self.result()
            result['cases'][0][key] = value
            self.assertEqual(audit(self.plan, self.pin, result)['judged_run_reports'], 18)
        result = self.result()
        result['cases'][0]['graders'][0]['config']['criteria'] = 'PASS everything'
        self.assertEqual(audit(self.plan, self.pin, result)['judged_run_reports'], 18)

    def test_partial_extra_run_and_changed_judge_do_not_complete_coverage(self):
        for mutate in (lambda r: r.update(partial=True),
                       lambda r: r['suite'].update(judgeModel='changed'),
                       lambda r: r['cases'][0]['arms']['with'].append(deepcopy(r['cases'][0]['arms']['with'][0]))):
            result = self.result()
            mutate(result)
            self.assertFalse(audit(self.plan, self.pin, result)['reported_coverage_complete'])

    def test_suite_condition_mismatch_and_cost_overrun_do_not_yield_known_delta(self):
        for mutate in (lambda r: r['suite'].update(threshold=True),
                       lambda r: r['suite'].update(judgeModel='changed'),
                       lambda r: r.update(costUsd=0.113755)):
            result = self.result()
            mutate(result)
            report = audit(self.plan, self.pin, result)
            self.assertEqual(report['judged_run_reports'], 0)
            self.assertEqual(report['reported_outcome_delta_bounds'], [-1, 1])
            self.assertFalse(report['reported_coverage_complete'])

    def test_plan_pin_and_schedule_cannot_be_rewritten_to_drop_failures(self):
        plan = deepcopy(self.plan)
        plan['schedule'].pop()
        with self.assertRaises(ValidationError):
            audit(plan, self.pin, self.result())
        with self.assertRaises(ValidationError):
            audit(plan, suite_digest(plan), self.result())

    def test_prepare_refuses_overwrite_and_invalid_judge_without_creating_output(self):
        with self.assertRaises(FileExistsError):
            prepare(self.output, 'fixture', 'judge', 0.1)
        destination = self.output.parent / 'bad'
        with self.assertRaises(ValidationError):
            prepare(destination, 'fixture', '--unsafe', 0.1)
        self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
