#!/usr/bin/env python3
"""Use ALVR's measured display-time prediction for HMD tracking, not raw samples."""
import os
from pathlib import Path
root = Path(os.environ.get("INTEL_XR_ROOT", "/ai/intel-xr-prototype"))
p = root / "src/alvr_render/src/Encoder.cpp"
t = p.read_text()
t = t.replace("    auto ids = alvr_get_ids();\n\n", "", 1)
old = "alvr_get_device_motion(ids.head, ts, &motion)"
new = "alvr_get_head_motion_for_display(ts, &motion)"
if new in t:
    p.write_text(t)
    print("[already patched] head display prediction")
elif old in t:
    p.write_text(t.replace(old, new, 1))
    print("[patched] head display prediction")
else:
    raise SystemExit("ERROR: expected head tracking call not found")
