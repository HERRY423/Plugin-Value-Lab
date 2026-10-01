"""Out-of-core arithmetic, malformed inputs, exact identity and budget gates."""
from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from value_lab.artifacts import sha
from value_lab.core import ValidationError, load_json
from value_lab.science_storage import stream_file, inventory_pinned
from value_lab.pseudobulk_backed import aggregate_h5ad, compare_counts
from test_pseudobulk import fixture


class StorageTests(unittest.TestCase):
    def test_large_file_is_streamed_and_tampering_leaves_no_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'raw.bin'
            with source.open('wb') as f:
                for i in range(33):
                    f.write(bytes([i]) * 1048576)
            digest = sha(source)
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('whole-file read')):
                info = stream_file(source, expected=digest, target=root / 'copy', maximum=40*1048576)
                self.assertEqual(info['bytes'], 33*1048576)
                self.assertEqual(sha(root / 'copy'), digest)
                with self.assertRaises(ValidationError):
                    inventory_pinned(root, {'raw.bin': digest}, 32*1048576)
                with self.assertRaisesRegex(ValidationError, 'Pinned file changed'):
                    stream_file(source, expected='0'*64, target=root / 'bad', maximum=40*1048576)
            self.assertFalse((root / 'bad').exists())

    def test_hardlink_and_disk_shortfall_rejected(self):
        import os
        from value_lab.science_storage import disk_preflight
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'raw').write_bytes(b'counts')
            os.link(root / 'raw', root / 'link')
            with self.assertRaises(ValidationError):
                stream_file(root / 'link', maximum=100)
            with patch('value_lab.science_storage.shutil.disk_usage', return_value=shutil._ntuple_diskusage(100, 90, 10)):
                with self.assertRaises(ValidationError):
                    disk_preflight(root, 10, 1)


class BackedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import anndata
            import h5py
            import numpy
            import pandas
            import scipy.sparse
        except ImportError as exc:
            raise unittest.SkipTest('Optional science dependencies unavailable') from exc
        cls.ad, cls.h5, cls.np, cls.pd, cls.sp = anndata, h5py, numpy, pandas, scipy.sparse

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.design, self.data, self.truth = fixture()

    def source(self, kind='csr', data=None):
        data = data or self.data
        x = self.np.zeros((len(data['cells']), len(data['genes'])), dtype='int64')
        for i, cell in enumerate(data['cells']):
            for j, v in cell['counts']:
                x[i, j] = v
        obs = self.pd.DataFrame([{k: c[k] for k in ('sample', 'donor', 'condition', 'cell_type')} for c in data['cells']],
                                index=[c['id'] for c in data['cells']])
        matrix = {'csr': self.sp.csr_matrix, 'csc': self.sp.csc_matrix, 'dense': lambda a: a}[kind](x)
        adata = self.ad.AnnData(X=matrix, obs=obs, var=self.pd.DataFrame(index=data['genes']))
        adata.layers['counts'] = matrix.copy()
        path = self.root / (kind + '.h5ad')
        adata.write_h5ad(path)
        return path

    def run_backed(self, source=None, name='out', **kwargs):
        source = source or self.source()
        return aggregate_h5ad(self.design, source, self.root / name, expected_sha256=sha(source),
                              reserve_bytes=0, **kwargs)

    def nullable_source(self):
        source = self.source()
        with self.h5.File(source, 'r+') as f:
            for name in ('obs/_index', 'var/_index', 'obs/sample/categories'):
                node = f[name]
                # New anndata/pandas may already encode nullable strings as a
                # group. Read via its public encoding reader in either case.
                labels = self.np.asarray(self.ad.io.read_elem(node), dtype=object)
                del f[name]
                group = f.create_group(name)
                group.attrs.update({'encoding-type': 'nullable-string-array', 'encoding-version': '0.1.0', 'na-value': 'NaN'})
                group.create_dataset('values', data=labels, dtype=self.h5.string_dtype('utf-8'))
                group.create_dataset('mask', data=self.np.zeros(len(labels), dtype=bool))
        return source

    def test_nullable_strings_and_categorical_labels_keep_exact_counts(self):
        source = self.nullable_source()
        receipt = self.run_backed(source)
        self.assertEqual(receipt['output_shape'], [6, 2])
        result = self.ad.read_h5ad(self.root / 'out/counts.h5ad')
        self.np.testing.assert_array_equal(result.X, [[3, 7]] * 6)
        self.assertEqual(list(result.var_names), ['g1', 'g2'])

    def test_nullable_missing_identity_is_not_converted_or_dropped(self):
        source = self.nullable_source()
        with self.h5.File(source, 'r+') as f:
            f['obs/_index/mask'][0] = True
        with self.assertRaisesRegex(ValidationError, 'Missing string identity'):
            self.run_backed(source)

    def test_nullable_malformed_mask_rejected(self):
        source = self.nullable_source()
        with self.h5.File(source, 'r+') as f:
            del f['var/_index/mask']
            f['var/_index'].create_dataset('mask', data=[False])
        with self.assertRaisesRegex(ValidationError, 'Malformed nullable'):
            self.run_backed(source)

    def test_csr_csc_dense_match_independent_arithmetic_and_legacy(self):
        for kind in ('csr', 'csc', 'dense'):
            with self.subTest(kind=kind):
                receipt = self.run_backed(self.source(kind), name=kind, block_entries=2)
                self.assertEqual(receipt['status'], 'COMPLETE')
                self.assertEqual(receipt['independent_units'], 3)
                self.assertEqual(receipt['excluded_cells'], 0)
                adata = self.ad.read_h5ad(self.root / kind / 'counts.h5ad')
                self.np.testing.assert_array_equal(adata.X, [[3, 7]] * 6)
                self.assertEqual(list(adata.var_names), self.truth['pseudobulk']['genes'])
                self.assertEqual(list(adata.obs_names), [s['id'] for s in self.truth['pseudobulk']['samples']])
        self.assertEqual(compare_counts(self.root / 'csr/counts.h5ad', self.root / 'csc/counts.h5ad'), [])

    def test_noninteger_negative_nan_and_duplicate_sparse_rejected(self):
        for value in (-1., .5, float('nan'), 2**31):
            source = self.source()
            with self.h5.File(source, 'a') as f:
                values = f['layers/counts/data'][:].astype('float64')
                values[0] = value
                del f['layers/counts/data']
                f['layers/counts'].create_dataset('data', data=values)
            with self.assertRaisesRegex(ValidationError, 'Counts'):
                self.run_backed(source, name='bad' + str(value))
        source = self.source()
        with self.h5.File(source, 'a') as f:
            f['layers/counts/indices'][1] = f['layers/counts/indices'][0]
        with self.assertRaisesRegex(ValidationError, 'canonical'):
            self.run_backed(source, name='duplicate', block_entries=1)

    def test_explicit_selection_counted_and_all_input_counts_validated(self):
        other = deepcopy(self.data['cells'][0])
        other.update(id='other', cell_type='T cells')
        self.data['cells'].append(other)
        source = self.source()
        with self.assertRaisesRegex(ValidationError, 'selection'):
            self.run_backed(source, name='strict')
        result = self.run_backed(source, name='selected', selection='design')
        self.assertEqual(result['excluded_cells'], 1)

    def test_duplicate_ids_missing_pairs_and_sample_conflicts(self):
        for i, mutate in enumerate((lambda d: d['cells'][1].update(id=d['cells'][0]['id']),
                                    lambda d: d['cells'][0].update(donor='conflict'),
                                    lambda d: d.update(cells=[c for c in d['cells'] if c['sample'] != 'astim']))):
            data = deepcopy(self.data)
            mutate(data)
            source = self.source(data=data)
            with self.assertRaises(ValidationError):
                self.run_backed(source, name='bad' + str(i))
            self.assertEqual(load_json(self.root / ('bad' + str(i)) / 'receipt.json')['status'], 'FAILED')

    def test_matrix_selection_no_fallback_and_hdf_external_link(self):
        source = self.source()
        with self.assertRaises(ValidationError):
            self.run_backed(source, name='missing', matrix='layers/missing')
        with self.h5.File(source, 'a') as f:
            del f['layers/counts']
            f['layers/counts'] = self.h5.ExternalLink(str(source), '/X')
        with self.assertRaisesRegex(ValidationError, 'linked'):
            self.run_backed(source, name='external')

    def test_disk_budget_blocks_without_success_artifact(self):
        with self.assertRaises(ValidationError):
            self.run_backed(max_disk_bytes=1024)
        self.assertFalse((self.root / 'out/counts.h5ad').exists())
        self.assertEqual(load_json(self.root / 'out/receipt.json')['status'], 'FAILED')

    def test_int64_aggregation_does_not_wrap_at_int32(self):
        for cell in self.data['cells']:
            cell['counts'] = [[0, 2**31-1]]
        self.run_backed(block_entries=1)
        adata = self.ad.read_h5ad(self.root / 'out/counts.h5ad')
        self.np.testing.assert_array_equal(adata.X, [[2*(2**31-1)]] * 6)

    def test_fit_budget_fails_before_backend_and_receipt_tamper_rejected(self):
        from value_lab.core import suite_digest
        from value_lab.pseudobulk_backed import fit_backed_reference
        receipt = self.run_backed()
        with patch('value_lab.pseudobulk._fit_aggregated') as fitting:
            with self.assertRaisesRegex(ValidationError, 'memory budget'):
                fit_backed_reference(self.design, self.root / 'out', suite_digest(receipt), max_fit_bytes=1024)
            with self.assertRaisesRegex(ValidationError, 'commitment'):
                fit_backed_reference(self.design, self.root / 'out', '0'*64, max_fit_bytes=2*1024**3)
            fitting.assert_not_called()

    def test_sparse_pointer_corruption_does_not_drop_entries(self):
        source = self.source()
        with self.h5.File(source, 'a') as f:
            f['layers/counts/indptr'][-1] -= 1
        with self.assertRaisesRegex(ValidationError, 'endpoints'):
            self.run_backed(source)

    def test_exact_comparator_detects_last_count_identity_and_extra_field(self):
        self.run_backed()
        a, b = self.root / 'out/counts.h5ad', self.root / 'copy.h5ad'
        shutil.copyfile(a, b)
        with self.h5.File(b, 'a') as f:
            f['X'][-1, -1] += 1
        self.assertTrue(compare_counts(a, b))
        shutil.copyfile(a, b)
        with self.h5.File(b, 'a') as f:
            f['obs/_index'][0] = 'wrong'
        self.assertTrue(compare_counts(a, b))
        shutil.copyfile(a, b)
        with self.h5.File(b, 'a') as f:
            f.create_group('obsm')
        with self.assertRaises(ValidationError):
            compare_counts(a, b)


if __name__ == '__main__':
    unittest.main()
