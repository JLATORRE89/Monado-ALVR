#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
LOGDIR="$ROOT/logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/$(date +%Y-%m-%d_%H-%M-%S)_prepare-companions.log"
exec > >(tee "$LOG") 2>&1
ALVR="$ROOT/src/alvr-monado"
ALVR_RENDER="$ROOT/src/alvr_render"

# These are the current tips of the historical companion integration branches
# used by Monado-ALVR. Pinning makes workstation builds reproducible.
ALVR_REV="5d45a6dcd9a5ae3df7c60c6a1282fb52140346da"
ALVR_RENDER_REV="ecb281249b6900ec6ceb6e0570be5100533c706a"

for d in "$ALVR" "$ALVR_RENDER"; do
    [[ -d "$d/.git" ]] || { echo "ERROR: missing repository: $d"; exit 1; }
done

echo "=== Prepare companion sources ==="
git -C "$ALVR" fetch origin
git -C "$ALVR" checkout --detach "$ALVR_REV"
git -C "$ALVR" submodule sync --recursive
git -C "$ALVR" submodule update --init --recursive

echo "=== Apply XR multi-mode client compatibility ==="
python3 - "$ALVR/alvr/session/src/settings.rs" "$ALVR/alvr/server_core/src/web_server.rs" <<'PY'
from pathlib import Path
import sys
settings=Path(sys.argv[1]); s=settings.read_text()
s=s.replace('auto_trust_clients: cfg!(debug_assertions),','auto_trust_clients: true,')
settings.write_text(s)

web=Path(sys.argv[2]); w=web.read_text()
# Add a compact persistent-state endpoint for the local XR client manager.
needle='.route("/ping", routing::get(async || ())),'
repl='''.route("/ping", routing::get(async || ()))
                .route("/xr/clients", routing::get(get_xr_clients)),'''
if needle in w and 'get_xr_clients' not in w:
    w=w.replace(needle,repl,1)
    w += '''
async fn get_xr_clients() -> Json<serde_json::Value> {
    let session = SESSION_MANAGER.read();
    Json(serde_json::json!({
        "auto_accept": session.settings().connection.client_discovery
            .as_option().map(|c| c.auto_trust_clients).unwrap_or(false),
        "clients": session.client_list(),
    }))
}
'''
web.write_text(w)
PY

git -C "$ALVR_RENDER" fetch origin
git -C "$ALVR_RENDER" checkout --detach "$ALVR_RENDER_REV"
git -C "$ALVR_RENDER" reset --hard "$ALVR_RENDER_REV"

echo "=== Apply XR legacy discovery compatibility ==="
python3 - "$ALVR/alvr/server_core/src/sockets.rs" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
s=s.replace('use std::{collections::HashMap, net::IpAddr};','use std::{collections::HashMap, net::{IpAddr, Ipv4Addr, SocketAddr, UdpSocket}};')
s=s.replace('pub struct WelcomeSocket {\n    mdns_receiver: Receiver<ServiceEvent>,\n}','pub struct WelcomeSocket {\n    mdns_receiver: Receiver<ServiceEvent>,\n    legacy_socket: Option<UdpSocket>,\n}')
s=s.replace('        Ok(Self { mdns_receiver })','''        let legacy_socket = UdpSocket::bind(SocketAddr::new(Ipv4Addr::UNSPECIFIED.into(), 9943))
            .map(|socket| { socket.set_nonblocking(true).ok(); socket })
            .ok();
        Ok(Self { mdns_receiver, legacy_socket })''')
needle='''        Ok(clients)
    }
}'''
replacement='''        if let Some(socket) = &self.legacy_socket {
            let mut buf = [0u8; 2048];
            loop {
                match socket.recv_from(&mut buf) {
                    Ok((size, peer)) if size > 0 => {
                        clients.entry(format!("legacy-{}", peer.ip())).or_insert(peer.ip());
                    }
                    Ok(_) => (),
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => break,
                    Err(e) => { warn!("Legacy UDP discovery receive error: {e}"); break; }
                }
            }
        }
        Ok(clients)
    }
}'''
if 'clients.entry(format!("legacy-{}"' not in s:
    if needle not in s: raise SystemExit("legacy receive insertion point missing")
    s=s.replace(needle,replacement,1)
p.write_text(s)
PY

echo "=== Harden ALVR mDNS address selection ==="
python3 - "$ALVR/alvr/server_core/src/sockets.rs" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
old='''                        let address = *info.get_addresses().iter().next().to_any()?;'''
new='''                        let addresses = info.get_addresses();
                        let address = addresses
                            .iter()
                            .copied()
                            .find(IpAddr::is_ipv4)
                            .or_else(|| addresses.iter().copied().next())
                            .to_any()?;
                        warn!(
                            "ALVR mDNS resolved: hostname={}, addresses={:?}, selected={}",
                            hostname,
                            addresses,
                            address
                        );'''
if old in s:
    s=s.replace(old,new,1)
elif 'ALVR mDNS resolved:' not in s:
    raise SystemExit("mDNS address selection insertion point missing")
p.write_text(s)
PY

echo "=== Add current-client direct-IP fallback ==="
python3 - "$ALVR/alvr/server_core/src/sockets.rs" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
needle='''        Ok(clients)
    }
}'''
insert='''        // Current-client direct-IP fallback. This only substitutes discovery;
        // the normal trust and ALVR protocol handshake still run afterwards.
        if let Ok(ip) = std::env::var("ALVR_DIRECT_CLIENT_IP") {
            if let Ok(address) = ip.parse::<IpAddr>() {
                clients.entry(format!("direct-{address}")).or_insert(address);
            }
        }

        Ok(clients)
    }
}'''
if 'ALVR_DIRECT_CLIENT_IP' not in s:
    if needle not in s: raise SystemExit("direct-IP insertion point missing")
    s=s.replace(needle,insert,1)
p.write_text(s)
PY

echo "=== Enable TEST-ONLY legacy ALVR protocol compatibility ==="
python3 - "$ALVR/alvr/server_core/src/connection.rs" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
old='''            if info.client_protocol_id != alvr_common::protocol_id_u64() {
                warn!(
                    "Trusted client is incompatible! Expected protocol ID: {}, found: {}",
                    alvr_common::protocol_id_u64(),
                    info.client_protocol_id,
                );

                return Ok(());
            }'''
new='''            if info.client_protocol_id != alvr_common::protocol_id_u64() {
                let legacy_test = std::env::var("ALVR_LEGACY_PROTOCOL_TEST")
                    .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
                    .unwrap_or(false);
                warn!(
                    "Trusted client protocol mismatch! Expected protocol ID: {}, found: {}. Client platform: {}. Legacy test mode: {}",
                    alvr_common::protocol_id_u64(),
                    info.client_protocol_id,
                    info.platform_string,
                    legacy_test,
                );
                if !legacy_test {
                    return Ok(());
                }
                warn!("TEST ONLY: continuing handshake despite ALVR protocol mismatch");
            }'''
if old in s: s=s.replace(old,new,1)
elif 'ALVR_LEGACY_PROTOCOL_TEST' not in s: raise SystemExit("protocol check insertion point missing")
p.write_text(s)
PY

echo "=== Repair pinned ALVR client tracking ABI ==="
python3 - "$ALVR/alvr/client_core/src/connection.rs" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
s=s.replace('view_params_queue.write()', 'global_view_params_queue.lock()')
s=s.replace('header.views_params', 'header.global_view_params')
p.write_text(s)
PY

echo "=== Apply Monado/ALVR ABI compatibility ==="
for f in "$ALVR_RENDER/src/Encoder.cpp" "$ALVR_RENDER/src/EventManager.hpp"; do
    sed -i       -e 's/ALVR_EVENT_VIEWS_PARAMS/ALVR_EVENT_LOCAL_VIEW_PARAMS/g'       -e 's/event\.views_params/event.local_view_params/g'       "$f"
done

echo "=== Apply Intel Arc DMA-BUF compatibility ==="
python3 - "$ALVR_RENDER/src/Renderer.cpp" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = "bool haveDrmModifiers = true;"
new = """// Intel ANV can export DMA-BUF, but the historical DRM-modifier image
    // creation path crashes during vkCreateImage on the tested Arc A750/Mesa
    // stack. Keep DMA-BUF for FFmpeg/VAAPI, but use the linear fallback.
    const bool isIntel = ctx.physDev.getProperties().vendorID == 0x8086;
    bool haveDrmModifiers = !isIntel;"""
if old not in s and new not in s:
    raise SystemExit("ERROR: expected DRM modifier switch not found")
if old in s:
    s = s.replace(old, new, 1)
p.write_text(s)
PY

echo "=== Companion state ==="
git -C "$ALVR" log -1 --oneline
git -C "$ALVR_RENDER" log -1 --oneline
git -C "$ALVR_RENDER" diff -- src/Encoder.cpp src/EventManager.hpp src/Renderer.cpp
