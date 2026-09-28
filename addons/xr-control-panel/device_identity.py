"""Which headset a browser belongs to, for browsers the panel opened on that headset over USB.

When the panel opens a headset's browser (adb am start ... http://127.0.0.1:<port>/...), it adds a
one-time `device=<token>` to the URL; the browser keeps it as a cookie and is then known to be that
headset. USB-reversed browsers all arrive from 127.0.0.1, so the address cannot identify them.
Wi-Fi browsers are identified by their USB pairing grant instead (usb_pairing.UsbPairing).
Only token hashes are stored; a new token replaces the previous one for the same headset.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import secrets
import threading

from usb_pairing import atomic_json


class DeviceIdentity:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.mtime = None
        self.data = {"version": 1, "devices": {}}
        self._reload()

    def _reload(self):
        # Another panel process (or a restart) may have issued tokens: follow the file.
        try:
            mtime = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            return
        if mtime != self.mtime:
            self.data = json.loads(self.path.read_text())
            self.mtime = mtime

    def issue(self, serial: str) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            self._reload()
            self.data["devices"][serial] = {"digest": hashlib.sha256(token.encode()).hexdigest()}
            atomic_json(self.path, self.data)
            self.mtime = self.path.stat().st_mtime_ns
        return token

    def serial_for(self, token: str) -> str | None:
        if not token:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            self._reload()
            for serial, row in self.data["devices"].items():
                if hmac.compare_digest(digest, row.get("digest", "")):
                    return serial
        return None
