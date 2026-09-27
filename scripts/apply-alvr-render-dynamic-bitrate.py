#!/usr/bin/env python3
"""Apply ALVR's dynamic encoder params (adaptive bitrate) in alvr_render.

ALVR's BitrateManager computes encoder bitrate/framerate (ConstantMbps changes,
or Adaptive mode driven by measured network throughput/latency), exposed as
alvr_get_dynamic_encoder_params(). Upstream ALVR's Linux encoder polls it every
frame and calls EncodePipeline::SetParams(); alvr_render never did, so the
bitrate was fixed at encoder open.

This patch polls alvr_get_dynamic_encoder_params() in Encoder::present() before
each PushFrame() and forwards updates to SetParams(), with a log line per
update (ALVR only reports on change / once per second in Adaptive mode).

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
encoder_cpp = root / "src" / "alvr_render" / "src" / "Encoder.cpp"
if not encoder_cpp.is_file():
    raise SystemExit(f"ERROR: required source file missing: {encoder_cpp}")

patch_once(
    encoder_cpp,
    """    bool const insertIdr = idrScheduler.CheckIDRInsertion();
    encoder->PushFrame(counter++, insertIdr);""",
    """    // Apply ALVR's dynamic encoder params (ConstantMbps changes / Adaptive mode),
    // as upstream ALVR's encoder does before every frame.
    AlvrDynamicEncoderParams dynamicParams {};
    if (alvr_get_dynamic_encoder_params(&dynamicParams) && dynamicParams.bitrate_bps > 0.f
        && dynamicParams.framerate > 0.f) {
        FfiDynamicEncoderParams params {};
        params.updated = 1;
        params.bitrate_bps = (unsigned long long)dynamicParams.bitrate_bps;
        params.framerate = dynamicParams.framerate;
        encoder->SetParams(params);
        std::cerr << "[INTEL-XR-SERVER] ENCODER_DYNAMIC_PARAMS bps=" << params.bitrate_bps
                  << " fps=" << params.framerate << std::endl;
    }

    bool const insertIdr = idrScheduler.CheckIDRInsertion();
    encoder->PushFrame(counter++, insertIdr);""",
    "ENCODER_DYNAMIC_PARAMS",
)

# The workstation's FFmpeg (6.1, unpatched) applies VAAPI rate control only in
# avcodec_open2(): changing encoder_ctx->bit_rate at runtime has no effect
# (measured: frames stayed 52,116 B after ENCODER_DYNAMIC_PARAMS 10 Mbps). Re-open
# the encoder with the new rate instead, with hysteresis; a new encoder starts
# with an IDR.
vaapi_h = root / "src" / "alvr_render" / "src" / "EncodePipelineVAAPI.h"
vaapi_cpp = root / "src" / "alvr_render" / "src" / "EncodePipelineVAAPI.cpp"
for required in (vaapi_h, vaapi_cpp):
    if not required.is_file():
        raise SystemExit(f"ERROR: required source file missing: {required}")

patch_once(
    vaapi_h,
    """  void SetParams(FfiDynamicEncoderParams params) override;

private:
""",
    """  void SetParams(FfiDynamicEncoderParams params) override;

private:
  // Runtime bitrate changes: FFmpeg VAAPI reads rate control only when the
  // encoder is opened, so a changed target re-opens the encoder.
  void MaybeReopenEncoder();
  bool has_pending_params = false;
  FfiDynamicEncoderParams pending_params = {};
  std::chrono::steady_clock::time_point last_reopen = {};
""",
    "void MaybeReopenEncoder();",
)

patch_once(
    vaapi_h,
    """#include "ffmpeg_helper.h"
""",
    """#include "ffmpeg_helper.h"

#include <chrono>
""",
    "#include <chrono>",
)

patch_once(
    vaapi_cpp,
    """void alvr::EncodePipelineVAAPI::SetParams(FfiDynamicEncoderParams params)
{
  if (!params.updated) {
    return;
  }
  encoder_ctx->bit_rate = params.bitrate_bps;
  encoder_ctx->framerate = AVRational{int(params.framerate * 1000), 1000};
  encoder_ctx->rc_buffer_size = encoder_ctx->bit_rate / params.framerate;
  encoder_ctx->rc_max_rate = encoder_ctx->bit_rate;
  encoder_ctx->rc_initial_buffer_occupancy = encoder_ctx->rc_buffer_size;
""",
    """static void apply_rate_params(AVCodecContext *ctx, FfiDynamicEncoderParams const &params)
{
  ctx->bit_rate = params.bitrate_bps;
  ctx->framerate = AVRational{int(params.framerate * 1000), 1000};
  ctx->rc_buffer_size = ctx->bit_rate / params.framerate;
  ctx->rc_max_rate = ctx->bit_rate;
  ctx->rc_initial_buffer_occupancy = ctx->rc_buffer_size;
}

void alvr::EncodePipelineVAAPI::MaybeReopenEncoder()
{
  if (!has_pending_params) {
    return;
  }
  auto const &params = pending_params;
  double const old_fps = av_q2d(encoder_ctx->framerate);
  double const old_budget = old_fps > 0 ? encoder_ctx->bit_rate / old_fps : 0;
  double const new_budget = params.bitrate_bps / params.framerate;
  if (old_budget > 0 && std::abs(new_budget - old_budget) / old_budget < 0.10) {
    has_pending_params = false; // not worth an IDR
    return;
  }
  auto const now = std::chrono::steady_clock::now();
  auto const min_interval = new_budget < old_budget ? std::chrono::seconds(1) : std::chrono::seconds(5);
  if (now - last_reopen < min_interval) {
    return; // keep pending, retry on a later frame
  }

  const AVCodec *codec = encoder_ctx->codec;
  AVCodecContext *ctx = avcodec_alloc_context3(codec);
  if (!ctx) {
    return;
  }
  ctx->profile = encoder_ctx->profile;
  ctx->width = encoder_ctx->width;
  ctx->height = encoder_ctx->height;
  ctx->time_base = encoder_ctx->time_base;
  ctx->sample_aspect_ratio = encoder_ctx->sample_aspect_ratio;
  ctx->pix_fmt = encoder_ctx->pix_fmt;
  ctx->max_b_frames = encoder_ctx->max_b_frames;
  ctx->gop_size = encoder_ctx->gop_size;
  ctx->color_range = encoder_ctx->color_range;
  ctx->compression_level = encoder_ctx->compression_level;
  ctx->flags = encoder_ctx->flags;
  av_opt_copy(ctx->priv_data, encoder_ctx->priv_data); // rc_mode, coder, async_depth, ...
  ctx->hw_frames_ctx = av_buffer_ref(encoder_ctx->hw_frames_ctx);
  apply_rate_params(ctx, params);

  auto const start = std::chrono::steady_clock::now();
  int err = avcodec_open2(ctx, codec, NULL);
  auto const took_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - start).count();
  last_reopen = now;
  if (err < 0) {
    std::cerr << "[INTEL-XR-SERVER] ENCODER_REOPEN_FAILED err=" << err
              << " keeping bps=" << encoder_ctx->bit_rate << std::endl;
    avcodec_free_context(&ctx);
    return;
  }
  has_pending_params = false;
  std::cerr << "[INTEL-XR-SERVER] ENCODER_REOPEN bps=" << params.bitrate_bps << " fps=" << params.framerate
            << " frame_budget_bytes=" << (unsigned long long)(new_budget / 8) << " took_ms=" << took_ms << std::endl;
  avcodec_free_context(&encoder_ctx);
  encoder_ctx = ctx;
}

void alvr::EncodePipelineVAAPI::SetParams(FfiDynamicEncoderParams params)
{
  if (!params.updated || params.bitrate_bps == 0 || params.framerate <= 0.f) {
    return;
  }
  if (avcodec_is_open(encoder_ctx)) {
    // Runtime change: applied by re-opening the encoder in PushFrame().
    pending_params = params;
    has_pending_params = true;
    return;
  }
  apply_rate_params(encoder_ctx, params);
""",
    "void alvr::EncodePipelineVAAPI::MaybeReopenEncoder()",
)

patch_once(
    vaapi_cpp,
    """void alvr::EncodePipelineVAAPI::PushFrame(uint64_t targetTimestampNs, bool idr)
{
  // r->Sync();""",
    """void alvr::EncodePipelineVAAPI::PushFrame(uint64_t targetTimestampNs, bool idr)
{
  MaybeReopenEncoder();
  // r->Sync();""",
    "  MaybeReopenEncoder();\n  // r->Sync();",
)

patch_once(
    vaapi_cpp,
    """#include <chrono>
#include <iostream>
""",
    """#include <chrono>
#include <cmath>
#include <iostream>
""",
    "#include <cmath>",
)

print()
print("alvr_render dynamic encoder params are applied.")
print("Expected markers: ENCODER_DYNAMIC_PARAMS bps=... fps=...; ENCODER_REOPEN bps=... took_ms=...")
print("No Git refs were changed.")
