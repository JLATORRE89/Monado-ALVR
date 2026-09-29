import unittest
from unittest.mock import patch
import test_usb_pairing as pairing

class DiscoveryTests(unittest.TestCase):
 def setUp(self):
  self.case=pairing.PairingTests();self.case.setUp();self.s=self.case.server
 def tearDown(self):self.case.tearDown()
 def clients(self):
  return {'clients':{'usb-Q1':{'connection_state':'Streaming','current_ip':'192.0.2.8','display_name':'Quest 2','trusted':True},
                     'old':{'connection_state':'Disconnected','display_name':'Quest 2'}}}
 def test_stream_remains_visible_without_adb(self):
  with patch.object(self.s,'list_adb_devices',return_value=[]),patch.object(self.s,'alvr_clients',return_value=self.clients()):
   devices=self.s.headsets_snapshot(0)['headsets']
  self.assertEqual(len(devices),1);self.assertTrue(devices[0]['streaming_only'])
  self.assertEqual((devices[0]['serial'],devices[0]['ip']),('Q1','192.0.2.8'))
  with patch.object(self.s,'list_adb_devices',return_value=[]):
   with self.assertRaises(RuntimeError):self.s.require_headset('Q1')
 def test_usb_reconnect_replaces_stream_card_without_duplicate(self):
  dev={'serial':'Q1','state':'device','model':'Quest 2','transport':'usb'}
  info={**dev,'is_quest':True,'ip':'192.0.2.8'}
  with patch.object(self.s,'list_adb_devices',return_value=[dev]),patch.object(self.s,'headset_info',return_value=info),patch.object(self.s,'alvr_clients',return_value=self.clients()):
   devices=self.s.headsets_snapshot(0)['headsets']
  self.assertEqual(len(devices),1);self.assertFalse(devices[0].get('streaming_only',False))
  self.assertEqual(devices[0]['alvr'][0]['state'],'Streaming')
 def test_ipv6_and_duplicate_aliases(self):
  c=self.clients();c['clients']['usb-Q1']['current_ip']='fd00::1'
  c['clients']['alias']=dict(c['clients']['usb-Q1'])
  d=self.s.add_streaming_headsets([],c)
  self.assertEqual(len(d),1);self.assertEqual(d[0]['ipv6'],['fd00::1']);self.assertIsNone(d[0]['ip'])
 def test_match_serial_when_adb_has_no_ip(self):
  d=self.s.add_streaming_headsets([{'serial':'Q1','state':'unauthorized'}],self.clients())
  self.assertEqual(len(d),1);self.assertEqual(d[0]['alvr'][0]['name'],'usb-Q1')

 def test_remembered_trusted_headset_remains_when_asleep(self):
  c=self.clients();c['clients']['usb-Q1'].update(connection_state='Disconnected',current_ip=None,manual_ips=['192.0.2.8'])
  c['clients']['client.wired']={'trusted':True,'connection_state':'Disconnected','current_ip':'127.0.0.1'}
  c['clients']['direct-192.0.2.8']={'trusted':True,'connection_state':'Disconnected','current_ip':None}
  d=self.s.add_streaming_headsets([],c)
  self.assertEqual(len(d),1);self.assertEqual(d[0]['alvr'][0]['state'],'Disconnected')
