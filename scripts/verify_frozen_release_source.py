"""Read-only fixed release source and process verifier, no environment values."""
import argparse,base64,hashlib,json,subprocess,sys,textwrap,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT/'.runtime/zeabur-stage-ced7de7d'
ENV='6ab6168036d2a6cac409f0c6'
SERVICES={'staging':'6abc0821454b8f31a5ef614a','formal':'6ab61834a4c05a5bcb57ad69'}
FILES=('backend/app.py','backend/integration_routes.py','backend/source_sync.py','backend/source_case_policy.py','backend/production_access.py','backend/company_dashboard.py','scripts/run_service.py')
MARKER='YX_RELEASE_SOURCE='
REMOTE=r'''
import hashlib,json,os
from pathlib import Path
checks=[]
for name,wanted in expected.items():
 path=Path('/app')/name
 actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() and not path.is_symlink() else None
 checks.append({'path':name,'expected_sha256':wanted,'actual_sha256':actual,'match':actual==wanted})
processes=[]
for entry in Path('/proc').iterdir():
 if not entry.name.isdecimal():continue
 try:
  arguments=(entry/'cmdline').read_bytes().split(b'\0')
  if b'-c' in arguments:continue
  matched=[]
  if any(a.endswith(b'/scripts/run_service.py') or a==b'scripts/run_service.py' for a in arguments):matched.append('run_service')
  if b'uvicorn' in arguments and b'backend.app:app' in arguments:matched.append('web')
  if any(a.endswith(b'/scripts/run_worker.py') or a==b'scripts/run_worker.py' for a in arguments):matched.append('worker')
  if not matched:continue
  uid=None
  for line in (entry/'status').read_text().splitlines():
   if line.startswith('Uid:'):uid=int(line.split()[2])
  processes.extend({'name':name,'pid':int(entry.name),'effective_uid':uid}for name in matched)
 except (OSError,ValueError):continue
print('YX_RELEASE_SOURCE='+json.dumps({'checks':checks,'files_match':all(c['match'] for c in checks),'processes':processes,'web_and_worker_present':{'web','worker'}<=set(p['name']for p in processes)}))
'''


def expected_hashes():
 manifest_path=ROOT/'.runtime/zeabur-stage-ced7de7d-manifest.json'
 manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
 if Path(manifest['directory']).resolve()!=STAGE.resolve():raise ValueError('Frozen stage mismatch')
 entries={v['path']:v['sha256']for v in manifest['files']}
 expected={}
 for name in FILES:
  path=STAGE/name
  if path.is_symlink() or not path.is_file():raise ValueError('Frozen file missing or symlink')
  value=hashlib.sha256(path.read_bytes()).hexdigest()
  if entries.get(name)!=value:raise ValueError('Frozen file checksum mismatch')
  expected[name]=value
 return expected


def verify(target):
 if target not in SERVICES:raise ValueError('Unapproved service')
 expected=expected_hashes()
 source='import json\ntry:\n'+textwrap.indent('expected='+repr(expected)+'\n'+REMOTE,' ')+'\nexcept Exception as exc:\n print("YX_RELEASE_SOURCE="+json.dumps({"error_class":type(exc).__name__}))\n'
 encoded=base64.b64encode(zlib.compress(source.encode())).decode()
 launcher='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(encoded)+')))'
 command=['zeabur.cmd','service','exec','--id',SERVICES[target],'--env-id',ENV,'-i=false','--','python','-c',launcher]
 completed=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
 lines=[line.split(MARKER,1)[1]for line in completed.stdout.splitlines()if line.startswith(MARKER)]
 if completed.returncode or len(lines)!=1:raise RuntimeError('Read-only source verification transport failed')
 result=json.loads(lines[0])
 if result.get('error_class'):raise RuntimeError('Remote verifier failed')
 if len(result.get('checks',[]))!=len(FILES) or {v['path']for v in result['checks']}!=set(FILES):raise RuntimeError('Incomplete verification receipt')
 result.update(service_id=SERVICES[target],target=target,stage=STAGE.name,read_only=True,
  observed_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat())
 required={'run_service','web','worker'}
 processes=result.get('processes',[])
 result['runtime_uid_10001_verified']=required<={p.get('name')for p in processes} and all(p.get('effective_uid')==10001 for p in processes if p.get('name')in required)
 result['ok']=result['files_match'] and result['web_and_worker_present'] and result['runtime_uid_10001_verified']
 (ROOT/'.runtime'/('release-source-'+target+'-ced7de7d.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
 return result


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('target',choices=sorted(SERVICES))
 result=verify(parser.parse_args().target);print(json.dumps(result));return 0 if result['ok'] else 1

if __name__=='__main__':
 try:sys.exit(main())
 except Exception as exc:print(json.dumps({'ok':False,'error_class':type(exc).__name__,'read_only':True}));sys.exit(1)
