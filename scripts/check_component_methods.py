"""Offline synthetic calibration of component, ceiling and equivalence methods."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.core import demo_suite, demo_records, suite_digest, write_json, load_json
from value_lab.component_studies import plan, analyze
from value_lab import saturation
from value_lab.equivalence import assess
from component_eval import render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    suite = demo_suite()
    suite['cases'] = suite['cases'][:2]
    suite['policy']['min_clusters'] = 2
    for case in suite['cases']:
        case.update(kind='task', prompt='Synthetic calibration: report total counts of 120 for a manufactured four-sample matrix.',
                    graders=[{'id': 'counts', 'type': 'json_equals', 'path': 'total_counts', 'value': 120,
                              'dimension': 'outcome', 'weight': 1, 'critical': True}])
    results = {}
    for factors in (2, 3):
        components = {'prompt': suite_digest('synthetic prompt'), 'tools': suite_digest('synthetic tools'),
                      'context': suite_digest('synthetic context') if factors == 3 else None}
        design = plan(suite, components)
        arms = {a['id']: a for a in design['arms']}
        template = demo_records(suite)[0]
        observations = {'format': 'pvl-component-observations-1', 'design_sha256': suite_digest(design), 'runs': []}
        for assignment in design['assignments']:
            arm = assignment['arm']
            record = deepcopy(template)
            correct = all(bit == '1' for bit in arm)
            record.update(case_id=assignment['case_id'], repetition=assignment['repetition'],
                arm='with' if '1' in arm else 'without', plugin_loaded='1' in arm,
                session_id='synthetic-' + str(assignment['execution_index']),
                output=json.dumps({'total_counts': 120 if correct else 119}), human_intervals=[],
                cost={'model_usd': 0, 'tool_usd': 0, 'human_minutes': 0})
            observations['runs'].append({**assignment, 'components': arms[arm]['components'], 'record': record})
        report = analyze(design, observations, suite_digest(design))
        dest = root / (str(2**factors) + '-arms')
        write_json(dest / 'design.json', design)
        write_json(dest / 'observations.json', observations)
        write_json(dest / 'report.json', report)
        (dest / 'README.md').write_text(render(report), encoding='utf-8')
        missing = deepcopy(observations)
        missing['runs'].pop()
        missing_report = analyze(design, missing, suite_digest(design))
        write_json(dest / 'missing-report.json', missing_report)
        assert report['status'] == 'COMPLETE' and missing_report['status'] == 'INCOMPLETE'
        assert all(c['success'] == 1 / (2**(factors - 1)) for c in report['contrasts'])
        results[str(2**factors) + '_arms'] = report['status']
    studies = []
    for model in ('SYNTHETIC-MODEL-1', 'SYNTHETIC-MODEL-2', 'SYNTHETIC-MODEL-3'):
        version = deepcopy(suite)
        version['conditions']['model'] = model
        records = demo_records(version)
        for r in records:
            r.update(output='{"total_counts":120}', session_id=model + '-' + r['session_id'])
        studies.append({'suite': version, 'records': records, 'lock': {'suite_sha256': suite_digest(version)}})
    series = saturation.plan(studies[0]['suite'], [s['suite']['conditions']['model'] for s in studies])
    result = saturation.analyze(series, studies, suite_digest(series))
    write_json(root / 'series/design.json', series)
    write_json(root / 'series/studies.json', studies)
    write_json(root / 'series/report.json', result)
    (root / 'series/README.md').write_text(render(result), encoding='utf-8')
    assert result['saturation_index'] == 1
    results['saturation_index'] = result['saturation_index']
    scientific = ROOT / 'examples/equivalence'
    design, truth, actual = (load_json(scientific / (name + '.json')) for name in ('design', 'truth', 'observed'))
    passed, receipt = assess(design, actual, truth)
    assert passed is True
    write_json(root / 'equivalence/pass.json', receipt)
    shifted = deepcopy(truth)
    shifted['values'] = [[x[0] + 10] for x in truth['values']]
    failed, receipt = assess(design, shifted, truth)
    assert failed is False
    write_json(root / 'equivalence/offset-failure.json', receipt)
    results.update(equivalence_pass=passed, offset_rejected=failed is False)
    acceptance = {'status': 'PASS', 'results': results, 'evidence_type': 'synthetic',
                  'model_calls': 0, 'host_component_execution': 'NOT_TESTED',
                  'scientific_validity': 'NOT_ESTABLISHED', 'paid_service_calls': 0}
    write_json(root / 'acceptance.json', acceptance)
    (root / 'README.md').write_text('# 方法校准结果\n\n全部为人工构造的工程校准，未调用真实模型。\n\n'
        '- [四臂消融](4-arms/README.md)\n- [八臂消融](8-arms/README.md)\n'
        '- [连续版本饱和度](series/README.md)\n- [TOST 等价示例](equivalence/pass.json)\n'
        '- [整体偏移反例](equivalence/offset-failure.json)\n\n'
        '配置声明不等于宿主执行；校准通过不证明真实插件收益或生物学有效性。\n', encoding='utf-8')
    print(json.dumps(acceptance, ensure_ascii=True))


if __name__ == '__main__':
    main()
