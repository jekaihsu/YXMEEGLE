"""Read-only source projections. Never substitute a source value for approval."""
from copy import deepcopy
import hashlib
from .sources import text, number, day, source_id


def project_fields(project):
    records=[r for r in project.get('source_records',[]) if not r.get('source_missing')]
    def value(names,parse=text,kinds=None):
        found=[]
        for row in records:
            if kinds and row.get('kind') not in kinds: continue
            for name in names:
                raw=row.get('fields',{}).get(name)
                if raw is None or raw=='': continue
                parsed=parse(raw)
                if parsed is not None and parsed!='': found.append((parsed,row.get('url')))
        values={repr(v):v for v,_ in found}
        return {'value':next(iter(values.values())) if len(values)==1 else None,
                'status':'conflict' if len(values)>1 else 'ready' if values else 'missing',
                'source_urls':sorted({url for _,url in found if url})}
    fields={'client':value(['行號單位']), 'due_date':value(['合約結束日期'],day),
            'contract_amount':value(['合約總額'],number,{'confirmation','quote_confirmation'})}
    finance=project.get('source_finance',{})
    return {'fields':fields,'finance':{'contract_amount':fields['contract_amount']['value'],
        'estimated_cost':finance.get('預估總成本'),'actual_cost':finance.get('實際總成本'),
        'verified':False,'readonly':True},'conflicts':[key for key,item in fields.items() if item['status']=='conflict'],
        'source_urls':sorted({r['url'] for r in records if r.get('url')})}


def update_attachments(ws,records,complete_tables=None,project_by_source=None):
    """Preserve missing metadata only when its own complete table proves absence."""
    project_by_source=project_by_source or {}
    old={a['id']:deepcopy(a) for a in ws.get('source_attachment_index',[])}
    current={}
    for r in records:
        rid=source_id(r)
        url=f"https://yong-xiang-survey.jp.larksuite.com/base/{r['base_token']}?table={r['table_id']}&record={r['record_id']}"
        for field in r.get('attachment_fields',[]):
            values=r.get('fields',{}).get(field) or []
            if not isinstance(values,list): continue
            for item in values:
                if not isinstance(item,dict) or not item.get('file_token'): continue
                ident='attachment-'+hashlib.sha256(f"{rid}/{field}/{item['file_token']}".encode()).hexdigest()[:24]
                current[ident]={'id':ident,'name':str(item.get('name') or ''),'file_token':item['file_token'],
                    'size':item.get('size'),'mime_type':item.get('type'),'source_url':url,
                    'source_field':field,'source_record_id':rid,'base_token':r['base_token'],
                    'table_id':r['table_id'],'project_id':project_by_source.get(rid),
                    'status':'indexed','verified':False,'category_id':'other'}
    complete={(t.get('base_token'),t.get('table_id')):t for t in complete_tables or [] if t.get('status')=='ready'}
    for ident,item in old.items():
        if ident in current: continue
        table=complete.get((item.get('base_token'),item.get('table_id')), {})
        if item.get('source_field') in table.get('attachment_fields',[]): item['status']='source_missing'
        current[ident]=item
    ws['source_attachment_index']=list(current.values())
    for p in ws['projects']:
        p['source_projection']=project_fields(p)
        p['source_attachments']=[deepcopy(a) for a in current.values() if a.get('project_id')==p['id']]


def preserve_missing_sources(ws,records,complete_tables,previous_records):
    from urllib.parse import urlparse,parse_qs
    from .workflow import now
    current={source_id(r) for r in records}
    complete={(t.get('base_token'),t.get('table_id')) for t in complete_tables or [] if t.get('status')=='ready'}
    def covered(row):
        if row.get('base_token') and row.get('table_id'): return (row['base_token'],row['table_id']) in complete
        parsed=urlparse(row.get('url','')); base=parsed.path.rstrip('/').split('/')[-1]
        return (base,parse_qs(parsed.query).get('table',[''])[0]) in complete
    for p in ws['projects']:
        history=p.setdefault('source_record_history',[])
        for old in previous_records.get(p['id'],[]):
            if old['id'] not in current and covered(old):
                if not any(h['id']==old['id'] and h.get('fields')==old.get('fields') for h in history):
                    history.append(dict(deepcopy(old),source_missing=True,source_missing_at=now()))
        for row in p.get('source_records',[]):
            if row['id'] in current: row.pop('source_missing',None)
            elif covered(row): row['source_missing']=True
        origins={r['id']:r for r in p.get('source_records',[])+previous_records.get(p['id'],[])}
        for quote in p.get('quotes',[]):
            if quote['id'] in current:quote.pop('source_missing',None)
            elif quote['id'] in origins and covered(origins[quote['id']]):quote['source_missing']=True
        p['source_missing']=bool(p.get('source_records')) and all(r.get('source_missing') for r in p['source_records'])
        for n in p['nodes']:
            for t in n['tasks']:
                source=t.get('source_identity')
                if not source: continue
                if source_id(source) in current: t.pop('source_missing',None)
                elif covered(source): t['source_missing']=True


def daily_index(state,*,project_id=None,department=None,actor_id=None,date_from=None,date_to=None,
                mapping_status=None,include_missing=False,status='all',q='',offset=0,limit=100):
    """Call after server workspace authorization; returns no raw employee fields."""
    rows=[]; seen=set()
    groups=[(p,p.get('daily_reports',[])) for p in state.get('projects',[])]+[(None,state.get('daily_unmatched',[]))]
    for p,entries in groups:
        for entry in entries:
            if entry['id'] in seen: continue
            seen.add(entry['id'])
            if entry.get('source_missing') and not include_missing and status!='source_missing': continue
            if status=='matched' and not p: continue
            if status=='unmatched' and (p or entry.get('source_missing')): continue
            if status=='source_missing' and not entry.get('source_missing'): continue
            if project_id and (not p or p['id']!=project_id): continue
            if department and entry.get('department')!=department: continue
            if actor_id and actor_id not in entry.get('source_actor_ids',[]): continue
            if date_from and (not entry.get('date') or entry['date']<date_from): continue
            if date_to and (not entry.get('date') or entry['date']>date_to): continue
            if mapping_status and entry.get('mapping_status')!=mapping_status: continue
            if q and q.casefold() not in ' '.join(str(v or '') for v in
                (entry.get('description'),entry.get('person'),entry.get('department'),entry.get('date'),p.get('code') if p else entry.get('case_code'))).casefold(): continue
            row={k:deepcopy(v) for k,v in entry.items() if k not in ('source_fields','source_provenance','candidates')}
            row.update(project_id=p['id'] if p else None,project_code=p['code'] if p else None,
                       source_missing=bool(entry.get('source_missing')))
            rows.append(row)
    rows.sort(key=lambda r:(r.get('date') or '',r['id']),reverse=True)
    offset=max(0,int(offset));limit=min(200,max(1,int(limit)))
    return {'items':rows[offset:offset+limit],'total':len(rows),'offset':offset,'limit':limit,
            'summary':{'matched':sum(bool(r['project_id']) for r in rows),
                       'unmatched':sum(not r['project_id'] and not r['source_missing'] for r in rows),
                       'source_missing':sum(r['source_missing'] for r in rows)},
            'last_sync':state.get('source_status',{}).get('last_sync')}
