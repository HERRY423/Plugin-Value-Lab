"""Guard the requested freeze and runnable README without claiming human timing."""
import copy
import importlib.util
import json
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
        from value_lab.core import load_json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'new colleague workspace'
            root.mkdir()
            shutil.copytree(ROOT / 'value_lab', root / 'value_lab', ignore=shutil.ignore_patterns('__pycache__'))
            (root / 'scripts').mkdir()
            shutil.copyfile(ROOT / 'scripts/value_lab.py', root / 'scripts/value_lab.py')
            shutil.copytree(ROOT / 'examples/first-run', root / 'examples/first-run')
            for readme in ('README.md', 'README.zh-CN.md'):
                commands = re.findall(r'^python scripts/value_lab.py .+$', (ROOT / readme).read_text(encoding='utf-8'), re.M)
                self.assertEqual([shlex.split(c)[2] for c in commands], guard.GOLDEN)
            # Execute once: both READMEs contain byte-identical commands.
            for command in commands:
                argv = [sys.executable, '-B', *shlex.split(command)[1:]]
                result = subprocess.run(argv, cwd=root, capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
            usage = root / 'work/first-run/usage/USAGE.md'
            self.assertTrue(usage.is_file())
            self.assertIn('SIMULATION\\_ONLY', usage.read_text(encoding='utf-8'))
            self.assertEqual(load_json(usage.parent / 'card.json')['source']['evidence_type'], 'synthetic')
            self.assertTrue((root / 'work/first-run/comparison.json').is_file())
            self.assertFalse(any(r['color'] == 'green' for r in load_json(usage.parent/'card.json')['envelope']['rows']))


if __name__ == '__main__':
    unittest.main()
