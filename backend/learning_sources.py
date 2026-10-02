"""Narrow HR readers: skills, linked capabilities and approved leave delegation only."""
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from .sources import text, link_ids
from .workflow import require, now

CAPABILITY_BASE='VwAsbezz9app3YsramgjduLYp2U'
LEAVE_DEFINITION='E9C400FC-10AD-4581-ACF7-B37B5D16CBD5'
DELEGATE_FIELD='widget17884233150800001'
APPROVAL_CACHE_TTL_SECONDS=300


def approval_is_fresh(approval,clock=None):
    """Authorization accepts only recent server verification, never client timestamps."""
    if not approval or approval.get('status')!='APPROVED': return False
    try:
        current=datetime.fromisoformat(clock or now())
        verified=datetime.fromisoformat(approval['verified_at'])
        if current.tzinfo is None or verified.tzinfo is None: return False
        return 0<=(current-verified).total_seconds()<=APPROVAL_CACHE_TTL_SECONDS
    except (ValueError,TypeError,KeyError): return False


def approval_in_period(approval,clock=None):
    if not approval_is_fresh(approval,clock): return False
    try:
        current=datetime.fromisoformat(clock or now())
        start=datetime.fromisoformat(approval['from']); end=datetime.fromisoformat(approval['to'])
        return start.tzinfo is not None and end.tzinfo is not None and start<=current<=end
    except (ValueError,TypeError,KeyError): return False


def leave_refresh_due(approval,clock=None):
    """Refresh good snapshots at four minutes; failed reads retry after one minute."""
    if not approval: return True
    try:
        current=datetime.fromisoformat(clock or now())
        last=datetime.fromisoformat(approval.get('last_refresh_attempt_at') or approval['verified_at'])
        if current.tzinfo is None or last.tzinfo is None: return True
        age=(current-last).total_seconds()
        return age<0 or age>=(60 if approval.get('status')=='UNKNOWN' else 240)
    except (ValueError,TypeError,KeyError): return True


def read_application_leave(adapter,instance_code):
    # Tenant-token endpoint, distinct from user-only /instances/detail.
    # Contract verified against official larksuite/oapi-sdk-python get_instance_request.py.
    remote=adapter.request('GET','/approval/v4/instances/'+quote(instance_code,safe=''),params={'user_id_type':'open_id','locale':'zh-TW'})
    return parse_leave(remote,instance_code)


def pages(adapter,path,params=None,key='items'):
    values=[]; cursor=None; seen=set()
    for _ in range(100):
        query=dict(params or {},page_size=100)
        if cursor: query['page_token']=cursor
        result=adapter.request('GET',path,params=query); values.extend(result.get(key,[]))
        if not result.get('has_more'): return values
        cursor=result.get('page_token'); require(cursor and cursor not in seen,'來源分頁不完整',502); seen.add(cursor)
    require(False,'來源超過完整讀取上限',502)


def account_ids(value):
    if isinstance(value,str): return [value] if value.startswith('ou_') else []
    if isinstance(value,list): return list(dict.fromkeys(x for v in value for x in account_ids(v)))
    if isinstance(value,dict):
        for key in ('id','open_id','user_id','open_ids','text'):
            if key in value:
                found=account_ids(value[key])
                if found: return found
    return []


def read_capabilities(adapter,base=CAPABILITY_BASE):
    require(base==CAPABILITY_BASE,'能力地圖來源不符',403)
    root='/bitable/v1/apps/'+base+'/tables'
    tables=pages(adapter,root)
    def table(name):
        matches=[t for t in tables if t.get('name')==name]; require(len(matches)==1,'能力來源表缺少或同名，請核對：'+name,409)
        return matches[0]['table_id']
    skills_table=table('能力地圖總表'); people_table=table('人員名單及資料')
    skill_fields=pages(adapter,root+'/'+skills_table+'/fields')
    available={f['field_name'] for f in skill_fields}
    require('技能名稱' in available,'能力地圖欄位已變更',409)
    skill_names=[name for name in ('技能名稱','技能','職系','類別','級別') if name in available]
    records=pages(adapter,root+'/'+skills_table+'/records',{'field_names':json.dumps(skill_names,ensure_ascii=False)})
    catalog=[dict(id=r['record_id'],source_record_id=r['record_id'],name=text(r.get('fields',{}).get('技能名稱')) or text(r.get('fields',{}).get('技能')),department=text(r.get('fields',{}).get('職系')),category=text(r.get('fields',{}).get('類別')),level=text(r.get('fields',{}).get('級別')),active=True,source_url=f'https://yong-xiang-survey.jp.larksuite.com/base/{base}?table={skills_table}&record={r["record_id"]}') for r in records]
    fields=pages(adapter,root+'/'+people_table+'/fields')
    mapping=next((f for f in fields if f.get('field_name')=='能力地圖點數'),None)
    require(mapping and mapping.get('type') in (18,21) and (mapping.get('property') or {}).get('table_id')==skills_table,'人員能力關聯欄位不符',409)
    names={f['field_name'] for f in fields}; require('Lark帳號' in names,'缺少可驗證的人員 Lark 身分欄位',409)
    people=pages(adapter,root+'/'+people_table+'/records',{'user_id_type':'open_id','field_names':json.dumps(['Lark帳號','能力地圖點數'],ensure_ascii=False)})
    bindings=[]
    for record in people:
        f=record.get('fields',{}); ids=account_ids(f.get('Lark帳號'))
        if len(ids)!=1: continue
        bindings.append(dict(id=record['record_id'],user_id=ids[0],base_token=base,table_id=people_table,record_id=record['record_id'],field_id=mapping['field_id'],field_name='能力地圖點數',type='link',link_type=mapping['type'],remote_value=link_ids(f.get('能力地圖點數')),verified=True,verified_at=now()))
    duplicate={b['user_id'] for b in bindings if sum(x['user_id']==b['user_id'] for x in bindings)>1}
    for b in bindings:
        if b['user_id'] in duplicate: b.update(verified=False,error='同一帳號對應多份人員資料')
    return catalog,bindings


def parse_leave(remote,instance_code):
    require((remote.get('definition_code') or remote.get('approval_code'))==LEAVE_DEFINITION,'不是已驗證的詠翔請假定義',409)
    require(remote.get('instance_code',instance_code)==instance_code,'審批實例識別不符',409)
    principal=remote.get('open_id') or remote.get('user_id')
    require(isinstance(principal,str) and principal.startswith('ou_'),'審批未返回可用的申請人 open_id',409)
    form=remote.get('form') or []
    if isinstance(form,str):
        try: form=json.loads(form)
        except ValueError: require(False,'審批表單格式無法核實',409)
    found={}
    def visit(value):
        if isinstance(value,list):
            for child in value: visit(child)
        elif isinstance(value,dict):
            if value.get('id'): found.setdefault(value['id'],[]).append(value.get('value'))
            for key,child in value.items():
                if key!='id': visit(child)
    visit(form)
    delegates=account_ids(found.get(DELEGATE_FIELD,[]))
    require(len(delegates)==1,'審批沒有唯一職務代理人',409)
    def moment(key):
        values=found.get(key,[]); require(len(values)==1,'請假起訖欄位缺少或重複',409)
        try:
            result=datetime.fromisoformat(str(values[0]).replace('Z','+00:00'))
            require(result.tzinfo is not None,'請假時間缺時區',409)
            return result.astimezone(timezone(timedelta(hours=8))).isoformat()
        except ValueError: require(False,'請假起訖格式無法核實',409)
    start=moment('widgetLeaveGroupStartTime'); end=moment('widgetLeaveGroupEndTime')
    require(start<=end,'請假期間順序錯誤',409)
    return {'id':instance_code,'approval_code':LEAVE_DEFINITION,'principal_id':principal,'delegate_id':delegates[0],'from':start,'to':end,'status':'CANCELED' if remote.get('reverted') else remote.get('status','UNKNOWN'),'verified_at':now()}
