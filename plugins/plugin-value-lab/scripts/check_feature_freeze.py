"""Check the frozen interface inventory and eight-document onboarding boundary.

This local CI guard does not judge whether code inside an existing interface adds
new behavior. Such changes still require review. Dates never unlock the guard.
"""
import argparse
import ast
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
GOLDEN = ['doctor', 'freeze', 'evaluate', 'usage-card', 'compare-studies']


def surface(root=ROOT):
    from value_lab.cli import main
    class Captured(Exception):
        pass
    result = {}
    def capture(parser, *args, **kwargs):
        def options(p):
            return sorted([{'name': a.dest, 'flags': sorted(a.option_strings),
                            'required': a.required, 'choices': sorted(a.choices) if a.choices else None}
                           for a in p._actions if not isinstance(a, argparse._SubParsersAction)], key=lambda a: a['name'])
        result['global_options'] = options(parser)
        result['commands'] = {name: options(p) for action in parser._actions
                              if isinstance(action, argparse._SubParsersAction) for name, p in action.choices.items()}
        raise Captured()
    with patch.object(argparse.ArgumentParser, 'parse_args', capture):
        try:
            main(['--advanced', '--enable-extensions', 'doctor'])
        except Captured:
            pass
    tree = ast.parse((root / 'value_lab/server.py').read_text(encoding='utf-8'))
    functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    names = {n.name for n in functions.values() if any(isinstance(d, ast.Call)
             and isinstance(d.func, ast.Attribute) and d.func.attr in ('tool', 'resource', 'prompt') for d in n.decorator_list)}
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Call) and isinstance(n.func.func, ast.Attribute)
                and n.func.func.attr in ('tool', 'resource', 'prompt')):
            names.update(a.id for a in n.args if isinstance(a, ast.Name))
    result['mcp_signatures'] = {name: ast.dump(functions[name].args, include_attributes=False) for name in sorted(names)}
    result['skills'] = sorted(p.relative_to(root).as_posix() for d in ('skills', 'extensions') for p in (root / d).rglob('SKILL.md'))
    result['runtime_modules'] = sorted(p.relative_to(root).as_posix() for p in (root / 'value_lab').rglob('*.py'))
    result['schemas'] = sorted(p.relative_to(root).as_posix() for p in (root / 'schemas').rglob('*.json'))
    # Includes file-grader and simple-grader literal allowlists, not only filenames.
    result['grader_allowlists'] = []
    for name in ('core.py', 'artifacts.py', 'science.py'):
        for n in ast.walk(ast.parse((root / 'value_lab' / name).read_text(encoding='utf-8'))):
            if isinstance(n, ast.Set) and all(isinstance(v, ast.Constant) and isinstance(v.value, str) for v in n.elts):
                values = sorted(v.value for v in n.elts)
                if set(values) & {'contains', 'artifact', 'backend_identity', 'replicate_effect'}:
                    result['grader_allowlists'].append([name, values])
    return result


def documentation_issues(root=ROOT):
    issues = []
    docs = sorted(list(root.glob('*.md')) + [p for p in (root / 'docs').rglob('*.md')
                  if p.relative_to(root / 'docs').parts[0] != 'history'])
    if len(docs) > 8:
        issues.append(f'Mainline documents: {len(docs)} exceeds 8')
    for name in ('README.md', 'README.zh-CN.md'):
        commands = re.findall(r'^python scripts/value_lab.py ([a-z-]+)\b', (root / name).read_text(encoding='utf-8'), re.M)
        if commands != GOLDEN:
            issues.append(f'{name}: expected exactly the five golden commands in order')
    for p in docs:
        for target in re.findall(r'\]\(([^\s)]+)\)', p.read_text(encoding='utf-8')):
            if urlsplit(target).scheme or target.startswith(('#', '/')):
                continue
            if not (p.parent / unquote(target.split('#')[0])).exists():
                issues.append(f'{p.relative_to(root)}: broken local link {target}')
    return issues, [p.relative_to(root).as_posix() for p in docs]


def check(root=ROOT):
    frozen = json.loads((root / 'docs/feature-freeze.json').read_text(encoding='utf-8'))
    observed = surface(root)
    issues, documents = documentation_issues(root)
    issues += ['Frozen surface changed: ' + k for k in sorted(set(observed) | set(frozen['surface']))
               if observed.get(k) != frozen['surface'].get(k)]
    if frozen['status'] != 'FROZEN' or frozen['golden_commands'] != GOLDEN:
        issues.append('Freeze status or golden path was altered; explicit owner decision required')
    return {'status': 'PASS' if not issues else 'FAIL', 'issues': issues,
            'mainline_documents': documents, 'planned_review': frozen['planned_review'],
            'automatic_unfreeze': False, 'semantic_feature_review_required': True}


if __name__ == '__main__':
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)
