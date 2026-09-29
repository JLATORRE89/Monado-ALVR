#!/usr/bin/env python3
"""Reproducible, opt-in encoder-boundary diagnostics; preserves rendering settings."""
import os
from pathlib import Path
import subprocess
root = Path(os.environ.get("INTEL_XR_ROOT", "/ai/intel-xr-prototype")) / "src/alvr_render"
patch = Path(__file__).with_name("alvr-render-boundary-capture.patch")
args = ["git", "-C", str(root), "apply"]
if subprocess.run(args + ["--reverse", "--check", str(patch)], capture_output=True).returncode == 0:
    print("[already patched] boundary capture")
else:
    subprocess.run(args + ["--check", str(patch)], check=True)
    subprocess.run(args + [str(patch)], check=True)
    print("[patched] boundary capture")
