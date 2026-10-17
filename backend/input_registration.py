"""Append-only Input registrations in a dedicated Base; never source cell edits.

The caller persists a plan before queueing, pins its destination via
connection_policy, and wraps the adapter with authorization at every HTTP hop.
An uncertain create is reconciled by reads only, never blindly re-created.
"""
from copy import deepcopy
import hashlib
import json
from urllib.parse import quote
from uuid import uuid4
from .lark_adapter import RemoteFailure
from .sources import text
from .remote_policy import FORMAL_BASES

FIELD_NAMES={
    'registration_key':'登錄識別', 'workspace_id':'工作區識別',
    'project_id':'案件識別', 'node_id':'節點識別', 'revision_id':'修訂識別',
    'actor_id':'提交人識別', 'submitted_at':'提交時間',
    'content_json':'登錄內容', 'content_hash':'內容雜湊',
}


def registration_fields(cfg,policy):
    """Mode-pinned schema: never fall back from test to formal field IDs."""
    mode=policy.get('mode')
    if mode not in ('production','isolated_live') or policy.get('simulated') is not False:
        raise RemoteFailure('Input 登錄未使用已核定實際連線','blocked')
    key='LARK_TEST_INPUT_REGISTRATION_FIELDS_JSON' if mode=='isolated_live' else 'LARK_INPUT_REGISTRATION_FIELDS_JSON'
    other='LARK_INPUT_REGISTRATION_FIELDS_JSON' if mode=='isolated_live' else 'LARK_TEST_INPUT_REGISTRATION_FIELDS_JSON'
    try:
        fields=json.loads(cfg.get(key) or '{}');opposite=json.loads(cfg.get(other) or '{}')
        if not isinstance(fields,dict) or set(fields)!=set(FIELD_NAMES) or not isinstance(opposite,dict):raise ValueError()
        ids={f['field_id'] for f in fields.values()}
        if len(ids)!=9 or not all(isinstance(i,str) and i for i in ids):raise ValueError()
        if ids & {f.get('field_id') for f in opposite.values() if isinstance(f,dict)}:
            raise RemoteFailure('正式與隔離測試 Input 不得混用欄位識別','blocked')
    except (ValueError,TypeError,KeyError):raise RemoteFailure('Input 登錄欄位設定無效或不完整','blocked')
    return deepcopy(fields)


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def fingerprint(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def make_plan(workspace_id,project,node,revision,destination):
    """Persist the returned immutable plan with the revision before any HTTP."""
    required=(workspace_id,project.get('id'),node.get('id'),revision.get('id'),
              revision.get('actor_id'),revision.get('created_at'))
    if not all(isinstance(x,str) and x for x in required):
        raise RemoteFailure('Input 登錄識別或提交人不完整','blocked')
    if revision.get('project_id')!=project['id'] or revision.get('node_id')!=node['id']:
        raise RemoteFailure('Input 修訂與案件節點不一致','blocked')
    key=fingerprint({'workspace':workspace_id,'revision':revision['id']})
    content={'project_code':project.get('code'),'mapping_id':revision.get('mapping_id'),
             'key':revision.get('key'),'label':revision.get('label'),
             'value':deepcopy(revision.get('value')),'base_value':deepcopy(revision.get('base_value'))}
    values=dict(registration_key=key,workspace_id=workspace_id,project_id=project['id'],
                node_id=node['id'],revision_id=revision['id'],actor_id=revision['actor_id'],
                submitted_at=revision['created_at'],content_json=canonical(content),content_hash=fingerprint(content))
    plan={'version':1,'destination':deepcopy(destination),'values':values,'client_token':str(uuid4())}
    plan['plan_hash']=fingerprint(plan)
    return plan


def validate_plan(plan,policy):
    if not isinstance(plan,dict) or plan.get('version')!=1:
        raise RemoteFailure('Input 登錄契約不完整','blocked')
    unsigned={k:v for k,v in plan.items() if k!='plan_hash'}
    if plan.get('plan_hash')!=fingerprint(unsigned):raise RemoteFailure('Input 登錄內容已改版','blocked')
    dest=plan.get('destination') or {}
    if (not dest.get('base_token') or dest['base_token'] in FORMAL_BASES or
        dest.get('base_token')!=policy.get('base_token') or not dest.get('table_id') or
        dest['table_id']!=policy.get('table_id') or policy.get('simulated') is not False):
        raise RemoteFailure('Input 專用登錄目的未核定','blocked')
    fields=dest.get('fields') or {}
    if set(fields)!=set(FIELD_NAMES) or any(not isinstance(f,dict) or not f.get('field_id') or
            f.get('field_name')!=FIELD_NAMES[key] for key,f in fields.items()):
        raise RemoteFailure('Input 登錄欄位映射不完整','blocked')
    if len({f['field_id'] for f in fields.values()})!=len(fields):
        raise RemoteFailure('Input 登錄欄位識別重複','blocked')
    if set(plan.get('values',{}))!=set(FIELD_NAMES):raise RemoteFailure('Input 登錄內容欄位不完整','blocked')
    return dest


class RegistrationAdapter:
    def __init__(self,adapter):self.adapter=adapter

    def _pages(self,path,query=None):
        cursor=None;seen=set()
        for _ in range(200):
            params={'page_size':100}
            if cursor:params['page_token']=cursor
            if query is None:
                data=self.adapter.request('GET',path,params=params)
            else:
                try:data=self.adapter.request('POST',path+'/search',params=params,json=query)
                except RemoteFailure as exc:
                    if exc.status=='outcome_unknown':raise RemoteFailure('Input 查詢暫時失敗；未執行新增','failed') from exc
                    raise
            if not isinstance(data,dict) or type(data.get('has_more')) is not bool:
                raise RemoteFailure('Input 登錄分頁狀態不完整','blocked')
            items=data.get('items')
            # Lark v1 omits items for an empty table. Accept only the observed
            # complete first-page shape; missing pages/cursors are not emptiness.
            if ('items' not in data and cursor is None and data.get('has_more') is False
                    and type(data.get('total')) is int and data['total']==0
                    and not data.get('page_token')):
                items=[]
            if not isinstance(items,list) or any(not isinstance(item,dict) for item in items):
                raise RemoteFailure('Input 登錄分頁內容不完整','blocked')
            if data['has_more'] is False and data.get('page_token'):
                raise RemoteFailure('Input 登錄分頁結尾不一致','blocked')
            if data['has_more'] is True and (not isinstance(data.get('page_token'),str)
                    or not data['page_token'] or data['page_token'] in seen):
                raise RemoteFailure('Input 登錄分頁不完整','blocked')
            yield from items
            if data['has_more'] is False:return
            cursor=data.get('page_token')
            if not cursor or cursor in seen:raise RemoteFailure('Input 登錄分頁不完整','blocked')
            seen.add(cursor)
        raise RemoteFailure('Input 登錄分頁超過上限','blocked')

    def _prepare(self,plan,policy):
        dest=validate_plan(plan,policy)
        prefix=f"/bitable/v1/apps/{quote(dest['base_token'],safe='')}/tables/{quote(dest['table_id'],safe='')}"
        remote={f.get('field_id'):f for f in self._pages(prefix+'/fields')}
        for f in dest['fields'].values():
            actual=remote.get(f['field_id']) or {}
            if actual.get('type')!=1 or actual.get('field_name')!=f['field_name']:
                raise RemoteFailure('Input 登錄欄位已改名或型別不符','blocked')
        expected={dest['fields'][key]['field_name']:value for key,value in plan['values'].items()}
        return prefix+'/records',expected

    def _find(self,path,plan,expected):
        key=plan['values']['registration_key'];name=FIELD_NAMES['registration_key']
        query={'field_names':list(expected),'filter':{'conjunction':'and',
               'conditions':[{'field_name':name,'operator':'is','value':[key]}]}}
        matches=[]
        for row in self._pages(path,query):
            if not isinstance(row.get('fields'),dict) or text(row['fields'].get(name))!=key:
                raise RemoteFailure('Input 查詢篩選結果不符，停止登錄','blocked')
            matches.append(row)
            if len(matches)>1:break
        if len(matches)>1:raise RemoteFailure('Input 登錄識別重複，需人工核對','conflict')
        if not matches:return None
        row=matches[0]
        if not row.get('record_id') or any(text(row.get('fields',{}).get(k))!=v for k,v in expected.items()):
            raise RemoteFailure('Input 登錄同識別內容不一致，保留原紀錄','conflict')
        return row['record_id']

    def reconcile(self,plan,policy):
        """Read-only search; absence never authorizes another uncertain create."""
        path,expected=self._prepare(plan,policy)
        ident=self._find(path,plan,expected)
        if not ident:raise RemoteFailure('尚未查到登錄，不代表先前未寫入；保留待核實','outcome_unknown')
        return self._receipt(plan,ident)

    def confirm_absent(self,plan,policy):
        """Read-only freshness check for an explicit not-created disposal.

        Returns normally only when a complete filtered search finds no row. A
        found, duplicate or changed row means the caller must reconcile instead.
        """
        path,expected=self._prepare(plan,policy)
        if self._find(path,plan,expected):
            raise RemoteFailure('遠端已有此登錄，請改用查回核實，不可處置為未建立','conflict')

    def submit(self,plan,policy):
        path,expected=self._prepare(plan,policy)
        ident=self._find(path,plan,expected)
        if not ident:
            try:self.adapter.request('POST',path,params={'client_token':plan['client_token']},json={'fields':expected})
            except RemoteFailure as exc:
                if exc.status!='outcome_unknown':raise
                try:return self.reconcile(plan,policy)
                except RemoteFailure as read_exc:
                    raise RemoteFailure('登錄送出結果尚未核實，請使用唯讀查回','outcome_unknown') from read_exc
            except Exception as exc:
                # A non-remote error once the POST was issued (e.g. a permission
                # re-check) cannot prove the row was not created.
                raise RemoteFailure('登錄送出期間發生未核實錯誤，請使用唯讀查回','outcome_unknown') from exc
            # POST success is insufficient: independently read the complete row.
            try:return self.reconcile(plan,policy)
            except Exception as read_exc:
                raise RemoteFailure('登錄已送出但讀回尚未核實，請使用唯讀查回','outcome_unknown') from read_exc
        return self._receipt(plan,ident)

    @staticmethod
    def _receipt(plan,ident):
        return {'record_id':ident,'registration_key':plan['values']['registration_key'],
                'plan_hash':plan['plan_hash'],'verified':True,'operation':'append_registration',
                'verification_basis':'remote_current_row_matches_plan'}
