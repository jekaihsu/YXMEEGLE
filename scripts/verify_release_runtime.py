"""Read-only release verification through the authenticated Zeabur CLI.

Only file hashes, process names, booleans and aggregate counts are returned.
No credential or business record is printed.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'


def main():
    manifest = json.loads((RUNTIME / 'zeabur-stage-manifest.json').read_text(encoding='utf-8'))
    expected = {item['path']: item['sha256'] for item in manifest['files']
                if item['path'].startswith(('backend/', 'scripts/', 'deployment/'))}
    assets = sorted(re.findall(r'(?:src|href)="(/assets/[^"]+)"',
                              (ROOT / 'frontend/dist/index.html').read_text(encoding='utf-8')))
    prepared = json.loads((RUNTIME / 'release-settings-request.json').read_text(encoding='utf-8'))
    setting_hashes = {key: hashlib.sha256(value.encode()).hexdigest()
                      for key, value in prepared['variables']['data'].items()}
    remote = r'''
import hashlib,json,os,re,urllib.request
from pathlib import Path
expected=EXPECTED_FILES
expected_assets=EXPECTED_ASSETS
setting_hashes=EXPECTED_SETTINGS
files={name:Path('/app',name).is_file() and hashlib.sha256(Path('/app',name).read_bytes()).hexdigest()==digest for name,digest in expected.items()}
assets=sorted(re.findall(r'(?:src|href)="(/assets/[^"]+)"',Path('/app/frontend/dist/index.html').read_text()))
processes=[]
for p in Path('/proc').iterdir():
    if not p.name.isdecimal(): continue
    try: cmd=(p/'cmdline').read_bytes().replace(b'\x00',b' ').decode(errors='replace')
    except (OSError,PermissionError): continue
    if 'python' not in cmd or ' -c ' in cmd: continue
    for name in ['scripts/run_service.py','uvicorn','scripts/run_worker.py']:
        if name in cmd: processes.append(name)
with urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/api/health',timeout=10) as response:
    health=json.load(response)
settings={key:hashlib.sha256(os.environ.get(key,'').encode()).hexdigest()==value for key,value in setting_hashes.items()}
result={'files_match':all(files.values()),'file_checks':files,'assets_match':assets==expected_assets,'assets':assets,'processes':sorted(set(processes)),'settings_match':settings,'health':health}
result['ok']=result['files_match'] and result['assets_match'] and all(settings.values()) and health.get('status')=='ok' and health.get('database')=='postgresql' and all(name in processes for name in ['scripts/run_service.py','uvicorn','scripts/run_worker.py'])
print('YX_RELEASE_RESULT='+json.dumps(result))
'''.replace('EXPECTED_FILES', repr(expected)).replace('EXPECTED_ASSETS', repr(assets)).replace('EXPECTED_SETTINGS', repr(setting_hashes))
    encoded = base64.b64encode(zlib.compress(remote.encode())).decode()
    launcher = 'import base64,zlib;exec(zlib.decompress(base64.b64decode(' + repr(encoded) + ')))'
    command = ['zeabur.cmd', 'service', 'exec', '--id', '6ab61834a4c05a5bcb57ad69',
               '--env-id', '6ab6168036d2a6cac409f0c6', '-i=false', '--', 'python', '-c', launcher]
    completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
    lines = [line.split('YX_RELEASE_RESULT=', 1)[1] for line in completed.stdout.splitlines()
             if line.startswith('YX_RELEASE_RESULT=')]
    if completed.returncode or len(lines) != 1:
        raise SystemExit('Runtime verification transport failed; no result accepted')
    result = json.loads(lines[0])
    (RUNTIME / 'release-runtime-verification-20260927.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
    raise SystemExit(0 if result['ok'] else 1)


if __name__ == '__main__':
    main()
