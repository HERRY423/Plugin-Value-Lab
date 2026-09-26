"""Pilot material checks. Manufactured sessions never count as real participants."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_pseudobulk import fixture
from value_lab.core import write_json, ValidationError

BASE = Path(__file__).resolve().parents[1] / 'examples/pseudobulk-author-pilot'


def load(name):
    spec = importlib.util.spec_from_file_location('pilot_' + name, BASE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare, observe = load('prepare'), load('observe')


class AuthorPilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.design, self.data, _ = fixture()
        write_json(self.root / 'data.json', self.data)
        self.config = {'question': 'Check my declared paired analysis', 'plugin_path': '.',
                       'design': self.design, 'data': {'kind': 'pvl-cell-counts-1', 'path': 'data.json'},
                       'author_review': {}}
        self.session = {'participant': 'manufactured', 'arm': 'with_pvl', 'problem_id': 'a',
                        'task_pair': 'pair1', 'order': 1, 'previous_exposure': 'test',
                        'maintainer_or_ai': True, 'preparation_plan': 'plan.md'}

    def run_prepare(self):
        write_json(self.root / 'input.json', self.config)
        return prepare.prepare(self.root / 'input.json', self.root / 'attempt')

    def start(self):
        return {'event': 'start', 'elapsed_seconds': 0, 'session': self.session}

    def test_preparation_reports_real_supplied_shape_without_truth(self):
        result = self.run_prepare()
        self.assertEqual(result['status'], 'AUTHOR_REVIEW_REQUIRED')
        self.assertEqual((result['donor_pairs'], result['samples'], result['tested_genes']), (3, 6, 2))
        self.assertFalse(result['reference_created'])
        self.assertEqual(len(result['pending']), 5)
        self.assertFalse((self.root / 'attempt/reference.json').exists())
        self.assertFalse((self.root / 'attempt/result.json').exists())
        self.assertEqual(result['samples_to_check'][0]['cells'], 2)
        with self.assertRaises(FileExistsError):
            self.run_prepare()

    def test_author_confirmation_is_still_not_review_authentication(self):
        self.config['author_review'] = {k: True for k in ('raw_counts_and_identity_checked', 'paired_design_appropriate',
                        'fixed_method_matches_question', 'filters_chosen_before_results')}
        self.config['author_review']['reference_suitability_basis'] = 'declared, not certified'
        result = self.run_prepare()
        self.assertEqual(result['status'], 'READY_FOR_EXPLICIT_REFERENCE_RUN')
        self.assertFalse(result['review_authenticated'])
        self.assertFalse(result['reference_created'])

    def test_incomplete_pairs_retain_failed_attempt(self):
        self.data['cells'] = [c for c in self.data['cells'] if c['sample'] != 'astim']
        write_json(self.root / 'data.json', self.data)
        with self.assertRaises(ValidationError):
            self.run_prepare()
        receipt = json.loads((self.root / 'attempt/preparation.json').read_text())
        self.assertEqual(receipt['status'], 'FAILED')
        self.assertFalse(receipt['reference_created'])

    def test_bad_json_retains_failed_attempt(self):
        (self.root / 'bad.json').write_text('{', encoding='utf-8')
        with self.assertRaises(ValueError):
            prepare.prepare(self.root / 'bad.json', self.root / 'attempt')
        self.assertEqual(json.loads((self.root / 'attempt/preparation.json').read_text())['status'], 'FAILED')

    def test_h5ad_requires_explicit_layer_and_mapping(self):
        self.config['data'] = {'kind': 'h5ad', 'path': 'data.h5ad'}
        with self.assertRaisesRegex(ValidationError, 'counts_layer'):
            self.run_prepare()

    def test_h5ad_adapter_uses_supplied_layer_and_never_rounds(self):
        import anndata
        import numpy as np
        import pandas as pd
        obs = pd.DataFrame([{k: c[k] for k in ('id', 'sample', 'donor', 'condition', 'cell_type')}
                           for c in self.data['cells']]).set_index('id')
        counts = np.zeros((len(obs), len(self.data['genes'])))
        for i, cell in enumerate(self.data['cells']):
            for j, value in cell['counts']:
                counts[i, j] = value
        obj = anndata.AnnData(np.full_like(counts, .5), obs=obs, var=pd.DataFrame(index=self.data['genes']), layers={'counts': counts})
        path = self.root / 'input.h5ad'
        obj.write_h5ad(path)
        source = {'kind': 'h5ad', 'path': path.name, 'counts_layer': 'counts',
                  **{k + '_column': k for k in ('sample', 'donor', 'condition', 'cell_type')}}
        data, _ = prepare.read_data(source, self.design, self.root)
        self.assertEqual(data['cells'], self.data['cells'])
        source['counts_layer'] = 'X'
        with self.assertRaisesRegex(ValidationError, 'no rounding'):
            prepare.read_data(source, self.design, self.root)

    def test_active_time_and_extra_retest_preparation_stay_separate(self):
        events = [self.start(), {'event': 'phase', 'phase': 'preparation', 'elapsed_seconds': 10},
                  {'event': 'phase', 'phase': 'pause', 'elapsed_seconds': 30},
                  {'event': 'phase', 'phase': 'diagnosis', 'elapsed_seconds': 90},
                  {'event': 'milestone', 'name': 'understood', 'elapsed_seconds': 100,
                   'explanation': 'claim only', 'evidence': {'path': 'diagnosis', 'sha256': 'a' * 64}},
                  {'event': 'phase', 'phase': 'retest_preparation', 'elapsed_seconds': 100},
                  {'event': 'phase', 'phase': 'retest', 'elapsed_seconds': 125},
                  {'event': 'milestone', 'name': 'credible_retest', 'elapsed_seconds': 140,
                   'explanation': 'pending review', 'evidence': {'path': 'retest', 'sha256': 'b' * 64}},
                  {'event': 'end', 'outcome': 'completed', 'elapsed_seconds': 145}]
        report = observe.summarize(events)
        self.assertEqual(report['milestones']['understood']['active_seconds'], 40)
        self.assertEqual(report['diagnosis_to_retest']['active_seconds'], 40)
        self.assertEqual(report['diagnosis_to_retest']['by_phase_seconds']['retest_preparation'], 25)
        self.assertEqual(report['observed_active_seconds'], 85)
        self.assertEqual(report['observed_wall_seconds'], 145)
        self.assertEqual(report['milestones']['credible_retest']['adjudication'], 'PENDING')
        self.assertIsNone(report['confirmed_defects'])

    def test_interrupted_or_abandoned_is_not_success(self):
        events = [self.start(), {'event': 'phase', 'phase': 'preparation', 'elapsed_seconds': 10}]
        report = observe.summarize(events)
        self.assertEqual(report['outcome'], 'INTERRUPTED_OR_OPEN')
        self.assertTrue(report['unobserved_tail_unknown'])
        self.assertIsNone(report['diagnosis_to_retest'])
        report = observe.summarize(events + [{'event': 'end', 'outcome': 'abandoned', 'elapsed_seconds': 20}])
        self.assertEqual(report['outcome'], 'abandoned')
        self.assertEqual(report['pvl_benefit'], 'NOT_ESTABLISHED')

    def test_invalid_chronology_and_unsubstantiated_marks_rejected(self):
        cases = [[{'event': 'phase', 'phase': 'reading', 'elapsed_seconds': -1}],
                 [{'event': 'phase', 'phase': 'reading', 'elapsed_seconds': float('nan')}],
                 [{'event': 'milestone', 'name': 'understood', 'elapsed_seconds': 1}],
                 [{'event': 'milestone', 'name': 'credible_retest', 'elapsed_seconds': 1, 'explanation': 'x', 'evidence': {'path': 'x'}}],
                 [{'event': 'end', 'outcome': 'completed', 'elapsed_seconds': 1}, {'event': 'help', 'elapsed_seconds': 2}]]
        for tail in cases:
            with self.assertRaises(ValueError):
                observe.summarize([self.start()] + tail)

    def test_aggregate_keeps_invalid_logs_and_failed_attempts(self):
        directory = self.root / 'observations'
        directory.mkdir()
        (directory / 'bad.jsonl').write_text('{', encoding='utf-8')
        (directory / 'open.jsonl').write_text(json.dumps(self.start()) + '\n', encoding='utf-8')
        summary = observe.summarize_folder(self.root)
        self.assertEqual(summary['attempts'], 2)
        self.assertEqual(summary['non_maintainer_participants_declared'], 0)
        self.assertEqual(len(summary['invalid_journals']), 1)
        self.assertEqual(summary['runs'][0]['outcome'], 'INTERRUPTED_OR_OPEN')

    def test_empty_packet_has_no_fabricated_participants(self):
        summary = observe.summarize_folder(self.root)
        self.assertEqual(summary['status'], 'AWAITING_REAL_PARTICIPANT')
        self.assertEqual(summary['attempts'], 0)
        self.assertEqual(summary['non_maintainer_participants_declared'], 0)

    def test_unknown_arm_and_missing_exposure_rejected(self):
        for key, value in (('arm', 'with_plugin'), ('previous_exposure', None), ('maintainer_or_ai', None), ('order', True)):
            config = deepcopy(self.session)
            config[key] = value
            with self.assertRaises(ValueError):
                observe.validate_session(config)
