#!/usr/bin/env python3
"""Loft proximity voice: only nearby users hear one another; never loop back self.

Passive presence listener (does not publish an avatar), stdlib + PipeWire tools.
Unknown positions fail closed. Entry radius 3m, exit radius 3.5m on the floor plane.
"""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import re
import select
import socket
import struct
import subprocess
import tempfile
import time

PACKET = struct.Struct('<I32s7fI')
RADIUS = 3.0
HYSTERESIS = 0.5


def instance(name, base):
    if name == base:
        return 'primary'
    m = re.fullmatch(re.escape(base) + r' \(([a-z0-9_-]{1,31})\)', name)
    return m[1] if m else None


def read_position(data):
    if len(data) != PACKET.size:
        return None
    magic, raw, x, y, z, *rest = PACKET.unpack(data)
    cid = raw.split(b'\0', 1)[0].decode('ascii', errors='replace')
    if magic != 0x3154464c or not re.fullmatch(r'[a-z0-9_-]{1,31}', cid) or not all(map(math.isfinite, (x,y,z))):
        return None
    return cid, (x, z)


def positions(directory, duration=0.18):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix='voice-', suffix='.sock', dir=directory)
    os.close(fd)
    os.unlink(filename)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    result = {}
    try:
        sock.bind(filename)
        end = time.monotonic() + duration
        while (remaining := end - time.monotonic()) > 0:
            if not select.select([sock], [], [], remaining)[0]:
                break
            packet = read_position(sock.recv(1024))
            if packet:
                result[packet[0]] = packet[1]
    finally:
        sock.close()
        Path(filename).unlink(missing_ok=True)
    return result


def voice_links(graph, pos, radius=RADIUS, mutes=None):
    mutes = mutes or {}
    nodes, ports, existing = {}, {}, set()
    for obj in graph:
        info = obj.get('info') or {}; props = info.get('props') or {}
        kind = obj.get('type', '').rsplit(':',1)[-1]
        if kind == 'Node': nodes[obj['id']] = props.get('node.name','')
        elif kind == 'Port': ports[obj['id']] = (int(props.get('node.id',-1)), info.get('direction'), props.get('audio.channel'))
        elif kind == 'Link': existing.add((info.get('output-port-id'),info.get('input-port-id')))
    mics = {pid:instance(nodes.get(node,''),'ALVR Microphone') for pid,(node,direction,ch) in ports.items() if direction=='output'}
    ears = {pid:instance(nodes.get(node,''),'ALVR Audio') for pid,(node,direction,ch) in ports.items() if direction=='input'}
    mics = {p:i for p,i in mics.items() if i}; ears = {p:i for p,i in ears.items() if i}
    managed = {(a,b) for a,b in existing if a in mics and b in ears}
    wanted = set()
    for a, speaker in mics.items():
        for b, listener in ears.items():
            if speaker == listener or speaker not in pos or listener not in pos: continue
            if speaker in mutes.get(listener, []): continue
            threshold = radius + (HYSTERESIS if (a,b) in managed else 0)
            if math.dist(pos[speaker],pos[listener]) > threshold: continue
            ac,bc = ports[a][2],ports[b][2]
            if ac == 'MONO' or bc == 'MONO' or ac == bc: wanted.add((a,b))
    return wanted, managed


def sync(mode, directory):
    graph = json.JSONDecoder().raw_decode(subprocess.check_output(['pw-dump'],text=True,timeout=5).lstrip())[0]
    pos = positions(directory) if mode == 'link' else {}
    runtime=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))
    if mode == 'link':
        fd,filename=tempfile.mkstemp(dir=runtime,prefix='.voice-positions-')
        with os.fdopen(fd,'w') as f: json.dump({'time':time.monotonic(),'positions':pos},f)
        os.replace(filename,runtime/'xr-loft-voice-positions.json')
    config=Path(os.environ.get('XR_PANEL_CONFIG',Path.home()/'.config/xr-control-panel/config.json'))
    try: mutes=json.loads(config.with_name('voice-mutes.json').read_text())
    except (OSError,ValueError): mutes={}
    wanted, current = voice_links(graph, pos, mutes=mutes)
    if mode == 'status':
        print(f'{len(current)} proximity voice channel links; enter {RADIUS:g}m / leave {RADIUS+HYSTERESIS:g}m')
        return
    for a,b in current - wanted:
        subprocess.run(['pw-link','-d',str(a),str(b)],capture_output=True,timeout=3)
    for a,b in wanted - current:
        subprocess.run(['pw-link',str(a),str(b)],capture_output=True,timeout=3)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['link','watch','unlink','status'],default='link',nargs='?')
    args=parser.parse_args()
    runtime=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))
    directory=Path(os.environ.get('XR_LOFT_PRESENCE_DIR',runtime/'xr-loft-presence'))
    with open(runtime/'xr-proximity-voice.lock','a') as lock:
        while True:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try: sync('link' if args.mode=='watch' else args.mode,directory)
            finally: fcntl.flock(lock,fcntl.LOCK_UN)
            if args.mode!='watch': break
            time.sleep(0.3)

if __name__=='__main__': main()
