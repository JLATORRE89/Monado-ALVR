"""Focused authorization/network regressions; no headset or service changes."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from usb_pairing import UsbPairing


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.now = 1000.0
        self.registry = UsbPairing(self.path / 'pairs.json', clock=lambda: self.now)
        self.env = patch.dict(os.environ, XR_PANEL_CONFIG=str(self.path / 'config.json'))
        self.env.start()
        spec = importlib.util.spec_from_file_location('panel_under_test', ROOT / 'server.py')
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.server.USB_PAIRS = self.registry
        self.server.CFG.update(lan_access=True, auto_authorize_usb=True)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_persistent_cookie_not_ip_authorization(self):
        token = self.registry.begin('quest', 'Quest 3')
        self.assertFalse(self.registry.authorized(token))
        self.assertTrue(self.registry.accept(token))
        self.assertTrue(UsbPairing(self.path / 'pairs.json').authorized(token))
        self.assertFalse(self.registry.authorized('wrong'))
        self.assertNotIn(token, (self.path / 'pairs.json').read_text())
        self.assertEqual((self.path / 'pairs.json').stat().st_mode & 0o777, 0o600)
        self.assertIsNone(self.registry.begin('quest', 'Quest 3'))
        self.assertNotIn('digest', self.registry.public()[0])

    def test_revocation_stays_revoked_until_manual_pair(self):
        token = self.registry.begin('quest', 'Quest')
        self.registry.accept(token)
        self.registry.revoke()
        self.assertFalse(self.registry.authorized(token))
        self.assertIsNone(UsbPairing(self.path / 'pairs.json').begin('quest', 'Quest'))
        new = self.registry.begin('quest', 'Quest', manual=True)
        self.assertTrue(self.registry.accept(new))
        self.assertFalse(self.registry.authorized(token))

    def test_expiry_retries_and_separate_devices(self):
        first = self.registry.begin('one', 'Quest')
        second = self.registry.begin('two', 'Quest')
        self.assertNotEqual(first, second)
        self.now += 301
        self.assertFalse(self.registry.accept(first))
        for _ in range(2):
            self.assertIsNotNone(self.registry.begin('one', 'Quest'))
            self.now += 121
        self.assertIsNone(self.registry.begin('one', 'Quest'))
        self.assertEqual(self.registry.public()[0]['state'], 'failed')

    def test_only_authorized_physical_quest_usb(self):
        devs = [dict(serial='unauthorized', state='unauthorized', usb_path='1-1'),
                dict(serial='wifi', state='device', usb_path=None),
                dict(serial='phone', state='device', usb_path='1-2'),
                dict(serial='quest', state='device', usb_path='1-3')]
        def info(d):
            return dict(d, model='Quest', is_quest=d['serial']=='quest', ip='192.0.2.10')
        with patch.object(self.server, 'list_adb_devices', return_value=devs), \
             patch.object(self.server, 'headset_info', side_effect=info) as read, \
             patch.object(self.server, 'issue_usb_pairing') as issue:
            self.server.auto_pair_usb_once()
            self.assertEqual([c.args[0]['serial'] for c in read.call_args_list], ['phone','quest'])
            self.assertEqual(issue.call_count, 1)
            self.assertEqual(issue.call_args.args[0]['serial'], 'quest')
            self.server.CFG['auto_authorize_usb'] = False
            self.server.auto_pair_usb_once()
            self.assertEqual(issue.call_count, 1)
            self.server.CFG.update(auto_authorize_usb=True, lan_access=False)
            self.server.auto_pair_usb_once()
            self.assertEqual(issue.call_count, 1)

    def test_ipv6_url_and_no_repeated_browser_launch(self):
        info = dict(serial='quest', model='Quest', ipv6=['fd12:3456::20'])
        with patch.object(self.server, 'lan_address_for', return_value='fd12:3456::1'), \
             patch.object(self.server, 'adb', return_value=subprocess.CompletedProcess([],0,'','')) as adb:
            self.server.issue_usb_pairing(info)
            url = adb.call_args.args[-1]
            self.assertIn('http://[fd12:3456::1]:8083/?pair=', url)
            self.server.issue_usb_pairing(info)
            self.assertEqual(adb.call_count, 1)

    def test_addresses_and_route_fallback(self):
        self.assertEqual(self.server.valid_ipv6_addresses('::1 fd12::2 bad fe80::3 fd12::2'), ['fd12::2','fe80::3'])
        with patch.object(self.server, 'lan_address_for', side_effect=[RuntimeError('no v4'),'fd12::1']) as route:
            self.assertEqual(self.server.pairing_address(dict(ip='192.0.2.2',ipv6=['fd12::2'])), 'fd12::1')
            self.assertEqual(route.call_args.args[0], 'fd12::2')
        with self.assertRaises(RuntimeError):
            self.server.pairing_address(dict(ipv6=['fe80::2']))
        with patch.object(self.server.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,'fd12::2 dev eno1 src fd12::1\n','')) as run:
            self.assertEqual(self.server.lan_address_for('fd12::2'),'fd12::1')
            self.assertEqual(run.call_args.args[0][:2], ['ip','-6'])

    def test_setting_types_and_preservation(self):
        self.server.CONFIG_PATH.write_text(json.dumps({'port':9000,'runtime_root':'keep'}))
        self.server.set_auto_authorize_usb(True)
        conf=json.loads(self.server.CONFIG_PATH.read_text())
        self.assertEqual(conf, dict(port=9000,runtime_root='keep',auto_authorize_usb=True))
        with self.assertRaises(ValueError): self.server.set_auto_authorize_usb('false')

    def test_remote_request_cookie_handshake_and_revoke(self):
        h = object.__new__(self.server.Handler)
        h.client_address=('fd12::99', 5000)
        h.headers={}; h.command='GET'; h.path='/'
        sent=[]
        h.send=lambda *a:sent.append(a)
        h.send_response=lambda *a:sent.append(a)
        h.send_header=lambda *a:sent.append(a)
        h.end_headers=lambda:None
        self.assertFalse(h.authorized())
        token=self.registry.begin('quest','Quest')
        h.path='/?pair='+token
        self.assertFalse(h.authorized()) # redirects after setting cookie
        self.assertTrue(any(a[0]=='Set-Cookie' for a in sent))
        h.path='/api/status';h.headers={'Cookie':'xrpanel='+token}
        self.assertTrue(h.authorized())
        h.client_address=('192.0.2.123', 5000) # DHCP/family changes do not lose identity
        self.assertTrue(h.authorized())
        self.registry.revoke()
        self.assertFalse(h.authorized())
        h.client_address=('::ffff:127.0.0.1',5000)
        self.assertTrue(h.authorized())

    @unittest.skipUnless(socket.has_dualstack_ipv6(), 'dual-stack IPv6 unavailable')
    def test_live_ipv4_and_ipv6_http(self):
        srv=self.server.create_http_server('127.0.0.1',0,True)
        thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
        try:
            port=srv.server_address[1]
            for host in ('127.0.0.1','::1'):
                conn=http.client.HTTPConnection(host,port,timeout=3)
                conn.request('GET','/api/panel/access');response=conn.getresponse()
                self.assertEqual(response.status,200);self.assertIn('auto_authorize_usb',json.loads(response.read()));conn.close()
        finally:
            srv.shutdown();srv.server_close();thread.join()


if __name__=='__main__': unittest.main()
