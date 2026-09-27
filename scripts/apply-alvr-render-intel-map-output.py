#!/usr/bin/env python3
"""Encode the renderer's real output on Intel instead of an unwritten VA surface.

On Intel, EncodePipelineVAAPI took the "Importing VA surface" branch: it
allocated a fresh VA surface and encoded it, but the step that would make the
renderer draw into it (`r->ImportOutput(drm)`, "TODO: Fix output import") is
commented out. The encoder therefore encoded an all-zero NV12 surface, which
decodes as solid green (verified by decoding logs/encoder-dump.h264).

The renderer already exports its output as a linear DMA-BUF on Intel (the Arc
compatibility change), which is what map_frame() consumes on other vendors.

This patch:
  * advertises DRM_FORMAT_MOD_LINEAR (not MOD_INVALID) for that eLinear image;
  * uses map_frame() on Intel too; the old surface-import path remains
    available through the existing ALVR_VAAPI_IMPORT_SURFACE env variable;
  * checks av_hwframe_map() and falls back to the old path with a log line
    instead of continuing with an unmapped frame.

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


root = project_root()
src = root / "src" / "alvr_render" / "src"
renderer_cpp = src / "Renderer.cpp"
vaapi_cpp = src / "EncodePipelineVAAPI.cpp"
for required in (renderer_cpp, vaapi_cpp):
    if not required.is_file():
        raise SystemExit(f"ERROR: required source file missing: {required}")

patch_once(
    renderer_cpp,
    """            out.drm.modifier = DRM_FORMAT_MOD_INVALID;
            out.drm.planes = 1;""",
    """            // The fallback image uses vk::ImageTiling::eLinear.
            out.drm.modifier = DRM_FORMAT_MOD_LINEAR;
            out.drm.planes = 1;""",
    "The fallback image uses vk::ImageTiling::eLinear.",
)

patch_once(
    vaapi_cpp,
    """  av_hwframe_map(mapped_frame, vk_frame, AV_HWFRAME_MAP_READ);
  av_frame_free(&vk_frame);""",
    """  int map_err = av_hwframe_map(mapped_frame, vk_frame, AV_HWFRAME_MAP_READ);
  av_frame_free(&vk_frame);
  if (map_err < 0) {
    // vk_frame owned drm_frames_ref; av_frame_free() above released it.
    av_frame_free(&mapped_frame);
    throw alvr::AvException("Failed to map renderer output into VAAPI:", map_err);
  }""",
    "Failed to map renderer output into VAAPI:",
)

patch_once(
    vaapi_cpp,
    """  if (vendor == Vendor::Intel || getenv("ALVR_VAAPI_IMPORT_SURFACE")) {
    // TODO: Fix output import
    Info("Importing VA surface");
    DrmImage drm;
    mapped_frame = import_frame(hw_frames_ref, drm);
    // r->ImportOutput(drm);
  } else {
    mapped_frame = map_frame(hw_frames_ref, drm_ctx, input_frame);
        // std::cout << "mapped frame" << std::endl;
  }""",
    """  bool const isIntel = vendor == Vendor::Intel;
  if (getenv("ALVR_VAAPI_IMPORT_SURFACE")) {
    // TODO: Fix output import (the renderer never draws into this surface)
    Info("Importing VA surface");
    DrmImage drm;
    mapped_frame = import_frame(hw_frames_ref, drm);
    // r->ImportOutput(drm);
    std::cerr << "[INTEL-XR-SERVER] VAAPI_INPUT mode=import_surface intel=" << isIntel << std::endl;
  } else {
    // Map the renderer's exported output (linear DMA-BUF on Intel) so the
    // encoder reads what was actually rendered.
    try {
      mapped_frame = map_frame(hw_frames_ref, drm_ctx, input_frame);
      std::cerr << "[INTEL-XR-SERVER] VAAPI_INPUT mode=map_renderer_output intel=" << isIntel << std::endl;
    } catch (std::exception const &e) {
      std::cerr << "[INTEL-XR-SERVER] VAAPI_INPUT_MAP_FAILED err=" << e.what()
                << " fallback=import_surface" << std::endl;
      DrmImage drm;
      mapped_frame = import_frame(hw_frames_ref, drm);
    }
  }""",
    "VAAPI_INPUT mode=map_renderer_output",
)

print()
print("alvr_render Intel renderer-output mapping is applied.")
print("Expected marker: VAAPI_INPUT mode=map_renderer_output intel=1")
print("No Git refs were changed.")
