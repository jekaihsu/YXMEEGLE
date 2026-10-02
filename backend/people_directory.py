"""Read-only company directory, with stable application-scoped identities."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
import re
from sqlalchemy import select, update

from . import storage
from .workflow import require, now, event
from .policy import upgrade
from .sources import text
from .lark_adapter import application_adapter

BASE = 'VwAsbezz9app3YsramgjduLYp2U'
TABLE_NAME = '人員名單及資料'
TABLE_ID = 'tblrXclB7LSknReZ'
OPTIONAL = {'name': ('姓名', '人員姓名', '員工姓名'),
            'department': ('部門', '所屬部門', '組別'),
            'employment': ('在職狀態', '任職狀態', '人員狀態')}
LEFT = {'離職', '已離職', '不在職'}
EMPLOYED = {'在職', '在職中', '任職中'}


def complete_pages(adapter, path, params=None):
    result=[]; seen=set(); cursor=None
    for _ in range(100):
        query=dict(params or {}, page_size=100)
        if cursor: query['page_token']=cursor
        page=adapter.request('GET', path, params=query)
        require(isinstance(page,dict) and isinstance(page.get('items'),list)
                and isinstance(page.get('has_more'),bool), '名冊分頁回應不完整，保留上次資料',502)
        result.extend(page['items'])
        if not page['has_more']: return result
        cursor=page.get('page_token')
        require(isinstance(cursor,str) and cursor and cursor not in seen,
                '名冊分頁未完整讀取，保留上次資料',502)
        seen.add(cursor)
    require(False,'名冊分頁超過完整讀取上限',502)


def fetch_directory(adapter, app_id):
    require(bool(app_id),'名冊應用身分未設定',503)
    root='/bitable/v1/apps/'+BASE+'/tables'
    tables=complete_pages(adapter,root)
    matches=[t for t in tables if t.get('name')==TABLE_NAME]
    require(len(matches)==1 and matches[0].get('table_id')==TABLE_ID,'找不到已核定的人員名單及資料表',409)
    table=matches[0]['table_id']; fields=complete_pages(adapter,root+'/'+table+'/fields')
    # The approved HR contract is exactly these four columns. A newly exposed
    # department/salary field must not silently expand what this reader requests.
    for name,kind in {'姓名':1,'人員':11,'在職':7,'內外勤':3}.items():
        found=[f for f in fields if f.get('field_name')==name]
        require(len(found)==1 and found[0].get('type')==kind,'公司名冊四欄設定已變更，請重新核對',409)
    selected={'name':'姓名','account':'人員','employment_checkbox':'在職','work_category':'內外勤'}; warnings=[]
    names=list(selected.values())
    rows=complete_pages(adapter,root+'/'+table+'/records',
                        {'user_id_type':'open_id','field_names':json.dumps(names,ensure_ascii=False)})
    people=[]; issues=[]; record_ids=set(); account_counts=Counter()
    for row in rows:
        rid=row.get('record_id'); values=row.get('fields')
        require(isinstance(rid,str) and rid and rid not in record_ids and isinstance(values,dict),
                '名冊紀錄識別重複或不完整，保留上次資料',502)
        record_ids.add(rid)
        require(set(values)<=set(names),'名冊回應包含未要求的欄位，停止處理',502)
        checked=values.get(selected['employment_checkbox'])
        employment='employed' if checked is True else 'left' if checked is False else 'unknown'
        accounts=values.get(selected['account']) or []
        if isinstance(accounts,dict): accounts=[accounts]
        if not isinstance(accounts,list): accounts=[]
        accounts=[a for a in accounts if isinstance(a,dict) and re.fullmatch(r'ou_[A-Za-z0-9]+',str(a.get('id') or a.get('open_id') or ''))]
        ids={a.get('id') or a.get('open_id') for a in accounts}
        account_counts.update(ids)
        if len(ids)!=1:
            issues.append({'record_id':rid,'reason':'missing_account' if not ids else 'multiple_accounts',
                           'employment_status':employment}); continue
        ident=next(iter(ids)); account=next(a for a in accounts if (a.get('id') or a.get('open_id'))==ident)
        name=text(values.get(selected.get('name'))) or str(account.get('name') or '').strip()
        if not name:
            issues.append({'record_id':rid,'reason':'missing_name','employment_status':employment}); continue
        if employment=='unknown': issues.append({'record_id':rid,'reason':'employment_unknown'})
        people.append({'id':ident,'name':name,'department':text(values.get(selected.get('department'))),
            'source_work_category':text(values.get(selected.get('work_category'))),
            'employment_status':employment,
            'record_id':rid})
    duplicates={ident for ident,count in account_counts.items() if count>1}
    for person in people:
        if person['id'] in duplicates: issues.append({'record_id':person['record_id'],'reason':'duplicate_account'})
    return {'complete':True,'app_id':app_id,'base_token':BASE,'table_id':table,'fetched_at':now(),
            'source_count':len(rows),'people':[p for p in people if p['id'] not in duplicates],
            'issues':issues,'field_warnings':warnings,'selected_fields':names}


def merge_directory(existing, snapshot):
    """Never merge by name, delete missing people, or restore disabled privileges."""
    users=deepcopy(existing); by_id={u['id']:u for u in users}; stats=Counter()
    source={'app_id':snapshot['app_id'],'base_token':snapshot['base_token'],'table_id':snapshot['table_id']}
    incoming={p['id'] for p in snapshot['people']}
    for person in snapshot['people']:
        current=by_id.get(person['id'])
        if current is None:
            current={'id':person['id'],'role':'member','capabilities':[],
                     'active':person['employment_status']!='left','default_workspace':'production',
                     'identity_app_id':snapshot['app_id']}
            users.append(current); by_id[current['id']]=current; stats['created']+=1
        else:
            prior=(current.get('directory_source') or {}).get('app_id')
            require(not prior or prior==snapshot['app_id'],'人員名冊屬於另一應用，停止合併',409)
            require(not current.get('identity_app_id') or current['identity_app_id']==snapshot['app_id'],
                    '人員登入身分屬於另一應用，停止合併',409)
            stats['updated']+=1
        current['name']=person['name']; current['avatar']=person['name'][:1]
        previous_category=current.get('source_work_category','')
        old_placeholder=f'來源內外勤：{previous_category}（待確認組別）' if previous_category else '待確認部門'
        category=person.get('source_work_category','')
        current['source_work_category']=category
        if current.get('department','') in ('','公司成員','待確認部門',old_placeholder):
            current.update(department=f'來源內外勤：{category}（待確認組別）' if category else '待確認部門',
                           department_source='work_category_unmapped' if category else 'unknown')
        current.update(directory_source=dict(source,record_id=person['record_id']),
            directory_status=person['employment_status'],directory_last_seen_at=snapshot['fetched_at'],
            directory_missing=False)
        if person['employment_status']=='left':
            current['active']=False; current['directory_deactivation_reason']='來源明確離職'
            stats['explicit_left']+=1
        elif not current.get('active',True):
            stats['disabled_preserved']+=1
    for current in users:
        prior=current.get('directory_source') or {}
        if prior.get('app_id')==snapshot['app_id'] and current['id'] not in incoming:
            current['directory_missing']=True; stats['missing_retained']+=1
    return users,dict(stats)


class PeopleDirectoryService:
    def __init__(self,sessions,W,B,P,cfg,fetcher=None,adapter_factory=None):
        self.sessions=sessions; self.W=W; self.B=B; self.P=P; self.cfg=cfg
        self.fetcher=fetcher or fetch_directory; self.adapter_factory=adapter_factory or application_adapter

    def _policy(self,wid):
        require(wid.startswith('lark-') and wid=='lark-'+self.cfg.get('LARK_WORKER_ORGANIZATION',''),
                '名冊同步僅限已核定的公司正式工作區',403)
        require(self.cfg.get('LARK_WORKER_IDENTITY')=='application' and self.cfg.get('LARK_APP_ID'),
                '公司背景應用身分尚未設定',503)
        tenants={v.strip() for v in self.cfg.get('LARK_ALLOWED_TENANTS','').split(',') if v.strip()}
        require(self.cfg['LARK_WORKER_ORGANIZATION'] in tenants,'名冊公司不在登入允許名單',403)
        return (self.cfg['LARK_APP_ID'],self.cfg['LARK_WORKER_ORGANIZATION'])

    def _state(self,db,row):
        state=upgrade(storage.load(db,self.B,row))
        profiles={p.person_id:deepcopy(p.data) for p in db.scalars(select(self.P).where(self.P.organization_id==row.id))}
        old={u['id'] for u in state['users']}
        state['users']=[profiles.get(u['id'],u) for u in state['users']]+[u for ident,u in profiles.items() if ident not in old]
        return state

    def _actor(self,state,actor_id):
        if actor_id is None:
            from .production_access import readonly_sync_actor
            return readonly_sync_actor(state,self.cfg,'people_directory_connection')
        actor=next((u for u in state['users'] if u['id']==actor_id),None)
        require(actor and actor.get('active',True) and (actor.get('role')=='manager'
                or set(actor.get('capabilities',[]))&{'manage_people','manage_sources'}),'沒有同步公司名冊的權限',403)
        require(not actor.get('identity_app_id') or actor['identity_app_id']==self.cfg.get('LARK_APP_ID'),
                '同步人員的身分屬於另一應用，需先核對',403)
        from .production_access import admitted
        require(admitted(actor,self.cfg.get('LARK_APP_ID')),'名冊同步操作者尚未核實在職身分',403)
        return actor

    def _save(self,db,row,state):
        state['version']=row.version+1
        result=db.execute(update(self.W).where(self.W.id==row.id,self.W.version==row.version)
            .values(version=state['version'],data=storage.save(db,self.B,row.id,state)))
        require(result.rowcount==1,'名冊同步版本衝突，請重試',409)

    def failure(self,wid,message,expected_generation=None):
        with self.sessions.begin() as db:
            row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update())
            if not row: return
            state=self._state(db,row)
            if expected_generation is not None and state.get('people_directory_status',{}).get('sync_revision',0)!=expected_generation:
                return
            state.setdefault('people_directory_status',{}).update(status='error',last_attempt_at=now(),message=message)
            self._save(db,row,state)

    def sync(self,wid,actor_id):
        policy=self._policy(wid)
        with self.sessions() as db:
            row=db.get(self.W,wid); require(row is not None,'工作區不存在',404)
            state=self._state(db,row); self._actor(state,actor_id)
            require(state.get('environment') not in ('test','demo'),'隔離工作區不可同步正式名冊',403)
            prior=state.get('people_directory_status',{}).get('app_id')
            require(not prior or prior==policy[0],'Lark應用已變更，請先核對名冊身分',409)
            generation=state.get('people_directory_status',{}).get('sync_revision',0)
        adapter=None
        try:
            adapter=self.adapter_factory(deepcopy(self.cfg))
            require(self._policy(wid)==policy,'名冊同步設定已變更',409)
            def check():
                require(self._policy(wid)==policy,'名冊同步設定已變更',409)
                with self.sessions() as db:
                    row=db.get(self.W,wid); require(row is not None,'工作區不存在',404)
                    fresh=self._state(db,row); self._actor(fresh,actor_id)
                    require(fresh.get('environment') not in ('test','demo'),'工作區環境已變更',403)
            check()
            from .jobs import PermissionCheckedClient
            adapter.client=PermissionCheckedClient(adapter.client,check)
            snapshot=self.fetcher(adapter,policy[0])
            require(snapshot.get('complete') is True and snapshot.get('app_id')==policy[0]
                    and snapshot.get('base_token')==BASE and snapshot.get('table_id')==TABLE_ID
                    and isinstance(snapshot.get('people'),list) and isinstance(snapshot.get('issues'),list),
                    '名冊快照不完整或來源不符，保留上次資料',502)
            with self.sessions.begin() as db:
                require(self._policy(wid)==policy,'名冊同步設定已變更',409)
                row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update())
                require(row is not None,'工作區不存在',404)
                state=self._state(db,row); actor=self._actor(state,actor_id)
                require(state.get('environment') not in ('test','demo'),'工作區環境已变更',403)
                require(state.get('people_directory_status',{}).get('sync_revision',0)==generation,
                        '已有較新名冊同步完成，請重新讀取；保留最新人員資料',409)
                users,stats=merge_directory(state['users'],snapshot)
                state['users']=users
                for person in users:
                    profile=db.get(self.P,(wid,person['id']))
                    if profile:
                        if profile.data!=person: profile.data=deepcopy(person)
                    else: db.add(self.P(organization_id=wid,person_id=person['id'],data=deepcopy(person)))
                review=bool(snapshot['issues'] or snapshot.get('field_warnings') or stats.get('missing_retained') or snapshot['source_count']==0)
                state['people_directory_status']={'status':'review_required' if review else 'ready',
                    'last_success_at':snapshot['fetched_at'],'last_attempt_at':now(),
                    'sync_revision':generation+1,
                    'app_id':policy[0],'base_token':BASE,'table_id':snapshot['table_id'],
                    'source_count':snapshot['source_count'],'valid_people':len(snapshot['people']),
                    'issues':snapshot['issues'],'field_warnings':snapshot.get('field_warnings',[]),
                    'stats':stats,'message':'已唯讀更新公司名冊；缺漏或重複身分保留待核對' if review else '已唯讀更新公司名冊；未讀取薪資、未更改授權'}
                from .production_access import readonly_sync_connection
                prior=state.get('people_directory_connection',{})
                state['people_directory_connection']=readonly_sync_connection(self.cfg,actor_id or prior.get('authorized_by') or prior.get('actor_id'))
                event(state,actor,'people_directory_sync',message='唯讀同步人員名冊，保留原有授權及歷史')
                self._save(db,row,state)
                return deepcopy(state['people_directory_status'])
        except Exception as exc:
            from fastapi import HTTPException
            message=exc.detail if isinstance(exc,HTTPException) else '公司名冊讀取失敗；保留上次成功資料'
            self.failure(wid,message,generation)
            if isinstance(exc,HTTPException): raise
            raise HTTPException(502,message) from exc
        finally:
            if adapter: adapter.client.close()

    def run_due(self,wid):
        if not wid.startswith('lark-') or wid!='lark-'+self.cfg.get('LARK_WORKER_ORGANIZATION',''): return None
        with self.sessions.begin() as db:
            row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update())
            if not row: return None
            state=self._state(db,row); connection=state.get('people_directory_connection',{})
            if not connection.get('enabled'): return None
            status=state.setdefault('people_directory_status',{}); previous=status.get('last_attempt_at')
            if previous:
                try:
                    age=(datetime.fromisoformat(now())-datetime.fromisoformat(previous)).total_seconds()
                    if age<300: return None
                except (ValueError,TypeError): pass
            status['last_attempt_at']=now(); self._save(db,row,state)
        return self.sync(wid,None)
