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
Make streaming reliable on 2.4 GHz Wi-Fi (operator goal). USB streaming works (lossless,
30 Mbit/s, 72 FPS). Wi-Fi fixes are deployed but need a clean live re-test; one SIGBUS crash is
unexplained. Start from `CURRENT STATUS` at the top of `TASKS.md`.

## Proven state
End-to-end video is confirmed in the headset (red/blue checkerboard) over Wi-Fi at 10 Mbit/s and
over USB at 30 Mbit/s. alvr_render: RequestIDR routed and coalesced in IDRScheduler; VAAPI encodes
the renderer's real output on Intel; rate control follows ALVR (runtime changes via encoder
re-open); frames carry tracking timestamps so ALVR statistics/Adaptive work. ALVR server core:
wired (USB) mode picks the device with the client and falls back to Wi-Fi; send-path congestion
cuts bitrate (AIMD); EINTR is retried; IDR requests are de-duplicated. alvr_render changes live
as idempotent `scripts/apply-*.py` helpers (order in TASKS.md) because alvr_render is a pinned
detached checkout. Live ALVR session settings differ from defaults; see TASKS.md.

## Procedure
Read `RULES.md` and `TASKS.md` first. Inspect existing code before patching. Prefer existing ALVR/Monado mechanisms. Make one narrow change per hypothesis. Compile the directly changed component first, verify the actual artifact, then rebuild/restart dependencies. Run one controlled test, record evidence in `TASKS.md`, and commit meaningful changes.

## Branch safety
Do not merge to main. Do not force-push, reset --hard, rewrite history, delete branches, or discard user work. Work only on `xr-cleanup` and `intel-xr-client-diag`.

## Stop conditions
Stop and document before destructive Git, headset firmware/OS changes, factory reset, credential/account changes, unrelated firewall/network changes, evidence deletion, or broad speculative changes. Leave repositories buildable.
