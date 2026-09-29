#!/usr/bin/env bash
# Firewall (ufw) rules that let browsers on this PC's local networks (a tablet or headset on Wi-Fi)
# reach the XR Control Panel. Used by install.sh and uninstall.sh; safe to run again.
#
#   bash firewall.sh allow  [--config FILE] [--subnet CIDR]...   add the rules (existing ones are skipped)
#   bash firewall.sh remove                                       delete the rules this panel added
#   bash firewall.sh show   [--config FILE] [--subnet CIDR]...   print the rules, change nothing
#
# One rule per local network:
#   ufw allow from <subnet> to any port <port>,<https_port> proto tcp comment 'XR Control Panel (LAN)'
# Ports come from the panel config ("port", default 8083; "https_port", default 8483). Subnets are the
# private (RFC 1918) IPv4 networks of this PC's interfaces (not loopback, containers, VMs or VPNs) unless given
# with --subnet. "remove" deletes only IPv4 TCP allow rules whose comment is exactly that text, each
# by its full rule (never by number), so no other rule can be hit. Only ufw is handled. Needs sudo:
# asks for the password in a terminal, otherwise prints the commands to run.
set -Eeuo pipefail

COMMENT="XR Control Panel (LAN)"
ACTION="${1:-}"
[[ $# -gt 0 ]] && shift
CONFIG="$HOME/.config/xr-control-panel/config.json"
SUBNETS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --subnet) SUBNETS+=("$2"); shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

ports() {
  python3 - "$CONFIG" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
cfg = json.loads(p.read_text()) if p.is_file() else {}
print(f'{int(cfg.get("port") or 8083)},{int(cfg.get("https_port") or 8483)}')
PY
}

local_subnets() {
  ip -4 -j addr show scope global 2>/dev/null | python3 -c '
import ipaddress, json, re, sys
LAN = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")  # RFC 1918 home/office networks only
skip = re.compile(r"^(lo|docker|br-|virbr|veth|vnet|tun|tap|wg|tailscale|zt|lxc|cni|flannel|podman)")
seen = []
for link in json.load(sys.stdin):
    if skip.match(link.get("ifname", "")) or "UP" not in link.get("flags", []):
        continue
    for a in link.get("addr_info", []):
        net = ipaddress.ip_interface("%s/%s" % (a["local"], a["prefixlen"])).network
        if any(net.subnet_of(ipaddress.ip_network(r)) for r in LAN) and str(net) not in seen:
            seen.append(str(net))
print("\n".join(seen))'
}

valid_subnet() {
  python3 -c 'import ipaddress, sys; ipaddress.IPv4Network(sys.argv[1])' "$1" 2>/dev/null
}

# Runs a command as root: sudo without a prompt, else with one in a terminal; fails if neither works.
as_root() {
  if sudo -n true 2>/dev/null || [[ -t 0 ]]; then sudo "$@"; else return 1; fi
}

# 0: ufw active and usable; 1: nothing to do (no ufw / inactive); 2: needs sudo the user must run.
ufw_state() {
  command -v ufw >/dev/null || { echo "Firewall: ufw is not installed; nothing to change."; return 1; }
  local status
  if ! status="$(as_root ufw status 2>/dev/null)"; then return 2; fi
  if [[ "$status" != *"Status: active"* ]]; then
    echo "Firewall: ufw is not active; nothing to change."
    return 1
  fi
}

# The allow rules as ufw arguments (without the comment), one rule per line.
rules() {
  local p net
  p="$(ports)"
  if [[ ${#SUBNETS[@]} -eq 0 ]]; then mapfile -t SUBNETS < <(local_subnets); fi
  for net in "${SUBNETS[@]}"; do
    [[ -n "$net" ]] || continue
    valid_subnet "$net" || { echo "Firewall: skipping invalid subnet $net" >&2; continue; }
    printf '%s\n' "allow from $net to any port $p proto tcp"
  done
}

# Our rules as ufw shows them: "<ports>/tcp  ALLOW [IN]  <source>  # XR Control Panel (LAN)" (IPv4 only),
# printed as "<source> <ports>".
our_rules() {
  as_root ufw status | python3 -c '
import ipaddress, re, sys
comment = sys.argv[1]
for line in sys.stdin:
    m = re.fullmatch(r"([0-9]+(?:[,:][0-9]+)*)/tcp\s+ALLOW(?: IN)?\s+(\S+)\s+#\s(.*?)\s*", line.rstrip("\n"))
    if not m or m.group(3) != comment:
        continue
    try:
        src = ipaddress.IPv4Network(m.group(2))
    except ValueError:
        continue  # an IPv6 or "Anywhere" rule: never ours
    print(src, m.group(1))' "$COMMENT"
}

case "$ACTION" in
  show)
    while read -r r; do printf 'sudo ufw %s comment %q\n' "$r" "$COMMENT"; done < <(rules) ;;
  allow)
    mapfile -t RULES < <(rules)
    if [[ ${#RULES[@]} -eq 0 ]]; then echo "Firewall: no local network found; nothing to allow."; exit 0; fi
    rc=0; ufw_state || rc=$?
    if [[ $rc == 1 ]]; then exit 0; fi
    if [[ $rc == 2 ]]; then
      echo "Firewall: needs sudo. To let Wi-Fi devices reach the panel, run:"
      for r in "${RULES[@]}"; do printf '  sudo ufw %s comment %q\n' "$r" "$COMMENT"; done
      exit 0
    fi
    for r in "${RULES[@]}"; do
      read -ra args <<<"$r"
      as_root ufw "${args[@]}" comment "$COMMENT" | sed 's/^/Firewall: /'  # "Rule added" / "Skipping adding existing rule"
    done ;;
  remove)
    rc=0; ufw_state || rc=$?
    if [[ $rc == 1 ]]; then exit 0; fi
    if [[ $rc == 2 ]]; then
      echo "Firewall: needs sudo. To remove the panel's rules, delete each \"$COMMENT\" rule shown by:"
      echo "  sudo ufw status"
      echo "with: sudo ufw delete allow from <source> to any port <ports> proto tcp"
      exit 0
    fi
    n=0
    while read -r src p; do
      as_root ufw delete allow from "$src" to any port "$p" proto tcp >/dev/null &&
        echo "Firewall: removed allow from $src to port $p ($COMMENT)" && n=$((n + 1))
    done < <(our_rules)
    [[ $n -gt 0 ]] || echo "Firewall: no \"$COMMENT\" rules found." ;;
  *)
    sed -n 2,9p "$0"; exit 2 ;;
esac
