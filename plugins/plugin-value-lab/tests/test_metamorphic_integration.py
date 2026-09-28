"""Full evaluator, private scenarios, portable schema and report integration."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from test_metamorphic import numeric_design, contrast_design, observations
from value_lab.artifacts import sha
from value_lab.core import demo_suite, demo_records, evaluate, write_json
from value_lab.metamorphic import assess


class MetamorphicIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.design = numeric_design()
        write_json(self.root / 'design.json', self.design)
        self.grader = {'id': 'relation', 'type': 'metamorphic', 'dimension': 'outcome', 'weight': 1,
                       'critical': False, 'artifact': 'result',
                       'verifier': {'design': {'path': 'design.json', 'sha256': sha(self.root / 'design.json')}}}

    def report(self, with_runs, anchor=True):
        suite = demo_suite()
        suite['cases'] = suite['cases'][:1]
        suite['cases'][0]['graders'] = [self.grader]
        if anchor:
            suite['cases'][0]['graders'].append({'id': 'baseline-oracle', 'type': 'artifact', 'dimension': 'outcome',
                'weight': 99, 'critical': True, 'artifact': 'result', 'verifier': {'kind': 'json_fields',
                'expected': {'runs.0.output': {'row_ids': ['summary'], 'columns': ['x', 'y'], 'values': [[12, 21]]}}}})
        records = demo_records(suite)
        write_json(self.root / 'with.json', with_runs)
        write_json(self.root / 'without.json', observations(self.design))
        for record in records:
            filename = record['arm'] + '.json'
            record['artifacts'] = {'result': {'path': filename, 'sha256': sha(self.root / filename)}}
        return evaluate(suite, records, artifact_root=self.root, verifier_root=self.root)

    def test_relation_failure_cannot_hide_behind_high_partial_quality_score(self):
        runs = observations(self.design)
        runs['runs'][1]['output']['values'][0][0] = 100
        report = self.report(runs)
        with_run = next(r for r in report['cases'][0]['runs'] if r['arm'] == 'with')
        self.assertEqual(with_run['score'], .99)
        self.assertFalse(with_run['task_outcome']['passed'])
        self.assertEqual(with_run['task_outcome']['layers']['correctness']['status'], 'FAIL')

    def test_relation_only_success_is_unknown_in_full_evaluator(self):
        report = self.report(observations(self.design), anchor=False)
        for run in report['cases'][0]['runs']:
            self.assertEqual(run['score'], 1)
            self.assertIsNone(run['task_outcome']['passed'])

    def test_private_scenario_cannot_promote_relation_only_to_correctness(self):
        from value_lab.scenarios import grade_scenario
        child = {key: value for key, value in self.grader.items() if key in ('id', 'type', 'artifact', 'verifier')}
        private = {'type': 'ScorerOnlyGroundTruth', 'case_id': 'science', 'evidence_type': 'synthetic',
                   'nonce': 'a' * 64, 'rationale': 'Manufactured consistency-only test', 'graders': [child]}
        write_json(self.root / 'private.json', private)
        write_json(self.root / 'observations.json', observations(self.design))
        g = {'id': 'private', 'type': 'scenario', 'verifier': {'path': 'private.json',
             'sha256': sha(self.root / 'private.json'), 'case_id': 'science', 'evidence_type': 'synthetic'}}
        record = {'artifacts': {'result': {'path': 'observations.json', 'sha256': sha(self.root / 'observations.json')}}}
        result = grade_scenario(g, record, self.root, self.root)
        self.assertIsNone(result[0])
        self.assertTrue(result[2]['grades'][0]['passed'])

    def test_replay_inventory_and_declarative_loader_preserve_design_reference(self):
        from value_lab.replay import replay_contract
        from value_lab.declarative import dump_evals, load_evals
        suite = demo_suite()
        suite['cases'][0]['graders'] = [self.grader]
        dump_evals(suite, self.root / 'evals')
        self.assertEqual(load_evals(self.root / 'evals')['cases'][0]['graders'][0], self.grader)
        contract = replay_contract(suite, [], verifier_root=self.root)
        designs = [m for m in contract['materials'] if m['kind'] == 'design']
        self.assertEqual(designs[0]['status'], 'BYTES_MATCH')

    def test_report_exposes_relations_and_escapes_entity_text(self):
        from value_lab.report import _metamorphic_details
        _, receipt = assess(self.design, observations(self.design))
        receipt['relations'][0]['id'] = '<script>alert(1)</script>'
        rendered = _metamorphic_details([{'verification': receipt}])
        self.assertIn('科学蜕变关系', rendered)
        self.assertIn('row_permutation', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;script&gt;', rendered)

    def test_json_schema_matches_examples_and_rejects_extra_fields(self):
        import jsonschema
        path = Path(__file__).resolve().parents[1] / 'schemas/science/metamorphic-design.schema.json'
        schema = json.loads(path.read_text(encoding='utf-8'))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(self.design, schema)
        jsonschema.validate(contrast_design(), schema)
        bad = deepcopy(self.design)
        bad['relations'][0]['parameters']['code'] = 'untrusted'
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)


if __name__ == '__main__':
    unittest.main()
