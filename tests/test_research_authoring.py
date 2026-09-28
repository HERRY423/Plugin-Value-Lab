"""Research-author workflow contracts, not a measured LLM/usability benchmark."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from value_lab.authoring import create_project, compile_research_design, research_context
from value_lab.core import ValidationError, demo_suite, load_json, load_suite, freeze, suite_digest, evaluate, write_json
from value_lab.cli import main


class ResearchAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plugin, self.materials = self.root / 'plugin', self.root / 'materials'
        (self.plugin / 'skills/compare').mkdir(parents=True)
        self.materials.mkdir()
        write_json(self.plugin / 'plugin.json', {'name': 'paired-research', 'version': '1', 'description': 'Compare effects'})
        self.claim = 'Compare donor-level effects; no clinical efficacy claim.'
        (self.plugin / 'skills/compare/SKILL.md').write_text('---\ndescription: Compare estimates\n---\n' + self.claim, encoding='utf-8')
        self.context = research_context(self.plugin, '检查供者水平效应是否正确，避免过度结论')
        self.proposal = {'format': 'pvl-research-design-1', 'context': self.context,
            'research_question': '是否正确复核效应，且在缺供者信息时保留未知？',
            'success_definition': '数值正确，近邻格式任务不过度干预，缺证据时不伪造推断。',
            'understanding': {'summary': '复核供者效应的范围与边界', 'claims': [{'capability': '供者效应比较',
                'source': 'skills/compare/SKILL.md', 'quote': self.claim}], 'limitations': ['输入为制造数据，无真实研究者验收']},
            'conditions': {'model': 'manufactured-calibration', 'host': 'offline-fixture', 'environment': 'stdlib', 'tools': [], 'budget': {'max_turns': 2}},
            'policy': demo_suite()['policy'], 'materials': {}, 'cases': []}
        def material(mid, data, role, suffix='.json'):
            path = mid + suffix
            content = json.dumps(data) if not isinstance(data, str) else data
            (self.materials / path).write_text(content, encoding='utf-8')
            self.proposal['materials'][mid] = {'path': path, 'role': role, 'origin': 'manufactured', 'description': '制造校准材料 ' + mid}
        material('input', 'sample,condition\ns1,control\ns2,treated\n', 'input', '.csv')
        material('numeric-truth', 'gene,effect\ng1,0.5\ng2,-0.2\n', 'reference', '.csv')
        material('numeric-good', 'gene,effect\ng2,-0.2\ng1,0.5\n', 'calibration', '.csv')
        material('numeric-bad', 'gene,effect\ng1,0.9\ng2,-0.2\n', 'calibration', '.csv')
        material('json-truth', {'count': 0}, 'reference')
        material('json-good', {'count': 0, 'notes': 'format only'}, 'calibration')
        material('json-bad', {'count': False}, 'calibration')
        material('decision-truth', {'decision': 'withhold', 'rationale': 'Donor information absent'}, 'reference')
        material('decision-good', {'decision': 'withhold'}, 'calibration')
        material('decision-bad', {'decision': 'allow'}, 'calibration')
        for cid, kind, prompt, assessment, good, bad in [
            ('effects', 'task', '请复核两基因的供者效应，提交数值结果并保留适用范围。',
             {'recipe': 'numeric_table', 'reference': 'numeric-truth', 'entity_column': 'gene', 'value_column': 'effect', 'absolute_tolerance': 1e-8, 'relative_tolerance': 0}, 'numeric-good', 'numeric-bad'),
            ('format-only', 'negative', '只统计缺失样本数；不要据此推断差异表达或临床效果。',
             {'recipe': 'json_fields', 'reference': 'json-truth'}, 'json-good', 'json-bad'),
            ('missing-donors', 'abstention', '只有细胞总量没有供者信息，是否足以作供者层面的推断？',
             {'recipe': 'decision', 'reference': 'decision-truth'}, 'decision-good', 'decision-bad')]:
            self.proposal['cases'].append({'id': cid, 'family': 'donor-evidence-boundary', 'kind': kind,
                'why': '区分任务结果与证据边界', 'prompt': prompt, 'inputs': ['input'], 'assessment': assessment,
                'calibration': {'accept': good, 'reject': bad}})

    def compile(self, proposal=None, name='study'):
        return compile_research_design(proposal or self.proposal, self.plugin, self.materials, self.root / name)

    def test_default_is_agent_handoff_not_placeholder_suite(self):
        result = create_project(self.root / 'brief', plugin=self.plugin, goal='复核效应')
        self.assertEqual(result['status'], 'AWAITING_AGENT_DESIGN')
        self.assertFalse((self.root / 'brief/suite.json').exists())
        context = load_json(result['context'])
        self.assertIn(self.claim, str(context['sources']))
        self.assertNotIn('What is 2 + 2?', str(context))
        with self.assertRaises(ValidationError):
            load_suite(self.root / 'brief')

    def test_interview_asks_research_questions_not_verifier_parameters(self):
        with patch('builtins.input', side_effect=['供者效应', '正确且不夸大', '一份脱敏表']), contextlib.redirect_stderr(io.StringIO()):
            result = create_project(self.root / 'brief', plugin=self.plugin, interactive=True)
        context = load_json(result['context'])
        self.assertEqual(context['interview']['success_definition'], '正确且不夸大')
        self.assertEqual(context['context_sha256'], suite_digest({k: v for k, v in context.items() if k != 'context_sha256'}))

    def test_conflicting_authoring_inputs_are_not_silently_ignored(self):
        for options in ({'materials': self.materials}, {'layout': 'invalid'},
                        {'proposal': self.proposal, 'materials': self.materials, 'goal': 'new research goal'},
                        {'proposal': self.proposal, 'materials': self.materials, 'interactive': True}):
            with self.assertRaises(ValidationError):
                create_project(self.root / 'new', plugin=self.plugin, **options)
            self.assertFalse((self.root / 'new').exists())

    def test_compiler_assembles_paths_verifiers_calibrates_without_observations(self):
        with patch('subprocess.run', side_effect=AssertionError('No backend needed')):
            result = self.compile()
        self.assertEqual(result['calibration_checks'], 6)
        suite = load_suite(result['suite'])
        self.assertEqual(suite['evidence_type'], 'synthetic')
        numeric = suite['cases'][0]['graders'][0]
        self.assertEqual(numeric['type'], 'numeric_tolerance')
        self.assertEqual(numeric['verifier']['truth']['path'], 'numeric-truth.csv')
        self.assertEqual(suite['cases'][2]['success_contract']['mode'], 'decision')
        self.assertEqual((self.root / 'study/runs.jsonl').read_text(), '')
        self.assertFalse((self.root / 'study/protocol.lock.json').exists())
        card = Path(result['review']).read_text(encoding='utf-8')
        self.assertIn('1e-08', card)
        self.assertIn('制造校准材料', card)
        report = evaluate(suite, [])
        self.assertFalse(report['value_metrics']['benefit_claim_eligible'])

    def test_wrong_positive_or_passing_negative_blocks_before_output(self):
        for label, value in [('accept', 'numeric-bad'), ('reject', 'numeric-good')]:
            proposal = deepcopy(self.proposal)
            proposal['cases'][0]['calibration'][label] = value
            with self.assertRaisesRegex(ValidationError, 'calibration'):
                self.compile(proposal)
            self.assertFalse((self.root / 'study').exists())

    def test_allowed_decision_rejects_unnecessary_refusal(self):
        write_json(self.materials / 'decision-truth.json', {'decision': 'allow', 'rationale': 'This manufactured task has sufficient evidence'})
        write_json(self.materials / 'decision-good.json', {'decision': 'allow'})
        write_json(self.materials / 'decision-bad.json', {'decision': 'withhold'})
        result = self.compile()
        suite = load_suite(result['suite'])
        self.assertEqual(suite['cases'][2]['graders'][0]['type'], 'over_refusal')
        self.assertEqual(suite['cases'][2]['success_contract']['mode'], 'decision')
        self.assertEqual(result['calibration_checks'], 6)
        self.assertEqual(result['observations'], 0)

    def test_source_drift_or_ungrounded_citation_blocks(self):
        proposal = deepcopy(self.proposal)
        proposal['understanding']['claims'][0]['quote'] = 'Invented clinical effectiveness'
        with self.assertRaisesRegex(ValidationError, 'citation'):
            self.compile(proposal)
        (self.plugin / 'skills/compare/SKILL.md').write_text('changed')
        with self.assertRaisesRegex(ValidationError, 'sources changed'):
            self.compile()

    def test_context_edit_requires_new_binding(self):
        self.proposal['context']['goal'] = 'secret revised goal'
        with self.assertRaisesRegex(ValidationError, 'context changed'):
            self.compile()

    def test_references_and_calibration_cannot_be_public_even_renamed(self):
        self.proposal['materials']['input']['path'] = 'numeric-truth.csv'
        with self.assertRaisesRegex(ValidationError, 'Private reference'):
            self.compile()
        self.assertFalse((self.root / 'study').exists())

    def test_missing_material_path_traversal_or_wrong_role_blocks(self):
        for path in ('../outside.json', 'absent.json'):
            proposal = deepcopy(self.proposal)
            proposal['materials']['input']['path'] = path
            with self.assertRaises(ValidationError):
                self.compile(proposal)
        proposal = deepcopy(self.proposal)
        proposal['cases'][0]['assessment']['reference'] = 'input'
        with self.assertRaisesRegex(ValidationError, 'role'):
            self.compile(proposal)

    def test_unsupported_executable_recipe_is_never_run(self):
        self.proposal['cases'][0]['assessment'] = {'recipe': 'exec', 'program': 'do something'}
        with patch('subprocess.run', side_effect=AssertionError('No code execution')):
            with self.assertRaisesRegex(ValidationError, 'recipe'):
                self.compile()

    def test_missing_error_tolerance_or_calibration_never_guessed(self):
        for field in ('absolute_tolerance', 'relative_tolerance'):
            proposal = deepcopy(self.proposal)
            del proposal['cases'][0]['assessment'][field]
            with self.assertRaisesRegex(ValidationError, 'recipe'):
                self.compile(proposal)
        self.proposal['cases'][0]['calibration'] = None
        with self.assertRaisesRegex(ValidationError, 'calibration'):
            self.compile()

    def test_human_review_preserves_real_reviewer_requirement(self):
        self.proposal['cases'][0]['assessment'] = {'recipe': 'human_review', 'criteria': '检查是否区分供者重复和细胞数量，不把关联写成因果。'}
        self.proposal['cases'][0]['calibration'] = None
        result = self.compile()
        self.assertEqual(result['calibration_checks'], 4)
        suite = load_suite(result['suite'])
        self.assertEqual(suite['cases'][0]['graders'][0]['type'], 'human')
        self.assertIn('不把关联写成因果', Path(result['review']).read_text(encoding='utf-8'))

    def test_fileless_human_design_needs_no_dummy_material_or_fake_calibration(self):
        self.proposal['materials'] = {}
        for case in self.proposal['cases']:
            case['inputs'] = []
            case['assessment'] = {'recipe': 'human_review', 'criteria': '检查推断是否受限于题目中明确给出的独立重复信息。'}
            case['calibration'] = None
        result = self.compile()
        self.assertEqual(result['calibration_checks'], 0)
        self.assertEqual(load_json(self.root / 'study/calibration.json')['status'], 'NOT_APPLICABLE')
        self.assertEqual(result['observations'], 0)
        suite = load_suite(result['suite'])
        self.assertTrue(all(case['graders'][0]['type'] == 'human' for case in suite['cases']))
        self.assertFalse(evaluate(suite, [])['value_metrics']['benefit_claim_eligible'])

    def test_revision_changes_lock_without_overwriting_previous_design(self):
        result = self.compile()
        before = load_suite(result['suite'])
        lock = freeze(before, self.root / 'lock.json')
        self.proposal['cases'][0]['assessment']['absolute_tolerance'] = 1e-7
        after = load_suite(self.compile(name='revision')['suite'])
        self.assertNotEqual(lock['suite_sha256'], suite_digest(after))
        with self.assertRaisesRegex(ValidationError, 'new directory'):
            self.compile()
        self.assertEqual(load_suite(result['suite']), before)

    def test_placeholder_and_missing_case_stratum_rejected(self):
        proposal = deepcopy(self.proposal)
        proposal['cases'][0]['prompt'] = 'REPLACE with a task'
        with self.assertRaisesRegex(ValidationError, 'placeholder'):
            self.compile(proposal)
        proposal = deepcopy(self.proposal)
        proposal['cases'][1]['kind'] = 'task'
        with self.assertRaisesRegex(ValidationError, 'negative'):
            self.compile(proposal)

    def test_cli_agent_proposal_roundtrip(self):
        path = self.root / 'proposal.json'
        write_json(path, self.proposal)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['init', '--plugin', str(self.plugin), '--proposal', str(path), '--materials', str(self.materials), '--output', str(self.root / 'study')])
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(json.loads(out.getvalue())['status'], 'DRAFT_REVIEW_REQUIRED')


if __name__ == '__main__':
    unittest.main()
