#!/usr/bin/env python3
"""Read ALVR /api/events for N seconds and print statistics fields (stdlib only)."""
import base64
import json
import os
import socket
import sys
import time

duration = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
keys = ("network_latency_ms", "total_latency_ms", "video_mbits_per_sec",
        "scaled_calculated_throughput_bps", "decoder_latency_limiter_bps",
        "encoder_latency_limiter_bps", "requested_bitrate_bps", "manual_max_throughput_bps")

sock = socket.create_connection(("127.0.0.1", 8082), timeout=5)
key = base64.b64encode(os.urandom(16)).decode()
sock.sendall((
    "GET /api/events HTTP/1.1\r\nHost: 127.0.0.1:8082\r\nUpgrade: websocket\r\n"
    "Connection: Upgrade\r\nSec-WebSocket-Key: " + key + "\r\n"
    "Sec-WebSocket-Version: 13\r\nX-ALVR: 1\r\n\r\n").encode())
buf = b""
while b"\r\n\r\n" not in buf:
    buf += sock.recv(4096)
head, buf = buf.split(b"\r\n\r\n", 1)
if b" 101 " not in head.split(b"\r\n")[0]:
    sys.exit("handshake failed: " + head.split(b"\r\n")[0].decode())


def read_exact(n):
    global buf
    while len(buf) < n:
        chunk = sock.recv(65536)
        if not chunk:
            raise EOFError
        buf += chunk
    out, buf = buf[:n], buf[n:]
    return out


end = time.time() + duration
while time.time() < end:
    try:
        b0, b1 = read_exact(2)
    except (socket.timeout, EOFError):
        break
    length = b1 & 0x7F
    if length == 126:
        length = int.from_bytes(read_exact(2), "big")
    elif length == 127:
        length = int.from_bytes(read_exact(8), "big")
    payload = read_exact(length)
    if b0 & 0x0F != 1:
        continue
    try:
        event = json.loads(payload)
    except ValueError:
        continue
    text = json.dumps(event)
    if not any(k in text for k in keys):
        continue

    def walk(o, out):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in keys:
                    out[k] = v
                walk(v, out)
        elif isinstance(o, list):
            for v in o:
                walk(v, out)
        return out

    print(time.strftime("%T"), json.dumps(walk(event, {})))
