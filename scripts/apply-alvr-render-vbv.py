#!/usr/bin/env python3
"""Larger rate-control buffer so keyframes are not starved (step 14).

Upstream sets the VAAPI rate-control buffer to one frame of bits (bitrate / framerate), so every
IDR frame - on connect and after each loss recovery - must fit a single frame's budget and arrives
blocky, sharpening only over the following P-frames. This lets the buffer hold
INTEL_XR_VBV_FRAMES frames (default 2.5; 1 restores upstream): keyframes may use that many frames
of bits and the following frames give them back, at the cost of a short burst on the link.
Non-destructive and idempotent.
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


pipeline_cpp = project_root() / "src" / "alvr_render" / "src" / "EncodePipelineVAAPI.cpp"
if not pipeline_cpp.is_file():
    raise SystemExit(f"ERROR: required source file missing: {pipeline_cpp}")

patch_once(
    pipeline_cpp,
    """static void apply_rate_params(AVCodecContext *ctx, FfiDynamicEncoderParams const &params)
{
  ctx->bit_rate = params.bitrate_bps;
  ctx->framerate = AVRational{int(params.framerate * 1000), 1000};
  ctx->rc_buffer_size = ctx->bit_rate / params.framerate;""",
    """// INTEL-XR: rate-control buffer of INTEL_XR_VBV_FRAMES frames (default 2.5, 1 = upstream) so
// keyframes are not starved; see scripts/apply-alvr-render-vbv.py.
static double intel_xr_vbv_frames()
{
  static double const frames = [] {
    char const *v = getenv("INTEL_XR_VBV_FRAMES");
    double f = v ? atof(v) : 2.5;
    if (!(f >= 1.0 && f <= 8.0))
      f = 2.5;
    std::cerr << "[INTEL-XR-SERVER] VBV_FRAMES " << f << std::endl;
    return f;
  }();
  return frames;
}

static void apply_rate_params(AVCodecContext *ctx, FfiDynamicEncoderParams const &params)
{
  ctx->bit_rate = params.bitrate_bps;
  ctx->framerate = AVRational{int(params.framerate * 1000), 1000};
  ctx->rc_buffer_size = int(double(ctx->bit_rate) / params.framerate * intel_xr_vbv_frames());""",
    "INTEL_XR_VBV_FRAMES",
)
