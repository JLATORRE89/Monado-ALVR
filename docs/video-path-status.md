# Intel XR video-path status

Updated: 2026-09-26

## Purpose

This file records experimentally proven checkpoints for the Monado → ALVR → Quest video path. It is intended to prevent re-investigating already verified portions of the stack.

## Proven working

- Quest client launches and reaches OpenXR IDLE → READY → SYNCHRONIZED → VISIBLE → FOCUSED.
- Quest local lobby/HUD rendering works, proving the application, local renderer, swapchains, and Quest compositor can display client-generated pixels.
- PC OpenXR checkerboard creates an instance against the Monado `Alvr HMD`.
- ALVR discovery, trust, handshake, stream configuration, StartStream, and stream-socket connection complete.
- Quest video/audio/haptics subscriptions, tracking/statistics streams, and worker-thread creation complete.
- Control, tracking, and statistics sender installation completes.
- Diagnostic client log mirroring is bypassed because logging around `LOG_CHANNEL_SENDER` exposed a blocking/re-entrant logging path during diagnostics. Android logcat remains available.
- Quest now reaches `STREAMING_EVENT_QUEUED`, `CONNECTION_STATE_STREAMING`, and `STREAMING_STARTED`.
- Quest stream renderer runs and waits for its first decoded frame.
- Previous packet captures demonstrated PC → Quest UDP/9944 traffic during failing runs.

## Not yet observed

The current instrumented Quest runs have not observed:

- `CONTROL_DECODER_CONFIG`
- `VIDEO_PACKET_RECEIVED`
- `IDR_RECEIVED`
- decoder callback submission
- decoder creation
- MediaCodec configuration/input/output
- ImageReader output
- first decoded stream frame

Therefore MediaCodec is not the current investigation target.

## Current boundary

The client successfully enters ALVR streaming mode, but the Quest-side subscribed video receiver and decoder-config control path have not produced an event.

Server-side checkpoints are now prepared:

1. `FRAME_RECEIVED_FROM_MONADO` — Monado ALVR compositor target.
2. `ENCODER_INPUT` — alvr_render receives the compositor image for encoding.
3. `ENCODED_FRAME` — alvr_render obtains an encoded frame and records IDR state.
4. `DECODER_CONFIG_SENT` / `DECODER_CONFIG_UNAVAILABLE_ON_IDR_REQUEST` — ALVR server response to the Quest IDR request.
5. `VIDEO_PACKET_SENT` — ALVR server hands the first encoded video packet to the stream transport.

The Monado target marker is in this repository. The ALVR transport/config markers are on
`JLATORRE89/ALVR:intel-xr-client-diag`. The alvr_render markers are applied locally with
`scripts/apply-server-video-instrumentation.py`.

The next controlled run should compare these server markers with the Quest's
`STREAMING_STARTED` and `VIDEO_PACKET_RECEIVED` markers. Only after those checkpoints are
known should investigation move back to the Quest decoder.

## Testing rules

- Kill stale `intel_xr_checkerboard` / `run-video-test` processes before controlled tests.
- Keep the headset worn for tests where focus/DOFF matters.
- Use current-process lifecycle evidence for DOFF classification; do not classify a run from unrelated historical Guardian/system log entries.
- Do not log every render iteration. Log waiting-for-first-frame once and first-decoded-frame once.
- Preserve explicit `[INTEL-XR-VIDEO]` checkpoint names so the one-shot diagnostic can classify the boundary automatically.
