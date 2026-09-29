"""Real sandbox calibration of 2/3-component localization, with fixed controls."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.artifacts import sha
from value_lab.core import suite_digest, write_json
from value_lab.science_execution import capture_runtime
from value_lab.component_localization import run_interventions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--runtime')
    args = parser.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    source, answers, configs = (root / n for n in ('public', 'answers', 'configs'))
    for p in (source, answers, configs):
        p.mkdir()
    code = {
        'run.py': 'import sys,json\nfrom pathlib import Path\nsys.path.insert(0,"/inputs")\nimport method,selection,formatting\nrows=json.loads(Path(sys.argv[1]).read_text())\nrows=selection.select(rows)\nq=method.adjust([r["p"] for r in rows])\nformatting.save("q.json",dict(zip([r["id"] for r in rows],q)))\nformatting.save("preserved.json",rows)\n',
        'method-candidate.py': 'def adjust(p):\n    return p\n',
        'method-replacement.py': 'def adjust(p):\n    n=len(p)\n    order=sorted(range(n),key=lambda i:p[i])\n    q=[1.0]*n\n    ceiling=1.0\n    for j in range(n-1,-1,-1):\n        i=order[j]\n        ceiling=min(ceiling,p[i]*n/(j+1))\n        q[i]=ceiling\n    return q\n',
        'selection-candidate.py': 'def select(rows):\n    return [r for r in rows if r["p"] <= 0.5]\n',
        'selection-replacement.py': 'def select(rows):\n    return list(rows)\n',
        'formatting-candidate.py': 'import json\nfrom pathlib import Path\ndef save(p,v):\n    Path("/output",p).write_text(json.dumps(v))\n',
        'formatting-replacement.py': 'import json\nfrom pathlib import Path\ndef save(p,v):\n    Path("/output",p).write_text(json.dumps(v,sort_keys=True,indent=2))\n'}
    for name, content in code.items():
        (source / name).write_text(content, encoding='utf-8')
    target = [{'id': k, 'p': p, 'effect': e} for k, p, e in [('A', .01, 1.0), ('B', .04, -2.0), ('C', .03, .5), ('D', .8, 0.0)]]
    control = [dict(r, p=0.0) for r in target]
    for name, data in [('target', target), ('control', control)]:
        write_json(source / (name + '.json'), data)
        write_json(answers / (name + '-preserved.json'), data)
    write_json(answers / 'target-q.json', {'A': .04, 'B': .16/3, 'C': .16/3, 'D': .8})
    write_json(answers / 'control-q.json', dict.fromkeys('ABCD', 0.0))
    lock = capture_runtime(['packaging'], root / 'runtime', runtime=args.runtime)
    write_json(configs / 'environment.lock.json', lock)
    ref = lambda name: {'path': name, 'sha256': sha(source / name)}
    results = {}
    for factors in (2, 3):
        components = ['method', 'formatting'] if factors == 2 else ['method', 'selection', 'formatting']
        common_names = ['run.py', 'target.json', 'control.json']
        if factors == 2:
            (source / 'selection.py').write_text(code['selection-replacement.py'], encoding='utf-8')
            common_names.append('selection.py')
        cases = []
        for name in ('target', 'control'):
            manifest = {'format': 'pvl-science-execution-1', 'files': {p: sha(source / p) for p in common_names},
                'entrypoint': 'run.py', 'arguments': ['/inputs/' + name + '.json'],
                'environment': {'path': 'environment.lock.json', 'sha256': sha(configs / 'environment.lock.json')},
                'outputs': [{'path': p + '.json', 'submitted': {'path': name + '-' + p + '.json', 'sha256': sha(answers / (name + '-' + p + '.json'))},
                             'comparison': 'json', 'absolute': 1e-12, 'relative': 1e-12} for p in ('q', 'preserved')],
                'timeout_seconds': 15, 'memory_mb': 256}
            cases.append({'id': name, 'role': name, 'manifest': manifest})
        design = {'format': 'pvl-component-localization-1', 'cases': cases, 'seed': 73419,
                  'components': [{'id': c, 'target': c + '.py', 'candidate': ref(c + '-candidate.py'),
                                  'replacement': ref(c + '-replacement.py')} for c in components]}
        path = configs / (str(factors) + '-design.json')
        write_json(path, design)
        report = run_interventions(path, suite_digest(design), source, answers, root / (str(factors) + '-factor'), runtime=args.runtime)
        resolved = [c for c in report['contrasts'] if c['failure_disappeared']]
        assert report['status'] == 'COMPLETE'
        assert all(r['pipeline_completed'] and r['environment_check'] == 'MATCH_BEFORE_AND_AFTER' for r in report['runs'])
        assert len(resolved) == (2 if factors == 2 else 4), report
        assert not any(c['component'] == 'formatting' for c in resolved)
        results[str(factors)] = {'executions': report['recorded_runs'], 'resolved_conditional_contrasts': len(resolved),
                                'components': sorted({c['component'] for c in resolved})}
    write_json(root / 'acceptance.json', {'status': 'PASS', 'results': results, 'evidence_kind': 'AUTHOR_CONSTRUCTED_ACTUAL_SANDBOX_EXECUTIONS',
        'native_plugin_activation': False, 'human_validation': 'PENDING'})
    print(json.dumps(results))


if __name__ == '__main__':
    main()
