"""Lark HTTP boundary. Never log credentials or infer successful remote writes.

Contracts: Feishu/Lark bitable-v1 app-table-record/update, im-v1/message/create,
drive-v1 files/upload_all + metas/batch_query + files/download.
"""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
import httpx
from .sources import API, day, text, link_ids

class RemoteFailure(Exception):
    def __init__(self,message,status='failed',retry_after=None):
        super().__init__(message); self.status=status; self.retry_after=retry_after


class NativeRequestRejected(RemoteFailure):
    """Only an endpoint-specific documented HTTP 400 validation rejection.

    Transport errors, unknown codes, duplicate UUIDs and GET not-found are not
    evidence that a write did not happen.
    """
    def __init__(self,operation,api_code):
        super().__init__('Lark 明確拒絕'+('建立審批' if operation=='create' else '撤回審批')+f'（{api_code}）；修正原因後可重試原申請','blocked')
        self.operation=operation;self.api_code=api_code;self.http_status=400

class LarkAdapter:
    def __init__(self,token,client=None):
        self.token=token; self.client=client or httpx.Client(timeout=30)

    def request(self,method,path,**kwargs):
        from .capability_write_policy import protected_request, PAUSED_MESSAGE
        if protected_request(method,path):
            raise RemoteFailure(PAUSED_MESSAGE,'blocked')
        try: response=self.client.request(method,API+path,headers={'Authorization':'Bearer '+self.token},**kwargs)
        except httpx.HTTPError as exc:
            raise RemoteFailure('遠端請求結果待核實' if method!='GET' else '遠端讀取暫時失敗','outcome_unknown' if method!='GET' else 'failed') from exc
        # Lark approval-v4 instance create/cancel official error tables, read
        # 2026-09-30. 1395001 (service error) is deliberately excluded.
        rejected={'/approval/v4/instances':('create',{1390001,1390015,1390013}),
                  '/approval/v4/instances/cancel':('cancel',{1390001,1390002,1390003,1390018})}
        if method=='POST' and response.status_code==400 and path in rejected:
            try:payload=response.json()
            except (ValueError,TypeError):payload=None
            operation,codes=rejected[path]
            if isinstance(payload,dict) and type(payload.get('code')) is int and payload['code'] in codes:
                raise NativeRequestRejected(operation,payload['code'])
        try: retry_after=max(1,int(response.headers.get('x-ogw-ratelimit-reset',response.headers.get('Retry-After','60'))))
        except ValueError: retry_after=60
        retry_codes=(1254290,99991400,1254607)
        if response.status_code==429:
            raise RemoteFailure('Lark 限流，稍後重試','retry',retry_after)
        if response.status_code in (401,403): raise RemoteFailure('Lark 授權或資源權限不足','blocked')
        if response.status_code>=500: raise RemoteFailure('Lark 服務暫時不可用','outcome_unknown' if method!='GET' else 'failed')
        if response.status_code>=400:
            try: error=response.json()
            except (ValueError,TypeError): error=None
            if isinstance(error,dict) and error.get('code') in retry_codes:
                raise RemoteFailure(f"Lark 拒絕請求（{error['code']}）",'retry',retry_after)
            raise RemoteFailure(f'Lark 請求失敗 HTTP {response.status_code}','blocked')
        try: result=response.json()
        except (ValueError,TypeError) as exc:
            raise RemoteFailure('Lark 回應無法核實','outcome_unknown' if method!='GET' else 'failed') from exc
        if not isinstance(result,dict): raise RemoteFailure('Lark 回應格式不完整','outcome_unknown' if method!='GET' else 'failed')
        if result.get('code') in retry_codes: raise RemoteFailure(f"Lark 拒絕請求（{result['code']}）",'retry',retry_after)
        if result.get('code',0)!=0: raise RemoteFailure(f"Lark 拒絕請求（{result.get('code')}）",'blocked')
        data=result.get('data',{})
        if not isinstance(data,dict): raise RemoteFailure('Lark 回應內容無法核實','outcome_unknown' if method!='GET' else 'failed')
        return data

    def record_path(self,m):
        return f"/bitable/v1/apps/{quote(m['base_token'],safe='')}/tables/{quote(m['table_id'],safe='')}/records/{quote(m['record_id'],safe='')}"

    def verify_mapping(self,m):
        path=f"/bitable/v1/apps/{quote(m['base_token'],safe='')}/tables/{quote(m['table_id'],safe='')}/fields"
        cursor=None; seen=set(); field=None
        for _ in range(30):
            params={'page_size':100}
            if cursor: params['page_token']=cursor
            result=self.request('GET',path,params=params)
            field=next((f for f in result.get('items',[]) if f['field_id']==m['field_id']),field)
            if not result.get('has_more'): break
            cursor=result.get('page_token')
            if not cursor or cursor in seen: raise RemoteFailure('欄位分頁不完整','blocked')
            seen.add(cursor)
        else: raise RemoteFailure('欄位分頁超過上限','blocked')
        expected={'text':1,'number':2,'select':3,'date':5,'checkbox':7,'person':11,'link':18}
        permitted=(18,21) if m['type']=='link' else (expected.get(m['type']),)
        if not field or field.get('type') not in permitted or field.get('field_name')!=m['field_name']: raise RemoteFailure('欄位型別或名稱已變更，映射停用','blocked')
        description=text(field.get('description'))
        if field['field_name'] in ('狀態','案件狀態','案件已入帳') or any(x in description for x in ('連接器','不可人工修改','只讀','同步帶入')): raise RemoteFailure('欄位為來源管理或狀態欄，禁止回寫','blocked')
        record=self.request('GET',self.record_path(m)).get('record',{})
        if record.get('record_id')!=m['record_id']: raise RemoteFailure('目的紀錄識別不符','blocked')
        return field,self.canonical(m,record.get('fields',{}).get(m['field_name']))

    def canonical(self,m,value):
        if value is None: return None
        if m['type']=='number': return str(Decimal(str(value)).normalize())
        if m['type']=='date': return day(value) or None
        if m['type']=='text': return text(value)
        if m['type']=='person': return sorted(v['id'] for v in value) if value and isinstance(value[0],dict) else sorted(value)
        if m['type']=='link': return sorted(link_ids(value))
        return value

    def wire_value(self,m,value):
        if value is None: return None
        if m['type']=='number': return float(Decimal(str(value)))
        if m['type']=='date': return int(datetime.fromisoformat(value).replace(tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)
        if m['type']=='person': return [{'id':v} for v in value]
        return value

    def write_input(self,m,revision):
        from .capability_write_policy import CAPABILITY_BASE, PAUSED_MESSAGE
        if m.get('base_token')==CAPABILITY_BASE:
            raise RemoteFailure(PAUSED_MESSAGE,'blocked')
        field,remote=self.verify_mapping(m)
        local=self.canonical(m,self.wire_value(m,revision['value'])); base=self.canonical(m,self.wire_value(m,revision.get('base_value')))
        if m['type']=='select' and local is not None and local not in [x['name'] for x in field.get('property',{}).get('options',[])]: raise RemoteFailure('遠端選項已變更','blocked')
        if remote not in (base,local): raise RemoteFailure('遠端同欄位已修改，請核對差異','conflict')
        if remote!=local:
            try: self.request('PUT',self.record_path(m),json={'fields':{m['field_name']:self.wire_value(m,revision['value'])}})
            except RemoteFailure as exc:
                if exc.status!='outcome_unknown': raise
                remote=self.canonical(m,self.request('GET',self.record_path(m)).get('record',{}).get('fields',{}).get(m['field_name']))
                if remote!=local: raise exc
        actual=self.canonical(m,self.request('GET',self.record_path(m)).get('record',{}).get('fields',{}).get(m['field_name']))
        if actual!=local: raise RemoteFailure('寫後讀回不一致','conflict')
        return {'record_id':m['record_id'],'field_id':m['field_id'],'value':actual,'verified':True}

    def message(self,recipient,content,identifier):
        result=self.request('POST','/im/v1/messages',params={'receive_id_type':'open_id'},json={'receive_id':recipient,'msg_type':'text','content':json.dumps({'text':content},ensure_ascii=False),'uuid':identifier})
        if not result.get('message_id'): raise RemoteFailure('通知結果缺少回執','outcome_unknown')
        return {'recipient':recipient,'message_id':result['message_id']}

    def verify_training_mapping(self,m):
        from .learning_sources import pages, CAPABILITY_BASE
        if m.get('base_token')!=CAPABILITY_BASE or m.get('purpose')!='training': raise RemoteFailure('訓練寫入目的未列入白名單','blocked')
        tables=pages(self,f'/bitable/v1/apps/{quote(CAPABILITY_BASE,safe="")}/tables')
        catalog=[t for t in tables if t.get('name')=='能力地圖總表']
        if len(catalog)!=1: raise RemoteFailure('能力地圖總表缺少或同名，無法核實技能關聯','blocked')
        catalog_id=catalog[0]['table_id']
        root=f"/bitable/v1/apps/{quote(m['base_token'],safe='')}/tables/{quote(m['table_id'],safe='')}"
        fields=pages(self,root+'/fields'); by_name={f['field_name']:f for f in fields}
        # Use typed columns, not an opaque full-record JSON cell.
        schema={'key':1,'title':1,'trainee':11,'trainer':11,'skills':18,'planned_date':5,'status':1,'summary':1,'evidence':1,'version':2}
        if set(m.get('fields',{}))!=set(schema): raise RemoteFailure('訓練欄位映射不完整','blocked')
        if len(set(m['fields'].values()))!=len(schema): raise RemoteFailure('多個訓練欄位不可覆寫同一目的欄','blocked')
        for semantic,kind in schema.items():
            field=by_name.get(m['fields'][semantic]); valid=(18,21) if kind==18 else (kind,)
            if not field or field.get('type') not in valid: raise RemoteFailure('訓練欄位型別已變更：'+semantic,'blocked')
            if semantic=='skills':
                target=field.get('property') or {}
                if target.get('table_id')!=catalog_id or target.get('app_token',CAPABILITY_BASE)!=CAPABILITY_BASE: raise RemoteFailure('訓練技能欄位未關聯至已核實的能力地圖總表','blocked')
        return root

    def write_training(self,m,plan,workspace):
        from .capability_write_policy import CAPABILITY_BASE, PAUSED_MESSAGE
        if m.get('base_token')==CAPABILITY_BASE:
            raise RemoteFailure(PAUSED_MESSAGE,'blocked')
        root=self.verify_training_mapping(m); names=m['fields']
        if not isinstance(plan.get('version'),int) or isinstance(plan['version'],bool) or plan['version']<1: raise RemoteFailure('訓練版本必須為正整數','blocked')
        identifier=workspace+':'+plan['id']+':'+str(plan['version'])
        semantic={'key':identifier,'title':plan['title'],'trainee':[{'id':plan['trainee_id']}],'trainer':[{'id':plan['trainer_id']}],'skills':plan['skill_ids'],'planned_date':self.wire_value({'type':'date'},plan['planned_date']),'status':plan['status'],'summary':plan.get('summary',''),'evidence':'\n'.join(plan.get('evidence_urls',[])),'version':plan['version']}
        fields={names[k]:v for k,v in semantic.items()}
        def find_revision():
            # This POST is read-only. Every attempt searches its immutable key before
            # any create; a matching revision is never updated, even if edited remotely.
            result=self.request('POST',root+'/records/search',params={'user_id_type':'open_id','page_size':2},json={'filter':{'conjunction':'and','conditions':[{'field_name':names['key'],'operator':'is','value':[identifier]}]}})
            rows=result.get('items',[])
            if result.get('has_more') or len(rows)>1: raise RemoteFailure('訓練版本識別碼重複，需核對來源','conflict')
            return rows[0] if rows else None
        existing=find_revision()
        rid=existing.get('record_id') if existing else None
        if existing and not rid: raise RemoteFailure('訓練來源紀錄缺少識別碼','conflict')
        if not existing:
            try:
                check=self.request('POST',root+'/records',params={'user_id_type':'open_id'},json={'fields':fields})
                rid=check.get('record',{}).get('record_id')
                if not rid: raise RemoteFailure('訓練儲存缺少回執','outcome_unknown')
            except RemoteFailure as exc:
                if exc.status!='outcome_unknown': raise
                try: recovered=find_revision()
                except RemoteFailure as read_exc:
                    if read_exc.status=='conflict': raise
                    raise exc from read_exc
                if not recovered or not recovered.get('record_id'): raise exc
                rid=recovered['record_id']
            # Detect concurrent duplicate creation as well as pre-existing duplicates.
            found=find_revision()
            if not found: raise RemoteFailure('訓練新增版本尚未能依識別碼核實','outcome_unknown')
            if found.get('record_id')!=rid: raise RemoteFailure('訓練版本識別對應不一致','conflict')
        record=self.request('GET',root+'/records/'+quote(rid,safe=''),params={'user_id_type':'open_id'}).get('record',{})
        if record.get('record_id')!=rid: raise RemoteFailure('訓練讀回紀錄識別不符','conflict')
        actual=record.get('fields',{}); types={'key':'text','title':'text','trainee':'person','trainer':'person','skills':'link','planned_date':'date','status':'text','summary':'text','evidence':'text','version':'number'}
        for key,value in semantic.items():
            mapping={'type':types[key]}
            if self.canonical(mapping,actual.get(names[key]))!=self.canonical(mapping,value):
                # Lark omits empty optional text cells.
                if value=='' and actual.get(names[key]) is None: continue
                raise RemoteFailure('訓練寫後讀回不符：'+key,'conflict')
        return {'record_id':rid,'revision_key':identifier,'version':plan['version'],'verified':True,'simulated':False}

    def folder(self,parent,name):
        # A UUID suffix in planned folder names allows reuse after a lost response.
        cursor=None; seen=set(); matches=[]
        for _ in range(100):
            params={'folder_token':parent,'page_size':200}
            if cursor: params['page_token']=cursor
            result=self.request('GET','/drive/v1/files',params=params)
            files=result.get('files'); has_more=result.get('has_more')
            if not isinstance(files,list) or type(has_more) is not bool:
                raise RemoteFailure('Drive 目錄回應不完整，停止建立資料夾','blocked')
            for item in files:
                if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not isinstance(item.get('type'),str):
                    raise RemoteFailure('Drive 目錄項目格式不完整，停止建立資料夾','blocked')
                if item['name']==name and item['type']=='folder':
                    if not isinstance(item.get('token'),str) or not item['token']:
                        raise RemoteFailure('目的資料夾缺少識別碼，需管理員核對','blocked')
                    matches.append(item)
            if not has_more: break
            next_cursor=result.get('next_page_token')
            if not isinstance(next_cursor,str) or not next_cursor or next_cursor in seen:
                raise RemoteFailure('Drive 目錄分頁不完整','blocked')
            seen.add(next_cursor)
            cursor=next_cursor
        else: raise RemoteFailure('Drive 目錄超過查詢上限','blocked')
        if len(matches)>1: raise RemoteFailure('目的資料夾重名，需管理員核對','blocked')
        if matches: return matches[0]['token']
        result=self.request('POST','/drive/v1/files/create_folder',json={'name':name,'folder_token':parent})
        if not result.get('token'): raise RemoteFailure('資料夾建立結果待核實','outcome_unknown')
        return result['token']

    def upload(self,path,parent,name):
        path=Path(path)
        if path.stat().st_size>20*1024*1024: raise RemoteFailure('第一版遠端單檔上限20MB，請拆分文件','blocked')
        with path.open('rb') as file:
            result=self.request('POST','/drive/v1/files/upload_all',data={'file_name':name,'parent_type':'explorer','parent_node':parent,'size':str(path.stat().st_size)},files={'file':(name,file,'application/octet-stream')})
        token=result.get('file_token')
        if not token: raise RemoteFailure('上傳結果缺少file token','outcome_unknown')
        return {'file_token':token,'folder_token':parent,'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

    def verify_file(self,token,expected_hash):
        # Downloading also keeps a local recoverable copy; metadata alone is insufficient.
        try: r=self.client.get(API+f'/drive/v1/files/{quote(token,safe="")}/download',headers={'Authorization':'Bearer '+self.token},follow_redirects=True)
        except httpx.HTTPError as exc: raise RemoteFailure('文件讀回失敗') from exc
        if r.status_code!=200 or hashlib.sha256(r.content).hexdigest()!=expected_hash: raise RemoteFailure('文件讀回校驗不符')
        return {'verified':True,'sha256':expected_hash,'size':len(r.content)}

def application_adapter(cfg):
    if cfg.get('LARK_WORKER_IDENTITY')!='application' or not all(cfg.get(k) for k in ('LARK_APP_ID','LARK_APP_SECRET','LARK_WORKER_ORGANIZATION')): raise RemoteFailure('背景應用連線尚未設定','blocked')
    try:
        with httpx.Client(timeout=25) as client:
            response=client.post(API+'/auth/v3/tenant_access_token/internal',json={'app_id':cfg['LARK_APP_ID'],'app_secret':cfg['LARK_APP_SECRET']})
            body=response.json()
            if response.status_code!=200 or body.get('code',0)!=0 or not body.get('tenant_access_token'): raise RemoteFailure('背景應用授權失敗','blocked')
            return LarkAdapter(body['tenant_access_token'])
    except httpx.HTTPError as exc: raise RemoteFailure('背景連線暫時不可用') from exc
