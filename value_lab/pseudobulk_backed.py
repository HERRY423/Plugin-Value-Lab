"""Out-of-core raw-count aggregation; HDF5 carries arrays, JSON carries receipts.

Supports canonical CSR/CSC and dense h5ad X or an explicitly named counts layer.
No implicit normalization, cell filtering, replicate pooling, or backend fitting.
"""
from collections import defaultdict
from pathlib import Path
import sqlite3
import time

from .artifacts import sha
from .core import ValidationError, suite_digest, write_json
from .pseudobulk import validate_design
from .science_storage import disk_preflight, stream_file

I64 = 2**63 - 1


def _deps():
    try:
        import h5py
        import numpy as np
    except ImportError as exc:
        raise ValidationError('Backed counts require the optional science dependencies (h5py/numpy)') from exc
    return h5py, np


def _node(root, path):
    """Do not follow HDF5 external/soft links, VDS or external raw storage."""
    h5py, _ = _deps()
    node = root
    for part in path.split('/'):
        if not part or part in ('.', '..') or not isinstance(node, h5py.Group):
            raise ValidationError('Invalid HDF5 data path')
        if not isinstance(node.get(part, getlink=True), h5py.HardLink):
            raise ValidationError('Missing or linked HDF5 field: ' + path)
        node = node[part]
        if isinstance(node, h5py.Dataset) and (node.is_virtual or node.external):
            raise ValidationError('HDF5 data must be self-contained')
    return node


def _text(value):
    return value.decode('utf-8') if isinstance(value, bytes) else str(value)


def _nullable_strings(node):
    h5py, _ = _deps()
    values, mask = _node(node, 'values'), _node(node, 'mask')
    if (not isinstance(values, h5py.Dataset) or not isinstance(mask, h5py.Dataset)
            or len(values.shape) != 1 or mask.shape != values.shape or mask.dtype.kind != 'b'
            or h5py.check_string_dtype(values.dtype) is None):
        raise ValidationError('Malformed nullable string identity column')
    return values, mask


def _read_string_array(node, selection):
    h5py, np = _deps()
    if isinstance(node, h5py.Group):
        if _text(node.attrs.get('encoding-type', '')) != 'nullable-string-array':
            raise ValidationError('Unsupported string identity encoding')
        node, mask = _nullable_strings(node)
        if np.any(mask[selection]):
            raise ValidationError('Missing string identity; correct missing labels upstream')
    if len(node.shape) != 1 or h5py.check_string_dtype(node.dtype) is None:
        raise ValidationError('Identity columns must contain strings')
    return node.asstr()[selection].tolist()


def _strings(node, start, end):
    h5py, np = _deps()
    if isinstance(node, h5py.Dataset) or _text(node.attrs.get('encoding-type', '')) == 'nullable-string-array':
        values = _read_string_array(node, slice(start, end))
    elif _text(node.attrs.get('encoding-type', '')) == 'categorical':
        codes, categories = _node(node, 'codes'), _node(node, 'categories')
        if not isinstance(codes, h5py.Dataset) or len(codes.shape) != 1 or codes.dtype.kind not in 'iu':
            raise ValidationError('Malformed categorical identity column')
        selected = codes[start:end]
        if np.any(selected < 0) or np.any(selected >= _length(categories)):
            raise ValidationError('Missing or invalid categorical identity')
        used = np.unique(selected)
        labels = dict(zip(map(int, used), _read_string_array(categories, used)))
        values = [labels[int(i)] for i in selected]
    else:
        raise ValidationError('Unsupported identity encoding')
    if any(not isinstance(v, str) or not v.strip() or len(v.encode('utf-8')) > 4096 for v in values):
        raise ValidationError('Identity must be a nonempty UTF-8 string of at most 4096 bytes')
    return values


def _length(node):
    h5py, _ = _deps()
    if isinstance(node, h5py.Group):
        kind = _text(node.attrs.get('encoding-type', ''))
        if kind == 'categorical':
            node = _node(node, 'codes')
        elif kind == 'nullable-string-array':
            node, _ = _nullable_strings(node)
        else:
            raise ValidationError('Unsupported identity encoding')
    if not isinstance(node, h5py.Dataset):
        raise ValidationError('Identity column must be an array')
    if len(node.shape) != 1:
        raise ValidationError('Identity column must be one-dimensional')
    return node.shape[0]


def _index(group):
    name = group.attrs.get('_index')
    if name is None:
        raise ValidationError('Missing AnnData index declaration')
    return _node(group, _text(name))


def _counts(values):
    _, np = _deps()
    if values.dtype.kind not in 'iuf' or not np.all(np.isfinite(values)):
        raise ValidationError('Counts must be finite raw integers, not booleans')
    if np.any(values < 0) or np.any(values > 2**31 - 1) or np.any(values != np.floor(values)):
        raise ValidationError('Counts must be nonnegative raw integers <= 2**31-1')
    return values.astype('int64', copy=False)


def _blocks(matrix, shape, block_entries):
    """Yield bounded COO blocks, including validation of the entire sparse layout."""
    h5py, np = _deps()
    if isinstance(matrix, h5py.Dataset):
        if matrix.shape != shape:
            raise ValidationError('Matrix and obs/var shapes differ')
        columns = min(shape[1], block_entries)
        rows = max(1, block_entries // columns)
        for start in range(0, shape[0], rows):
            stop = min(shape[0], start + rows)
            for left in range(0, shape[1], columns):
                right = min(shape[1], left + columns)
                values = _counts(matrix[start:stop, left:right])
                r, c = np.nonzero(values)
                yield r + start, c + left, values[r, c]
        return
    kind = _text(matrix.attrs.get('encoding-type', ''))
    if kind not in ('csr_matrix', 'csc_matrix') or tuple(matrix.attrs.get('shape', ())) != shape:
        raise ValidationError('Expected dense, canonical CSR or canonical CSC with matching shape')
    data, indices, indptr = [_node(matrix, k) for k in ('data', 'indices', 'indptr')]
    major_size, minor_size = shape if kind == 'csr_matrix' else shape[::-1]
    if (len(data.shape) != 1 or indices.shape != data.shape or indptr.shape != (major_size + 1,)
            or indices.dtype.kind not in 'iu' or indptr.dtype.kind not in 'iu'):
        raise ValidationError('Malformed sparse array dimensions or indices')
    if int(indptr[0]) != 0 or int(indptr[-1]) != len(data):
        raise ValidationError('Sparse endpoints do not cover all count entries')
    for start in range(0, major_size, 4096):
        stop = min(major_size, start + 4096)
        pointers = indptr[start:stop + 1]
        if np.any(pointers[1:] < pointers[:-1]) or np.any(pointers > len(data)):
            raise ValidationError('Invalid sparse pointers')
        previous = None
        for left in range(int(pointers[0]), int(pointers[-1]), block_entries):
            right = min(int(pointers[-1]), left + block_entries)
            minor = indices[left:right]
            if np.any(minor < 0) or np.any(minor >= minor_size):
                raise ValidationError('Sparse index out of range')
            major = np.searchsorted(pointers, np.arange(left, right), side='right') - 1 + start
            if (np.any((major[1:] == major[:-1]) & (minor[1:] <= minor[:-1]))
                    or previous is not None and major[0] == previous[0] and minor[0] <= previous[1]):
                raise ValidationError('Sparse indices must be canonical: sorted, unique per row/column')
            previous = (int(major[-1]), int(minor[-1]))
            values = _counts(data[left:right])
            yield (major, minor, values) if kind == 'csr_matrix' else (minor, major, values)


def _write_strings(group, name, values):
    h5py, _ = _deps()
    ds = group.create_dataset(name, data=values, dtype=h5py.string_dtype('utf-8'))
    ds.attrs.update({'encoding-type': 'string-array', 'encoding-version': '0.2.0'})


def _frame(root, name, ids, columns):
    h5py, _ = _deps()
    group = root.create_group(name)
    group.attrs.update({'encoding-type': 'dataframe', 'encoding-version': '0.2.0', '_index': '_index'})
    group.attrs.create('column-order', list(columns), dtype=h5py.string_dtype('utf-8'))
    _write_strings(group, '_index', ids)
    for key, values in columns.items():
        if values and isinstance(values[0], str):
            _write_strings(group, key, values)
        else:
            ds = group.create_dataset(key, data=values)
            ds.attrs.update({'encoding-type': 'array', 'encoding-version': '0.2.0'})


def aggregate_h5ad(design, source, output, *, expected_sha256, matrix='layers/counts',
                   obs_columns=None, selection='strict', sample_covariates=None,
                   block_entries=262144, metadata_mb=128, max_disk_bytes=4 * 1024**3,
                   reserve_bytes=256 * 1024**2):
    """Aggregate to a standard h5ad using disk arrays and a disk identity index.

    Working arrays scale with block_entries and one gene vector, not cells*genes.
    Metadata has a separate explicit budget. Published receipt is written last;
    incomplete attempts cannot be mistaken for a complete artifact. No retry.
    """
    validate_design(design)
    if selection not in ('strict', 'design'):
        raise ValidationError('Selection must be strict or explicitly design')
    for name, value, lo, hi in [('block_entries', block_entries, 1, 1048576),
                               ('metadata_mb', metadata_mb, 1, 4096),
                               ('max_disk_bytes', max_disk_bytes, 1, 16 * 1024**4),
                               ('reserve_bytes', reserve_bytes, 0, 16 * 1024**4)]:
        if type(value) is not int or not lo <= value <= hi:
            raise ValidationError('Invalid ' + name)
    columns = obs_columns or {k: k for k in ('sample', 'donor', 'condition', 'cell_type')}
    if (not isinstance(columns, dict) or set(columns) != {'sample', 'donor', 'condition', 'cell_type'}
            or any(not isinstance(v, str) or '/' in v or not v for v in columns.values())):
        raise ValidationError('Declare the four obs identity columns')
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ValidationError('A frozen source SHA-256 is required')
    source, root = Path(source).absolute(), Path(output).absolute()
    if source.resolve().is_relative_to(root.resolve()):
        raise ValidationError('Output must not contain the source')
    source_info = stream_file(source, expected=expected_sha256, maximum=16 * 1024**4)
    h5py, np = _deps()
    root.mkdir(parents=True, exist_ok=False)
    receipt = {'format': 'pvl-backed-pseudobulk-1', 'status': 'STARTED',
               'input': source_info, 'design_sha256': suite_digest(design),
               'matrix': matrix, 'obs_columns': columns, 'selection': selection,
               'block_entries': block_entries, 'metadata_mb': metadata_mb,
               'max_disk_bytes': max_disk_bytes, 'reserve_bytes': reserve_bytes,
               'sample_covariates_sha256': suite_digest(sample_covariates),
               'analysis_unit': 'declared_donor', 'donor_identity': 'DECLARED_NOT_AUTHENTICATED',
               'scientific_validity': 'NOT_ESTABLISHED', 'automatic_retry': False,
               'backend_fit': False, 'files': {}}
    write_json(root / 'receipt.json', receipt)
    started = time.monotonic()
    db = None
    try:
        db = sqlite3.connect(root / 'identities.sqlite')
        db.execute('PRAGMA cache_size=-4096')
        db.execute('PRAGMA journal_mode=OFF')
        db.execute('CREATE TABLE cells (id TEXT PRIMARY KEY) WITHOUT ROWID')
        def space():
            if sum(p.stat().st_size for p in root.iterdir() if p.is_file()) > max_disk_bytes:
                raise ValidationError('Aggregation exceeds declared disk budget')
            disk_preflight(root, 0, reserve_bytes)
        with h5py.File(source, 'r', rdcc_nbytes=1048576) as src, h5py.File(root / 'working.h5', 'w', rdcc_nbytes=1048576) as work:
            obs, var = _node(src, 'obs'), _node(src, 'var')
            cell_ids, gene_ids = _index(obs), _index(var)
            n_cells, n_genes = _length(cell_ids), _length(gene_ids)
            if not n_cells or not n_genes:
                raise ValidationError('Empty counts are not an analysis')
            # One gene vector and its identifiers must fit the declared metadata budget.
            metadata_used = n_genes * 160
            genes = []
            for start in range(0, n_genes, 4096):
                block = _strings(gene_ids, start, min(n_genes, start + 4096))
                metadata_used += sum(len(v.encode('utf-8')) * 4 for v in block)
                if metadata_used > metadata_mb * 1048576:
                    raise ValidationError('Gene metadata exceeds metadata budget')
                genes.extend(block)
            if len(set(genes)) != n_genes:
                raise ValidationError('Duplicate gene identity')
            nodes = {key: _node(obs, value) for key, value in columns.items()}
            if any(_length(v) != n_cells for v in nodes.values()):
                raise ValidationError('Cell metadata length differs from matrix')
            disk_preflight(root, n_cells * 8, reserve_bytes)
            mapping = work.create_dataset('sample_index', (n_cells,), dtype='int64', chunks=True)
            groups, pairs, selected_cells = {}, defaultdict(dict), 0
            for start in range(0, n_cells, 4096):
                stop = min(n_cells, start + 4096)
                identities = _strings(cell_ids, start, stop)
                try:
                    db.executemany('INSERT INTO cells VALUES (?)', ((v,) for v in identities))
                    db.commit()
                except sqlite3.IntegrityError as exc:
                    raise ValidationError('Duplicate cell identity') from exc
                fields = {key: _strings(node, start, stop) for key, node in nodes.items()}
                assigned = np.full(stop - start, -1, dtype='int64')
                for i in range(stop - start):
                    sample, donor, condition, cell_type = (fields[k][i] for k in ('sample', 'donor', 'condition', 'cell_type'))
                    if cell_type != design['cell_type'] or condition not in (design['control'], design['treatment']):
                        if selection == 'strict':
                            raise ValidationError('Unexpected cell type/condition; freeze explicit design selection')
                        continue
                    if sample not in groups:
                        metadata_used += 1024 + 4 * sum(len(v.encode('utf-8')) for v in (sample, donor, condition))
                        if metadata_used > metadata_mb * 1048576:
                            raise ValidationError('Sample metadata exceeds metadata budget')
                        groups[sample] = {'id': sample, 'donor': donor, 'condition': condition,
                                          'cells': 0, 'index': len(groups)}
                    row = groups[sample]
                    if (row['donor'], row['condition']) != (donor, condition):
                        raise ValidationError('A sample maps to conflicting donors/conditions')
                    if condition in pairs[donor] and pairs[donor][condition] != sample:
                        raise ValidationError('Multiple samples per donor-condition require a technical-replicate contract')
                    pairs[donor][condition] = sample
                    row['cells'] += 1
                    selected_cells += 1
                    assigned[i] = row['index']
                mapping[start:stop] = assigned
                work.flush()
                space()
            if len(pairs) < 3 or any(set(v) != {design['control'], design['treatment']} for v in pairs.values()):
                raise ValidationError('At least three complete donor pairs required')
            if any(s['cells'] < design['min_cells'] for s in groups.values()):
                raise ValidationError('Sample below frozen minimum cell count')
            samples = [groups[k] for k in sorted(groups)]
            if design['format'] == 'pvl-pseudobulk-design-2':
                from .pseudobulk_design import attach_covariates, design_matrix
                attach_covariates(design, {'sample_covariates': sample_covariates}, samples)
                receipt['design_matrix'] = design_matrix(design, samples)
            elif sample_covariates is not None:
                raise ValidationError('Sample covariates require design v2')
            # Worst-case working and final dense pseudobulk arrays, never cells*genes.
            required = len(groups) * n_genes * 16 + n_cells * 8
            used = sum(p.stat().st_size for p in root.iterdir() if p.is_file())
            if required + used > max_disk_bytes:
                raise ValidationError('Pseudobulk arrays exceed declared disk budget')
            disk_preflight(root, required, reserve_bytes)
            counts = work.create_dataset('counts', (len(groups), n_genes), dtype='int64',
                                         chunks=(1, min(n_genes, 8192)), fillvalue=0)
            matrix_node = _node(src, matrix)
            nnz = 0
            for rows, cols, values in _blocks(matrix_node, (n_cells, n_genes), block_entries):
                nnz += int(np.count_nonzero(values))
                unique, inverse = np.unique(rows, return_inverse=True)
                assignments = mapping[unique][inverse] if len(unique) else np.empty(0, dtype='int64')
                for group in np.unique(assignments):
                    if group < 0:
                        continue
                    chosen = assignments == group
                    add = np.zeros(n_genes, dtype='int64')
                    # Each block has <= 2**20 entries, so its sum cannot overflow int64.
                    np.add.at(add, cols[chosen], values[chosen])
                    current = counts[int(group), :]
                    if np.any(current > I64 - add):
                        raise ValidationError('Pseudobulk int64 overflow')
                    counts[int(group), :] = current + add
                work.flush()
                space()
            # Saturating totals avoid overflow in the gene-filter reduction.
            threshold = design['min_total_count']
            if threshold > I64:
                raise ValidationError('Gene filter threshold exceeds int64')
            totals = np.zeros(n_genes, dtype='int64')
            for i in range(len(groups)):
                totals += np.minimum(counts[i, :], threshold - totals)
            kept = sorted(np.flatnonzero(totals >= threshold).tolist(), key=genes.__getitem__)
            if not kept:
                raise ValidationError('No genes pass the frozen filter')
            retained = set(kept)
            with h5py.File(root / 'counts.h5ad.partial', 'w') as dest:
                dest.attrs.update({'encoding-type': 'anndata', 'encoding-version': '0.1.0'})
                x = dest.create_dataset('X', (len(samples), len(kept)), dtype='int64',
                                        chunks=(1, min(len(kept), 8192)), compression='gzip')
                x.attrs.update({'encoding-type': 'array', 'encoding-version': '0.2.0'})
                for i, sample in enumerate(samples):
                    values = counts[sample['index'], :][kept]
                    if not np.any(values):
                        raise ValidationError('Zero-library pseudobulk sample')
                    x[i, :] = values
                metadata = {k: [s[k] for s in samples] for k in ('donor', 'condition', 'cells')}
                for name in design.get('covariates', {}):
                    metadata[name] = [s['covariates'][name] for s in samples]
                _frame(dest, 'obs', [s['id'] for s in samples], metadata)
                _frame(dest, 'var', [genes[i] for i in kept], {})
            space()
            summary = {'genes': [genes[i] for i in kept], 'samples': [{k: v for k, v in s.items() if k != 'index'} for s in samples],
                       'excluded_genes': sorted(g for i, g in enumerate(genes) if i not in retained),
                       'aggregation': 'sum_raw_integer_counts_by_sample', 'independent_units': len(pairs)}
            write_json(root / 'metadata.json', summary)
            receipt.update(input_shape=[n_cells, n_genes], output_shape=[len(samples), len(kept)],
                           selected_cells=selected_cells, excluded_cells=n_cells - selected_cells,
                           nonzero_entries=nnz, independent_units=len(pairs))
        # Detect source mutation during HDF5 reads before publishing any success.
        stream_file(source, expected=expected_sha256, maximum=source_info['bytes'])
        db.close()
        db = None
        (root / 'working.h5').unlink()
        (root / 'identities.sqlite').unlink()
        (root / 'counts.h5ad.partial').rename(root / 'counts.h5ad')
        receipt['files'] = {n: sha(root / n) for n in ('counts.h5ad', 'metadata.json')}
        receipt.update(status='COMPLETE', elapsed_seconds=time.monotonic() - started)
    except Exception as exc:
        receipt.update(status='FAILED', error=type(exc).__name__ + ': ' + str(exc)[:500],
                       elapsed_seconds=time.monotonic() - started)
        write_json(root / 'receipt.json', receipt)
        raise
    finally:
        if db is not None:
            db.close()
    write_json(root / 'receipt.json', receipt)
    return receipt


def compare_counts(observed, expected):
    """Exact, ordered pseudobulk h5ad X/obs/var comparison; no tolerances.

    Only accepts the dense integer pseudobulk artifact produced above. Other
    AnnData fields are rejected rather than silently ignored. It is not a
    general comparator for embeddings, floating normalized values or all h5ad.
    """
    h5py, np = _deps()
    differences = []
    with h5py.File(observed, 'r') as a, h5py.File(expected, 'r') as b:
        for f in (a, b):
            if set(f) != {'X', 'obs', 'var'}:
                raise ValidationError('Counts comparator accepts exactly X/obs/var')
            x = _node(f, 'X')
            if not isinstance(x, h5py.Dataset) or len(x.shape) != 2 or x.dtype.kind not in 'iu':
                raise ValidationError('Counts comparator requires dense integer X')
            if _length(_index(_node(f, 'obs'))) != x.shape[0] or _length(_index(_node(f, 'var'))) != x.shape[1]:
                raise ValidationError('Counts comparator shape/identity mismatch')
        if a['X'].shape != b['X'].shape:
            return ['/X/shape']
        for name in ('obs', 'var'):
            ga, gb = _node(a, name), _node(b, name)
            if set(ga) != set(gb) or _text(ga.attrs.get('_index')) != _text(gb.attrs.get('_index')):
                return ['/' + name]
            if list(ga.attrs.get('column-order', [])) != list(gb.attrs.get('column-order', [])):
                return ['/' + name + '/column-order']
            for key in ga:
                da, db = _node(ga, key), _node(gb, key)
                if not isinstance(da, h5py.Dataset) or not isinstance(db, h5py.Dataset) or da.shape != db.shape or len(da.shape) != 1:
                    raise ValidationError('Counts comparator requires plain metadata arrays')
                for start in range(0, len(da), 4096):
                    av, bv = da[start:start+4096], db[start:start+4096]
                    if da.dtype.kind != db.dtype.kind or not np.array_equal(av, bv):
                        return ['/' + name + '/' + key]
        for i in range(a['X'].shape[0]):
            for j in range(0, a['X'].shape[1], 262144):
                av, bv = a['X'][i, j:j+262144], b['X'][i, j:j+262144]
                if np.any(av < 0) or np.any(bv < 0):
                    raise ValidationError('Negative pseudobulk counts')
                if not np.array_equal(av, bv):
                    differences.append('/X/' + str(i) + '/' + str(j))
                    if len(differences) >= 100:
                        return differences
    return differences


def fit_backed_reference(design, directory, expected_receipt_id, *, max_fit_bytes):
    """Fit the existing pinned PyDESeq2 method to the reduced sample matrix.

    PyDESeq2 itself is in-memory. This explicit gate reserves a conservative 40x
    dense-array estimate; actual enforcement requires execution-2 OS limits.
    Counts stay in the referenced h5ad, never duplicated into result JSON.
    """
    from .core import load_json
    from .artifacts import confined
    from .pseudobulk import _fit_aggregated
    validate_design(design)
    root = Path(directory)
    receipt = load_json(root / 'receipt.json')
    if (suite_digest(receipt) != expected_receipt_id or receipt.get('status') != 'COMPLETE'
            or receipt.get('format') != 'pvl-backed-pseudobulk-1'
            or receipt.get('design_sha256') != suite_digest(design)
            or set(receipt.get('files', {})) != {'counts.h5ad', 'metadata.json'}):
        raise ValidationError('Backed aggregation commitment changed or incomplete')
    if type(max_fit_bytes) is not int or max_fit_bytes < 1:
        raise ValidationError('Declare a positive fitting-memory budget')
    for name, digest in receipt['files'].items():
        stream_file(confined(root, name), expected=digest, maximum=16 * 1024**4)
    h5py, np = _deps()
    with h5py.File(confined(root, 'counts.h5ad'), 'r') as f:
        x = _node(f, 'X')
        if len(x.shape) != 2 or x.dtype.kind not in 'iu' or not all(x.shape):
            raise ValidationError('Expected dense integer pseudobulk counts')
        estimate = x.shape[0] * x.shape[1] * 8 * 40 + 256 * 1048576
        if estimate > max_fit_bytes:
            raise ValidationError('PyDESeq2 fitting estimate exceeds explicit memory budget; aggregation remains usable')
        summary_path = confined(root, 'metadata.json')
        if summary_path.stat().st_size > 32 * 1048576:
            raise ValidationError('Fitting metadata exceeds small-JSON boundary')
        pb = load_json(summary_path)
        if (len(pb['samples']), len(pb['genes'])) != x.shape:
            raise ValidationError('Backed summary shape mismatch')
        if (_strings(_index(_node(f, 'obs')), 0, x.shape[0]) != [s['id'] for s in pb['samples']]
                or _strings(_index(_node(f, 'var')), 0, x.shape[1]) != pb['genes']):
            raise ValidationError('Backed summary identities differ from counts')
        values = x[:]
        if np.any(values < 0) or np.any(values > I64):
            raise ValidationError('Invalid aggregate counts')
    for i, row in enumerate(pb['samples']):
        row['counts'] = values[i, :]
    result = _fit_aggregated(design, pb, counts_reference={
        'format': 'pvl-backed-counts-reference-1', 'receipt_sha256': expected_receipt_id,
        'files': receipt['files'], 'shape': receipt['output_shape'],
        'analysis_unit': 'declared_donor', 'independent_units': receipt['independent_units']})
    result['resource_estimate'] = {'fit_bytes': estimate, 'budget_bytes': max_fit_bytes,
                                   'enforcement': 'ESTIMATE_ONLY_UNLESS_RUN_IN_OS_SANDBOX'}
    return result
