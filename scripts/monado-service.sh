#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
UNIT_SRC="$ROOT/src/Monado-ALVR/systemd/intel-xr-monado.service"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/intel-xr-monado.service"
LOGDIR="$ROOT/logs"
source "$ROOT/src/Monado-ALVR/scripts/xr-log.sh"
xr_init_log "$(basename "$0" .sh)"
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
   if api_wait; then
     echo "ALVR API is ready; verifying 15-second startup stability..."
     sleep 15
     if systemctl --user is-active --quiet intel-xr-monado.service && \
        curl -fsS -H 'X-ALVR: 1' http://127.0.0.1:8082/api/ping >/dev/null 2>&1; then
       echo "PASS: Monado survived stabilization and ALVR API remains ready on 127.0.0.1:8082"
     else
       echo "ERROR: Monado/API failed during the 15-second stabilization window"
       systemctl --user --no-pager --full status intel-xr-monado.service || true
       journalctl --user -u intel-xr-monado.service -n 100 --no-pager || true
       exit 1
     fi
   else
     echo "ERROR: service/API not ready"
     systemctl --user --no-pager --full status intel-xr-monado.service || true
     journalctl --user -u intel-xr-monado.service -n 100 --no-pager || true
     exit 1
   fi
   ;;
 logs) journalctl --user -u intel-xr-monado.service -n "${2:-200}" --no-pager ;;
 crash)
   systemctl --user stop intel-xr-monado.service 2>/dev/null || true
   CRASH_LOG="$LOGDIR/$(date +%Y-%m-%d_%H-%M-%S)_monado-crash-debug.log"
   echo "Collecting Monado crash diagnostics: $CRASH_LOG"
   {
     echo "=== systemd status ==="
     systemctl --user --no-pager --full status intel-xr-monado.service || true
     echo
     echo "=== recent journal ==="
     journalctl --user -u intel-xr-monado.service -n 200 --no-pager || true
     echo
     echo "=== coredump inventory ==="
     coredumpctl list 2>/dev/null | grep -i monado || true
   } | tee "$CRASH_LOG"
   if coredumpctl info monado-service >/dev/null 2>&1; then
     echo >>"$CRASH_LOG"; echo "=== coredump backtrace ===" | tee -a "$CRASH_LOG"
     coredumpctl debug monado-service --debugger-arguments="-batch -ex 'thread apply all bt 20'" 2>&1 | tee -a "$CRASH_LOG"
   else
     echo >>"$CRASH_LOG"
     echo "No retained systemd coredump. Running one controlled GDB reproduction." | tee -a "$CRASH_LOG"
     systemctl --user stop intel-xr-monado.service 2>/dev/null || true
     gdb -q -batch \
       -ex "set pagination off" \
       -ex "set environment XRT_LOG debug" \
       -ex run \
       -ex "thread apply all bt 20" \
       --args "$ROOT/build/monado-alvr/src/xrt/targets/service/monado-service" \
       2>&1 | tee -a "$CRASH_LOG"
   fi
   echo "Crash log: $CRASH_LOG"
   ;;
 *) echo "Usage: $0 {install|start|restart|stop|enable|disable|status|ensure|logs|crash}"; exit 2 ;;
esac
