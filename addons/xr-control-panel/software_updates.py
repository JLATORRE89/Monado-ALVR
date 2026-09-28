"""Offline APK/OTA library and explicit, serial-scoped update jobs (stdlib only)."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tarfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "xr-downloader"))
from xr_downloader import validate_manifest, member_name, SCHEMA, MAX_TOTAL, REQUEST_SCHEMA, APP_CATALOG, validate_request
import threading
import time
import uuid
import zipfile
from usb_pairing import atomic_json

ID = re.compile(r'^[a-f0-9]{64}$')
PACKAGE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$')
MAX_UPLOAD = 16 * 1024**3


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def inspect_package(path, kind, aapt):
    with zipfile.ZipFile(path) as z:
        if kind == 'firmware':
            info = z.getinfo('META-INF/com/android/metadata')
            if info.file_size > 65536:
                raise ValueError('OTA metadata is too large')
            meta = dict(line.split('=', 1) for line in z.read(info).decode().splitlines() if '=' in line)
            if not all(meta.get(k) for k in ('pre-device','post-build-incremental','post-timestamp')):
                raise ValueError('Firmware needs model, target build and timestamp metadata')
            if 'payload.bin' not in z.namelist() and 'META-INF/com/google/android/update-binary' not in z.namelist():
                raise ValueError('This ZIP does not contain an OTA update')
            if any(meta.get(k, '').lower() in ('yes','true','1') for k in ('ota-wipe','ota-downgrade','spl-downgrade')):
                raise ValueError('Wipe and downgrade firmware packages are not supported')
            if not meta['post-timestamp'].isdigit():
                raise ValueError('Invalid firmware build timestamp')
            return {'label':'Quest system firmware','version':meta['post-build-incremental'],'models':meta['pre-device'], 'metadata':meta}
        if 'AndroidManifest.xml' not in z.namelist():
            raise ValueError('Not an Android APK')
    if not aapt:
        raise ValueError('Android SDK aapt2 is required to read APK versions; configure aapt in panel config')
    result = subprocess.run([aapt,'dump','badging',str(path)],capture_output=True,text=True,timeout=30)
    match = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'",result.stdout,re.M)
    if result.returncode or not match or not PACKAGE.fullmatch(match[1]):
        raise ValueError('Unable to read APK package/version; use a complete, standalone APK')
    if re.search(r"^package:.*\bsplit=",result.stdout,re.M):
        raise ValueError('Split APKs are not supported; upload a standalone APK')
    label = re.search(r"^application-label:'(.*)'$",result.stdout,re.M)
    return {'package':match[1],'version_code':int(match[2]),'version':match[3], 'label':label[1] if label else match[1]}


class UpdateLibrary:
    def __init__(self, root, adb, devices, aapt=None):
        self.root=Path(root); self.adb=adb; self.devices=devices; self.aapt=aapt
        self.lock=threading.RLock();self.prepared={}
        self.sources_path=self.root/"sources.json"
        self.sources=json.loads(self.sources_path.read_text()) if self.sources_path.exists() else {}
        self.jobs_path=self.root/'jobs.json'
        self.jobs=json.loads(self.jobs_path.read_text()) if self.jobs_path.exists() else {}
        for job in self.jobs.values():
            if job['state'] in ('queued','running'):
                job.update(state='interrupted',message='Panel restarted; inspect the headset before retrying. Installation outcome is unknown.')
        if self.jobs:self._save_jobs()

    def _save_jobs(self): atomic_json(self.jobs_path,self.jobs)

    def get(self, ident):
        if not ID.fullmatch(str(ident)):raise ValueError('Invalid update ID')
        info=self.root/ident/'info.json'
        if not info.is_file():raise ValueError('Update not found')
        return json.loads(info.read_text())

    def file(self, ident):
        row=self.get(ident)
        return self.root/ident/('package.apk' if row['kind']=='apk' else 'package.zip')

    def listing(self):
        with self.lock:
            rows=[json.loads(p.read_text()) for p in self.root.glob('*/info.json') if ID.fullmatch(p.parent.name)]
            return {'updates':sorted(rows,key=lambda x:-x['stored_at']), 'jobs':sorted(self.jobs.values(),key=lambda x:-x['started']),
                    'devices':self.devices(), 'apk_inspection_available':bool(self.aapt), 'sources':list(self.sources.values()), 'catalog':[{'name':v['name'],'kind':'apk','package':k,'resolve':'catalog'} for k,v in APP_CATALOG.items()]}

    def upload(self, name, kind, length, stream, expected=''):
        if kind not in ('apk','firmware'):raise ValueError('Choose APK or firmware')
        if not 0 < length <= MAX_UPLOAD:raise ValueError('Update files must be between 1 byte and 16 GiB')
        if not name.lower().endswith('.apk' if kind=='apk' else '.zip'):raise ValueError('Wrong file extension for update type')
        if expected and not ID.fullmatch(expected.lower()):raise ValueError('Expected SHA-256 must contain 64 hexadecimal characters')
        self.root.mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(self.root).free < length + 256*1024**2:raise ValueError('Not enough disk space to store this update')
        temp=Path(tempfile.mkdtemp(prefix='.upload-',dir=self.root))
        try:
            file=temp/('package.apk' if kind=='apk' else 'package.zip')
            with file.open('wb') as out:
                remaining=length
                while remaining:
                    data=stream.read(min(1024*1024,remaining))
                    if not data:raise ValueError('Update upload was interrupted')
                    out.write(data);remaining-=len(data)
            sha=digest(file)
            if expected and sha!=expected.lower():raise ValueError('SHA-256 does not match; file was not stored')
            try: metadata=inspect_package(file,kind,self.aapt)
            except (zipfile.BadZipFile,KeyError,UnicodeError) as e:raise ValueError('Invalid update archive or missing metadata') from e
            row=dict(metadata,id=sha,sha256=sha,kind=kind,size=length,filename=Path(name).name[:180],stored_at=time.time())
            atomic_json(temp/'info.json',row)
            with self.lock:
                dest=self.root/sha
                if dest.exists():return {'message':'This update is already stored','update':self.get(sha)}
                os.replace(temp,dest)
            return {'message':'Update stored for offline use','update':row}
        finally:
            if temp.exists():shutil.rmtree(temp)

    def save_source(self, app):
        automatic = app.get('resolve') == 'catalog'
        (validate_request if automatic else validate_manifest)({'schema':REQUEST_SCHEMA if automatic else SCHEMA,'applications':[app]})
        key = 'app:' + app['package'] if automatic else app['sha256']
        app = dict(app, source_id=key)
        with self.lock:
            self.sources[key]=app
            atomic_json(self.sources_path,self.sources)
        return {'message':'Supported download saved'}

    def remove_source(self, sha):
        with self.lock:
            if sha not in self.sources:raise ValueError('Download definition not found')
            del self.sources[sha];atomic_json(self.sources_path,self.sources)
        return {'message':'Download definition removed; stored update files remain available'}

    def export_manifest(self):
        with self.lock:
            apps=list(self.sources.values())
            automatic=any(a.get('resolve')=='catalog' for a in apps)
            manifest={'schema':REQUEST_SCHEMA if automatic else SCHEMA,'applications':apps}
            return (validate_request if automatic else validate_manifest)(manifest)

    def import_bundle(self, length, stream):
        if not 0 < length <= MAX_TOTAL:raise ValueError('Bundle must be between 1 byte and 64 GiB')
        self.root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.bundle-',dir=self.root) as folder:
            temp=Path(folder);bundle=temp/'bundle.tar.gz'
            if shutil.disk_usage(self.root).free < length+256*1024**2:raise ValueError('Not enough space for bundle upload')
            with bundle.open('wb') as target:
                remaining=length
                while remaining:
                    chunk=stream.read(min(1024*1024,remaining))
                    if not chunk:raise ValueError('Bundle upload interrupted')
                    target.write(chunk);remaining-=len(chunk)
            staged=UpdateLibrary(temp/'staged',self.adb,lambda:[],self.aapt)
            try:
                with tarfile.open(bundle,'r|gz') as archive:
                    first=archive.next()
                    if not first or first.name!='manifest.json' or not first.isfile() or first.size>1024*1024:
                        raise ValueError('Bundle must start with manifest.json (maximum 1 MiB)')
                    manifest=validate_manifest(json.load(archive.extractfile(first)))
                    expected={member_name(app):app for app in manifest['applications']};seen=set();total=0
                    for member in archive:
                        if member.name=='manifest.json' and member is first:continue
                        if not member.isfile() or member.name not in expected or member.name in seen:
                            raise ValueError('Bundle contains an unexpected, duplicate or unsafe entry')
                        app=expected[member.name];total+=member.size
                        if total>MAX_TOTAL or not 0<member.size<=MAX_UPLOAD:raise ValueError('Bundle contents exceed size limit')
                        if app.get('size') and member.size!=app['size']:raise ValueError('Bundle file size differs from manifest')
                        row=staged.upload(member.name,app['kind'],member.size,archive.extractfile(member),app['sha256'])['update']
                        if app.get('package') and row.get('package')!=app['package']:raise ValueError('APK package name differs from manifest')
                        if app.get('version_code') is not None and row.get('version_code')!=app['version_code']:raise ValueError('APK version differs from manifest')
                        seen.add(member.name)
                    if seen!=set(expected):raise ValueError('Bundle is incomplete; missing update files')
            except (tarfile.TarError,EOFError,json.JSONDecodeError) as e:
                raise ValueError('Invalid or incomplete XR bundle') from e
            # Publish only after every member, digest and update format has been validated.
            added=[]
            with self.lock:
                old_sources=dict(self.sources)
                try:
                    for app in manifest['applications']:
                        dest=self.root/app['sha256']
                        if not dest.exists():
                            os.replace(staged.root/app['sha256'],dest);added.append(dest)
                        self.sources[app['sha256']]=app
                    atomic_json(self.sources_path,self.sources)
                except Exception:
                    self.sources=old_sources
                    for dest in added:shutil.rmtree(dest)
                    raise
            return {'message':f"Imported {len(seen)} verified updates for offline use"}

    def remove(self, ident):
        with self.lock:
            self.get(ident)
            if any(j['update']==ident and j['state'] in ('queued','running','awaiting_verification') for j in self.jobs.values()):
                raise ValueError('Update is in use by an unfinished job')
            shutil.rmtree(self.root/ident)
            return {'message':'Stored update removed; installed headset software is unchanged'}

    def device(self, serial, state='device'):
        dev=next((d for d in self.devices() if d['serial']==serial and d['state']==state),None)
        if not dev:raise ValueError('Selected device is not connected in the required mode: '+state)
        return dev

    def identity(self, serial):
        self.device(serial)
        result=self.adb('-s',serial,'shell','pm path com.oculus.vrshell; getprop ro.product.device; getprop ro.build.version.incremental; getprop ro.build.fingerprint; getprop ro.build.date.utc; dumpsys battery')
        lines=result.stdout.strip().splitlines()
        if result.returncode or len(lines)<6 or not lines[0].startswith('package:'):raise ValueError('Unable to identify a Quest headset')
        battery=re.search(r'level:\s*(\d+)',result.stdout)
        return dict(model=lines[1],build=lines[2],fingerprint=lines[3],timestamp=int(lines[4]),battery=int(battery[1]) if battery else 0)

    def prepare(self, ident, serial):
        with self.lock:
            row=self.get(ident)
            if row['kind']!='firmware':raise ValueError('Preparation is only needed for firmware')
            if not self.device(serial).get('usb_path'):raise ValueError('Firmware preparation requires a physical USB connection')
            info=self.identity(serial);meta=row['metadata']
            if info['model'] not in meta['pre-device'].split('|'):raise ValueError('Firmware does not match this headset model')
            for key,field in [('pre-build-incremental','build'),('pre-build','fingerprint')]:
                if meta.get(key) and info[field] not in meta[key].split('|'):raise ValueError('Incremental firmware requires a different installed build')
            if int(meta['post-timestamp'])<=info['timestamp']:raise ValueError('Firmware must be newer than the installed build')
            if info['battery']<50:raise ValueError('Charge the headset to at least 50% before firmware installation')
            self.prepared[(ident,serial)]=dict(info,expires=time.time()+1800)
            return {'message':'Compatibility checked. Keep USB connected. Power off the headset, hold Power + Volume Down, then select Sideload update. Select this same headset and Install stored update when ready.', 'identity':info}

    def start(self, ident, serial, confirmed):
        with self.lock:
            row=self.get(ident)
            if confirmed is not True:raise ValueError('Confirm installation on the selected device')
            if any(j['serial']==serial and j['state'] in ('queued','running','awaiting_verification') for j in self.jobs.values()):raise ValueError('This device already has an unfinished update job')
            if row['kind']=='firmware':
                self.device(serial,'sideload')
                if self.prepared.get((ident,serial),{}).get('expires',0)<time.time():raise ValueError('Check firmware compatibility while the headset is booted normally first')
                self.prepared.pop((ident,serial),None)
            else:self.device(serial)
            job=dict(id=uuid.uuid4().hex,update=ident,serial=serial,label=row['label'],kind=row['kind'],state='queued',started=time.time(),message='Queued')
            self.jobs[job['id']]=job;self._save_jobs()
            threading.Thread(target=self._install,args=(job['id'],),daemon=True).start()
            return {'message':'Update job started','job':dict(job)}

    def _set(self, job, **values):
        with self.lock:self.jobs[job].update(values);self._save_jobs()

    def _install(self, job_id):
        job=self.jobs[job_id]
        try:
            row=self.get(job['update']);path=self.file(row['id'])
            self._set(job_id,state='running',message='Checking stored file, then transferring. Keep the device connected.')
            if digest(path)!=row['sha256']:raise ValueError('Stored update checksum changed; upload a clean copy')
            args=('install','-r',str(path)) if row['kind']=='apk' else ('sideload',str(path))
            result=self.adb('-s',job['serial'],*args,timeout=1800)
            if result.returncode:raise RuntimeError((result.stdout+'\n'+result.stderr).strip()[-2000:] or 'ADB update failed')
            if row['kind']=='apk' and not re.search(r'^Success\s*$',result.stdout,re.M):raise RuntimeError('Android did not confirm APK installation: '+result.stdout[-1500:])
            self._set(job_id,state='awaiting_verification',message='Transfer finished. Wait for normal boot, reconnect USB debugging, then Verify installed version.')
            if row['kind']=='apk':self.verify(job_id)
        except Exception as e:self._set(job_id,state='failed',message=str(e)[:2000])

    def close_job(self, job_id):
        with self.lock:
            job=self.jobs.get(job_id)
            if not job or job['state'] not in ('awaiting_verification','interrupted','failed'):
                raise ValueError('Only an inactive, unverified job can be closed')
            self._set(job_id,state='closed_unverified',message='Closed by operator without verification; check the headset before retrying.')
            return {'message':'Job closed without claiming installation success'}

    def verify(self, job_id):
        with self.lock:
            job=self.jobs.get(job_id)
            if not job or job['state'] not in ('awaiting_verification','interrupted','failed'):raise ValueError('Job is not ready for verification')
            row=self.get(job['update'])
            if row['kind']=='firmware':
                info=self.identity(job['serial'])
                if info['build']!=row['version'] or info['model'] not in row['models'].split('|'):raise ValueError('Target firmware is not yet installed; check recovery/boot status on the headset')
            else:
                self.device(job['serial'])
                result=self.adb('-s',job['serial'],'shell','dumpsys','package',row['package'])
                version=re.search(r'\bversionCode=(\d+)',result.stdout)
                if result.returncode or not version or int(version[1])!=row['version_code']:raise ValueError('Installed APK version does not match the stored update')
            self._set(job_id,state='verified',message='Installed version verified on the device')
            return {'message':'Installed version verified'}
