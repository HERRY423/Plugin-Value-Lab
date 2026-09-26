"""Guard the requested freeze and runnable README without claiming human timing."""
import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('freeze_guard', ROOT / 'scripts/check_feature_freeze.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class FeatureFreezeTests(unittest.TestCase):
    def test_signature_schema_covers_all_parameter_kinds(self):
        function = ast.parse('''
async def tool(a: int, b: str = "中文", /, c: "list[dict]" = None,
               *items: bytes, required: bool, optional: int = 2, **extra: dict) -> "dict":
    pass
''').body[0]
        def name(value):
            return {'node': 'Name', 'id': value}
        def constant(kind, value):
            return {'node': 'Constant', 'type': kind, 'value': value}
        def parameter(label, kind, annotation, present=False, value=None):
            return {'name': label, 'kind': kind, 'annotation': annotation,
                    'default': {'present': present, 'value': value}}
        # The same literal expectation runs on every CI interpreter/OS.
        self.assertEqual(guard.signature(function), {
            'async': True, 'returns': name('dict'), 'parameters': [
                parameter('a', 'POSITIONAL_ONLY', name('int')),
                parameter('b', 'POSITIONAL_ONLY', name('str'), True, constant('str', '中文')),
                parameter('c', 'POSITIONAL_OR_KEYWORD',
                          {'node': 'Subscript', 'value': name('list'), 'slice': name('dict')},
                          True, constant('NoneType', None)),
                parameter('items', 'VAR_POSITIONAL', name('bytes')),
                parameter('required', 'KEYWORD_ONLY', name('bool')),
                parameter('optional', 'KEYWORD_ONLY', name('int'), True, constant('int', 2)),
                parameter('extra', 'VAR_KEYWORD', name('dict')),
            ]})
        self.assertEqual(guard.signature(ast.parse('def f(): pass').body[0]),
                         {'parameters': [], 'returns': None, 'async': False})

    def test_formatting_forward_annotations_and_ast_metadata_do_not_change_signature(self):
        before = ast.parse('def f(x: dict | None = None) -> list[dict]: pass').body[0]
        after = ast.parse('def f( x: "dict|None" = (None), ) -> "list[dict]": pass').body[0]
        ast.increment_lineno(after, 200)
        after.args.args[0].annotation.kind = 'interpreter-only-metadata'
        with patch.object(ast, 'dump', side_effect=AssertionError('AST repr is not a contract')):
            self.assertEqual(guard.signature(before), guard.signature(after))

    def test_default_values_preserve_type_and_structure_without_execution(self):
        def sig(default):
            return guard.signature(ast.parse(f'def f(x={default}): pass').body[0])
        values = ['None', 'True', '1', '1.0', '"1"', 'b"1"', '[1]', '(1,)', '{1}',
                  '{"x": 1}', '...', '-1', '1j']
        encoded = [json.dumps(sig(value), sort_keys=True) for value in values]
        self.assertEqual(len(set(encoded)), len(values))
        for left, right in zip(values, values[1:]):
            self.assertNotEqual(sig(left), sig(right))
        self.assertEqual(sig("{'x': [1, None]}"), sig('{ "x" : [ 1, (None) ] }'))
        with patch('builtins.__import__', side_effect=AssertionError('defaults must not execute')):
            guard.signature(ast.parse('def f(x=__import__("never_import_this")): pass').body[0])
        with self.assertRaisesRegex(ValueError, 'Unsupported signature expression'):
            sig('[x for x in ()]')

    def test_real_mcp_parameter_and_return_changes_are_rejected(self):
        original = (ROOT / 'value_lab/server.py').read_text(encoding='utf-8')
        changes = [
            ('suite: dict, samples: dict | None = None', 'suite: dict'),
            ('samples: dict | None = None', 'samples: dict | None = {}'),
            ('samples: dict | None = None', 'samples: dict | None'),
            ('samples: dict | None = None', 'samples: list | None = None'),
            ('samples: dict | None = None', 'other: dict | None = None'),
            ('suite: dict, samples:', 'suite: dict, *, samples:'),
            ('suite: dict, samples:', 'suite: dict, /, samples:'),
            ('suite: dict, samples: dict | None = None',
             'samples: dict | None = None, suite: dict = None'),
            ('example_value_suite() -> dict', 'example_value_suite(extra=None) -> dict'),
            ('example_value_suite() -> dict', 'example_value_suite() -> list'),
            ('def example_value_suite()', 'async def example_value_suite()'),
            ('action: str, context:', 'action: bytes, context:'),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / 'value_lab', root / 'value_lab', ignore=shutil.ignore_patterns('__pycache__'))
            (root / 'docs').mkdir()
            shutil.copyfile(ROOT / 'docs/feature-freeze.json', root / 'docs/feature-freeze.json')
            server = root / 'value_lab/server.py'
            server.write_text(original, encoding='utf-8')
            # Keep the other inventories fixed; exercise actual AST extraction,
            # normalization and comparison against the shipped frozen signatures.
            actual_surface = guard.surface
            frozen = json.loads((ROOT / 'docs/feature-freeze.json').read_text(encoding='utf-8'))
            def changed_surface(_):
                return {**frozen['surface'], 'mcp_signatures': actual_surface(root)['mcp_signatures']}
            with patch.object(guard, 'surface', side_effect=changed_surface):
                self.assertEqual(guard.check()['issues'], [])
                for old, new in changes:
                    with self.subTest(change=new):
                        self.assertIn(old, original)
                        server.write_text(original.replace(old, new, 1), encoding='utf-8')
                        self.assertIn('Frozen surface changed: mcp_signatures', guard.check()['issues'])

    def test_unknown_signature_syntax_fails_closed(self):
        with patch.object(guard, 'surface', side_effect=ValueError('Unsupported signature expression')):
            self.assertEqual(guard.check()['status'], 'FAIL')

    def test_current_surface_and_eight_mainline_documents(self):
        result = guard.check()
        self.assertEqual(result['issues'], [])
        self.assertEqual(len(result['mainline_documents']), 8)
        self.assertFalse(result['automatic_unfreeze'])

    def test_added_command_tool_module_or_grader_fails(self):
        frozen = guard.surface()
        for key in ('commands', 'mcp_signatures', 'runtime_modules', 'grader_allowlists'):
            with self.subTest(key=key):
                changed = copy.deepcopy(frozen)
                if isinstance(changed[key], dict):
                    changed[key]['new-feature'] = []
                else:
                    changed[key].append('new-feature')
                with patch.object(guard, 'surface', return_value=changed):
                    self.assertIn('Frozen surface changed: ' + key, guard.check()['issues'])

    def test_ninth_document_and_sixth_command_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / 'docs', root / 'docs')
            for p in ROOT.glob('*.md'):
                shutil.copyfile(p, root / p.name)
            (root / 'docs/extra').mkdir()
            (root / 'docs/extra/NEW.md').write_text('A nested guide must count too', encoding='utf-8')
            with (root / 'README.md').open('a', encoding='utf-8') as f:
                f.write('\npython scripts/value_lab.py diagnose\n')
            issues, _ = guard.documentation_issues(root)
            self.assertTrue(any('exceeds 8' in i for i in issues))
            self.assertTrue(any('five golden' in i for i in issues))

    def test_five_commands_work_in_relocated_offline_directory(self):
        for encoding in (None, 'cp1252:strict', 'ascii:strict', 'utf-8:strict'):
            with self.subTest(encoding=encoding):
                self._five_commands(encoding)

    def _five_commands(self, encoding):
        from value_lab.core import load_json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '新同事 workspace'
            root.mkdir()
            shutil.copytree(ROOT / 'value_lab', root / 'value_lab', ignore=shutil.ignore_patterns('__pycache__'))
            (root / 'scripts').mkdir()
            shutil.copyfile(ROOT / 'scripts/value_lab.py', root / 'scripts/value_lab.py')
            shutil.copytree(ROOT / 'examples/first-run', root / 'examples/first-run')
            readme_commands = []
            for readme in ('README.md', 'README.zh-CN.md'):
                commands = re.findall(r'^python scripts/value_lab.py .+$', (ROOT / readme).read_text(encoding='utf-8'), re.M)
                readme_commands.append(commands)
                self.assertEqual([shlex.split(c)[2] for c in commands], guard.GOLDEN)
            self.assertEqual(*readme_commands)
            env = dict(os.environ)
            env.pop('PYTHONIOENCODING', None)
            env.pop('PYTHONUTF8', None)
            if encoding:
                env.update(PYTHONIOENCODING=encoding, PYTHONUTF8='0')
            # Execute once: both READMEs contain byte-identical commands.
            for command in commands:
                argv = [sys.executable, '-B', *shlex.split(command)[1:]]
                result = subprocess.run(argv, cwd=root, capture_output=True, timeout=60, env=env)
                self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
                payload = json.loads(result.stdout.decode('ascii'))
                self.assertIsInstance(payload, dict)
            usage = root / 'work/first-run/usage/USAGE.md'
            self.assertTrue(usage.is_file())
            self.assertIn('SIMULATION\\_ONLY', usage.read_text(encoding='utf-8'))
            self.assertEqual(load_json(usage.parent / 'card.json')['source']['evidence_type'], 'synthetic')
            self.assertTrue((root / 'work/first-run/comparison.json').is_file())
            self.assertFalse(any(r['color'] == 'green' for r in load_json(usage.parent/'card.json')['envelope']['rows']))
            comparison_path = root / 'work/first-run/comparison.json'
            comparison = load_json(comparison_path)
            self.assertEqual(payload['blockers'], comparison['blockers'])
            self.assertTrue(any(ord(c) > 127 for c in ''.join(comparison['blockers'])))
            self.assertIn(comparison['blockers'][0], comparison_path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
