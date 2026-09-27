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
import os
import re
import shutil
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
FILE_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}\.(jpg|png|mp4)$")
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


def alvr(path: str, method: str = "GET", data=None) -> bytes:
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(CFG["alvr_api"] + path, data=body, method=method,
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
            "transport": "wifi" if ":" in bits[0] else "usb",
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
    'echo "METACAM=$(pm path com.oculus.metacam | head -1)"'
)

_cache_lock = threading.Lock()
_cache: dict = {"time": 0.0, "data": None}
recordings: dict[str, set] = {}


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
            if (h.get("ip") and (h["ip"] in ips or h["ip"] in name)) or (
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
                              "type": "video" if f.suffix == ".mp4" else "image"})
    return sorted(items, key=lambda x: x["mtime"], reverse=True)[:200]


def delete_capture(headset: str, file: str, on_headset: bool) -> dict:
    """Delete a capture from this PC and, optionally, the same file on the headset."""
    if not DIR_RE.match(headset) or not FILE_RE.match(file):
        raise ValueError("invalid capture name")
    f = CAPTURE_DIR / headset / file
    if not f.is_file():
        raise ValueError("capture not found")
    f.unlink()
    message = f"Deleted {file}"
    if on_headset:
        folder = QUEST_VIDEOS if file.endswith(".mp4") else QUEST_SHOTS
        try:
            require_headset(headset)
            res = adb("-s", headset, "shell", "rm", "-f", f"{folder}/{file}")
            message += " (also on the headset)" if res.returncode == 0 else " (headset copy not removed)"
        except RuntimeError as e:
            message += f" (headset copy kept: {e})"
    return {"message": message}


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
LOFT_COMMANDS = {"lobby", "checkerboard", "colors", "motion", "pictures", "next", "prev", "exit"}


def loft_command(cmd: str) -> dict:
    if cmd not in LOFT_COMMANDS:
        raise ValueError(f"unknown Loft command {cmd!r}")
    if not subprocess.run(["pgrep", "-x", "intel_xr_loft"], capture_output=True).stdout:
        raise RuntimeError("the Loft is not running (start it first)")
    LOFT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LOFT_DIR / "command.tmp"
    tmp.write_text(cmd + "\n")
    os.replace(tmp, LOFT_DIR / "command")
    return {"message": f"Loft: {cmd}"}


# ---------------------------------------------------------------- approved devices
def approved_tool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HERE / "approved_devices.py"), *args,
                           "--registry", os.path.expanduser(CFG["approved_registry"])],
                          capture_output=True, text=True, timeout=60)


# ---------------------------------------------------------------- HTTP
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}


class Handler(BaseHTTPRequestHandler):
    server_version = "XRControlPanel/1"

    def log_message(self, *args):
        pass

    def send(self, code: int, body: bytes, ctype: str = "application/json", cache: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=300" if cache else "no-store")
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
        url = urlparse(self.path)
        path = url.path
        try:
            if path in ("/", "/index.html"):
                return self.send(200, (STATIC / "index.html").read_bytes(), STATIC_TYPES[".html"])
            if path.startswith("/static/"):
                name = path[len("/static/"):]
                f = STATIC / name
                if "/" in name or f.suffix not in STATIC_TYPES or not f.is_file():
                    return self.json({"error": "not found"}, 404)
                return self.send(200, f.read_bytes(), STATIC_TYPES[f.suffix], cache=True)
            if path == "/api/status":
                return self.json(status())
            if path == "/api/headsets":
                return self.json(headsets_snapshot())
            if path == "/api/captures":
                headset = parse_qs(url.query).get("headset", [None])[0]
                return self.json({"captures": list_captures(headset)})
            if path.startswith("/captures/"):
                parts = [unquote(p) for p in path[len("/captures/"):].split("/")]
                if len(parts) != 2 or not DIR_RE.match(parts[0]) or not FILE_RE.match(parts[1]):
                    return self.json({"error": "not found"}, 404)
                f = CAPTURE_DIR / parts[0] / parts[1]
                if not f.is_file():
                    return self.json({"error": "not found"}, 404)
                ctype = "video/mp4" if f.suffix == ".mp4" else "image/png" if f.suffix == ".png" else "image/jpeg"
                return self.send(200, f.read_bytes(), ctype, cache=True)
            if path == "/api/config":
                return self.json({"values": config_values(), "types": {k: t.__name__ for k, t in EDITABLE.items()}})
            if path == "/api/clients":
                return self.json(alvr_clients())
            if path == "/api/gpu/status":
                return self.json(gpu_worker.status())
            if path == "/api/gpu/workflows":
                return self.json({"workflows": gpu_worker.workflows()})
            if path == "/api/gpu/jobs":
                return self.json({"jobs": gpu_worker.list_jobs()})
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
        path = urlparse(self.path).path
        try:
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
            m = re.match(r"^/api/loft/([a-z]+)$", path)
            if m:
                return self.json(loft_command(m.group(1)))
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
                rec = gpu_worker.refresh(m.group(1), CAPTURE_DIR)
                note = f"; saved {len(rec['outputs'])} output(s) to Captures" if rec.get("outputs") else ""
                return self.json({"message": f"Job {rec['status']}{note}", "job": rec})
            if path == "/api/service/restart":
                run_runtime("monado-service.sh", "restart", background=True)
                return self.json({"message": "Runtime restart requested"}, 202)
            if path == "/api/service/rebuild":
                log = str(runtime_root() / "logs/control-panel-rebuild.log")
                run_runtime("rebuild-runtime.sh", background=True, log=log)
                return self.json({"message": "Rebuild started; log: " + log}, 202)
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


def main():
    server = ThreadingHTTPServer((CFG["bind"], int(CFG["port"])), Handler)
    print(f"XR Control Panel on http://{CFG['bind']}:{CFG['port']}/ "
          f"(runtime: {runtime_root() or 'not configured'}, adb: {ADB or 'missing'})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
