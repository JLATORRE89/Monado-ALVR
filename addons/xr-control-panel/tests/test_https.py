"""HTTPS listener for Wi-Fi headset browsers (microphone needs a secure page)."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class HttpsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / 'config.json').write_text(json.dumps({'updates_dir': str(self.d / 'updates'),
                                                        'capture_dir': str(self.d / 'captures')}))
        self.env = patch.dict(os.environ, XR_PANEL_CONFIG=str(self.d / 'config.json'))
        self.env.start()
        spec = importlib.util.spec_from_file_location('panel_https_under_test', ROOT / 'server.py')
        self.s = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.s)
        from usb_pairing import UsbPairing
        self.s.USB_PAIRS = UsbPairing(self.d / 'pairs.json')

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def sans(self, cert):
        return subprocess.run(['openssl', 'x509', '-in', str(cert), '-noout', '-ext', 'subjectAltName'],
                              capture_output=True, text=True, check=True).stdout

    def test_cert_covers_lan_addresses_and_is_reused(self):
        cert, key = self.s.ensure_tls_cert(['192.0.2.7'])
        self.assertIn('192.0.2.7', self.sans(cert))
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        first = cert.read_bytes()
        self.s.ensure_tls_cert(['192.0.2.7'])
        self.assertEqual(cert.read_bytes(), first)          # same addresses: kept
        self.s.ensure_tls_cert(['192.0.2.8'])
        self.assertIn('192.0.2.8', self.sans(cert))          # new address (DHCP change): reissued

    def test_https_serves_paired_browsers_only(self):
        cert, key = self.s.ensure_tls_cert(['192.0.2.7'])
        srv = self.s.create_https_server(0, cert, key)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        port = srv.server_address[1]
        ctx = ssl.create_default_context(cafile=str(cert))
        ctx.check_hostname = False
        conn = http.client.HTTPSConnection('127.0.0.1', port, context=ctx, timeout=5)
        conn.request('GET', '/api/voice/status')
        self.assertEqual(conn.getresponse().status, 200)      # loopback is this PC
        conn.close()
        # A plain-HTTP client on the TLS port must not stall the listener.
        raw = socket.create_connection(('127.0.0.1', port), timeout=5)
        raw.sendall(b'GET / HTTP/1.0\r\n\r\n')
        conn = http.client.HTTPSConnection('127.0.0.1', port, context=ctx, timeout=5)
        conn.request('GET', '/api/whoami')
        self.assertEqual(conn.getresponse().status, 200)
        conn.close(); raw.close()

    def test_https_off_without_lan_access(self):
        self.s.CFG.update(lan_access=False)
        with patch.object(self.s, 'create_https_server') as create:
            self.s.start_https()
        create.assert_not_called()
        self.assertIsNone(self.s.HTTPS_PORT[0])


if __name__ == '__main__':
    unittest.main()
