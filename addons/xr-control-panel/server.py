#!/usr/bin/env python3
"""XR Control Panel: a local web UI to manage Quest headsets and, optionally, the
Intel XR (Monado + ALVR) runtime.

Standalone add-on: only the Python standard library and `adb` are required. Runtime
features (status, test app, ALVR connections, settings, restart/rebuild) are enabled
when `runtime_root` points at an Intel XR checkout; otherwise they report
"not installed" and the headset features keep working.

Config: $XR_PANEL_CONFIG or ~/.config/xr-control-panel/config.json
"""
from __future__ import annotations

import json
import io
import tarfile
import gzip
import html
import zipfile
import os
import re
import shutil
import shlex
import signal
import socket
import ssl
import ipaddress
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from usb_pairing import UsbPairing, atomic_json
from device_identity import DeviceIdentity
from software_updates import UpdateLibrary

import gpu_worker  # noqa: E402  optional add-on: remote shared GPU (Local AI Stack)

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
CONFIG_PATH = Path(os.environ.get("XR_PANEL_CONFIG", Path.home() / ".config/xr-control-panel/config.json"))
DEFAULTS = {
    "bind": "127.0.0.1",
    "port": 8083,
    "runtime_root": None,  # e.g. "/ai/intel-xr-prototype"; None = headset-only mode
    "alvr_api": "http://127.0.0.1:8082",
    "capture_dir": str(Path.home() / ".local/share/xr-control-panel/captures"),
    "approved_registry": str(Path.home() / ".config/intel-xr/approved-devices.json"),
    "client_package": "alvr.client.monado",
    "adb": None,  # optional explicit path to adb
    # Wi-Fi access for headset browsers: listen on all interfaces; clients other than this PC
    # (and USB-reversed headsets, which arrive as 127.0.0.1) must be paired (see pairing below).
    "lan_access": False,
    # A Quest connected by USB once is authorized for Wi-Fi automatically: its browser is paired with
    # this panel (needs lan_access) and ALVR trusts it for Wi-Fi streaming at its Wi-Fi address.
    "auto_authorize_usb": True,
    "auto_trust_usb_streaming": True,
    # With lan_access, also serve the panel over HTTPS (self-signed, covering this PC's LAN addresses)
    # so headset browsers may use the microphone over Wi-Fi. 0 turns it off.
    "https_port": 8483,
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.is_file():
        cfg.update(json.loads(CONFIG_PATH.read_text()))
    return cfg


CFG = load_config()
CAPTURE_DIR = Path(os.path.expanduser(CFG["capture_dir"]))
ADB = (os.path.expanduser(CFG["adb"]) if CFG.get("adb") else None) or shutil.which("adb") or next(
    (p for p in ("/ai/android-sdk/platform-tools/adb", str(Path.home() / "Android/Sdk/platform-tools/adb"))
     if Path(p).is_file()), None)

QUEST_SHOTS = "/sdcard/Oculus/Screenshots"
QUEST_VIDEOS = "/sdcard/Oculus/VideoShots"
CAPTURE_SERVICE = "com.oculus.metacam/.capture.CaptureService"
SERIAL_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
FILE_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}\.(jpg|jpeg|png|webp|mp4|webm|mov|mkv)$")
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv"}
CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
                 ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}
LIBRARY = "library"  # captures/<LIBRARY>/ holds uploaded pictures and videos
MAX_UPLOAD = 4 * 1024 ** 3
DIR_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}$")  # no leading dot: rejects "." and ".."

# Editable keys of the runtime's config/xr-build.json.
EDITABLE = {
    "paths.root": str, "paths.android_home": str, "paths.java_home": str,
    "android.ndk_version": str, "android.rust_target": str, "android.platform_api": int,
    "android.openxr_sdk_repo": str, "android.openxr_sdk_ref": str, "android.usb_stay_awake": bool,
    "alvr.legacy_protocol_test": bool,
    "network.quest_ip": str, "network.direct_ip_fallback": bool, "network.mdns": bool,
    "network.legacy_udp": bool, "network.usb": bool,
    "video.test_pattern": bool, "video.test_pattern_mode": str,
    "demo.openxr_sdk_source": str, "demo.graphics": str, "demo.form_factor": str,
}


# ---------------------------------------------------------------- runtime (optional)
def runtime_root() -> Path | None:
    root = CFG.get("runtime_root")
    if not root:
        return None
    root = Path(os.path.expanduser(root))
    return root if (root / "src/Monado-ALVR/scripts/xr-app.sh").is_file() else None


def runtime_script(name: str) -> Path:
    root = runtime_root()
    if root is None:
        raise RuntimeError("Intel XR runtime is not installed/configured (runtime_root)")
    path = root / "src/Monado-ALVR/scripts" / name
    if not path.is_file():
        raise RuntimeError(f"runtime script missing: {path}")
    return path


def runtime_config_path() -> Path:
    root = runtime_root()
    if root is None:
        raise RuntimeError("Intel XR runtime is not installed/configured (runtime_root)")
    return root / "src/Monado-ALVR/config/xr-build.json"


def alvr(path: str, method: str = "GET", data=None, base: str | None = None) -> bytes:
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request((base or CFG["alvr_api"]) + path, data=body, method=method,
                                 headers={"X-ALVR": "1", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.read()


def systemd_state(unit: str) -> str:
    out = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True)
    return out.stdout.strip() or "unknown"


# ---------------------------------------------------------------- adb / headsets
def adb(*args: str, timeout: float = 20) -> subprocess.CompletedProcess:
    if ADB is None:
        raise RuntimeError("adb not found (install Android platform-tools)")
    return subprocess.run([ADB, *args], capture_output=True, text=True, timeout=timeout)


def list_adb_devices() -> list[dict]:
    if ADB is None:
        return []
    out = adb("devices", "-l", timeout=10).stdout.splitlines()[1:]
    devices = []
    for line in out:
        bits = line.split()
        if len(bits) < 2:
            continue
        extra = dict(b.split(":", 1) for b in bits[2:] if ":" in b)
        devices.append({
            "serial": bits[0],
            "state": bits[1],
            "model": extra.get("model", "").replace("_", " "),
            "transport": "usb" if "usb" in extra else "wifi" if ":" in bits[0] or "_adb-" in bits[0] else "unknown",
            "usb_path": extra.get("usb"),
        })
    return devices


INFO_CMD = (
    'echo "MODEL=$(getprop ro.product.model)"; '
    'echo "BATTERY=$(dumpsys battery | sed -n \'s/^ *level: //p\' | head -1)"; '
    'echo "CHARGING=$(dumpsys battery | sed -n \'s/^ *status: //p\' | head -1)"; '
    'echo "WAKE=$(dumpsys power | sed -n \'s/^ *mWakefulness=//p\' | head -1)"; '
    'echo "CLIENT=$(pm path {pkg} | head -1)"; '
    'echo "PID=$(pidof {pkg})"; '
    'echo "IP=$(ip -4 addr show wlan0 2>/dev/null | sed -n \'s/^ *inet \\([0-9.]*\\).*/\\1/p\' | head -1)"; '
    'echo "IP6=$(ip -6 -o addr show wlan0 2>/dev/null | sed -n \'s/.*inet6 \\([^ /]*\\).*/\\1/p\' | tr \'\\n\' \' \')"; '
    'echo "METACAM=$(pm path com.oculus.metacam | head -1)"'
)

_cache_lock = threading.Lock()
_cache: dict = {"time": 0.0, "data": None}
recordings: dict[str, set] = {}


def valid_ipv6_addresses(text):
    addresses = []
    for value in text.split():
        try:
            address = ipaddress.IPv6Address(value)
            if not address.is_loopback and not address.is_unspecified and not address.is_multicast:
                addresses.append(str(address))
        except ValueError:
            continue
    return list(dict.fromkeys(addresses))


def headset_info(dev: dict) -> dict:
    info = dict(dev)
    if dev["state"] != "device":
        return info
    out = adb("-s", dev["serial"], "shell", INFO_CMD.format(pkg=CFG["client_package"]), timeout=15).stdout
    kv = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    info.update({
        "model": kv.get("MODEL") or dev["model"],
        "battery": int(kv["BATTERY"]) if kv.get("BATTERY", "").isdigit() else None,
        "charging": kv.get("CHARGING") in ("2", "5"),  # BatteryManager: charging / full
        "awake": kv.get("WAKE") == "Awake",
        "client_installed": kv.get("CLIENT", "").startswith("package:"),
        "client_running": bool(kv.get("PID")),
        "ip": kv.get("IP") or None,
        "ipv6": valid_ipv6_addresses(kv.get("IP6", "")),
        "is_quest": kv.get("METACAM", "").startswith("package:"),
        "recording": dev["serial"] in recordings,
    })
    return info


def alvr_clients() -> dict:
    try:
        data = json.loads(alvr("/api/xr/clients"))
        return {"available": True, "auto_accept": data.get("auto_accept", False), "clients": data.get("clients", {})}
    except Exception:
        try:
            session = json.loads(alvr("/api/session"))
            return {"available": True, "auto_accept": False,
                    "clients": session.get("client_connections", session.get("clients", {}))}
        except Exception as e:
            return {"available": False, "error": str(e), "clients": {}}


def headsets_snapshot(max_age: float = 2.0) -> dict:
    with _cache_lock:
        if _cache["data"] is not None and time.time() - _cache["time"] < max_age:
            return _cache["data"]
    headsets = [headset_info(d) for d in list_adb_devices()]
    clients = alvr_clients()
    for h in headsets:  # match ALVR connection entries by IP / wired transport
        h["alvr"] = []
        for name, c in clients.get("clients", {}).items():
            ips = [c.get("current_ip")] + list(c.get("manual_ips") or [])
            addresses = ([h["ip"]] if h.get("ip") else []) + h.get("ipv6", [])
            if any(address in ips or address in name for address in addresses) or (
                    name == "client.wired" and h.get("transport") == "usb" and h.get("client_running")):
                h["alvr"].append({"name": name, "state": c.get("connection_state"), "trusted": c.get("trusted")})
    data = {"adb": ADB is not None, "headsets": headsets, "alvr": clients}
    with _cache_lock:
        _cache.update(time=time.time(), data=data)
    return data


def require_headset(serial: str) -> dict:
    if not SERIAL_RE.match(serial):
        raise ValueError("invalid serial")
    for d in list_adb_devices():
        if d["serial"] == serial:
            if d["state"] != "device":
                raise RuntimeError(f"headset {serial} is {d['state']} (authorize USB debugging in the headset)")
            return d
    raise RuntimeError(f"headset {serial} is not connected")


def capture_dir_for(serial: str) -> Path:
    path = CAPTURE_DIR / re.sub(r"[^A-Za-z0-9._-]", "_", serial)
    path.mkdir(parents=True, exist_ok=True)
    return path


def remote_files(serial: str, folder: str) -> list[str]:
    return [x for x in adb("-s", serial, "shell", "ls", "-t", folder).stdout.split() if FILE_RE.match(x)]


def pull_new(serial: str, folder: str, before: set, wait_s: float) -> str:
    deadline = time.time() + wait_s
    while time.time() < deadline:
        time.sleep(0.4)
        new = [x for x in remote_files(serial, folder) if x not in before]
        if new:
            time.sleep(1.0)  # let the capture service finish writing
            res = adb("-s", serial, "pull", f"{folder}/{new[0]}", str(capture_dir_for(serial) / new[0]), timeout=300)
            if res.returncode != 0:
                raise RuntimeError(res.stderr.strip() or "adb pull failed")
            return new[0]
    raise RuntimeError("the headset did not save a capture (is it awake and in use?)")


def headset_action(serial: str, action: str) -> dict:
    require_headset(serial)
    pkg = CFG["client_package"]
    with _cache_lock:
        _cache["data"] = None
    if action == "screenshot":
        before = set(remote_files(serial, QUEST_SHOTS))
        adb("-s", serial, "shell", "am", "startservice", "-n", CAPTURE_SERVICE, "-a", "TAKE_SCREENSHOT")
        return {"file": pull_new(serial, QUEST_SHOTS, before, 10), "message": "Screenshot saved"}
    if action == "record-start":
        recordings[serial] = set(remote_files(serial, QUEST_VIDEOS))
        # Horizon OS names; START_CAPTURE/STOP_CAPTURE are rejected as invalid.
        adb("-s", serial, "shell", "am", "startservice", "-n", CAPTURE_SERVICE, "-a", "START_INTERNAL_CAPTURE_TO_DISK")
        return {"message": "Recording started"}
    if action == "record-stop":
        before = recordings.pop(serial, set(remote_files(serial, QUEST_VIDEOS)))
        adb("-s", serial, "shell", "am", "startservice", "-n", CAPTURE_SERVICE, "-a", "STOP_INTERNAL_CAPTURE_TO_DISK")
        return {"file": pull_new(serial, QUEST_VIDEOS, before, 30), "message": "Recording saved"}
    if action == "client-launch":
        adb("-s", serial, "shell", "am", "start", "-n", f"{pkg}/android.app.NativeActivity")
        return {"message": "Client launched"}
    if action == "client-close":
        adb("-s", serial, "shell", "am", "force-stop", pkg)
        return {"message": "Client closed"}
    if action == "wake":
        adb("-s", serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
        return {"message": "Wake sent"}
    if action == "pair-wifi":
        # Over USB: open http://<this PC's LAN address>:<port>/?pair=<token> in the headset's
        # browser; the cookie it gets lets it use the panel over Wi-Fi afterwards.
        if not CFG.get("lan_access"):
            raise RuntimeError("turn on Wi-Fi access first (Settings, Panel access)")
        info = headset_info(require_headset(serial))
        if not info.get("is_quest"):
            raise ValueError("Wi-Fi panel pairing requires a Quest headset")
        issue_usb_pairing(info, manual=True)
        return {"message": "Pairing page opened in the headset's browser; bookmark the panel for Wi-Fi use"}
    if action == "panel-in-headset":
        # Over USB only: the headset's own 127.0.0.1:<port> is forwarded to this panel, so the
        # panel stays bound to localhost and nothing is exposed on the network.
        port = int(CFG["port"])
        res = adb("-s", serial, "reverse", f"tcp:{port}", f"tcp:{port}")
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip() or "adb reverse failed (is the headset on USB?)")
        adb("-s", serial, "shell", "am", "start", "-a", "android.intent.action.VIEW",
            "-d", shlex.quote(f"http://127.0.0.1:{port}/?device={DEVICE_IDS.issue(serial)}"))
        return {"message": f"Opened the panel in the headset's browser (http://127.0.0.1:{port}/, over USB)"}
    raise ValueError(f"unknown action {action!r}")


def list_captures(headset: str | None) -> list[dict]:
    if not CAPTURE_DIR.is_dir():
        return []
    items = []
    for d in CAPTURE_DIR.iterdir():
        if not d.is_dir() or (headset and d.name != headset):
            continue
        for f in d.iterdir():
            if FILE_RE.match(f.name):
                st = f.stat()
                items.append({"headset": d.name, "file": f.name, "size": st.st_size, "mtime": st.st_mtime,
                              "type": "video" if f.suffix.lower() in VIDEO_EXTS else "image"})
    return sorted(items, key=lambda x: x["mtime"], reverse=True)[:200]


def capture_export(headset, destination, selected=None):
    if selected is None:
        raise ValueError("Select at least one capture to export")
    if not isinstance(selected, list) or not 1 <= len(selected) <= 200:
        raise ValueError("Select between 1 and 200 captures")
    items, seen = [], set()
    for entry in selected:
        if not isinstance(entry, dict):raise ValueError("Invalid capture selection")
        h, name = entry.get("headset"), entry.get("file")
        if not isinstance(h, str) or not isinstance(name, str) or not DIR_RE.fullmatch(h) or not FILE_RE.fullmatch(name):
            raise ValueError("Invalid capture selection")
        if (h, name) in seen:raise ValueError("Duplicate capture selection")
        seen.add((h, name))
        path = CAPTURE_DIR / h / name
        if not path.is_file():raise ValueError("A selected capture is no longer available")
        stat = path.stat()
        items.append({"headset":h, "file":name, "size":stat.st_size, "mtime":stat.st_mtime,
                      "type":"video" if path.suffix.lower() in VIDEO_EXTS else "image"})
    if not items:
        raise ValueError("No captures to export")
    files = []
    for item in items:
        if not DIR_RE.fullmatch(item["headset"]) or not FILE_RE.fullmatch(item["file"]):
            raise ValueError("Invalid capture name")
        path = CAPTURE_DIR / item["headset"] / item["file"]
        if not path.is_file() or path.is_symlink() or path.parent.is_symlink():
            raise ValueError("Capture is not a regular local file")
        files.append((item, path))
    total = sum(path.stat().st_size for _, path in files)
    if shutil.disk_usage(Path(tempfile.gettempdir())).free < total + 64 * 1024**2:
        raise ValueError("Not enough temporary disk space for this export")
    with gzip.GzipFile(fileobj=destination, mode="wb", compresslevel=9, mtime=0, filename="") as gz:
        with tarfile.open(fileobj=gz, mode="w|", format=tarfile.PAX_FORMAT) as archive:
            metadata = json.dumps({"captures":items}, indent=2).encode()
            member = tarfile.TarInfo("captures.json"); member.size = len(metadata)
            archive.addfile(member, io.BytesIO(metadata))
            for item, path in files:
                archive.add(path, arcname=item["headset"] + "/" + item["file"], recursive=False)
    destination.seek(0)


def delete_capture(headset: str, file: str, on_headset: bool) -> dict:
    """Delete a capture from this PC and, optionally, the same file on the headset."""
    if not DIR_RE.match(headset) or not FILE_RE.match(file):
        raise ValueError("invalid capture name")
    f = CAPTURE_DIR / headset / file
    if not f.is_file():
        raise ValueError("capture not found")
    f.unlink()
    message = f"Deleted {file}"
    if on_headset and headset != LIBRARY:
        folder = QUEST_VIDEOS if Path(file).suffix.lower() in VIDEO_EXTS else QUEST_SHOTS
        try:
            require_headset(headset)
            res = adb("-s", headset, "shell", "rm", "-f", f"{folder}/{file}")
            message += " (also on the headset)" if res.returncode == 0 else " (headset copy not removed)"
        except RuntimeError as e:
            message += f" (headset copy kept: {e})"
    return {"message": message}


def safe_upload_name(name: str) -> str:
    base = Path(name).name
    stem, suffix = os.path.splitext(base)
    suffix = suffix.lower()
    if suffix not in CONTENT_TYPES:
        raise ValueError("upload pictures (jpg, png, webp) or videos (mp4, webm, mov, mkv)")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-")[:100] or "upload"
    return stem + suffix


def save_upload(name: str, length: int, stream) -> dict:
    """Stream an uploaded picture/video into captures/library/ without overwriting anything."""
    if length <= 0:
        raise ValueError("empty upload")
    if length > MAX_UPLOAD:
        raise ValueError("uploads are limited to 4 GiB")
    fname = safe_upload_name(name)
    folder = CAPTURE_DIR / LIBRARY
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".upload-")
    try:
        remaining = length
        with os.fdopen(fd, "wb") as out:
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("upload interrupted")
                out.write(chunk)
                remaining -= len(chunk)
        stem, suffix = os.path.splitext(fname)
        for n in range(1000):
            dst = folder / (fname if n == 0 else f"{stem}-{n}{suffix}")
            try:
                os.link(tmp, dst)  # atomic, fails if the name exists: never overwrite
                break
            except FileExistsError:
                continue
        else:
            raise ValueError("too many files with this name")
    finally:
        os.unlink(tmp)
    return {"message": f"Uploaded {dst.name}", "file": dst.name}


# ---------------------------------------------------------------- headset-friendly video (local or GPU worker)
TRANSCODES: dict[str, dict] = {}
_transcode_lock = threading.Lock()


def running_lofts() -> int:
    return len(subprocess.run(["pgrep", "-x", "intel_xr_loft"], capture_output=True, text=True).stdout.split())


def gpu_transcode_workflow() -> str | None:
    """A GPU worker workflow for video transcoding, if the worker is set up and offers one."""
    if not gpu_worker.status()["configured"]:
        return None
    try:
        return next((w for w in sorted(gpu_worker.workflows()) if "transcode" in w.lower()), None)
    except gpu_worker.GpuWorkerError:
        return None


def _local_transcode(job_id: str, src: Path, dst: Path) -> None:
    base = ["ffmpeg", "-v", "error", "-nostdin", "-n"]
    hw = base + ["-vaapi_device", "/dev/dri/renderD128", "-i", str(src), "-vf",
                 "scale='min(1920,iw)':-2,format=nv12,hwupload", "-c:v", "h264_vaapi", "-b:v", "8M",
                 "-maxrate", "10M", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)]
    sw = base + ["-i", str(src), "-vf", "scale='min(1920,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "21", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)]
    res = subprocess.run(hw, capture_output=True, text=True, timeout=3600)
    how = "Arc hardware encoder"
    if res.returncode != 0:
        dst.unlink(missing_ok=True)
        res = subprocess.run(sw, capture_output=True, text=True, timeout=7200)
        how = "software encoder"
    with _transcode_lock:
        TRANSCODES[job_id].update(status="complete" if res.returncode == 0 else "failed", how=how,
                                  error=res.stderr.strip()[-300:] if res.returncode else "")


def transcode_capture(headset: str, file: str, where: str = "auto") -> dict:
    """Make a video headset-friendly (H.264, at most 1920 wide) into captures/library/. Runs on the
    GPU worker when asked, or automatically when two or more headsets are streaming (this PC's GPU
    is busy encoding their streams) and the worker offers a transcode workflow; otherwise locally."""
    if not DIR_RE.match(headset) or not FILE_RE.match(file):
        raise ValueError("invalid capture name")
    src = CAPTURE_DIR / headset / file
    if not src.is_file() or src.suffix.lower() not in VIDEO_EXTS:
        raise ValueError("pick a video capture")
    if where not in ("auto", "local", "gpu"):
        raise ValueError("where must be auto, local or gpu")
    workflow = gpu_transcode_workflow() if where in ("auto", "gpu") else None
    if where == "gpu" and not workflow:
        raise ValueError("the GPU worker is not set up or offers no transcode workflow")
    if workflow and (where == "gpu" or running_lofts() >= 2):
        rec = gpu_worker.submit(workflow, "Transcode for headset playback: H.264, at most 1920 wide, AAC",
                                src, f"{headset}/{file}")
        return {"message": f"Sent to the GPU worker ({workflow}); check the GPU Worker tab", "job": rec}
    folder = CAPTURE_DIR / LIBRARY
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", src.stem)[:90]
    for n in range(1000):
        dst = folder / (f"{stem}-headset.mp4" if n == 0 else f"{stem}-headset-{n}.mp4")
        if not dst.exists():
            break
    job_id = f"{int(time.time() * 1000):x}"
    with _transcode_lock:
        TRANSCODES[job_id] = {"id": job_id, "source": f"{headset}/{file}", "output": dst.name, "status": "running",
                              "how": "", "error": "", "started": time.time()}
    threading.Thread(target=_local_transcode, args=(job_id, src, dst), daemon=True).start()
    return {"message": f"Preparing {dst.name} on this PC; it appears in Captures when done", "job": TRANSCODES[job_id]}


# ---------------------------------------------------------------- Loft menu (shared with the Loft's library.c)
LOFT_MENU = Path(os.environ.get("XR_LOFT_MENU") or Path.home() / ".config/xr-loft/menu.tsv")
MENU_TYPES = ("builtin", "apk", "pc")
LOFT_BUILTINS = ("pictures", "videos", "checkerboard", "colors", "motion")
DEFAULT_MENU = [
    {"enabled": True, "type": "builtin", "id": "pictures", "title": "Pictures", "subtitle": "Photos and captures", "target": "pictures"},
    {"enabled": True, "type": "builtin", "id": "videos", "title": "Videos", "subtitle": "Uploaded and recorded videos", "target": "videos"},
    {"enabled": False, "type": "builtin", "id": "checkerboard", "title": "Checkerboard", "subtitle": "Red / blue per eye", "target": "checkerboard"},
    {"enabled": False, "type": "builtin", "id": "colors", "title": "Color test", "subtitle": "Solid colour cycle", "target": "colors"},
    {"enabled": False, "type": "builtin", "id": "motion", "title": "Motion test", "subtitle": "Smoothness and latency", "target": "motion"},
]
MENU_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")


def load_menu() -> list[dict]:
    if not LOFT_MENU.is_file():
        return [dict(e) for e in DEFAULT_MENU]
    items = []
    for line in LOFT_MENU.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        f = line.split("\t")
        if len(f) >= 6 and f[1] in MENU_TYPES:
            items.append({"enabled": f[0] == "1", "type": f[1], "id": f[2], "title": f[3], "subtitle": f[4],
                          "target": "\t".join(f[5:])})
    return items


def save_menu(items: list) -> dict:
    if not isinstance(items, list) or len(items) > 16:
        raise ValueError("the menu holds at most 16 entries")
    seen, lines = set(), ["# Intel XR Loft menu: enabled<TAB>type<TAB>id<TAB>title<TAB>subtitle<TAB>target",
                          "# Written by the XR Control Panel; the Loft re-reads it on the \"reload\" command."]
    for it in items:
        kind, ident = str(it.get("type", "")), str(it.get("id", ""))
        title, subtitle, target = (str(it.get(k, "")).strip() for k in ("title", "subtitle", "target"))
        if kind not in MENU_TYPES or not MENU_ID_RE.match(ident) or ident in seen:
            raise ValueError(f"invalid or duplicate menu id {ident!r}")
        if not title or any(c in "\t\n\r" for c in title + subtitle + target) or len(title) > 40 or len(subtitle) > 70:
            raise ValueError(f"invalid title or subtitle for {ident!r}")
        if kind == "builtin" and target not in LOFT_BUILTINS:
            raise ValueError(f"unknown built-in app {target!r}")
        if kind == "apk" and not PACKAGE_RE.match(target):
            raise ValueError(f"invalid Android package name {target!r}")
        if kind == "pc":
            exe = Path(target).expanduser()
            if not exe.is_absolute() or not exe.is_file() or not (os.access(exe, os.X_OK) or (exe.suffix.lower() == ".py" and os.access(exe, os.R_OK))):
                raise ValueError(f"PC mini-game must be an executable or readable Python file (absolute path): {target!r}")
        seen.add(ident)
        lines.append("\t".join(["1" if it.get("enabled") else "0", kind, ident, title, subtitle, target]))
    LOFT_MENU.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOFT_MENU.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, LOFT_MENU)
    reloaded = False
    if subprocess.run(["pgrep", "-x", "intel_xr_loft"], capture_output=True).stdout:
        loft_command("reload")
        reloaded = True
    return {"message": "Menu saved" + ("; the Loft reloaded it" if reloaded else "")}


def headset_packages(serial: str) -> list[str]:
    require_headset(serial)
    out = adb("-s", serial, "shell", "pm", "list", "packages", "-3").stdout
    return sorted(p[8:] for p in out.split() if p.startswith("package:") and PACKAGE_RE.match(p[8:]))


def headset_apps(serial: str) -> dict:
    packages = headset_packages(serial)
    labels, warning = {}, None
    if packages:
        helper = HERE / "android/labels.jar"
        try:
            if not helper.is_file():
                raise RuntimeError("label helper not installed")
            pushed = adb("-s", serial, "push", str(helper), "/data/local/tmp/xr-loft-labels.jar")
            if pushed.returncode:
                raise RuntimeError("could not copy label helper")
            result = adb("-s", serial, "shell", "CLASSPATH=/data/local/tmp/xr-loft-labels.jar",
                         "app_process", "/system/bin", "LoftAppLabels", *packages, timeout=30)
            if result.returncode:
                raise RuntimeError("device label lookup failed")
            labels = json.loads(result.stdout.strip())
            if not isinstance(labels, dict):
                raise ValueError("unexpected label response")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            warning = "Friendly names could not be read. Package names are shown; you can set the title in the Loft."
    apps = [{"package": p, "label": str(labels.get(p) or p).replace("\n", " ").replace("\r", " ").replace("\t", " ").strip() or p}
            for p in packages]
    apps.sort(key=lambda app: (app["label"].casefold(), app["package"]))
    return {"packages": packages, "apps": apps, "warning": warning}


# ---------------------------------------------------------------- runtime features
def status() -> dict:
    root = runtime_root()
    st = {"panel": "ok", "adb": ADB is not None, "runtime": {"installed": root is not None}}
    if root is not None:
        st["runtime"]["service"] = systemd_state("intel-xr-monado.service")
        try:
            alvr("/api/ping")
            st["runtime"]["api"] = "ready"
        except Exception:
            st["runtime"]["api"] = "down"
        loft = subprocess.run(["pgrep", "-x", "intel_xr_loft"], capture_output=True, text=True).stdout.strip()
        checker = subprocess.run(["pgrep", "-x", "intel_xr_checke"], capture_output=True, text=True).stdout.strip()
        st["runtime"]["app"] = "loft" if loft else "checkerboard" if checker else "stopped"
        st["runtime"]["loft_built"] = (runtime_root() / "build/intel-xr-loft/intel_xr_loft").is_file()
        state = LOFT_DIR / "state"
        st["runtime"]["loft_mode"] = state.read_text().strip() if loft and state.is_file() else None
    return st


def config_values() -> dict:
    cfg = json.loads(runtime_config_path().read_text())
    values = {}
    for key in EDITABLE:
        cur = cfg
        for bit in key.split("."):
            cur = cur.get(bit) if isinstance(cur, dict) else None
        if cur is not None:
            values[key] = cur
    return values


def config_defaults() -> dict:
    path = runtime_config_path()
    result = subprocess.run(["git", "-C", str(path.parent.parent), "show", "HEAD:config/xr-build.json"],
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError("Committed runtime defaults are unavailable; no settings were reset")
    cfg = json.loads(result.stdout)
    defaults = {}
    for key in EDITABLE:
        value = cfg
        for bit in key.split("."):
            value = value.get(bit) if isinstance(value, dict) else None
        if value is not None:
            defaults[key] = value
    return defaults


def config_restore(key):
    defaults = config_defaults()
    if key == "*":
        if set(defaults) != set(EDITABLE):
            raise ValueError("Some runtime defaults are missing; no settings were reset")
        changes = defaults
    else:
        if not isinstance(key, str) or key not in defaults:
            raise ValueError("Select an editable setting with an available default")
        changes = {key: defaults[key]}
    config_save(changes)
    return {"message": "Runtime defaults restored. Changes may need a runtime restart."}


def config_save(changes: dict) -> None:
    path = runtime_config_path()
    cfg = json.loads(path.read_text())
    for key, val in changes.items():
        if key not in EDITABLE:
            raise ValueError("setting not editable: " + key)
        typ = EDITABLE[key]
        parsed = (val if isinstance(val, bool) else str(val).lower() in ("1", "true", "yes", "on")) if typ is bool \
            else int(val) if typ is int else str(val)
        cur = cfg
        bits = key.split(".")
        for b in bits[:-1]:
            cur = cur.setdefault(b, {})
        cur[bits[-1]] = parsed
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n")
    os.replace(tmp, path)


def run_runtime(script: str, *args: str, background: bool = False, log: str | None = None) -> str:
    path = runtime_script(script)
    if background:
        out = open(log, "ab") if log else subprocess.DEVNULL
        subprocess.Popen(["bash", str(path), *args], stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        return "started"
    res = subprocess.run(["bash", str(path), *args], capture_output=True, text=True, timeout=120)
    lines = (res.stdout.strip() or res.stderr.strip()).splitlines()
    if res.returncode != 0:
        raise RuntimeError(" ".join(lines[-2:]) or f"{script} failed")
    return " ".join(lines[-2:])


# ---------------------------------------------------------------- Loft (github.com/JLATORRE89/loft)
LOFT_DIR = Path(os.environ.get("XR_LOFT_CONTROL_DIR") or
                Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "xr-loft")
LOFT_COMMANDS = {"lobby", "next", "prev", "exit", "reload", "pause"}  # plus open:<menu id>


def loft_command(cmd: str) -> dict:
    if cmd.startswith("open:"):
        if not any(it["enabled"] and it["id"] == cmd[5:] for it in load_menu()):
            raise ValueError(f"{cmd[5:]!r} is not an enabled Loft menu entry")
    elif cmd not in LOFT_COMMANDS:
        raise ValueError(f"unknown Loft command {cmd!r}")
    if not subprocess.run(["pgrep", "-x", "intel_xr_loft"], capture_output=True).stdout:
        raise RuntimeError("the Loft is not running (start it first)")
    targets = loft_dirs()
    for d in targets:  # every headset's Loft sees the same thing
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "command.tmp"
        tmp.write_text(cmd + "\n")
        os.replace(tmp, d / "command")
    return {"message": f"Loft: {cmd}" + (f" (sent to {len(targets)} headsets)" if len(targets) > 1 else "")}


def loft_dirs() -> list[Path]:
    """Control folders of the running Lofts (one per headset / runtime instance), read from each
    running intel_xr_loft process's environment; the default folder if none can be read."""
    dirs = []
    pids = subprocess.run(["pgrep", "-x", "intel_xr_loft"], capture_output=True, text=True).stdout.split()
    for pid in pids:
        try:
            env = dict(kv.split("=", 1) for kv in
                       Path(f"/proc/{pid}/environ").read_bytes().decode(errors="replace").split("\0") if "=" in kv)
        except OSError:
            continue
        d = Path(env["XR_LOFT_CONTROL_DIR"]) if env.get("XR_LOFT_CONTROL_DIR") else \
            Path(env.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "xr-loft"
        if d not in dirs:
            dirs.append(d)
    return dirs or [LOFT_DIR]


# ---------------------------------------------------------------- approved devices
def approved_tool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HERE / "approved_devices.py"), *args,
                           "--registry", os.path.expanduser(CFG["approved_registry"])],
                          capture_output=True, text=True, timeout=60)


# ---------------------------------------------------------------- HTTP
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}


# ---------------------------------------------------------------- Wi-Fi pairing
TOKEN_FILE = CONFIG_PATH.parent / "pair-token"
COOKIE = "xrpanel"
USB_PAIRS = UsbPairing(CONFIG_PATH.parent / "usb-paired-devices.json")
# Browsers the panel opened on a headset over USB (all arrive from 127.0.0.1) -> that headset.
DEVICE_IDS = DeviceIdentity(CONFIG_PATH.parent / "device-identity.json")
DEVICE_COOKIE = "xrdevice"
_pairing_lock = threading.RLock()
_pairing_wake = threading.Event()
UNPAIRED_PAGE = (b"<!doctype html><meta name=viewport content='width=device-width'><title>XR Control Panel</title>"
                 b"<body style='font:18px system-ui;padding:24px'><h1>Pairing needed</h1><p>This device is not "
                 b"paired with the XR Control Panel. On the PC's panel, connect the headset by USB and use "
                 b"<b>Pair headset for Wi-Fi</b>.</p></body>")


def pair_token(renew: bool = False) -> str:
    import secrets
    if renew or not TOKEN_FILE.is_file():
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32))
    return TOKEN_FILE.read_text().strip()


def lan_address_for(peer_ip: str) -> str:
    """Use the same address family and actual route as the headset."""
    peer = ipaddress.ip_address(peer_ip)
    out = subprocess.run(["ip", "-6" if peer.version == 6 else "-4", "route", "get", str(peer)],
                         capture_output=True, text=True).stdout
    m = re.search(r"\bsrc (\S+)", out)
    if not m:
        raise RuntimeError("no route from this PC to the headset")
    address = ipaddress.ip_address(m.group(1))
    if address.version != peer.version:
        raise RuntimeError("route address family mismatch")
    return str(address)


def url_host(address: str) -> str:
    parsed = ipaddress.ip_address(address)
    return f"[{parsed}]" if parsed.version == 6 else str(parsed)


def pairing_address(info):
    # Prefer existing IPv4 connectivity, then routable IPv6 (including ULA).
    # Link-local addresses need an interface scope that differs between PC and headset.
    candidates = ([info["ip"]] if info.get("ip") else []) + info.get("ipv6", [])
    for candidate in candidates:
        try:
            peer = ipaddress.ip_address(candidate)
            if peer.is_unspecified or peer.is_loopback or peer.is_multicast or peer.is_link_local:
                continue
            return lan_address_for(str(peer))
        except (ValueError, RuntimeError):
            continue
    raise RuntimeError("No reachable Wi-Fi address. Connect the headset to IPv4 or routable IPv6 Wi-Fi.")


def set_lan_access(enabled: bool) -> dict:
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    with _pairing_lock:
        save_panel_setting("lan_access", enabled)
    if enabled:
        pair_token()
    # Re-bind: restart ourselves shortly after this response is sent.
    subprocess.Popen(["bash", "-c", "sleep 1; systemctl --user restart xr-control-panel.service"],
                     start_new_session=True)
    return {"message": "Wi-Fi access " + ("on" if enabled else "off") + "; the panel restarts now"}


def save_panel_setting(key, value):
    cfg = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.is_file() else {}
    cfg[key] = value
    atomic_json(CONFIG_PATH, cfg)
    CFG[key] = value


def set_auto_authorize_usb(enabled):
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    with _pairing_lock:
        save_panel_setting("auto_authorize_usb", enabled)
    _pairing_wake.set()
    return {"message": "Automatic USB authorization " + ("on" if enabled else "off")}


def issue_usb_pairing(info, manual=False):
    # Never use the device's current address as an authorization identity.
    address = pairing_address(info)
    with _pairing_lock:
        if not CFG.get("lan_access") or (not manual and not CFG.get("auto_authorize_usb")):
            return
        token = USB_PAIRS.begin(info["serial"], info.get("model", "Quest"), manual=manual)
        if not token:
            return
        url = f"http://{url_host(address)}:{int(CFG['port'])}/?pair={token}"
        try:
            result = adb("-s", info["serial"], "shell", "am", "start", "-a", "android.intent.action.VIEW",
                         "-d", shlex.quote(url))
            if result.returncode or "Error:" in result.stdout or "Error:" in result.stderr:
                raise RuntimeError("headset browser could not be opened")
        except Exception:
            USB_PAIRS.launch_failed(info["serial"])
            raise


_usb_trusted: dict[str, str] = {}   # serial -> "mac|ip" already recorded
_usb_checked: dict[str, float] = {}  # serial -> last time its details were read


def alvr_api_for(serial: str) -> str:
    """ALVR API of the runtime serving this headset: an extra instance pinned to its serial
    (scripts/xr-instance.sh), else the default runtime."""
    inst_dir = Path.home() / ".config/intel-xr/instances"
    for env in sorted(inst_dir.glob("*.env")) if inst_dir.is_dir() else []:
        kv = dict(line.split("=", 1) for line in env.read_text().splitlines() if "=" in line)
        if kv.get("ALVR_WIRED_SERIAL") == serial and kv.get("XR_INSTANCE_INDEX", "").isdigit():
            return f"http://127.0.0.1:{8090 + int(kv['XR_INSTANCE_INDEX'])}"
    return CFG["alvr_api"]


def trust_usb_headset_streaming(info) -> dict | None:
    """A Quest seen on USB (physical evidence) becomes an approved device and is trusted by ALVR
    for Wi-Fi streaming: client entry "usb-<serial>" whose manual IP is its current Wi-Fi IPv4
    address (refreshed on each USB connection, since DHCP addresses change)."""
    import approved_devices as registry
    serial, ip = info["serial"], info.get("ip") or ""
    # Android hides /sys/class/net/*/address from the shell; the Wi-Fi service reports the factory
    # MAC (stable identity) and the randomized MAC this network actually sees.
    out = adb("-s", serial, "shell", "dumpsys", "wifi").stdout
    factory = re.search(r"wifi_sta_factory_mac_address=([0-9a-fA-F:]{17})", out)
    randomized = re.search(r"mRandomizedMacAddress: ([0-9a-fA-F:]{17})", out)
    try:
        mac = registry.norm(factory.group(1) if factory else "")
    except ValueError:
        return None  # Wi-Fi service not ready: try again later
    key = f"{mac}|{ip}"
    if _usb_trusted.get(serial) == key:
        return None
    path = Path(os.path.expanduser(CFG["approved_registry"]))
    reg = registry.load_registry(path)
    entry = next((d for d in reg["devices"] if d["mac_address"] == mac), None)
    if entry is None:
        entry = {"mac_address": mac, "name": info.get("model") or serial,
                 "notes": "added automatically after a USB connection", "enabled": True}
        reg["devices"].append(entry)
    entry.update(serial=serial, wifi_ip=ip, last_usb=time.strftime("%Y-%m-%d %H:%M"))
    if randomized:
        entry["network_mac"] = registry.norm(randomized.group(1))  # what the Wi-Fi router sees
    entry.setdefault("source", "usb")
    reg["devices"].sort(key=lambda d: d["mac_address"])
    atomic_json(path, reg)
    status = "approved; no Wi-Fi IPv4 address yet"
    if ip:
        base, name = alvr_api_for(serial), f"usb-{serial}"
        for action in ({"AddIfMissing": {"trusted": True, "manual_ips": [ip]}}, {"SetManualIps": [ip]}, "Trust",
                       {"SetDisplayName": info.get("model") or serial}):
            alvr("/api/session/client-connections", "POST", [name, action], base=base)  # raises if not running
        status = f"ALVR trusts {name} at {ip}"
    _usb_trusted[serial] = key
    print(f"[panel] USB headset {serial}: {status}", flush=True)
    return {"serial": serial, "mac": mac, "ip": ip, "status": status}


def auto_pair_usb_once():
    for device in list_adb_devices():
        # Positive USB transport evidence, successful Android debugging authorization,
        # and the Quest system package are all required. Ignore phones, emulators and Wi-Fi ADB.
        if device["state"] != "device" or not device.get("usb_path") or not SERIAL_RE.fullmatch(device["serial"]):
            continue
        serial = device["serial"]
        browser = (CFG.get("lan_access") and CFG.get("auto_authorize_usb") and USB_PAIRS.needs_pairing(serial))
        streaming = CFG.get("auto_trust_usb_streaming", True)
        if not browser and not (streaming and time.time() - _usb_checked.get(serial, 0) >= 30):
            continue
        _usb_checked[serial] = time.time()
        try:
            info = headset_info(device)
        except Exception:
            continue  # disconnected/offline: must not block other headsets
        if not info.get("is_quest"):
            continue
        if streaming and info.get("client_installed"):
            try:
                trust_usb_headset_streaming(info)
            except Exception:
                _usb_trusted.pop(serial, None)  # runtime not running yet: retry on a later pass
        if browser and (info.get("ip") or info.get("ipv6")):
            try:
                issue_usb_pairing(info)
            except Exception:
                # Never log the bearer URL or raw subprocess output.
                continue


def auto_pair_usb_worker():
    while True:
        try:
            auto_pair_usb_once()
        except Exception:
            pass  # ADB can be unavailable while the headset or workstation reconnects.
        _pairing_wake.wait(5)
        _pairing_wake.clear()


# ---------------------------------------------------------------- local speech-to-text (whisper.cpp)
# Fallback for headset browsers without built-in speech recognition: the page records a short clip
# and the panel transcribes it on this PC. Audio is never stored or sent elsewhere.
_whisper_lock = threading.Lock()


def whisper_paths() -> tuple[str | None, str | None]:
    root = runtime_root()
    cli = CFG.get("whisper_cli") or (str(root / "build/whisper.cpp/build/bin/whisper-cli") if root else None)
    model = CFG.get("whisper_model") or (str(root / "models/whisper/ggml-base.en.bin") if root else None)
    ok = cli and model and os.access(cli, os.X_OK) and os.path.isfile(model)
    return (cli, model) if ok else (None, None)


def transcribe(audio: bytes) -> str:
    cli, model = whisper_paths()
    if not cli:
        raise RuntimeError("Local speech recognition is not installed on this PC")
    if not audio or len(audio) > 5 * 1024 * 1024:
        raise ValueError("Record a spoken request of up to about 30 seconds")
    with tempfile.TemporaryDirectory() as tmp:
        src, wav = Path(tmp) / "clip", Path(tmp) / "clip.wav"
        src.write_bytes(audio)
        conv = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(src), "-t", "30", "-ar", "16000",
                               "-ac", "1", str(wav)], capture_output=True, text=True, timeout=60)
        if conv.returncode or not wav.is_file():
            raise ValueError("The recording could not be read")
        # Whisper invents words ("you", "Thank you.") for silence: require audible speech first.
        vol = subprocess.run(["ffmpeg", "-v", "info", "-nostdin", "-i", str(wav), "-af", "volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True, timeout=60).stderr
        peak = re.search(r"max_volume: (-?[\d.]+) dB", vol)
        if not peak or float(peak.group(1)) < -40.0:
            raise ValueError("The recording was silent; check the microphone (Test Quest microphone) and speak closer")
        with _whisper_lock:  # CPU-heavy: one transcription at a time
            res = subprocess.run([cli, "-m", model, "-f", str(wav), "-nt", "-np", "-t", str(min(8, os.cpu_count() or 4))],
                                 capture_output=True, text=True, timeout=120)
    text = " ".join(line.strip() for line in res.stdout.splitlines() if line.strip())
    if res.returncode or not text or text.strip("[] ").upper() in ("BLANK_AUDIO", "SILENCE"):
        raise ValueError("No speech was recognised; speak closer to the headset and try again")
    return text


# ---------------------------------------------------------------- headset view and voice without ADB
def instance_env_for(serial: str) -> dict:
    """Settings of the extra runtime instance pinned to this headset's serial (scripts/xr-instance.sh);
    empty for a headset on the default runtime."""
    inst_dir = Path.home() / ".config/intel-xr/instances"
    for env in sorted(inst_dir.glob("*.env")) if inst_dir.is_dir() else []:
        kv = dict(line.split("=", 1) for line in env.read_text().splitlines() if "=" in line)
        if kv.get("ALVR_WIRED_SERIAL") == serial:
            return kv
    return {}


def runtime_dir_for(serial: str) -> Path:
    """XDG runtime folder of the runtime streaming this headset."""
    rdir = instance_env_for(serial).get("XDG_RUNTIME_DIR")
    return Path(rdir or os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")


def headset_mic_node(serial: str) -> str:
    """PipeWire source ALVR creates for this headset's microphone while it streams."""
    name = instance_env_for(serial).get("ALVR_INSTANCE_NAME")
    return f"ALVR Microphone ({name})" if name else "ALVR Microphone"


def record_headset_mic(serial: str, seconds: float) -> bytes:
    """Record the headset's microphone as streamed by ALVR over Wi-Fi (no browser, no ADB)."""
    if not shutil.which("pw-record"):
        raise RuntimeError("PipeWire tools (pw-record) are not installed on this PC")
    node = headset_mic_node(serial)
    ports = subprocess.run(["pw-link", "-o"], capture_output=True, text=True, timeout=10).stdout.splitlines()
    if not any(line.startswith(node + ":") for line in ports):
        raise RuntimeError("This headset's microphone stream is not available. It must be streaming, "
                           "with microphone access allowed for the ALVR app in the headset")
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "mic.wav"
        proc = subprocess.Popen(["pw-record", "--target", node, "--rate", "16000", "--channels", "1",
                                 "--format", "s16", str(wav)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=10)
        data = wav.read_bytes() if wav.is_file() else b""
    if len(data) <= 44:
        raise RuntimeError("Nothing was recorded from the headset microphone")
    return data


def stream_codec(data: bytes) -> str:
    """ffmpeg demuxer for an Annex-B keyframe: HEVC starts with a VPS/SPS NAL, H.264 with SPS/AUD."""
    i = data.find(b"\x00\x00\x01")
    head = data[i + 3] if 0 <= i < len(data) - 3 else 0
    return "hevc" if (head >> 1) & 0x3F in (32, 33, 34, 35) and head & 0x81 == 0 else "h264"


def stream_view_capture(serial: str) -> str:
    """Capture what the runtime streams to this headset (works over Wi-Fi, no ADB): ask its encoder
    for one keyframe (alvr_render companion step 13), decode the left eye and save it as a capture.
    Shows app/Loft content, not passthrough or the Quest's own overlays."""
    rdir = runtime_dir_for(serial)
    frame, request = rdir / "intel-xr-view.h264", rdir / "intel-xr-view-request"
    if not rdir.is_dir():
        raise RuntimeError("the headset's runtime is not running")
    before = frame.stat().st_mtime_ns if frame.exists() else 0
    request.touch()
    deadline = time.time() + 5
    while time.time() < deadline:
        if frame.exists() and frame.stat().st_mtime_ns != before:
            break
        time.sleep(0.1)
    else:
        request.unlink(missing_ok=True)
        raise RuntimeError("the headset's stream did not answer (is its runtime running?)")
    name = f"view-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
    out = capture_dir_for(serial) / name
    fmt = stream_codec(frame.read_bytes()[:64])
    res = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", fmt, "-i", str(frame), "-frames:v", "1",
                          "-vf", "crop=iw/2:ih:0:0", "-q:v", "2", str(out)], capture_output=True, text=True, timeout=30)
    if res.returncode or not out.is_file():
        raise RuntimeError("the captured stream frame could not be decoded")
    return name


def gpu_screen_request(serial, workflow, prompt):
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
        raise ValueError("Speak or type a request of at most 2000 characters")
    if not isinstance(serial, str) or not SERIAL_RE.fullmatch(serial):
        raise ValueError("Select the headset to capture")
    available = gpu_worker.workflows()
    info = available.get(workflow)
    if not isinstance(info, dict) or int(info.get("reference_count") or 0) != 1:
        raise ValueError("Select a GPU image-analysis workflow accepting one source image")
    try:
        require_headset(serial)
        on_usb = True
    except (RuntimeError, ValueError):
        on_usb = False
    if on_usb:   # the Quest screenshot includes passthrough and system overlays
        name = headset_action(serial, "screenshot")["file"]
    else:        # over Wi-Fi: the frame the runtime streams to this headset
        try:
            name = stream_view_capture(serial)
        except RuntimeError as e:
            raise RuntimeError(f"Cannot capture this headset's view: {e}") from None
    shot = {"file": name}
    source = capture_dir_for(serial) / name
    rec = gpu_worker.submit(workflow, prompt.strip(), source, serial + "/" + shot["file"],
                            review_serial=serial)
    return {"message":"Captured the headset view and submitted your request; the result will return to this headset", "job":rec}


def gpu_deliver_review(rec) -> str:
    """Show a finished result on the headset that asked for it. Over USB: copy the image to its
    Pictures and open the review in its browser. Headset not on USB (Wi-Fi only): the result waits
    in that headset's own panel page (its browser polls /api/gpu/jobs, filtered to itself)."""
    serial = rec["review_serial"]
    try:
        require_headset(serial)
    except RuntimeError:
        return "ready"
    files = [name for name in rec.get("outputs", []) if FILE_RE.fullmatch(name) and Path(name).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    if not files:
        raise RuntimeError("The workflow returned no reviewable image. Choose an image-analysis workflow that returns an annotated image.")
    for name in files:
        path = CAPTURE_DIR / gpu_worker.OUTPUT_FOLDER / name
        if not path.is_file():raise RuntimeError("Review image is missing")
        result = adb("-s", serial, "push", str(path), "/sdcard/Pictures/", timeout=120)
        if result.returncode:raise RuntimeError("Could not copy the review image to the headset")
    port = str(int(CFG["port"]))
    result = adb("-s", serial, "reverse", "tcp:" + port, "tcp:" + port)
    if result.returncode:raise RuntimeError("Could not open the panel connection on the headset")
    result = adb("-s", serial, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d",
                 shlex.quote("http://127.0.0.1:" + port + "/gpu-review/" + rec["request_id"]
                             + "?device=" + DEVICE_IDS.issue(serial)))
    if result.returncode or "Error:" in result.stdout or "Error:" in result.stderr:
        raise RuntimeError("Review was copied, but its headset browser could not be opened")
    return "delivered"


_gpu_refresh_lock = threading.Lock()

def refresh_gpu_job(ident):
    with _gpu_refresh_lock:
        return gpu_worker.refresh(ident, CAPTURE_DIR)


def gpu_screen_worker():
    while True:
        for rec in gpu_worker.list_jobs():
            if not rec.get("review_serial") or rec.get("review_state") not in ("waiting", "delivering"):
                continue
            ident = rec["request_id"]
            try:
                rec = refresh_gpu_job(ident)
                if rec["status"] in ("failed", "cancelled"):
                    gpu_worker._update(ident, review_state="failed", review_error="GPU job did not complete")
                elif rec["status"] == "complete":
                    gpu_worker._update(ident, review_state="delivering")
                    gpu_worker._update(ident, review_state=gpu_deliver_review(rec), review_error="")
            except Exception as e:
                gpu_worker._update(ident, review_state="failed", review_error=str(e)[:500])
        time.sleep(5)


def job_owned_by(rec: dict, serial: str | None) -> bool:
    """Headset browsers see only their own voice/GPU jobs; the PC's browser (operator) sees all."""
    if serial is None:
        return True
    return rec.get("review_serial") == serial or str(rec.get("source", "")).startswith(serial + "/")


def gpu_output_owner_ok(name: str, serial: str | None) -> bool:
    if serial is None:
        return True
    return any(name in (j.get("outputs") or []) for j in gpu_worker.list_jobs() if job_owned_by(j, serial))


def gpu_review_page(ident):
    rec = gpu_worker._find(ident)
    pictures = []
    for name in rec.get("outputs", []):
        if FILE_RE.fullmatch(name) and Path(name).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            pictures.append('<img style="max-width:100%;height:auto" alt="GPU analysis result" src="/captures/gpu-worker/' + name + '">')
    return ('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Headset review</title>'
            '<body style="background:#162030;color:white;font:20px system-ui;padding:24px"><h1>GPU review</h1><p>'
            + html.escape(rec.get("prompt", "")) + '</p>' + ''.join(pictures) + '<p><a style="color:lightblue" href="/#gpu">Back to GPU Worker</a></p></body>').encode()


AAPT = CFG.get("aapt") or shutil.which("aapt2") or next(
    (str(p) for sdk in (Path("/ai/android-sdk"), Path.home()/"Android/Sdk")
     for p in sorted(sdk.glob("build-tools/*/aapt2"), reverse=True) if p.is_file()), None)
UPDATES = UpdateLibrary(CFG.get("updates_dir", str(Path.home()/".local/share/xr-control-panel/updates")),
                        adb, list_adb_devices, AAPT)

class Handler(BaseHTTPRequestHandler):
    server_version = "XRControlPanel/1"

    def authorized(self) -> bool:
        """This PC (and USB-reversed headsets) always; other clients only with the pairing cookie.
        A GET /?pair=<token> sets the cookie."""
        import hmac
        from http.cookies import SimpleCookie
        client = self.client_address[0]
        address = ipaddress.ip_address(client)
        local_address = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped else address
        if local_address.is_loopback:
            return True
        token = pair_token() if TOKEN_FILE.is_file() else None
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        if COOKIE in cookie and ((token and hmac.compare_digest(cookie[COOKIE].value, token)) or USB_PAIRS.authorized(cookie[COOKIE].value)):
            return True
        url = urlparse(self.path)
        offered = parse_qs(url.query).get("pair", [""])[0]
        if self.command == "GET" and url.path == "/" and offered and ((token and hmac.compare_digest(offered, token)) or USB_PAIRS.accept(offered)):
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"{COOKIE}={offered}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        self.send(401, UNPAIRED_PAGE, "text/html; charset=utf-8")
        return False

    def identity(self) -> str | None:
        """The headset this browser belongs to (Wi-Fi pairing grant or the USB device cookie);
        None for the PC's own browser and global LAN pairings (operator)."""
        from http.cookies import SimpleCookie
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        if COOKIE in cookie:
            serial = USB_PAIRS.serial_for(cookie[COOKIE].value)
            if serial:
                return serial
        if DEVICE_COOKIE in cookie:
            return DEVICE_IDS.serial_for(cookie[DEVICE_COOKIE].value)
        return None

    def log_message(self, *args):
        pass

    def send(self, code: int, body: bytes, ctype: str = "application/json", cache: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # Static files revalidate on every load so panel updates show at once (headset browsers too).
        self.send_header("Cache-Control", "no-cache" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code: int = 200):
        self.send(code, json.dumps(obj).encode())

    def error_json(self, e: Exception, code: int = 500):
        self.json({"error": str(e)}, code)

    def body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))

    def do_GET(self):
        if not self.authorized():
            return
        url = urlparse(self.path)
        path = url.path
        offered = parse_qs(url.query).get("device", [""])[0]
        if offered and DEVICE_IDS.serial_for(offered):
            # Opened by the panel on a headset: remember which headset this browser is.
            self.send_response(303)
            self.send_header("Location", path)
            self.send_header("Set-Cookie", f"{DEVICE_COOKIE}={offered}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        me = self.identity()
        try:
            if path == "/api/voice/status":
                return self.json({"available": whisper_paths()[0] is not None,
                                  "https_port": HTTPS_PORT[0]})
            if path == "/api/whoami":
                name = next((d.get("model") for d in list_adb_devices() if d["serial"] == me), None) if me else None
                return self.json({"serial": me, "name": name or me, "role": "headset" if me else "operator"})
            if path in ("/", "/index.html"):
                return self.send(200, (STATIC / "index.html").read_bytes(), STATIC_TYPES[".html"])
            if path.startswith("/static/"):
                name = path[len("/static/"):]
                f = STATIC / name
                if "/" in name or f.suffix not in STATIC_TYPES or not f.is_file():
                    return self.json({"error": "not found"}, 404)
                return self.send(200, f.read_bytes(), STATIC_TYPES[f.suffix], cache=True)
            m = re.fullmatch(r"/gpu-review/([0-9a-f-]{36})", path)
            if m:
                if not job_owned_by(gpu_worker._find(m.group(1)), me):
                    return self.json({"error": "not found"}, 404)
                return self.send(200, gpu_review_page(m.group(1)), "text/html; charset=utf-8")
            if path == "/api/updates/downloader":
                folder = HERE / "downloader"
                if not folder.is_dir():
                    folder = HERE.parent / "xr-downloader"
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                    for name in ("xr_downloader.py", "README.md", "xr-downloader.cmd", "xr-downloader.sh"):
                        archive.writestr("XR-Downloader/" + name, (folder / name).read_bytes())
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", 'attachment; filename="XR-Downloader.zip"')
                self.send_header("Content-Length", str(len(buffer.getvalue())))
                self.end_headers(); self.wfile.write(buffer.getvalue())
                return
            if path == "/api/updates/export":
                body = json.dumps(UPDATES.export_manifest(), indent=2).encode() + b"\n"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Disposition", 'attachment; filename="xr-downloads.json"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers(); self.wfile.write(body)
                return
            if path == "/api/updates":
                return self.json(UPDATES.listing())
            m = re.fullmatch(r"/api/updates/([a-f0-9]{64})/download", path)
            if m:
                file = UPDATES.file(m.group(1))
                with file.open("rb") as stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(file.stat().st_size))
                    self.send_header("Content-Disposition", f'attachment; filename="{m.group(1)}{file.suffix}"')
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    shutil.copyfileobj(stream, self.wfile, 1024*1024)
                return
            if path == "/api/status":
                return self.json(status())
            if path == "/api/transcodes":
                with _transcode_lock:
                    return self.json({"jobs": sorted(TRANSCODES.values(), key=lambda j: -j["started"])})
            if path == "/api/panel/access":
                return self.json({"lan_access": bool(CFG.get("lan_access")), "port": int(CFG["port"]),
                                  "paired_token_exists": TOKEN_FILE.is_file(),
                                  "auto_authorize_usb": bool(CFG.get("auto_authorize_usb")),
                                  "usb_devices": USB_PAIRS.public(),
                                  "ipv6_available": socket.has_dualstack_ipv6()})
            if path == "/api/headsets":
                return self.json(headsets_snapshot())
            if path == "/api/captures":
                headset = parse_qs(url.query).get("headset", [None])[0]
                caps = list_captures(headset)
                if me:  # another headset's voice/GPU results are not listed
                    caps = [c for c in caps if c["headset"] != gpu_worker.OUTPUT_FOLDER or gpu_output_owner_ok(c["file"], me)]
                return self.json({"captures": caps})
            if path.startswith("/captures/"):
                parts = [unquote(p) for p in path[len("/captures/"):].split("/")]
                if len(parts) != 2 or not DIR_RE.match(parts[0]) or not FILE_RE.match(parts[1]):
                    return self.json({"error": "not found"}, 404)
                if parts[0] == gpu_worker.OUTPUT_FOLDER and not gpu_output_owner_ok(parts[1], me):
                    return self.json({"error": "not found"}, 404)
                f = CAPTURE_DIR / parts[0] / parts[1]
                if not f.is_file():
                    return self.json({"error": "not found"}, 404)
                ctype = CONTENT_TYPES.get(f.suffix.lower(), "application/octet-stream")
                with f.open("rb") as stream:
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(f.stat().st_size))
                    if parse_qs(url.query).get("download") == ["1"]:
                        self.send_header("Content-Disposition", f'attachment; filename="{f.name}"')
                    self.end_headers()
                    shutil.copyfileobj(stream, self.wfile, 1024*1024)
                return
            if path == "/api/config":
                return self.json({"values": config_values(), "defaults": config_defaults(), "types": {k: t.__name__ for k, t in EDITABLE.items()}})
            if path == "/api/clients":
                return self.json(alvr_clients())
            if path == "/api/loft/menu":
                return self.json({"items": load_menu(), "builtins": LOFT_BUILTINS})
            m = re.match(r"^/api/headsets/([^/]+)/packages$", path)
            if m:
                return self.json(headset_apps(unquote(m.group(1))))
            if path == "/api/gpu/status":
                return self.json(gpu_worker.status())
            if path == "/api/gpu/workflows":
                return self.json({"workflows": gpu_worker.workflows()})
            if path == "/api/gpu/jobs":
                return self.json({"jobs": [j for j in gpu_worker.list_jobs() if job_owned_by(j, me)]})
            if path == "/api/approved":
                res = approved_tool("list")
                if res.returncode != 0:
                    raise RuntimeError(res.stderr.strip())
                return self.send(200, res.stdout.encode())
            return self.json({"error": "not found"}, 404)
        except gpu_worker.GpuWorkerError as e:
            return self.error_json(e, e.status)
        except Exception as e:
            return self.error_json(e)

    def do_POST(self):
        if not self.authorized():
            return
        path = urlparse(self.path).path
        try:
            if path == "/api/captures/export":
                if int(self.headers.get("Content-Length", "0") or 0) > 128 * 1024:
                    raise ValueError("Capture selection is too large")
                form = parse_qs(self.body().decode())
                selected = json.loads(form.get("selection", ["null"])[0])
                with tempfile.TemporaryFile() as archive:
                    capture_export(None, archive, selected)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/gzip")
                    self.send_header("Content-Disposition", 'attachment; filename="xr-selected-captures.tar.gz"')
                    self.send_header("Content-Length", str(os.fstat(archive.fileno()).st_size))
                    self.end_headers()
                    shutil.copyfileobj(archive, self.wfile, 1024*1024)
                return
            if path.startswith("/api/updates/") and self.headers.get("Origin"):
                if urlparse(self.headers["Origin"]).netloc != self.headers.get("Host"):
                    return self.json({"error": "Update actions must originate from this panel"}, 403)
            if path == "/api/updates/import":
                self.connection.settimeout(120)
                return self.json(UPDATES.import_bundle(int(self.headers.get("Content-Length", "0") or 0), self.rfile), 201)
            if path == "/api/updates/source":
                return self.json(UPDATES.save_source(json.loads(self.body())))
            if path == "/api/updates/remove-source":
                return self.json(UPDATES.remove_source(json.loads(self.body()).get("sha256")))
            if path == "/api/updates/upload":
                # Bound stalled uploads; stream to disk, never keep multi-GB files in memory.
                self.connection.settimeout(120)
                return self.json(UPDATES.upload(unquote(self.headers.get("X-Filename", "")),
                    self.headers.get("X-Update-Kind", ""), int(self.headers.get("Content-Length", "0") or 0),
                    self.rfile, self.headers.get("X-SHA256", "").strip()), 201)
            if path in ("/api/updates/prepare", "/api/updates/install", "/api/updates/remove", "/api/updates/verify", "/api/updates/close-job"):
                req = json.loads(self.body())
                if path.endswith("/prepare"):
                    return self.json(UPDATES.prepare(req.get("id"), req.get("serial")))
                if path.endswith("/install"):
                    return self.json(UPDATES.start(req.get("id"), req.get("serial"), req.get("confirmed")), 202)
                if path.endswith("/remove"):
                    return self.json(UPDATES.remove(req.get("id")))
                if path.endswith("/close-job"):
                    return self.json(UPDATES.close_job(req.get("job")))
                return self.json(UPDATES.verify(req.get("job")))
            if path == "/api/panel/lan":
                return self.json(set_lan_access(json.loads(self.body()).get("enabled", False)))
            if path == "/api/panel/auto-usb":
                return self.json(set_auto_authorize_usb(json.loads(self.body()).get("enabled")))
            if path == "/api/panel/revoke":
                with _pairing_lock:
                    pair_token(renew=True)
                    USB_PAIRS.revoke()
                return self.json({"message": "Paired devices revoked; pair headsets again to use Wi-Fi"})
            m = re.match(r"^/api/headsets/([^/]+)/([a-z-]+)$", path)
            if m:
                return self.json(headset_action(unquote(m.group(1)), m.group(2)))
            m = re.match(r"^/api/app/(start|stop|stop-all)$", path)
            if m:
                args = [m.group(1)]
                if m.group(1) == "start":
                    app = parse_qs(urlparse(self.path).query).get("app", ["checkerboard"])[0]
                    if app not in ("checkerboard", "loft"):
                        raise ValueError("app must be checkerboard or loft")
                    args.append(app)
                return self.json({"message": run_runtime("xr-app.sh", *args)})
            if path == "/api/loft/menu":
                return self.json(save_menu(json.loads(self.body()).get("items")))
            m = re.match(r"^/api/loft/([a-z]+(?::[a-z0-9_-]{1,40})?)$", path)
            if m:
                return self.json(loft_command(m.group(1)))
            if path == "/api/library/upload":
                return self.json(save_upload(unquote(self.headers.get("X-Filename", "")),
                                             int(self.headers.get("Content-Length", "0") or 0), self.rfile), 201)
            if path == "/api/captures/transcode":
                req = json.loads(self.body())
                return self.json(transcode_capture(str(req.get("headset", "")), str(req.get("file", "")),
                                                   str(req.get("where", "auto"))), 202)
            if path == "/api/captures/delete":
                req = json.loads(self.body())
                return self.json(delete_capture(str(req.get("headset", "")), str(req.get("file", "")),
                                                bool(req.get("on_headset", False))))
            if path == "/api/gpu/config":
                req = json.loads(self.body())
                return self.json({"message": "GPU worker settings saved", **gpu_worker.save_conf(
                    str(req.get("address", "")), str(req.get("server_name", "")), str(req.get("ca_file", "")),
                    req.get("key") or None, bool(req.get("clear_key", False)))})
            if path == "/api/gpu/test":
                acct = gpu_worker.account()
                return self.json({"message": "Connected to the GPU worker", "account": acct})
            if path == "/api/voice/transcribe":
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length > 5 * 1024 * 1024:
                    return self.json({"error": "Recording too long"}, 413)
                return self.json({"text": transcribe(self.rfile.read(length))})
            if path == "/api/voice/listen":
                # Wi-Fi voice without the browser microphone: record the headset's ALVR mic stream.
                req = json.loads(self.body())
                me = self.identity()
                if me and req.get("serial") not in (None, "", me):
                    return self.json({"error": "A headset can only listen through its own microphone"}, 403)
                serial = me or req.get("serial")
                if not isinstance(serial, str) or not SERIAL_RE.fullmatch(serial):
                    raise ValueError("Select the headset to listen to")
                seconds = req.get("seconds", 6)
                if not isinstance(seconds, (int, float)) or not 1 <= seconds <= 15:
                    raise ValueError("Listen for 1 to 15 seconds")
                return self.json({"text": transcribe(record_headset_mic(serial, float(seconds)))})
            if path == "/api/gpu/screen-request":
                req = json.loads(self.body())
                me = self.identity()
                if me and req.get("serial") not in (None, "", me):
                    return self.json({"error": "A headset can only capture and review its own view"}, 403)
                return self.json(gpu_screen_request(me or req.get("serial"), req.get("workflow"), req.get("prompt")), 202)
            if path == "/api/gpu/retry-review":
                rec = gpu_worker._find(json.loads(self.body()).get("request_id"))
                if not job_owned_by(rec, self.identity()):
                    return self.json({"error": "not found"}, 404)
                if not rec.get("review_serial") or rec.get("review_state") != "failed":
                    raise ValueError("No failed headset review to retry")
                gpu_worker._update(rec["request_id"], review_state="waiting", review_error="")
                return self.json({"message":"Headset review queued for retry"})
            if path == "/api/gpu/jobs":
                req = json.loads(self.body())
                source, label = None, ""
                if req.get("headset") or req.get("file"):
                    h, f = str(req.get("headset", "")), str(req.get("file", ""))
                    if not DIR_RE.match(h) or not FILE_RE.match(f) or not (CAPTURE_DIR / h / f).is_file():
                        raise ValueError("capture not found")
                    source, label = CAPTURE_DIR / h / f, f"{h}/{f}"
                rec = gpu_worker.submit(str(req.get("workflow", "")), str(req.get("prompt", ""))[:2000], source, label)
                return self.json({"message": "Job submitted to the shared GPU", "job": rec}, 202)
            m = re.match(r"^/api/gpu/jobs/([0-9a-f-]{36})/refresh$", path)
            if m:
                rec = refresh_gpu_job(m.group(1))
                note = f"; saved {len(rec['outputs'])} output(s) to Captures" if rec.get("outputs") else ""
                return self.json({"message": f"Job {rec['status']}{note}", "job": rec})
            if path == "/api/service/restart":
                run_runtime("monado-service.sh", "restart", background=True)
                return self.json({"message": "Runtime restart requested"}, 202)
            if path == "/api/service/rebuild":
                log = str(runtime_root() / "logs/control-panel-rebuild.log")
                run_runtime("rebuild-runtime.sh", background=True, log=log)
                return self.json({"message": "Rebuild started; log: " + log}, 202)
            if path == "/api/config/restore":
                return self.json(config_restore(json.loads(self.body()).get("key")))
            if path == "/api/config":
                config_save(json.loads(self.body()))
                return self.json({"message": "Saved. Runtime/network changes may need a runtime restart."})
            if path == "/api/clients/action":
                name, action = json.loads(self.body())
                if action not in ("Trust", "RemoveEntry"):
                    raise ValueError("unsupported client action")
                alvr("/api/session/client-connections", "POST", [name, action])
                return self.json({"message": f"{action} sent for {name}"})
            if path == "/api/clients/clear":
                clients = alvr_clients().get("clients", {})
                for name in list(clients):
                    alvr("/api/session/client-connections", "POST", [name, "RemoveEntry"])
                return self.json({"message": f"Removed {len(clients)} client entr{'y' if len(clients) == 1 else 'ies'}"})
            if path == "/api/approved/import":
                name = self.headers.get("X-Filename", "devices.json").lower()
                suffix = ".xlsx" if name.endswith(".xlsx") else ".csv" if name.endswith(".csv") else ".json"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as t:
                    t.write(self.body())
                try:
                    res = approved_tool("import", t.name)
                finally:
                    os.unlink(t.name)
                if res.returncode != 0:
                    raise RuntimeError((res.stderr or res.stdout).strip())
                return self.json({"message": res.stdout.strip()})
            if path == "/api/approved/remove":
                mac = json.loads(self.body()).get("mac_address", "")
                res = approved_tool("remove", mac)
                if res.returncode != 0:
                    raise RuntimeError((res.stderr or res.stdout).strip())
                return self.json({"message": res.stdout.strip()})
            return self.json({"error": "not found"}, 404)
        except gpu_worker.GpuWorkerError as e:
            return self.error_json(e, e.status)
        except (ValueError, KeyError) as e:
            return self.error_json(e, 400)
        except Exception as e:
            return self.error_json(e)


class IPv6HTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def create_http_server(bind, port, lan_access):
    if lan_access:
        if socket.has_dualstack_ipv6():
            return IPv6HTTPServer(("::", port), Handler)
        return ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server_type = IPv6HTTPServer if ":" in bind else ThreadingHTTPServer
    return server_type((bind, port), Handler)


# ---------------------------------------------------------------- HTTPS for Wi-Fi browsers
TLS_DIR = CONFIG_PATH.parent / "tls"
HTTPS_PORT = [None]  # set once the HTTPS listener runs


def lan_addresses() -> list[str]:
    """Global-scope addresses of this PC (what headsets on the LAN reach it by)."""
    res = subprocess.run(["ip", "-o", "addr", "show", "scope", "global"], capture_output=True, text=True)
    found = []
    for line in res.stdout.splitlines():
        parts = line.split()
        # Rotating IPv6 privacy addresses would reissue the certificate (and its browser warning).
        if len(parts) > 3 and parts[2] in ("inet", "inet6") and "temporary" not in parts and "deprecated" not in parts:
            addr = parts[3].split("/")[0]
            if addr not in found:
                found.append(addr)
    return found


def ensure_tls_cert(addresses: list[str]) -> tuple[Path, Path]:
    """Self-signed certificate for this PC's LAN addresses; regenerated when an address is new.
    Browsers warn once (Advanced, Proceed); the page then counts as secure."""
    cert, key, names = TLS_DIR / "cert.pem", TLS_DIR / "key.pem", TLS_DIR / "names.json"
    wanted = sorted(set(addresses) | {"127.0.0.1", "::1"})
    try:
        covered = set(json.loads(names.read_text()))
    except (OSError, ValueError):
        covered = set()
    if cert.is_file() and key.is_file() and set(wanted) <= covered:
        return cert, key
    TLS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(TLS_DIR, 0o700)
    host = socket.gethostname()
    san = ",".join([f"IP:{a}" for a in wanted] + ["DNS:localhost"]
                   + ([f"DNS:{host}", f"DNS:{host}.local"] if re.fullmatch(r"[A-Za-z0-9-]{1,63}", host) else []))
    tmp_key = TLS_DIR / "key.pem.new"
    tmp_key.unlink(missing_ok=True)
    res = subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                          "-nodes", "-days", "825", "-subj", "/CN=Intel XR Control Panel",
                          "-addext", f"subjectAltName={san}", "-addext", "extendedKeyUsage=serverAuth",
                          "-keyout", str(tmp_key), "-out", str(TLS_DIR / "cert.pem.new")],
                         capture_output=True, text=True, timeout=60)
    if res.returncode:
        raise RuntimeError(res.stderr.strip() or "openssl failed")
    os.chmod(tmp_key, 0o600)
    os.replace(tmp_key, key)
    os.replace(TLS_DIR / "cert.pem.new", cert)
    atomic_json(names, wanted)
    return cert, key


class TLSMixin:
    """TLS handshake in the request's own thread, so a slow or plain-HTTP client cannot stall accept()."""
    tls_context: ssl.SSLContext

    def finish_request(self, request, client_address):
        request.settimeout(15)
        try:
            request = self.tls_context.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return
        request.settimeout(None)
        super().finish_request(request, client_address)


class HTTPSServer(TLSMixin, ThreadingHTTPServer):
    pass


class IPv6HTTPSServer(TLSMixin, IPv6HTTPServer):
    pass


def create_https_server(port, cert, key):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    server_type = IPv6HTTPSServer if socket.has_dualstack_ipv6() else HTTPSServer
    server = server_type(("::", port) if server_type is IPv6HTTPSServer else ("0.0.0.0", port), Handler)
    server.tls_context = ctx
    return server


def start_https():
    port = int(CFG.get("https_port") or 0)
    if not CFG.get("lan_access") or not port:
        return
    try:
        server = create_https_server(port, *ensure_tls_cert(lan_addresses()))
    except (OSError, RuntimeError, ssl.SSLError) as e:
        print(f"HTTPS listener not started: {e}", flush=True)
        return
    HTTPS_PORT[0] = port
    print(f"XR Control Panel also on https://<this PC>:{port}/ (headset microphone over Wi-Fi)", flush=True)
    threading.Thread(target=server.serve_forever, daemon=True, name="https").start()


def main():
    server = create_http_server(CFG["bind"], int(CFG["port"]), bool(CFG.get("lan_access")))
    bind = server.server_address[0]
    print(f"XR Control Panel on http://{url_host(bind)}:{CFG['port']}/ "
          f"(runtime: {runtime_root() or 'not configured'}, adb: {ADB or 'missing'})", flush=True)
    threading.Thread(target=auto_pair_usb_worker, daemon=True, name="usb-pairing").start()
    threading.Thread(target=gpu_screen_worker, daemon=True, name="gpu-screen-review").start()
    start_https()
    server.serve_forever()


if __name__ == "__main__":
    main()
