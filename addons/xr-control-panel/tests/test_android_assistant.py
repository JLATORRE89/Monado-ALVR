import json,shlex,subprocess,tempfile,unittest
from pathlib import Path
from android_assistant import AndroidAssistant,GOOGLE,ROLE

class AssistantTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'backups.json'
  self.devices=[{'serial':'TAB','state':'device'},{'serial':'QUEST','state':'device'}]
  self.roles={'TAB':[GOOGLE],'QUEST':['com.example.quest']}
  self.settings={s:{'assistant':self.roles[s][0]+'/.Assist','voice_interaction_service':self.roles[s][0]+'/.Voice'} for s in self.roles}
  self.calls=[];self.fail=False
  self.manager=AndroidAssistant(self.adb,lambda:self.devices,self.path)
 def tearDown(self):self.tmp.cleanup()
 def adb(self,*args,**kw):
  self.calls.append(args);self.assertEqual(args[0],'-s');serial=args[1];cmd=shlex.split(args[3]);out=''
  if cmd==['am','get-current-user']:out='0'
  elif cmd[:2]==['getprop','ro.serialno']:out=serial
  elif cmd[:2]==['cmd','role']:
   if cmd[2]=='get-role-holders':out='\n'.join(self.roles[serial])
   elif cmd[2]=='clear-role-holders':self.roles[serial]=[]
   elif cmd[2]=='add-role-holder':self.roles[serial]=[cmd[-1]]
  elif cmd[0]=='settings':
   op,key=cmd[3],cmd[5]
   if op=='get':out=self.settings[serial].get(key) or 'null'
   elif op=='put':
    if self.fail:self.fail=False;return subprocess.CompletedProcess(args,1,'','denied')
    self.settings[serial][key]=cmd[6]
   elif op=='delete':self.settings[serial][key]=None
  elif cmd[:2]==['pm','path']:out='package:/data/app/google.apk' if cmd[-1]==GOOGLE and serial=='TAB' else ''
  elif cmd[:2]==['am','start']:out='Starting: Intent'
  else:raise AssertionError(cmd)
  return subprocess.CompletedProcess(args,0,out,'')
 def test_off_restore_isolated_and_history_survives(self):
  original=json.loads(json.dumps(self.settings));self.manager.action('TAB','off')
  self.assertEqual(self.manager.status('TAB')['current'],'Off');self.assertEqual(self.settings['QUEST'],original['QUEST'])
  self.assertEqual(self.path.stat().st_mode&0o777,0o600)
  # A new server process can restore the saved configuration.
  other=AndroidAssistant(self.adb,lambda:self.devices,self.path);other.action('TAB','restore')
  self.assertEqual(self.settings,original);data=json.loads(self.path.read_text())
  self.assertEqual(len(data['history']),2);self.assertFalse(data['backups'])
  self.assertEqual(data['history'][0]['previous']['settings'],original['TAB'])
 def test_unavailable_xr_and_unknown_device_do_not_mutate(self):
  with self.assertRaises(ValueError):self.manager.action('OTHER','off')
  with self.assertRaises(ValueError):self.manager.action('TAB','xr')
  self.assertFalse(self.path.exists());self.assertEqual(self.roles['TAB'],[GOOGLE])
 def test_failure_rolls_back_before_reporting(self):
  original=json.loads(json.dumps(self.settings));self.fail=True
  with self.assertRaisesRegex(ValueError,'restored'):self.manager.action('TAB','off')
  self.assertEqual(self.roles['TAB'],[GOOGLE]);self.assertEqual(self.settings,original)
 def test_settings_only_opens_selected_device(self):
  self.manager.action('QUEST','settings');self.assertFalse(self.path.exists())
  self.assertTrue(all(c[1]=='QUEST' for c in self.calls))
 def test_google_unavailable_on_quest(self):
  self.assertFalse(self.manager.status('QUEST')['google_available'])
  with self.assertRaises(ValueError):self.manager.action('QUEST','google')
  self.assertEqual(self.roles['QUEST'],['com.example.quest'])
if __name__=='__main__':unittest.main()
