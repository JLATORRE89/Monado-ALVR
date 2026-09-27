#!/usr/bin/env python3
"""Base Monado/ALVR compatibility for the pinned alvr_render checkout (step 1).

The two changes prepare-companions.sh applies after its `reset --hard`, as a
standalone, non-destructive, idempotent helper:
  * ABI rename: ALVR_EVENT_VIEWS_PARAMS -> ALVR_EVENT_LOCAL_VIEW_PARAMS and
    event.views_params -> event.local_view_params (current ALVR C API);
  * Intel Arc DMA-BUF compatibility: skip the DRM-format-modifier image path on
    Intel (vkCreateImage crash on Arc/Mesa) and use the linear fallback.

Never fetches, resets or checks out Git refs.
"""
from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    if os.getenv("INTEL_XR_ROOT"):
        return Path(os.environ["INTEL_XR_ROOT"]).resolve()
    here = Path(__file__).resolve()
    for candidate in (Path.cwd(), here.parent):
        for parent in (candidate, *candidate.parents):
            if parent.name == "intel-xr-prototype":
                return parent
    inferred = here.parents[3]
    if (inferred / "src" / "Monado-ALVR").is_dir():
        return inferred
    raise SystemExit("ERROR: cannot locate intel-xr-prototype; set INTEL_XR_ROOT")


src = project_root() / "src" / "alvr_render" / "src"

for name in ("Encoder.cpp", "EventManager.hpp"):
    path = src / name
    text = path.read_text()
    new = text.replace("ALVR_EVENT_VIEWS_PARAMS", "ALVR_EVENT_LOCAL_VIEW_PARAMS").replace(
        "event.views_params", "event.local_view_params")
    if new != text:
        path.write_text(new)
        print(f"[patched] {path}: LOCAL_VIEW_PARAMS ABI")
    else:
        print(f"[already patched] {path}: LOCAL_VIEW_PARAMS ABI")

renderer = src / "Renderer.cpp"
text = renderer.read_text()
old = "bool haveDrmModifiers = true;"
new = """// Intel ANV can export DMA-BUF, but the historical DRM-modifier image
    // creation path crashes during vkCreateImage on the tested Arc A750/Mesa
    // stack. Keep DMA-BUF for FFmpeg/VAAPI, but use the linear fallback.
    const bool isIntel = ctx.physDev.getProperties().vendorID == 0x8086;
    bool haveDrmModifiers = !isIntel;"""
if new in text:
    print(f"[already patched] {renderer}: Intel linear DMA-BUF")
elif old in text:
    renderer.write_text(text.replace(old, new, 1))
    print(f"[patched] {renderer}: Intel linear DMA-BUF")
else:
    raise SystemExit(f"ERROR: expected DRM modifier switch not found in {renderer}")
