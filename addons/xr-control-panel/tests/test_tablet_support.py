"""Tablet pairing and app updates, with fake devices only."""
import unittest
from unittest.mock import patch
import test_software_updates as updates
import test_usb_pairing as pairing

class TabletUpdates(unittest.TestCase):
 def test_apk_install_does_not_require_quest_home(self):
  case=updates.UpdatesTests('test_apk_install_preserves_data_and_checks_version');case.setUp()
  try:
   case.devices[0]['model']='SM-X210'
   def quest_identity(serial):raise AssertionError('Tablet APK update must not probe Quest Home')
   case.lib.identity=quest_identity
   case.test_apk_install_preserves_data_and_checks_version()
  finally:case.tearDown()

class TabletPairing(unittest.TestCase):
 def test_usb_tablet_pairs_browser_without_alvr_trust(self):
  case=pairing.PairingTests();case.setUp()
  try:
   server=case.server
   device=dict(serial='TAB1',state='device',usb_path='1-4',model='SM-X210')
   info=dict(device,is_tablet=True,is_quest=False,client_installed=True,ip='192.0.2.20')
   with patch.object(server,'list_adb_devices',return_value=[device]),patch.object(server,'headset_info',return_value=info),patch.object(server,'issue_usb_pairing') as issue,patch.object(server,'trust_usb_headset_streaming') as trust:
    server.auto_pair_usb_once();issue.assert_called_once_with(info);trust.assert_not_called()
    issue.reset_mock();server.CFG['auto_authorize_usb']=False
    server.auto_pair_usb_once();issue.assert_not_called()
    server.CFG['auto_authorize_usb']=True;server.CFG['lan_access']=False
    server.auto_pair_usb_once();issue.assert_not_called()
    server.CFG['lan_access']=True;device['usb_path']=None
    server.auto_pair_usb_once();issue.assert_not_called()
  finally:case.tearDown()
if __name__=='__main__':unittest.main()
