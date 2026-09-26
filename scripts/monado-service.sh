#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
UNIT_SRC="$ROOT/src/Monado-ALVR/systemd/intel-xr-monado.service"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/intel-xr-monado.service"
LOGDIR="$ROOT/logs"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/$(date +%Y-%m-%d_%H-%M-%S)_monado-service-manager.log"
exec > >(tee "$LOG") 2>&1
ACTION="${1:-status}"

install_unit() {
  mkdir -p "$UNIT_DIR"
  cp "$UNIT_SRC" "$UNIT"
  systemctl --user daemon-reload
  systemctl --user enable intel-xr-monado.service
}
api_wait() {
  for _ in $(seq 1 20); do
    curl -fsS -H 'X-ALVR: 1' http://127.0.0.1:8082/api/ping >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}
case "$ACTION" in
 install) install_unit ;;
 start) install_unit; systemctl --user start intel-xr-monado.service ;;
 restart) install_unit; systemctl --user restart intel-xr-monado.service ;;
 stop) systemctl --user stop intel-xr-monado.service ;;
 enable) install_unit ;;
 disable) systemctl --user disable --now intel-xr-monado.service ;;
 status) systemctl --user --no-pager --full status intel-xr-monado.service || true ;;
 ensure)
   install_unit
   systemctl --user is-active --quiet intel-xr-monado.service || systemctl --user start intel-xr-monado.service
   if api_wait; then echo "PASS: Monado service active and ALVR API ready on 127.0.0.1:8082"; else
     echo "ERROR: service/API not ready"
     systemctl --user --no-pager --full status intel-xr-monado.service || true
     journalctl --user -u intel-xr-monado.service -n 100 --no-pager || true
     exit 1
   fi
   ;;
 logs) journalctl --user -u intel-xr-monado.service -n "${2:-200}" --no-pager ;;
 *) echo "Usage: $0 {install|start|restart|stop|enable|disable|status|ensure|logs}"; exit 2 ;;
esac
