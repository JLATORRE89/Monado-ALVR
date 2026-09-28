import subprocess,unittest
from unittest.mock import patch
import test_loft_menu as menu_tests

class VoiceTests(unittest.TestCase):
 setUp=menu_tests.MenuTests.setUp
 tearDown=menu_tests.MenuTests.tearDown
 def test_missing_vision_workflow_does_not_capture(self):
  with patch.object(self.server,'require_headset'),patch.object(self.server.gpu_worker,'workflows',return_value={'text':{'reference_count':0}}),patch.object(self.server,'headset_action') as capture:
   with self.assertRaises(ValueError):self.server.gpu_screen_request('quest','text','Find a chair')
   capture.assert_not_called()
 def test_capture_uses_spoken_request_and_same_headset(self):
  with patch.object(self.server,'require_headset'),patch.object(self.server.gpu_worker,'workflows',return_value={'vision':{'reference_count':1}}),patch.object(self.server,'headset_action',return_value={'file':'screen.png'}) as capture,patch.object(self.server,'capture_dir_for',return_value=self.path),patch.object(self.server.gpu_worker,'submit',return_value={'request_id':'example'}) as submit:
   for text in ['Find a ball in my current field of view','Find a chair','Find a glass cup','Find all dogs']:
    self.server.gpu_screen_request('quest','vision',text)
    self.assertEqual(submit.call_args.args[1],text)
    self.assertEqual(submit.call_args.kwargs['review_serial'],'quest')
   capture.assert_called_with('quest','screenshot')
 def test_delivery_pushes_and_opens_only_target_headset(self):
  self.server.CAPTURE_DIR=self.path;folder=self.path/'gpu-worker';folder.mkdir();(folder/'result.png').write_bytes(b'example')
  rec={'review_serial':'quest','request_id':'12345678-1234-1234-1234-123456789abc','outputs':['result.png']}
  with patch.object(self.server,'require_headset'),patch.object(self.server,'adb',return_value=subprocess.CompletedProcess([],0,'','')) as adb:
   self.server.gpu_deliver_review(rec)
   self.assertEqual(len(adb.call_args_list),3)
   self.assertTrue(all(c.args[:2]==('-s','quest') for c in adb.call_args_list))
   self.assertIn('/gpu-review/',adb.call_args_list[-1].args[-1])
 def test_no_images_no_false_delivery(self):
  with patch.object(self.server,'require_headset'),patch.object(self.server,'adb') as adb:
   with self.assertRaises(RuntimeError):self.server.gpu_deliver_review({'review_serial':'quest','outputs':[]})
   adb.assert_not_called()

if __name__=='__main__':unittest.main()
