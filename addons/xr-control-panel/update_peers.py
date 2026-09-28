"""Pull stored software updates from another XR Control Panel.

Source panel: ShareKeys issues read-only share keys (only their hashes are stored; each can be
revoked). A request presenting one as `Authorization: Bearer <key>` may list the stored updates
(GET /api/share/updates) and download them (GET /api/share/updates/<sha256>/download), nothing else.

Pulling panel: Peers remembers other panels by address, share key and the SHA-256 fingerprint of
their HTTPS certificate, pinned when the peer is added (compare it with the fingerprint the other
panel shows). Every later connection must present the same certificate before the key is sent.
Pulled files go through UpdateLibrary.upload with the expected SHA-256, so they are verified and
inspected exactly like a manual upload. Standard library only.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import re
import secrets
import socket
import ssl
import threading
import time
import uuid
from pathlib import Path

from usb_pairing import atomic_json

SHA_RE = re.compile(r"^[a-f0-9]{64}$")
ADDRESS_RE = re.compile(r"^(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]{1,253}):(\d{1,5})$")


def fingerprint(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def pretty(fp: str) -> str:
    return ":".join(fp[i:i + 2] for i in range(0, len(fp), 2)).upper()


def cert_fingerprint_file(pem_path: Path) -> str:
    return fingerprint(ssl.PEM_cert_to_DER_cert(pem_path.read_text()))


# ---------------------------------------------------------------- source side
class ShareKeys:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.data = json.loads(path.read_text()) if path.exists() else {"version": 1, "keys": {}}

    def create(self, label: str) -> dict:
        label = (label or "").strip()[:60] or "Other panel"
        token = secrets.token_urlsafe(32)
        kid = uuid.uuid4().hex[:12]
        with self.lock:
            self.data["keys"][kid] = {"label": label, "digest": hashlib.sha256(token.encode()).hexdigest(),
                                      "created": time.time(), "last_used": None}
            atomic_json(self.path, self.data)
        return {"id": kid, "label": label, "key": token}

    def revoke(self, kid: str) -> None:
        with self.lock:
            if kid not in self.data["keys"]:
                raise ValueError("Share key not found")
            del self.data["keys"][kid]
            atomic_json(self.path, self.data)

    def check(self, token: str) -> bool:
        if not token:
            return False
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            for row in self.data["keys"].values():
                if hmac.compare_digest(digest, row["digest"]):
                    if not row["last_used"] or time.time() - row["last_used"] > 60:
                        row["last_used"] = time.time()
                        atomic_json(self.path, self.data)
                    return True
        return False

    def public(self) -> list[dict]:
        with self.lock:
            return [{"id": k, "label": r["label"], "created": r["created"], "last_used": r["last_used"]}
                    for k, r in sorted(self.data["keys"].items(), key=lambda kv: kv[1]["created"])]


def share_listing(listing: dict) -> list[dict]:
    """What another panel may see of this panel's stored updates."""
    keep = ("sha256", "kind", "filename", "size", "package", "version", "version_code", "label", "models")
    return [{k: row[k] for k in keep if k in row} for row in listing.get("updates", [])]


# ---------------------------------------------------------------- pulling side
class PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to a panel with a self-signed certificate: accepted only if its SHA-256 matches the pin
    (checked before anything, including the share key, is sent)."""

    def __init__(self, host, port, pin, timeout=20):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # trust comes from the pinned fingerprint instead
        super().__init__(host, port, context=ctx, timeout=timeout)
        self.pin = pin

    def connect(self):
        super().connect()
        got = fingerprint(self.sock.getpeercert(binary_form=True))
        if self.pin and not hmac.compare_digest(got, self.pin):
            self.sock.close()
            raise ssl.SSLError("the other panel's certificate changed; remove and add it again after checking")


def parse_address(address: str) -> tuple[str, int]:
    address = (address or "").strip()
    address = re.sub(r"^https?://", "", address).rstrip("/")
    if ":" not in address.replace("[", "").replace("]", "") or (address.startswith("[") and "]:" not in address):
        address += ":8483"  # the panel's default HTTPS port
    m = ADDRESS_RE.fullmatch(address)
    if not m or not 0 < int(m.group(2)) < 65536:
        raise ValueError("Enter the other panel's address, e.g. 192.168.1.50 or 192.168.1.50:8483")
    return m.group(1).strip("[]"), int(m.group(2))


def peek_fingerprint(host: str, port: int, timeout: float = 10) -> str:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with ctx.wrap_socket(raw, server_hostname=None) as tls:
            return fingerprint(tls.getpeercert(binary_form=True))


class Peers:
    def __init__(self, path: Path, library):
        self.path = path
        self.library = library
        self.lock = threading.RLock()
        self.data = json.loads(path.read_text()) if path.exists() else {"version": 1, "peers": {}}
        self.pulls: dict[str, dict] = {}

    def _save(self):
        atomic_json(self.path, self.data)

    def _peer(self, pid: str) -> dict:
        with self.lock:
            peer = self.data["peers"].get(pid)
        if not peer:
            raise ValueError("Panel not found")
        return peer

    def _get(self, peer: dict, path: str, timeout: float = 20):
        conn = PinnedHTTPS(peer["host"], peer["port"], peer["fingerprint"], timeout)
        try:
            conn.request("GET", path, headers={"Authorization": "Bearer " + peer["key"],
                                               "User-Agent": "xr-control-panel-peer"})
            res = conn.getresponse()
        except (OSError, ssl.SSLError) as e:
            conn.close()
            raise RuntimeError(f"Cannot reach {peer['host']}:{peer['port']}: {e}") from None
        if res.status != 200:
            res.read()
            conn.close()
            raise RuntimeError("The other panel refused the share key (revoked or mistyped)" if res.status in (401, 403)
                               else f"The other panel answered HTTP {res.status}")
        return conn, res

    def add(self, address: str, key: str, label: str = "") -> dict:
        host, port = parse_address(address)
        key = (key or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", key):
            raise ValueError("Paste the share key created on the other panel")
        try:
            fp = peek_fingerprint(host, port)
        except (OSError, ssl.SSLError) as e:
            raise RuntimeError(f"Cannot reach {host}:{port} over HTTPS: {e}") from None
        peer = {"host": host, "port": port, "key": key, "fingerprint": fp,
                "label": (label or "").strip()[:60] or f"{host}", "added": time.time()}
        conn, res = self._get(peer, "/api/share/updates")  # proves the key works
        res.read()
        conn.close()
        pid = uuid.uuid4().hex[:12]
        with self.lock:
            self.data["peers"][pid] = peer
            self._save()
        return {"id": pid, "label": peer["label"], "fingerprint": pretty(fp),
                "message": "Panel added. Check that this fingerprint matches the one shown on the other panel."}

    def remove(self, pid: str) -> None:
        with self.lock:
            if pid not in self.data["peers"]:
                raise ValueError("Panel not found")
            del self.data["peers"][pid]
            self._save()

    def public(self) -> list[dict]:
        with self.lock:
            return [{"id": pid, "label": p["label"], "address": f"{p['host']}:{p['port']}",
                     "fingerprint": pretty(p["fingerprint"])} for pid, p in self.data["peers"].items()]

    def remote_updates(self, pid: str) -> list[dict]:
        conn, res = self._get(self._peer(pid), "/api/share/updates")
        try:
            rows = json.loads(res.read(4 * 1024 * 1024))["updates"]
        finally:
            conn.close()
        stored = {row["sha256"] for row in self.library.listing()["updates"]}
        out = []
        for row in rows:
            if isinstance(row, dict) and SHA_RE.fullmatch(str(row.get("sha256", ""))):
                out.append(dict(row, stored=row["sha256"] in stored))
        return out

    def pull(self, pid: str, sha: str) -> dict:
        if not SHA_RE.fullmatch(str(sha)):
            raise ValueError("Invalid update ID")
        peer = self._peer(pid)
        remote = {row["sha256"]: row for row in self.remote_updates(pid)}
        row = remote.get(sha)
        if not row:
            raise ValueError("That update is no longer on the other panel")
        if row["stored"]:
            return {"message": "This update is already stored here"}
        with self.lock:
            if any(p["sha256"] == sha and p["state"] == "running" for p in self.pulls.values()):
                raise ValueError("This update is already being pulled")
            job = {"id": uuid.uuid4().hex[:12], "sha256": sha, "filename": row.get("filename", sha),
                   "from": peer["label"], "state": "running", "message": "Starting", "started": time.time()}
            self.pulls[job["id"]] = job
        threading.Thread(target=self._run_pull, args=(job, peer, row), daemon=True, name="update-pull").start()
        return {"message": f"Pulling {job['filename']} from {peer['label']}", "pull": job}

    def _run_pull(self, job, peer, row):
        try:
            conn, res = self._get(peer, f"/api/share/updates/{job['sha256']}/download", timeout=120)
            try:
                length = int(res.getheader("Content-Length") or 0)
                job["message"] = f"Downloading {length / 1024 ** 2:.0f} MiB"
                name = row.get("filename") or (job["sha256"] + (".apk" if row.get("kind") == "apk" else ".zip"))
                result = self.library.upload(name, row.get("kind", ""), length, res, job["sha256"])
            finally:
                conn.close()
            job.update(state="done", message=result.get("message", "Stored"))
        except Exception as e:  # reported to the user in the pull list
            job.update(state="failed", message=str(e) or e.__class__.__name__)

    def pull_jobs(self) -> list[dict]:
        with self.lock:
            return sorted(self.pulls.values(), key=lambda j: -j["started"])[:20]
