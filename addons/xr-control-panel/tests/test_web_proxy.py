import base64,copy,http.client,json,socket,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from web_proxy import ProxyManager,ProxyServer,ProxyHandler,allows,rules

class ProxyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'proxy.json';self.manager=ProxyManager(self.path)
 def tearDown(self):self.manager.stop();self.tmp.cleanup()
 def profile(self):
  login=self.manager.device('TAB','Tablet',True,['example.com'],False)
  self.manager.config['enabled']=True
  auth='Basic '+base64.b64encode((login['username']+':'+login['password']).encode()).decode()
  return login,auth
 def test_disabled_by_default_and_empty_allowlist(self):
  self.manager.start();self.assertIsNone(self.manager.server);self.assertFalse(self.manager.public()['enabled'])
  self.assertFalse(allows('example.com',[]))
 def test_exact_domains_wildcards_and_rejection(self):
  self.assertTrue(allows('example.com',rules(['example.com'])))
  self.assertFalse(allows('evil-example.com',['example.com']))
  self.assertFalse(allows('example.com',['*.example.com']))
  self.assertTrue(allows('a.example.com',['*.example.com']))
  for bad in ['https://example.com','example.com:443','*',3]:
   with self.assertRaises(ValueError):rules([bad])
 def test_credentials_individual_hashed_and_revocable(self):
  login,auth=self.profile();self.assertEqual(self.manager.authenticate(auth)['serial'],'TAB')
  self.assertNotIn(login['password'],self.path.read_text());self.assertNotIn('digest',json.dumps(self.manager.public()))
  self.assertEqual(self.path.stat().st_mode&0o777,0o600)
  self.manager.config['enabled']=False
  self.manager.device('TAB','Tablet',False,['example.com'],True)
  self.manager.config['enabled']=True;self.assertIsNone(self.manager.authenticate(auth))
 def test_local_destinations_and_non_web_ports_blocked(self):
  profile={'allowed':['example.com']}
  with patch('web_proxy.socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',80))]):
   with self.assertRaises(ValueError):self.manager.destination('example.com',80,profile)
  with self.assertRaises(ValueError):self.manager.destination('example.com',22,profile)
 def serve(self):
  server=ProxyServer(('127.0.0.1',0),ProxyHandler);server.manager=self.manager
  threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  return server.server_port
 def test_http_auth_filter_and_no_credential_leak(self):
  received=[]
  class Origin(BaseHTTPRequestHandler):
   def do_GET(self):
    received.append(dict(self.headers));self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'OK')
   def log_message(self,*a):pass
  origin=ThreadingHTTPServer(('127.0.0.1',0),Origin);threading.Thread(target=origin.serve_forever,daemon=True).start()
  self.addCleanup(origin.server_close);self.addCleanup(origin.shutdown)
  login,auth=self.profile();port=self.serve();real_connect=socket.create_connection;real_lookup=socket.getaddrinfo
  def lookup(host,port,*a,**kw):
   if host=='example.com':return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',port))]
   return real_lookup(host,port,*a,**kw)
  def connect(address,*a,**kw):return real_connect(origin.server_address if address==('8.8.8.8',80) else address,*a,**kw)
  with patch('web_proxy.socket.getaddrinfo',side_effect=lookup),patch('web_proxy.socket.create_connection',side_effect=connect):
   for url,headers,status in [('http://example.com/',{},407),('http://blocked.example/',{'Proxy-Authorization':auth},403),('http://example.com/',{'Proxy-Authorization':auth},200)]:
    c=http.client.HTTPConnection('127.0.0.1',port,timeout=5);c.request('GET',url,headers=headers);response=c.getresponse();self.assertEqual(response.status,status);response.read();c.close()
  self.assertEqual(len(received),1);self.assertNotIn('Proxy-Authorization',received[0]);self.assertEqual(received[0]['Host'],'example.com')
 def test_upstream_failure_never_connects_direct(self):
  _,auth=self.profile();self.manager.config['upstream']='http://127.0.0.1:9';port=self.serve();real_connect=socket.create_connection;attempts=[]
  def connect(address,*a,**kw):
   if address[1]!=port:attempts.append(address);raise OSError('upstream unavailable')
   return real_connect(address,*a,**kw)
  with patch.object(self.manager,'destination',return_value=('example.com','8.8.8.8')),patch('web_proxy.socket.create_connection',side_effect=connect):
   c=http.client.HTTPConnection('127.0.0.1',port,timeout=5);c.request('CONNECT','example.com:443',headers={'Proxy-Authorization':auth});r=c.getresponse();self.assertEqual(r.status,502);r.read();c.close()
  self.assertEqual(attempts,[('127.0.0.1',9)])
if __name__=='__main__':unittest.main()
