#!/usr/bin/env python3
"""Standalone Linux/Windows offline XR download packager. Python 3.11+, stdlib only."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile

SCHEMA = 'xr-offline-updates-v1'
MAX_FILE = 16 * 1024**3
MAX_TOTAL = 64 * 1024**3


REQUEST_SCHEMA = 'xr-download-request-v1'
# Explicit publisher mappings prevent resolving a similarly named but different app.
APP_CATALOG = {
    'alvr.client.stable': {'name': 'ALVR', 'repository': 'alvr-org/ALVR', 'asset': 'alvr_client_android.apk'},
    'alvr.client.monado': {'name': 'ALVR for Monado', 'repository': 'JLATORRE89/ALVR', 'asset': 'alvr_client_openxr.apk'},
}

def validate_request(data):
    if not isinstance(data, dict) or data.get('schema') != REQUEST_SCHEMA:
        raise ValueError('Unsupported app selection format')
    apps = data.get('applications')
    if not isinstance(apps, list) or not 1 <= len(apps) <= 128:
        raise ValueError('Select between 1 and 128 apps')
    seen=set()
    for app in apps:
        if not isinstance(app,dict):raise ValueError('Invalid app selection')
        if app.get('resolve') == 'catalog':
            package=app.get('package','')
            if app.get('kind')!='apk' or not isinstance(package,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+',package):
                raise ValueError('An automatic download needs a valid Quest app identity')
            if not isinstance(app.get('name'),str) or not app['name'].strip():raise ValueError('App name is missing')
            key=package
        else:
            validate_manifest({'schema':SCHEMA,'applications':[app]});key=app['sha256']
        if key in seen:raise ValueError('Duplicate app selection')
        seen.add(key)
    return data


def resolve_requests(data, progress=print):
    validate_request(data)
    resolved=[];errors=[]
    for app in data['applications']:
        if app.get('resolve')!='catalog':resolved.append(dict(app));continue
        package=app['package'];publisher=APP_CATALOG.get(package)
        if not publisher:
            errors.append(f"{app['name']} ({package}): no supported publisher download is available. Store-managed apps may require the headset's store.")
            continue
        progress(f"Finding the latest published release for {app['name']}…")
        try:
            request=urllib.request.Request('https://api.github.com/repos/'+publisher['repository']+'/releases/latest',
                headers={'User-Agent':'XR-Downloader/2','Accept':'application/vnd.github+json'})
            with urllib.request.urlopen(request,timeout=30) as response:
                raw=response.read(2*1024*1024+1)
                if len(raw)>2*1024*1024:raise ValueError('Release metadata is too large')
                release=json.loads(raw)
            assets=[a for a in release.get('assets',[]) if a.get('name')==publisher['asset']]
            if len(assets)!=1:raise ValueError('The publisher has no matching standalone APK in this release')
            asset=assets[0];digest=asset.get('digest') or ''
            if not re.fullmatch(r'sha256:[a-f0-9]{64}',digest):
                raise ValueError('The publisher did not provide a verifiable SHA-256 for this release')
            url=asset['browser_download_url']
            expected='https://github.com/'+publisher['repository']+'/releases/download/'
            if not url.startswith(expected):raise ValueError('Unexpected publisher download URL')
            resolved.append({'name':app['name'],'kind':'apk','package':package,'version':release['tag_name'],
                             'url':url,'sha256':digest[7:],'size':asset['size']})
        except Exception as e:
            errors.append(f"{app['name']}: no downloadable verified release was found ({e})")
    if errors:raise ValueError('Unable to prepare the complete bundle:\n'+'\n'.join(errors))
    return validate_manifest({'schema':SCHEMA,'applications':resolved})


def validate_manifest(data):
    if not isinstance(data, dict) or data.get('schema') != SCHEMA:
        raise ValueError('Unsupported download-list format')
    apps = data.get('applications')
    if not isinstance(apps, list) or not 1 <= len(apps) <= 128:
        raise ValueError('Download list must contain between 1 and 128 applications/firmware packages')
    seen = set()
    for app in apps:
        if not isinstance(app, dict): raise ValueError('Invalid application entry')
        sha = app.get('sha256', '')
        if not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{64}', sha): raise ValueError('Every download needs a lowercase SHA-256 checksum')
        if sha in seen: raise ValueError('Duplicate file checksum in download list')
        seen.add(sha)
        if app.get('kind') not in ('apk', 'firmware'): raise ValueError('Download kind must be apk or firmware')
        if not isinstance(app.get('name'),str) or not app['name'].strip(): raise ValueError('Each download needs a name')
        url = app.get('url','')
        if not isinstance(url,str): raise ValueError('Download URL must be text')
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f"{app['name']}: provide a direct HTTP(S) download URL without embedded credentials")
        if 'size' in app and (type(app['size']) is not int or not 0 < app['size'] <= MAX_FILE): raise ValueError('Invalid download size')
    return data


def member_name(app):
    return 'files/' + app['sha256'] + ('.apk' if app['kind']=='apk' else '.zip')


class HttpRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed=urllib.parse.urlsplit(newurl)
        if parsed.scheme not in ('http','https') or parsed.username or parsed.password:
            raise ValueError('Download redirected to an unsupported URL')
        if urllib.parse.urlsplit(req.full_url).scheme=='https' and parsed.scheme!='https':
            raise ValueError('Refusing a download redirect from HTTPS to HTTP')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def create_bundle(manifest, output, progress=print):
    if manifest.get('schema') == REQUEST_SCHEMA:
        manifest=resolve_requests(manifest,progress)
    validate_manifest(manifest)
    output=Path(output).expanduser().resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists(): raise ValueError('Output already exists; choose another filename')
    # Work next to the output so final publication is atomic on Linux and Windows.
    with tempfile.TemporaryDirectory(prefix='.xr-download-',dir=output.parent) as folder:
        work=Path(folder); total=0; files=[]
        opener=urllib.request.build_opener(HttpRedirects())
        for index,app in enumerate(manifest['applications'],1):
            progress(f"Downloading {index}/{len(manifest['applications'])}: {app['name']}")
            path=work/app['sha256']; count=0; sha=hashlib.sha256()
            request=urllib.request.Request(app['url'],headers={'User-Agent':'XR-Downloader/1','Accept-Encoding':'identity'})
            with opener.open(request,timeout=60) as response, path.open('wb') as target:
                declared=response.headers.get('Content-Length')
                if declared and int(declared)>MAX_FILE: raise ValueError('Download exceeds 16 GiB')
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk: break
                    count+=len(chunk);total+=len(chunk)
                    if count>MAX_FILE or total>MAX_TOTAL: raise ValueError('Download size limit exceeded')
                    if shutil.disk_usage(work).free < len(chunk)+64*1024**2: raise ValueError('Not enough free disk space')
                    target.write(chunk);sha.update(chunk)
            if not count or (declared and count!=int(declared)): raise ValueError(f"{app['name']}: incomplete download")
            if app.get('size') and count!=app['size']: raise ValueError(f"{app['name']}: download size did not match")
            if sha.hexdigest()!=app['sha256']: raise ValueError(f"{app['name']}: SHA-256 mismatch; no bundle was produced")
            try:
                with zipfile.ZipFile(path) as package:
                    required = 'AndroidManifest.xml' if app['kind']=='apk' else 'META-INF/com/android/metadata'
                    if required not in package.namelist(): raise ValueError(f"{app['name']}: downloaded file is not the declared update type")
            except zipfile.BadZipFile as e:
                raise ValueError(f"{app['name']}: downloaded file is not a valid update archive") from e
            files.append((app,path,count))
        progress('All files verified. Creating tar.gz at maximum gzip compression (level 9)…')
        bundle=work/'bundle.tar.gz'
        payload=json.dumps(manifest,indent=2).encode()+b'\n'
        with bundle.open('wb') as raw, gzip.GzipFile(fileobj=raw,mode='wb',filename='',compresslevel=9,mtime=0) as gz, tarfile.open(fileobj=gz,mode='w|',format=tarfile.USTAR_FORMAT) as archive:
            entry=tarfile.TarInfo('manifest.json');entry.size=len(payload);entry.mode=0o644
            archive.addfile(entry,io.BytesIO(payload))
            for app,path,count in files:
                entry=tarfile.TarInfo(member_name(app));entry.size=count;entry.mode=0o644
                with path.open('rb') as source:archive.addfile(entry,source)
        # Avoid silently replacing an existing user file, including a concurrent run's output.
        try:
            os.link(bundle,output)
        except FileExistsError:raise ValueError('Output already exists; choose another filename')
        except OSError:
            with output.open('xb') as dest, bundle.open('rb') as source:
                try:shutil.copyfileobj(source,dest,1024*1024)
                except BaseException:
                    dest.close();output.unlink(missing_ok=True);raise
        progress(f'Ready: {output}')
        return output


def main():
    parser=argparse.ArgumentParser(description='Download a panel JSON list into one fully verified offline tar.gz. XR Control Panel is not required.')
    parser.add_argument('manifest',type=Path,help='JSON download list exported from XR Control Panel')
    parser.add_argument('-o','--output',type=Path,default=Path('xr-offline-updates.tar.gz'))
    args=parser.parse_args()
    try:
        if args.manifest.stat().st_size>1024*1024:raise ValueError('Download list exceeds 1 MiB')
        create_bundle(json.loads(args.manifest.read_text(encoding='utf-8')),args.output)
    except (Exception,KeyboardInterrupt) as e:
        parser.exit(1,f'XR Downloader: {e or "cancelled"}\n')

if __name__=='__main__':main()
