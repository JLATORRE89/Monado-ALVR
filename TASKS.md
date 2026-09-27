# Intel XR Prototype — Task Progress

## OVERNIGHT RESULT (2026-09-26)

**Status (latest):** END-TO-END VIDEO CONFIRMED — operator sees red (left) / blue (right) in the Quest (2026-09-26 ~22:12). Encoder output verified by PC decode — see section 7. Previously solid green (section 6). Earlier: first decoded video frame reached the Quest renderer
(`STREAM_RENDER first_decoded_frame`, Quest 20:57:20.925 = PC 21:57:20). Whether the
checkerboard is visible has not been confirmed by a person.

**Root cause of "only the first packet arrives":** PC egress bandwidth, not code. The PC
reaches the Quest LAN (192.168.86.0/24) only through USB Wi-Fi `wlx9cefd5fa3634`
(rt2800usb, 2.4 GHz ch 11, 130 Mbit/s PHY; `eno1` is on a different LAN, 192.168.1.0/24).
The adapter saturates at ~32 Mbit/s TX, and at a 30 Mbit/s video target the stream socket held
~4 MB in the driver (`ss -uanpm`: `t4142592`). `send()` returns OK, so the server logs
`errors=0`, while the Quest socket shows rx_queue=0/drops=0. At 10 Mbit/s: Send-Q 131 KB,
Quest `STREAM_RECV_STATS shards` rising with `try_again=0`, `DECODER_SUBMIT accepted=true`,
`MEDIACODEC_OUTPUT`, first decoded frame. Delivery is still lossy (`loss=true`, ~20 s gaps).

**Exact remaining blockers:** (1) FIXED in section 7 (green); (2) lossy/insufficient PC->Quest network path (2.4 GHz USB Wi-Fi).
**Needs a human decision (host networking, not changed tonight):** put the PC on the Quest's
LAN via Ethernet or a 5 GHz adapter/AP, or accept a lower bitrate.

**Session config currently changed:** ALVR `video.bitrate.mode.ConstantMbps` 30 -> 10
(backup: `/ai/intel-xr-prototype/backups/alvr-session-2026-09-26-pre-bitrate-test.json`).
Restore: `bash scripts/monado-service.sh stop && cp <backup> ~/.config/alvr/session.json &&
bash scripts/monado-service.sh start`.

**Next command for the operator (headset worn):**
```
pkill -f '[i]ntel_xr_checkerboard'; bash scripts/monado-service.sh restart && bash scripts/monado-service.sh ensure
bash scripts/run-video-test.sh   # then put on the headset / open the ALVR client
```
Expected markers: Quest `VIDEO_PACKET_RECEIVED`, `DECODER_SUBMIT accepted=true`,
`MEDIACODEC_OUTPUT`, `STREAM_RENDER first_decoded_frame`, `STREAM_RECV_STATS`; PC
`ss -uanpm | grep -A1 :9944` Send-Q should stay near 0. Look for the red (left) / blue
(right) solid colours from `demo/checkerboard`.

Commits:
- Monado-ALVR `xr-cleanup`: `603c25467` route RequestIDR into alvr_render IDRScheduler;
  `ac98803f1` seed VAAPI rate control from the ALVR session; `2d63b7349` rate-limit proven
  NAL probes and stop writing into the generated binding header; `25316f274` + this file (docs).
- ALVR `intel-xr-client-diag`: `5401e13c` server VIDEO_SEND_STATS; `b40375a1` client
  STREAM_RECV_STATS heartbeat.

Tests passed: Monado builds rc=0 / 0 warnings; `cargo build -p alvr_server_core` rc=0
(1 pre-existing upstream warning); target/deployed server-core sha256 match (`4581c6d5…`);
client debug APK 0 warnings, installed sha256 `2904634a…` matches build; service `ensure`
PASS after every restart; `/api/insert-idr` -> `REQUEST_IDR_CONSUMED` -> `ENCODED_IDR
requested=true` (3/3 plus live-client requests).

## Proven
- [x] Quest client builds/installs and reaches OpenXR FOCUSED.
- [x] Monado service/API stable.
- [x] Valid initial HMD and eye poses; `xrLocateViews` succeeds.
- [x] Real Quest tracking accepted.
- [x] Checkerboard reaches render and projection submission.
- [x] Monado compositor present path reached.
- [x] Encoder receives frame and produces H.264 IDR.
- [x] Annex-B `00 00 00 01` / prefix 4 verified.
- [x] NAL parser -> Rust C ABI -> ServerCore send path verified.
- [x] Initial IDR observed while `video_channel_sender=None`.
- [x] StreamReady/socket setup later installs video channel and marks Streaming.
- [x] `70b0097d`: request fresh IDR after video transport ready.
- [x] Runtime: `REQUEST_IDR_AFTER_VIDEO_READY ok=true`.
- [x] Rust build freshness issue understood: explicitly build server_core, verify marker/mtime, deploy, compare hashes.
- [x] Target/deployed server-core hashes matched after correct build.
- [x] Build warning cleanup moved to scoped CMake configuration.
- [x] RequestIDR consumer located: alvr_render `handleEvents()` (Encoder.cpp) polls
      `alvr_poll_event` but dropped `ALVR_EVENT_REQUEST_IDR`.
- [x] Existing force-IDR mechanism: alvr_render `IDRScheduler::InsertIDR()` /
      `CheckIDRInsertion()` -> `PushFrame(ts, idr)` -> VAAPI `pict_type = AV_PICTURE_TYPE_I`.
      `present()` bypassed it with a hardcoded `true` (every frame IDR).
- [x] RequestIDR wired (603c25467); headset-free proof via ALVR `POST /api/insert-idr`
      (same `ServerCoreEvent::RequestIDR` path): 3/3 `REQUEST_IDR_CONSUMED` -> next frame
      `ENCODED_IDR requested=true`; P-frames in between; scheduler's 100 ms spacing works.
- [x] Live Quest: client RequestIdr -> `DECODER_CONFIG_SENT` x2 -> `REQUEST_IDR_CONSUMED`
      -> `ENCODED_IDR requested=true` (frames 9, 17).
- [x] Server enqueue/dequeue/send: `VIDEO_CHANNEL_READY/ENQUEUE/DEQUEUE/VIDEO_PACKET_SENT
      idr=true`; `VIDEO_SEND_STATS sent=1000 errors=0`; no "Dropping video packet".
- [x] Quest receives first IDR intact: `VIDEO_PACKET_RECEIVED bytes=52066 idr=true loss=false`.
- [x] Quest decoder config/creation: `CONTROL_DECODER_CONFIG` -> `DECODER_CREATE_BEGIN` ->
      `MEDIACODEC_STARTED software=false` -> `DECODER_CREATED`. A second identical config is
      correctly ignored (no re-create; not a stall).

## Next tasks
- [x] Locate every consumer/match arm for `ServerCoreEvent::RequestIDR`.
- [x] Identify existing alvr_render/encoder force-IDR API.
- [x] Wire RequestIDR to force-keyframe behavior with minimal architecture change.
- [x] Compile and verify artifacts (Monado build clean, 0 warnings; markers in monado-service).
- [x] Verify a new `ENCODED_IDR ... requested=true` occurs after `VIDEO_CHANNEL_INSTALL`.
- [x] Verify `VIDEO_CHANNEL_LOCK_OK present=true` / ENQUEUE (VIDEO_CHANNEL_READY + ENQUEUE logged).
- [x] Verify `VIDEO_CHANNEL_DEQUEUE` and `VIDEO_PACKET_SENT`.
- [x] Quest packet receive (first packet only) and decoder config.
- [x] Explain why only the first video packet reaches `VIDEO_PACKET_RECEIVED` (PC USB Wi-Fi egress saturation).
- [x] Decoder input/output: `DECODER_SUBMIT accepted=true`, `MEDIACODEC_OUTPUT`, `STREAM_RENDER first_decoded_frame` (at 10 Mbit/s).
- [ ] Reliable PC->Quest network path (Ethernet/5 GHz) — human decision.
- [x] Displayed checkerboard confirmed by a person in the headset (red/blue, 2026-09-26 ~22:12).
- [ ] If teardown occurs, capture `SHUTDOWN_TRIGGER client_streaming=... lifecycle=...`.
      Observed twice: `client_streaming=false lifecycle=Resumed` exactly when the Quest's
      OpenXR session went VISIBLE -> STOPPING -> IDLE (activity paused / headset removed).
      That is the headset leaving the app, not a server fault.

## After pixels
- [ ] Save concise end-to-end evidence.
- [ ] Separate production fixes from diagnostics.
- [ ] Prepare clean tracking fixes for main.
- [ ] Prepare video startup/RequestIDR fix for main after end-to-end verification.
- [ ] Remove/rate-limit obsolete probes (candidates: per-frame `[INTEL-XR-NAL] PREFIX_SIZE /
      BEFORE_SEND / AFTER_SEND` in NalParsing.cpp — ~216 journal lines/s).
- [ ] Leave a reproducible regression test.

## Session log 2026-09-26 (overnight)

### 1. RequestIDR consumer (boundary: RequestIDR emitted, no fresh IDR believed seen)
- Evidence re-read: per-frame NAL probe showed ~3,494 `idr=1` frames sent after install in
  the 21:02 run. "No fresh IDR" was an artifact of one-shot `ENCODED_FRAME`/`VIDEO_NAL_ENTER`
  probes; every frame was an IDR because `present()` hardcoded `PushFrame(..., true)`.
  Server-side `info!` markers live in `~/alvr_session.log`, not the journal.
- Hypothesis: route `ALVR_EVENT_REQUEST_IDR` into the existing `IDRScheduler`.
- Change: `scripts/apply-alvr-render-request-idr.py` (idempotent companion patch; alvr_render
  is a detached pinned checkout, not a commit branch): CallbackManager `REQUEST_IDR` slot,
  dispatch from `handleEvents()`, `InsertIDR()` registered once in `initEncoding()`,
  `CheckIDRInsertion()` restored, skip frame if `GetEncoded` has no output.
- Build: `cmake --build build/monado-alvr` rc=0, 0 warnings; markers present in
  `monado-service`, binary newer than source. Commit `603c25467`.
- Test: `/api/insert-idr` x3 -> `REQUEST_IDR_CONSUMED count=1..3` -> `ENCODED_IDR
  idr_count=2..4 requested=true` ~10 ms later. RESULT: proven.

### 2. Encoder rate control (found while verifying P-frames)
- Observation: P-frames of a static solid-colour scene were exactly the IDR size (95.5 KB).
- Root cause: VAAPI opened with hardcoded 500 Mbps CBR and framerate 0 —
  `Settings::Load()` expects `openvr_config`, which `alvr_get_settings_json()` does not
  return, so it throws on the first key and every alvr_render setting stays default
  (`m_refreshRate=0`). Workstation uses Ubuntu's unpatched FFmpeg (libavcodec 60), whose
  VAAPI rate control is fixed at `avcodec_open2()`.
- Change: `scripts/apply-alvr-render-encoder-bitrate.py`: `m_refreshRate` from
  `video.preferred_fps` (only that field), init bitrate from
  `alvr_get_dynamic_encoder_params()`, never framerate <= 0. Commit `ac98803f1`.
- Test: `ENCODER_INIT_BITRATE bps=30000000 fps=72 source=alvr`; every frame 52,084 B
  (= 30 Mbit/72/8; Intel CBR pads each frame to budget). RequestIDR still works.
- Note: Quest Wi-Fi is 5 GHz, 866 Mbit/s, RSSI -34 dBm; the old ~55 Mbit/s would not by
  itself explain zero received packets. This is a correctness fix, not the root cause.
- Not changed on purpose: other openvr_config-derived alvr_render settings (foveation,
  colour correction, codec options) remain at defaults; loading them would change behaviour.

### 3. Server shard send errors (hypothesis H3)
- `StreamSender::send()` aborts a packet on the first failed shard and the result was ignored.
- Change: ALVR `5401e13c` VIDEO_SEND_STATS / VIDEO_PACKET_SEND_ERROR (session log).
- Build: `cargo build -p alvr_server_core` rc=0 (1 pre-existing upstream warning:
  `server_to_client_pose` unused, from upstream `ba48a4d0`); marker in target .so; xtask
  deploy; target/deployed sha256 `4581c6d5…` match; service maps the deployed .so.
- Live Quest test 21:45:22-21:45:48: `VIDEO_SEND_STATS sent=500 errors=0`, `sent=1000
  errors=0`. RESULT: H3 disproved.

### 4. Quest receive after first packet (current)
- Quest timeline (Quest clock = PC - 1 h): STREAMING at 20:45:22.38; first video only at
  20:45:33.6 because Monado produced no frames until the checkerboard connected; packet 0
  received intact; decoder created; then only `STREAM_RENDER no_decoded_frame` at 72 FPS.
- Ruled out statically: unsubscribed stream IDs (server VIDEO/AUDIO/HAPTICS all
  subscribed), buffer starvation (10 recycled buffers/stream), decoder re-create stall
  (identical config is skipped), client state-lock ordering.
- Installed APK sha256 `fd03ee08…` == 17:37 local build; it predates `cd285266` (STREAM_RENDER
  rate limit), which is why logcat rotated in earlier runs.
- Next probe (in progress): client `STREAM_RECV_STATS shards=N try_again=M` heartbeat in the
  stream receive loop, plus passive watchers started 21:48 (8 h limit):
  `logs/2026-09-26_21-48-20_quest-logcat-continuous.txt` and
  `logs/2026-09-26_21-48-20_quest-udp9944-watch.txt` (Quest `/proc/net/udp` rx_queue/drops
  for port 9944 + PC `ss` for 9944).

### Operational lessons recorded
- `pkill -f run-video-test` inside a shell whose command line contains that text kills the
  shell itself (exit 144). Use `pkill -f '[r]un-video-test'`.
- Do not run `scripts/build-intel-xr.sh` / `prepare-companions.sh` for incremental work:
  they `reset --hard` alvr_render and detach ALVR at a pinned rev. Build with
  `cmake --build build/monado-alvr` and re-apply `scripts/apply-*.py`.
- `scripts/quest-usb-awake.sh` uses `adb` without `-s`; it fails when the Pixel 5 is also
  attached. Quest serial: `1WMHHA42R81461`.

### 5. PC egress saturation (decisive, 21:52-21:58)
- Passive watcher (`logs/2026-09-26_21-48-20_quest-udp9944-watch.txt`): Quest UDP 9944
  rx_queue=0 drops=0 while PC socket Send-Q 2.7-4.2 MB. PC `wlx9cefd5fa3634` TX ~32 Mbit/s
  (rt2800usb, 2.4 GHz ch 11, 130 Mbit/s PHY).
- Release APK install refused (`INSTALL_FAILED_UPDATE_INCOMPATIBLE`, signature): the Quest
  has the debug-signed build. Installed debug build instead (`cargo xtask build-client`,
  `target/debug/apk/alvr_client_openxr.apk`); no uninstall, app data kept.
- 10 Mbit/s test (session backed up first): Send-Q 131 KB; client `STREAM_RECV_STATS
  shards=4484..6433 try_again=0`; first decoded frame rendered; frequent `loss=true`.

### 6. Picture content (live, operator in headset, 21:58-22:05)
- Operator saw a grey box: only 2 IDRs arrived, both before the decoder existed; all 17
  accepted frames were P-frames (10 with loss). Enabled existing ALVR
  `connection.avoid_video_glitching=true` (session backup as above) -> decoder gets IDRs.
- Operator then saw solid **green**. Opt-in dump (`scripts/apply-alvr-render-h264-dump.py`,
  trigger file `logs/INTEL_XR_DUMP_H264`) of 150 encoded frames decoded on the PC:
  2144x2336 yuv420p, both eyes RGB ~(0,135,0) = Y=U=V=0 in every frame.
- RESULT: transport, Quest decode and display work end to end; the Quest shows exactly what
  is encoded. **New boundary: encoder input surface is all zeros** — checkerboard content
  (red left / blue right) does not reach the VAAPI frame (alvr_render Renderer output ->
  DRM import `VkFrame`/`mapped_frame` -> `scale_vaapi`/filter graph -> encoder).
- Session config now: ConstantMbps 10, avoid_video_glitching true (both differ from backup).

## Next (operator request)
- After the picture is correct: USB streaming via ALVR's wired mode (ADB port forwarding,
  `alvr_adb::WiredConnection` in server_core). It avoids the 2.4 GHz USB Wi-Fi bottleneck
  entirely. Requires `connection.stream_protocol = Tcp` and the wired client setting; verify
  with `adb -s 1WMHHA42R81461 forward --list`.

### 7. Green frame fixed (22:10)
- Cause: on Intel, `EncodePipelineVAAPI` took the "Importing VA surface" branch — a fresh VA
  surface was encoded while the step that makes the renderer draw into it
  (`r->ImportOutput(drm)`, "TODO: Fix output import") is commented out -> all-zero NV12 -> green.
- Change: `scripts/apply-alvr-render-intel-map-output.py` — Intel uses the existing
  `map_frame()` path (renderer's linear DMA-BUF output, now advertised as
  `DRM_FORMAT_MOD_LINEAR` instead of `MOD_INVALID`); `av_hwframe_map()` result checked with a
  logged fallback to the old path; `ALVR_VAAPI_IMPORT_SURFACE` still forces the old path.
- Build rc=0, 0 warnings. Runtime: `VAAPI_INPUT mode=map_renderer_output intel=1`; service stable.
- Dump decoded on PC: frame 0 grey (Monado idle), frames 5..149 left RGB (254,0,0), right
  (0,0,254) — the checkerboard demo's red/blue.
- Operator confirmed red/blue in the headset. USB CONFIRMED lossless at 72 FPS (section 9); then
  separate production fixes from diagnostics for main.

### 8. USB (wired) streaming — prepared, awaiting headset (22:10-22:15)
- Mechanism (existing ALVR): session entry `client.wired` -> server handshake loop uses
  `alvr_adb::WiredConnection` to `adb forward tcp:9943/9944` to the headset, autolaunches the
  client, waits until its activity is resumed, connects via 127.0.0.1; both ends switch the
  stream to TCP from the negotiated `wired` flag (no client change needed).
- Fix ALVR `2f53241c`: wired setup picked the first ADB device (the Pixel 5 is listed before the
  Quest); now picks the device that has a matching ALVR client installed.
  cargo build rc=0 (1 pre-existing warning); deployed; sha256 `a44b7849…` target == deployed.
- Fix Monado-ALVR `22c489f41`: unit PATH includes `/ai/android-sdk/platform-tools` so ALVR
  uses the SDK adb (otherwise it downloads platform-tools and runs a second ADB server).
- Session (backup `/ai/intel-xr-prototype/backups/alvr-session-2026-09-26-pre-wired.json`):
  `wired_client_type = Custom("alvr.client.monado")`, added `client.wired` (trusted).
- Verified headset-free: service PATH correct, forwards `1WMHHA42R81461 tcp:9943/9944`
  created by the server, no download, client running; handshake waits (headset asleep).
- Wireless entries (`5747.client.local.`, `direct-192.168.86.168`) were left in place; the
  handshake loop tries wired first. If Wi-Fi wins the race, remove them temporarily.

**Operator test for USB (headset on, USB cable connected):**
```
cd /ai/intel-xr-prototype/src/Monado-ALVR
pkill -f '[i]ntel_xr_checkerboard'; bash scripts/monado-service.sh restart && bash scripts/monado-service.sh ensure
bash scripts/run-video-test.sh &      # one checkerboard
# put on headset; ALVR client is autolaunched/resumed
ss -tnp | grep -E ':994[34]'           # expect ESTAB 127.0.0.1 -> 127.0.0.1:9943/9944 (TCP)
grep -E "VIDEO_SEND_STATS|DECODER_CONFIG_SENT" ~/alvr_session.log | tail
```
Expected: TCP 127.0.0.1 connections, `VIDEO_SEND_STATS ... errors=0`, red/blue in headset,
no `loss=true` on the Quest. Then try raising `video.bitrate.mode.ConstantMbps` back to 30
(stop service, edit session, start — the encoder reads bitrate only at init).

## Follow-up: Wi-Fi anti-stutter (operator request)
Evidence so far: PC egress is a 2.4 GHz USB Wi-Fi adapter (~32 Mbit/s); loss appears as
`loss=true` / incomplete packets. Options, most effective first:
1. Network path: PC on the Quest's LAN via Ethernet or a 5 GHz adapter (removes the
   bottleneck; host change — operator decision).
2. Adaptive bitrate: ALVR's `BitrateMode::Adaptive` already measures throughput, but
   alvr_render applies rate control only at `avcodec_open2()` (unpatched FFmpeg). Needs either
   ALVR's FFmpeg dynamic-bitrate patch (`alvr/xtask/patches/0001-vaapi_encode-Allow-to-
   dynamically-change-bitrate-and.patch`) or re-opening the encoder on bitrate change.
3. Faster recovery: keep `avoid_video_glitching=true`; tune `IDRScheduler` min interval
   (`aggressive_keyframe_resend`); consider intra-refresh instead of full IDRs to avoid
   ~13-shard keyframe bursts.
4. Client buffering: `video.max_buffering_frames` to absorb jitter at a latency cost.

### 9. USB streaming confirmed (2026-09-27 ~09:12)
- Operator sees red/blue over USB.
- PC: `monado-service` TCP 127.0.0.1 -> 9943/9944 via `adb` forwards; no UDP 9944 socket;
  `VIDEO_SEND_STATS sent=3000 errors=0`.
- Quest (logcat saved `logs/2026-09-27_usb-stream-logcat.txt`): 1,631
  `VIDEO_PACKET_RECEIVED ... loss=false`, 0 with loss, 1,632 `MEDIACODEC_OUTPUT`, no
  drop/IDR-wait warnings, VrApi FPS=72/72.
- Next: raise bitrate toward 30 Mbit/s over USB (stop service, edit
  `video.bitrate.mode.ConstantMbps`, start); Wi-Fi anti-stutter follow-up above.
