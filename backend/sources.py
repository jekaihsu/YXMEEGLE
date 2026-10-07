"""Lark read-only adapter. No request in this module writes a Base record."""
import hashlib
import json
import os
import unicodedata
from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime, timezone, timedelta
import httpx
from fastapi import HTTPException
from .seed import STAGES, TITLES

API='https://open.larksuite.com/open-apis'
PROVISIONAL_CASE_FIELD='可能的確認單工編(若暫無確認單才需填寫)'
FIELDS={
 'quote':['工程編號','報價編號','此案確認單','工程名稱','行號單位','契約價格(未稅)','備註','案件負責人','報價期限','外業期限','內業期限(控)','內業期限(圖)','內業期限(報)','合約開始日期','合約結束日期'],
 'confirmation':['工程確認單編號','所屬案件','SourceID','工程名稱','狀態','合約總額','預估總成本','實際總成本','案件負責人','合約結束日期','備註','報價編號'],
 'contract':['所屬案件','SourceID','所屬成案確認單（日報關聯）','合約項次','合約工作項目','分項金額(原始)','分項金額(報出)','控制工項','圖資工項','報告工項','控制預估工天','圖資預估工天','報告預估工天'],
 'reporting':['所屬案件','工項類別','工項名稱','填報工項','對應營業額','來源合約明細（日報關聯）','來源明細唯一鍵'],
 'daily':['工作日期-薪資','工作日期-營業額明細','營業額組別-明細','姓名','案件編號','工作內容','營業額點數','最終營業額點數','日期','組別','填寫人','人員','工程編號','案號','所屬成本單','所屬案件','工項說明','內業工項','合約工項','外業工項','本明細適用工項','備註','組長帳號-津貼自動化','組員帳號-津貼自動化'],
 'cost':['出工日期','工作日期','日期','組別','內業組別','所屬組別','填報帳號','組長帳號-津貼自動化','組員帳號-津貼自動化']}
FIELDS['quote_confirmation']=FIELDS['confirmation'][:]
FIELDS['quote']+=['狀態','案件狀態','案件已入帳','累計已入帳','累計已請款','案件可請款總額','入帳資料檢核','可請款未請','入帳日期','付款條件']
FIELDS['confirmation']+=['案件已入帳','入帳日期']
FIELDS['quote_confirmation']+=['案件已入帳','入帳日期']
REVIEW_FIELDS=['檢核狀態','工務助理檢核','外業經理檢核','控制組檢核','品管檢核','雅雯檢核','檢核時間','PM檢核','內業組長檢核']
FIELDS['daily']+=REVIEW_FIELDS
FIELDS['daily']+=[PROVISIONAL_CASE_FIELD,'可能確認單工作編號']
FIELDS['cost']+=REVIEW_FIELDS
KNOWN_TABLES={
 'H7W6b0PFWaVF1BsgqXJj3pQ9pXb':{'tblmSQrcCs9vPQZx':'confirmation','tblobs4qPy2w9MZ6':'contract','tblwQPYk3c9RvCU7':'reporting','tbl8wRYCUCvbSoJG':'cost','tblKwSDRg6WaGHYr':'cost','tbl5zPLS0ExWNEty':'daily','tblrCo8KeZiuJUNh':'daily'},
 'JoOqbggsVar0ATsVgbcjh6IIp1g':{'tblENZvYAya93Twa':'quote','tblvV4X1kNVQisVj':'quote_confirmation'},
}

def configuration(cfg=None):
    cfg=os.environ if cfg is None else cfg
    raw=cfg.get('LARK_SOURCE_TABLES_JSON','[]')
    try: tables=json.loads(raw)
    except ValueError: return []
    if not isinstance(tables,list) or not all(isinstance(t,dict) and t.get('base_token') and t.get('table_id') for t in tables): return []
    base=cfg.get('LARK_V4_BASE_TOKEN','H7W6b0PFWaVF1BsgqXJj3pQ9pXb')
    quote_base=cfg.get('LARK_QUOTE_BASE_TOKEN','JoOqbggsVar0ATsVgbcjh6IIp1g')
    allowed={base:{'confirmation','contract','reporting','cost','daily'},quote_base:{'quote','quote_confirmation'}}
    result=[]; seen=set()
    for table in tables:
        key=(table['base_token'],table['table_id'])
        if table.get('kind') not in allowed.get(table['base_token'],set()) or key in seen: continue
        if table['base_token'] in KNOWN_TABLES and KNOWN_TABLES[table['base_token']].get(table['table_id'])!=table['kind']: continue
        seen.add(key); result.append(table)
    return result

def fetch_sources(token,cfg=None,client=None):
    cfg=os.environ if cfg is None else cfg
    tables=configuration(cfg)
    if not tables: raise HTTPException(503,'尚未設定 LARK_SOURCE_TABLES_JSON')
    try: max_pages=max(1,min(int(cfg.get('LARK_SOURCE_MAX_PAGES','50')),100))
    except ValueError: raise HTTPException(503,'LARK_SOURCE_MAX_PAGES 必須為整數')
    records_api=cfg.get('LARK_BITABLE_RECORDS_API','list')
    if records_api not in ('list','search'): raise HTTPException(503,'LARK_BITABLE_RECORDS_API 必須為 list 或 search')
    page_size=500 if records_api=='search' else 200
    collected=[]; summary=[]; partial=False
    with (nullcontext(client) if client is not None else httpx.Client(timeout=30)) as client:
        def request(method,url,**kwargs):
            from .live_read.client import ReadBlocked, ReadFailure
            from .live_read.rate_limit import BudgetExceeded
            try:
                # Legacy get-only test clients remain supported.
                if method=='GET' and not hasattr(client,'request'): return client.get(url,**kwargs)
                return client.request(method,url,**kwargs)
            except ReadBlocked:
                raise HTTPException(403,'目前 Lark 身分沒有這張 Base 的資源存取權限（1254302）；請確認表格分享權限') from None
            except (ReadFailure, BudgetExceeded):
                raise HTTPException(502,'Lark 讀取失敗；保留上次成功資料') from None
        for table in tables:
            params={'page_size':page_size,'user_id_type':'open_id'}; count=0
            available=set(); linked_tables={}; attachment_fields=[]; schema_params={'page_size':100}; schema_tokens=set()
            for _ in range(20):
                schema=request('GET',f"{API}/bitable/v1/apps/{table['base_token']}/tables/{table['table_id']}/fields",headers={'Authorization':f'Bearer {token}'},params=schema_params)
                if schema.status_code!=200: raise HTTPException(502,'無法讀取來源欄位設定')
                if schema.json().get('code',0)==1254302: raise HTTPException(403,'目前 Lark 身分沒有這張 Base 的資源存取權限（1254302）；請確認表格分享權限')
                if schema.json().get('code',0)!=0: raise HTTPException(502,'無法讀取來源欄位設定')
                metadata=schema.json().get('data')
                if not isinstance(metadata,dict): raise HTTPException(502,'Lark 欄位回應缺少 data；保留上次成功資料')
                if not isinstance(metadata.get('items'),list) or not isinstance(metadata.get('has_more'),bool): raise HTTPException(502,'Lark 欄位完整性不明；保留上次成功資料')
                schema_items=metadata.get('items') or []
                available.update(f['field_name'] for f in schema_items)
                for field in schema_items:
                    if field.get('type')==17: attachment_fields.append(field['field_name'])
                    target=(field.get('property') or {}).get('table_id')
                    if target: linked_tables[field['field_name']]=target
                if not metadata.get('has_more'): break
                next_token=metadata.get('page_token')
                if not next_token or next_token in schema_tokens: raise HTTPException(502,'Lark 欄位分頁游標缺漏或重複；保留上次成功資料')
                schema_tokens.add(next_token); schema_params['page_token']=next_token
            else: raise HTTPException(502,'Lark 欄位設定超過分頁上限；無法確認完整欄位，保留上次成功資料')
            if table['base_token'] in KNOWN_TABLES:
                required={'confirmation':'工程確認單編號','quote_confirmation':'工程確認單編號','quote':'報價編號'}.get(table.get('kind'))
                if required and required not in available: raise HTTPException(422,f"來源表 {table.get('name',table['table_id'])} 缺少識別欄位 {required}；保留上次成功資料")
            desired=list(table.get('field_names') or FIELDS.get(table.get('kind','quote'),[]))
            # Only approved business Bases, never the HR/capability Base. Index
            # native attachment metadata; do not fetch file bytes or temp URLs.
            if table['base_token'] in KNOWN_TABLES: desired+=attachment_fields
            if table.get('kind') in ('daily','cost'): desired+=REVIEW_FIELDS
            if table.get('kind')=='daily': desired+=['工作日期-薪資','工作日期-營業額明細','日期',PROVISIONAL_CASE_FIELD,'可能確認單工作編號']
            projected=list(dict.fromkeys(f for f in desired if f in available))
            if not projected: raise HTTPException(422,f"來源表 {table.get('name',table['table_id'])} 缺少已知映射欄位")
            if records_api=='list':
                params['field_names']=json.dumps(projected,ensure_ascii=False)
                params['automatic_fields']='true'
            record_tokens=set(); record_ids=set(); pages_read=0
            for _ in range(max_pages):
                url=f"{API}/bitable/v1/apps/{table['base_token']}/tables/{table['table_id']}/records"
                kwargs={'headers':{'Authorization':f'Bearer {token}'},'params':params}
                if records_api=='search': kwargs['json']={'field_names':projected,'automatic_fields':True}
                response=request('POST' if records_api=='search' else 'GET',url+'/search' if records_api=='search' else url,**kwargs)
                if response.status_code!=200: raise HTTPException(502,'Lark 讀取失敗，請檢查應用權限或重新登入')
                data=response.json()
                if data.get('code',0)==1254302: raise HTTPException(403,'目前 Lark 身分沒有這張 Base 的資源存取權限（1254302）；請確認表格分享權限')
                if data.get('code',0)!=0: raise HTTPException(502,f"Lark 來源無法讀取（代碼 {data.get('code')}）")
                page=data.get('data')
                if not isinstance(page,dict): raise HTTPException(502,'Lark 紀錄回應缺少 data；保留上次成功資料')
                if not isinstance(page.get('items'),list) or not isinstance(page.get('has_more'),bool): raise HTTPException(502,'Lark 紀錄完整性不明；保留上次成功資料')
                items=page.get('items') or []; pages_read+=1
                current_ids=[item['record_id'] for item in items]
                if len(set(current_ids))!=len(current_ids) or record_ids.intersection(current_ids): raise HTTPException(502,'Lark 分頁包含重複紀錄；請重新同步，保留上次成功資料')
                record_ids.update(current_ids); count+=len(items)
                collected.extend({'base_token':table['base_token'],'table_id':table['table_id'],'kind':table.get('kind','quote'),'department':table.get('department'),'cost_table_id':table.get('cost_table_id') or linked_tables.get('所屬成本單'),'linked_tables':linked_tables,'attachment_fields':attachment_fields,'record_id':item['record_id'],'created_time':item.get('created_time'),'last_modified_time':item.get('last_modified_time'),'fields':item.get('fields') or {}} for item in items)
                if not page.get('has_more'): break
                next_token=page.get('page_token')
                if not next_token or next_token in record_tokens: raise HTTPException(502,'Lark 紀錄分頁游標缺漏或重複；保留上次成功資料')
                record_tokens.add(next_token); params['page_token']=next_token
            table_partial=bool(page.get('has_more')); partial=partial or table_partial
            summary.append({'name':table.get('name',table['table_id']),'base_token':table['base_token'],'kind':table.get('kind','quote'),'table_id':table['table_id'],'count':count,'status':'partial' if table_partial else 'ready','attachment_fields':attachment_fields,'pages_read':pages_read,'page_limit':max_pages,'record_limit':max_pages*page_size})
    return {'configured':True,'last_sync':datetime.now(timezone(timedelta(hours=8))).isoformat(),'status':'partial' if partial else 'ready','message':'已達本次讀取上限；目前為部分資料' if partial else '來源唯讀同步完成；未寫入 Lark','tables':summary,'records':collected}

def text(value):
    if value is None: return ''
    if isinstance(value,list): return ''.join(text(v) for v in value)
    if isinstance(value,dict): return str(value.get('text') or value.get('name') or '')
    return str(value)
def number(value):
    if isinstance(value,(list,dict)): value=text(value)
    try: return float(value) if value not in ('',None) else None
    except (ValueError,TypeError): return None
def normalized_case(value):
    # Strip only spacing/format characters; never truncate suffixes or infer similar codes.
    return ''.join(c for c in text(value) if unicodedata.category(c)!='Cf').strip()
def day(value, *, formula_serial=False):
    # A formula returning a date may expose the spreadsheet serial-day number
    # (unlike a native Date field's Unix milliseconds). Enable this only for
    # known date formulas, never for arbitrary numbers, IDs or native dates.
    if formula_serial and not isinstance(value,bool):
        try:
            serial=float(text(value))
            if 1<=serial<2958466:
                return (datetime(1899,12,30)+timedelta(days=serial)).date().isoformat()
        except (ValueError,TypeError,OverflowError): pass
    if isinstance(value,(int,float)):
        try: return datetime.fromtimestamp(value/1000 if value>100000000000 else value,timezone(timedelta(hours=8))).date().isoformat()
        except (ValueError,OverflowError,OSError): return ''
    raw=text(value)
    if raw.isdigit() and len(raw)>=10: return day(int(raw))
    normalized=raw[:10].replace('/','-')
    try: return datetime.strptime(normalized,'%Y-%m-%d').date().isoformat()
    except ValueError: return ''
def source_id(r): return 'src-'+hashlib.sha256(f"{r['base_token']}/{r['table_id']}/{r['record_id']}".encode()).hexdigest()[:20]
def link_ids(value):
    """Accept native REST record-id lists and structured link values, never display names."""
    if isinstance(value,str): return [value] if value.startswith('rec') else []
    if isinstance(value,list): return list(dict.fromkeys(x for item in value for x in link_ids(item)))
    if isinstance(value,dict):
        if isinstance(value.get('record_id'),str): return [value['record_id']]
        if isinstance(value.get('record_ids'),list): return link_ids(value['record_ids'])
        if isinstance(value.get('link_record_ids'),list): return link_ids(value['link_record_ids'])
    return []
def canonical_department(value):
    return {'控制':'控制組','圖資':'圖資組','報告':'報告組','外業':'外業組'}.get(value,value)
def unique_value(values):
    values={value for value in values if value}
    return next(iter(values)) if len(values)==1 else ''
def project_nodes(pid):
    from .policy import template
    from .sop_contracts import decorate_task,applicability,VERSION as CONTRACT_VERSION
    definition=template()
    nodes=[]
    for key,name,_ in STAGES:
        definitions=next(n['task_definitions']for n in definition['nodes']if n['key']==key)
        tasks=[];pending=[]
        for i,item in enumerate(definitions,1):
            if item.get('disabled'):continue
            if applicability({},item) is None:
                pending.append({'key':item['key'],'rule':item['applicability'],'title':item['title'],'contract_version':CONTRACT_VERSION})
                continue
            tasks.append(decorate_task(new_task(f'{pid}-{key}-sop{i}',item['title'],None),item,definition['id']))
        for task in tasks:
            if not task.get('recurring_kind'):task['description']='固定 SOP 範本；請指派負責人與排期'
        nodes.append(dict(id=f'{pid}-{key}',key=key,name=name,owner_id='',collaborator_ids=[],status='pending',start_date=None,due_date=None,original_due_date=None,started_at=None,completed_at=None,tasks=tasks,sop_applicability_pending=pending))
    return nodes
def new_task(ident,title,work_id,points=None):
    return dict(id=ident,title=title,owner_id='',owner_inherited=True,status='pending',required=True,start_date=None,due_date=None,original_due_date=None,started_at=None,completed_at=None,points=points,work_item_id=work_id,description='由 V4 工項帶入；請指派負責人與排期',input='',output='',comments=[],revision=1)

def import_sources(ws,records,complete_tables=None):
    from .v4_sources import import_v4
    return import_v4(ws, records, complete_tables=complete_tables)
