"""Fixed formal runtime logs: only component/error-class aggregate, never raw logs."""
import collections,json,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SERVICE='6ab61834a4c05a5bcb57ad69';ENV='6ab6168036d2a6cac409f0c6'
COMPONENTS={'worker','approval_poll','people','attendance','source','jobs','backup'}


def collect(value,found):
 if isinstance(value,dict):
  component=value.get('component');error=value.get('error_type')
  if component in COMPONENTS and isinstance(error,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}',error):
   found.append((component,error));return
  for child in value.values():collect(child,found)
 elif isinstance(value,list):
  for child in value:collect(child,found)
 elif isinstance(value,str):
  decoder=json.JSONDecoder()
  for match in re.finditer(r'\{',value):
   try:decoded,_=decoder.raw_decode(value[match.start():])
   except ValueError:continue
   if isinstance(decoded,dict) and decoded.get('component')in COMPONENTS:collect(decoded,found)


def main():
 cmd=['zeabur.cmd','deployment','log','--service-id',SERVICE,'--env-id',ENV,'--project-id','6ab61680a4c05a5bcb57ace9','--type','runtime','-i=false','--json']
 completed=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
 if completed.returncode:raise RuntimeError('Runtime log transport failed')
 try:data=json.loads(completed.stdout)
 except ValueError:data=completed.stdout
 found=[];collect(data,found)
 counts=collections.Counter(found)
 result={'service_id':SERVICE,'observed_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
 'error_components':[{'component':c,'error_type':e,'count':n}for (c,e),n in sorted(counts.items())],
 'read_only':True,'raw_log_saved':False,'returned_log_error_count':len(found)}
 (ROOT/'.runtime/formal-worker-log-summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))

if __name__=='__main__':
 try:main()
 except Exception as exc:print(json.dumps({'ok':False,'error_class':type(exc).__name__}));sys.exit(1)
