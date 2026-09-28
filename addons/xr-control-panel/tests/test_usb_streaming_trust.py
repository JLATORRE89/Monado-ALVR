"""A Quest seen on USB becomes an approved device and is trusted by ALVR for Wi-Fi streaming."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class StreamingTrustTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.registry = self.path / 'approved.json'
        (self.path / 'config.json').write_text(json.dumps({
            'updates_dir': str(self.path / 'updates'), 'approved_registry': str(self.registry),
            'lan_access': False}))
        self.env = patch.dict(os.environ, XR_PANEL_CONFIG=str(self.path / 'config.json'))
        self.env.start()
        spec = importlib.util.spec_from_file_location('panel_trust_under_test', ROOT / 'server.py')
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.calls = []

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def fake_alvr(self, path, method='GET', data=None, base=None):
        self.calls.append((base, data))
        return b'{}'

    def run_once(self, ip, mac='2c:26:17:aa:bb:cc', client=True, quest=True):
        dev = [{'serial': 'Q1', 'state': 'device', 'usb_path': '1-2', 'model': 'Quest 2'}]
        info = {'serial': 'Q1', 'model': 'Quest 2', 'ip': ip, 'ipv6': [], 'is_quest': quest,
                'client_installed': client}
        self.server._usb_checked.clear()
        with patch.object(self.server, 'list_adb_devices', return_value=dev), \
             patch.object(self.server, 'headset_info', return_value=info), \
             patch.object(self.server, 'adb', return_value=subprocess.CompletedProcess(
                 [], 0, f'wifi_sta_factory_mac_address={mac}\n mRandomizedMacAddress: ba:49:9d:17:62:e0\n', '')), \
             patch.object(self.server, 'alvr', side_effect=self.fake_alvr):
            self.server.auto_pair_usb_once()

    def test_usb_headset_is_approved_and_trusted_without_lan_access(self):
        self.run_once('192.168.86.170')
        reg = json.loads(self.registry.read_text())
        self.assertEqual(reg['devices'][0]['mac_address'], '2C:26:17:AA:BB:CC')
        self.assertEqual(reg['devices'][0]['wifi_ip'], '192.168.86.170')
        self.assertEqual(reg['devices'][0]['network_mac'], 'BA:49:9D:17:62:E0')
        actions = [c[1] for c in self.calls]
        self.assertIn(['usb-Q1', {'AddIfMissing': {'trusted': True, 'manual_ips': ['192.168.86.170']}}], actions)
        self.assertIn(['usb-Q1', 'Trust'], actions)
        self.assertEqual((self.registry.stat().st_mode & 0o777), 0o600)

    def test_new_wifi_address_is_refreshed_and_unchanged_is_not_rewritten(self):
        self.run_once('192.168.86.170')
        n = len(self.calls)
        self.run_once('192.168.86.170')
        self.assertEqual(len(self.calls), n)  # nothing changed: no ALVR calls
        self.run_once('192.168.86.171')
        self.assertIn(['usb-Q1', {'SetManualIps': ['192.168.86.171']}], [c[1] for c in self.calls])

    def test_ignores_non_quest_and_headsets_without_the_client(self):
        self.run_once('192.168.86.170', quest=False)
        self.run_once('192.168.86.170', client=False)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.registry.exists())

    def test_instance_headset_uses_its_instance_api(self):
        home = self.path / 'home'
        inst = home / '.config/intel-xr/instances'
        inst.mkdir(parents=True)
        (inst / 'quest-b.env').write_text('XR_INSTANCE_INDEX=2\nALVR_WIRED_SERIAL=Q1\n')
        with patch.object(self.server.Path, 'home', return_value=home):
            self.run_once('192.168.86.170')
        self.assertTrue(all(base == 'http://127.0.0.1:8092' for base, _ in self.calls))


if __name__ == '__main__':
    unittest.main()
