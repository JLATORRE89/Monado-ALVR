#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
S="$ROOT/src/Monado-ALVR/scripts"; QUEST_IP="${QUEST_IP:-192.168.86.168}"
SERVICE="$ROOT/build/monado-alvr/src/xrt/targets/service/monado-service"
source "$S/xr-log.sh"; xr_init_log "xr-session"
step(){ printf '[%-24s] %s\n' "$1" "$2"; }
fail(){ step "$1" "FAIL"; echo "ERROR: $2"; exit 1; }
echo "Intel XR | Quest $QUEST_IP | Log: $XR_SESSION_LOG"
[[ -x "$SERVICE" ]] || fail Build "monado-service missing; run build-intel-xr.sh"

if bash "$S/monado-service.sh" ensure >/dev/null 2>&1; then step Runtime OK; else bash "$S/monado-service.sh" ensure; fail Runtime "Monado/API unavailable"; fi
MONADO_PID="$(systemctl --user show -p MainPID --value intel-xr-monado.service)"

if ping -c 1 -W 2 "$QUEST_IP" >/dev/null 2>&1; then TRANSPORT=wifi; step Network "OK (Wi-Fi)"; else
  step Network "Quest IP unreachable"
  if [[ -t 0 ]]; then read -r -p "Configure workstation Wi-Fi now? [Y/n] " a; case "${a:-Y}" in [Yy]*|"") bash "$S/connect-xr-wifi.sh";; esac; fi
  if ping -c 1 -W 2 "$QUEST_IP" >/dev/null 2>&1; then TRANSPORT=wifi; step Network "OK (Wi-Fi)"; else TRANSPORT=usb; step Network "USB fallback"; fi
fi

if [[ "$TRANSPORT" == usb ]]; then
  bash "$S/setup-usb-alvr.sh" >/dev/null || { bash "$S/setup-usb-alvr.sh"; fail Transport "USB setup failed"; }
else
  adb forward --remove tcp:9943 2>/dev/null || true; adb forward --remove tcp:9944 2>/dev/null || true
fi
step Transport OK

if bash "$S/xr-client-ui.sh" ensure >/dev/null 2>&1; then step "Client UI" "OK :8083"; else step "Client UI" WARN; fi
adb start-server >/dev/null 2>&1 || true
adb shell pidof alvr.client.stable >/dev/null 2>&1 || adb shell monkey -p alvr.client.stable -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
sleep 2

if [[ "$TRANSPORT" == wifi ]]; then
  WIFI_DEV="$(ip route get "$QUEST_IP" 2>/dev/null | awk '{for(i=1;i<=NF;i++)if($i=="dev"){print $(i+1);exit}}')"
  command -v tcpdump >/dev/null 2>&1 || fail Discovery "tcpdump missing"
  sudo -n true 2>/dev/null || fail Discovery "run 'sudo true' once, then rerun"
  PACKETS="$(timeout 6 sudo -n tcpdump -qn -c 1 -i "${WIFI_DEV:-any}" "host $QUEST_IP and (udp port 9943 or tcp port 9943)" 2>&1 || true)"
  grep -q "$QUEST_IP" <<<"$PACKETS" || fail Discovery "no Quest ALVR traffic detected; keep ALVR foregrounded"
fi
step Discovery OK

TRUSTED=0
for i in 1 2 3; do
  if QUEST_IP="$QUEST_IP" bash "$S/trust-alvr-client.sh" >/dev/null 2>&1; then TRUSTED=1; break; fi
  sleep 1
done
[[ "$TRUSTED" -eq 1 ]] || { QUEST_IP="$QUEST_IP" bash "$S/trust-alvr-client.sh" || true; fail Trust "client not identified after 3 attempts"; }
step Trust OK
sleep 3

REG="$(curl -fsS -H 'X-ALVR: 1' http://127.0.0.1:8082/api/xr/clients 2>/dev/null || true)"
STATE="$(python3 -c 'import json,sys; j=json.load(sys.stdin); cs=j.get("clients",{}); print(next(iter(cs.values()),{}).get("connection_state","Unknown"))' <<<"$REG" 2>/dev/null || echo Unknown)"
step Handshake "$STATE"

if [[ "$STATE" != "Streaming" && "$STATE" != "Connected" ]]; then
  echo
  echo "=== Handshake diagnostics (shown because connection is not healthy) ==="
  echo "-- Client registry --"; printf '%s\n' "$REG" | python3 -m json.tool 2>/dev/null || printf '%s\n' "$REG"
  echo "-- Server --"; journalctl --user -u intel-xr-monado.service --since "-45 seconds" --no-pager 2>/dev/null | grep -Ei 'alvr|legacy|handshake|connect|protocol|socket|error|warn' | tail -80 || true
  echo "-- Quest --"; adb logcat -d -v time 2>/dev/null | grep -Ei '\[ALVR NATIVE-RUST\].*(error|connect|protocol|socket)|os error' | tail -40 || true
else
  step Session READY
fi
echo "Monado PID: $MONADO_PID"
