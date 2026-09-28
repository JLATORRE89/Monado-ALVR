import sys,json,tempfile,unittest,io
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT.parent/'xr-downloader'))
import xr_downloader as d
import software_updates as u
class AutoTests(unittest.TestCase):
 def test_offline_selection_export(self):
  with tempfile.TemporaryDirectory() as tmp:
   library=u.UpdateLibrary(tmp,None,lambda:[])
   library.save_source({'name':'ALVR','kind':'apk','package':'alvr.client.stable','resolve':'catalog'})
   result=library.export_manifest()
   self.assertEqual(result['schema'],d.REQUEST_SCHEMA)
   self.assertNotIn('url',result['applications'][0]);self.assertNotIn('sha256',result['applications'][0])
   library.remove_source('app:alvr.client.stable');self.assertFalse(library.sources)
 def test_resolve_publisher_release(self):
  asset={'name':'alvr_client_android.apk','digest':'sha256:'+'a'*64,'size':123,'browser_download_url':'https://github.com/alvr-org/ALVR/releases/download/v1/alvr_client_android.apk'}
  req={'schema':d.REQUEST_SCHEMA,'applications':[{'name':'ALVR','kind':'apk','package':'alvr.client.stable','resolve':'catalog'}]}
  def fake(*a,**kw):return io.BytesIO(json.dumps({'tag_name':'v1','assets':[asset]}).encode())
  with patch.object(d.urllib.request,'urlopen',side_effect=fake):
   resolved=d.resolve_requests(req,lambda _:None);self.assertEqual(resolved['applications'][0]['sha256'],'a'*64)
   asset['digest']=None
   with self.assertRaisesRegex(ValueError,'verifiable SHA-256'):d.resolve_requests(req,lambda _:None)
 def test_no_wrong_package_fallback(self):
  req={'schema':d.REQUEST_SCHEMA,'applications':[{'name':'Unknown','kind':'apk','package':'com.example.unknown','resolve':'catalog'}]}
  with patch.object(d.urllib.request,'urlopen') as network:
   with self.assertRaisesRegex(ValueError,'no supported publisher'):d.resolve_requests(req,lambda _:None)
   network.assert_not_called()
if __name__=='__main__':unittest.main()
