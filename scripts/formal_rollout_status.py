"""Fixed formal deployment and worker/source readiness, READ ONLY."""
import argparse,base64,json,subprocess,sys,textwrap,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SERVICE='6ab61834a4c05a5bcb57ad69'
ENV='6ab6168036d2a6cac409f0c6'
MARKER='YX_FORMAL_HEALTH='
REMOTE=r'''
import json,os,collections
from datetime import datetime,timezone
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
url=make_url(os.environ['DATABASE_URL']).set(drivername='postgresql+psycopg')
engine=create_engine(url)
with engine.connect().execution_options(isolation_level='REPEATABLE READ') as connection:
 connection.exec_driver_sql('SET TRANSACTION READ ONLY')
 rows=[dict(r)for r in connection.execute(text("SELECT id, data FROM workspaces WHERE id LIKE 'lark-%'" )).mappings()]
 worker=connection.execute(text("SELECT data FROM source_caches WHERE id='runtime:worker'" )).scalar()
 counts=[dict(r)for r in connection.execute(text("SELECT kind, count(*) AS count FROM business_records WHERE workspace_id LIKE 'lark-%' GROUP BY kind" )).mappings()]
 projects=[r[0]for r in connection.execute(text("SELECT data FROM business_records WHERE workspace_id LIKE 'lark-%' AND kind='projects'" ))]
engine.dispose()
def status(item):
 keys=('status','last_sync','last_attempt_at','last_success_at','sync_revision','mapping_status')
 return {k:item.get(k)for k in keys if k in item}
result={'production_workspace_count':len(rows),'entity_counts':{r['kind']:r['count']for r in counts},
 'project_visibility':dict(collections.Counter(p.get('case_visibility','missing')for p in projects)),
 'execution_systems':dict(collections.Counter(p.get('execution_system','missing')for p in projects)),
 'workspaces':[{'environment':r['data'].get('environment'),'source_policy_revision':r['data'].get('source_case_policy_revision'),
 'baseline_status':'retired' if r['data'].get('source_case_policy_revision')=='all-authorized-lark-cases-20260930' else ('active'if r['data'].get('source_case_baseline')else 'baseline_required'),
 'baseline_old_record_count':len(r['data'].get('source_case_baseline',{}).get('record_ids',[])),
 'source':status(r['data'].get('source_status',{})),'directory':status(r['data'].get('people_directory_status',{})),
 'source_enabled':r['data'].get('source_connection',{}).get('enabled'),'directory_enabled':r['data'].get('people_directory_connection',{}).get('enabled')}for r in rows],
 'worker':{k:(worker or {}).get(k)for k in ('status','stage','at','last_success_at','error_type')},'read_only':True}
print('YX_FORMAL_HEALTH='+json.dumps(result))
'''


def status():
 cmd=['zeabur.cmd','deployment','get','--service-id',SERVICE,'--env-id',ENV,'-i=false','--json']
 completed=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
 if completed.returncode:raise RuntimeError('Deployment status unavailable')
 result=json.loads(completed.stdout)
 if result.get('serviceID')!=SERVICE or result.get('environmentID')!=ENV:raise RuntimeError('Deployment identity mismatch')
 return {k:result.get(k)for k in ('ID','serviceID','environmentID','status','createdAt','startedAt','finishedAt')}


def health():
 source='import json\ntry:\n'+textwrap.indent(REMOTE,' ')+'\nexcept Exception as exc:\n print("YX_FORMAL_HEALTH="+json.dumps({"error_class":type(exc).__name__}))\n'
 encoded=base64.b64encode(zlib.compress(source.encode())).decode();launcher='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(encoded)+')))'
 cmd=['zeabur.cmd','service','exec','--id',SERVICE,'--env-id',ENV,'-i=false','--','python','-c',launcher]
 result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
 lines=[l.split(MARKER,1)[1]for l in result.stdout.splitlines()if l.startswith(MARKER)]
 if result.returncode or len(lines)!=1:raise RuntimeError('Read-only health query failed')
 data=json.loads(lines[0])
 if data.get('error_class'):raise RuntimeError('Read-only health query unavailable')
 return data


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('step',choices=['status','health'])
 step=parser.parse_args().step;result={'step':step,'observed_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'data':status()if step=='status'else health(),'read_only':True}
 (ROOT/'.runtime'/('formal-rollout-'+step+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
 print(json.dumps(result))

if __name__=='__main__':
 try:main()
 except Exception as exc:print(json.dumps({'ok':False,'error_class':type(exc).__name__}));sys.exit(1)
