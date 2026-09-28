"""Wi-Fi view capture: without ADB the panel captures the frame the runtime streams to the headset."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class WifiCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / 'config.json').write_text(json.dumps({'updates_dir': str(self.d / 'updates'),
                                                        'capture_dir': str(self.d / 'captures')}))
        self.env = patch.dict(os.environ, XR_PANEL_CONFIG=str(self.d / 'config.json'), HOME=str(self.d))
        self.env.start()
        spec = importlib.util.spec_from_file_location('panel_wifi_under_test', ROOT / 'server.py')
        self.s = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.s)
        self.rt = self.d / 'xr-quest2'
        self.rt.mkdir()
        inst = self.d / '.config/intel-xr/instances'
        inst.mkdir(parents=True)
        (inst / 'quest2.env').write_text(f'ALVR_WIRED_SERIAL=SECOND\nXDG_RUNTIME_DIR={self.rt}\n')

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_runtime_dir_follows_pinned_instance(self):
        self.assertEqual(self.s.runtime_dir_for('SECOND'), self.rt)
        with patch.dict(os.environ, XDG_RUNTIME_DIR='/run/user/4242'):
            self.assertEqual(self.s.runtime_dir_for('FIRST'), Path('/run/user/4242'))

    def fake_encoder(self, frame_src):
        """Answer the request file the way alvr_render companion step 13 does."""
        def run():
            req = self.rt / 'intel-xr-view-request'
            for _ in range(100):
                if req.exists():
                    req.unlink()
                    (self.rt / 'intel-xr-view.h264').write_bytes(frame_src.read_bytes())
                    return
                threading.Event().wait(0.02)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t

    def test_stream_snapshot_decodes_left_eye(self):
        src = self.d / 'src.h264'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=256x128', '-frames:v', '1',
                        '-c:v', 'libx264', '-f', 'h264', str(src)], check=True)
        self.fake_encoder(src).join(0)
        name = self.s.stream_view_capture('SECOND')
        out = self.s.capture_dir_for('SECOND') / name
        self.assertTrue(self.s.FILE_RE.fullmatch(name))
        size = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=width,height', '-of', 'csv=p=0',
                               str(out)], capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(size, '128,128')

    def test_no_answer_is_an_error_and_clears_request(self):
        with patch.object(self.s.time, 'time', side_effect=[0, 0, 10]):
            with self.assertRaises(RuntimeError):
                self.s.stream_view_capture('SECOND')
        self.assertFalse((self.rt / 'intel-xr-view-request').exists())

    def test_request_uses_stream_without_adb_and_screenshot_with_it(self):
        gw = self.s.gpu_worker
        common = [patch.object(gw, 'workflows', return_value={'vision': {'reference_count': 1}}),
                  patch.object(gw, 'submit', return_value={'request_id': 'x'})]
        for p in common:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in common])
        with patch.object(self.s, 'require_headset', side_effect=RuntimeError('headset SECOND is not connected')), \
             patch.object(self.s, 'stream_view_capture', return_value='view-1.jpg') as stream, \
             patch.object(self.s, 'headset_action') as usb:
            self.s.gpu_screen_request('SECOND', 'vision', 'Find a chair')
            stream.assert_called_once_with('SECOND')
            usb.assert_not_called()
            self.assertTrue(str(gw.submit.call_args.args[2]).endswith('view-1.jpg'))
        with patch.object(self.s, 'require_headset'), \
             patch.object(self.s, 'stream_view_capture') as stream, \
             patch.object(self.s, 'headset_action', return_value={'file': 'screen.png'}) as usb:
            self.s.gpu_screen_request('SECOND', 'vision', 'Find a ball')
            stream.assert_not_called()
            usb.assert_called_once_with('SECOND', 'screenshot')

    def test_headset_mic_node_per_instance(self):
        env = self.d / '.config/intel-xr/instances/quest2.env'
        env.write_text(env.read_text() + 'ALVR_INSTANCE_NAME=quest2\n')
        self.assertEqual(self.s.headset_mic_node('SECOND'), 'ALVR Microphone (quest2)')
        self.assertEqual(self.s.headset_mic_node('FIRST'), 'ALVR Microphone')

    def test_listen_needs_the_streamed_microphone(self):
        ports = subprocess.CompletedProcess([], 0, 'ALVR Microphone (other):capture_MONO\n', '')
        with patch.object(self.s.subprocess, 'run', return_value=ports), \
             patch.object(self.s.shutil, 'which', return_value='/usr/bin/pw-record'), \
             patch.object(self.s.subprocess, 'Popen') as rec:
            with self.assertRaisesRegex(RuntimeError, 'microphone stream is not available'):
                self.s.record_headset_mic('FIRST', 2)
            rec.assert_not_called()

    def test_listen_endpoint_is_limited_to_own_headset(self):
        h = object.__new__(self.s.Handler)
        h.client_address = ('192.0.2.5', 5000)
        h.command, h.path, h.headers = 'POST', '/api/voice/listen', {'Content-Length': '0'}
        h.authorized = lambda: True
        h.identity = lambda: 'SECOND'
        h.body = lambda: json.dumps({'serial': 'FIRST'}).encode()
        sent = []
        h.json = lambda obj, code=200: sent.append((code, obj))
        with patch.object(self.s, 'record_headset_mic') as rec:
            h.do_POST()
        self.assertEqual(sent[0][0], 403)
        rec.assert_not_called()


if __name__ == '__main__':
    unittest.main()
