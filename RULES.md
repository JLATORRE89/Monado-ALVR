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

## Lessons 2026-09-26 (overnight)
- One-shot probes hide repetition: "no fresh IDR" was false; per-frame probes showed IDRs every frame.
- Server `info!` markers go to `~/alvr_session.log`; raw `eprintln!`/stderr goes to the journal.
- UDP `send()` success only means "queued in the PC kernel". Check `ss -uanpm | grep -A1 :9944`
  (Send-Q / `t…`) on the PC and `/proc/net/udp` port `:26D8` on the Quest before blaming code.
- The PC reaches the Quest LAN only via USB Wi-Fi (rt2800usb, 2.4 GHz, ~32 Mbit/s); `eno1` is a
  different LAN. Keep the video bitrate well below that or change the network.
- alvr_render opens VAAPI rate control once (unpatched system FFmpeg); runtime bitrate changes
  need a service restart. Intel CBR pads every frame to bitrate/framerate.
- Do not run `build-intel-xr.sh`/`prepare-companions.sh` for incremental work (they
  `reset --hard` alvr_render). Use `cmake --build build/monado-alvr` + `scripts/apply-*.py`.
- `alvr_binding.h` is a symlink to the xtask-generated header; never write into it.
- `pkill -f run-video-test` from a shell whose command line contains that text kills the
  shell; use `pkill -f '[r]un-video-test'`.
- The Quest carries the debug-signed client; install `target/debug/apk/alvr_client_openxr.apk`
  (`cargo xtask build-client`). The release build fails with a signature mismatch.
- Always use `adb -s 1WMHHA42R81461` (a Pixel 5 is also attached).

- Wired mode: ALVR forwards 9943/9944 over ADB itself; the service unit must have the SDK
  `adb` on PATH. `adb forward --list` is global; entries carry the device serial.
- ALVR session edits: stop the service first (it rewrites session.json), back up, then start.

## Diagnostic hygiene
Rate-limit noisy probes. Once a boundary is proven, reduce/remove its temporary logging. Record evidence in `TASKS.md`.
