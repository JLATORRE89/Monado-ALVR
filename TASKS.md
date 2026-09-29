> **Device-card parity (Codex, 2026-09-28):** ALVR-only/disconnected headset cards use
> the same six fields, assistant section and action layout as tablets. Unknown values
> shown as dash, unavailable actions disabled. Tested disconnected Quest + connected
> tablet at1280/800/390px; static-only deployment, no service restarts.

> **Panel visibility/layout + individual mute (Codex, 2026-09-28):** Headsets merges
> trusted ALVR inventory with ADB devices, preserves offline Quest cards and deduplicates
> aliases. ADB-only actions remain unavailable until debugging reconnects. User cannot
> replug USB now. Live browser verified Quest2/1WMHHA42R81461 card (Disconnected).
> Capture footer now selection/details + wrapping action row; all actions visible at
> 1456/800/390 px, no horizontal overflow. Tablet Menu→People has per-listener mute,
> persisted config voice-mutes.json, enforced by proximity router. 20 tablet tests,
> 5 headset discovery tests, JS lifecycle/sound tests and mocked 412px People menu pass.
> User confirms enabling Sound works. Last page reload requires a fresh playback gesture;
> tablet microphone remains explicit opt-in. Last Quest encoder3Mbps; quality tuning
> awaits connected awake headset. No bitrate settings changed.

> **Tablet listening + proximity voice (Codex, 2026-09-28):** Separate Sound/Mic;
> automatic listening after browser gesture, mic opt-in; microphone off/denied does
> not disable listening. scripts/xr-voice.py limits voice to 3m entry/3.5m exit using
> passive presence; unknown positions silent, self excluded. User reports nearby
> voice audible and stops after walking away. tablet_audio.py mirrors non-mic sources
> already feeding primary ALVR Audio; app-audio live acceptance still pending.
> Native Quest app capture is NOT implemented. 17 tablet tests + JS sound/lifecycle
> tests pass. PipeWire snapshot parser handles appended change arrays.
> Current new report: outdoor/lake image quality degrades on Quest; investigate
> streaming performance/bitrate before changing the artwork.

> **Codex tablet pause investigation (2026-09-28):** User confirms real Bluetooth Xbox
> controller walking/looking works on SM-X210, reports pauses. Fixed hidden-tab session
> contention: inactive page releases connection/input, resumes when visible; explicit
> takeover close 4001 prevents reconnect fights; stale close/decode callbacks ignored,
> replaced viewers cannot send movement. 12 isolated tablet tests + Node lifecycle
> regression passed. Panel-only deployment/restart, both tablet tabs reloaded.
> Before 10s sample:300frames/max55.4ms/no reconnects (did NOT reproduce reported pause).
> After 20s:599frames/max53.7ms/p95 43.7ms/no reconnects/no >200ms gaps, hidden tab disconnected.
> User acceptance pending; do not claim all pauses fixed. Desktop browser follow-up:
> Firefox/Ubuntu and Chrome/Windows11 acceptance plus independent remote-PC pairing.

> **Tablet Loft client (Claude, 2026-09-28):** SM-X210 joins the Loft as its own user. Loft 2816a58
> intel_xr_loft_flat (flat renderer in presence) + panel 8e3fafa7f tablet_client.py, /tablet page with touch
> and Xbox controller (Gamepad API; needs a secure page: USB 127.0.0.1 or HTTPS), "Join the Loft" on the tablet
> card. Verified on the tablet (render, presence, tap-to-sit, look). Each renderer uses ~9 MiB of CPU-visible
> VRAM (see the ReBAR note below). Then (Loft 4d2e604, panel d0e52f206): tap/A a glass to drink, Menu
> (Pictures/Videos) and voice chat with the headsets (PipeWire nodes linked by xr-voice.sh). TODO: accept the
> tablet's mic prompt and test voice with a streaming Quest; test a real Xbox pad.

> **Live re-open check (Claude, 2026-09-28 18:41-18:55) - partial:** live runtime now runs the step-15
> binary (72 Hz interval confirmed). 30 diagnostic requests -> 18 re-opens (74-94 ms), 0 faults, runtime
> and Loft stayed up, but the Quest client had already stopped streaming (headset not worn), so the
> with-headset-streaming check is still open. Quest adb then went offline (tablet recovered after an
> adb server restart). Proximity override (prox_close) is still set on the Quest: undo with
> `am broadcast -a com.oculus.vrpowermanager.automation_disable`.

> **Encoder re-open SIGBUS — root cause and fix (Claude, 2026-09-28):** the Arc A750 runs without
> Resizable BAR (lspci: BAR 2 current 256MB, supports up to 8GB; BIOS F68a), so only 256 MB of VRAM
> is CPU-visible; i915 debugfs showed visible_avail 39 MiB, and 0-7 MiB under load. The Intel media
> driver maps and zero-fills buffers there per encoder; the dynamic-bitrate re-open (step 7) opened
> the new encoder while the old one was alive, and the driver's first write faulted (gdb: memset
> into an i915.gem mapping from vaEndPicture, first frame after ENCODER_REOPEN). Live crashes
> 11:39:08 and 12:15:13 both came ~20 ms after a re-open at connection/app-start transitions.
> Companion step 15 apply-alvr-render-reopen-drain.py: drain + free the old encoder before opening
> the new one (fallback: reopen previous settings); rate control uses the configured refresh rate
> (no re-opens on ALVR's 60 fps placeholder flips); diagnostic $XDG_RUNTIME_DIR/intel-xr-encoder-test-bps.
> Controlled test on a separate instance (gdb, test Loft, main runtime + Loft also running): before,
> SIGBUS at the 5th re-open (twice); after, 160 requests / 91 re-opens, 0 faults, 0 failed opens,
> 73-91 ms each, visible_avail 0-7 MiB. Audit 15 steps: tree 49eed3c8 == alvr_render c36cdf9.
> NOT yet verified: the new binary on the live runtime with the headset streaming (needs a runtime
> restart, to be coordinated). Proper fix: enable Above 4G Decoding + Re-Size BAR in the BIOS.

> **Codex follow-up (2026-09-28 12:38):** Claude's pending alvr.cpp refresh-rate fix
> left untouched. Actual connected/awake Quest sample, 16:19:18–16:19:38 UTC:
> 3 late warnings (13.89 ms), 20 encoder reports at 72 fps, active Quest decoder
> input/submission/output. This is a real streaming sample, not a no-client window;
> it does not prove display FPS or controlled A/B improvement. Preserve 8-bit HEVC.
> Loft standing world eye height calibrated once to 1.6 m (measured ~1.618 m after,
> ~2.966 m before), user confirmed. Added centre-headset-dot chair targeting within
> 2.5 m horizontal distance, either trigger seats without controller aiming; centre
> dot turns blue. Visible menu tile under gaze retains priority. Existing controller
> seat marker now overrides an empty menu-plane dot. Three Loft tests pass; live
> 12:33:11 log contains SIT gaze for both L/R hands. Visual/range acceptance pending.
> Panel now offers friendly app dropdown and exports URL-free app identities.
> Standalone Downloader resolves known publisher releases online, verifies supplied
> SHA-256 and creates the existing gzip-9 offline bundle. Initial mappings: ALVR and
> Monado fork; fork currently has no published GitHub release, unmapped/store apps
> fail clearly. Firmware/custom pinned definitions remain supported. 13 existing
> update/bundle tests + 3 automatic-resolution tests + isolated browser picker test
> passed. Installed panel/helper/standalone ZIP synchronized and live endpoints checked.
> Native Windows acceptance remains pending. Do not run test_panel.py on the live host.

> **CORRECTION (2026-09-28 11:45):** HEVC Main10 crashed the runtime (SIGBUS in iHD
> vaEndPicture via avcodec_send_frame) when the headset connected; the Loft died with it and the
> headset showed nothing. 10-bit REVERTED (session back to 8-bit HEVC; crashed config kept as
> session.json.10bit-crashed-2026-09-28). The "0 late frames" figures below were measured with no
> headset streaming. While streaming, ~36 frames/s are "late by 11.11 ms" - the same with the old
> Loft 3e8016f (720 in 20 s) and the new one, so it predates the art pass (11.11 ms is a 90 Hz
> period: check headset refresh vs the 72 Hz runtime/encoder). User saw the new art in the
> headset and said it looked a lot better.
>
> **Loft quality pass (2026-09-28):** (3) Loft art pass, loft main 4367fc8: baked 4096² sun shadow
> map (window grid + furniture shadows), furnishings' AO baked at start-up into a 5 cm ambient-cube
> volume (compute shader), rounded club chairs, bevelled tables, leafy plants, bottles, bordered
> rugs; tools/loft_preview renders a view headless. Live at 2553x2777/eye: 0 late frames (a
> per-pixel AO version produced 4116 in 2.5 min, so it was replaced). (2) Stream: HEVC Main10
> (session use_10bit; backup session.json.pre-10bit-2026-09-28) + companion step 14
> apply-alvr-render-vbv.py (rate-control buffer INTEL_XR_VBV_FRAMES, default 2.5 frames; 1 =
> upstream). Keyframe 110 KB -> ~228 KB, visibly crisper; 0 late frames after. Reconstruction
> audit (14 steps): tree 316b3c6e == alvr_render 904fe27, second run idempotent. NOT verified in
> the headset: Main10 decode/latency on the Quest 2, IDR bursts over 2.4 GHz Wi-Fi (set
> INTEL_XR_VBV_FRAMES=1 in the service env if Wi-Fi stutters on reconnects). The Khronos
> validation layer is not installed here, so Vulkan validation was not run. Wi-Fi adapter is an
> RT5372 (USB 2.0, 2.4 GHz only): moving it to a USB 3 port does not raise throughput.

> **Loft image quality, stream side (2026-09-28):** ALVR session switched H.264 -> HEVC (8-bit; Arc
> VAAPI HEVC LP encode; backup ~/.config/alvr/session.json.pre-hevc-2026-09-28). Same Loft view,
> same 76 Mbit/s: keyframe 158,400 B (H.264, blocky, subtitles illegible) -> 110,772 B (HEVC,
> brick detail and subtitles legible). Panel snapshot now detects HEVC. Root cause of blocky
> keyframes: alvr_render rc_buffer_size = bitrate/fps (one frame of bits per IDR). NOT verified:
> Quest decode/latency with HEVC. Revert = copy the backup back and restart intel-xr-monado.
> Next quality steps: HEVC 10-bit, larger IDR budget (latency trade-off), faster PC->Quest link
> (5 GHz/ethernet AP instead of the 2.4 GHz USB adapter), Loft art pass (baked AO/shadows).
> (GPU add-on pointed at this PC's GPU API https://127.0.0.1 as "localnet" with the local CA;
> it needs a connection key with render+storage scopes from Open WebUI account settings.)

> **Wi-Fi capture + voice, not limited to USB (2026-09-28):** (1) view capture without ADB: companion
> step 13 `apply-alvr-render-view-snapshot.py` (encoder writes one keyframe to
> `$XDG_RUNTIME_DIR/intel-xr-view.h264` on `intel-xr-view-request`), default Quest 2 FOV seeded in
> alvr.cpp so frames render before view params arrive; panel `gpu_screen_request` uses the USB
> screenshot on ADB, else this stream frame (left eye, per instance via the pinned serial). Live:
> panel capture of the running Loft = real 1824x1984 lobby image. Stream frames contain app content
> only (no passthrough/Quest overlays). Reconstruction audit re-run with 13 steps: tree 9d735700 ==
> alvr_render 841717b, second run idempotent. (2) HTTPS listener (`https_port` 8483, self-signed
> cert for stable LAN addresses in ~/.config/xr-control-panel/tls; handshake per request thread);
> insecure pages link to it. Verified on 192.168.1.80 and 192.168.86.151 (cert verifies, unpaired
> -> 401). (3) `POST /api/voice/listen` + "Listen through headset": records the headset's ALVR mic
> ("ALVR Microphone[ (<instance>)]") with pw-record, then whisper. Verified with a temporary virtual
> source of that name (3 s recorded, audible); the real node exists only while a headset streams.
> Tests: test_wifi_capture.py (7), test_https.py (3). NOT verified: real Quest mic over ALVR, Quest
> browser accepting the cert, two headsets at once. Host firewall has no rule for TCP 8083/8483 from
> 192.168.86.0/24 (Quest Wi-Fi); not changed (needs the user's approval).
> Note: tests/test_panel.py is a LIVE click-through (restarts the runtime, stops apps); do not
> include it in offline test loops.

> **Local speech-to-text (2026-09-28):** headset browsers without speech recognition record a clip
> that the panel transcribes with whisper.cpp base.en (build/whisper.cpp, models/whisper). Verified:
> endpoint 0.75 s on the JFK sample, silence/junk refused, headless Chrome with a fake microphone
> (recognition disabled) -> transcript -> request reached GPU submission. NOT verified: the real
> Quest microphone/browser, Wi-Fi voice (needs HTTPS for the mic).

> **Voice with several headsets (2026-09-28):** automatic browser->headset identity (USB device
> cookie from panel-opened links; Wi-Fi via USB pairing grant), per-headset isolation of voice/GPU
> jobs, results and review pages (403/404 for other headsets), Wi-Fi-only result delivery ("ready"
> in the headset's own page). tests/test_voice_isolation.py (6) + all panel suites pass; headset
> view locked to "This headset" at 412 px. NOT yet verified: real Quest speech/mic, two headsets at
> once, live GPU workflow (no GPU key configured).

> **USB once -> Wi-Fi (2026-09-28):** panel now also authorizes Wi-Fi *streaming* for Quests seen on
> USB (approved devices: factory MAC from `dumpsys wifi`; ALVR trusted entry `usb-<serial>` with the
> current Wi-Fi IP), built into Codex's USB pairing worker; `auto_authorize_usb` (browser pairing)
> now defaults on; panel Wi-Fi access turned on for this PC. Live: Quest 2 1WMHHA42R81461 approved
> and trusted at 192.168.86.168. All video files deleted on request (PC and headset VideoShots).

> **ALVR upstream merge (2026-09-27 ~20:50):** branch `intel-xr-master-merge` (d28353c0, pushed to
> the fork, NOT on master): our branch + 55 upstream commits incl. the new socket layer; our pacing /
> send-buffer / IDR / wired / multi-instance features ported; server core builds. Before landing:
> build the Quest client from it, carry `server_send_buffer_bytes` into `server_buffer_config`,
> deploy (companion step 12 then patches alvr_render's alvr_send_video_nal call), headset-test USB +
> Wi-Fi. Panel: "Open panel in headset" (adb reverse, verified HTTP 200 from the headset).

> **W15 several headsets + voice (2026-09-27 ~20:30):** implemented, see `docs/multi-headset.md`.
> ALVR fork 2d4cba1d (port offset, serial pin, instance audio names; server core built, target ==
> deployed sha256 2a177877...), companion step 11 `apply-alvr-render-instance.py` (reconstruction
> re-audited: identical, tree e01f7b36 == alvr_render 0f89e4f), `scripts/xr-instance.sh`,
> `systemd/intel-xr-monado@.service`, `scripts/xr-voice.sh` + `intel-xr-voice.service`, Loft
> presence. Verified: two runtimes side by side (APIs 8082/8091, separate IPC, test instance left
> the first headset's USB forwards alone), two Lofts see each other, voice links with fake nodes.
> Not yet verified: two real headsets, real ALVR audio nodes.

> **Release v0.1.0-beta (2026-09-27):** Monado-ALVR `main` = merge c066ca309 of `xr-cleanup` (tree
> identical to the verified branch); tags `v0.1.0-beta` on Monado-ALVR, loft (28d5d1a) and the ALVR
> fork (830a55bb). The ALVR fork was NOT merged into its `master`: a trial merge (temporary worktree,
> aborted) hit 33 conflicts with upstream master (connection, sockets, client, encoder, OpenVR
> driver); that needs a planned integration and re-test.

> **Loft committed (2026-09-27):** Claude verified Codex's handoff (source hashes, clean build,
> CTest) and committed the art pass + Codex's seating/water/staff work unchanged as loft `main`
> 28d5d1a (pushed). Headset acceptance of the staff, glasses and seating is still pending.

> **Codex follow-up complete (2026-09-27 19:00 EDT):** Seating alignment fixes, interactive water,
> male human bartender and walking female human server are built/running. Read the current
> `/ai/intel-xr-prototype/LOFT-CODEX-HANDOFF.md` before editing; preserve these changes.

> **Claude resume notice (2026-09-27 18:30 EDT):** Jason asked Codex to brighten the
> rear Loft and add seating. Read `/ai/intel-xr-prototype/LOFT-CODEX-HANDOFF.md`
> and current `src/loft` files before editing. Preserve this and the earlier uncommitted
> art pass; do not overwrite from stale session context. OS ports remain plan-only.

# Intel XR Prototype — Task Progress

## CONSOLIDATION RESULT (2026-09-27 ~16:10)

Priority changed from "add features quickly" to "consolidate and preserve the known-good XR stack".

**Companion reproducibility: PASS.** A clean reconstruction reproduces the working alvr_render
source state byte-for-byte.
- Procedure (non-destructive; the working tree is never touched):
  ```
  git -C src/alvr_render worktree add --detach <scratch>/audit/root/src/alvr_render \
      ecb281249b6900ec6ceb6e0570be5100533c706a
  INTEL_XR_ROOT=<scratch>/audit/root INTEL_XR_LOG_DIR=/ai/intel-xr-prototype/logs \
      bash src/Monado-ALVR/scripts/apply-alvr-render-companion.sh     # prints COMPANION OK
  diff -r -x .git <scratch>/audit/root/src/alvr_render src/alvr_render  # no output
  ```
- Result: `diff -r` empty; reconstructed git tree `030ce49411ee2597f1c598893b784bf1438f3d36`
  == `4814e5f^{tree}` (working tree snapshot on the local `intel-xr-companion` branch).
- The orchestrator runs every helper twice; the second pass must report only `[already patched]`.
- The audit found and fixed three reconstruction bugs (8bee6bf01): frame-timestamps marker
  rewritten by its own later patch (re-run aborted), idr-dedup marker colliding with the dump
  helper (fresh reconstruction silently kept `InsertIDR`), encoder-bitrate codec marker absent
  from its inserted text. Before 8bee6bf01 a fresh checkout did NOT reproduce the known-good
  state.

**Clean build: PASS** (logs `logs/2026-09-27_15-56-58_clean-verify/`).
| Component | Result |
|---|---|
| Monado, fresh configure into `build/monado-alvr-verify` | rc=0; 0 warnings from project/companion code. The only 2 warnings are GCC `-Wmaybe-uninitialized` in system Eigen headers via upstream `src/xrt/auxiliary/tracking/t_imu.cpp` (unchanged from `main`). |
| server_core, fresh `CARGO_TARGET_DIR=build/cargo-verify` | rc=0; 1 warning: upstream dead code `TrackingManager::server_to_client_pose` (identical on `origin/monado`; not ours). |
| Quest client `cargo xtask build-client` | rc=0, 0 warnings; APK sha256 `f9258276…0ee1dc6`. |
| Markers, fresh `libopenxr_monado.so` | `IDR_REQUEST_COALESCED`, `[INTEL-XR-FAULT]`, `ENCODER_INIT`, `INTEL_XR_NO_REOPEN`, `INTEL-XR-VIEWS` present |
| Markers, fresh server core / APK | `VIDEO_SEND_STATS`; `STREAM_RECV_STATS`, `APP_EXIT`, `finish_activity` present |
Deployed server core check: `scripts/rebuild-runtime.sh` fails unless target and deployed
sha256 match. No stale artifact is relied on: the verify builds are independent directories.

**Commits / branches.** Monado-ALVR `xr-cleanup`: b7ab80911 (opt-in session codec),
8bee6bf01 (reconstruction fixes), consolidation commit (this section, config hygiene,
`docs/commit-classification.md`) — pushed. ALVR `intel-xr-client-diag` at 830a55bb — pushed,
no new commits. alvr_render `intel-xr-companion` 4814e5f — local only (upstream not ours); the
Monado-ALVR helpers are the source of truth. loft `main` dc982ef — pushed. Classification
of all commits, dependencies and what must not go to main: `docs/commit-classification.md`.
No squash/rebase/merge/force-push.

**SIGBUS review (encoder re-open): no clear bug; fault handler kept.**
- `SetParams`, `MaybeReopenEncoder`, `PushFrame` and `GetEncoded` all run on the encoder
  thread (`Encoder.cpp` loop) → no race on `pending_params` / `encoder_ctx`.
- Re-open builds the new context first, shares `hw_frames_ctx` by reference, frees the old one
  only after `avcodec_open2` succeeds; on failure the old context stays. `mapped_frame` and the
  filter graph belong to the pipeline, not the codec context, and outlive the swap.
- `async_depth=1`: at most one frame is inside the old context; freeing it drops that frame
  (logged as `ENCODER_NO_OUTPUT`) and the new context starts with an IDR. Packet data is consumed
  synchronously before the next `GetEncoded` frees it.
- Residual hazards, documented not fixed: (1) `~EncodePipelineVAAPI` deliberately leaks the
  filter graph / mapped frame (upstream comment: freeing causes a GPU reset), while the base
  destructor frees `encoder_ctx`; (2) at shutdown the Vulkan images backing the DMA-BUF-mapped
  `mapped_frame` can be destroyed while the encoder thread is still in `PushFrame` — the most
  plausible cause of the 15:45 shutdown SIGBUS. The 09:33 mid-stream SIGBUS is unreproduced
  (18 re-opens). `INTEL_XR_NO_REOPEN=1` disables re-open for A/B if it recurs.

**Config hygiene.**
| Layer | Where | Notes |
|---|---|---|
| Repo defaults | `config/xr-build.json` | `android.usb_stay_awake` reverted to `false`. Still contains workstation values (`quest_ip`, `legacy_protocol_test`) listed in the classification as not-for-main. |
| Workstation config | `config/xr-build.local.json` (gitignored) | `{"android":{"usb_stay_awake":true}}`, read by `scripts/quest-usb-awake.sh` after the repo file. Note: the control panel's setting editor still writes the repo file. |
| ALVR session state | `~/.config/alvr/session.json` | see CURRENT STATUS; backups in `backups/alvr-session-*.json` |
| Diagnostic config | env vars on the service: `INTEL_XR_NO_REOPEN`, `INTEL_XR_H264_DUMP*`, `INTEL_XR_LOG_DIR`, `ALVR_LEGACY_PROTOCOL_TEST` | off unless set |
| Add-on config | `~/.config/xr-control-panel/config.json` | outside the runtime |

**Remaining diagnostics** (to gate or remove before main): `INTEL-XR-*` stderr markers from
`apply-server-video-instrumentation.py`, per-frame `ENCODER_DYNAMIC_PARAMS` log, h264 dump
helper, `[INTEL-XR-VIEWS]` in the Monado driver/target, `INTEL-XR-VIDEO`/`STREAM_RECV_STATS` in
the client, `VIDEO_SEND_STATS` in the server, fault handler (keep until SIGBUS understood).

**Next operator command:** `bash scripts/monado-service.sh restart`, start the client on USB,
`bash scripts/xr-app.sh start loft`, confirm image + look-around, then unplug for Wi-Fi.
**Next engineering task:** controllers, W14 step 1 (`docs/controllers.md`).

## UPDATE (2026-09-27 ~17:35)

**Controllers (W14): working in the headset.** Poses, buttons, haptics and trigger selection
confirmed by the operator and the logs (`[INTEL-XR-CTRL] BUTTON/HAPTIC`, `[LOFT] SELECT`). Aim
pitch left -50 / right -60 (a right-hand press landed 1.8 cm from a tile centre at 1.5 m). A
"level and straight" hold read 50/37 degrees up with those settings; closed-loop pointing
disagrees with that open-loop hold, so the pitch was left unchanged. Pose logging: Loft `poses`
command.

**Loft (github.com/JLATORRE89/loft):** 3D room is now the default backdrop (bar, stools,
armchairs, windows onto a CC0 meadow), joystick walking and snap turn, sitting (point + trigger),
menu hide (A/X), menu follow, Quest Home tile (closes the client, the Loft keeps running). Needs
the operator's first look: whether Monado honours the projection layer's source alpha (windows
should show trees, not black).

**ALVR session:** `wired_client_autolaunch` disabled (see below). **Next development task (W15):**
several headsets on this PC in one Loft: one Monado + ALVR instance per headset (own IPC socket,
ALVR ports and config dir), the Loft instances sharing positions over a local socket so people see
each other; limit is the Arc encoder (expect 2-3 streams at reduced resolution).

## CURRENT STATUS (2026-09-27 ~16:10)

**Known-good baseline.** Monado compositor → alvr_render (Vulkan) → Intel VAAPI H.264 →
ALVR server core → USB (ADB TCP) or Wi-Fi (UDP) → Quest MediaCodec. Headset: image, look-around,
no double vision, no interface resets; per-eye 1824×1984 on a two-eye canvas.

**Branches / commits.** Monado-ALVR `xr-cleanup` (see git log; classification in
`docs/commit-classification.md`), ALVR `intel-xr-client-diag` 830a55bb, loft `main` dc982ef.

**Companion.** alvr_render pinned `ecb281249b6900ec6ceb6e0570be5100533c706a`; reconstruct with
`scripts/apply-alvr-render-companion.sh`, order: base-compat, server-video-instrumentation,
request-idr, encoder-bitrate, intel-map-output, h264-dump (diagnostic, opt-in at runtime),
dynamic-bitrate, frame-timestamps, idr-dedup, stream-extent. Known-good tree = local
`intel-xr-companion` 4814e5f. Rebuild with `scripts/rebuild-runtime.sh` (never resets repos);
do NOT run `prepare-companions.sh` / `build-intel-xr.sh` on a working tree (they reset).

**Known-good ALVR session** (`~/.config/alvr/session.json`): codec H264, 8-bit; Adaptive bitrate
min 3 / max 80 Mbit/s; `foveated_encoding` disabled (alvr_render cannot foveate — enabling it
causes double vision); `avoid_video_glitching=true`; transcoding/emulated view width 1832
(ALVR aligns to 1824×1984); `server_send_buffer_bytes=Custom(131072)`,
`max_queued_server_video_frames=3` (Wi-Fi limits; wired overrides them in code to max buffer and
16 frames); wired client `Custom("alvr.client.monado")`.
`wired_client_autolaunch` disabled (2026-09-27 17:19): with it on, ALVR relaunched the client over
ADB about once a second, so the Loft's Quest Home tile could not leave the client. On USB, open
the client from the Quest library by hand; ports are still forwarded automatically. Backup:
`backups/alvr-session-2026-09-27_17-18-46-pre-autolaunch-off.json`.
- USB: ADB forward 9943/9944, TCP; measured ~76 Mbit/s, 72 FPS, lossless.
- Wi-Fi: UDP via the 2.4 GHz rt2800usb adapter (~3–32 Mbit/s); Adaptive + AIMD + pacing 1.5×.

**Unresolved risks.** Shutdown SIGBUS (stop service while streaming); one unreproduced
mid-stream SIGBUS; encoder dumps show flat colours while the headset shows content
(capture-path anomaly, diagnostic only); pacing/send-buffer sizing not yet live-tested on
Wi-Fi; foveation unsupported; test-only legacy protocol still enabled on the service.

**Controllers plan (W14)** (higher priority than Loft polish): design in
`docs/controllers.md` — ALVR data (poses via `alvr_get_device_motion(hand_*)`, button batches
via `BUTTONS_UPDATED`/`alvr_get_buttons`, `alvr_send_haptics`), two Monado Touch
`xrt_device`s, pose/button/haptic mapping, 5 incremental steps. Found while researching:
alvr_render never drains `BUTTONS_UPDATED`, so server_core's button queue grows for the whole
session (fixed by W14 step 2).

**Next human test:** USB then Wi-Fi look-around in the Loft (command above).
**W14 status (16:35):** steps 1-3 (poses, buttons, haptics) built with 0 warnings and running:
journal shows `[INTEL-XR-CTRL] CREATED`, roles left/right assigned; Loft `[LOFT] INPUT ready`.
Pending in-headset evidence: `[INTEL-XR-CTRL] FIRST_POSE`, `BUTTON`, `HAPTIC`, `[LOFT] SELECT`.
**Next development task:** confirm W14 in the headset, tune the aim pitch, then Loft locomotion (W14 step 4).

## STATUS SNAPSHOT (2026-09-27 ~09:55, superseded)

**Working:** end-to-end video over **USB** (ADB-forwarded TCP, lossless at 30 Mbit/s, 72/72 FPS)
and over **2.4 GHz Wi-Fi** (stable, adaptive at ~3-6 Mbit/s on a ~3-4 Mbit/s link; operator can look
around with minor edge clipping from ~110 ms latency). See W10.

**Open tasks (in order):**
1. DONE (W10): clean 2.4 GHz re-test. Next for Wi-Fi quality: packet pacing and a latency-bounded
   send buffer (see W10). Operator: quit and
   reopen the ALVR client in the headset (or unplug USB while streaming). Watch
   `python3 scripts/alvr-stats.py 30`, `ENCODER_REOPEN`, `IDR_REQUEST_COALESCED`, journal
   `[INTEL-XR-FAULT]`.
2. SIGBUS crash (2026-09-27 09:33:20, ~1.1 s after the 2nd encoder re-open under Wi-Fi congestion;
   process stalled, then died). Not reproduced in 18 re-opens (headset-free and live USB). No GPU
   hang in kernel log. `[INTEL-XR-FAULT]` handler now prints a backtrace if it recurs.
3. Wi-Fi anti-stutter follow-ups if still choppy: packet pacing (spread a frame's shards over
   the frame interval), IDR/intra-refresh tuning, client buffering (see the Wi-Fi section).
4. Separate production fixes from INTEL-XR diagnostics and prepare changes for `main`.
5. Optional: faster Adaptive start (encoder opens at 30 Mbit/s before the first estimate).

**Live ALVR session (`~/.config/alvr/session.json`), differs from the original:**
Adaptive bitrate (min 3, max 30 Mbit/s); `avoid_video_glitching=true`; wired client
`client.wired` + `wired_client_type=Custom("alvr.client.monado")`;
`server_send_buffer_bytes=Custom(131072)`; `max_queued_server_video_frames=3`.
Backups in `/ai/intel-xr-prototype/backups/alvr-session-*.json` (oldest:
`...-2026-09-26-pre-bitrate-test.json`).

**alvr_render companion patches** (pinned detached checkout; apply in this order after a fresh
checkout, then `cmake --build build/monado-alvr`):
`apply-server-video-instrumentation.py`, `apply-alvr-render-request-idr.py`,
`apply-alvr-render-encoder-bitrate.py`, `apply-alvr-render-intel-map-output.py`,
`apply-alvr-render-dynamic-bitrate.py`, `apply-alvr-render-frame-timestamps.py`,
`apply-alvr-render-idr-dedup.py`; optional diagnostic `apply-alvr-render-h264-dump.py`.

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
- 30 Mbit/s over USB (2026-09-27 09:13; session backup
  `backups/alvr-session-2026-09-27-pre-30mbps.json`): `ENCODER_INIT_BITRATE bps=30000000 fps=72`,
  frames 52,116 B; Quest 1,687 packets `loss=false`, 0 lost, 1,687 `MEDIACODEC_OUTPUT`,
  FPS=72/72, no drop warnings (`logs/2026-09-27_usb-30mbps-logcat.txt`). Session now: 30 Mbit/s,
  avoid_video_glitching=true, wired client enabled. For Wi-Fi keep <=10 Mbit/s until the network changes.

## Wi-Fi / 2.4 GHz work (2026-09-27)
Goal (operator): streaming must work on 2.4 GHz networks.

### W1. Runtime bitrate (commit 8d9a9f91c)
- alvr_render never applied ALVR's dynamic encoder params; Ubuntu FFmpeg 6.1 VAAPI also
  ignores runtime `bit_rate` changes (measured). `scripts/apply-alvr-render-dynamic-bitrate.py`
  polls `alvr_get_dynamic_encoder_params()` per frame and re-opens the VAAPI encoder when
  the per-frame budget changes >= 10% (decrease after >= 1 s, increase after >= 5 s).
- Measured: re-open 8-9 ms; frames 17,394 B (10 Mbps) -> 62,542 (30) -> 10,450 (5) -> 62,542 (30).

### W2. Frame timestamps (commit 3ce2701f5)
- ALVR stats/Adaptive and the client's pose lookup key frames by tracking `poll_timestamp`;
  alvr_render sent its frame counter, so no latency was ever measured.
  `scripts/apply-alvr-render-frame-timestamps.py` tags frames with the latest tracking
  timestamp and calls `alvr_report_present/composed`.
- USB result: `FRAME_TIMESTAMP source=tracking`; Quest 570 packets, 0 lost, 72/72 FPS.
  `scripts/alvr-stats.py 10` (reads ws://127.0.0.1:8082/api/events): network_latency 2.6 ms,
  total 58.7 ms, estimated throughput ~114-118 Mbit/s, requested 30 Mbit/s (max clamp).

### W3. Adaptive mode enabled (session; backup
`backups/alvr-session-2026-09-27-pre-adaptive.json`)
- `video.bitrate.mode = Adaptive`, min 3 Mbit/s, max 30 Mbit/s (other Adaptive defaults).
- Next: 2.4 GHz test — unplug USB (wired entry then not ready), let the client connect over
  Wi-Fi, watch `scripts/alvr-stats.py 30` (requested bitrate should fall toward the
  link's capacity) and Quest `loss=` counts / `ENCODER_REOPEN` lines.

### W4. Wi-Fi fallback after unplugging USB (ALVR cfb2e4cf)
- With a `client.wired` entry the handshake loop `continue`d past the wireless paths whenever
  wired was not ready, so after unplugging the server stopped trying Wi-Fi (Quest listening on
  9943). Fixed with a labeled block (`break 'wired`). Verified: reconnected over Wi-Fi.

### W5. Bufferbloat (session change; backup `...-2026-09-27-pre-antibloat.json`)
- Wi-Fi link measured ~10 Mbit/s (retries); at 30 Mbit/s the socket queue sat at ~4 MB =
  seconds of latency -> grey screen. Set `server_send_buffer_bytes=Custom(131072)` (kernel:
  256 KB) and `max_queued_server_video_frames=3` (was 1024). Queue then bounded at ~256 KB.

### W6. Send-path congestion control (ALVR f1f3e0f6)
- With no frames arriving, the client sends no stats and Adaptive never lowers the bitrate
  (observed 1,293 drops at 30 Mbit/s, no change). `BitrateManager::report_send_congestion()`
  on "Can't push to network": cap = 70% (>= 500 ms apart, floor 2 Mbit/s); after 2 s without
  congestion +5%/s; removed when above the computed bitrate. Observed 30 -> 21 -> 14.7 -> ...
  -> 5.1 Mbit/s, then recovery to 15 Mbit/s.

### W7. SIGBUS crash (open)
- 09:33:20: `Main process exited, code=dumped, status=7/BUS` ~1.1 s after `ENCODER_REOPEN
  bps=14700000` (process silent after one more frame). apport kept no core (non-packaged
  binary); `coredumpctl` not installed; `ptrace_scope=1` blocks attaching. Reproduction attempts
  (9 re-opens + insert-IDR spam headset-free; 9 re-opens with live USB client under gdb): no
  crash. No i915/xe GPU hang in `journalctl -k`. Fault handler added (W9).

### W8. EINTR disconnects (ALVR 1d955f09)
- Running `monado-service` under gdb: `Client disconnected. Cause: Interrupted system call
  (os error 4)` every few seconds. `HandleTryAgain` now maps `ErrorKind::Interrupted` to TryAgain.

### W9. Keyframe (IDR) de-duplication (ALVR a6d57db2, Monado-ALVR add2b7689)
- Operator request: no duplicate keyframes on any channel. Sources: send-path drops (per drop),
  client RequestIdr (per lost packet, each also resent the decoder config), post-install,
  `/api/insert-idr`, recording.
- Server: request on transition into corrupted or when the dropped frame was an IDR; client
  requests forwarded (with decoder config) at most every 100 ms per connection.
- alvr_render `IDRScheduler::RequestIDR()`: one pending request, forced IDRs >= 100 ms apart,
  any encoded IDR satisfies pending requests (`IDR_REQUEST_COALESCED count=N`).
- Same commit: SIGBUS/SIGSEGV handler (`[INTEL-XR-FAULT] signal= code= addr=` + backtrace).
- Builds: Monado rc=0, 0 warnings; server core deployed, sha256 `7fb92253…` target == deployed.
- Not yet live-tested (headset client stopped accepting connections after the gdb loop).
- Note: a stress test left the session in ConstantMbps 15; restored to Adaptive at ~09:55.

### W10. 2.4 GHz live result (2026-09-27 09:55-09:58)
- Normal service with W1-W9 deployed; client reloaded; connected over Wi-Fi (UDP).
- 60 s: no crash, no disconnect, 24 drops only at start; send queue 45-75 KB (was ~4 MB);
  Adaptive + congestion cap settled at 3-6.6 Mbit/s (floor 3). ALVR stats: network latency
  ~50-100 ms, total ~100-140 ms (USB: 2.6 / 58.7 ms); estimate ~0.8 Mbit/s (clamped to min 3).
  PC adapter TX ~3 Mbit/s with a standing queue => link capacity ~3-4 Mbit/s at this time
  (was ~10 at 09:28, ~32 on 2026-09-26). Quest on 5 GHz 866 Mbit/s; bottleneck is the PC's
  2.4 GHz rt2800usb adapter (ch 11).
- **Operator: can look up/down/left/right with minor visual clipping** (edge clipping from
  ~110 ms latency under reprojection).
- Next candidates: packet pacing (reduce burst loss/queueing on 2.4 GHz); lower latency floor
  (queue is ~160 ms at 3 Mbit/s: consider a smaller send buffer relative to bitrate); better
  2.4 GHz channel/adapter placement (operator).

### W11. Exit controls, queue sizing, pacing, UI (2026-09-27 ~10:00-10:15)
- PC exit: `scripts/xr-app.sh {start|stop|stop-all|status}` + web UI buttons (8792bbb72);
  verified stop/start via the UI endpoints.
- In-headset exit (ALVR 0bf9b502): hold left menu (≡) 2 s while streaming -> xrRequestExitSession
  -> leave session loop -> Activity.finish(). APK built (0 warnings), installed sha256 `820a6961…`.
  NOT yet tested in the headset.
- Send buffer = 3 frames of current bitrate (32 KB-2 MB) and UDP shard pacing at 1.5x bitrate
  (ALVR 616a740d). Server core deployed sha256 `3145f29d…`. NOT yet tested live (headset was not
  connected); expected markers `SEND_BUFFER_RESIZE`, smaller `ss` queue, lower network latency.
- Web UI mobile-first (af0fea496); "Rebuild runtime" now confirms (destructive).
- `TERMS.md` glossary added.

## Requested next (operator, 2026-09-27)
1. Live test of W11 (pacing/queue on 2.4 GHz; menu-hold exit).
2. Media viewer: stream a chosen picture or WebM video (with sound via ALVR's PipeWire output)
   to the headset, selectable from the web UI.
3. Desktop streaming with interaction: needs **controller support in the Monado ALVR driver**
   (today only the HMD is exposed; ALVR already delivers controller poses/buttons), then an
   OpenXR desktop viewer such as wlx-overlay-s. Controllers are also the prerequisite for using
   pointers on the web UI inside VR.
4. Web UI reachable from the Quest browser would require binding beyond 127.0.0.1 (security
   decision for the operator; currently localhost only).

### W12. Exit fix + headset screenshots (2026-09-27 ~10:15-10:20)
- In-headset exit verified by operator. Relaunch then failed: Android kept the process cached
  after Activity.finish() and reused it; client never restarted (lobby placeholder only, 9943
  refused, no client logs). Fixed (ALVR b13c4e5d): reset exit flag at start and
  `std::process::exit(0)` after an in-app exit. Installed sha256 `f9258276…`; client reconnects.
- Headset screenshots from the web UI (Monado-ALVR commit above): metacam TAKE_SCREENSHOT ->
  pull to `logs/headset-screenshots/` -> gallery. Verified (1440x1440 JPEG of the streamed view).
  Works for any foreground Quest app while ADB is connected. For Wi-Fi-only use, ADB over Wi-Fi
  must be enabled once over USB (`adb tcpip 5555`) — not done (operator decision).
- Still pending live test: W11 pacing / bitrate-sized send buffer on 2.4 GHz.
- Headset video recording from the web UI (with audio): metacam
  `START_/STOP_INTERNAL_CAPTURE_TO_DISK` -> MP4 1920x1080 H.264 + AAC pulled to
  `logs/headset-screenshots/`. (`START_CAPTURE`/`STOP_CAPTURE` log "Invalid action" on this OS.)
  SideQuest uses the same ADB mechanisms, so the web UI does not need SideQuest.

### W13. XR Control Panel add-on (2026-09-27 ~10:25-10:42)
- Operator: web UI must manage multiple headsets, work offline, look professional, and be a
  separately installable/removable module. Built `addons/xr-control-panel/` (commit 8a5004fb4):
  install.sh/uninstall.sh, own user unit `xr-control-panel.service`, config
  `~/.config/xr-control-panel/config.json`, captures `~/.local/share/xr-control-panel/captures/<serial>/`.
- Runtime decoupled: monado-service.sh / xr-support.sh no longer start or require the UI; old
  `xr-client-ui.*` and unit removed. Verified: panel uninstalled -> runtime restart/ensure/status/
  test app all OK -> reinstall keeps config and captures.
- `scripts/rebuild-runtime.sh`: safe incremental rebuild used by the panel.
- Test: headless Chrome click-through (DevTools over pipe; test in session scratchpad) 25/25 PASS
  + approve/forget/clear (session backup restored) + full rebuild OK; no script errors; no
  external requests. Found and fixed: old page never parsed (`\'` escaping); XLSX needed
  openpyxl (now CSV + clear error); installer f-string bug; mobile top bar hid tabs.
- Lobby capture works (client lobby = black diagnostic HUD "STREAM STOPPED").

## Next (operator request): Loft lobby demo app
- PC OpenXR app `demo/loft/`: world-locked tiles (OpenXR quad layers, CPU-rendered textures with
  embedded bitmap font, offline), gaze + 1.5 s dwell selection (no PC controller input yet),
  mini apps: Checkerboard, Color/gradient test, Latency/motion bars, Picture viewer (later WebM).
  "Back" tile below view. Panel: mini-app picker on Streaming tab via a local control file;
  `xr-app.sh start loft|checkerboard`.

## 2026-09-27 afternoon: Loft, double vision, sharpness
- Loft moved to its own repo github.com/JLATORRE89/loft (main); `xr-app.sh start loft`; panel
  Loft card switches mini apps (lobby/checkerboard/colors/motion/pictures/prev/next).
- **Double vision fixed:** ALVR session had `video.foveated_encoding.enabled=true`, so the Quest
  un-warped frames that alvr_render never foveated (its settings loader cannot read
  openvr_config). Disabled in the session (backup `...-pre-no-foveation.json`). Operator confirmed.
  Proper fix later: implement foveation in alvr_render from the session values (saves bandwidth).
- Frame timestamps made unique (client matches view params by timestamp, first match).
- **Resets:** USB streams disconnected every 5-15 s because the Wi-Fi anti-bufferbloat limits
  (3 queued frames, 128 KB) also applied to USB -> drops, IDR waits, bitrate cut to ~3-5 Mbit/s.
  Fixed (ALVR 830a55bb): wired uses >=16 queued frames and the maximum send buffer.
- **Sharpness:** each eye got half its width (per-eye stream size used as the two-eye canvas).
  Fixed (00a835f88); per-eye width 1832 (H.264/Intel max 4096 wide), canvas 3664x1996,
  session `openvr_config.eye_resolution_*` + `transcoding_view_resolution` set (backup
  `...-pre-sharpness.json`); Adaptive max 80 Mbit/s.
- Open: SIGBUS when the runtime is stopped while streaming (fault handler prints no backtrace);
  PC-side encoder dumps of the Loft decode as flat colors although the headset shows content
  (capture-path issue, unresolved); a 4288-wide canvas crashes encoder init (SEGV) instead of
  failing cleanly.
- alvr_render changes also committed to local branch `intel-xr-companion` (upstream is not ours).

## Next (operator): smooth surfaces, view out of the windows, joystick movement
Operator chose to extend the C Loft (not Godot/Unity). Plan:
1. HEVC 10-bit (smooth gradients, better quality per bit; lifts the 4096 px H.264 limit).
2. C Loft 3D room: Vulkan mesh pipeline with MSAA, CC0 PBR textures, window openings onto a
   CC0 outdoor (trees) skybox + tree billboards for parallax; walkable 6DoF.
3. Controllers in the Monado ALVR driver (poses, buttons, thumbsticks, haptics) -> joystick
   locomotion and snap turn in the Loft.

## Codex panel and Quest Home follow-up (2026-09-27)

- Implemented full-width device cards with separate status/address rows and wrapped buttons; dual-stack panel listener, IPv6 display and routable IPv6 pairing.
- Added opt-in automatic USB-to-Wi-Fi panel browser authorization with persistent per-device grants, bounded retries and sticky revocation. Existing LAN/auto-pairing settings remain unchanged. This does not authorize wireless ADB or ALVR streaming.
- Quest app picker reads real device labels; selected/editable title is saved to the Loft tile. Quest and mini-game shortcuts have explicit Remove from Loft controls (no uninstall).
- PC mini-games accept readable Python files; launch hook selects adjacent .venv/bin/python or python3, uses the script folder and returns to Loft on exit.
- Validation: 13 focused backend tests passed, including actual IPv4/IPv6 sockets; isolated browser checks at 320/412/1440px passed with full IPv6 addresses and buttons; friendly picker → tile title → removal passed; Python launch/working directory/venv/return smoke test passed. Real Quest label helper verified. Full native/streamed headset app-launch acceptance remains manual.
- Native Quest Home grey floor/sky: restarted only com.oculus.vrshell, preserved data. Jason confirmed the room returned.

### Backlog: display ordinary Python mini-games inside the headset

- [ ] Present third-party desktop Python application windows on an interactive surface inside the Loft/headset. This is separate from launching scripts on the PC.
- [ ] Select a window capture/presentation mechanism and map Quest controller input to pointer/keyboard input, including focus and returning to Loft.
- [ ] Verify a basic third-party Python GUI/pygame app can be seen and operated entirely in the headset, with clean exit and useful failure feedback. Preserve native OpenXR mini-game support.

## Offline updates, XR Downloader, captures, defaults and voice (Codex, 2026-09-27)

- Installed Software updates tab: streamed APK/OTA storage, verified metadata/hashes, per-headset installation jobs, explicit firmware USB preflight/recovery sideload and post-boot verification. No actual firmware was flashed.
- Added independent addons/xr-downloader (Python 3.11+, Linux/Windows launchers). Panel exports supported-download JSON with direct URLs and SHA-256. Downloader verifies every file, makes gzip-level-9 tar.gz; offline panel import stages and validates everything before publication. Native Windows acceptance remains pending. Configure trusted download definitions; no app-store feed is invented.
- Capture export: individual originals or explicitly selected files (up to 200; none selected by default) as max-compression tar.gz, preserving source files. Settings: selected/default preview and Restore All for editable runtime keys only, from committed runtime defaults; no automatic restart.
- GPU screen voice feature: tap-to-speak/typed dog, ball, chair, glass-cup prompts; selected-headset capture; configured single-image workflow; durable polling; result image copy and browser review on the same headset. Current panel has no GPU host/key configured, so live provider detection and Quest microphone/review are NOT verified. No remote Local AI Stack server code changed.
- Verification: focused update safety tests, downloader → source shutdown → offline import, invalid/traversal/incomplete bundle rejection, real ALVR APK inspection, capture archive/filter/symlink tests, selected/all reset preservation tests, voice routing/target delivery tests. Browser checks at 320/412/1440px, simulated speech routing, menu regression passed. No actual headset install, reset-to-default or GPU submission was used as a test.

### Remaining integration acceptance
- [ ] Configure the GPU worker through the panel using an authorized account key and a real object-detection/annotation workflow; test dogs, balls, chairs and glass cups against known screenshots.
- [ ] Verify real Quest microphone recognition, screenshot visibility (including passthrough limitations), image delivery and review. Native in-Loft speech input is separate from this browser interface.
- [ ] Run XR Downloader on Windows with the same JSON and import its archive on the offline panel.
- [ ] Exercise APK upgrade and firmware recovery with approved release files in a controlled device test; confirm final versions, preserving user data.

### Future item: live video-feed streaming
- [ ] Accept a live video feed and display it in the headset/Loft. Scope and source protocols remain to be chosen.
- [ ] Plan optional voice-requested analysis of current frames, return annotations for review, and validate latency, reconnect behavior and access controls. Future work only; not implemented in this change.

- Selection correction verified: unchecked captures are omitted from archives; export is disabled with no selection. Legacy bulk GET export was removed.

### Future: standalone .NET XR Downloader
- [ ] Implement a .NET version of XR Downloader with self-contained Linux and Windows distributions. Retain compatibility with xr-offline-updates-v1 JSON and max-compression tar.gz bundles; test cross-implementation imports and Windows execution. Python remains the current implementation. Requested as later work, not implemented now.

### Quest microphone diagnostics
- Browser RECORD_AUDIO permission was found not granted. Added an explicit 12-second microphone level test independent of GPU configuration and speech recognition, with permission guidance and cancellation/late-grant cleanup. Test audio stays in browser memory and is not recorded or uploaded. Real headset input and browser speech acceptance pending user interaction.

- Mic diagnostic browser tests passed with simulated signal, denied permission, cancelled pending permission and late stream cleanup. No real audio was captured during those automated tests.
