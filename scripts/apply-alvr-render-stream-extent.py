#!/usr/bin/env python3
"""Use a two-eye stream canvas in alvr_render.

alvr_initialize() reports stream_width/stream_height per eye (ALVR
eye_resolution_width/height). ensureInit() used that per-eye width as the width of
the whole side-by-side canvas, and both the Monado ALVR driver (views = width / 2)
and alvr_render (foveation eye width = width / 2) split it in half, so each eye got
half its horizontal resolution (e.g. 1072 px instead of 2144): a blurry, pixelated
image. Double the width here.

Keep 2 x per-eye width within the encoder limit (H.264 on Intel VAAPI: 4096 px),
e.g. ALVR video.transcoding_view_resolution width 1832 (Quest 2 native).

Non-destructive and idempotent, like the other apply-*.py companion helpers.
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


def patch_once(path: Path, old: str, new: str, marker: str) -> bool:
    text = path.read_text()
    if marker in text:
        print(f"[already patched] {path}: {marker}")
        return False
    if old not in text:
        raise SystemExit(f"ERROR: insertion point missing in {path}: {marker}")
    path.write_text(text.replace(old, new, 1))
    print(f"[patched] {path}: {marker}")
    return True


encoder_cpp = project_root() / "src" / "alvr_render" / "src" / "Encoder.cpp"
if not encoder_cpp.is_file():
    raise SystemExit(f"ERROR: required source file missing: {encoder_cpp}")

patch_once(
    encoder_cpp,
    """            extent.width = targetCfg.stream_width;
            extent.height = targetCfg.stream_height;""",
    """            // stream_width/height are per eye; the canvas holds both eyes side by side.
            extent.width = targetCfg.stream_width * 2;
            extent.height = targetCfg.stream_height;
            std::cerr << "[INTEL-XR-SERVER] STREAM_EXTENT per_eye=" << targetCfg.stream_width << "x"
                      << targetCfg.stream_height << " canvas=" << extent.width << "x" << extent.height << std::endl;""",
    "STREAM_EXTENT per_eye=",
)

print()
print("alvr_render two-eye stream canvas is applied.")
print("Expected marker: STREAM_EXTENT per_eye=WxH canvas=(2W)xH")
print("No Git refs were changed.")
