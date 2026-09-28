"""Optional GPU Worker add-on for the XR Control Panel.

Sends XR assets (captures, pictures) to a remote Local AI Stack shared GPU through the
gpu_video_api_package application API (`/api/v1/gpu-api`), then saves the outputs into the
captures folder, where the panel's Captures tab and the Loft's Pictures app pick them up.

This is offline asset acceleration: remote renders are queued jobs, not live VR frames (the
runtime keeps rendering and encoding on the local GPU).

Security, following the API's reviewed client:
  * the connection key stays in this backend (0600 file), never in browser JavaScript;
  * HTTPS only with certificate verification; a remote reached by IP address is verified
    against its certificate host name (``server_name``), optionally with a custom CA file;
  * no redirects are followed; outputs are downloaded only through ``/assets/{id}/content``;
  * a submission's request ID is persisted before POST /jobs and reused for retries;
  * downloads never overwrite existing files.
Standard library only (the panel has no dependencies).
"""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote, urlsplit

CONF_FILE = Path.home() / ".config/xr-control-panel/gpu-worker.json"
STATE_DIR = Path.home() / ".local/share/xr-control-panel/gpu-worker"
JOBS_FILE = STATE_DIR / "jobs.json"
API_PATH = "/api/v1/gpu-api"
TERMINAL = {"complete", "failed", "cancelled"}
OUTPUT_FOLDER = "gpu-worker"  # captures/<OUTPUT_FOLDER>/ holds downloaded outputs
UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
_lock = threading.Lock()


class GpuWorkerError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- configuration
def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _write_private(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def load_conf() -> dict:
    return _read_json(CONF_FILE, {})


def normalize_address(address: str) -> tuple[str, int, str]:
    """IP or host, optionally with :port or an https:// URL -> (host, port, base path)."""
    address = address.strip()
    if not address:
        raise ValueError("enter the remote system's IP address or host name")
    if "://" not in address:
        address = "https://" + address
    parts = urlsplit(address)
    if parts.scheme != "https":
        raise ValueError("the GPU worker API must be reached over HTTPS")
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("invalid address")
    path = parts.path.rstrip("/")
    if not path.endswith(API_PATH):
        path += API_PATH
    return parts.hostname, parts.port or 443, path


def save_conf(address: str, server_name: str = "", ca_file: str = "", key: str | None = None,
              clear_key: bool = False) -> dict:
    host, port, path = normalize_address(address)
    if server_name and not re.match(r"^[A-Za-z0-9.-]{1,253}$", server_name):
        raise ValueError("invalid certificate host name")
    if ca_file and not Path(ca_file).expanduser().is_file():
        raise ValueError("CA file not found")
    conf = load_conf()
    conf.update(address=address.strip(), host=host, port=port, path=path,
                server_name=server_name.strip(), ca_file=ca_file.strip())
    if clear_key:
        conf.pop("key", None)
    elif key:
        conf["key"] = key.strip()
    _write_private(CONF_FILE, conf)
    return status()


def status() -> dict:
    c = load_conf()
    return {"configured": bool(c.get("host") and c.get("key")), "address": c.get("address", ""),
            "server_name": c.get("server_name", ""), "ca_file": c.get("ca_file", ""),
            "key_set": bool(c.get("key"))}


# ---------------------------------------------------------------- HTTPS client
class _PinnedNameHTTPS(http.client.HTTPSConnection):
    """Connects to host (e.g. an IP address) but verifies the certificate for server_name."""

    def __init__(self, host, port, server_name, context, timeout):
        super().__init__(host, port, context=context, timeout=timeout)
        self._server_name = server_name
        self._ctx = context

    def connect(self):
        sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock = self._ctx.wrap_socket(sock, server_hostname=self._server_name)


def _request(method: str, path: str, body: bytes | None = None, content_type: str | None = None,
             timeout: float = 90, want_json: bool = True):
    c = load_conf()
    if not c.get("host"):
        raise GpuWorkerError("GPU worker is not set up yet", 409)
    if not c.get("key"):
        raise GpuWorkerError("add a connection key first", 409)
    ctx = ssl.create_default_context(cafile=os.path.expanduser(c["ca_file"]) if c.get("ca_file") else None)
    name = c.get("server_name") or c["host"]
    conn = _PinnedNameHTTPS(c["host"], c["port"], name, ctx, timeout)
    headers = {"Authorization": "Bearer " + c["key"], "Host": name if c["port"] == 443 else f"{name}:{c['port']}",
               "Accept": "application/json", "User-Agent": "xr-control-panel-gpu-worker"}
    if content_type:
        headers["Content-Type"] = content_type
    try:
        conn.request(method, c["path"] + path, body=body, headers=headers)
        res = conn.getresponse()
        data = res.read()
    except ssl.SSLCertVerificationError as e:
        raise GpuWorkerError(f"certificate check failed ({e.verify_message}); when using an IP address, set the "
                             "certificate host name", 502)
    except OSError as e:
        raise GpuWorkerError(f"cannot reach the GPU worker: {e}", 502)
    finally:
        conn.close()
    if not 200 <= res.status < 300:  # redirects are errors too: never follow them with the key
        try:
            detail = json.loads(data).get("detail", "")
        except ValueError:
            detail = data[:200].decode(errors="replace")
        messages = {401: "the connection key is invalid, expired or revoked",
                    403: "the connection key lacks the render/storage scope or entitlement",
                    404: "not found on the GPU worker", 409: "conflicting submission",
                    413: "over the storage or upload limit", 429: "the shared GPU is busy; try again later"}
        raise GpuWorkerError(f"{messages.get(res.status, 'GPU worker error')} (HTTP {res.status}"
                             f"{': ' + str(detail) if detail else ''})", res.status if res.status < 500 else 502)
    if not want_json:
        return data, res.getheader("Content-Type", "")
    return json.loads(data or b"{}")


def account() -> dict:
    return _request("GET", "/account")


def workflows() -> dict:
    return _request("GET", "/workflows").get("workflows", {})


# ---------------------------------------------------------------- jobs
def _jobs() -> list[dict]:
    return _read_json(JOBS_FILE, [])


def _save_jobs(jobs: list[dict]) -> None:
    _write_private(JOBS_FILE, jobs[-200:])


def list_jobs() -> list[dict]:
    return list(reversed(_jobs()))


def _png_reference_bundle(src: Path) -> bytes:
    """One-reference ZIP_STORED bundle: 0.png, RGB, at most 1024 px per side (API format)."""
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "0.png"
        res = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-frames:v", "1", "-vf",
                              "scale='min(1024,iw)':'min(1024,ih)':force_original_aspect_ratio=decrease",
                              "-pix_fmt", "rgb24", str(png)], capture_output=True, text=True, timeout=120)
        if res.returncode != 0 or not png.is_file():
            raise GpuWorkerError("could not convert the capture to PNG (is ffmpeg installed?)", 400)
        if png.stat().st_size > 4 * 1024 * 1024:
            raise GpuWorkerError("the converted reference is larger than 4 MiB", 400)
        buf = Path(tmp) / "references.zip"
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as z:
            z.write(png, "0.png")
        return buf.read_bytes()


def submit(workflow: str, prompt: str, source: Path | None, source_label: str = "", review_serial: str | None = None) -> dict:
    available = workflows()
    if workflow not in available:
        raise GpuWorkerError("that workflow is not offered by this GPU worker", 400)
    info = available[workflow] or {}
    refs = int(info.get("reference_count") or 0)
    if refs > 1:
        raise GpuWorkerError(f"this workflow needs {refs} reference images; the panel sends one capture", 400)
    if refs == 1 and source is None:
        raise GpuWorkerError("this workflow needs a source capture", 400)

    request_id = str(uuid.uuid4())
    record = {"request_id": request_id, "workflow": workflow, "prompt": prompt, "source": source_label,
              "asset_id": None, "job_id": None, "status": "uploading" if source else "submitting",
              "created": time.time(), "outputs": [], "error": "",
              "review_serial": review_serial, "review_state": "waiting" if review_serial else None}
    with _lock:
        jobs = _jobs()
        jobs.append(record)
        _save_jobs(jobs)  # persisted before any submission

    try:
        if source is not None:
            if refs == 1:
                data, name = _png_reference_bundle(source), "references.zip"
            else:
                data, name = source.read_bytes(), source.name
            up = _request("POST", "/assets?filename=" + quote(name), body=data,
                          content_type="application/octet-stream", timeout=300)
            _update(request_id, asset_id=up["asset"]["id"], status="submitting")
        return _send_job(request_id)
    except GpuWorkerError as e:
        _update(request_id, status="error", error=str(e))
        raise


def _send_job(request_id: str) -> dict:
    rec = _find(request_id)
    payload = {"workflow": rec["workflow"], "values": {"prompt": rec["prompt"]}, "request_id": request_id}
    if rec.get("asset_id"):
        payload["asset_id"] = rec["asset_id"]
    job = _request("POST", "/jobs", body=json.dumps(payload).encode(), content_type="application/json")
    return _update(request_id, job_id=job.get("job_id"), status=job.get("status", "queued"), error="")


def _find(request_id: str) -> dict:
    for rec in _jobs():
        if rec["request_id"] == request_id:
            return rec
    raise GpuWorkerError("unknown job", 404)


def _update(request_id: str, **fields) -> dict:
    with _lock:
        jobs = _jobs()
        for rec in jobs:
            if rec["request_id"] == request_id:
                rec.update(fields)
                _save_jobs(jobs)
                return rec
    raise GpuWorkerError("unknown job", 404)


def _ext_for(content_type: str) -> str:
    ct = content_type.split(";")[0].strip().lower()
    return {"image/png": "png", "image/jpeg": "jpg", "video/mp4": "mp4", "image/webp": "webp"}.get(ct, "bin")


def refresh(request_id: str, capture_root: Path) -> dict:
    """Poll a job; after success download its outputs once into capture_root/gpu-worker/."""
    rec = _find(request_id)
    if not rec.get("job_id"):
        uploaded = rec.get("asset_id") is not None or not rec.get("source")
        if rec.get("status") in ("submitting", "error") and uploaded:
            # Lost or failed submission response: retry with the SAME request ID and payload.
            return _send_job(request_id)
        raise GpuWorkerError("this job was never submitted; start a new one", 409)
    if not UUID_RE.match(rec["job_id"]):
        raise GpuWorkerError("unexpected job id", 502)
    job = _request("GET", "/jobs/" + rec["job_id"])
    rec = _update(request_id, status=job.get("status", "unknown"))
    if rec["status"] != "complete" or rec.get("outputs"):
        return rec
    out_dir = capture_root / OUTPUT_FOLDER
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for n, asset in enumerate(job.get("assets") or []):
        asset_id = str(uuid.UUID(asset["id"]))  # API path only; never follow result URLs
        data, ctype = _request("GET", f"/assets/{asset_id}/content", timeout=300, want_json=False)
        ext = _ext_for(ctype)
        stem = f"gpu-{request_id[:8]}-{n}"
        if ext == "webp":  # keep captures viewable: convert to PNG
            with tempfile.NamedTemporaryFile(suffix=".webp") as t:
                t.write(data)
                t.flush()
                dst = out_dir / f"{stem}.png"
                if dst.exists():
                    continue
                subprocess.run(["ffmpeg", "-v", "error", "-n", "-i", t.name, str(dst)], timeout=120)
        else:
            dst = out_dir / f"{stem}.{ext}"
            with dst.open("xb") as f:  # never overwrite
                f.write(data)
        saved.append(dst.name)
    return _update(request_id, outputs=saved)
