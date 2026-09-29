"""Small public Python API. Local files in, typed results and reviewable plans out.

This adapter simplifies mechanics; biological choices are explicit and existing
validators remain authoritative. Importing it requires only the standard library.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import platform
from typing import Callable

from . import __version__
from .artifacts import confined, sha
from .core import ValidationError, load_json, suite_digest, write_json
from .science_storage import stream_file

__all__ = ['PVLError', 'RunResult', 'inspect_counts', 'aggregate_counts', 'check_bh', 'verify_run', 'demo', 'doctor']


class PVLError(ValueError):
    """Stable error code plus a concrete recovery hint; original cause is chained."""
    def __init__(self, code: str, message: str, hint: str):
        super().__init__(message)
        self.code, self.hint = code, hint

    def to_dict(self):
        return {'status': 'ERROR', 'code': self.code, 'message': str(self), 'hint': self.hint}


@dataclass(frozen=True)
class RunResult:
    directory: Path
    status: str
    commitment: str
    reused: bool = False

    @property
    def report(self) -> Path:
        return self.directory / 'REPORT.md'

    @property
    def counts(self) -> Path | None:
        path = self.directory / 'aggregation/counts.h5ad'
        return path if path.is_file() else None

    @property
    def manifest(self) -> dict:
        return _read_manifest(self.directory)

    def to_dict(self) -> dict:
        return {'status': self.status, 'directory': str(self.directory), 'report': str(self.report),
                'counts': str(self.counts) if self.counts else None,
                'commitment': self.commitment, 'reused': self.reused}


def _translate(exc):
    if isinstance(exc, PVLError):
        return exc
    text = str(exc)
    if isinstance(exc, FileNotFoundError):
        return PVLError('INPUT_NOT_FOUND', text, 'Check the input path; quote paths containing spaces. No data was downloaded.')
    if isinstance(exc, FileExistsError):
        return PVLError('OUTPUT_EXISTS', text, 'Use reuse=True / --reuse for a verified completed run, or choose a new output directory.')
    if isinstance(exc, PermissionError):
        return PVLError('PERMISSION_DENIED', text, 'Choose a readable input and a writable output directory; original files are preserved.')
    if isinstance(exc, ImportError) or 'optional science dependencies' in text:
        return PVLError('MISSING_DEPENDENCY', text, 'Install with: python -m pip install "plugin-value-lab[science]" (or ".[science]" from a checkout).')
    for fragment, code, hint in [
        ('disk', 'DISK_BUDGET', 'Choose an output drive with space, or review disk_budget and reserve_bytes. Nothing is truncated.'),
        ('metadata budget', 'METADATA_BUDGET', 'Increase metadata_mb within available RAM; the count matrix remains on disk.'),
        ('complete donor pairs', 'INCOMPLETE_PAIRS', 'Check donor/condition columns and the selected population. At least three complete pairs are required.'),
        ('minimum cell count', 'TOO_FEW_CELLS', 'Review the declared min_cells threshold and sample coverage; no samples are silently dropped.'),
        ('Unexpected cell type', 'SELECTION_REQUIRED', 'Use selection="design" / --select-design only if you intend to select the declared cell type and contrast.'),
        ('raw integer', 'NOT_RAW_COUNTS', 'Select a matrix containing unnormalised, nonnegative integer counts; no rounding or normalization is performed.'),
        ('canonical', 'SPARSE_LAYOUT', 'Prepare a sorted, duplicate-free sparse matrix explicitly, preserve its provenance, then rerun.'),
        ('Duplicate', 'DUPLICATE_IDENTITY', 'Correct duplicate cell/gene identities upstream; identities will not be renamed automatically.'),
        ('Pinned file changed', 'INPUT_CHANGED', 'The input changed during processing. Keep it immutable and start a new run.'),
    ]:
        if fragment.lower() in text.lower():
            return PVLError(code, text, hint)
    return PVLError('VALIDATION_FAILED' if isinstance(exc, ValueError) else 'IO_ERROR', text,
                    'Review the message and the saved plan. Failed attempts are retained; use a new output directory after correcting the input.')


def _dependencies():
    try:
        from .pseudobulk_backed import _deps
        return _deps()
    except (ImportError, ValueError) as exc:
        raise _translate(exc) from exc


def doctor() -> dict:
    """Capability-scoped, read-only checks; never launch hosts or install packages."""
    modules = {n: importlib.util.find_spec(n) is not None for n in ('h5py', 'numpy', 'pydeseq2')}
    return {'version': __version__, 'python': platform.python_version(),
            'ready': {'artifact_checks': True, 'counts_aggregation': modules['h5py'] and modules['numpy'],
                      'reference_fitting': all(modules.values())},
            'dependency_presence_only': True, 'dependencies': modules,
            'install_counts': 'python -m pip install "plugin-value-lab[science]"',
            'network_calls': 0, 'host_authentication_required': False}


def inspect_counts(source: str | Path) -> dict:
    """Inspect HDF5 headers only. No full matrix read or raw-count certification."""
    try:
        from .pseudobulk_backed import _node, _index, _length, _text
        h5py, _ = _dependencies()
        source = Path(source).expanduser().absolute()
        from .science_storage import regular
        regular(source, 16 * 1024**4)
        with h5py.File(source, 'r') as f:
            obs, var = _node(f, 'obs'), _node(f, 'var')
            shape = [_length(_index(obs)), _length(_index(var))]
            paths = ['X'] if 'X' in f else []
            if 'layers' in f:
                layers = _node(f, 'layers')
                if len(layers) > 1000:
                    raise ValidationError('Too many layers to inspect; choose a bounded input')
                paths.extend('layers/' + key for key in layers)
            matrices = {}
            for name in paths:
                node = _node(f, name)
                matrices[name] = {'shape': list(node.shape) if isinstance(node, h5py.Dataset) else list(map(int, node.attrs.get('shape', []))),
                                  'storage': 'dense' if isinstance(node, h5py.Dataset) else _text(node.attrs.get('encoding-type', 'unknown'))}
            return {'shape': shape, 'bytes': source.stat().st_size, 'obs_columns': [_text(v) for v in obs.attrs.get('column-order', [])],
                    'matrices': matrices, 'raw_counts_verified': False, 'inspection': 'HEADERS_ONLY'}
    except (OSError, ValueError, ImportError, KeyError, TypeError) as exc:
        raise _translate(exc) from exc


def _engine_id():
    # Include implementation bytes, not only a version that may be unchanged.
    return suite_digest({p.name: sha(p) for p in Path(__file__).parent.glob('*.py')})


def _read_manifest(root):
    path = confined(root, 'run.json')
    if not path.is_file() or path.stat().st_size > 8 * 1048576:
        raise PVLError('INCOMPLETE_RUN', 'A complete run.json is missing or oversized.', 'Read failure.json if present; start corrected work in a new directory.')
    value = load_json(path)
    if not isinstance(value, dict) or value.get('format') != 'pvl-sdk-run-1' or value.get('state') != 'COMPLETE':
        raise PVLError('INCOMPLETE_RUN', 'This directory does not contain a complete SDK run.', 'Inspect failure.json; incomplete runs are not reused.')
    return value


def verify_run(directory: str | Path, *, expected_id: str | None = None) -> RunResult:
    """Verify retained bytes; does not re-execute analysis or establish validity.

    Supply a separately retained expected_id to anchor the manifest. The local
    COMPLETED marker otherwise detects accidental changes, not malicious edits.
    """
    try:
        root = Path(directory).expanduser().absolute()
        manifest = _read_manifest(root)
        marker = confined(root, 'COMPLETED')
        if not marker.is_file() or marker.stat().st_size > 128:
            raise PVLError('INCOMPLETE_RUN', 'Completion marker is missing.', 'The run may have been interrupted; preserve it and use a new output directory.')
        commitment = suite_digest(manifest)
        if marker.read_text(encoding='ascii').strip() != commitment or expected_id is not None and expected_id != commitment:
            raise PVLError('RESULT_CHANGED', 'Run manifest commitment does not match.', 'Restore the original manifest or rerun into a new directory; do not update hashes to conceal changes.')
        files = manifest.get('files')
        if not isinstance(files, dict) or not files or len(files) > 1000:
            raise ValidationError('Invalid artifact inventory')
        for name, digest in files.items():
            stream_file(confined(root, name), expected=digest, maximum=16 * 1024**4)
        return RunResult(root, manifest['status'], commitment)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        error = _translate(exc)
        if error.code == 'INPUT_CHANGED':
            error = PVLError('RESULT_CHANGED', str(exc), 'An output file changed. Preserve it for investigation and rerun into a new directory.')
        raise error from exc


def _begin(root, source, request, reuse):
    if source.resolve().is_relative_to(root.resolve()):
        raise PVLError('OUTPUT_OVERLAPS_INPUT', 'Output must not contain the input file.', 'Choose a separate results directory.')
    if root.exists():
        if not reuse:
            raise PVLError('OUTPUT_EXISTS', f'Output already exists: {root}', 'Use --reuse / reuse=True to verify and reuse an identical completed run, or choose a new directory.')
        result = verify_run(root)
        if result.manifest['request_sha256'] != suite_digest(request):
            raise PVLError('REQUEST_CHANGED', 'Input, settings or implementation differ from the completed run.', 'Use a new output directory. Existing results will not be overwritten.')
        return RunResult(root, result.status, result.commitment, reused=True)
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / 'plan.json', request)
    write_json(root / 'run.json', {'format': 'pvl-sdk-run-1', 'state': 'RUNNING', 'request_sha256': suite_digest(request)})
    return None


def _finish(root, request, status, summary, report):
    (root / 'REPORT.md').write_text(report, encoding='utf-8')
    files = {p.relative_to(root).as_posix(): sha(p) for p in root.rglob('*')
             if p.is_file() and p.name not in ('run.json', 'COMPLETED', 'failure.json')}
    manifest = {'format': 'pvl-sdk-run-1', 'state': 'COMPLETE', 'status': status,
                'request_sha256': suite_digest(request), 'summary': summary, 'files': files,
                'scientific_validity': 'NOT_ESTABLISHED', 'non_author_use': 'NOT_MEASURED'}
    write_json(root / 'run.json', manifest)
    commitment = suite_digest(manifest)
    (root / 'COMPLETED').write_text(commitment + '\n', encoding='ascii')
    return RunResult(root, status, commitment)


def _failed(root, request, exc):
    error = _translate(exc)
    write_json(root / 'failure.json', error.to_dict())
    write_json(root / 'run.json', {'format': 'pvl-sdk-run-1', 'state': 'FAILED',
                                  'request_sha256': suite_digest(request), 'error': error.to_dict()})
    (root / 'REPORT.md').write_text(f'# Run did not complete\n\n{error.code}: {error}\n\nNext step: {error.hint}\n', encoding='utf-8')
    return error


def aggregate_counts(source: str | Path, *, output: str | Path, cell_type: str,
                     control: str, treatment: str, matrix: str = 'layers/counts',
                     sample_key: str = 'sample', donor_key: str = 'donor',
                     condition_key: str = 'condition', cell_type_key: str = 'cell_type',
                     min_cells: int = 10, min_total_count: int = 10, selection: str = 'strict',
                     block_entries: int = 262144, metadata_mb: int = 128,
                     disk_budget: int = 4 * 1024**3, reserve_bytes: int = 256 * 1024**2,
                     reuse: bool = False, dry_run: bool = False,
                     progress: Callable[[str], None] | None = None) -> RunResult | dict:
    """One-call donor-paired raw-count aggregation, with automatic provenance.

    Biological choices are required; no model fitting or online calls. dry_run
    checks headers/configuration only; it does not validate counts or donors.
    reuse verifies every artifact plus the input/config/implementation identity.
    """
    from .pseudobulk import validate_design
    from .pseudobulk_backed import aggregate_h5ad
    source, root = Path(source).expanduser().absolute(), Path(output).expanduser().absolute()
    notify = progress or (lambda event: None)
    try:
        notify('Inspecting input headers')
        info = inspect_counts(source)
        design = {'format': 'pvl-pseudobulk-design-1', 'task_mode': 'fixed_method',
                  'cell_type': cell_type, 'control': control, 'treatment': treatment,
                  'min_cells': min_cells, 'min_total_count': min_total_count,
                  'backend_version': '0.5.4', 'reference_workflow': 'Local raw-count aggregation; no fit performed'}
        validate_design(design)
        columns = dict(sample=sample_key, donor=donor_key, condition=condition_key, cell_type=cell_type_key)
        missing = sorted(set(columns.values()) - set(info['obs_columns']))
        if missing:
            raise PVLError('MISSING_COLUMNS', 'Missing obs columns: ' + ', '.join(missing),
                           'Map sample_key/donor_key/condition_key/cell_type_key to available columns: ' + ', '.join(info['obs_columns']))
        if matrix not in info['matrices']:
            raise PVLError('MATRIX_NOT_FOUND', f'Count matrix {matrix!r} is absent.',
                           'Available matrices: ' + ', '.join(info['matrices']) + '. Select one explicitly only if it contains raw counts.')
        if info['matrices'][matrix]['shape'] != info['shape']:
            raise ValidationError('Matrix and obs/var shapes differ')
        if selection not in ('strict', 'design'):
            raise ValidationError('selection must be strict or design')
        for name, value, low, high in [('block_entries', block_entries, 1, 1048576), ('metadata_mb', metadata_mb, 1, 4096),
                                      ('disk_budget', disk_budget, 1, 16*1024**4), ('reserve_bytes', reserve_bytes, 0, 16*1024**4)]:
            if type(value) is not int or not low <= value <= high:
                raise ValidationError(f'{name} must be an integer in {low}..{high}')
        config = {'design': design, 'matrix': matrix, 'obs_columns': columns, 'selection': selection,
                  'block_entries': block_entries, 'metadata_mb': metadata_mb,
                  'max_disk_bytes': disk_budget, 'reserve_bytes': reserve_bytes}
        if dry_run:
            return {'status': 'PREFLIGHT_ONLY', 'input': info, 'settings': config,
                    'counts_validated': False, 'donor_design_validated': False, 'output_written': False}
        if root.exists() and not reuse:
            raise PVLError('OUTPUT_EXISTS', f'Output already exists: {root}', 'Use --reuse for a completed identical run or choose a new directory.')
        notify('Hashing source and freezing the plan')
        input_info = stream_file(source, maximum=16*1024**4)
        request = {'format': 'pvl-sdk-plan-1', 'operation': 'aggregate', 'source': str(source),
                   'input': input_info, 'settings': config, 'engine': _engine_id()}
        existing = _begin(root, source, request, reuse)
        if existing:
            notify('Verified existing result; no new aggregation')
            return existing
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise _translate(exc) from exc
    try:
        write_json(root / 'design.json', design)
        notify('Aggregating counts in bounded blocks')
        result = aggregate_h5ad(design, source, root / 'aggregation', expected_sha256=input_info['sha256'],
            matrix=matrix, obs_columns=columns, selection=selection, block_entries=block_entries,
            metadata_mb=metadata_mb, max_disk_bytes=disk_budget, reserve_bytes=reserve_bytes)
        summary = {k: result[k] for k in ('input_shape', 'output_shape', 'selected_cells', 'excluded_cells', 'independent_units')}
        report = (f'# Counts aggregation complete\n\nInput: {info["shape"][0]:,} cells x {info["shape"][1]:,} genes.\n\n'
                  f'Output: {result["output_shape"][0]:,} samples x {result["output_shape"][1]:,} genes; '
                  f'{result["independent_units"]} declared paired donors.\n\n'
                  f'Selected cells: {result["selected_cells"]:,}; excluded: {result["excluded_cells"]:,}.\n\n'
                  f'Counts: [aggregation/counts.h5ad](aggregation/counts.h5ad)\n\n'
                  f'Frozen settings: [plan.json](plan.json); minimum cells {min_cells}, minimum total count {min_total_count}, selection {selection}.\n\n'
                  'No differential-expression model was fitted. Raw-count declarations and donor identities are not authenticated; scientific validity requires review.\n')
        notify('Writing the result manifest and report')
        return _finish(root, request, 'COMPLETE', summary, report)
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        raise _failed(root, request, exc) from exc


def check_bh(source: str | Path, *, output: str | Path, reuse: bool = False) -> RunResult:
    """Explicit BH audit of gene,p_value,q_value,log2fc; no method inference."""
    from .usage import diagnose
    source, root = Path(source).expanduser().absolute(), Path(output).expanduser().absolute()
    try:
        request = {'format': 'pvl-sdk-plan-1', 'operation': 'check_bh', 'source': str(source),
                   'input': stream_file(source, maximum=64*1048576), 'engine': _engine_id()}
        existing = _begin(root, source, request, reuse)
        if existing:
            return existing
    except (OSError, ValueError) as exc:
        raise _translate(exc) from exc
    try:
        paths = diagnose(source, root / 'diagnosis', check='bh')
        result = load_json(paths['json'])['result']
        stream_file(source, expected=request['input']['sha256'], maximum=request['input']['bytes'])
        report = Path(paths['report']).read_text(encoding='utf-8')
        return _finish(root, request, result['status'], {'passed': result['passed'], 'reason': result['reason']}, report)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise _failed(root, request, exc) from exc


def demo(output: str | Path) -> RunResult:
    """Zero-dependency synthetic BH example; no models, accounts or credentials."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix='pvl-demo-') as temp:
        source = Path(temp) / 'synthetic.csv'
        source.write_text('gene,p_value,q_value,log2fc\ng1,0.01,0.02,1\ng2,0.2,0.2,-1\n', encoding='utf-8')
        result = check_bh(source, output=output)
        # Keep the instructional input; explicitly mark it as synthetic.
        root = result.directory
        (root / 'synthetic.csv').write_bytes(source.read_bytes())
        request = load_json(root / 'plan.json')
        request.update(source='synthetic.csv', synthetic=True)
        write_json(root / 'plan.json', request)
        report = '# Synthetic demonstration\n\nThis is manufactured data, not a real plugin study or evidence of benefit.\n\n' + result.report.read_text(encoding='utf-8')
        return _finish(root, request, 'DEMO_COMPLETE', {'synthetic': True, 'non_author_participants': 0}, report)
