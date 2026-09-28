"""Tablet Loft client: the Loft on a tablet's browser, as its own user.

For each tablet this PC runs intel_xr_loft_flat (the Loft's flat-screen renderer, which joins Loft
presence under the tablet's own id), and relays it over one WebSocket: JPEG frames and state to
the page, touch input back. Frames are sent only after the page has shown the previous ones
(at most two in flight), so a slow Wi-Fi link gets fewer, fresh frames instead of a growing delay.
A renderer with no page connected for IDLE_STOP seconds is stopped. Standard library only.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import threading
import time
from pathlib import Path

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
IDLE_STOP = 20.0
MAX_IN_FLIGHT = 2
ID_RE = re.compile(r"^[a-z0-9_-]{1,31}$")


def client_id(serial: str | None, local: bool) -> str | None:
    """Presence id for a browser: its device serial, or 'pc-viewer' for this PC's own browser."""
    if serial:
        cid = "tablet-" + re.sub(r"[^a-z0-9]", "", serial.lower())[:24]
        return cid if ID_RE.fullmatch(cid) else None
    return "pc-viewer" if local else None


def view_size(w, h) -> tuple[int, int]:
    """The page's requested render size, clamped (a tablet is 1920x1200) and rounded to 8 pixels."""
    try:
        w, h = int(w), int(h)
    except (TypeError, ValueError):
        return 1280, 800
    scale = min(1.0, 1280 / max(w, 1), 1280 / max(h, 1))  # longest side at most 1280 for Wi-Fi
    w, h = max(320, int(w * scale)), max(240, int(h * scale))
    return w // 8 * 8, h // 8 * 8


# ---------------------------------------------------------------- WebSocket (RFC 6455), minimal
def ws_accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()


def ws_frame(opcode: int, payload: bytes) -> bytes:
    n = len(payload)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack(">H", n)
    else:
        head += bytes([127]) + struct.pack(">Q", n)
    return head + payload


def ws_read(rfile, limit: int = 65536) -> tuple[int, bytes] | None:
    """One client frame (opcode, unmasked payload); None when the connection ends. Client frames
    must be masked and small (input only); fragments are not used by the page."""
    head = rfile.read(2)
    if len(head) < 2:
        return None
    opcode, masked, n = head[0] & 0x0F, head[1] & 0x80, head[1] & 0x7F
    if n == 126:
        n = struct.unpack(">H", rfile.read(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", rfile.read(8))[0]
    if not masked or n > limit:
        return None
    mask = rfile.read(4)
    data = bytearray(rfile.read(n))
    if len(mask) < 4 or len(data) < n:
        return None
    for i in range(n):
        data[i] ^= mask[i & 3]
    return opcode, bytes(data)


def command_for(msg: dict) -> str | None:
    """A validated renderer command line for one page input message."""
    def num(key, lo, hi):
        v = msg.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            raise ValueError
        return min(max(float(v), lo), hi)
    try:
        kind = msg.get("t")
        if kind == "look":
            return f"look {num('dx', -3.2, 3.2):.5f} {num('dy', -3.2, 3.2):.5f}"
        if kind == "move":
            return f"move {num('f', -1, 1):.3f} {num('r', -1, 1):.3f}"
        if kind == "tap":
            return f"tap {num('u', 0, 1):.4f} {num('v', 0, 1):.4f}"
        if kind == "stand":
            return "stand"
    except ValueError:
        pass
    return None


# ---------------------------------------------------------------- renderer processes
class FlatSession:
    def __init__(self, binary: Path, cid: str, size: tuple[int, int], env: dict, log_dir: Path | None):
        self.id, self.size = cid, size
        self.cond = threading.Condition()
        self.frame, self.seq, self.state = b"", 0, {}
        self.viewer = None  # the connected page (only the newest one is kept)
        self.last_viewer = time.monotonic()
        log = open(log_dir / f"loft-flat-{cid}.log", "ab") if log_dir else subprocess.DEVNULL
        self.proc = subprocess.Popen([str(binary), "--id", cid, "--size", f"{size[0]}x{size[1]}"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, env=env)
        if log_dir:
            log.close()
        threading.Thread(target=self._read, daemon=True, name=f"loft-flat-{cid}").start()

    def _read(self):
        out = self.proc.stdout
        while True:
            try:
                head = out.read(5)
                if len(head) < 5:
                    break
                kind, n = head[:1], struct.unpack("<I", head[1:])[0]
                data = out.read(n)
            except (OSError, ValueError):  # closed by stop()
                break
            if len(data) < n:
                break
            with self.cond:
                if kind == b"F":
                    self.frame, self.seq = data, self.seq + 1
                elif kind == b"S":
                    try:
                        self.state = json.loads(data)
                    except ValueError:
                        pass
                self.cond.notify_all()
        with self.cond:
            self.cond.notify_all()

    def alive(self) -> bool:
        return self.proc.poll() is None

    def send(self, line: str):
        try:
            self.proc.stdin.write((line + "\n").encode())
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            pass

    def stop(self):
        try:
            self.proc.stdin.close()  # the renderer exits (and leaves presence) when its input closes
        except OSError:
            pass
        try:
            self.proc.wait(3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(3)
        try:
            self.proc.stdout.close()
        except OSError:
            pass
        with self.cond:
            self.cond.notify_all()


class TabletClients:
    def __init__(self, binary_fn, env_fn, log_dir_fn):
        self.binary_fn, self.env_fn, self.log_dir_fn = binary_fn, env_fn, log_dir_fn
        self.lock = threading.Lock()
        self.sessions: dict[str, FlatSession] = {}
        threading.Thread(target=self._reap, daemon=True, name="tablet-client-reaper").start()

    def available(self) -> bool:
        b = self.binary_fn()
        return bool(b and b.is_file() and os.access(b, os.X_OK))

    def status(self) -> list[dict]:
        with self.lock:
            return [{"id": s.id, "size": list(s.size), "running": s.alive(), "viewer": s.viewer is not None,
                     "state": s.state} for s in self.sessions.values()]

    def session(self, cid: str, size: tuple[int, int]) -> FlatSession:
        with self.lock:
            s = self.sessions.get(cid)
            if s and (not s.alive() or s.size != size):
                s.stop()
                s = None
            if not s:
                if not self.available():
                    raise RuntimeError("The Loft's tablet renderer is not built (intel_xr_loft_flat)")
                s = FlatSession(self.binary_fn(), cid, size, self.env_fn(), self.log_dir_fn())
                self.sessions[cid] = s
            return s

    def _reap(self):
        while True:
            time.sleep(5)
            with self.lock:
                for cid, s in list(self.sessions.items()):
                    if not s.alive() or (s.viewer is None and time.monotonic() - s.last_viewer > IDLE_STOP):
                        s.stop()
                        del self.sessions[cid]

    def stop_all(self):
        with self.lock:
            for s in self.sessions.values():
                s.stop()
            self.sessions.clear()

    def serve(self, handler, cid: str, size: tuple[int, int]):
        """Upgrades the handler's request to a WebSocket and relays one session until either side ends."""
        key = handler.headers.get("Sec-WebSocket-Key", "")
        if handler.headers.get("Upgrade", "").lower() != "websocket" or len(key) < 16:
            return handler.json({"error": "WebSocket required"}, 400)
        try:
            s = self.session(cid, size)
        except RuntimeError as e:
            return handler.json({"error": str(e)}, 503)
        # The panel speaks HTTP/1.0; the upgrade response must be HTTP/1.1, so it is written directly.
        handler.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                             f"Sec-WebSocket-Accept: {ws_accept_key(key)}\r\n\r\n").encode())
        handler.wfile.flush()
        handler.close_connection = True
        me = object()
        wlock = threading.Lock()
        acked = [0]  # frames the page has shown
        closed = threading.Event()

        def send(opcode, data):
            with wlock:
                handler.wfile.write(ws_frame(opcode, data))
                handler.wfile.flush()

        def reader():
            try:
                while not closed.is_set():
                    msg = ws_read(handler.rfile)
                    if msg is None or msg[0] == 0x8:
                        break
                    if msg[0] == 0x9:
                        send(0xA, msg[1])
                        continue
                    if msg[0] != 0x1:
                        continue
                    try:
                        req = json.loads(msg[1])
                    except ValueError:
                        continue
                    if not isinstance(req, dict):
                        continue
                    if req.get("t") == "ack":
                        with s.cond:
                            acked[0] += 1
                            s.cond.notify_all()
                        continue
                    line = command_for(req)
                    if line:
                        s.send(line)
            except (OSError, ValueError, struct.error):
                pass
            closed.set()
            with s.cond:
                s.cond.notify_all()

        with s.cond:
            s.viewer = me
            s.cond.notify_all()  # a previous page for this tablet gives way
        threading.Thread(target=reader, daemon=True, name=f"tablet-ws-{cid}").start()
        sent_seq, sent, state_sent = 0, 0, None
        try:
            send(0x1, json.dumps({"t": "hello", "id": cid, "size": list(size)}).encode())
            while not closed.is_set():
                with s.cond:
                    s.cond.wait_for(lambda: closed.is_set() or s.viewer is not me or not s.alive()
                                    or (s.seq != sent_seq and sent - acked[0] < MAX_IN_FLIGHT)
                                    or s.state is not state_sent, timeout=5)
                    if s.viewer is not me or not s.alive():
                        break
                    frame, seq, state = s.frame, s.seq, s.state
                if state is not state_sent:
                    state_sent = state
                    if state:  # nothing until the renderer has reported
                        send(0x1, json.dumps({"t": "state", **state}).encode())
                if seq != sent_seq and frame and sent - acked[0] < MAX_IN_FLIGHT:
                    sent_seq, sent = seq, sent + 1
                    send(0x2, frame)
            if not s.alive():
                send(0x1, json.dumps({"t": "error", "message": "The tablet renderer stopped"}).encode())
            send(0x8, b"")
        except OSError:
            pass
        finally:
            closed.set()
            with s.cond:
                if s.viewer is me:
                    s.viewer = None
                    s.last_viewer = time.monotonic()
