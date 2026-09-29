import unittest
from unittest.mock import patch
import test_usb_pairing as pairing

class HealthTests(unittest.TestCase):
    def setUp(self):
        self.case=pairing.PairingTests(); self.case.setUp(); self.s=self.case.server
    def tearDown(self): self.case.tearDown()
    def device(self, **kw):
        return dict(serial='Q1', state='device', is_quest=True, telemetry_ok=True, battery=77, awake=True, client_installed=True, client_running=True, alvr=[{'state':'Streaming'}], **kw)
    def test_outage_retains_timestamped_values_and_recovery_refreshes(self):
        with patch.object(self.s.time,'time',return_value=100):
            a=self.s.control_health(self.device())
        self.assertEqual(a['health']['summary'],'Streaming / Healthy')
        with patch.object(self.s.time,'time',return_value=110):
            b=self.s.control_health({'serial':'Q1','state':'streaming-only','alvr':[{'state':'Streaming'}]})
        self.assertEqual(b['health']['summary'],'Streaming / Degraded')
        self.assertEqual(b['battery'],77);self.assertEqual(b['telemetry']['age_seconds'],10)
        d=self.device();d['battery']=78
        c=self.s.control_health(d)
        self.assertEqual(c['battery'],78);self.assertEqual(c['telemetry']['state'],'fresh')
    def test_empty_or_failed_shell_is_not_healthy(self):
        import subprocess
        d={'serial':'Q1','state':'device','model':'Quest 2'}
        for result in [subprocess.CompletedProcess([],0,''),subprocess.CompletedProcess([],1,'BATTERY=99')]:
            with patch.object(self.s,'adb',return_value=result):
                h=self.s.control_health(self.s.headset_info(d))
            self.assertEqual(h['health']['control'],'degraded')
    def test_unauthorized_never_reconnects(self):
        h=self.s.control_health({'serial':'Q1','state':'unauthorized','is_quest':True})
        with patch.object(self.s,'headsets_snapshot',return_value={'headsets':[h]}),patch.object(self.s,'adb') as a:
            self.s.recover_controls_once()
        a.assert_not_called()
    def test_reconnect_is_targeted_and_rate_limited(self):
        h=self.s.control_health({'serial':'Q1','state':'offline','is_quest':True})
        with patch.object(self.s,'headsets_snapshot',return_value={'headsets':[h]}),patch.object(self.s,'adb') as a:
            self.s.recover_controls_once();self.s.recover_controls_once()
        a.assert_called_once_with('-s','Q1','reconnect',timeout=5)
    def test_timeout_isolated(self):
        import subprocess
        with patch.object(self.s,'adb',side_effect=subprocess.TimeoutExpired('adb',15)):
            h=self.s.headset_info({'serial':'Q1','state':'device','model':'Quest'})
        self.assertFalse(h['telemetry_ok'])

    def test_slow_authorized_telemetry_never_resets_transport(self):
        h=self.s.control_health({'serial':'Q1','state':'device','is_quest':True,'telemetry_ok':False})
        with patch.object(self.s,'headsets_snapshot',return_value={'headsets':[h]}),patch.object(self.s,'adb') as a:
            self.s.recover_controls_once()
        a.assert_not_called()
