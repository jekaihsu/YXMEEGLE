"""Minimal native work-item read model. Never changes executable tasks."""
from copy import deepcopy
import json
from .sources import source_id

ITEM_TABLE='tblwQPYk3c9RvCU7'
CONTRACT_TABLE='tblobs4qPy2w9MZ6'
MAX_ROWS=200
MAX_BYTES=24_000  # Leaves headroom within 165 KB raw / 30 KB gzip request ceilings.


def update_work_items(ws,records,tables,assignments):
    from .source_entities import entity_id
    from .v4_sources import native_records
    schemas={(t.get('base_token'),t.get('table_id')):{f['field_id']:f for f in t.get('field_schema') or [] if f.get('field_id')} for t in tables or []}
    complete={(t.get('base_token'),t.get('table_id')) for t in tables or [] if t.get('status')=='ready'}
    index={}
    for r in records:index.setdefault((r['base_token'],r['record_id']),[]).append(r)
    def field(row,fid):return schemas.get((row['base_token'],row['table_id']),{}).get(fid,{})
    def links(row,fid,kind):
        schema=field(row,fid);name=schema.get('field_name')
        if not name:return [],[True]
        linked={**row.get('linked_tables',{}),name:(schema.get('property') or {}).get('table_id')}
        return native_records({**row,'linked_tables':linked},name,index,{kind})
    items={r['id']:deepcopy(r) for r in ws.get('source_work_items',[])}
    present={entity_id(r) for r in records}
    for old in items.values():
        base,table,_=old['id'].split('/')
        if old['id'] not in present and (base,table) in complete:old['source_missing']=True
    ready={}
    for r in records:
        if r['table_id']!=ITEM_TABLE or r.get('kind')!='reporting':continue
        contracts,missing=links(r,'flduW5c5uF','contract');pids=set()
        for contract in contracts:
            cases,unknown=links(contract,'fldDSpokn5','confirmation')
            missing+=unknown
            pids.update(assignments.get(source_id(c)) for c in cases)
            if not cases:missing.append(True)
        pid=next(iter(pids)) if len(pids)==1 and None not in pids and not missing else None
        category=field(r,'fldzDDIQkr').get('field_name')
        if not category:continue
        ident=entity_id(r)
        items[ident]={'id':ident,'project_id':pid,'contract_ids':sorted({entity_id(c) for c in contracts}),
            'category':deepcopy(r['fields'].get(category)),'source_missing':False,
            'source_url':f"https://yong-xiang-survey.jp.larksuite.com/base/{r['base_token']}?table={r['table_id']}&record={r['record_id']}"}
        if pid:ready[pid]={'partial':(r['base_token'],ITEM_TABLE) not in complete or
            (r['base_token'],CONTRACT_TABLE) not in complete}
    ws['source_work_items']=sorted(items.values(),key=lambda i:i['id'])
    # Forward links catch absent rows even when no imported item can own a project.
    for contract in ws.get('contract_items',[]):
        origin=contract.get('source_identity') or {}
        row=next((r for r in index.get((origin.get('base_token'),origin.get('record_id')),[])
                  if r['table_id']==CONTRACT_TABLE),None)
        if row is None:continue
        forward,unknown=links(row,'fldOFyOZgb','reporting')
        expected={entity_id(r) for r in forward}
        linked=[i for i in items.values() if contract['id'] in i['contract_ids'] or i['id'] in expected]
        incomplete=bool(unknown or expected-items.keys() or
            any(i.get('project_id') is None or i.get('source_missing') for i in linked))
        pid=contract.get('project_id')
        if pid:
            ready.setdefault(pid,{'partial':(row['base_token'],ITEM_TABLE) not in complete or
                (row['base_token'],CONTRACT_TABLE) not in complete})
            if incomplete:ready[pid].setdefault('incomplete_contract_ids',[]).append(contract['id'])
    ws['source_work_items_status']=ready


def project_work_items(ws,pid,*,max_rows=MAX_ROWS,max_bytes=MAX_BYTES):
    status=deepcopy(ws.get('source_work_items_status',{}).get(pid,{'partial':True}))
    items=[];size=2;truncated=bool(status.get('truncated'))
    for item in ws.get('source_work_items',[]):
        if item.get('project_id')!=pid:continue
        added=len(json.dumps(item,ensure_ascii=False,separators=(',',':')).encode())+(1 if items else 0)
        if len(items)>=max_rows or size+added>max_bytes:truncated=True;break
        items.append(item);size+=added
    return items,{**status,'partial':status['partial'] or truncated,'truncated':truncated,'payload_bytes':size}
