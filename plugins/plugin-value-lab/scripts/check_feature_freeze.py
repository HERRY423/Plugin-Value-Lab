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
FREEZE_FORMAT = 'pvl-feature-freeze-2'

# Explicit expression fields, never AST repr/_fields: interpreter metadata and
# empty-field display defaults are not part of this project's interface schema.
# Unknown syntax fails closed until this schema is deliberately extended.
EXPRESSION_FIELDS = {
    'Name': ('id',), 'Attribute': ('value', 'attr'),
    'Subscript': ('value', 'slice'), 'Slice': ('lower', 'upper', 'step'),
    'List': ('elts',), 'Tuple': ('elts',), 'Set': ('elts',),
    'Dict': ('keys', 'values'), 'Starred': ('value',),
    'BinOp': ('left', 'op', 'right'), 'UnaryOp': ('op', 'operand'),
    'BoolOp': ('op', 'values'), 'Compare': ('left', 'ops', 'comparators'),
    'IfExp': ('test', 'body', 'orelse'), 'Call': ('func', 'args', 'keywords'),
    'keyword': ('arg', 'value'),
}
OPERATORS = frozenset(('Add Sub Mult MatMult Div Mod Pow LShift RShift BitOr '
                       'BitXor BitAnd FloorDiv Invert Not UAdd USub And Or '
                       'Eq NotEq Lt LtE Gt GtE Is IsNot In NotIn').split())


def expression(node):
    """JSON-safe syntax, without evaluating defaults or importing annotations."""
    if node is None or isinstance(node, str):
        return node
    if isinstance(node, list):
        return [expression(item) for item in node]
    if isinstance(node, ast.Constant):
        value = node.value
        kind = type(value).__name__
        # Typed constants keep True, 1 and 1.0 distinct even under JSON equality.
        if value is Ellipsis:
            value = '...'
        elif isinstance(value, bytes):
            value = value.hex()
        elif isinstance(value, float):
            value = value.hex()
        elif isinstance(value, complex):
            value = [value.real.hex(), value.imag.hex()]
        elif value is not None and type(value) not in (str, bool, int):
            raise ValueError(f'Unsupported signature constant: {kind}')
        return {'node': 'Constant', 'type': kind, 'value': value}
    kind = type(node).__name__
    if kind in OPERATORS:
        return {'node': kind}
    if kind not in EXPRESSION_FIELDS:
        raise ValueError(f'Unsupported signature expression: {kind}')
    return {'node': kind, **{field: expression(getattr(node, field))
                            for field in EXPRESSION_FIELDS[kind]}}


def annotation(node):
    # Quoted forward annotations and their unquoted spelling describe the same
    # type. Do not resolve names or rewrite e.g. Literal string arguments.
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        node = ast.parse(node.value, mode='eval').body
    return expression(node)


def parameters(args):
    result = []

    def add(arg, kind, default=None):
        result.append({'name': arg.arg, 'kind': kind,
                       'annotation': annotation(arg.annotation),
                       'default': {'present': default is not None,
                                   'value': expression(default)}})

    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + args.defaults
    for index, (arg, default) in enumerate(zip(positional, defaults)):
        add(arg, 'POSITIONAL_ONLY' if index < len(args.posonlyargs) else 'POSITIONAL_OR_KEYWORD', default)
    if args.vararg:
        add(args.vararg, 'VAR_POSITIONAL')
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        add(arg, 'KEYWORD_ONLY', default)
    if args.kwarg:
        add(args.kwarg, 'VAR_KEYWORD')
    return result


def signature(function):
    if getattr(function, 'type_params', []):
        raise ValueError('Generic MCP function signatures require an explicit schema extension')
    return {'parameters': parameters(function.args),
            'returns': annotation(function.returns),
            'async': isinstance(function, ast.AsyncFunctionDef)}


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
    functions = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    names = {n.name for n in functions.values() if any(isinstance(d, ast.Call)
             and isinstance(d.func, ast.Attribute) and d.func.attr in ('tool', 'resource', 'prompt') for d in n.decorator_list)}
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Call) and isinstance(n.func.func, ast.Attribute)
                and n.func.func.attr in ('tool', 'resource', 'prompt')):
            names.update(a.id for a in n.args if isinstance(a, ast.Name))
    result['mcp_signatures'] = {name: signature(functions[name]) for name in sorted(names)}
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
    issues, documents = documentation_issues(root)
    try:
        observed = surface(root)
    except (ValueError, SyntaxError) as exc:
        issues.append('Cannot normalize frozen surface: ' + str(exc))
    else:
        issues += ['Frozen surface changed: ' + k for k in sorted(set(observed) | set(frozen['surface']))
                   if observed.get(k) != frozen['surface'].get(k)]
    if frozen.get('format') != FREEZE_FORMAT:
        issues.append('Unsupported freeze format; reviewed migration required')
    if frozen['status'] != 'FROZEN' or frozen['golden_commands'] != GOLDEN:
        issues.append('Freeze status or golden path was altered; explicit owner decision required')
    return {'status': 'PASS' if not issues else 'FAIL', 'issues': issues,
            'mainline_documents': documents, 'planned_review': frozen['planned_review'],
            'automatic_unfreeze': False, 'semantic_feature_review_required': True}


if __name__ == '__main__':
    result = check()
    print(json.dumps(result, ensure_ascii=True, indent=2))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)
