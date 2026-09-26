"""Local pilot material, not a new PVL command. No fitting, model calls or inferred truth."""
from pathlib import Path
from datetime import datetime, timezone
import json
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from value_lab.core import ValidationError, load_json, write_json
from value_lab.artifacts import sha
from value_lab.pseudobulk import aggregate


def required(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f'Author must supply {label}; it will not be inferred')
    return value


def read_data(source, design, base):
    path = (base / required(source.get('path'), 'data.path')).resolve()
    if source.get('kind') == 'pvl-cell-counts-1':
        return load_json(path), {'sha256': sha(path), 'kind': source['kind']}
    if source.get('kind') != 'h5ad':
        raise ValidationError('Data kind must be pvl-cell-counts-1 or h5ad')
    # Layer and column mappings are supplied, never guessed from .X or labels.
    layer = required(source.get('counts_layer'), 'data.counts_layer (explicit X or layer name)')
    columns = {k: required(source.get(k + '_column'), k + '_column')
               for k in ('sample', 'donor', 'condition', 'cell_type')}
    import anndata
    from scipy.sparse import csr_matrix
    import numpy as np
    obj = anndata.read_h5ad(path)
    for column in columns.values():
        if column not in obj.obs or obj.obs[column].isna().any():
            raise ValidationError('Missing declared metadata column or values: ' + column)
    # Select only the explicitly declared cell type, never silently drop other conditions.
    obj = obj[obj.obs[columns['cell_type']].astype(str) == design['cell_type']].copy()
    if obj.n_obs > 100000 or obj.n_vars > 100000:
        raise ValidationError('Selected material exceeds the existing bounded verifier budget')
    if layer != 'X' and layer not in obj.layers:
        raise ValidationError('Declared raw-count layer is absent')
    matrix = csr_matrix(obj.X if layer == 'X' else obj.layers[layer])
    if not np.isfinite(matrix.data).all() or (matrix.data < 0).any() or not np.equal(matrix.data, np.floor(matrix.data)).all():
        raise ValidationError('Declared layer is not finite nonnegative integer counts; no rounding')
    matrix.sum_duplicates()
    data = {'format': 'pvl-cell-counts-1', 'genes': list(map(str, obj.var_names)), 'cells': [],
            'provenance': {'source': 'author-supplied local file', 'source_file_sha256': sha(path),
                           'counts_layer': layer, 'metadata_mapping': columns, 'authenticity': 'NOT_VERIFIED'}}
    for i, (identifier, row) in enumerate(obj.obs.iterrows()):
        values = matrix.getrow(i)
        data['cells'].append({'id': str(identifier), **{k: str(row[v]) for k, v in columns.items()},
                             'counts': [[int(j), int(v)] for j, v in zip(values.indices, values.data) if v]})
    return data, {'sha256': sha(path), 'kind': source['kind'], 'mapping': columns, 'counts_layer': layer}


def prepare(config_path, output):
    config_path, output = Path(config_path), Path(output)
    output.mkdir(parents=True, exist_ok=False)  # Preserve failures as separate attempts.
    try:
        config = load_json(config_path)
        write_json(output / 'submitted-input.json', config)
        required(config.get('question'), 'question')
        plugin = (config_path.parent / required(config.get('plugin_path'), 'plugin_path')).resolve()
        if not plugin.is_dir():
            raise ValidationError('plugin_path must identify an existing local plugin directory')
        design = config['design']
        data, source = read_data(config['data'], design, config_path.parent)
        pb = aggregate(design, data)
        write_json(output / 'design.json', design)
        write_json(output / 'data.json', data)
        review = config.get('author_review', {})
        pending = [k for k in ('raw_counts_and_identity_checked', 'paired_design_appropriate',
                    'fixed_method_matches_question', 'filters_chosen_before_results') if review.get(k) is not True]
        if not isinstance(review.get('reference_suitability_basis'), str) or not review['reference_suitability_basis'].strip():
            pending.append('reference_suitability_basis')
        if design['task_mode'] != 'fixed_method':
            pending.append('pilot_requires_fixed_method; use existing expert-review path for acceptable alternatives')
        summary = {'status': 'AUTHOR_REVIEW_REQUIRED' if pending else 'READY_FOR_EXPLICIT_REFERENCE_RUN',
            'question': config['question'], 'pending': pending,
            'source': source, 'design_sha256': sha(output / 'design.json'), 'data_sha256': sha(output / 'data.json'),
            'cells': len(data['cells']), 'donor_pairs': pb['independent_units'], 'samples': len(pb['samples']),
            'tested_genes': len(pb['genes']), 'excluded_genes': len(pb['excluded_genes']),
            'samples_to_check': [{k: s[k] for k in ('id', 'donor', 'condition', 'cells')} for s in pb['samples']],
            'author_review': review, 'review_authenticated': False, 'reference_created': False,
            'plugin_content_identity': 'NOT_CAPTURED; bind actual bytes in the existing host collection plan',
            'claim': 'Input preparation only; no standard answer, confirmed defect or benefit evidence'}
        write_json(output / 'preparation.json', summary)
        title = '待作者确认' if pending else '可显式运行参考；仍须审阅'
        (output / 'REVIEW.md').write_text(
            f'# {title}\n\n问题：{config["question"]}\n\n'
            f'输入核对：{summary["cells"]} 个细胞、{summary["donor_pairs"]} 对供者、'
            f'{summary["samples"]} 个样本；预设过滤后 {summary["tested_genes"]} 个基因。\n\n'
            '逐样本身份和细胞数见 preparation.json。供者身份、独立性和方法适用性仍需作者核对。\n\n'
            '待确认项：' + (', '.join(pending) or '已提供作者声明；声明不等于独立验证') + '\n\n'
            '下一步按包内 RUNBOOK.md：先审阅设计，再显式运行参考、检验合法变体、隔离评分材料，'
            '最后在授权宿主运行自己的插件。此处没有生成真值、运行结果或收益分数。\n', encoding='utf-8')
        return summary
    except Exception as exc:
        write_json(output / 'preparation.json', {'status': 'FAILED', 'error': str(exc), 'reference_created': False})
        raise


if __name__ == '__main__':
    base = Path(__file__).resolve().parent
    output = ROOT / 'work/author-pilot/attempts' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    try:
        result = prepare(base / 'author-input.json', output)
        print(json.dumps({'output': str(output), **result}, ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({'output': str(output), 'error': str(exc)}, ensure_ascii=True))
        raise SystemExit(2)
