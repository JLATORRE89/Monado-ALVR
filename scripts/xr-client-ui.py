#!/usr/bin/env python3
import json, os, urllib.request, subprocess, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
API=os.environ.get("ALVR_API","http://127.0.0.1:8082")
PORT=int(os.environ.get("XR_CLIENT_UI_PORT","8083"))
CONFIG="/ai/intel-xr-prototype/src/Monado-ALVR/config/xr-build.json"
EDITABLE={
 "paths.root":str,"paths.android_home":str,"paths.java_home":str,
 "android.ndk_version":str,"android.rust_target":str,"android.platform_api":int,
 "android.openxr_sdk_repo":str,"android.openxr_sdk_ref":str,"android.usb_stay_awake":bool,
 "alvr.legacy_protocol_test":bool,
 "network.quest_ip":str,"network.direct_ip_fallback":bool,"network.mdns":bool,
 "network.legacy_udp":bool,"network.usb":bool,
 "video.test_pattern":bool,"video.test_pattern_mode":str,
}
def config_load(): return json.load(open(CONFIG))
def config_save(data):
    tmp=CONFIG+".tmp"
    with open(tmp,"w") as x: json.dump(data,x,indent=2); x.write("\n")
    os.replace(tmp,CONFIG)
def set_path(obj,path,value):
    cur=obj
    bits=path.split(".")
    for b in bits[:-1]: cur=cur[b]
    cur[bits[-1]]=value
def req(path, method="GET", data=None):
    body=None if data is None else json.dumps(data).encode()
    r=urllib.request.Request(API+path,data=body,method=method,headers={"X-ALVR":"1","Content-Type":"application/json"})
    with urllib.request.urlopen(r,timeout=3) as x:return x.read()
PAGE="""<!doctype html><meta charset=utf-8><title>Intel XR Clients</title>
<style>body{font:16px system-ui;max-width:900px;margin:32px auto;padding:0 20px}button,input,select{margin:4px;padding:8px}pre{background:#eee;padding:12px}.card{border:1px solid #bbb;padding:12px;margin:12px 0}</style>
<h1>Intel XR Clients</h1><div id=stack>Checking stack...</div><p>Default policy: <b>auto-accept protocol-valid ALVR clients</b>.</p>
<h2>Settings</h2><p>Edit any item in <code>config/xr-build.json</code>.</p><select id=settingSelect onchange="showSetting()"><option value="">Select a setting...</option></select><span id=settingEditor></span><button onclick="saveSelectedSetting()">Update setting</button><button onclick="service('restart')">Restart services</button><button onclick="service('rebuild')">Rebuild runtime</button><span id=setmsg></span><h2>Approved MAC devices</h2><input id=file type=file accept=".json,.xlsx"><button onclick="upload()">Import JSON/XLSX</button><pre id=approved></pre>
<h2>ALVR clients</h2><button onclick="clearClients()">Clear client cache</button><span id=msg></span><div id=x>Loading...</div>
<script>
async function stackStatus(){try{let r=await fetch('/api/status');let j=await r.json();stack.innerHTML='<b>Runtime:</b> '+j.runtime+' &nbsp; <b>API:</b> '+j.api+' &nbsp; <b>UI:</b> READY'}catch(e){stack.textContent='Stack status unavailable: '+e}}
async function service(a){setmsg.textContent=' '+a+'...';let r=await fetch('/api/service/'+a,{method:'POST'});let j=await r.json();setmsg.textContent=r.ok?' '+j.message:' Failed: '+(j.error||r.status);stackStatus();load()}
let configValues={};
async function loadSettings(){try{let r=await fetch('/api/config',{cache:'no-store'});let j=await r.json();if(!r.ok)throw Error(j.error||r.status);configValues=j.values||{};let sel=document.getElementById('settingSelect');sel.replaceChildren(new Option('Select a setting...',''));for(let k of Object.keys(configValues).sort())sel.add(new Option(k,k));document.getElementById('settingEditor').innerHTML='';document.getElementById('setmsg').textContent=' Loaded '+Object.keys(configValues).length+' settings.'}catch(e){document.getElementById('setmsg').textContent=' Config error: '+e}}
function showSetting(){let k=settingSelect.value;if(!k){settingEditor.innerHTML='';return}let v=configValues[k];if(typeof v==='boolean'){settingEditor.innerHTML='<label><input id=settingValue type=checkbox '+(v?'checked':'')+'> '+String(v)+'</label>'}else{settingEditor.innerHTML='<input id=settingValue style="min-width:360px" value="'+String(v).replaceAll('"','&quot;')+'">'}}
async function saveSelectedSetting(){let k=settingSelect.value;if(!k){setmsg.textContent=' Select a setting first.';return}let el=document.getElementById('settingValue');let v=el.type==='checkbox'?el.checked:el.value;setmsg.textContent=' Saving...';let r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({[k]:v})});let j=await r.json();if(r.ok){configValues[k]=v;setmsg.textContent=' Saved '+k+'. '+j.action;showSetting()}else setmsg.textContent=' Save failed: '+(j.error||r.status)}
async function load(){try{let r=await fetch('/api/clients');let j=await r.json();if(!r.ok)throw Error(j.error||r.status);let ar=await fetch('/api/approved');let a=await ar.json();approved.textContent=JSON.stringify(a,null,2);let h='<p>Auto-accept: <b>'+(j.auto_accept?'ON':'OFF')+'</b></p>';for(const [n,c] of Object.entries(j.clients||{})){h+='<div class=card><b>'+n+'</b><pre>'+JSON.stringify(c,null,2)+'</pre><button onclick="act(\''+n+'\',\'Trust\')">Approve</button><button onclick="act(\''+n+'\',\'RemoveEntry\')">Reject / Forget</button></div>'}x.innerHTML=h||'No clients';msg.textContent=''}catch(e){x.innerHTML='<b>API error:</b> '+e;msg.textContent=''}}
async function act(n,a){await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify([n,a])});load()}
async function clearClients(){if(!confirm('Clear cached ALVR client entries? Approved MAC devices are preserved.'))return;msg.textContent=' Clearing...';try{let r=await fetch('/api/clients/clear',{method:'POST'});let t=await r.text();if(!r.ok)throw Error(t||r.status);msg.textContent=' Client cache cleared.';await load()}catch(e){msg.textContent=' Clear failed: '+e}}
async function upload(){let f=file.files[0];if(!f)return;let r=await fetch('/api/approved/import',{method:'POST',headers:{'X-Filename':f.name},body:await f.arrayBuffer()});if(!r.ok)alert(await r.text());load()}
stackStatus();loadSettings();load();setInterval(()=>{stackStatus();load()},3000)
</script>"""
class H(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def sendx(self,code,body,typ="application/json"):
        self.send_response(code);self.send_header("Content-Type",typ);self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path=="/":return self.sendx(200,PAGE.encode(),"text/html; charset=utf-8")
        if self.path=="/api/status":
            runtime=subprocess.run(["systemctl","--user","is-active","intel-xr-monado.service"],capture_output=True,text=True).stdout.strip()
            try:req("/api/ping"); api="READY"
            except Exception:api="DOWN"
            return self.sendx(200,json.dumps({"runtime":runtime or "unknown","api":api}).encode())
        if self.path=="/api/config":
            try:
                cfg=config_load(); vals={}
                for key in EDITABLE:
                    cur=cfg
                    for bit in key.split("."): cur=cur[bit]
                    vals[key]=cur
                return self.sendx(200,json.dumps({"values":vals}).encode())
            except Exception as e:return self.sendx(500,json.dumps({"error":str(e)}).encode())
        if self.path=="/api/approved":
            try:
                out=subprocess.check_output(["/usr/bin/python3","/ai/intel-xr-prototype/src/Monado-ALVR/scripts/xr-approved-devices.py","list"])
                return self.sendx(200,out)
            except Exception as e:return self.sendx(502,json.dumps({"error":str(e)}).encode())
        if self.path=="/api/clients":
            try:return self.sendx(200,req("/api/xr/clients"))
            except Exception as e:
                # Keep the UI usable if the enhanced registry endpoint is absent
                # or temporarily unavailable. Session clients are the fallback.
                try:
                    raw=req("/api/session")
                    session=json.loads(raw)
                    clients=session.get("client_connections",session.get("clients",{}))
                    return self.sendx(200,json.dumps({"auto_accept":False,"clients":clients,"source":"session-fallback","registry_error":str(e)}).encode())
                except Exception as e2:return self.sendx(502,json.dumps({"error":str(e),"fallback_error":str(e2)}).encode())
        self.sendx(404,b"{}")
    def do_POST(self):
        if self.path in ("/api/service/restart","/api/service/rebuild"):
            try:
                if self.path.endswith("restart"):
                    subprocess.Popen(["bash","/ai/intel-xr-prototype/src/Monado-ALVR/scripts/monado-service.sh","restart"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    return self.sendx(202,json.dumps({"message":"Restart requested."}).encode())
                subprocess.Popen(["bash","/ai/intel-xr-prototype/src/Monado-ALVR/scripts/build-intel-xr.sh"],stdout=open("/ai/intel-xr-prototype/logs/webui-build.log","ab"),stderr=subprocess.STDOUT)
                return self.sendx(202,json.dumps({"message":"Build started; progress is logged to logs/webui-build.log."}).encode())
            except Exception as e:return self.sendx(500,json.dumps({"error":str(e)}).encode())
        if self.path=="/api/config":
            try:
                raw=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
                cfg=config_load()
                for key,val in raw.items():
                    if key not in EDITABLE: raise ValueError("setting not editable: "+key)
                    typ=EDITABLE[key]
                    if typ is bool: parsed=bool(val)
                    elif typ is int: parsed=int(val)
                    else: parsed=str(val)
                    set_path(cfg,key,parsed)
                config_save(cfg)
                return self.sendx(200,json.dumps({"saved":True,"action":"Runtime/network changes may require service restart; toolchain/version changes require rebuild."}).encode())
            except Exception as e:return self.sendx(400,json.dumps({"error":str(e)}).encode())
        if self.path=="/api/clients/clear":
            try:
                clients=json.loads(req("/api/xr/clients")).get("clients",{})
                errors=[]
                for name in list(clients):
                    try:req("/api/session/client-connections","POST",[name,"RemoveEntry"])
                    except Exception as e:errors.append(f"{name}: {e}")
                if errors:return self.sendx(502,json.dumps({"errors":errors}).encode())
                return self.sendx(204,b"")
            except Exception as e:return self.sendx(502,json.dumps({"error":str(e)}).encode())
        if self.path=="/api/approved/import":
            try:
                n=int(self.headers.get("Content-Length","0")); raw=self.rfile.read(n)
                typ=self.headers.get("X-Filename","devices.json")
                suffix=".xlsx" if typ.lower().endswith(".xlsx") else ".json"
                with tempfile.NamedTemporaryFile(suffix=suffix,delete=False) as t: t.write(raw); name=t.name
                subprocess.run(["/usr/bin/python3","/ai/intel-xr-prototype/src/Monado-ALVR/scripts/xr-approved-devices.py","import",name],check=True)
                os.unlink(name); return self.sendx(204,b"")
            except Exception as e:return self.sendx(400,json.dumps({"error":str(e)}).encode())

        if self.path!="/api/action":return self.sendx(404,b"{}")
        try:
            data=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
            req("/api/session/client-connections","POST",data);self.sendx(204,b"")
        except Exception as e:self.sendx(502,json.dumps({"error":str(e)}).encode())
ThreadingHTTPServer(("127.0.0.1",PORT),H).serve_forever()
