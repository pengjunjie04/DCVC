import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ('start_encoder.sh', 'start_decoder.sh', 'tools/start_common.sh')


class StartScriptTests(unittest.TestCase):
    def test_start_scripts_parse_and_entry_points_are_executable(self):
        for name in SCRIPTS:
            with self.subTest(name=name):
                path = ROOT / name
                self.assertTrue(path.is_file())
                subprocess.run(['bash', '-n', str(path)], check=True)
        for name in SCRIPTS[:2]:
            self.assertTrue(os.access(ROOT / name, os.X_OK))


if __name__ == '__main__':
    unittest.main()
