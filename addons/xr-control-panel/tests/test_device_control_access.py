"""HTTP handlers enforce device identity for assistant actions and operator-only proxy policy."""
import json,unittest
from unittest.mock import Mock
import test_usb_pairing as pairing
class AccessTests(unittest.TestCase):
 def setUp(self):
  self.case=pairing.PairingTests();self.case.setUp();self.server=self.case.server
  self.server.ANDROID_ASSISTANT=Mock();self.server.WEB_PROXY=Mock()
 def tearDown(self):self.case.tearDown()
 def post(self,path,identity,data):
  h=Mock();h.path=path;h.authorized.return_value=True;h.identity.return_value=identity
  h.headers={'Host':'localhost','Origin':'http://localhost'};h.body.return_value=json.dumps(data).encode()
  self.server.Handler.do_POST(h);return h
 def test_cross_device_assistant_is_rejected(self):
  h=self.post('/api/android-assistant','TAB',{'serial':'QUEST','action':'off'})
  self.assertEqual(h.json.call_args.args[1],403);self.server.ANDROID_ASSISTANT.action.assert_not_called()
 def test_device_can_control_only_itself(self):
  self.post('/api/android-assistant','TAB',{'serial':'TAB','action':'off'})
  self.server.ANDROID_ASSISTANT.action.assert_called_once_with('TAB','off')
 def test_device_cannot_loosen_proxy_policy(self):
  h=self.post('/api/web-proxy','TAB',{'enabled':True,'port':8084})
  self.assertEqual(h.json.call_args.args[1],403);self.server.WEB_PROXY.configure.assert_not_called()
 def test_operator_controls_selected_assistant(self):
  self.post('/api/android-assistant',None,{'serial':'QUEST','action':'settings'})
  self.server.ANDROID_ASSISTANT.action.assert_called_once_with('QUEST','settings')
if __name__=='__main__':unittest.main()
