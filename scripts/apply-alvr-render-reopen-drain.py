#!/usr/bin/env python3
"""Drain the old encoder before a bitrate re-open; keep rate control at the refresh rate (step 15).

Dynamic bitrate (step 7) replaces the VAAPI encoder with a newly opened one, and opened the new
encoder while the old one was still alive. Without Resizable BAR the Arc A750 exposes only 256 MB
of CPU-visible VRAM (lspci: BAR 2 current size 256MB; i915 debugfs visible_avail fell to 39 MiB);
the Intel media driver maps and zero-fills buffers there for every encoder, so two encoders at once
could exhaust it and the driver's first write raised SIGBUS (gdb: memset into an i915.gem mapping
from vaEndPicture, on the new encoder's first frame). Seen twice live on 2026-09-28 and reproduced
with the diagnostic below. Now the old encoder is drained (send NULL, receive to EOF) and freed
before the new one is opened; if opening fails, the previous settings are reopened. The proper
fix is enabling Resizable BAR in the firmware; this keeps the peak lower until then.
ALVR reports a placeholder 60 fps before a headset connects; the 60 <-> 72 flips forced re-opens at
exactly those transitions. Rate control now uses the configured refresh rate (Settings), the rate
the compositor paces at. Diagnostic: writing a bitrate in bit/s to
$XDG_RUNTIME_DIR/intel-xr-encoder-test-bps requests a re-open to it (the file is removed).
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

# 1. Drain-before-replace re-open (replaces the tail of MaybeReopenEncoder).
patch_once(
    pipeline_cpp,
    """  const AVCodec *codec = encoder_ctx->codec;
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
}""",
    """  // INTEL-XR: drain and free the old encoder before opening its replacement (INTEL_XR_REOPEN_DRAIN);
  // see scripts/apply-alvr-render-reopen-drain.py. Without Resizable BAR the Arc exposes only
  // 256 MB of CPU-visible VRAM; the Intel media driver maps (and zero-fills) buffers there for
  // each encoder, so holding two encoders at once could exhaust it and the driver's first write
  // then raised SIGBUS in vaEndPicture.
  const AVCodec *codec = encoder_ctx->codec;
  AVCodecContext *const old_ctx = encoder_ctx;
  // Configured but unopened contexts hold no VA resources; open them only after the old one is gone.
  auto prepare = [&](FfiDynamicEncoderParams const &p) -> AVCodecContext * {
    AVCodecContext *ctx = avcodec_alloc_context3(codec);
    if (!ctx) {
      return nullptr;
    }
    ctx->profile = old_ctx->profile;
    ctx->width = old_ctx->width;
    ctx->height = old_ctx->height;
    ctx->time_base = old_ctx->time_base;
    ctx->sample_aspect_ratio = old_ctx->sample_aspect_ratio;
    ctx->pix_fmt = old_ctx->pix_fmt;
    ctx->max_b_frames = old_ctx->max_b_frames;
    ctx->gop_size = old_ctx->gop_size;
    ctx->color_range = old_ctx->color_range;
    ctx->compression_level = old_ctx->compression_level;
    ctx->flags = old_ctx->flags;
    av_opt_copy(ctx->priv_data, old_ctx->priv_data); // rc_mode, coder, async_depth, ...
    ctx->hw_frames_ctx = av_buffer_ref(old_ctx->hw_frames_ctx);
    apply_rate_params(ctx, p);
    return ctx;
  };
  FfiDynamicEncoderParams previous {};
  previous.updated = true;
  previous.bitrate_bps = old_ctx->bit_rate;
  previous.framerate = old_fps > 0 ? (float)old_fps : params.framerate;
  AVCodecContext *ctx = prepare(params);
  AVCodecContext *fallback = prepare(previous);
  if (!ctx || !fallback) {
    avcodec_free_context(&ctx);
    avcodec_free_context(&fallback);
    return; // out of memory: keep the current encoder, retry later
  }

  auto const start = std::chrono::steady_clock::now();
  // Flush: no more input, then collect every picture still in flight (dropped: the new encoder
  // starts with an IDR, which the client needs after a re-open anyway). Then release it.
  int drained = 0;
  if (avcodec_send_frame(old_ctx, NULL) >= 0) {
    AVPacket *pkt = av_packet_alloc();
    while (pkt && avcodec_receive_packet(old_ctx, pkt) == 0) {
      ++drained;
      av_packet_unref(pkt);
    }
    av_packet_free(&pkt);
  }
  avcodec_free_context(&encoder_ctx);

  int err = avcodec_open2(ctx, codec, NULL);
  bool const fell_back = err < 0;
  if (fell_back) {
    std::cerr << "[INTEL-XR-SERVER] ENCODER_REOPEN_FAILED err=" << err << " reopening bps=" << previous.bitrate_bps
              << std::endl;
    avcodec_free_context(&ctx);
    std::swap(ctx, fallback);
    err = avcodec_open2(ctx, codec, NULL);
    if (err < 0) {
      avcodec_free_context(&ctx);
      throw alvr::AvException("Encoder re-open failed:", err);
    }
  }
  avcodec_free_context(&fallback);
  auto const took_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - start).count();
  last_reopen = now;
  has_pending_params = false;
  auto const &used = fell_back ? previous : params;
  std::cerr << "[INTEL-XR-SERVER] ENCODER_REOPEN bps=" << used.bitrate_bps << " fps=" << used.framerate
            << " frame_budget_bytes=" << (unsigned long long)(used.bitrate_bps / used.framerate / 8)
            << " drained=" << drained << " took_ms=" << took_ms << std::endl;
  encoder_ctx = ctx;
}""",
    "INTEL_XR_REOPEN_DRAIN",
)

# 2. Rate control at the configured refresh rate, plus the diagnostic re-open request.
patch_once(
    pipeline_cpp,
    """void alvr::EncodePipelineVAAPI::SetParams(FfiDynamicEncoderParams params)
{
  if (!params.updated || params.bitrate_bps == 0 || params.framerate <= 0.f) {
    return;
  }""",
    """void alvr::EncodePipelineVAAPI::SetParams(FfiDynamicEncoderParams params)
{
  // INTEL-XR (INTEL_XR_RATE_AT_REFRESH): ALVR reports a placeholder 60 fps until a headset
  // connects; flipping between it and the real rate forced encoder re-opens at connection
  // transitions. Budget per frame at the configured refresh rate, which the compositor paces at.
  if (Settings::Instance().m_refreshRate > 0) {
    params.framerate = (float)Settings::Instance().m_refreshRate;
  }
  // Diagnostic: $XDG_RUNTIME_DIR/intel-xr-encoder-test-bps holding a bitrate requests a re-open
  // (checked on each ALVR parameter report, about once a second).
  {
    static std::string const request = std::string(getenv("XDG_RUNTIME_DIR") ? getenv("XDG_RUNTIME_DIR") : "/tmp")
                                       + "/intel-xr-encoder-test-bps";
    {
      if (FILE *f = fopen(request.c_str(), "r")) {
        unsigned long long bps = 0;
        int const got = fscanf(f, "%llu", &bps);
        fclose(f);
        remove(request.c_str());
        if (got == 1 && bps >= 1000000 && bps <= 500000000) {
          std::cerr << "[INTEL-XR-SERVER] ENCODER_TEST_REQUEST bps=" << bps << std::endl;
          params.updated = true;
          params.bitrate_bps = bps;
        }
      }
    }
  }
  if (!params.updated || params.bitrate_bps == 0 || params.framerate <= 0.f) {
    return;
  }""",
    "INTEL_XR_RATE_AT_REFRESH",
)
