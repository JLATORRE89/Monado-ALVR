#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
UNIT_SRC="$ROOT/src/Monado-ALVR/systemd/intel-xr-client-ui.service"
UNIT="$HOME/.config/systemd/user/intel-xr-client-ui.service"
case "${1:-ensure}" in
 install|ensure)
  mkdir -p "$(dirname "$UNIT")"; cp "$UNIT_SRC" "$UNIT"; systemctl --user daemon-reload
  systemctl --user enable --now intel-xr-client-ui.service
  systemctl --user --no-pager status intel-xr-client-ui.service || true
  echo "Client UI: http://127.0.0.1:8083/"
  ;;
 start) systemctl --user start intel-xr-client-ui.service;;
 stop) systemctl --user stop intel-xr-client-ui.service;;
 restart) systemctl --user restart intel-xr-client-ui.service;;
 status) systemctl --user --no-pager status intel-xr-client-ui.service || true;;
 *) echo "Usage: $0 {install|ensure|start|stop|restart|status}"; exit 2;;
esac
