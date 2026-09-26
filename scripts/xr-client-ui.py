#!/usr/bin/env python3
import json, os, urllib.request, subprocess, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
API=os.environ.get("ALVR_API","http://127.0.0.1:8082")
PORT=int(os.environ.get("XR_CLIENT_UI_PORT","8083"))
def req(path, method="GET", data=None):
    body=None if data is None else json.dumps(data).encode()
    r=urllib.request.Request(API+path,data=body,method=method,headers={"X-ALVR":"1","Content-Type":"application/json"})
    with urllib.request.urlopen(r,timeout=3) as x:return x.read()
PAGE="""<!doctype html><meta charset=utf-8><title>Intel XR Clients</title>
<style>body{font:16px system-ui;max-width:900px;margin:32px auto;padding:0 20px}button,input{margin:4px;padding:8px}pre{background:#eee;padding:12px}.card{border:1px solid #bbb;padding:12px;margin:12px 0}</style>
<h1>Intel XR Clients</h1><p>Default policy: <b>auto-accept protocol-valid ALVR clients</b>.</p>
<h2>Approved MAC devices</h2><input id=file type=file accept=".json,.xlsx"><button onclick="upload()">Import JSON/XLSX</button><pre id=approved></pre>
<h2>ALVR clients</h2><div id=x>Loading...</div>
<script>
async function load(){let j=await fetch('/api/clients').then(r=>r.json());let a=await fetch('/api/approved').then(r=>r.json());approved.textContent=JSON.stringify(a,null,2);let h='<p>Auto-accept: <b>'+(j.auto_accept?'ON':'OFF')+'</b></p>';for(const [n,c] of Object.entries(j.clients||{})){h+='<div class=card><b>'+n+'</b><pre>'+JSON.stringify(c,null,2)+'</pre><button onclick="act(\''+n+'\',\'Trust\')">Approve</button><button onclick="act(\''+n+'\',\'RemoveEntry\')">Reject / Forget</button></div>'}x.innerHTML=h||'No clients'}
async function act(n,a){await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify([n,a])});load()}
async function upload(){let f=file.files[0];if(!f)return;let r=await fetch('/api/approved/import',{method:'POST',headers:{'X-Filename':f.name},body:await f.arrayBuffer()});if(!r.ok)alert(await r.text());load()}
load();setInterval(load,3000)
</script>"""
class H(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def sendx(self,code,body,typ="application/json"):
        self.send_response(code);self.send_header("Content-Type",typ);self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path=="/":return self.sendx(200,PAGE.encode(),"text/html; charset=utf-8")
        if self.path=="/api/approved":
            try:
                out=subprocess.check_output(["/usr/bin/python3","/ai/intel-xr-prototype/src/Monado-ALVR/scripts/xr-approved-devices.py","list"])
                return self.sendx(200,out)
            except Exception as e:return self.sendx(502,json.dumps({"error":str(e)}).encode())
        if self.path=="/api/clients":
            try:return self.sendx(200,req("/api/xr/clients"))
            except Exception as e:return self.sendx(502,json.dumps({"error":str(e)}).encode())
        self.sendx(404,b"{}")
    def do_POST(self):
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
