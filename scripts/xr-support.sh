#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
S="$ROOT/src/Monado-ALVR/scripts"; QUEST_IP="${QUEST_IP:-192.168.86.168}"
SERVICE="$ROOT/build/monado-alvr/src/xrt/targets/service/monado-service"
CLIENT_PACKAGE="${XR_CLIENT_PACKAGE:-}"
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
if [[ -z "$CLIENT_PACKAGE" ]]; then
  if adb shell pm path alvr.client.monado >/dev/null 2>&1; then CLIENT_PACKAGE=alvr.client.monado
  elif adb shell pm path alvr.client.stable >/dev/null 2>&1; then CLIENT_PACKAGE=alvr.client.stable
  else fail Client "no ALVR client package installed"; fi
fi
CLIENT_VERSION="$(adb shell dumpsys package "$CLIENT_PACKAGE" 2>/dev/null | sed -n 's/.*versionName=//p' | head -1 | tr -d '\r')"
step Client "$CLIENT_PACKAGE ${CLIENT_VERSION:-unknown}"
adb shell pidof "$CLIENT_PACKAGE" >/dev/null 2>&1 || adb shell monkey -p "$CLIENT_PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
sleep 2

if [[ "$TRANSPORT" == wifi ]]; then
  WIFI_DEV="$(ip route get "$QUEST_IP" 2>/dev/null | awk '{for(i=1;i<=NF;i++)if($i=="dev"){print $(i+1);exit}}')"
  command -v tcpdump >/dev/null 2>&1 || fail Discovery "tcpdump missing"
  sudo -n true 2>/dev/null || fail Discovery "run 'sudo true' once, then rerun"
  # Current ALVR discovers over mDNS/5353; legacy clients use UDP/TCP 9943.
  # Do not require the destination/source host to be the Quest because mDNS is multicast.
  PACKETS="$(timeout 6 sudo -n tcpdump -qn -c 1 -i "${WIFI_DEV:-any}" "(udp port 5353 or udp port 9943 or tcp port 9943)" 2>&1 || true)"
  if grep -qE '5353|9943' <<<"$PACKETS"; then
    :
  elif [[ "$CLIENT_PACKAGE" == "alvr.client.monado" ]] && ss -unap 2>/dev/null | grep -q ':5353'; then
    step Discovery "mDNS active"
  else
    fail Discovery "no ALVR mDNS/legacy discovery traffic detected; keep ALVR foregrounded"
  fi
fi
step Discovery OK

# Do not let a stale legacy registry entry masquerade as the currently running
# protocol-matched client. Current clients must appear through current discovery.
if [[ "$CLIENT_PACKAGE" == "alvr.client.monado" ]]; then
  STALE="$(curl -fsS -H 'X-ALVR: 1' http://127.0.0.1:8082/api/xr/clients 2>/dev/null || true)"
  if python3 -c 'import json,sys; j=json.load(sys.stdin); raise SystemExit(0 if any(k.startswith("legacy-") for k in j.get("clients",{})) else 1)' <<<"$STALE" 2>/dev/null; then
    step Registry "ignoring stale legacy entry"
  fi
fi

TRUSTED=0
for i in 1 2 3; do
  if XR_CLIENT_PACKAGE="$CLIENT_PACKAGE" QUEST_IP="$QUEST_IP" bash "$S/trust-alvr-client.sh" >/dev/null 2>&1; then TRUSTED=1; break; fi
  sleep 1
done
[[ "$TRUSTED" -eq 1 ]] || { XR_CLIENT_PACKAGE="$CLIENT_PACKAGE" QUEST_IP="$QUEST_IP" bash "$S/trust-alvr-client.sh" || true; fail Trust "current client not identified after 3 attempts"; }
step Trust OK

# The registry can contain stale mDNS/legacy entries. Poll the identity matching
# this Quest instead of sampling the first dictionary item.
STATE=Unknown
for _ in $(seq 1 12); do
  REG="$(curl -fsS -H 'X-ALVR: 1' http://127.0.0.1:8082/api/xr/clients 2>/dev/null || true)"
  STATE="$(python3 -c 'import json,sys
j=json.load(sys.stdin); ip=sys.argv[1]; cs=j.get("clients",{})
match=None
for name,c in cs.items():
    if c.get("current_ip")==ip or name=="direct-"+ip:
        match=c; break
print((match or {}).get("connection_state","Unknown"))
' "$QUEST_IP" <<<"$REG" 2>/dev/null || echo Unknown)"
  [[ "$STATE" == "Streaming" || "$STATE" == "Connected" ]] && break
  sleep 1
done
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
