"""Tablet Loft client: ids, sizes, input validation, and the WebSocket relay to a renderer."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tablet_client as tc  # noqa: E402

# Stands in for intel_xr_loft_flat: frames numbered 1, 2, ... and one state packet; logs each input line.
FAKE_RENDERER = textwrap.dedent('''\
    #!/usr/bin/env python3
    import os, select, struct, sys, time
    log = open(os.environ["FAKE_LOG"], "a")
    log.write("ARGS " + " ".join(sys.argv[1:]) + "\\n"); log.flush()
    out = sys.stdout.buffer
    def packet(kind, data):
        out.write(kind + struct.pack("<I", len(data)) + data); out.flush()
    packet(b"S", b'{"seated":null,"x":0.9,"z":1.6,"peers":0}')
    n = 0
    while True:
        r, _, _ = select.select([sys.stdin], [], [], 0.02)
        if r:
            line = sys.stdin.readline()
            if not line:
                break
            log.write(line); log.flush()
        n += 1
        packet(b"F", b"\\xff\\xd8frame%d" % n)
    ''')


class PureTests(unittest.TestCase):
    def test_ids(self):
        self.assertEqual(tc.client_id("R9TWC0DTP6Z", False), "tablet-r9twc0dtp6z")
        self.assertEqual(tc.client_id(None, True), "pc-viewer")
        self.assertIsNone(tc.client_id(None, False))

    def test_sizes(self):
        self.assertEqual(tc.view_size(1920, 1200), (1280, 800))
        self.assertEqual(tc.view_size(1200, 1920), (800, 1280))
        self.assertEqual(tc.view_size(100, 50), (320, 240))
        self.assertEqual(tc.view_size("x", None), (1280, 800))

    def test_commands_are_validated(self):
        self.assertEqual(tc.command_for({"t": "look", "dx": 0.1, "dy": -0.2}), "look 0.10000 -0.20000")
        self.assertEqual(tc.command_for({"t": "move", "f": 5, "r": -5}), "move 1.000 -1.000")
        self.assertEqual(tc.command_for({"t": "tap", "u": 0.5, "v": 2}), "tap 0.5000 1.0000")
        self.assertEqual(tc.command_for({"t": "stand"}), "stand")
        for bad in ({"t": "look", "dx": "1\nquit", "dy": 0}, {"t": "move", "f": float("nan"), "r": 0},
                    {"t": "tap", "u": True, "v": 0}, {"t": "shell"}, {}):
            self.assertIsNone(tc.command_for(bad), bad)

    def test_ws_frames(self):
        self.assertEqual(tc.ws_accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")
        for n in (5, 300, 70000):
            f = tc.ws_frame(2, b"x" * n)
            self.assertEqual(f[0], 0x82)
            self.assertTrue(f.endswith(b"x" * n))


def client_frame(opcode, payload):
    mask = os.urandom(4)
    data = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
    n = len(payload)
    head = bytes([0x80 | opcode, 0x80 | n]) if n < 126 else bytes([0x80 | opcode, 0x80 | 126]) + struct.pack(">H", n)
    return head + mask + data


def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("closed")
        data += chunk
    return data


def read_frame(sock):
    b0, b1 = recv_exact(sock, 2)
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack(">H", recv_exact(sock, 2))[0]
    elif n == 127:
        n = struct.unpack(">Q", recv_exact(sock, 8))[0]
    return b0 & 0x0F, recv_exact(sock, n)


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "config.json").write_text(json.dumps({"updates_dir": str(d / "updates"), "capture_dir": str(d / "captures")}))
        self.fake = d / "fake_flat"
        self.fake.write_text(FAKE_RENDERER)
        self.fake.chmod(0o755)
        self.log = d / "fake.log"
        self.env = patch.dict(os.environ, XR_PANEL_CONFIG=str(d / "config.json"), FAKE_LOG=str(self.log))
        self.env.start()
        spec = importlib.util.spec_from_file_location("panel_tablet", ROOT / "server.py")
        self.s = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.s)
        self.s.TABLET_CLIENTS.binary_fn = lambda: self.fake
        self.s.TABLET_CLIENTS.log_dir_fn = lambda: None
        self.srv = self.s.create_http_server("127.0.0.1", 0, False)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.s.TABLET_CLIENTS.stop_all()
        self.srv.shutdown()
        self.srv.server_close()
        self.env.stop()
        self.tmp.cleanup()

    def open_ws(self, query="w=1920&h=1200"):
        sock = socket.create_connection(self.srv.server_address[:2], timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET /api/tablet/ws?{query} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(1)
            if not chunk:
                break
            head += chunk
        return sock, sock, head.split(b"\r\n", 1)[0]

    def test_relay_frames_state_and_input(self):
        sock, f, status = self.open_ws()
        self.assertIn(b"101", status)
        op, hello = read_frame(f)
        self.assertEqual(json.loads(hello), {"t": "hello", "id": "pc-viewer", "size": [1280, 800]})
        got = {}
        while "frame" not in got or "state" not in got:
            op, data = read_frame(f)
            if op == 2:
                got["frame"] = data
            elif op == 1:
                got["state"] = json.loads(data)
        self.assertTrue(got["frame"].startswith(b"\xff\xd8frame"))
        self.assertEqual(got["state"]["t"], "state")
        # Flow control: without acks only MAX_IN_FLIGHT frames arrive.
        sock.settimeout(0.6)
        extra = 0
        try:
            while True:
                if read_frame(f)[0] == 2:
                    extra += 1
        except (socket.timeout, TimeoutError):
            pass
        self.assertEqual(1 + extra, tc.MAX_IN_FLIGHT)
        sock.settimeout(5)
        sock.sendall(client_frame(1, b'{"t":"ack"}'))
        self.assertEqual(read_frame(f)[0], 2)
        sock.sendall(client_frame(1, b'{"t":"move","f":1,"r":0}'))
        sock.sendall(client_frame(1, b'{"t":"tap","u":0.25,"v":0.5}'))
        sock.sendall(client_frame(1, b'{"t":"look","dx":"bad","dy":0}'))
        deadline = time.time() + 3
        while time.time() < deadline and "tap" not in self.log.read_text():
            time.sleep(0.05)
        lines = self.log.read_text().splitlines()
        self.assertEqual(lines[0], "ARGS --id pc-viewer --size 1280x800")
        self.assertEqual(lines[1:], ["move 1.000 0.000", "tap 0.2500 0.5000"])
        status = self.s.TABLET_CLIENTS.status()
        self.assertEqual([(x["id"], x["viewer"]) for x in status], [("pc-viewer", True)])
        sock.sendall(client_frame(8, b""))
        sock.close()
        deadline = time.time() + 3
        while time.time() < deadline and self.s.TABLET_CLIENTS.status()[0]["viewer"]:
            time.sleep(0.05)
        self.assertFalse(self.s.TABLET_CLIENTS.status()[0]["viewer"])

    def test_new_page_replaces_old_and_size_change_restarts(self):
        a, fa, _ = self.open_ws()
        read_frame(fa)
        b, fb, status = self.open_ws("w=800&h=600")
        self.assertIn(b"101", status)
        self.assertEqual(json.loads(read_frame(fb)[1])["size"], [800, 600])
        self.assertEqual(self.s.TABLET_CLIENTS.status()[0]["size"], [800, 600])
        a.close()
        b.close()

    def test_plain_request_and_missing_renderer(self):
        import urllib.request
        import urllib.error
        base = "http://%s:%d" % self.srv.server_address[:2]
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/api/tablet/ws")
        self.assertEqual(e.exception.code, 400)
        self.s.TABLET_CLIENTS.binary_fn = lambda: Path(self.tmp.name) / "missing"
        st = json.loads(urllib.request.urlopen(base + "/api/tablet/status").read())
        self.assertEqual((st["available"], st["id"]), (False, "pc-viewer"))
        sock, f, status = self.open_ws()
        self.assertIn(b"503", status)
        sock.close()
        page = urllib.request.urlopen(base + "/tablet").read()
        self.assertIn(b"/static/tablet.js", page)


if __name__ == "__main__":
    unittest.main()
