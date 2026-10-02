"""Fixed, reversible formal uploads ownership repair. plan/apply/status only."""
import argparse,base64,hashlib,json,subprocess,sys,textwrap,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.runtime/formal-upload-permissions'
SERVICE='6ab61834a4c05a5bcb57ad69'
ENV='6ab6168036d2a6cac409f0c6'
MARKER='YX_UPLOAD_PERMISSIONS='
COMMON=r'''
import hashlib,json,os,stat,re,subprocess,sys,textwrap
from pathlib import Path
root=Path('/data/uploads');journal=Path('/tmp/yx-uploads-permission-repair-20260930')
def ensure(value):
 if not value:raise RuntimeError('Preflight condition changed')
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def scan():
 ensure(os.environ.get('UPLOAD_DIR')==str(root))
 for path in (Path('/'),Path('/data'),root):
  s=path.lstat();ensure(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode))
 mounts=[line.split(' - ',1)[0].split()[4]for line in Path('/proc/self/mountinfo').read_text().splitlines()]
 ensure(str(root) in mounts)
 paths=[root];children=sorted(root.iterdir());ensure(len(children)==2)
 for directory in children:
  s=directory.lstat();ensure(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode) and re.fullmatch(r'[a-f0-9]{64}',directory.name))
  paths.append(directory)
  files=list(directory.iterdir());ensure(len(files)==1)
  file=files[0];s=file.lstat()
  ensure(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and re.fullmatch(r'[A-Za-z0-9_.-]{1,160}',file.name))
  paths.append(file)
 entries=[]
 for path in paths:
  s=path.lstat();ensure(s.st_dev==root.stat().st_dev)
  entries.append({'relative':str(path.relative_to(root)),'uid':s.st_uid,'gid':s.st_gid,'mode':stat.S_IMODE(s.st_mode),
   'device':s.st_dev,'inode':s.st_ino,'kind':'directory' if stat.S_ISDIR(s.st_mode) else 'file','size':s.st_size if stat.S_ISREG(s.st_mode) else None})
 return entries
def journal_safe():
 s=journal.lstat();ensure(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode) and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o700)
def write(name,value):
 fd=os.open(journal/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as out:json.dump(value,out);out.flush();os.fsync(out.fileno())
def read(name):
 path=journal/name;s=path.lstat();ensure(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o600)
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd) as source:return json.load(source)
def emit(value):print('YX_UPLOAD_PERMISSIONS='+json.dumps(value))
'''
PLAN=r'''
entries=scan()
ensure(not journal.exists())
for item in entries:
 ensure(item['uid']==0 and item['gid']==0)
 ensure(item['mode']==(0o777 if item['relative']=='.' else 0o755 if item['kind']=='directory' else 0o644))
emit({'ok':True,'manifest':entries,'manifest_sha256':digest(entries),'entry_count':len(entries),'applied':False})
'''
APPLY=r'''
entries=scan();ensure(digest(entries)==expected_hash)
ensure(os.geteuid()==0)
journal.mkdir(mode=0o700);journal_safe()
write('original.json',{'entries':entries,'manifest_sha256':expected_hash})
write('attempt.json',{'attempted':True,'manifest_sha256':expected_hash})
# Fixed snapshot only, deepest entries first; root permission changes last.
for entry in sorted(entries,key=lambda x:len(Path(x['relative']).parts),reverse=True):
 path=root/entry['relative'];flags=os.O_RDONLY|os.O_NOFOLLOW
 if entry['kind']=='directory':flags|=os.O_DIRECTORY
 fd=os.open(path,flags)
 try:
  current=os.fstat(fd);ensure(current.st_dev==entry['device'] and current.st_ino==entry['inode'])
  os.fchown(fd,10001,10001);os.fchmod(fd,0o750 if entry['kind']=='directory' else 0o640)
 finally:os.close(fd)
actual=scan()
ensure(all(item['uid']==10001 and item['gid']==10001 and item['mode']==(0o750 if item['kind']=='directory' else 0o640) for item in actual))
child="import os,json;from pathlib import Path;os.setgroups([]);os.setgid(10001);os.setuid(10001);r=Path('/data/uploads');paths=[r,*r.rglob('*')];print(json.dumps({'access':all(os.access(p,os.R_OK|os.W_OK|(os.X_OK if p.is_dir() else 0))for p in paths),'uid':os.geteuid()}))"
check=subprocess.run([sys.executable,'-c',child],capture_output=True,text=True,timeout=15)
ensure(check.returncode==0);access=json.loads(check.stdout);ensure(access['access'] and access['uid']==10001)
receipt={'ok':True,'applied':True,'entry_count':len(actual),'original_sha256':expected_hash,'result_sha256':digest(actual),'uid_10001_verified':True}
write('success.json',receipt);emit(receipt)
'''
STATUS=r'''
entries=scan()
if not journal.exists():emit({'ok':True,'state':'not_attempted','manifest_sha256':digest(entries),'retry_authorized':False})
else:
 journal_safe();original=read('original.json')
 verified=(journal/'success.json').exists()
 matching=all(i['uid']==10001 and i['gid']==10001 and i['mode']==(0o750 if i['kind']=='directory' else 0o640) for i in entries)
 if verified:
  receipt=read('success.json');ensure(receipt['result_sha256']==digest(entries))
 else:receipt={'original_sha256':original['manifest_sha256']}
 emit({'ok':True,'state':'verified' if verified else 'outcome_unknown','metadata_matches_target':matching,'retry_authorized':False,'receipt':receipt})
'''


def remote(source):
    wrapped='import json\ntry:\n'+textwrap.indent(source,' ')+'\nexcept Exception as exc:\n print("YX_UPLOAD_PERMISSIONS="+json.dumps({"ok":False,"error_class":type(exc).__name__}))\n'
    encoded=base64.b64encode(zlib.compress(wrapped.encode())).decode()
    launcher='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(encoded)+')))'
    cmd=['zeabur.cmd','service','exec','--id',SERVICE,'--env-id',ENV,'-i=false','--','python','-c',launcher]
    result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
    lines=[line.split(MARKER,1)[1]for line in result.stdout.splitlines()if line.startswith(MARKER)]
    if result.returncode or len(lines)!=1:raise RuntimeError('Unknown remote outcome; use status only')
    result=json.loads(lines[0])
    if result.get('ok') is not True:raise RuntimeError('Permission operation failed; use status to reconcile')
    return result


def perform(step):
    STATE.mkdir(parents=True,exist_ok=True)
    if step=='plan':
        result=remote(COMMON+PLAN)
        with (STATE/'plan.json').open('x',encoding='utf-8') as out:json.dump(result,out,indent=2)
        return {k:v for k,v in result.items() if k!='manifest'}
    if step=='apply':
        plan=json.loads((STATE/'plan.json').read_text(encoding='utf-8'))
        expected=hashlib.sha256(json.dumps(plan['manifest'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if expected!=plan['manifest_sha256']:raise RuntimeError('Local permission plan changed')
        with (STATE/'dispatch.json').open('x',encoding='utf-8') as out:json.dump({'original_sha256':expected,'attempted':True},out)
        result=remote(COMMON+'\nexpected_hash='+repr(expected)+'\n'+APPLY)
        if result.get('original_sha256')!=expected or result.get('uid_10001_verified') is not True:raise RuntimeError('Permission receipt mismatch')
    elif step=='status':result=remote(COMMON+STATUS)
    else:raise ValueError('Unsupported command')
    (STATE/(step+'-receipt.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('step',choices=['plan','apply','status'])
    print(json.dumps(perform(parser.parse_args().step)))

if __name__=='__main__':
    try:main()
    except Exception as exc:print(json.dumps({'ok':False,'error_class':type(exc).__name__}));sys.exit(1)
