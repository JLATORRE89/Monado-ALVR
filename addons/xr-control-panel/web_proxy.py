"""Optional authenticated HTTP/CONNECT proxy. Disabled by default; allowlists fail closed.
This is explicit-proxy filtering, not a device-wide firewall or a physical air gap.
"""
import base64
import copy
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import re
import secrets
import select
import socket
import threading
from urllib.parse import urlsplit
from usb_pairing import atomic_json

DEFAULT={'enabled':False,'port':8084,'upstream':'','devices':{}}
HOP={'connection','proxy-connection','proxy-authorization','proxy-authenticate','keep-alive','te','trailer','transfer-encoding','upgrade'}

def domain(value):
    if not isinstance(value,str):raise ValueError('Domain names must be text')
    value=value.strip().lower().rstrip('.')
    if not value or any(c in value for c in '/:@?#[ ]\\'):raise ValueError('Enter a domain name, without a URL or port')
    try:value=value.encode('idna').decode('ascii')
    except UnicodeError:raise ValueError('Invalid domain name')
    if len(value)>253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part) for part in value.split('.')):raise ValueError('Invalid domain name')
    return value

def rules(values):
    if not isinstance(values,list) or len(values)>200:raise ValueError('Use at most 200 allowed domains')
    return list(dict.fromkeys(('*.'+domain(v[2:])) if isinstance(v,str) and v.startswith('*.') else domain(v) for v in values))

def allows(host,entries):
    return any(host==p if not p.startswith('*.') else host.endswith(p[1:]) and host!=p[2:] for p in entries)

class ProxyManager:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.RLock();self.server=None;self.sockets=set()
        self.config=json.loads(self.path.read_text()) if self.path.exists() else copy.deepcopy(DEFAULT)
    def public(self,serial=None):
        with self.lock:
            c=copy.deepcopy(self.config)
            c['devices']=[{k:v for k,v in d.items() if k!='digest'} for d in c['devices'].values() if serial is None or d['serial']==serial]
            c['listening']=self.server is not None
            return c
    def _save(self):atomic_json(self.path,self.config)
    def stop(self):
        server=self.server;self.server=None
        for connection in list(self.sockets):
            try:connection.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            connection.close()
        if server:server.shutdown();server.server_close()
    def start(self):
        if not self.config['enabled'] or self.server:return
        self.server=ProxyServer(('0.0.0.0',self.config['port']),ProxyHandler);self.server.manager=self
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
    def configure(self,data):
        enabled=data.get('enabled');port=data.get('port',8084);upstream=data.get('upstream','').strip()
        if type(enabled) is not bool or type(port) is not int or not 1024<=port<=65535:raise ValueError('Choose an enabled state and port from 1024 to 65535')
        if upstream:
            p=urlsplit(upstream)
            try:valid=p.scheme=='http' and p.hostname and p.port and not p.username and not p.password and p.path in ('','/') and not p.query and not p.fragment
            except ValueError:valid=False
            if not valid:raise ValueError('Upstream must be http://host:port without credentials or a path')
        with self.lock:
            self.stop();self.config.update(enabled=enabled,port=port,upstream=upstream);self._save()
            try:self.start()
            except OSError:
                self.config['enabled']=False;self._save();raise ValueError('Proxy could not listen on that port; it remains disabled')
        return {'message':'Proxy enabled with domain filtering' if enabled else 'Proxy disabled; it does not filter direct device traffic'}
    def device(self,serial,name,enabled,allowed,renew=False):
        if not isinstance(serial,str) or not serial or len(serial)>200 or type(enabled) is not bool or type(renew) is not bool:raise ValueError('Select a valid device')
        allowed=rules(allowed)
        with self.lock:
            old=self.config['devices'].get(serial,{})
            token=secrets.token_urlsafe(24) if renew or not old else None
            row=dict(old,serial=serial,name=str(name)[:100],enabled=enabled,allowed=allowed)
            if token:row.update(username=secrets.token_hex(8),digest=hashlib.sha256(token.encode()).hexdigest())
            self.config['devices'][serial]=row;self._save()
            # Stop existing tunnels when a rule/credential changes; reauthentication uses the new rules.
            self.stop();self.start()
            result={'message':'Device proxy rules saved. Unlisted destinations are blocked.'}
            if token:result.update(username=row['username'],password=token)
            return result
    def authenticate(self,header):
        try:
            scheme,payload=header.split(' ',1)
            if scheme.lower()!='basic':return None
            user,password=base64.b64decode(payload,validate=True).decode().split(':',1)
        except (ValueError,UnicodeError):return None
        digest=hashlib.sha256(password.encode()).hexdigest()
        with self.lock:
            if not self.config['enabled']:return None
            for d in self.config['devices'].values():
                if d['enabled'] and hmac.compare_digest(d['username'],user) and hmac.compare_digest(d['digest'],digest):return copy.deepcopy(d)
        return None
    def destination(self,host,port,profile):
        host=domain(host)
        if port not in (80,443) or not allows(host,profile['allowed']):raise ValueError('Destination is not allowed for this device')
        # Never turn the proxy into a route to local admin services, metadata or loopback endpoints.
        addresses=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError('Private/local destinations must not pass through this internet proxy')
        return host,addresses[0][4][0]

class ProxyServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,*a,**kw):self.slots=threading.BoundedSemaphore(32);super().__init__(*a,**kw)
    def process_request(self,request,address):
        if not self.slots.acquire(False):request.close();return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()

class ProxyHandler(BaseHTTPRequestHandler):
    timeout=30
    def setup(self):
        super().setup();self.server.manager.sockets.add(self.connection)
    def finish(self):
        try:super().finish()
        finally:self.server.manager.sockets.discard(self.connection)
    def log_message(self,*a):pass # Do not record browsing URLs or credentials.
    def target(self,tunnel=False):
        manager=self.server.manager
        profile=manager.authenticate(self.headers.get('Proxy-Authorization',''))
        if not profile:
            self.send_response(407);self.send_header('Proxy-Authenticate','Basic realm="XR device proxy"');self.send_header('Connection','close');self.end_headers();self.close_connection=True;return None
        try:
            p=urlsplit('//'+self.path if tunnel else self.path)
            if (not tunnel and p.scheme!='http') or p.username or p.password or p.fragment or (tunnel and p.path):raise ValueError('Invalid proxy destination')
            port=p.port or (443 if tunnel else 80)
            host,ip=manager.destination(p.hostname or '',port,profile)
            return host,ip,port,p
        except (ValueError,OSError):self.send_error(403,'Destination blocked');return None
    def do_CONNECT(self):
        target=self.target(True)
        if not target:return
        host,ip,port,_=target;manager=self.server.manager;remote=None;started=False
        try:
            upstream=manager.config['upstream']
            if upstream:
                p=urlsplit(upstream);remote=socket.create_connection((p.hostname,p.port),15)
                remote.sendall(f'CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n'.encode())
                reply=bytearray()
                while not reply.endswith(b'\r\n\r\n'):
                    b=remote.recv(1)
                    if not b or len(reply)>=32768:raise OSError('Invalid upstream response')
                    reply.extend(b)
                if not re.match(rb'HTTP/1\.[01] 200(?: |\r)',reply):raise OSError('Upstream refused tunnel')
            else:remote=socket.create_connection((ip,port),15)
            manager.sockets.add(remote)
            self.send_response(200,'Connection established');self.end_headers();self.wfile.flush();started=True
            self.connection.settimeout(30);remote.settimeout(30)
            while True:
                readable,_,_=select.select([self.connection,remote],[],[],30)
                if not readable:break
                for source in readable:
                    data=source.recv(65536)
                    if not data:return
                    (remote if source is self.connection else self.connection).sendall(data)
        except (OSError,ValueError):
            if not started:self.send_error(502,'Proxy connection failed; no direct fallback')
        finally:
            self.close_connection=True
            if remote:manager.sockets.discard(remote);remote.close()
    def forward(self):
        target=self.target()
        if not target:return
        host,ip,port,p=target;connection=None;outgoing=None;started=False
        try:
            if self.headers.get('Transfer-Encoding'):self.send_error(411,'Use Content-Length');return
            lengths=self.headers.get_all('Content-Length') or ['0']
            if len(lengths)!=1 or not lengths[0].isdigit() or int(lengths[0])>16*1024*1024:self.send_error(413);return
            size=int(lengths[0]);body=self.rfile.read(size) if size else None
            if body is not None and len(body)!=size:self.send_error(400);return
            manager=self.server.manager;upstream=manager.config['upstream']
            path=(p.path or '/')+('?' +p.query if p.query else '')
            if upstream:
                u=urlsplit(upstream);connection=http.client.HTTPConnection(u.hostname,u.port,timeout=20)
                path=f'http://{host}:{port}'+path
            else:connection=http.client.HTTPConnection(ip,port,timeout=20)
            blocked=HOP|{x.strip().lower() for x in self.headers.get('Connection','').split(',')}|{'host'}
            headers={k:v for k,v in self.headers.items() if k.lower() not in blocked};headers['Host']=host+(f':{port}' if port!=80 else '');headers['Connection']='close'
            connection.connect();outgoing=connection.sock;manager.sockets.add(outgoing)
            connection.request(self.command,path,body=body,headers=headers);response=connection.getresponse()
            self.send_response(response.status);started=True
            blocked=HOP|{x.strip().lower() for x in response.getheader('Connection','').split(',')}
            for k,v in response.getheaders():
                if k.lower() not in blocked:self.send_header(k,v)
            self.send_header('Connection','close');self.end_headers()
            if self.command!='HEAD':
                while True:
                    block=response.read(65536)
                    if not block:break
                    self.wfile.write(block)
        except (OSError,http.client.HTTPException,ValueError):
            if not started:self.send_error(502,'Proxy connection failed; no direct fallback')
        finally:
            self.close_connection=True
            if connection:
                if outgoing:self.server.manager.sockets.discard(outgoing)
                connection.close()
    do_GET=do_HEAD=do_POST=do_PUT=do_PATCH=do_DELETE=do_OPTIONS=forward
