"""Menu labels, removable shortcuts and Python file validation; no live runtime."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

class MenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        with patch.dict(os.environ, XR_PANEL_CONFIG=str(self.path/'config.json')):
            spec = importlib.util.spec_from_file_location('menu_server', ROOT/'server.py')
            self.server = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.server)
        self.server.LOFT_MENU = self.path/'menu.tsv'

    def tearDown(self):
        self.temp.cleanup()

    def test_friendly_label_and_package_fallback(self):
        responses = [subprocess.CompletedProcess([],0,'',''), subprocess.CompletedProcess([],0,'{"com.example.game":"Example Game"}','')]
        with patch.object(self.server,'headset_packages',return_value=['com.example.game','com.example.unknown']), patch.object(self.server,'adb',side_effect=responses):
            result = self.server.headset_apps('quest')
        self.assertIn({'label':'Example Game','package':'com.example.game'},result['apps'])
        self.assertIn({'label':'com.example.unknown','package':'com.example.unknown'},result['apps'])

    def test_failed_label_lookup_is_visible(self):
        with patch.object(self.server,'headset_packages',return_value=['com.example.game']), patch.object(self.server,'adb',side_effect=RuntimeError()):
            self.assertTrue(self.server.headset_apps('quest')['warning'])

    def test_python_and_apk_shortcuts_roundtrip_and_remove(self):
        script=self.path/'my game.py'
        script.write_text('print("test")')
        items=[dict(enabled=True,type='pc',id='python',title='Python Game',subtitle='',target=str(script)),
               dict(enabled=True,type='apk',id='quest',title='Friendly Game',subtitle='',target='com.example.game')]
        with patch.object(self.server.subprocess,'run',return_value=subprocess.CompletedProcess([],1,b'')):
            self.server.save_menu(items)
            self.assertEqual(self.server.load_menu(),items)
            self.server.save_menu([])
            self.assertEqual(self.server.load_menu(),[])
        self.assertTrue(script.exists())

    def test_non_executable_non_python_rejected(self):
        path=self.path/'game.txt';path.write_text('x')
        with self.assertRaises(ValueError):
            self.server.save_menu([dict(enabled=True,type='pc',id='bad',title='Bad',subtitle='',target=str(path))])

if __name__ == '__main__': unittest.main()
