"""Read-only fixed formal production data delta against the verified snapshot."""
import base64,hashlib,json,subprocess,sys,textwrap,zlib
from pathlib import Path
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1]
SERVICE='6ab61834a4c05a5bcb57ad69'
ENV='6ab6168036d2a6cac409f0c6'
MARKER='YX_FORMAL_DELTA='
SUMMARY=r'''
import collections,hashlib,json

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
def summarize(rows):
 production={w['id'] for w in rows['workspaces'] if w['id'].startswith('lark-')}
 groups=collections.defaultdict(list);normalized=collections.defaultdict(list)
 for record in rows['business_records']:
  if record['workspace_id'] not in production:continue
  data=record['data'];kind=record['kind'];value={'entity_id':record['entity_id'],'parent_id':record['parent_id'],'data':data}
  groups[kind].append(value)
  if kind=='events' and data.get('action') in ('source_sync','people_directory_sync'):continue
  if kind=='users':
   value={**value,'data':{k:v for k,v in data.items() if k not in ('directory_last_seen_at',)}}
  normalized[kind].append(value)
 def stats(group):return {kind:{'count':len(values),'sha256':digest(sorted(values,key=lambda v:v['entity_id']))} for kind,values in sorted(group.items())}
 field_hashes={}
 for kind,values in groups.items():
  fields=set().union(*(v['data'].keys() for v in values))
  field_hashes[kind]={field:digest(sorted([(v['entity_id'],v['data'].get(field))for v in values],key=lambda x:x[0]))for field in fields}
 roots=[]
 ignored={'version','as_of','source_status','source_connection','people_directory_status','people_directory_connection','attendance_status','attendance_connection'}
 for row in rows['workspaces']:
  if row['id'] in production:roots.append({k:v for k,v in row['data'].items() if k not in ignored})
 approvals=[r['data']for r in rows['business_records']if r['workspace_id'] in production and r['kind'] in ('approvals','financial_requests')]
 for w in rows['workspaces']:
  if w['id'] in production:approvals.extend(w['data'].get('node_skip_requests',[]))
 audit=[r for r in rows['action_audit']if r['workspace_id'] in production]
 return {'production_workspaces':len(production),'business':stats(groups),'normalized_business':stats(normalized),'field_hashes':field_hashes,
  'workspace_field_hashes':{k:digest([r.get(k)for r in roots]) for k in set().union(*(r.keys()for r in roots))},
  'event_actions':dict(collections.Counter(r['data'].get('action')for r in rows['business_records']if r['workspace_id']in production and r['kind']=='events')),
  'nonheartbeat_workspace_sha256':digest(roots),'approval_count':len(approvals),'native_attempted':sum(bool(a.get('native_binding',{}).get('attempted'))for a in approvals),
  'audit_count':len(audit),'audit_sha256':digest(sorted(audit,key=lambda a:a['id'])),
  'audit_actions':dict(collections.Counter(r['action']for r in audit))}
'''
REMOTE=r'''
import os,stat
from pathlib import Path
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
url=make_url(os.environ['DATABASE_URL']).set(drivername='postgresql+psycopg')
engine=create_engine(url)
with engine.connect().execution_options(isolation_level='REPEATABLE READ') as connection:
 connection.exec_driver_sql('SET TRANSACTION READ ONLY')
 rows={}
 for table in ('workspaces','business_records','action_audit'):
  rows[table]=[dict(row)for row in connection.execute(text('SELECT * FROM '+table)).mappings()]
engine.dispose()
result=summarize(rows)
root=Path('/data/uploads')
if os.environ.get('UPLOAD_DIR')!=str(root):raise RuntimeError('Unexpected uploads path')
files=[]
for parent,dirs,names in os.walk(root,followlinks=False):
 for name in dirs:
  if (Path(parent)/name).is_symlink():raise RuntimeError('Symlink found')
 for name in names:
  path=Path(parent)/name;s=path.lstat()
  if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:raise RuntimeError('Unexpected attachment type')
  with path.open('rb')as source:sha=hashlib.file_digest(source,'sha256').hexdigest()
  files.append({'path':path.relative_to(root).as_posix(),'sha256':sha,'bytes':s.st_size})
result['attachment_files']={'count':len(files),'sha256':digest(sorted(files,key=lambda f:f['path']))}
print('YX_FORMAL_DELTA='+json.dumps(result))
'''


def main():
 receipt=json.loads((ROOT/'.runtime/workbench-snapshot/receipt.json').read_text(encoding='utf-8'))
 archive=ROOT/'.runtime/workbench-snapshot/snapshot.zip'
 if hashlib.sha256(archive.read_bytes()).hexdigest()!=receipt['sha256']:raise RuntimeError('Snapshot checksum mismatch')
 namespace={};exec(SUMMARY,namespace)
 with ZipFile(archive)as zipped:
  old=namespace['summarize'](json.loads(zipped.read('database.json')))
  files=[{'path':name.removeprefix('uploads/'),'sha256':hashlib.sha256(zipped.read(name)).hexdigest(),'bytes':zipped.getinfo(name).file_size}for name in zipped.namelist()if name.startswith('uploads/')and not name.endswith('/')]
  old['attachment_files']={'count':len(files),'sha256':namespace['digest'](sorted(files,key=lambda f:f['path']))}
 source='import json\ntry:\n'+textwrap.indent(SUMMARY+REMOTE,' ')+'\nexcept Exception as exc:\n print("YX_FORMAL_DELTA="+json.dumps({"error_class":type(exc).__name__}))\n'
 encoded=base64.b64encode(zlib.compress(source.encode())).decode();launcher='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(encoded)+')))'
 cmd=['zeabur.cmd','service','exec','--id',SERVICE,'--env-id',ENV,'-i=false','--','python','-c',launcher]
 completed=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
 values=[line.split(MARKER,1)[1]for line in completed.stdout.splitlines()if line.startswith(MARKER)]
 if completed.returncode or len(values)!=1:raise RuntimeError('Read-only delta transport failed')
 current=json.loads(values[0])
 if current.get('error_class'):raise RuntimeError('Read-only delta failed: '+current['error_class'])
 changed=[k for k in old['normalized_business'].keys()|current['normalized_business'].keys()if old['normalized_business'].get(k)!=current['normalized_business'].get(k)]
 result={'ok':True,'source_service_id':SERVICE,'snapshot_sha256':receipt['sha256'],'snapshot_at':receipt['observed_at'],
  'observed_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
  'changed_nonheartbeat_business_kinds':sorted(changed),'nonheartbeat_workspace_equal':old['nonheartbeat_workspace_sha256']==current['nonheartbeat_workspace_sha256'],
  'changed_fields':{kind:sorted(k for k in old['field_hashes'].get(kind,{}).keys()|current['field_hashes'].get(kind,{}).keys()if old['field_hashes'].get(kind,{}).get(k)!=current['field_hashes'].get(kind,{}).get(k))for kind in changed},
  'changed_workspace_fields':sorted(k for k in old['workspace_field_hashes'].keys()|current['workspace_field_hashes'].keys()if old['workspace_field_hashes'].get(k)!=current['workspace_field_hashes'].get(k)),
  'event_action_count_deltas':{k:current['event_actions'].get(k,0)-old['event_actions'].get(k,0)for k in old['event_actions'].keys()|current['event_actions'].keys()if current['event_actions'].get(k,0)!=old['event_actions'].get(k,0)},
  'audit_equal':old['audit_sha256']==current['audit_sha256'],'attachments_equal':old['attachment_files']==current['attachment_files'],
  'baseline':old,'current':current,'read_only':True}
 (ROOT/'.runtime/formal-data-delta.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in result.items()if k not in ('baseline','current')}|{'current_approval_count':current['approval_count'],'current_native_attempted':current['native_attempted'],'current_audit_count':current['audit_count']}))

if __name__=='__main__':
 try:main()
 except Exception as exc:print(json.dumps({'ok':False,'error_class':type(exc).__name__}));sys.exit(1)
