import io,json,subprocess,tarfile,unittest
from unittest.mock import patch
import test_loft_menu as menu_tests

class ExportDefaultsTests(unittest.TestCase):
 setUp=menu_tests.MenuTests.setUp
 tearDown=menu_tests.MenuTests.tearDown
 def test_capture_archive_roundtrip_and_filter(self):
  self.server.CAPTURE_DIR=self.path/'captures'
  for headset in ['quest','other']:
   folder=self.server.CAPTURE_DIR/headset;folder.mkdir(parents=True)
   (folder/'screen.png').write_bytes(b'example image bytes')
   (folder/'movie.mp4').write_bytes(b'example video bytes')
  data=io.BytesIO();self.server.capture_export(None,data,[{'headset':'quest','file':'screen.png'}])
  with tarfile.open(fileobj=data,mode='r:gz') as t:
   self.assertEqual(set(t.getnames()),{'captures.json','quest/screen.png'})
   self.assertEqual(t.extractfile('quest/screen.png').read(),b'example image bytes')
  self.assertTrue((self.server.CAPTURE_DIR/'quest/screen.png').exists())
 def test_capture_requires_explicit_selection(self):
  for selection in [None, [], [{'headset':'../other','file':'screen.png'}]]:
   with self.assertRaises(ValueError):self.server.capture_export(None,io.BytesIO(),selection)
 def test_capture_rejects_symlink(self):
  self.server.CAPTURE_DIR=self.path/'captures';folder=self.server.CAPTURE_DIR/'quest';folder.mkdir(parents=True)
  secret=self.path/'outside';secret.write_text('outside');(folder/'screen.png').symlink_to(secret)
  with self.assertRaises(ValueError):self.server.capture_export(None,io.BytesIO(),[{'headset':'quest','file':'screen.png'}])
 def test_selected_and_all_defaults_preserve_other_settings(self):
  path=self.path/'runtime.json'
  path.write_text(json.dumps({'network':{'usb':False,'mdns':False},'private':'keep'}))
  with patch.object(self.server,'runtime_config_path',return_value=path), patch.object(self.server,'config_defaults',return_value={'network.usb':True,'network.mdns':True}), patch.object(self.server,'EDITABLE',{'network.usb':bool,'network.mdns':bool}):
   self.server.config_restore('network.usb')
   cfg=json.loads(path.read_text());self.assertTrue(cfg['network']['usb']);self.assertFalse(cfg['network']['mdns']);self.assertEqual(cfg['private'],'keep')
   before=path.read_bytes()
   with self.assertRaises(ValueError):self.server.config_restore('private')
   self.assertEqual(before,path.read_bytes())
   self.server.config_restore('*');self.assertTrue(json.loads(path.read_text())['network']['mdns'])
 def test_defaults_from_committed_config_not_current_values(self):
  result=subprocess.CompletedProcess([],0,'{"network":{"usb":true}}','')
  with patch.object(self.server,'runtime_config_path',return_value=self.path/'config/xr-build.json'),patch.object(self.server.subprocess,'run',return_value=result) as run:
   self.assertTrue(self.server.config_defaults()['network.usb'])
   self.assertEqual(run.call_args.args[0][-1],'HEAD:config/xr-build.json')

if __name__=='__main__':unittest.main()
