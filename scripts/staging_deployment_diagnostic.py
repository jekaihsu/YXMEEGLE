"""Fixed staging READ ONLY deployment diagnostics; suppress raw logs/config."""
import json,re,subprocess,sys,base64,zlib
from pathlib import Path
STATE=Path(__file__).resolve().parents[1]/'.runtime/staging-diagnostic'
SERVICE='6abc0821454b8f31a5ef614a'
ENV='6ab6168036d2a6cac409f0c6'


def command(name,args):
 result=subprocess.run(['zeabur.cmd',*args,'-i=false','--json'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
 STATE.mkdir(parents=True,exist_ok=True)
 (STATE/(name+'.txt')).write_text(result.stdout,encoding='utf-8')
 try:value=json.loads(result.stdout)
 except ValueError:value=None
 return result.returncode,value,result.stdout


def safe(value):
 if isinstance(value,list):return [safe(item)for item in value]
 if not isinstance(value,dict):return None
 allowed={'_id','id','ID','status','Status','Template','createdAt','updatedAt','startedAt','finishedAt','serviceID','environmentID','runAsUserID','dockerfile','rootDirectory','template'}
 result={k:v for k,v in value.items() if k in allowed and (v is None or isinstance(v,(str,int,bool)))}
 for key,item in value.items():
  if isinstance(item,(dict,list)) and key not in ('variables','environmentVariables','env','config'):
   nested=safe(item)
   if nested:result[key]=nested
 return result


def main():
 args=['--service-id',SERVICE,'--env-id',ENV]
 output={}
 for name,cmd in [('deployments',['deployment','list',*args]),('latest',['deployment','get',*args]),('service',['service','get','--id',SERVICE,'--env-id',ENV])]:
  code,data,raw=command(name,cmd);output[name]={'exit_code':code,'metadata':safe(data),'json_parsed':data is not None}
 code,data,raw=command('build-log',['deployment','log',*args,'--project-id','6ab61680a4c05a5bcb57ace9','--type','build'])
 output['build_log']={'exit_code':code,'characters':len(raw),'signals':{word:bool(re.search(pattern,raw,re.I))for word,pattern in {
   'dockerfile':'Dockerfile','docker_user_10001':r'USER\s+10001','zeabur_builder':'Zeabur Builder','nixpacks':'nixpacks','railpack':'railpack',
   'build_error':r'error:|failed to|ERROR \[','build_complete':r'build.*success|build.*complete|exporting to image','useradd':'useradd'}.items()}}
 program="""
import os,json,stat
from pathlib import Path
paths=[Path('/data'),Path('/data/uploads'),Path('/app')]
metadata=[{'path':str(p),'uid':p.lstat().st_uid,'gid':p.lstat().st_gid,'mode':oct(stat.S_IMODE(p.lstat().st_mode)),'symlink':p.is_symlink()}for p in paths]
if os.geteuid()==0:
 os.setgroups([]);os.setgid(10001);os.setuid(10001)
print('YX_STAGING_VOLUME='+json.dumps({'metadata':metadata,'effective_uid':os.geteuid(),'uploads_rwx':os.access('/data/uploads',os.R_OK|os.W_OK|os.X_OK),'app_read_traverse':os.access('/app',os.R_OK|os.X_OK)}))
"""
 encoded=base64.b64encode(zlib.compress(program.encode())).decode()
 launcher='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(encoded)+')))'
 completed=subprocess.run(['zeabur.cmd','service','exec','--id',SERVICE,'--env-id',ENV,'-i=false','--','python','-c',launcher],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
 lines=[line.split('YX_STAGING_VOLUME=',1)[1]for line in completed.stdout.splitlines()if line.startswith('YX_STAGING_VOLUME=')]
 output['uid_10001_preflight']=json.loads(lines[0])if completed.returncode==0 and len(lines)==1 else {'verified':False}
 print(json.dumps(output));(STATE/'safe-receipt.json').write_text(json.dumps(output,indent=2),encoding='utf-8')

if __name__=='__main__':
 try:main()
 except Exception as exc:print(json.dumps({'ok':False,'error_class':type(exc).__name__}));sys.exit(1)
