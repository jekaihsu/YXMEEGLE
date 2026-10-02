"""Fixed formal-service READ ONLY UID/volume preflight; never chmod/chown/write."""
import base64,json,subprocess,sys,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SERVICE='6ab61834a4c05a5bcb57ad69'
ENV='6ab6168036d2a6cac409f0c6'
MARKER='YX_FORMAL_VOLUME='
REMOTE=r'''
import collections,json,os,stat,shutil,subprocess,sys
from pathlib import Path
configured=os.environ.get('UPLOAD_DIR','')
if configured!='/data/uploads':
 print('YX_FORMAL_VOLUME='+json.dumps({'ok':False,'error_code':'unexpected_upload_path','configured_upload_path':configured if __import__('re').fullmatch(r'/[A-Za-z0-9_./-]{1,160}',configured) else 'nonstandard_path_redacted','read_only_probe':True}))
 raise SystemExit(0)
root=Path('/data/uploads')
paths=[Path('/'),Path('/data'),root]
def info(p):
 s=p.lstat()
 return {'path':str(p),'uid':s.st_uid,'gid':s.st_gid,'mode':oct(stat.S_IMODE(s.st_mode)),'directory':stat.S_ISDIR(s.st_mode),'symlink':stat.S_ISLNK(s.st_mode)}
ancestry=[info(p) for p in paths]
entries=[];truncated=False;symlinks=0;ownership=collections.Counter()
for parent,dirs,files in os.walk(root,followlinks=False):
 for name in dirs+files:
  p=Path(parent)/name;s=p.lstat();symlinks+=int(stat.S_ISLNK(s.st_mode))
  ownership[(s.st_uid,s.st_gid,oct(stat.S_IMODE(s.st_mode)),'dir' if stat.S_ISDIR(s.st_mode) else 'file')]+=1
  entries.append(str(p))
  if len(entries)>=10000:truncated=True;break
 if truncated:break
mount=None
for line in Path('/proc/self/mountinfo').read_text().splitlines():
 before,after=line.split(' - ',1);fields=before.split();target=fields[4].replace('\\040',' ')
 if str(root)==target or str(root).startswith(target.rstrip('/')+'/'):
  if mount is None or len(target)>len(mount['path']):mount={'path':target,'fstype':after.split()[0],'read_only':'ro' in fields[5].split(',')}
child=r"""
import json,os,stat,sys
from pathlib import Path
try:
 if os.geteuid()!=10001:
  os.setgroups([]);os.setgid(10001);os.setuid(10001)
 root=Path('/data/uploads');paths=[Path('/'),Path('/data'),root]
 access=[{'path':str(p),'read':os.access(p,os.R_OK),'write':os.access(p,os.W_OK),'traverse':os.access(p,os.X_OK)} for p in paths]
 blocked_dirs=blocked_files=0;seen=0;truncated=False;scan_error=False
 def failure(error):
  global scan_error
  scan_error=True
 for parent,dirs,files in os.walk(root,followlinks=False,onerror=failure):
  for name in dirs+files:
   p=Path(parent)/name;seen+=1
   if p.is_symlink():continue
   if p.is_dir():blocked_dirs+=int(not os.access(p,os.R_OK|os.W_OK|os.X_OK))
   else:blocked_files+=int(not os.access(p,os.R_OK))
   if seen>=10000:truncated=True;break
  if truncated:break
 print(json.dumps({'uid_tested':os.geteuid(),'gid_tested':os.getegid(),'access':access,'blocked_directories':blocked_dirs,'unreadable_files':blocked_files,'scan_truncated':truncated,'scan_error':scan_error}))
except Exception as exc:print(json.dumps({'uid_tested':None,'error_class':type(exc).__name__}))
"""
result=subprocess.run([sys.executable,'-c',__import__('textwrap').dedent(child)],capture_output=True,text=True,timeout=20)
if result.returncode:raise RuntimeError('UID subprocess failed')
access=json.loads(result.stdout)
known=access.get('uid_tested')==10001 and not access.get('scan_truncated') and not access.get('scan_error')
can_write=known and all(a['traverse'] for a in access['access']) and access['access'][-1]['write'] and access['access'][-1]['read'] and access['blocked_directories']==0 and access['unreadable_files']==0 and symlinks==0 and not truncated
print('YX_FORMAL_VOLUME='+json.dumps({'ok':True,'runtime_uid':os.geteuid(),'runtime_gid':os.getegid(),'ancestors':ancestry,'uid_10001_check':access,'uid_10001_uploads_ready':bool(can_write),'mount':mount,'dedicated_upload_mount_observed':bool(mount and mount['path']=='/data/uploads'),'free_bytes':shutil.disk_usage(root).free,'existing_entries':len(entries),'symlink_count':symlinks,'scan_truncated':truncated,'ownership_summary':[{'uid':k[0],'gid':k[1],'mode':k[2],'type':k[3],'count':v}for k,v in ownership.items()],'read_only_probe':True}))
'''

def main():
 source="import json\ntry:\n"+__import__('textwrap').indent(REMOTE,' ')+"\nexcept Exception as exc:\n print('YX_FORMAL_VOLUME='+json.dumps({'ok':False,'error_class':type(exc).__name__}))\n"
 encoded=base64.b64encode(zlib.compress(source.encode())).decode()
 launcher='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(encoded)+')))'
 cmd=['zeabur.cmd','service','exec','--id',SERVICE,'--env-id',ENV,'-i=false','--','python','-c',launcher]
 completed=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
 lines=[line.split(MARKER,1)[1]for line in completed.stdout.splitlines()if line.startswith(MARKER)]
 if completed.returncode or len(lines)!=1:raise RuntimeError('Formal read-only probe transport failed; raw output suppressed')
 result=json.loads(lines[0]);result.update(service_id=SERVICE,environment_id=ENV,observed_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat())
 target=ROOT/'.runtime/formal-volume-preflight.json';target.write_text(json.dumps(result,indent=2),encoding='utf-8')
 print(json.dumps(result))
 return 0 if result.get('ok') and result.get('uid_10001_uploads_ready') else 1

if __name__=='__main__':
 try:sys.exit(main())
 except Exception as exc:print(json.dumps({'ok':False,'error_class':type(exc).__name__,'read_only_probe':True}));sys.exit(1)
