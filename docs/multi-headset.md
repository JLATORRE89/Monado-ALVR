# Several headsets on one PC (W15)

ALVR streams to one headset per server and the Monado ALVR driver drives one HMD, so each extra
headset gets its own **runtime instance**: a second Monado service with its own ALVR server. The
default runtime (`intel-xr-monado.service`) keeps serving the first headset unchanged.

## Quick start

```sh
# Second headset on USB (find its serial with `adb devices`) and/or on Wi-Fi by IP:
bash scripts/xr-instance.sh create quest-b --serial 2G0YC1ZF8B0123 --ip 192.168.86.170
bash scripts/xr-instance.sh start quest-b            # also starts voice chat routing
XR_INSTANCE=quest-b bash scripts/xr-app.sh start loft
bash scripts/xr-instance.sh list
```

Open the ALVR client on the second headset (on USB by hand; it is not auto-launched). Both users
are in the same Loft room and see each other as people (presence), and hear each other
(voice). Stop: `XR_INSTANCE=quest-b bash scripts/xr-app.sh stop-all`; delete:
`xr-instance.sh remove quest-b`.

## What each instance gets

| Resource | Default runtime | Instance *n* (1..9) |
|---|---|---|
| systemd unit | `intel-xr-monado.service` | `intel-xr-monado@<name>.service` (`systemd/intel-xr-monado@.service`) |
| Monado IPC | `$XDG_RUNTIME_DIR` | `/run/user/<uid>/xr-<name>` (Loft started with the same `XDG_RUNTIME_DIR`) |
| ALVR config | `~/.config/alvr/` | `~/.config/alvr-<name>/` (`ALVR_CONFIG_DIR`, copy of the default session) |
| ALVR logs | `~/alvr_session.log` | `logs/instance-<name>/` (`ALVR_LOG_DIR`) |
| ALVR web API | 8082 | 8090 + *n* (8083 is the control panel) |
| Stream port | 9944 | 9944 + 20·*n* (UDP bind on this PC must differ) |
| USB control port (PC side) | 9943 | 9943 + 20·*n* → headset 9943 (`ALVR_WIRED_PORT_OFFSET`) |
| USB headset | first with the client | pinned: `ALVR_WIRED_SERIAL` |
| Trusted headsets | as configured | wired entry + `direct-<ip>` only (never the first headset's Wi-Fi entry) |
| Audio nodes | `ALVR Audio`, `ALVR Microphone` | `ALVR Audio (<name>)`, `ALVR Microphone (<name>)` (`ALVR_INSTANCE_NAME`) |
| Loft spawn | (0, 1.0) | beside/ahead of the default spawn (`XR_INSTANCE_INDEX`) |

Code: ALVR fork `sockets::wired_control_port`, `adb` local→remote forwards and serial pinning,
`audio/linux.rs` node names (commit 2d4cba1d); alvr_render companion step 11
`apply-alvr-render-instance.py` (config/log dirs); Loft `presence.c`.

## Presence (seeing each other)

Every Loft binds `/run/user/<uid>/xr-loft-presence/<instance>.sock` (`XR_LOFT_PRESENCE_DIR`, set by
`xr-app.sh`) and sends its user's world head pose ~20 times a second to the others; peers silent
for 2 s disappear. Others are drawn as people standing under their head position, facing their
view direction. Tested with two runtimes and two Lofts on this PC (logs `PRESENCE joined`,
snapshot shows the visitor); not yet with two real headsets.

## Voice

`scripts/xr-voice.sh watch` (service `intel-xr-voice.service`, started by `xr-instance.sh start`)
links each `ALVR Microphone*` into every **other** `ALVR Audio*` with `pw-link` (mono mic → both
channels), never into its own headset, and re-checks every 3 s because ALVR creates the nodes only
while a headset streams. `xr-voice.sh status|unlink` inspect/remove. Verified with PipeWire null
devices named like ALVR's; real headset audio has not been verified yet (ALVR's audio nodes were
not seen during this session because no headset was streaming at the time).

## Limits

- Every instance encodes its own stream on the one Arc GPU; expect 2-3 headsets at full quality.
- The control panel's Loft card and media commands reach the default runtime's Loft only.
- Visitors look like the staff style of person (no distinct clothing or name tag yet).
