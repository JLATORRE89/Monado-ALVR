#!/usr/bin/env bash
# Remove the XR Control Panel add-on. The Intel XR runtime is not affected.
#
#   bash uninstall.sh [--purge] [--prefix DIR] [--keep-firewall]
#
# Stops and removes the service and the installed app, and deletes the firewall rules the panel
# added (only rules commented "XR Control Panel (LAN)"; see firewall.sh). --keep-firewall leaves them.
# --purge also deletes the panel config (~/.config/xr-control-panel) and stored captures
# (~/.local/share/xr-control-panel/captures). The approved-device registry
# (~/.config/intel-xr/approved-devices.json) is always kept.
set -Eeuo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="$HOME/.local/share/xr-control-panel/app"
PURGE=0
FIREWALL=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge) PURGE=1; shift ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --keep-firewall) FIREWALL=0; shift ;;
    -h|--help) sed -n 2,10p "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

# Only ever delete a panel installation: an existing folder holding the panel's server, never / or home.
PREFIX="$(realpath -m -- "$PREFIX")"
if [[ -e "$PREFIX" ]]; then
  if [[ "$PREFIX" == "/" || "$PREFIX" == "$(realpath -m -- "$HOME")" || ! -f "$PREFIX/server.py" ||
        ( ! -f "$PREFIX/usb_pairing.py" && ! -f "$PREFIX/tablet_client.py" ) ]]; then
    echo "ERROR: $PREFIX does not look like an XR Control Panel installation; not deleting it." >&2
    exit 1
  fi
fi

systemctl --user disable --now xr-control-panel.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/xr-control-panel.service"
systemctl --user daemon-reload

if [[ $FIREWALL == 1 ]]; then
  bash "$SRC/firewall.sh" remove || echo "WARNING: firewall rules not removed; see: sudo ufw status"
fi

[[ -e "$PREFIX" ]] && rm -rf -- "$PREFIX"
echo "XR Control Panel removed."

if [[ $PURGE == 1 ]]; then
  rm -rf -- "$HOME/.config/xr-control-panel" "$HOME/.local/share/xr-control-panel"
  echo "Config and captures deleted."
else
  echo "Kept config (~/.config/xr-control-panel) and captures (~/.local/share/xr-control-panel/captures)."
fi
