#!/usr/bin/env python3
"""Seed alvr_render's VAAPI encoder with ALVR's configured bitrate.

EncodePipelineVAAPI opens the encoder with a hardcoded 500 Mbps CBR target
("TODO: Make dynamic") and nothing applies ALVR's dynamic encoder params
afterwards. The workstation links Ubuntu's unpatched FFmpeg, whose VAAPI
encoder only applies rate control at avcodec_open2(), so the initial value is
the one that matters.

Query alvr_get_dynamic_encoder_params() once before avcodec_open2(). Its first
call always reports the session bitrate (e.g. ConstantMbps). Its framerate is
a pre-connection placeholder (60), so keep settings.m_refreshRate: Intel CBR
pads every frame to exactly bitrate/framerate, so the framerate must match
the real stream rate. Keep the 500 Mbps fallback when the server core has no
context yet, and log the chosen values once.

settings.m_refreshRate was always 0 (the encoder was opened with framerate 0),
because Settings::Load() expects an openvr_config object that
alvr_get_settings_json() does not return. Fill it from video.preferred_fps.

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
vaapi = root / "src" / "alvr_render" / "src" / "EncodePipelineVAAPI.cpp"
if not vaapi.is_file():
    raise SystemExit(f"ERROR: required source file missing: {vaapi}")

patch_once(
    vaapi,
    """#include <chrono>
""",
    """#include <chrono>
#include <iostream>

extern "C" {
#include "alvr_binding.h"
}
""",
    '#include "alvr_binding.h"',
)

patch_once(
    vaapi,
    """  // TODO: Make dynamic
  auto params = FfiDynamicEncoderParams {};
  params.updated = true;
  params.bitrate_bps = 500'000'000;
  params.framerate = settings.m_refreshRate;
  SetParams(params);
""",
    """  // TODO: Make dynamic
  auto params = FfiDynamicEncoderParams {};
  params.updated = true;
  params.bitrate_bps = 500'000'000;
  params.framerate = settings.m_refreshRate;

  // Unpatched FFmpeg VAAPI applies rate control only at avcodec_open2(), so
  // seed it from ALVR's configured bitrate instead of the placeholder above.
  // Keep the configured refresh rate: before a client connects ALVR reports a
  // placeholder framerate, and Intel CBR pads every frame to bitrate/framerate.
  // Never open rate control with framerate 0 (bitrate / 0 buffer size).
  AlvrDynamicEncoderParams alvrParams {};
  bool const alvrParamsValid = alvr_get_dynamic_encoder_params(&alvrParams);
  if (alvrParamsValid && alvrParams.bitrate_bps > 0.f) {
    params.bitrate_bps = (unsigned long long)alvrParams.bitrate_bps;
  }
  if (params.framerate <= 0.f && alvrParamsValid && alvrParams.framerate > 0.f) {
    params.framerate = alvrParams.framerate;
  }
  std::cerr << "[INTEL-XR-SERVER] ENCODER_INIT_BITRATE bps=" << params.bitrate_bps
            << " fps=" << params.framerate
            << " source=" << (alvrParamsValid ? "alvr" : "fallback") << std::endl;
  SetParams(params);
""",
    "ENCODER_INIT_BITRATE",
)

# Settings::Load() reads openvr_config, which alvr_get_settings_json() does not
# provide, so it throws on the first key and m_refreshRate stays 0. Take the
# stream refresh rate from video.preferred_fps before that parse. Only
# m_refreshRate is filled; the other openvr_config-derived settings are left
# at their current defaults on purpose.
settings_cpp = root / "src" / "alvr_render" / "src" / "alvr_server" / "Settings.cpp"
if not settings_cpp.is_file():
    raise SystemExit(f"ERROR: required source file missing: {settings_cpp}")

patch_once(
    settings_cpp,
    """        auto config = v.get("openvr_config");
""",
    """        // alvr_get_settings_json() returns session settings without
        // openvr_config; use video.preferred_fps so encoders get a real rate.
        if (v.get("video").is<picojson::object>()) {
            auto preferredFps = v.get("video").get("preferred_fps");
            if (preferredFps.is<double>()) {
                m_refreshRate = (int)preferredFps.get<double>();
            }
        }

        auto config = v.get("openvr_config");
""",
    "video.preferred_fps so encoders get a real rate",
)

print()
print("alvr_render encoder bitrate seeding is applied.")
print("Expected marker:")
print("  ENCODER_INIT_BITRATE bps=<session bitrate> fps=<preferred_fps> source=alvr")
print("No Git refs were changed.")
