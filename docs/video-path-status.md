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

Next investigation is server-side:

1. frame received from Monado
2. frame submitted to encoder
3. encoded frame / IDR produced
4. decoder configuration sent
5. video packet handed to ALVR stream transport

Only after those server checkpoints are known should investigation move back to the Quest receiver or decoder.

## Testing rules

- Kill stale `intel_xr_checkerboard` / `run-video-test` processes before controlled tests.
- Keep the headset worn for tests where focus/DOFF matters.
- Use current-process lifecycle evidence for DOFF classification; do not classify a run from unrelated historical Guardian/system log entries.
- Do not log every render iteration. Log waiting-for-first-frame once and first-decoded-frame once.
- Preserve explicit `[INTEL-XR-VIDEO]` checkpoint names so the one-shot diagnostic can classify the boundary automatically.
