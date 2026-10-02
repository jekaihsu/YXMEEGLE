"""Schema-only directory probe; deliberately never requests records."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.lark_adapter import application_adapter, RemoteFailure
from backend.learning_sources import pages, CAPABILITY_BASE

raw=json.loads((ROOT/'.runtime/zeabur-lark-settings-request.json').read_text(encoding='utf-8-sig'))
cfg=raw.get('variables',{}).get('data',raw).copy()
tenants=[x.strip() for x in cfg.get('LARK_ALLOWED_TENANTS','').split(',') if x.strip()]
if len(tenants)!=1: raise SystemExit('Expected one configured tenant')
cfg.update(LARK_WORKER_IDENTITY='application',LARK_WORKER_ORGANIZATION=tenants[0])
result={'record_reads':False,'remote_writes':False,'status':'error'}
adapter=None
try:
    adapter=application_adapter(cfg)
    root='/bitable/v1/apps/'+CAPABILITY_BASE+'/tables'
    tables=pages(adapter,root)
    matches=[t for t in tables if t.get('name')=='人員名單及資料']
    result['matching_tables']=[{'table_id':t['table_id'],'name':t['name']} for t in matches]
    if len(matches)==1:
        fields=pages(adapter,root+'/'+matches[0]['table_id']+'/fields')
        candidates={'Lark帳號','姓名','人員姓名','員工姓名','人員','部門','所屬部門','組別','職系','在職狀態','任職狀態','人員狀態','在職','是否離職','離職日期','內外勤'}
        result.update(status='ready',fields=[{k:f[k] for k in ('field_id','field_name','type') if k in f}|
            {'options':[(o.get('name') or o.get('text')) for o in (f.get('property') or {}).get('options',[])]}
            for f in fields if f.get('field_name') in candidates])
except RemoteFailure as exc: result['error']=str(exc)
finally:
    if adapter: adapter.client.close()
(ROOT/'.runtime/people-schema-probe-20260927.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
