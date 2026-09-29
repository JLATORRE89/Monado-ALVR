"""Mirror the primary streamed headset's app sources to tablet listeners.

Follow only sources already feeding ALVR Audio, not the desktop's default sink.
Microphones are linked separately by xr-voice.sh: excluding them here prevents
hearing the tablet's own microphone back through the headset mix. Native Quest
apps that never send audio to this PC are outside this route.
"""
import json
import os
import re
import math
import time
import tempfile
from pathlib import Path
import subprocess
import threading


def desired_links(graph, listeners):
    nodes, ports, links = {}, {}, set()
    for obj in graph:
        info = obj.get('info') or {}
        props = info.get('props') or {}
        kind = obj.get('type', '').rsplit(':', 1)[-1]
        if kind == 'Node':
            nodes[obj['id']] = props.get('node.name', '')
        elif kind == 'Port':
            ports[obj['id']] = (int(props.get('node.id', -1)), info.get('direction'), props.get('audio.channel'))
        elif kind == 'Link':
            links.add((info.get('output-port-id'), info.get('input-port-id')))
    targets = {f'ALVR Audio ({cid})' for cid in listeners}
    inputs = [pid for pid, (node, direction, _) in ports.items() if direction == 'input' and nodes.get(node) in targets]
    sources = set()
    for src, dst in links:
        if src not in ports or dst not in ports:
            continue
        if nodes.get(ports[dst][0]) != 'ALVR Audio':
            continue
        name = nodes.get(ports[src][0], '')
        if not name or name.startswith(('ALVR Microphone', 'ALVR Audio')):
            continue
        sources.add(src)
    wanted = set()
    for src in sources:
        for dst in inputs:
            sc, dc = ports[src][2], ports[dst][2]
            if dc == 'MONO' or sc == 'MONO' or sc == dc:
                wanted.add((src, dst))
    return wanted, links


class HeadsetAudioRouter:
    def __init__(self, run=subprocess.run):
        self.run = run
        self.owned = set()
        self.lock = threading.Lock()

    def sync(self, listeners):
        with self.lock:
            result = self.run(['pw-dump'], capture_output=True, text=True, timeout=5)
            if result.returncode:
                return
            # pw-dump may append change arrays during graph churn. Use its complete
            # initial snapshot; the next sync picks up subsequent updates.
            wanted, existing = desired_links(json.JSONDecoder().raw_decode(result.stdout.lstrip())[0], listeners)
            for src, dst in self.owned - wanted:
                if (src, dst) in existing:
                    self.run(['pw-link', '-d', str(src), str(dst)], capture_output=True, timeout=3)
            self.owned.intersection_update(wanted & existing)
            for src, dst in wanted - existing:
                result = self.run(['pw-link', str(src), str(dst)], capture_output=True, timeout=3)
                if not result.returncode:
                    self.owned.add((src, dst))

class VoicePreferences:
    """Per-listener mute choices. The listener identity always comes from the authenticated socket."""
    def __init__(self, path, positions_path):
        self.path, self.positions_path = Path(path), Path(positions_path)
        self.lock = threading.Lock()

    def read(self):
        try: return json.loads(self.path.read_text())
        except (OSError, ValueError): return {}

    def set_muted(self, listener, speaker, muted):
        if listener == speaker or not all(re.fullmatch(r'[a-z0-9_-]{1,31}', x) for x in (listener,speaker)):
            return
        with self.lock:
            data=self.read(); values=set(data.get(listener,[]))
            if muted: values.add(speaker)
            else: values.discard(speaker)
            data[listener]=sorted(values)
            self.path.parent.mkdir(parents=True,exist_ok=True)
            fd,name=tempfile.mkstemp(dir=self.path.parent,prefix='.voice-mutes-')
            try:
                with os.fdopen(fd,'w') as f: json.dump(data,f)
                os.replace(name,self.path)
            finally:
                Path(name).unlink(missing_ok=True)

    def players(self, listener):
        muted=set(self.read().get(listener,[]))
        try:
            state=json.loads(self.positions_path.read_text())
            pos=state['positions'] if time.monotonic()-state['time'] < 2 else {}
        except (OSError,ValueError,KeyError): pos={}
        result=[]
        for cid in sorted((set(pos)|muted)-{listener}):
            distance=math.dist(pos[listener],pos[cid]) if listener in pos and cid in pos else None
            name='Quest user' if cid=='primary' else 'Tablet '+cid[7:] if cid.startswith('tablet-') else cid
            result.append({'id':cid,'name':name,'distance':round(distance,1) if distance is not None else None,'muted':cid in muted})
        return result
