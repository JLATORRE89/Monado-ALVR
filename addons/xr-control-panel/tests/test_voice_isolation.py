"""Each headset captures its own view and sees only its own voice/GPU results."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class VoiceIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / 'config.json').write_text(json.dumps({'updates_dir': str(d / 'updates'),
                                                   'capture_dir': str(d / 'captures')}))
        self.env = patch.dict(os.environ, XR_PANEL_CONFIG=str(d / 'config.json'))
        self.env.start()
        spec = importlib.util.spec_from_file_location('panel_voice_under_test', ROOT / 'server.py')
        self.s = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.s)
        from device_identity import DeviceIdentity
        from usb_pairing import UsbPairing
        self.s.DEVICE_IDS = DeviceIdentity(d / 'ids.json')
        self.s.USB_PAIRS = UsbPairing(d / 'pairs.json')
        gw = self.s.gpu_worker
        self.patches = [patch.object(gw, 'JOBS_FILE', d / 'jobs.json'), patch.object(gw, 'STATE_DIR', d)]
        for p in self.patches:
            p.start()
        out = d / 'captures' / gw.OUTPUT_FOLDER
        out.mkdir(parents=True)
        for name in ('gpu-aaaa-0.png', 'gpu-bbbb-0.png'):
            (out / name).write_bytes(b'\x89PNG')
        gw._save_jobs([
            {'request_id': 'aaaaaaaa-0000-0000-0000-000000000000', 'workflow': 'detect', 'prompt': 'Find dogs',
             'source': 'QA/shot.jpg', 'review_serial': 'QA', 'review_state': 'ready', 'outputs': ['gpu-aaaa-0.png'],
             'status': 'complete', 'created': 1},
            {'request_id': 'bbbbbbbb-0000-0000-0000-000000000000', 'workflow': 'detect', 'prompt': 'Find a ball',
             'source': 'QB/shot.jpg', 'review_serial': 'QB', 'review_state': 'ready', 'outputs': ['gpu-bbbb-0.png'],
             'status': 'complete', 'created': 2}])
        self.cookie_a = 'xrdevice=' + self.s.DEVICE_IDS.issue('QA')
        self.srv = self.s.create_http_server('127.0.0.1', 0, False)
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close(); self.thread.join()
        for p in self.patches:
            p.stop()
        self.env.stop(); self.tmp.cleanup()

    def req(self, method, path, cookie=None, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.srv.server_address[1], timeout=5)
        headers = {'Cookie': cookie} if cookie else {}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        r = conn.getresponse(); data = r.read(); conn.close()
        return r.status, data

    def test_whoami(self):
        with patch.object(self.s, 'list_adb_devices', return_value=[{'serial': 'QA', 'model': 'Quest 2'}]):
            self.assertEqual(json.loads(self.req('GET', '/api/whoami', self.cookie_a)[1])['serial'], 'QA')
        self.assertEqual(json.loads(self.req('GET', '/api/whoami')[1])['role'], 'operator')

    def test_device_link_sets_cookie(self):
        token = self.s.DEVICE_IDS.issue('QB')
        conn = http.client.HTTPConnection('127.0.0.1', self.srv.server_address[1], timeout=5)
        conn.request('GET', '/gpu-review/bbbbbbbb-0000-0000-0000-000000000000?device=' + token)
        r = conn.getresponse(); r.read(); conn.close()
        self.assertEqual(r.status, 303)
        self.assertIn('xrdevice=' + token, r.getheader('Set-Cookie'))
        self.assertEqual(r.getheader('Location'), '/gpu-review/bbbbbbbb-0000-0000-0000-000000000000')

    def test_jobs_reviews_and_images_are_per_headset(self):
        jobs = json.loads(self.req('GET', '/api/gpu/jobs', self.cookie_a)[1])['jobs']
        self.assertEqual([j['review_serial'] for j in jobs], ['QA'])
        self.assertEqual(len(json.loads(self.req('GET', '/api/gpu/jobs')[1])['jobs']), 2)  # operator
        self.assertEqual(self.req('GET', '/gpu-review/bbbbbbbb-0000-0000-0000-000000000000', self.cookie_a)[0], 404)
        self.assertEqual(self.req('GET', '/gpu-review/aaaaaaaa-0000-0000-0000-000000000000', self.cookie_a)[0], 200)
        self.assertEqual(self.req('GET', '/captures/gpu-worker/gpu-bbbb-0.png', self.cookie_a)[0], 404)
        self.assertEqual(self.req('GET', '/captures/gpu-worker/gpu-aaaa-0.png', self.cookie_a)[0], 200)
        listed = [c['file'] for c in json.loads(self.req('GET', '/api/captures', self.cookie_a)[1])['captures']]
        self.assertEqual(listed, ['gpu-aaaa-0.png'])

    def test_headset_can_only_request_for_itself(self):
        status, _ = self.req('POST', '/api/gpu/screen-request', self.cookie_a,
                             {'serial': 'QB', 'workflow': 'detect', 'prompt': 'Find a chair'})
        self.assertEqual(status, 403)
        with patch.object(self.s, 'gpu_screen_request', return_value={'message': 'ok'}) as sr:
            self.req('POST', '/api/gpu/screen-request', self.cookie_a, {'workflow': 'detect', 'prompt': 'Find a chair'})
            self.assertEqual(sr.call_args[0][0], 'QA')  # no serial given: its own

    def test_wifi_pairing_identifies_the_headset(self):
        token = self.s.USB_PAIRS.begin('QB', 'Quest 3')
        self.s.USB_PAIRS.accept(token)
        h = self.s.Handler.__new__(self.s.Handler)
        h.headers = {'Cookie': 'xrpanel=' + token}
        self.assertEqual(h.identity(), 'QB')

    def test_result_waits_on_a_wifi_only_headset(self):
        rec = self.s.gpu_worker.list_jobs()[0]
        with patch.object(self.s, 'require_headset', side_effect=RuntimeError('headset QB is not connected')):
            self.assertEqual(self.s.gpu_deliver_review(rec), 'ready')


if __name__ == '__main__':
    unittest.main()
