#!/usr/bin/env python3
"""Run only after a successful runtime build and server-core deployment."""
import hashlib, json, os, subprocess, time
from pathlib import Path
root = Path(os.environ.get("INTEL_XR_ROOT", "/ai/intel-xr-prototype"))
repo = root / "src/Monado-ALVR"
def git(*args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
core = root / "src/alvr-monado"
assert digest(core / "target/debug/libalvr_server_core.so") == digest(core / "build/alvr_server_core/libalvr_server_core.so")
info = {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain")),
        "built_at": time.time(), "binary_sha256": digest(root / "build/monado-alvr/src/xrt/targets/service/monado-service"),
        "server_core_sha256": digest(core / "build/alvr_server_core/libalvr_server_core.so"),
        "components": {name: subprocess.check_output(["git", "-C", str(root / "src" / name), "rev-parse", "HEAD"], text=True).strip()
                       for name in ("alvr-monado", "alvr_render", "loft")}}
(root / "build/monado-alvr/build-info.json").write_text(json.dumps(info, indent=2) + "\n")
print(json.dumps(info, indent=2))
