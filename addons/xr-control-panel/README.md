# XR Control Panel (add-on)

A local web UI to manage one or more Quest headsets and, optionally, the Intel XR
(Monado + ALVR) runtime. It is a separate add-on: install it on any Linux PC to manage
headsets, or remove it — the runtime does not depend on it.

- **Headsets** — every headset attached over ADB (USB or ADB over Wi‑Fi): model, serial,
  battery, awake/asleep, Wi‑Fi IP, ALVR client state and matching ALVR connection.
  Per headset: Screenshot, Start/Stop recording (video with audio), Launch/Close client, Wake.
- **Captures** — screenshots and recordings stored per headset on this PC
  (`~/.local/share/xr-control-panel/captures/<serial>/`), with viewer, download and delete
  (asks first; "Also delete from headset" removes the Quest's copy too when it is connected).
- **Streaming** *(runtime)* — start/exit the test app, stop the runtime, ALVR connections
  (approve, forget, clear).
- **Settings** *(runtime)* — edit `config/xr-build.json`, restart, rebuild (incremental,
  re-applies companion patches; never resets repositories).
- **Approved devices** — MAC allow-list; import JSON, CSV or XLSX (XLSX needs
  `python3-openpyxl`), remove entries.

Works offline: no external fonts, scripts or images. Mobile-first layout for touch and
VR pointers. Requirements: `python3` (standard library only), `adb` (Android platform-tools),
systemd user session.

## Install

```bash
# Headset management only (any PC):
bash addons/xr-control-panel/install.sh

# With the Intel XR runtime features:
bash addons/xr-control-panel/install.sh --runtime-root /ai/intel-xr-prototype
```

Options: `--port 8083`, `--bind 127.0.0.1`, `--prefix DIR`. Open http://127.0.0.1:8083/.
Service: `systemctl --user status xr-control-panel.service`; logs:
`journalctl --user -u xr-control-panel.service`.

## Uninstall

```bash
bash addons/xr-control-panel/uninstall.sh          # keeps config and captures
bash addons/xr-control-panel/uninstall.sh --purge  # also deletes config and captures
```

## Configuration

`~/.config/xr-control-panel/config.json` (created by the installer):

| Key | Default | Meaning |
|---|---|---|
| `bind` | `127.0.0.1` | Listen address. Anything else exposes headset and runtime control to your network. |
| `port` | `8083` | Listen port. |
| `runtime_root` | `null` | Intel XR checkout (enables Streaming/Settings). |
| `alvr_api` | `http://127.0.0.1:8082` | ALVR web API. |
| `capture_dir` | `~/.local/share/xr-control-panel/captures` | Where captures are stored. |
| `approved_registry` | `~/.config/intel-xr/approved-devices.json` | MAC allow-list. |
| `client_package` | `alvr.client.monado` | ALVR client package on the headsets. |
| `adb` | auto | Explicit path to `adb`. |

## Headsets over Wi‑Fi

Captures and client control need ADB. For a headset without a cable, enable ADB over
Wi‑Fi once while connected by USB: `adb -s <serial> tcpip 5555`, then
`adb connect <headset-ip>:5555`. Any device on the network can then use ADB with that
headset until it reboots — only do this on a trusted network.

## Notes

- Captures use the Quest system capture service (`com.oculus.metacam`); on current Horizon
  OS the recording actions are `START_/STOP_INTERNAL_CAPTURE_TO_DISK`.
- ALVR streams to one headset at a time; the panel manages many.

## GPU Worker add-on (optional)

The **GPU Worker** tab sends captures to a Local AI Stack shared GPU on another system
(`gpu_video_api_package`, `/api/v1/gpu-api`) and saves the results to
`captures/gpu-worker/`, so they show up in Captures and in the Loft's Pictures app. It is for
offline work (upscaling, generating images or panoramas); live VR frames always render and encode
on this PC's GPU.

- **Connection:** the remote system's IP address or host name (optional `:port`), HTTPS only.
  When you use an IP address, enter the **certificate host name** the server's certificate was
  issued for; the certificate is still fully verified. A custom CA file is optional.
- **Connection key:** create one in the Local AI Stack account settings with the `render` and
  `storage` scopes. It is stored only in `~/.config/xr-control-panel/gpu-worker.json` (mode
  0600) and never sent to the browser. **Remove key** deletes it.
- **Jobs:** pick a workflow offered by the remote (discovered from the API, never typed in),
  an optional source capture and a prompt. One-reference workflows receive the capture as the
  API's `0.png` ZIP bundle. The request ID is saved before submitting; **Check status** polls and
  downloads outputs once, **Retry submission** resends with the same request ID after a lost
  response. Outputs are downloaded only through the API's asset path and never overwrite files.
- Job history: `~/.local/share/xr-control-panel/gpu-worker/jobs.json` (0600).

## Loft menu and uploads

- **Streaming → Loft:** buttons for Lobby and each enabled Loft menu entry (`open:<id>`), plus
  Previous / Next / Play-pause for Pictures and Videos.
- **Streaming → Loft menu:** enable/disable entries, remove added ones, add a **Quest app** (pick
  from the headset's installed apps) or a **PC mini-game** (absolute path of an executable). Saved
  to `~/.config/xr-loft/menu.tsv`; a running Loft reloads it immediately.
- **Captures → Upload pictures or videos:** jpg, png, webp, mp4, webm, mov, mkv (up to 4 GiB),
  stored in `captures/library/` (names sanitised, never overwritten); the Loft's Pictures and
  Videos apps show them.

## Using the panel from inside the headset

The panel is mobile-first so it works in the Quest's browser. On the **Headsets** tab, **Open
panel in headset** runs `adb reverse tcp:8083 tcp:8083` (USB) and opens
`http://127.0.0.1:8083/` in the headset's browser. The panel stays bound to 127.0.0.1; nothing is
opened to the network. Over Wi-Fi only, run the panel with `"bind": "<LAN address>"` in
`~/.config/xr-control-panel/config.json` instead (the panel has no login, so only on a trusted
network).
