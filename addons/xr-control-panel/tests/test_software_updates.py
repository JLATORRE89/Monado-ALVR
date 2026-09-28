import io,json,sys,tempfile,time,unittest,zipfile,subprocess
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from software_updates import UpdateLibrary

class UpdatesTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'updates';self.calls=[]
  self.devices=[{'serial':'quest','state':'device','usb_path':'1-2','model':'Quest'}]
  self.lib=UpdateLibrary(self.root,self.adb,lambda:self.devices,'aapt2')
  self.info=dict(model='testquest',build='100',fingerprint='test/100',timestamp=100,battery=90)
  self.lib.identity=lambda serial:dict(self.info)
 def tearDown(self):self.tmp.cleanup()
 def adb(self,*args,**kw):
  self.calls.append(args)
  return subprocess.CompletedProcess(args,0,'Success\n' if 'install' in args else 'versionCode=7\n','')
 def archive(self,kind='firmware',**meta):
  f=io.BytesIO()
  with zipfile.ZipFile(f,'w') as z:
   if kind=='apk':z.writestr('AndroidManifest.xml',b'fake')
   else:
    m={'pre-device':'testquest','post-build-incremental':'200','post-timestamp':'200'};m.update(meta)
    z.writestr('META-INF/com/android/metadata','\n'.join(k+'='+v for k,v in m.items()));z.writestr('payload.bin',b'fake test payload')
  return f.getvalue()
 def upload(self,kind='firmware',**meta):
  data=self.archive(kind,**meta)
  return self.lib.upload('file.apk' if kind=='apk' else 'file.zip',kind,len(data),io.BytesIO(data))['update']
 def wait_job(self,j):
  for _ in range(100):
   if self.lib.jobs[j]['state'] not in ('queued','running'):return
   time.sleep(.01)
  self.fail('job timed out')
 def test_offline_persistence_dedup_and_remove(self):
  row=self.upload();self.assertEqual(self.upload()['id'],row['id'])
  fresh=UpdateLibrary(self.root,self.adb,lambda:[])
  self.assertEqual(fresh.listing()['updates'][0]['id'],row['id'])
  fresh.remove(row['id']);self.assertFalse(fresh.listing()['updates'])
 def test_bad_checksum_interrupted_invalid_and_path(self):
  data=self.archive()
  for length,body,sha in [(len(data),io.BytesIO(data),'0'*64),(len(data)+1,io.BytesIO(data),''),(3,io.BytesIO(b'bad'),'')]:
   with self.assertRaises(ValueError):self.lib.upload('update.zip','firmware',length,body,sha)
  self.assertEqual(list(self.root.iterdir()),[])
  with self.assertRaises(ValueError):self.lib.get('../../etc/passwd')
 def test_unsafe_firmware_rejected(self):
  for meta in [{'ota-wipe':'yes'},{'ota-downgrade':'yes'},{'post-timestamp':'bad'}]:
   with self.assertRaises(ValueError):self.upload(**meta)
 def test_prepare_model_build_age_battery_usb(self):
  row=self.upload(**{'pre-build-incremental':'100','pre-build':'test/100'})
  for change in [dict(model='wrong'),dict(build='wrong'),dict(fingerprint='wrong'),dict(timestamp=300),dict(battery=10)]:
   with patch.dict(self.info,change):
    with self.assertRaises(ValueError):self.lib.prepare(row['id'],'quest')
  self.devices[0]['usb_path']=None
  with self.assertRaises(ValueError):self.lib.prepare(row['id'],'quest')
  self.devices[0]['usb_path']='1-2'
  self.assertIn('Compatibility checked',self.lib.prepare(row['id'],'quest')['message'])
 def test_firmware_needs_prepare_same_device_confirm_and_mode(self):
  row=self.upload()
  with self.assertRaises(ValueError):self.lib.start(row['id'],'quest',True)
  self.lib.prepare(row['id'],'quest')
  with self.assertRaises(ValueError):self.lib.start(row['id'],'quest',True)
  self.devices[0]['state']='sideload'
  with self.assertRaises(ValueError):self.lib.start(row['id'],'quest',False)
  with self.assertRaises(ValueError):self.lib.start(row['id'],'other',True)
  self.lib.prepared[(row['id'],'quest')]['expires']=0
  with self.assertRaises(ValueError):self.lib.start(row['id'],'quest',True)
 def test_transfer_not_success_until_reboot_verified(self):
  row=self.upload();self.lib.prepare(row['id'],'quest');self.devices[0]['state']='sideload'
  job=self.lib.start(row['id'],'quest',True)['job']['id'];self.wait_job(job)
  self.assertEqual(self.lib.jobs[job]['state'],'awaiting_verification')
  self.assertEqual(self.calls[0][0:3],('-s','quest','sideload'))
  with self.assertRaises(ValueError):self.lib.remove(row['id'])
  with self.assertRaises(ValueError):self.lib.verify(job)
  self.info['build']='200';self.lib.verify(job)
  self.assertEqual(self.lib.jobs[job]['state'],'verified')
 def test_apk_install_preserves_data_and_checks_version(self):
  with patch('software_updates.subprocess.run',return_value=subprocess.CompletedProcess([],0,"package: name='com.test.game' versionCode='7' versionName='1.0'\napplication-label:'Game'\n",'')):
   row=self.upload('apk')
  job=self.lib.start(row['id'],'quest',True)['job']['id'];self.wait_job(job)
  self.assertEqual(self.lib.jobs[job]['state'],'verified')
  self.assertEqual(self.calls[0][:4],('-s','quest','install','-r'))
  self.assertNotIn('-d',self.calls[0])
 def test_corrupt_stored_file_does_not_install(self):
  row=self.upload();self.lib.prepare(row['id'],'quest');self.devices[0]['state']='sideload'
  self.lib.file(row['id']).write_bytes(b'bad')
  job=self.lib.start(row['id'],'quest',True)['job']['id'];self.wait_job(job)
  self.assertEqual(self.lib.jobs[job]['state'],'failed');self.assertFalse(self.calls)
 def test_restart_marks_running_unknown(self):
  self.root.mkdir();(self.root/'jobs.json').write_text(json.dumps({'j':{'state':'running'}}))
  lib=UpdateLibrary(self.root,self.adb,lambda:[])
  self.assertEqual(lib.jobs['j']['state'],'interrupted')
 def test_failed_adb_is_not_success(self):
  row=self.upload();self.lib.prepare(row['id'],'quest');self.devices[0]['state']='sideload'
  self.lib.adb=lambda *a,**k:subprocess.CompletedProcess(a,1,'','failed')
  job=self.lib.start(row['id'],'quest',True)['job']['id'];self.wait_job(job)
  self.assertEqual(self.lib.jobs[job]['state'],'failed')
  self.lib.close_job(job);self.assertEqual(self.lib.jobs[job]['state'],'closed_unverified')

if __name__=='__main__':unittest.main()
