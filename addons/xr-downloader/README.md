# XR Downloader

Standalone offline-update packager for Linux and Windows. XR Control Panel does not
need to be installed or running. Requires Python 3.11 or newer; no third-party Python
packages, administrator rights or ADB are required.

1. In XR Control Panel → Software updates → Supported downloads, configure direct
   download URLs and trusted SHA-256 checksums, then export `xr-downloads.json`.
2. Take the JSON file and this folder to a Linux or Windows computer with internet.
3. Run one command:

   Linux: `python3 xr_downloader.py xr-downloads.json --output xr-offline-updates.tar.gz`

   Windows: `py -3 xr_downloader.py xr-downloads.json --output xr-offline-updates.tar.gz`

   The included `xr-downloader.sh` and `xr-downloader.cmd` launchers accept the same
   arguments. Quote paths containing spaces.
4. Copy the completed tar.gz to the offline computer. In XR Control Panel → Software
   updates → Import offline bundle, choose it. Import verifies every file before
   publishing the updates. Then select the headset and install a stored update.

The archive uses maximum gzip compression (level 9), includes `manifest.json` and
all files, and needs no internet during panel import or installation. APK and OTA
ZIP files are usually already compressed; level 9 may save little additional space.
Every file must pass its expected SHA-256 and optional size check. Failed or interrupted
downloads do not produce a completed bundle. Existing output files are never overwritten.
Rerun failed jobs; partial downloads are not resumed. Allow space for downloaded files
plus their final archive (up to approximately twice the download size). Limits: 128
files, 16 GiB per file, 64 GiB total. The panel must have Android SDK aapt2 to inspect
APKs on import; that tool is not needed by XR Downloader.

This downloads configured URLs, not app-store accounts or dynamically discovered latest
releases. Update each definition's URL/version/checksum when approving a new release.
Use stable direct file URLs, not sign-in pages. Credentials embedded in URLs and HTTPS
redirects to HTTP are rejected. Keep private signed URLs private if used in the JSON.
Checksums verify file identity, not publisher trust; obtain them from a trusted source.
Firmware still needs a compatible, vendor-signed package and the headset's recovery
workflow. XR Downloader never installs anything or changes a headset.

## JSON format

```json
{
  "schema": "xr-offline-updates-v1",
  "applications": [
    {
      "name": "My Quest App",
      "kind": "apk",
      "version": "1.2.3",
      "url": "https://your-download-host.example/releases/app.apk",
      "sha256": "replace-with-the-actual-64-character-lowercase-sha256"
    }
  ]
}
```

`kind` is `apk` or `firmware`. Optional `size` is the exact byte count. For APKs,
optional `package` and numeric `version_code` are checked during panel import.
`version` is a display label; actual APK/firmware version metadata is read by the panel.
The same JSON contract works on both supported operating systems. Linux execution
is tested in this project; native Windows execution still needs a Windows acceptance run.
