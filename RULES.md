# Intel XR Prototype — Rules / Lessons Learned

## Evidence
- Never diagnose from a black screen alone. Instrument boundaries.
- Preserve positive findings; do not repeatedly reopen proven layers without a regression reason.
- Prefer raw stderr probes when normal logging may hide execution.
- Compare event order, not Android/Linux wall-clock timestamps.

## Builds
- A Monado build does not prove Rust server_core was rebuilt.
- After changing `alvr/server_core`: run `cargo build -p alvr_server_core` first.
- Verify .so mtime and required marker strings.
- Then run `cargo xtask build-server-lib`; verify target/deployed SHA-256 hashes match.
- Never restart after a failed build.
- Reconfigure CMake after CMakeLists changes.
- Run `python3 -m py_compile` before modified Python helpers.
- Never emit literal `\n` when physical source lines are intended; this repeatedly caused Python/C++ failures.
- Keep builds clean. Do not rewrite ABI layout to silence warnings. `alvr_binding.h` intentionally uses anonymous structs; warning suppression belongs narrowly in build configuration.

## Git
- Verify branch/commit when an artifact looks stale.
- Do not merge diagnostic instrumentation wholesale to main.
- Separate production fixes from temporary `INTEL-XR-*` probes.
- No destructive Git during unattended work.

## Runtime
- Kill stale checkerboard/run-video-test processes before a controlled test.
- Run one checkerboard.
- Keep headset awake/worn for focus/streaming tests.
- Do not clear evidence before capture.
- `STREAMING_STARTED` or UDP traffic does not prove video delivery.
- Require explicit transport/decode/display markers.

## Proven technical lessons
- Zero quaternions broke OpenXR. Seed valid identity head and per-eye poses.
- Reject invalid/non-finite/zero-length tracking samples; real samples replace identity.
- Intel output observed is valid H.264 Annex-B, prefix size 4.
- `ParseFrameNals()` reaches `alvr_send_video_nal()`; parser is not the current blocker.
- Runtime symbol resolution was verified: one loaded server-core .so provides `alvr_send_video_nal`.
- Initial IDR can arrive before `video_channel_sender` exists.
- Connection later reaches `SEND_START_STREAM -> GOT_STREAM_READY -> STREAM_SOCKET_CONNECT_OK -> VIDEO_CHANNEL_INSTALL -> MARK_STREAMING`.
- A fresh-IDR request after install is now emitted successfully; consumption of `ServerCoreEvent::RequestIDR` is the current boundary.
- Connection shutdown probes identify client streaming vs lifecycle causes if teardown recurs.

## Diagnostic hygiene
Rate-limit noisy probes. Once a boundary is proven, reduce/remove its temporary logging. Record evidence in `TASKS.md`.
