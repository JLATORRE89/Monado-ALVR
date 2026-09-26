# Known Issues / Future Work

## Native ALVR mDNS discovery — UNFINISHED

Status: **known issue; not complete**.

### Proven working

- Matched Quest client `alvr.client.monado` v21.0.0-dev11 launches with the bundled Android OpenXR loader.
- Quest Wi-Fi address observed during development: `192.168.86.168`.
- Quest emits valid `_alvr._tcp.local.` mDNS advertisements.
- Advertisement includes `protocol=21-dev11`, an SRV record, and the Quest IPv4 A record.
- Multicast packets reach the workstation.
- Monado/server has UDP 5353 listeners.

### Unfinished

The pinned server_core `mdns_sd` browser does not currently turn the valid Quest advertisement into a usable current-generation client registry entry. Native mDNS discovery must therefore not be reported as complete.

### Current workaround / next path

Implement direct/manual-IP discovery for current clients. Direct IP replaces discovery only: normal ALVR protocol validation, trust policy, approved-MAC policy, and handshake must remain enforced.

### Future investigation

- Instrument all `ServiceEvent` variants from `mdns_sd`, not only `ServiceResolved`.
- Determine why `ServiceResolved` is absent despite complete PTR/SRV/TXT/A records being visible on the interface.
- Keep IPv4-preference hardening and resolved-address logging.
- Restore native mDNS as a first-class path once reliable.

Target architecture:

```text
mDNS -----------\
Direct IP -------+--> common registry --> trust/MAC policy --> ALVR handshake
Legacy UDP 9943 -+
USB -------------/
```
