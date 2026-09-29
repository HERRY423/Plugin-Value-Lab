"""Evidence retention tests; these mocks do not establish kernel isolation."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('kernel_acceptance',
    Path(__file__).resolve().parents[1] / 'scripts/check_kernel_acceptance.py')
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)


class KernelEvidenceTests(unittest.TestCase):
    def exercise(self, codes, receipts):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name) / 'evidence'
        calls = []
        def execute(command, **kwargs):
            gate = Path(command[-1])
            calls.append(gate.name)
            gate.mkdir()
            (gate / 'boundary').mkdir()
            (gate / 'boundary/stderr.txt').write_text('bwrap: permission denied (manufactured)')
            (gate / '.hidden-cassette').write_text('manufactured replay')
            # Windows cannot create this name; Linux additionally exercises it.
            name = 'canary\nwith newline.txt' if kernel.os.name != 'nt' else 'canary with spaces.txt'
            (gate / name).write_text('manufactured canary')
            if gate.name in receipts:
                (gate / 'acceptance.json').write_text(json.dumps({'status': receipts[gate.name]}))
            return subprocess.CompletedProcess(command, codes[gate.name])
        stream = io.StringIO()
        with patch.object(kernel, 'environment', return_value={'scope': 'MOCK'}), \
             patch.object(kernel.subprocess, 'run', side_effect=execute), contextlib.redirect_stdout(stream):
            receipt = kernel.run(root)
        return root, receipt, calls, stream.getvalue()

    def test_first_failure_retains_stderr_and_still_runs_second_gate(self):
        root, receipt, calls, stdout = self.exercise({'offline': 1, 'online': 0}, {'online': 'PASS'})
        self.assertEqual(calls, ['offline', 'online'])
        self.assertEqual(receipt['status'], 'FAIL')
        self.assertIn('bwrap: permission denied', stdout)
        with tarfile.open(root.with_suffix('.tar.gz')) as archive:
            names = archive.getnames()
            self.assertIn('evidence/offline/.hidden-cassette', names)
            canaries = [n for n in names if 'canary' in n]
            self.assertEqual(len(canaries), 2)
            if kernel.os.name != 'nt':
                self.assertTrue(all('\n' in n for n in canaries))
        manifest = json.loads((root / 'manifest.json').read_text())
        self.assertIn('offline/boundary/stderr.txt', manifest['files'])

    def test_success_requires_both_zero_exits_and_pass_receipts(self):
        for codes, receipts, expected in [({'offline': 0, 'online': 0}, {'offline': 'PASS', 'online': 'PASS'}, 'PASS'),
                ({'offline': 0, 'online': 0}, {'offline': 'PASS'}, 'FAIL'),
                ({'offline': 0, 'online': 1}, {'offline': 'PASS', 'online': 'PASS'}, 'FAIL')]:
            with self.subTest(codes=codes, receipts=receipts):
                self.assertEqual(self.exercise(codes, receipts)[1]['status'], expected)


if __name__ == '__main__':
    unittest.main()
