# Intel XR Prototype — Agent Guide

## Mission
Build and verify the Monado + ALVR standalone XR prototype incrementally. Preserve proven results and advance one evidence boundary at a time.

## Working tree
Project root: `/ai/intel-xr-prototype`

Repositories:
- `src/Monado-ALVR` — `JLATORRE89/Monado-ALVR`, branch `xr-cleanup`
- `src/alvr-monado` — `JLATORRE89/ALVR`, branch `intel-xr-client-diag`
- `src/alvr_render` — companion renderer/encoder consumed by Monado

Artifacts:
- Monado: `build/monado-alvr`
- Cargo server core: `src/alvr-monado/target/debug/libalvr_server_core.so`
- Deployed server core: `src/alvr-monado/build/alvr_server_core/libalvr_server_core.so`
- Logs: `logs/`

## Immediate objective
Trace and implement consumption of `ServerCoreEvent::RequestIDR` so that the existing request emitted after `VIDEO_CHANNEL_INSTALL` forces a fresh encoder IDR.

Target chain:
`VIDEO_CHANNEL_INSTALL -> REQUEST_IDR_AFTER_VIDEO_READY -> fresh IDR -> VIDEO_CHANNEL_LOCK_OK present=true -> VIDEO_CHANNEL_TRY_SEND_RESULT ok=true -> VIDEO_CHANNEL_DEQUEUE -> VIDEO_PACKET_SENT -> Quest receive/decode/display`.

## Proven state
Tracking works; valid initial head/eye identity poses fixed `xrLocateViews`. Real Quest tracking is accepted. Checkerboard reaches `SHOULD_RENDER=1`, projection submission, compositor present, encoder input, and H.264 Annex-B IDR output (~95 KB, `00 00 00 01`). NAL parsing reaches Rust C ABI and `ServerCoreContext::send_video_nal`. The initial IDR occurs before `video_channel_sender` exists and is dropped. The connection later reaches StreamReady, socket connect, `VIDEO_CHANNEL_INSTALL`, and Streaming. Commit `70b0097d` requests `ServerCoreEvent::RequestIDR` after channel installation; runtime proves `REQUEST_IDR_AFTER_VIDEO_READY ok=true`, but no subsequent encoded frame has yet been observed.

## Procedure
Read `RULES.md` and `TASKS.md` first. Inspect existing code before patching. Prefer existing ALVR/Monado mechanisms. Make one narrow change per hypothesis. Compile the directly changed component first, verify the actual artifact, then rebuild/restart dependencies. Run one controlled test, record evidence in `TASKS.md`, and commit meaningful changes.

## Branch safety
Do not merge to main. Do not force-push, reset --hard, rewrite history, delete branches, or discard user work. Work only on `xr-cleanup` and `intel-xr-client-diag`.

## Stop conditions
Stop and document before destructive Git, headset firmware/OS changes, factory reset, credential/account changes, unrelated firewall/network changes, evidence deletion, or broad speculative changes. Leave repositories buildable.
