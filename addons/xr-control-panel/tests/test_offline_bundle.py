import functools,hashlib,io,json,sys,tarfile,tempfile,threading,unittest
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import test_software_updates as update_tests
from software_updates import UpdateLibrary
from xr_downloader import create_bundle,SCHEMA,member_name

class BundleTests(unittest.TestCase):
 setUp=update_tests.UpdatesTests.setUp
 tearDown=update_tests.UpdatesTests.tearDown
 adb=update_tests.UpdatesTests.adb
 archive=update_tests.UpdatesTests.archive
 def test_download_pack_import_without_network(self):
  data=self.archive();sha=hashlib.sha256(data).hexdigest()
  host=Path(self.tmp.name)/'online';host.mkdir();(host/'firmware.zip').write_bytes(data)
  class Quiet(SimpleHTTPRequestHandler):
   def log_message(self,*args):pass
  server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(host)))
  threading.Thread(target=server.serve_forever,daemon=True).start()
  app={'name':'Quest Firmware','kind':'firmware','version':'200','url':f'http://127.0.0.1:{server.server_port}/firmware.zip','sha256':sha,'size':len(data)}
  self.lib.save_source(app);manifest=self.lib.export_manifest();out=Path(self.tmp.name)/'offline.tar.gz'
  try:create_bundle(manifest,out,lambda message:None)
  finally:server.shutdown();server.server_close()
  self.assertEqual(out.read_bytes()[8],2) # gzip XFL=maximum compression
  with out.open('rb') as f:self.lib.import_bundle(out.stat().st_size,f)
  self.assertEqual(self.lib.file(sha).read_bytes(),data)
  self.assertEqual(self.lib.export_manifest(),manifest)
  with self.assertRaises(ValueError):create_bundle(manifest,out,lambda message:None)
 def test_import_rejects_missing_tampered_and_traversal_atomically(self):
  data=self.archive();sha=hashlib.sha256(data).hexdigest();app={'name':'Firmware','kind':'firmware','url':'https://example.com/fw.zip','sha256':sha}
  manifest={'schema':SCHEMA,'applications':[app]}
  for files in [[],[('../outside',data)],[(member_name(app),b'bad')],[(member_name(app),data),('unexpected',b'bad')]]:
   out=io.BytesIO()
   with tarfile.open(fileobj=out,mode='w:gz') as tar:
    payload=json.dumps(manifest).encode();entry=tarfile.TarInfo('manifest.json');entry.size=len(payload);tar.addfile(entry,io.BytesIO(payload))
    for name,blob in files:
     entry=tarfile.TarInfo(name);entry.size=len(blob);tar.addfile(entry,io.BytesIO(blob))
   with self.assertRaises(ValueError):self.lib.import_bundle(len(out.getvalue()),io.BytesIO(out.getvalue()))
   self.assertFalse(self.lib.listing()['updates'])
 def test_manifest_rejects_missing_url_or_checksum(self):
  for app in [{'name':'App','kind':'apk','url':'https://example.com/app.apk'}, {'name':'App','kind':'apk','sha256':'0'*64,'url':'file:///etc/passwd'}]:
   with self.assertRaises(ValueError):self.lib.save_source(app)

if __name__=='__main__':unittest.main()
