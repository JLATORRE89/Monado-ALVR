#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
LOGDIR="$ROOT/logs"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/$(date +%Y-%m-%d_%H-%M-%S)_trust-alvr-client.log"
QUEST_IP="${QUEST_IP:-192.168.86.168}"
API="${ALVR_API:-http://127.0.0.1:8082}"
exec > >(tee "$LOG") 2>&1

echo "=== Trust ALVR client ==="
echo "API: $API"

SESSION="$(curl -fsS -H 'X-ALVR: 1' "$API/api/session/" || true)"
if [[ -z "$SESSION" ]]; then
  echo "ERROR: ALVR server API is not reachable."
  exit 1
fi
echo "$SESSION" > "$LOGDIR/.last-alvr-session.json"

HOST="$(python3 - "$LOGDIR/.last-alvr-session.json" "$QUEST_IP" <<'PY'
import json,sys
j=json.load(open(sys.argv[1]))
ip=sys.argv[2]
clients=j.get("client_connections",{})
# Prefer discovered current IP, then a sole untrusted client, then wired identity.
for h,c in clients.items():
    if c.get("current_ip")==ip:
        print(h); raise SystemExit
u=[h for h,c in clients.items() if not c.get("trusted",False)]
if len(u)==1:
    print(u[0]); raise SystemExit
if "client.wired" in clients:
    print("client.wired"); raise SystemExit
PY
)"
if [[ -z "$HOST" ]]; then
  echo "ERROR: could not identify discovered Quest client."
  echo "Session saved to $LOGDIR/.last-alvr-session.json"
  exit 1
fi

echo "Client hostname: $HOST"
echo "Quest IP: $QUEST_IP"
PAYLOAD="$(python3 - "$HOST" <<'PY'
import json,sys
print(json.dumps([sys.argv[1],"Trust"]))
PY
)"
curl -fsS -X POST -H 'X-ALVR: 1' -H 'Content-Type: application/json'   --data "$PAYLOAD" "$API/api/session/client-connections"
echo
echo "Trust request sent."
sleep 2
curl -fsS -H 'X-ALVR: 1' "$API/api/session/" | python3 -m json.tool | sed -n "/$HOST/,+12p" || true
