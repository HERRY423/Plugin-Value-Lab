"""Explicit PyDESeq2 same-fit contrast acceptance on synthetic counts; no model calls."""
from copy import deepcopy
import argparse
import importlib.metadata
import json
import math
from pathlib import Path
import random
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.core import suite_digest, write_json
from value_lab.metamorphic import build_inputs, assess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / 'acceptance.json', {'status': 'STARTED', 'synthetic': True})
    try:
        import pandas as pd
        from pydeseq2.dds import DeseqDataSet
        from pydeseq2.ds import DeseqStats
        rng = random.Random(20260928)
        genes = ['g' + str(i) for i in range(80)]
        base = [rng.randint(50, 300) for _ in genes]
        names, metadata, counts = [], [], []
        for donor in range(6):
            for condition in ('control', 'treated'):
                names.append(f'd{donor}-{condition}')
                metadata.append({'donor': 'd' + str(donor), 'condition': condition})
                counts.append([max(1, int(b * rng.lognormvariate(0, .25) *
                               (1.8 if condition == 'treated' and i < 15 else 1))) for i, b in enumerate(base)])
        columns = ['effect', 'se', 'ci_lower', 'ci_upper', 'p', 'q']
        design = {'format': 'pvl-metamorphic-design-1',
            'source': {'matrix': {'row_ids': names, 'columns': genes, 'values': counts},
                       'context': {'contrast': ['treated', 'control'], 'test': 'two_sided_wald',
                                   'lfc_shrinkage': False, 'testing_family': 'fixed', 'fit_policy': 'same_fit',
                                   'metadata': dict(zip(names, metadata)), 'formula': '~donor + condition'}},
            'output': {'kind': 'numeric', 'row_ids': genes, 'columns': columns},
            'tolerance': {'absolute': 1e-7, 'relative': 1e-6},
            'relations': [{'id': 'reverse', 'relation': 'contrast_reversal',
                           'parameters': {'effect': 'effect', 'standard_error': 'se', 'ci_lower': 'ci_lower',
                                          'ci_upper': 'ci_upper', 'p_value': 'p', 'q_value': 'q'},
                           'rationale': 'Same fitted design, unshrunk two-sided Wald contrast and full fixed gene family'}]}
        inputs = build_inputs(design)
        dds = DeseqDataSet(counts=pd.DataFrame(counts, index=names, columns=genes),
                          metadata=pd.DataFrame(metadata, index=names), design='~donor + condition',
                          n_cpus=1, refit_cooks=True, size_factors_fit_type='ratio', quiet=True)
        with warnings.catch_warnings(record=True) as fit_warnings:
            warnings.simplefilter('always')
            dds.deseq2()
        observed_warnings = [str(w.message) for w in fit_warnings]
        runs = []
        for identity, value in inputs.items():
            stats = DeseqStats(dds, contrast=['condition', *value['context']['contrast']],
                              alpha=.05, independent_filter=False, cooks_filter=True, n_cpus=1, quiet=True)
            with warnings.catch_warnings(record=True) as stat_warnings:
                warnings.simplefilter('always')
                stats.summary()
            observed_warnings.extend(str(w.message) for w in stat_warnings)
            rows = []
            for gene in genes:
                row = stats.results_df.loc[gene]
                effect, se = float(row['log2FoldChange']), float(row['lfcSE'])
                result = [effect, se, effect - 1.959963984540054 * se, effect + 1.959963984540054 * se,
                          float(row['pvalue']), float(row['padj'])]
                if not all(math.isfinite(v) for v in result):
                    raise RuntimeError('Synthetic fixture produced undefined results; retain failure, do not drop genes')
                rows.append(result)
            runs.append({'id': identity, 'input_sha256': suite_digest(value), 'status': 'completed',
                         'output': {'row_ids': genes, 'columns': columns, 'values': rows}})
        observations = {'format': 'pvl-metamorphic-observations-1', 'design_sha256': suite_digest(design), 'runs': runs}
        good, receipt = assess(design, observations)
        mutant = deepcopy(observations)
        mutant['runs'][1]['output'] = deepcopy(mutant['runs'][0]['output'])
        bad, mutant_receipt = assess(design, mutant)
        missing = deepcopy(observations)
        missing['runs'].pop()
        unknown, missing_receipt = assess(design, missing)
        assert good is True and bad is False and unknown is None
        for name, data in [('design', design), ('observations', observations), ('assessment', receipt),
                           ('mutant-assessment', mutant_receipt), ('missing-assessment', missing_receipt)]:
            write_json(root / (name + '.json'), data)
        acceptance = {'status': 'PASS', 'synthetic': True, 'backend': 'pydeseq2',
                      'version': importlib.metadata.version('pydeseq2'), 'real_model_fits': 1, 'real_contrasts': 2,
                      'genes_compared': len(genes), 'valid_relation': good, 'unchanged_sign_mutant': bad,
                      'missing_followup': unknown, 'external_model_calls': 0, 'biological_validity': 'NOT_TESTED',
                      'observed_dispersion_trend': str(dds.uns['disp_function_type']), 'warnings': observed_warnings,
                      'design_sha256': suite_digest(design)}
        write_json(root / 'acceptance.json', acceptance)
        print(json.dumps(acceptance, ensure_ascii=True))
    except Exception:
        write_json(root / 'acceptance.json', {'status': 'FAILED', 'synthetic': True})
        raise


if __name__ == '__main__':
    main()
