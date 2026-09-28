"""Per-device Android default-assistant controls over authorized ADB."""
import json
from pathlib import Path
import re
import shlex
import threading
import time
from usb_pairing import atomic_json

ROLE='android.app.role.ASSISTANT'
GOOGLE='com.google.android.googlequicksearchbox'
PACKAGE=re.compile(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+')
KEYS=('assistant','voice_interaction_service')

class AndroidAssistant:
    def __init__(self,adb,devices,path,xr_package=''):
        self.adb,self.devices,self.path,self.xr_package=adb,devices,Path(path),xr_package
        self.lock=threading.RLock()
        data=json.loads(self.path.read_text()) if self.path.exists() else {}
        self.saved=data.get("backups",{});self.history=data.get("history",[])

    def _save(self):
        atomic_json(self.path,{"version":1,"backups":self.saved,"history":self.history})

    def _shell(self,serial,*args):
        result=self.adb('-s',serial,'shell',shlex.join(str(a) for a in args),timeout=30)
        if result.returncode or re.search(r'(?:^|\n)(?:Error:|Exception|Failure|SecurityException)',result.stdout):
            raise ValueError('Android could not apply this assistant command. Unlock the device or use its assistant settings.')
        return result.stdout.strip()

    def _target(self,serial):
        if not isinstance(serial,str) or not any(d['serial']==serial and d['state']=='device' for d in self.devices()):
            raise ValueError('Select a connected, authorized Android device')
        user=self._shell(serial,'am','get-current-user')
        if not user.isdigit():raise ValueError('Unable to identify the active Android user')
        hardware=self._shell(serial,'getprop','ro.serialno')
        # Use the hardware serial across USB and wireless ADB. Never merge devices with missing IDs.
        if not hardware or hardware.lower() in ('unknown','null'):hardware=serial
        return user,json.dumps([hardware,user],separators=(',',':'))

    def _read(self,serial,user):
        holders=self._shell(serial,'cmd','role','get-role-holders','--user',user,ROLE).splitlines()
        if any(not PACKAGE.fullmatch(p) for p in holders):raise ValueError('Assistant role control is not supported on this device')
        settings={}
        for key in KEYS:
            value=self._shell(serial,'settings','--user',user,'get','secure',key)
            settings[key]=None if value=='null' else value
        return {'holders':holders,'settings':settings}

    def _installed(self,serial,user,package):
        if not package or not PACKAGE.fullmatch(package):return False
        result=self.adb('-s',serial,'shell',shlex.join(['pm','path','--user',user,package]),timeout=30)
        return result.returncode==0 and result.stdout.strip().startswith('package:')

    def _restore(self,serial,user,state):
        self._shell(serial,'cmd','role','clear-role-holders','--user',user,ROLE)
        for package in state['holders']:
            if not PACKAGE.fullmatch(package):raise ValueError('Invalid saved assistant package')
            self._shell(serial,'cmd','role','add-role-holder','--user',user,ROLE,package)
        for key in KEYS:
            value=state['settings'][key]
            if value is None:self._shell(serial,'settings','--user',user,'delete','secure',key)
            else:self._shell(serial,'settings','--user',user,'put','secure',key,value)

    def status(self,serial):
        with self.lock:
            user,key=self._target(serial);state=self._read(serial,user)
            names=state['holders'] or [v.split('/')[0] for v in state['settings'].values() if v]
            label='Off' if not names else 'Google / Gemini' if GOOGLE in names else 'XR Assistant' if self.xr_package and self.xr_package in names else ', '.join(dict.fromkeys(names))
            return {'serial':serial,'android_user':user,'current':label,'restore_available':key in self.saved,
                    'google_available':self._installed(serial,user,GOOGLE),
                    'xr_available':self._installed(serial,user,self.xr_package)}

    def action(self,serial,action):
        if action not in ('off','google','xr','restore','settings'):raise ValueError('Unknown assistant action')
        with self.lock:
            user,key=self._target(serial)
            if action=='settings':
                out=self._shell(serial,'am','start','--user',user,'-a','android.settings.VOICE_INPUT_SETTINGS')
                if 'Error' in out:raise ValueError('Open Settings → Apps → Default apps → Digital assistant app on the device')
                return {'message':'Assistant settings opened on the selected device. Confirm your choice there, then refresh.'}
            before=self._read(serial,user)
            if action=='restore' and key not in self.saved:raise ValueError('No previous assistant has been saved for this device and Android user')
            package=GOOGLE if action=='google' else self.xr_package if action=='xr' else ''
            if action in ('google','xr') and not self._installed(serial,user,package):
                raise ValueError('This assistant is not installed or configured on the selected device')
            # Capture the most recent configuration before a managed change; keep it until restored.
            if key not in self.saved:
                self.saved[key]=before
            self.history.append({"device":key,"serial":serial,"android_user":user,"action":action,"saved_at":time.time(),"previous":before})
            self._save()
            try:
                if action=='restore':self._restore(serial,user,self.saved[key])
                elif action=='off':
                    self._shell(serial,'cmd','role','clear-role-holders','--user',user,ROLE)
                    for setting in KEYS:self._shell(serial,'settings','--user',user,'put','secure',setting,'')
                else:self._shell(serial,'cmd','role','add-role-holder','--user',user,ROLE,package)
                after=self._read(serial,user)
                valid=(after==self.saved[key]) if action=='restore' else (not after['holders'] and not any(after['settings'].values())) if action=='off' else package in after['holders']
                if not valid:raise ValueError('Android did not retain the requested assistant setting')
            except Exception as error:
                try:self._restore(serial,user,before)
                except Exception:raise ValueError('Assistant change failed and could not be fully restored. Open assistant settings on the selected device to check it.') from error
                raise ValueError('Assistant change was not applied; the previous configuration was restored. Use assistant settings on the device.') from error
            if action=='restore':del self.saved[key];self._save()
            return {'message':{'off':'Default assistant turned off on this device. The Gemini app can still be opened manually.',
                               'google':'Google assistant selected. Choose Gemini inside Google’s settings if needed.',
                               'xr':'XR Assistant selected on this device.',
                               'restore':'Previous assistant restored on this device.'}[action]}
