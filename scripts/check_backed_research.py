"""Compare a supplied cached raw-count bundle with the backed pathway and fit.

No download or provenance authentication; records the supplied source boundary.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.artifacts import sha
from value_lab.core import load_json, suite_digest, write_json
from value_lab.pseudobulk import aggregate, fit_reference
from value_lab.pseudobulk_backed import aggregate_h5ad, fit_backed_reference
from value_lab.science_execution import compare_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--fit', action='store_true')
    args = parser.parse_args()
    import anndata as ad
    import numpy as np
    import pandas as pd
    from scipy.sparse import csr_matrix
    source, root = Path(args.source), Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    design, data = (load_json(source / n) for n in ('design.json', 'data.json'))
    pb = aggregate(design, data)
    values, indices, pointers = [], [], [0]
    for cell in data['cells']:
        entries = sorted(cell['counts'])
        indices.extend(i for i, v in entries)
        values.extend(v for i, v in entries)
        pointers.append(len(values))
    counts = csr_matrix((np.asarray(values, dtype='int64'), np.asarray(indices), np.asarray(pointers)),
                         shape=(len(data['cells']), len(data['genes'])))
    obs = pd.DataFrame([{k: c[k] for k in ('sample', 'donor', 'condition', 'cell_type')} for c in data['cells']],
                       index=[c['id'] for c in data['cells']])
    ad.AnnData(X=counts, obs=obs, var=pd.DataFrame(index=data['genes'])).write_h5ad(root / 'input.h5ad')
    result = aggregate_h5ad(design, root / 'input.h5ad', root / 'aggregation',
                           expected_sha256=sha(root / 'input.h5ad'), matrix='X', reserve_bytes=0,
                           sample_covariates=data.get('sample_covariates'))
    backed = ad.read_h5ad(root / 'aggregation/counts.h5ad')
    np.testing.assert_array_equal(backed.X, [s['counts'] for s in pb['samples']])
    assert list(backed.var_names) == pb['genes']
    assert list(backed.obs_names) == [s['id'] for s in pb['samples']]
    summary = load_json(root / 'aggregation/metadata.json')
    assert summary['excluded_genes'] == pb['excluded_genes']
    receipt = {'status': 'PASS', 'input_shape': list(counts.shape), 'output_shape': list(backed.shape),
               'source_data_sha256': sha(source / 'data.json'), 'source_design_sha256': sha(source / 'design.json'),
               'source_provenance': data['provenance'], 'raw_source_revalidated': False,
               'all_aggregate_counts_and_identities_equal': True, 'backend_fits': 0,
               'independent_expert_validation': 'NOT_ESTABLISHED', 'biological_validity': 'NOT_ESTABLISHED'}
    write_json(root / 'acceptance.json', receipt)
    if args.fit:
        legacy = fit_reference(design, data)
        fitted = fit_backed_reference(design, root / 'aggregation', suite_digest(result), max_fit_bytes=2*1024**3)
        write_json(root / 'backed-result.json', fitted)
        fields = ('method', 'normalization', 'design_matrix', 'testing_family', 'results', 'conclusion_scope', 'uncertainty')
        differences = compare_json({k: fitted[k] for k in fields}, {k: legacy[k] for k in fields}, 1e-7, 1e-6)
        receipt.update(backend_fits=2, fit_difference_paths=differences,
                       fitted_genes=len(fitted['results']), status='PASS' if not differences else 'FAIL',
                       result_json_bytes=(root / 'backed-result.json').stat().st_size)
        write_json(root / 'acceptance.json', receipt)
        if differences:
            raise RuntimeError('Backed fit differs from legacy method')
    print(json.dumps(receipt, ensure_ascii=True, allow_nan=False))


if __name__ == '__main__':
    main()
