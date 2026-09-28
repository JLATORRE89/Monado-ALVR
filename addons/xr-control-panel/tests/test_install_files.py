"""install.sh must deploy every local module server.py imports (a missing one crash-loops the panel)."""
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallFilesTests(unittest.TestCase):
    def test_every_local_import_is_installed(self):
        server = (ROOT / 'server.py').read_text()
        imported = set(re.findall(r'^(?:from|import)\s+(\w+)', server, re.M))
        local = {name for name in imported if (ROOT / f'{name}.py').is_file()}
        installed = set(re.findall(r'"\$SRC/(\w+)\.py"', (ROOT / 'install.sh').read_text()))
        self.assertTrue(local, 'no local modules found')
        self.assertEqual(sorted(local - installed), [])


if __name__ == '__main__':
    unittest.main()
