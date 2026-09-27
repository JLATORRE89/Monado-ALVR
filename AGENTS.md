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
Get reliable PC->Quest video delivery. Code path is proven through Quest decoder output and
`STREAM_RENDER first_decoded_frame` (2026-09-26, at 10 Mbit/s). Remaining blocker is the
network: the PC's only path to the Quest LAN is a 2.4 GHz USB Wi-Fi adapter saturating at
~32 Mbit/s. See the OVERNIGHT RESULT in `TASKS.md`.

## Proven state
Tracking, render, compositor, encoder and NAL -> server-core paths are proven.
`ServerCoreEvent::RequestIDR` is consumed by alvr_render `handleEvents()` and drives the existing
`IDRScheduler` (`scripts/apply-alvr-render-request-idr.py`). VAAPI rate control is seeded from the
ALVR session (`scripts/apply-alvr-render-encoder-bitrate.py`). Server enqueue/dequeue/send is
proven with 0 send errors. At 10 Mbit/s the Quest receives packets, decodes them
(`MEDIACODEC_OUTPUT`) and renders the first decoded frame. alvr_render changes live as idempotent
`scripts/apply-*.py` helpers because alvr_render is a pinned detached checkout.

## Procedure
Read `RULES.md` and `TASKS.md` first. Inspect existing code before patching. Prefer existing ALVR/Monado mechanisms. Make one narrow change per hypothesis. Compile the directly changed component first, verify the actual artifact, then rebuild/restart dependencies. Run one controlled test, record evidence in `TASKS.md`, and commit meaningful changes.

## Branch safety
Do not merge to main. Do not force-push, reset --hard, rewrite history, delete branches, or discard user work. Work only on `xr-cleanup` and `intel-xr-client-diag`.

## Stop conditions
Stop and document before destructive Git, headset firmware/OS changes, factory reset, credential/account changes, unrelated firewall/network changes, evidence deletion, or broad speculative changes. Leave repositories buildable.
