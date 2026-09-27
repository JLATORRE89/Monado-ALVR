#!/usr/bin/env bash
# Remove the XR Control Panel add-on. The Intel XR runtime is not affected.
#
#   bash uninstall.sh [--purge] [--prefix DIR]
#
# --purge also deletes the panel config (~/.config/xr-control-panel) and stored captures
# (~/.local/share/xr-control-panel/captures). The approved-device registry
# (~/.config/intel-xr/approved-devices.json) is always kept.
set -Eeuo pipefail

PREFIX="$HOME/.local/share/xr-control-panel/app"
PURGE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge) PURGE=1; shift ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    -h|--help) sed -n 2,8p "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

systemctl --user disable --now xr-control-panel.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/xr-control-panel.service"
systemctl --user daemon-reload
rm -rf "$PREFIX"
echo "XR Control Panel removed."

if [[ $PURGE == 1 ]]; then
  rm -rf "$HOME/.config/xr-control-panel" "$HOME/.local/share/xr-control-panel"
  echo "Config and captures deleted."
else
  echo "Kept config (~/.config/xr-control-panel) and captures (~/.local/share/xr-control-panel/captures)."
fi
