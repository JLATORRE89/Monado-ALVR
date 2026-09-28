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
- `ServerCoreEvent::RequestIDR` is consumed by alvr_render `handleEvents()` and coalesced in `IDRScheduler` (resolved 2026-09-26/27).
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

## Lessons 2026-09-27 (Wi-Fi / USB)
- `pkill -f` patterns match the invoking shell's own command line (exit 144). Bracket every
  pattern and never put another matching word later in the same command; prefer PIDs from
  `ps -eo pid,comm`.
- Crash evidence: apport drops cores of non-packaged binaries, `coredumpctl` is not installed and
  `ptrace_scope=1` blocks attaching. Use the in-process `[INTEL-XR-FAULT]` handler, or run the
  service as a gdb child only for short tests: gdb causes EINTR-driven disconnects in
  un-patched ALVR and is not representative of live timing.
- FFmpeg 6.1 (system) VAAPI ignores runtime `bit_rate`; bitrate changes need an encoder re-open.
  Measure effective bitrate by frame size (Intel CBR pads each frame to bitrate/fps).
- ALVR stats/Adaptive key frames by tracking `poll_timestamp`; never send counters as frame
  timestamps.
- Adaptive bitrate only learns from frames the client receives; a saturated link needs a
  server-side congestion signal (send-path drops) and bounded send buffers/queues.
- Bound latency, not throughput: large socket buffers (Maximum) and 1024 queued frames turn
  congestion into seconds of delay.
- Every IDR request path must be rate-limited/coalesced; the consumer (IDRScheduler) is the
  single place that decides.
- After any API stress test via `/api/session/values`, re-check `~/.config/alvr/session.json`:
  those changes persist.
- `/api/session/values` changes apply live; connection-level settings (buffers, queue length,
  stream protocol) apply only to new connections.

## Lessons 2026-09-27 (consolidation)
- A companion helper's `marker` must be text that only exists after its own patch, is not
  rewritten by a later patch, and does not occur elsewhere in the file. Violations made a fresh
  reconstruction silently differ from the working tree.
- Prove companion reproducibility in a temporary `git worktree` from the pinned revision, never
  in `src/alvr_render`; compare with `diff -r -x .git`. Re-run after any helper change.
- Use `scripts/rebuild-runtime.sh` for rebuilds; `prepare-companions.sh`/`build-intel-xr.sh`
  reset repositories.
- Do not commit workstation choices as repo defaults; put them in `config/xr-build.local.json`.
- Only warnings from project or companion code count against "clean build"; record upstream ones.

## Runtime rebuilds
- Any Monado build relinks the OpenXR client library with the new git tag; the running service
  then rejects new apps (`ipc_client_check_git_tag`). Restart the service after building, before
  launching apps (`scripts/rebuild-runtime.sh` already tells you to).

## Diagnostic hygiene
Rate-limit noisy probes. Once a boundary is proven, reduce/remove its temporary logging. Record evidence in `TASKS.md`.
