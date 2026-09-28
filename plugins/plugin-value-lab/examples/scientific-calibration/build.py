"""Public manufactured development controls, never a model or human study.

The paired reference is hand-calculated: 4 equal positive paired differences
give two-sided p=2/16. It is not produced by the detector being calibrated.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def build(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cases, expected = [], {}
    def put(name, value):
        data = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=True) + '\n'
        path = root / name
        path.write_text(data, encoding='utf-8', newline='\n')
        return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    def add(name, family, label, content, grader, passed, reason, suffix='csv'):
        ref = put(name + '.' + suffix, content) if content is not None else {'path': name + '.' + suffix, 'sha256': '0'*64}
        cases.append({'id': name, 'family': family, 'label': label, 'basis': 'task_contract',
                      'origin': 'synthetic', 'source': 'Public manufactured development control; not blinded or independent field evidence',
                      'label_reason': reason, 'artifact': ref, 'grader': deepcopy(grader)})
        expected[name] = passed
    bh = {'id': 'full-family-bh', 'type': 'artifact', 'artifact': 'result', 'verifier': {
        'kind': 'de_table', 'id_column': 'gene', 'p_column': 'p_value', 'q_column': 'q_value',
        'effect_column': 'log2fc', 'min_rows': 1, 'bh_tolerance': 1e-8,
        'testing_family': put('bh-family.json', {'ids': ['g1', 'g2', 'g3']})}}
    header = 'gene,p_value,q_value,log2fc\n'
    good = header + 'g1,.01,.03,2\ng2,.03,.04,-1\ng3,.04,.04,0\n'
    add('bh-correct', 'full-family-bh', 'valid', good, bh, True, 'Reverse cumulative minimum gives .03,.04,.04.')
    add('bh-reordered', 'full-family-bh', 'valid', header + 'g3,.04,.04,0\ng1,1e-2,3e-2,2\ng2,.03,.04,-1\n', bh, True, 'Row order and decimal notation do not change entity identity.')
    add('bh-ties-wrong', 'full-family-bh', 'defect', header + 'g1,0,0,0\ng2,.03,.045,1\ng3,.03,.045,1\n', bh, False, 'Tied p=.03 requires q=.03, not .045.')
    add('bh-ties-correct', 'full-family-bh', 'valid', header + 'g1,0,0,0\ng2,.03,.03,1\ng3,.03,.03,1\n', bh, True, 'Ties receive the same reverse-minimum adjustment.')
    add('bh-no-reverse-minimum', 'full-family-bh', 'defect', good.replace('g2,.03,.04', 'g2,.03,.045'), bh, False, 'Rank-wise product alone misses the monotone adjustment.')
    add('bh-dropped-null', 'full-family-bh', 'defect', header + 'g1,.01,.01,2\n', bh, False, 'Self-consistent one-row BH still omits the frozen family.')
    add('bh-nonfinite', 'full-family-bh', 'defect', good.replace('g3,.04,.04,0', 'g3,.04,.04,nan'), bh, False, 'The frozen contract requires finite effects.')
    add('bh-uncollected', 'full-family-bh', 'defect', None, bh, None, 'Unavailable bytes cannot prove detection or correctness.')
    absent = deepcopy(bh)
    absent['verifier']['testing_family']['sha256'] = '0'*64
    add('bh-reference-changed', 'full-family-bh', 'valid', good, absent, None, 'Reference integrity failure is a measurement gap.')
    add('by-method-dispute', 'full-family-bh', 'disputed', header + 'g1,.01,.055,2\ng2,.03,.0733333333333333,-1\ng3,.04,.0733333333333333,0\n', bh, False,
        'BY is a different adjustment. Whether BH is required is unresolved; the mismatch is not an adjudicated scientific defect.')

    numeric = {'id': 'partition', 'type': 'numeric_tolerance', 'artifact': 'result', 'verifier': {
        'metric': 'ari', 'truth': put('partition-truth.csv', 'id,value\na,T\nb,T\nc,B\nd,B\n'),
        'id_column': 'id', 'value_column': 'value', 'threshold': 1, 'absolute': 0, 'relative': 0}}
    add('partition-correct', 'entity-partition', 'valid', 'id,value\na,T\nb,T\nc,B\nd,B\n', numeric, True, 'Exact partition; biological labels are not validated.')
    add('partition-renamed-reordered', 'entity-partition', 'valid', 'id,value\nd,2\nc,2\nb,1\na,1\n', numeric, True, 'ARI permits cluster-name permutations and row order.')
    add('partition-swapped-members', 'entity-partition', 'defect', 'id,value\na,1\nb,2\nc,1\nd,2\n', numeric, False, 'Entity membership changed; ARI=-.5 by hand calculation.')
    add('partition-missing', 'entity-partition', 'defect', 'id,value\na,1\nb,1\n', numeric, False, 'A correct subset is not complete coverage.')
    add('partition-duplicate', 'entity-partition', 'defect', 'id,value\na,1\na,1\nc,2\nd,2\n', numeric, False, 'Duplicate IDs do not establish coverage.')
    absent = deepcopy(numeric)
    absent['verifier']['truth']['sha256'] = '0'*64
    add('partition-reference-changed', 'entity-partition', 'valid', 'id,value\na,T\nb,T\nc,B\nd,B\n', absent, None, 'Changed reference integrity remains unknown.')

    design = {'format': 'pvl-replicate-design-1', 'mode': 'paired', 'control': 'control', 'treatment': 'treated',
              'features': ['signal', 'null'], 'training_units': [], 'exchangeability': 'Manufactured equal paired differences; not biological independence.',
              'samples': [{'id': group + str(i), 'unit': 'donor' + str(i), 'condition': group, 'block': 'batch'}
                          for group in ('control', 'treated') for i in range(4)]}
    raw = 'sample,feature,value\n' + ''.join(f'{g}{i},{f},{i + (4 if g == "treated" and f == "signal" else 0)}\n'
        for g in ('control', 'treated') for i in range(4) for f in ('signal', 'null'))
    spec = {'design': put('paired-design.json', design), 'data': put('paired-data.csv', raw),
            'alpha': .1, 'minimum_effect': 1, 'absolute': 1e-10, 'relative': 1e-10}
    rule = {'id': 'donor-reference', 'type': 'replicate_effect', 'artifact': 'result', 'verifier': spec}
    result = {'format': 'pvl-replicate-result-1', 'method': 'exact-blocked-permutation-bh', 'analysis_unit': 'independent_unit',
              'mode': 'paired', 'contrast': ['control', 'treated'], 'alternative': 'two-sided-doubled-min-tail',
              'design_sha256': spec['design']['sha256'], 'data_sha256': spec['data']['sha256'], 'alpha': .1,
              'minimum_effect': 1, 'results': [
                  {'feature': 'signal', 'effect': 4, 'p_value': .125, 'q_value': .25, 'n_control': 4, 'n_treatment': 4,
                   'loo_effect_min': 4, 'loo_effect_max': 4, 'decision': 'not_supported'},
                  {'feature': 'null', 'effect': 0, 'p_value': 1, 'q_value': 1, 'n_control': 4, 'n_treatment': 4,
                   'loo_effect_min': 0, 'loo_effect_max': 0, 'decision': 'not_supported'}]}
    add('paired-correct', 'donor-replication', 'valid', result, rule, True, '4 paired units; exact sign-flip count 16; adjusted significance remains insufficient.', 'json')
    reordered = deepcopy(result)
    reordered['results'].reverse()
    add('paired-feature-order', 'donor-replication', 'valid', reordered, rule, True, 'Feature order does not change the testing family.', 'json')
    wrong = deepcopy(result)
    wrong['results'][0]['n_treatment'] = 400
    add('paired-cell-count-as-replicates', 'donor-replication', 'defect', wrong, rule, False, '400 cells cannot replace 4 treatment unit samples.', 'json')
    wrong = deepcopy(result)
    wrong['analysis_unit'] = 'cell'
    add('paired-wrong-unit', 'donor-replication', 'defect', wrong, rule, False, 'Paired independent units, not cells, are required.', 'json')
    wrong = deepcopy(result)
    wrong['results'][0]['effect'] = -4
    add('paired-reversed-effect', 'donor-replication', 'defect', wrong, rule, False, 'Treatment minus control is +4.', 'json')
    broken = deepcopy(design)
    broken['samples'][0]['unit'] = 'unknown-donor'
    unknown = deepcopy(rule)
    unknown['verifier']['design'] = put('paired-unresolved-design.json', broken)
    add('paired-unresolved-identity', 'donor-replication', 'disputed', result, unknown, None, 'Unresolved reference pairing cannot adjudicate a result; donor authenticity is also unverified.', 'json')
    return put('manifest.json', {'format': 'pvl-detector-corpus-1', 'families': ['full-family-bh', 'entity-partition', 'donor-replication'],
        'development_only': True, 'heldout': False, 'independent_review': 'PENDING', 'expected_passed': expected, 'cases': cases})


if __name__ == '__main__':
    print(json.dumps(build(Path(__file__).resolve().parent), ensure_ascii=True))
