"""Pulling stored updates from another panel: share keys, pinned HTTPS, verified transfer."""
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from software_updates import UpdateLibrary  # noqa: E402
import update_peers  # noqa: E402


def firmware_zip(build='200'):
    f = io.BytesIO()
    with zipfile.ZipFile(f, 'w') as z:
        z.writestr('META-INF/com/android/metadata',
                   f'pre-device=testquest\npost-build-incremental={build}\npost-timestamp={build}')
        z.writestr('payload.bin', b'fake test payload ' * 1000)
    return f.getvalue()


class PeerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / 'config.json').write_text(json.dumps({'updates_dir': str(d / 'source-updates'),
                                                   'capture_dir': str(d / 'captures')}))
        self.env = patch.dict(os.environ, XR_PANEL_CONFIG=str(d / 'config.json'))
        self.env.start()
        spec = importlib.util.spec_from_file_location('panel_peer_source', ROOT / 'server.py')
        self.s = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.s)
        # Source panel: one stored firmware, served over HTTPS.
        data = firmware_zip()
        self.stored = self.s.UPDATES.upload('fw.zip', 'firmware', len(data), io.BytesIO(data))['update']
        cert, key = self.s.ensure_tls_cert(['127.0.0.1'])
        self.srv = self.s.create_https_server(0, cert, key)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]
        self.share = self.s.SHARE_KEYS.create('Test panel')
        # Pulling panel: its own library and peer list.
        self.lib = UpdateLibrary(d / 'pull-updates', None, lambda: [], None)
        self.peers = update_peers.Peers(d / 'peers.json', self.lib)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.env.stop()
        self.tmp.cleanup()

    def get(self, path, key=None):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection('127.0.0.1', self.port, context=ctx, timeout=5)
        conn.request('GET', path, headers={'Authorization': 'Bearer ' + key} if key else {})
        res = conn.getresponse()
        body = res.read()
        conn.close()
        return res.status, body

    def test_share_key_is_read_only_and_revocable(self):
        self.assertEqual(self.get('/api/share/updates')[0], 401)
        self.assertEqual(self.get('/api/share/updates', 'wrong-key-wrong-key-wrong')[0], 401)
        status, body = self.get('/api/share/updates', self.share['key'])
        self.assertEqual(status, 200)
        rows = json.loads(body)['updates']
        self.assertEqual([r['sha256'] for r in rows], [self.stored['sha256']])
        self.assertNotIn('metadata', rows[0])
        status, body = self.get(f"/api/share/updates/{self.stored['sha256']}/download", self.share['key'])
        self.assertEqual((status, len(body)), (200, self.stored['size']))
        # The key opens nothing else in the panel (for a client on the network; this PC is trusted).
        h = object.__new__(self.s.Handler)
        h.client_address = ('192.0.2.40', 5000)
        h.command, h.path = 'GET', '/api/updates'
        h.headers = {'Authorization': 'Bearer ' + self.share['key']}
        sent = []
        h.send = lambda *a: sent.append(a)
        self.assertFalse(h.authorized())
        self.assertEqual(sent[0][0], 401)
        self.s.SHARE_KEYS.revoke(self.share['id'])
        self.assertEqual(self.get('/api/share/updates', self.share['key'])[0], 401)
        self.assertNotIn(self.share['key'], (Path(self.tmp.name) / 'update-share-keys.json').read_text())

    def test_pull_verified_copy(self):
        added = self.peers.add(f'127.0.0.1:{self.port}', self.share['key'])
        pid = added['id']
        cert_fp = update_peers.pretty(update_peers.cert_fingerprint_file(self.s.TLS_DIR / 'cert.pem'))
        self.assertEqual(added['fingerprint'], cert_fp)
        rows = self.peers.remote_updates(pid)
        self.assertEqual([(r['sha256'], r['stored']) for r in rows], [(self.stored['sha256'], False)])
        self.peers.pull(pid, self.stored['sha256'])
        for _ in range(100):
            job = self.peers.pull_jobs()[0]
            if job['state'] != 'running':
                break
            time.sleep(0.05)
        self.assertEqual(job['state'], 'done', job['message'])
        self.assertEqual(self.lib.get(self.stored['sha256'])['sha256'], self.stored['sha256'])
        self.assertTrue(self.peers.remote_updates(pid)[0]['stored'])
        self.assertIn('already stored', self.peers.pull(pid, self.stored['sha256'])['message'])
        self.assertNotIn('key', json.dumps(self.peers.public()))

    def test_changed_certificate_is_refused_before_the_key_is_sent(self):
        pid = self.peers.add(f'127.0.0.1:{self.port}', self.share['key'])['id']
        self.peers.data['peers'][pid]['fingerprint'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'certificate changed'):
            self.peers.remote_updates(pid)

    def test_bad_key_or_address_is_not_added(self):
        with self.assertRaisesRegex(RuntimeError, 'refused the share key'):
            self.peers.add(f'127.0.0.1:{self.port}', 'x' * 43)
        with self.assertRaises(ValueError):
            self.peers.add('not an address!', self.share['key'])
        self.assertEqual(self.peers.public(), [])

    def test_address_forms(self):
        p = update_peers.parse_address
        self.assertEqual(p('192.168.1.50'), ('192.168.1.50', 8483))
        self.assertEqual(p('https://192.168.1.50:9443/'), ('192.168.1.50', 9443))
        self.assertEqual(p('[fd12::5]:8483'), ('fd12::5', 8483))
        self.assertEqual(p('office-pc.local'), ('office-pc.local', 8483))


if __name__ == '__main__':
    unittest.main()
