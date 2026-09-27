# XR Control Panel (add-on)

A local web UI to manage one or more Quest headsets and, optionally, the Intel XR
(Monado + ALVR) runtime. It is a separate add-on: install it on any Linux PC to manage
headsets, or remove it — the runtime does not depend on it.

- **Headsets** — every headset attached over ADB (USB or ADB over Wi‑Fi): model, serial,
  battery, awake/asleep, Wi‑Fi IP, ALVR client state and matching ALVR connection.
  Per headset: Screenshot, Start/Stop recording (video with audio), Launch/Close client, Wake.
- **Captures** — screenshots and recordings stored per headset on this PC
  (`~/.local/share/xr-control-panel/captures/<serial>/`), with viewer and download.
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
