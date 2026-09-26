#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
source "$ROOT/src/Monado-ALVR/scripts/xr-log.sh"
xr_init_log "$(basename "$0" .sh)"
QUEST_IP="${QUEST_IP:-192.168.86.168}"
API="${ALVR_API:-http://127.0.0.1:8082}"

echo "=== Trust ALVR client ==="
curl -fsS -H 'X-ALVR: 1' "$API/api/ping" >/dev/null || { echo "ERROR: ALVR API ping failed."; exit 1; }

REG="$(curl -fsS -H 'X-ALVR: 1' "$API/api/xr/clients" || true)"
[[ -n "$REG" ]] || { echo "ERROR: enhanced client registry unavailable."; exit 1; }
HOST="$(python3 -c 'import json,sys
j=json.load(sys.stdin); ip=sys.argv[1]; cs=j.get("clients",{})
for h,c in cs.items():
    if c.get("current_ip")==ip or h=="legacy-"+ip or ip in [str(x) for x in c.get("manual_ips",[])]: print(h); break
' "$QUEST_IP" <<<"$REG")"
[[ -n "$HOST" ]] || { echo "ERROR: no registered ALVR candidate for Quest $QUEST_IP."; exit 1; }
echo "Registered candidate: $HOST"
PAYLOAD="$(python3 -c 'import json,sys; print(json.dumps([sys.argv[1],"Trust"]))' "$HOST")"
curl -fsS -X POST -H 'X-ALVR: 1' -H 'Content-Type: application/json' --data "$PAYLOAD" "$API/api/session/client-connections"
echo "Trust request sent for $HOST."
