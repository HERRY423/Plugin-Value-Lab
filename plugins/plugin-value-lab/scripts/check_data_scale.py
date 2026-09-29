"""Independent arithmetic oracle at 50k cells x 20k genes; no biological claim."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.artifacts import sha
from value_lab.core import load_json, suite_digest, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--cells', type=int, default=50000)
    args = parser.parse_args()
    import h5py
    import numpy as np
    import psutil
    from value_lab.pseudobulk_backed import _frame
    from value_lab.science_storage import disk_preflight
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    cells, genes, samples, width = args.cells, 20000, 200, 200
    if cells < 200 or cells % samples:
        raise ValueError('Cells must be a positive multiple of 200')
    disk_preflight(root, cells * width * 8 + cells * 256 + samples * genes * 16, 256*1048576)
    receipt = {'status': 'STARTED', 'synthetic': True, 'independent_expert_validation': 'NOT_ESTABLISHED'}
    write_json(root / 'acceptance.json', receipt)
    source = root / 'input.h5ad'
    with h5py.File(source, 'w') as f:
        f.attrs.update({'encoding-type': 'anndata', 'encoding-version': '0.1.0'})
        group = f.create_group('X')
        group.attrs.update({'encoding-type': 'csr_matrix', 'encoding-version': '0.1.0', 'shape': [cells, genes]})
        data = group.create_dataset('data', (cells*width,), dtype='int32')
        indices = group.create_dataset('indices', (cells*width,), dtype='int32')
        group.create_dataset('indptr', data=np.arange(cells + 1, dtype='int64') * width)
        for start in range(0, cells, 1000):
            stop = min(cells, start + 1000)
            cols = ((np.arange(start, stop)[:, None] % 100) * width + np.arange(width)[None, :]).astype('int32')
            indices[start*width:stop*width] = cols.ravel()
            data[start*width:stop*width] = (cols % 5 + 1).ravel()
        _frame(f, 'obs', ['cell' + str(i) for i in range(cells)], {
            'sample': [f's{i % samples:03}' for i in range(cells)],
            'donor': [f'd{(i % samples)//2:03}' for i in range(cells)],
            'condition': ['ctrl' if i % 2 == 0 else 'stim' for i in range(cells)],
            'cell_type': ['synthetic'] * cells})
        _frame(f, 'var', [f'g{i:05}' for i in range(genes)], {})
    design = {'format': 'pvl-pseudobulk-design-1', 'task_mode': 'fixed_method', 'cell_type': 'synthetic',
              'control': 'ctrl', 'treatment': 'stim', 'min_cells': 1, 'min_total_count': 1,
              'backend_version': '0.5.4', 'reference_workflow': 'Manufactured scale arithmetic only'}
    write_json(root / 'design.json', design)
    plan = {'format': 'pvl-backed-counts-plan-1',
            'design': {'path': 'design.json', 'sha256': sha(root / 'design.json')},
            'data': {'path': source.name, 'sha256': sha(source)}, 'matrix': 'X',
            'obs_columns': {k: k for k in ('sample', 'donor', 'condition', 'cell_type')},
            'selection': 'strict', 'sample_covariates': None, 'block_entries': 262144,
            'metadata_mb': 64, 'max_disk_bytes': 256*1048576, 'reserve_bytes': 256*1048576}
    write_json(root / 'plan.json', plan)
    started, peak = time.monotonic(), 0
    with (root / 'stdout.json').open('wb') as out, (root / 'stderr.txt').open('wb') as err:
        child = subprocess.Popen([sys.executable, str(ROOT / 'scripts/science_scale.py'), str(root / 'plan.json'),
                                  '--expected-id', suite_digest(plan), '--inputs', str(root), '--output', str(root / 'result')],
                                  stdout=out, stderr=err)
        process = psutil.Process(child.pid)
        while child.poll() is None:
            try:
                mem = process.memory_info()
                peak = max(peak, getattr(mem, 'peak_wset', mem.rss), mem.rss)
            except psutil.NoSuchProcess:
                pass
            time.sleep(.02)
    receipt.update(returncode=child.returncode, elapsed_seconds=time.monotonic()-started,
                   peak_rss_bytes=peak, memory_measurement='child RSS sampled every 20 ms; Windows peak_wset when available',
                   input_shape=[cells, genes], input_bytes=source.stat().st_size,
                   input_nonzeros=cells*width, dense_input_int64_bytes=cells*genes*8,
                   output_shape=[samples, genes], aggregate_elements=samples*genes,
                   plan_sha256=suite_digest(plan), source_sha256=sha(source))
    if child.returncode:
        receipt['status'] = 'FAILED'
        write_json(root / 'acceptance.json', receipt)
        raise RuntimeError('Aggregation failed; inspect stderr/stdout')
    # Closed-form oracle does not reuse aggregation, sparse traversal or legacy code.
    with h5py.File(root / 'result/counts.h5ad', 'r') as f:
        assert f['X'].shape == (samples, genes)
        assert f['var/_index'].asstr()[:].tolist() == [f'g{i:05}' for i in range(genes)]
        assert f['obs/_index'].asstr()[:].tolist() == [f's{i:03}' for i in range(samples)]
        for sample in range(samples):
            expected = np.zeros(genes, dtype='int64')
            start = (sample % 100)*width
            expected[start:start+width] = (np.arange(start, start+width) % 5 + 1) * (cells//samples)
            np.testing.assert_array_equal(f['X'][sample, :], expected)
        assert int(f['obs/cells'][:].sum()) == cells
    # Standard ecosystem interoperability, without requiring the whole matrix in memory.
    import anndata as ad
    backed = ad.read_h5ad(root / 'result/counts.h5ad', backed='r')
    assert backed.shape == (samples, genes)
    backed.file.close()
    receipt.update(status='PASS', exact_full_matrix_oracle=True, anndata_backed_read=True,
                   aggregation_receipt=load_json(root / 'result/receipt.json'),
                   scientific_validity='NOT_ESTABLISHED', real_biological_dataset=False)
    write_json(root / 'acceptance.json', receipt)
    print(json.dumps(receipt, ensure_ascii=True, allow_nan=False))


if __name__ == '__main__':
    main()
