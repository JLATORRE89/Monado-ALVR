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

## Headset-friendly videos (local or GPU worker)

Each video in Captures has **Prepare for headset**: an H.264 copy at most 1920 wide with AAC sound,
saved as `captures/library/<name>-headset.mp4` (never overwriting). It runs on this PC's Arc
hardware encoder (software x264 if that fails), or on the GPU worker when two or more headsets are
streaming (this PC's GPU is then busy encoding their streams) and the worker offers a workflow
whose ID contains `transcode`. `POST /api/captures/transcode {headset, file, where: auto|local|gpu}`;
local jobs are listed at `GET /api/transcodes`. Live VR streams always encode on the PC that
renders them: raw frames (~2 GB/s per headset) cannot cross the network in time.

### USB browser authorization, addresses and Loft shortcuts

Settings → Panel access now offers **Automatically authorize USB-connected headsets**.
It is off by default and requires Wi-Fi panel access to be enabled. A Quest with USB
debugging approved on this computer and a reachable Wi-Fi address receives a one-time
browser pairing link. Persistent per-device browser credentials survive USB removal
and panel restart; addresses are not credentials. This authorizes the panel browser,
not wireless ADB or ALVR streaming. Turning the setting off stops new grants; Revoke
pairings invalidates existing grants and requires explicit manual pairing to restore.
A browser whose storage was cleared can also be paired manually. Pairing retries are
bounded and their status appears in Settings. Cookies are associated with the panel
address; after changing the host's address, pair again.

The panel supports a dual-stack IPv4/IPv6 listener when LAN access is enabled and the
host supports it. Pairing supports IPv4 and routable IPv6, with bracketed IPv6 URLs.
Link-local IPv6 is displayed but is not used for automatic pairing. This does not
change ALVR's streaming protocol. Device cards use full-width items, separate status
and address rows, wrapping addresses and action buttons.

Installed Quest apps show their device-provided friendly labels followed by package
names in parentheses. The selected label fills **Title in the Loft**, which is saved
as the actual Loft tile title. Labels can be edited, including existing shortcuts.
**Remove from Loft** removes either a Quest app or PC mini-game shortcut without
uninstalling it or deleting its files. Labels are read by the small source-included
Android helper (`android/LoftAppLabels.java`, compiled `android/labels.jar`) through
authorized ADB; no Android application is installed. If label lookup fails, the UI
shows a warning and package names remain available. Rebuild with `javac -source 8
-target 8 -classpath "$ANDROID_JAR" -d "$BUILD_DIR" android/LoftAppLabels.java`, then
`d8 --lib "$ANDROID_JAR" --output android/labels.jar "$BUILD_DIR/LoftAppLabels.class"`.

PC mini-games accept executable files or readable `.py` files at absolute paths.
The runtime launch hook runs Python with `.venv/bin/python` beside the script when
present, otherwise `python3`, and uses the script's folder as its working directory.
Install third-party dependencies in that environment first. Desktop Python windows
appear on the PC; headset presentation of ordinary desktop apps is a separate backlog
task. OpenXR applications can render directly to the headset. The Loft returns when
the launched process finishes.

### Offline software updates

The **Software updates** tab stores standalone APKs and unmodified OTA firmware ZIPs
on this PC (default `~/.local/share/xr-control-panel/updates`; config `updates_dir`).
Upload while files are available, then install without internet. Download copy exports
an unchanged file for transfer to another offline panel. File SHA-256 IDs deduplicate
packages; optional publisher checksums are checked during upload and stored file hashes
are rechecked before installation. Uploads stream to temporary files with a 16 GiB limit,
free-space check and atomic publication. No remote update feed is configured or scraped.

APK metadata needs Android SDK `aapt2` (auto-discovered, or config `aapt`). Android's
`adb install -r` preserves app data and enforces its normal signature/version rules;
this panel does not force downgrades, uninstall first, bypass signatures or support
split APK bundles. Jobs verify the installed versionCode after installation.

Firmware must contain standard Android OTA metadata and payload. **Check firmware
compatibility** reads the selected physical USB Quest's model, current build/fingerprint,
build timestamp and battery before allowing a newer compatible package. Wipe/downgrade
packages are rejected. The preparation expires after 30 minutes and is not carried
across a panel restart. Then manually enter the headset's Sideload update mode and
explicitly install to the same ADB serial. The panel never automatically reboots,
flashes partitions, unlocks a bootloader or wipes data. If recovery exposes a different
serial, installation is blocked: use Meta's official tool instead of guessing identity.
Recovery must verify the vendor signature; a checksum/metadata check alone does not
prove Meta provenance. Obtain packages from an authorized, trusted source.

Firmware jobs remain **awaiting verification** after ADB transfer. Boot normally,
reconnect ADB and choose Verify installed version to check the target build. Interrupted
jobs remain unknown after restart. Close without verification explicitly records that
outcome and permits a new attempt; it never stops an active flash. Check the headset
before retrying. No real firmware was flashed during feature development; recovery
installation acceptance requires a compatible official package and a controlled test.

References: [Android ADB install](https://developer.android.com/tools/adb),
[Android OTA preconditions](https://source.android.com/docs/core/ota/tools),
[Meta software update tool](https://www.meta.com/help/quest/software_update/) (WebUSB: Chrome, Edge or another Chromium browser; not Firefox or Safari).

### XR Downloader bundles

Software updates → Create a download list offers a friendly app picker, including
installed headset apps (`Name (package)`). Selecting an app exports its identity in
`xr-download-request-v1` JSON without requiring internet, a URL or a checksum on the
offline system. XR Downloader finds supported publisher releases on the online PC,
obtains the release checksum and verifies the download. Its initial publisher catalog
covers ALVR and ALVR for Monado; the Monado fork currently has no published release.
Unmapped/store-only apps and missing releases produce a clear error rather than a
partial bundle or a similarly named substitute. Additional publishers need catalog
support. Advanced custom/firmware entries retain pinned URL/SHA-256 support; existing
`xr-offline-updates-v1` lists remain compatible.

Get XR Downloader downloads a standalone Linux/Windows ZIP. Its source is the sibling
`addons/xr-downloader`; it uses Python 3.11+ and no panel or third-party libraries.
Run it on any online computer with the exported JSON to generate a complete tar.gz
using gzip level 9. Import offline bundle accepts the archive on an offline panel,
validates all paths, file sizes, SHA-256 values and actual APK/OTA metadata, then
publishes all files and their download definitions. Unexpected entries, links,
traversal, missing files and tampered payloads reject the whole import. See the
Downloader README for the format and Linux/Windows commands. Native Windows runtime
acceptance remains pending; Linux download → disconnected import has been tested.

### Pulling updates from another panel

Software updates → *Other XR Control Panels* copies stored updates between panels on the network,
for example from a panel on a PC that has internet access to an offline one.

- On the panel that has the updates: *Let other panels pull from this one* → name the other panel →
  **Create share key**. The key is shown once; only its hash is stored, and **Revoke** ends that
  panel's access. The section also shows this panel's HTTPS address(es) and certificate fingerprint.
- On the panel that wants them: enter that address and the share key → **Add panel**. It pins the
  other panel's certificate fingerprint (compare it with the one shown there); later connections
  with a different certificate are refused before the key is sent. **Show its updates** lists them,
  **Pull** copies one in the background.
- A share key can only list stored updates and download them (`GET /api/share/updates`,
  `GET /api/share/updates/<sha256>/download`), only over HTTPS (Wi-Fi access must be on). Pulled
  files are checked against their SHA-256 and inspected exactly like a manual upload.
- Share keys: `~/.config/xr-control-panel/update-share-keys.json`; known panels (with their keys):
  `update-peers.json` (both 0600).

### Captures and settings defaults

Captures → Export file downloads one original screenshot/recording. Export selected
captures downloads a maximum-compression tar.gz of only the checked files (up to
200 files; nothing is selected by default), with metadata and originals grouped by headset. Exports never delete
captures. File transfer is streamed rather than loading recordings into memory.

Settings shows the committed default for the selected editable runtime setting.
Restore selected to default restores one key; Restore All to Default restores all
editable runtime keys after confirmation. Defaults come from the runtime checkout's
committed `HEAD:config/xr-build.json`, not the current edited file. Unrelated config
keys, pairings, captures, update packages and Loft shortcuts are preserved. Existing
workstation overrides/environment settings can still take precedence in the runtime.
No runtime restart or rebuild is triggered automatically.

### Voice screen analysis and return-to-headset review

GPU Worker → Ask by voice about my current screen supports tap-to-speak, typed
requests and basic dog/ball/chair/glass-cup examples. Choose a connected headset and
an actual image-analysis workflow accepting one reference image and returning an
annotated image. The request captures that headset's current screenshot, submits it
with the spoken instruction, polls the durable job, copies resulting images back to
that same headset's Pictures directory, and opens a review page there through ADB.
Unavailable workflows are rejected before capture. Failed delivery can be retried.

This is a browser voice interface, not an always-listening native Loft voice agent.
Browser speech recognition must be supported and requires a secure context (USB
Open panel in headset uses localhost; unencrypted LAN pages may not allow speech).
Depending on the browser, recognition may use an internet service. A typed fallback
remains available. Capture includes only what Quest screenshots expose; this does
not add a passthrough camera permission or physical-world camera feed.

Current deployment has no GPU-worker connection key configured. The routing,
selected-headset delivery and simulated speech tests pass, but real model detection,
Quest microphone support and in-headset review need provider/device acceptance.
Do not substitute a generative image workflow and claim verified object detection.
See [browser speech support](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition).

Quest microphone check: GPU Worker includes a 12-second Test Quest microphone meter.
It requests browser/Android permission independently of speech or GPU setup. Samples
are analyzed locally without recording or upload. Stop, page hide, permission denial,
and late permission grants release input tracks. Input signal is not proof of speech
recognition or model detection. If access is denied, grant Meta Quest Browser and the
site microphone permission; use USB localhost or HTTPS for a secure browser context.

## USB once, then Wi-Fi (automatic)

A Quest connected by USB (debugging allowed, ALVR client installed) is authorized for Wi-Fi
automatically, re-checked every 30 s while it stays on USB:

- **Streaming** (`auto_trust_usb_streaming`, default on; works with or without panel Wi-Fi access):
  it is added to **Approved devices** (factory Wi-Fi MAC as identity, plus the randomized MAC the
  network sees, serial, model, Wi-Fi IP) and ALVR trusts a client entry `usb-<serial>` whose manual
  IP is its current Wi-Fi IPv4 address, refreshed on every USB connection. Extra runtime instances
  pinned to that serial are updated through their own ALVR API.
- **Panel in the headset browser** (`auto_authorize_usb`, default on; needs Panel access / Wi-Fi
  access on): a one-time pairing page opens in the headset's browser (see the pairing section).

This does not enable wireless ADB. Remove a device from Approved devices and from the ALVR client
list (Streaming tab) to withdraw it.

## Voice requests with several headsets

Each headset's browser is identified automatically, so it captures and reviews only itself:
- **Over USB:** when the panel opens a headset's browser (Open panel in headset, result review) it
  adds a one-time `device=` link; the browser keeps it as a cookie (`device-identity.json` stores
  only hashes).
- **Over Wi-Fi:** the headset's USB pairing grant identifies it.

`GET /api/whoami` returns the headset (or `operator` for this PC's browser). A headset's browser
can only send voice/GPU requests for itself (others get 403) and only sees its own jobs, result
images and review pages; the PC's browser sees all and can target any headset. Capturing the view
needs the headset on USB (ADB screenshot); the result is delivered over USB when connected, and
otherwise waits in that headset's own panel page, which announces it.

## Speech recognition on the headset

**Speak a request** uses the browser's own speech recognition when it exists. Headset browsers
often lack it (or it needs a cloud service); then the page records up to 8 s (Stop listening ends
early) and the panel transcribes it on this PC with whisper.cpp (`POST /api/voice/transcribe`,
`GET /api/voice/status`). Audio is kept only in memory/temporary files for the transcription,
never stored or uploaded; silent clips are refused (Whisper invents words for silence).

Setup (done on this PC): `build/whisper.cpp` (`cmake --build build --target whisper-cli`) and
`models/whisper/ggml-base.en.bin` (sha256 a03779c8...), both under the runtime root; override
with `whisper_cli` / `whisper_model` in the panel config. The microphone needs a secure page: over
USB (`http://127.0.0.1`) it works; over plain Wi-Fi HTTP the browser blocks it.
