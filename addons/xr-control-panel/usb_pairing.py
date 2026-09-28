"""Persistent browser grants issued only after an authorized physical USB connection.

The browser holds a per-device random credential; IP addresses never authorize it.
Only hashes are stored. Revocation is sticky until explicit manual pairing.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class UsbPairing:
    def __init__(self, path: Path, clock=time.time):
        self.path = path
        self.clock = clock
        self.lock = threading.RLock()
        self.data = json.loads(path.read_text()) if path.exists() else {"version": 1, "devices": {}}
        if self.data.get("version") != 1 or not isinstance(self.data.get("devices"), dict):
            raise ValueError("invalid USB pairing registry")

    def _save(self):
        atomic_json(self.path, self.data)

    def needs_pairing(self, serial):
        with self.lock:
            row = self.data["devices"].get(serial, {})
            return row.get("state") not in ("paired", "revoked", "failed") and self.clock() >= row.get("retry_at", 0)

    def begin(self, serial, name, manual=False):
        with self.lock:
            if not manual and not self.needs_pairing(serial):
                return None
            old = self.data["devices"].get(serial, {})
            attempts = 1 if manual else old.get("attempts", 0) + 1
            if attempts > 3:
                old.update(state="failed", error="Pairing was not completed. Use Pair headset for Wi-Fi to retry.")
                old.pop("digest", None)
                self._save()
                return None
            token = secrets.token_urlsafe(32)
            self.data["devices"][serial] = {
                "name": name, "state": "pending", "attempts": attempts,
                "digest": hashlib.sha256(token.encode()).hexdigest(),
                "issued_at": self.clock(), "retry_at": self.clock() + 120,
                "expires_at": self.clock() + 300, "error": "",
            }
            self._save()
            return token

    def launch_failed(self, serial):
        with self.lock:
            row = self.data["devices"].get(serial)
            if row and row["state"] == "pending":
                row["error"] = "Could not open the pairing page. Reconnect USB or pair manually."
                self._save()

    def accept(self, token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            for row in self.data["devices"].values():
                if row["state"] == "pending" and self.clock() <= row["expires_at"] and hmac.compare_digest(digest, row.get("digest", "")):
                    row.update(state="paired", paired_at=self.clock(), error="")
                    self._save()
                    return True
        return False

    def authorized(self, token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            return any(row["state"] == "paired" and hmac.compare_digest(digest, row.get("digest", ""))
                       for row in self.data["devices"].values())

    def revoke(self):
        with self.lock:
            for row in self.data["devices"].values():
                row.update(state="revoked", error="")
                row.pop("digest", None)
            self._save()

    def public(self):
        with self.lock:
            return [{"serial": serial, "name": row.get("name", ""), "state": row["state"], "error": row.get("error", "")}
                    for serial, row in sorted(self.data["devices"].items())]
