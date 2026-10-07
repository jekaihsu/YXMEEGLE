"""Directory synchronization uses fake HTTP/state only, never salary records."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest
from fastapi import HTTPException

from . import people_directory as directory, storage
from .people_directory import fetch_directory, merge_directory, PeopleDirectoryService, BASE, TABLE_ID
from .test_source_sync import harness
from .workflow import apply_action


def person(ident='ou_new', name='同名同事', status='employed', record='rec1'):
    return {'id':ident,'name':name,'department':'控制','employment_status':status,'record_id':record}


def snapshot(people=None):
    people=[person()] if people is None else people
    return {'complete':True,'app_id':'app1','base_token':BASE,'table_id':TABLE_ID,
            'fetched_at':'2026-09-27T10:00:00+08:00','source_count':len(people),
            'people':people,'issues':[],'field_warnings':[]}


class Pages:
    def __init__(self, responses): self.responses=responses; self.calls=[]
    def request(self, method, path, **kwargs):
        assert method=='GET'
        self.calls.append((path,deepcopy(kwargs)))
        return self.responses.pop(0)


def schema():
    return [dict(field_name='人員',type=11),dict(field_name='姓名',type=1),
            dict(field_name='內外勤',type=3),dict(field_name='在職',type=7),
            dict(field_name='薪資',type=2),dict(field_name='銀行帳號',type=1)]


def page(items, more=False, token=None):
    return {'items':items,'has_more':more,'page_token':token}


def row(rid, ident, name='同名同事', status='在職'):
    return {'record_id':rid,'fields':{'人員':[{'id':ident,'name':name}] if ident else [],
                                    '內外勤':'內勤','在職':status=='在職'}}


def test_fetch_reads_only_whitelisted_fields_all_pages_and_keeps_same_name_distinct():
    adapter=Pages([page([{'table_id':TABLE_ID,'name':'人員名單及資料'}]),page(schema()),
        page([row('r1','ou_one')],True,'next'),page([row('r2','ou_two')])])
    result=fetch_directory(adapter,'app1')
    assert [p['id'] for p in result['people']]==['ou_one','ou_two']
    assert result['source_count']==2 and result['complete']
    for _,kw in adapter.calls[2:]:
        assert set(json.loads(kw['params']['field_names']))=={'人員','姓名','內外勤','在職'}
        assert kw['params']['user_id_type']=='open_id'
    assert adapter.calls[-1][1]['params']['page_token']=='next'


def test_bad_identity_rows_are_reported_and_duplicate_account_is_never_merged():
    multiple=row('multi','ou_a'); multiple['fields']['人員'].append({'id':'ou_b','name':'另一位'})
    adapter=Pages([page([{'table_id':TABLE_ID,'name':'人員名單及資料'}]),page(schema()),page([
        row('missing',None),row('one','ou_dup'),row('two','ou_dup'),multiple,row('good','ou_ok')])])
    result=fetch_directory(adapter,'app1')
    assert [p['id'] for p in result['people']]==['ou_ok']
    assert sorted(i['reason'] for i in result['issues'])==['duplicate_account','duplicate_account','missing_account','multiple_accounts']


def test_duplicate_identity_is_quarantined_even_when_one_row_has_no_name():
    adapter=Pages([page([{'table_id':TABLE_ID,'name':'人員名單及資料'}]),page(schema()),
                   page([row('r1','ou_dup',name=''),row('r2','ou_dup')])])
    result=fetch_directory(adapter,'app1')
    assert not result['people']
    assert {i['reason'] for i in result['issues']}=={'missing_name','duplicate_account'}


def test_missing_account_reports_employment_without_guessing_same_name_identity():
    entries=[{'record_id':'rec'+str(i),'fields':{'姓名':'同名同事','人員':[], '在職':checked,'內外勤':'內勤'}}
             for i,checked in enumerate([True,False,None])]
    adapter=Pages([page([{'table_id':TABLE_ID,'name':'人員名單及資料'}]),page(schema()),page(entries)])
    result=fetch_directory(adapter,'app1')
    assert result['people']==[]
    assert [i['employment_status'] for i in result['issues']]==['employed','left','unknown']
    assert {i['reason'] for i in result['issues']}=={'missing_account'}
    prior={'id':'ou_existing','name':'同名同事','role':'manager','active':True,
           'directory_source':{'app_id':'app1','record_id':'recOld'},'directory_status':'employed'}
    users,stats=merge_directory([prior],result)
    assert len(users)==1 and users[0]['id']=='ou_existing'
    assert users[0]['active'] and users[0]['directory_missing']
    from .production_access import admitted
    assert not admitted(users[0],'app1')
    assert not stats.get('explicit_left')


def actual_schema():
    return [dict(field_id='fldhYxrH9E',field_name='姓名',type=1),
            dict(field_id='fldOCtTTze',field_name='人員',type=11),
            dict(field_id='fldsl05S5S',field_name='在職',type=7),
            dict(field_id='fldrj1YPHn',field_name='內外勤',type=3),
            dict(field_name='薪資',type=2)]


@pytest.mark.parametrize('value,expected',[(True,'employed'),(False,'left'),(None,'unknown'),('false','unknown'),(0,'unknown'),('missing','unknown')])
def test_verified_actual_schema_checkbox_is_strict_and_category_is_not_a_department(value,expected):
    fields={'姓名':'同事','人員':[{'id':'ou_verified','name':'帳號名'}],'內外勤':'外勤'}
    if value!='missing': fields['在職']=value
    adapter=Pages([page([{'table_id':'tblrXclB7LSknReZ','name':'人員名單及資料'}]),
                   page(actual_schema()),page([{'record_id':'recVerified','fields':fields}])])
    result=fetch_directory(adapter,'app1')
    person=result['people'][0]
    assert person['employment_status']==expected and person['source_work_category']=='外勤'
    assert person['department']=='' and person['name']=='同事'
    assert set(json.loads(adapter.calls[-1][1]['params']['field_names']))=={'姓名','人員','在職','內外勤'}
    users,_=merge_directory([],result)
    assert users[0]['department']=='來源內外勤：外勤（待確認組別）'
    assert users[0]['active']==(expected!='left')


@pytest.mark.parametrize('bad',['ambiguous_account','text_account','text_checkbox','number_category'])
def test_actual_schema_drift_or_ambiguous_account_does_not_guess_mapping(bad):
    fields=actual_schema()
    if bad=='ambiguous_account': fields.append({'field_name':'人員','type':11})
    elif bad=='text_account': fields[1]['type']=1
    elif bad=='text_checkbox': fields[2]['type']=1
    else: fields[3]['type']=2
    adapter=Pages([page([{'table_id':TABLE_ID,'name':'人員名單及資料'}]),page(fields)])
    with pytest.raises(HTTPException): fetch_directory(adapter,'app1')
    assert len(adapter.calls)==2  # Never read records under an unverified mapping.


def test_work_category_updates_only_placeholder_and_preserves_actual_department():
    source=snapshot([dict(person(),department='',source_work_category='外勤')])
    users,_=merge_directory([],source)
    source['people'][0]['source_work_category']='內勤'
    users,_=merge_directory(users,source)
    assert users[0]['department']=='來源內外勤：內勤（待確認組別）'
    users[0]['department']='已核實控制組'
    source['people'][0]['source_work_category']='外勤'
    users,_=merge_directory(users,source)
    assert users[0]['department']=='已核實控制組' and users[0]['source_work_category']=='外勤'


@pytest.mark.parametrize('bad', ['cursor', 'response', 'salary', 'repeat_record', 'text_account'])
def test_incomplete_or_unexpected_schema_data_cannot_be_applied(bad):
    fields=schema(); records=page([row('r','ou_one')])
    if bad=='cursor': records.update(has_more=True,page_token=None)
    elif bad=='response': records.pop('has_more')
    elif bad=='salary': records['items'][0]['fields']['薪資']='must never be retained'
    elif bad=='repeat_record': records['items'].append(row('r','ou_two'))
    else: fields[0]['type']=1
    adapter=Pages([page([{'table_id':TABLE_ID,'name':'人員名單及資料'}]),page(fields),records])
    with pytest.raises(HTTPException): fetch_directory(adapter,'app1')


def test_merging_renames_preserves_privileges_disable_and_historical_links():
    existing=[{'id':'ou_one','name':'舊名','role':'manager','capabilities':['manage_people'],'active':False},
              {'id':'ou_missing','name':'原同事','role':'member','active':True,
               'directory_source':{'app_id':'app1','record_id':'old'}}]
    updated,stats=merge_directory(existing,snapshot([person('ou_one','新名'),person('ou_new','新名',record='r2')]))
    first=next(p for p in updated if p['id']=='ou_one')
    assert first['name']=='新名' and not first['active'] and first['role']=='manager'
    assert first['capabilities']==['manage_people']
    new=next(p for p in updated if p['id']=='ou_new')
    assert new['role']=='member' and new['capabilities']==[]
    missing=next(p for p in updated if p['id']=='ou_missing')
    assert missing['active'] and missing['directory_missing']
    assert existing[0]['name']=='舊名' and stats['missing_retained']==1


def test_explicit_left_disables_but_rehire_does_not_restore_and_other_app_rejected():
    users,_=merge_directory([],snapshot([person(status='left')]))
    assert not users[0]['active']
    users,_=merge_directory(users,snapshot())
    assert not users[0]['active']
    users[0]['directory_source']['app_id']='other-app'
    with pytest.raises(HTTPException): merge_directory(users,snapshot())
    users[0]['directory_source']['app_id']='app1'; users[0]['identity_app_id']='other-login-app'
    with pytest.raises(HTTPException): merge_directory(users,snapshot())


@pytest.fixture
def directory_service(harness,monkeypatch):
    h=harness
    monkeypatch.setattr(directory,'now',lambda:h.clock[0])
    h.cfg.update(LARK_APP_ID='app1',LARK_WORKER_IDENTITY='application',
                 LARK_WORKER_ORGANIZATION='tenant',LARK_ALLOWED_TENANTS='tenant')
    calls=[]
    def factory(cfg):
        calls.append(cfg['LARK_APP_ID'])
        return SimpleNamespace(client=SimpleNamespace(close=lambda:None))
    service=PeopleDirectoryService(h.sessions,h.W,h.B,h.P,h.cfg,
        fetcher=lambda adapter,appid:snapshot(),adapter_factory=factory)
    return h,service,calls


def test_sync_writes_shared_person_profile_and_keeps_case_ids_history(directory_service):
    h,service,calls=directory_service; before,_=h.read()
    result=service.sync(h.wid,'u-manager'); state,_=h.read()
    assert result['status']=='ready' and result['last_success_at']==h.clock[0]
    assert state['projects']==before['projects']
    with h.sessions() as db:
        profile=db.get(h.P,(h.wid,'ou_new')).data
        assert profile['role']=='member' and profile['capabilities']==[]
    assert state['people_directory_connection']['enabled'] and len(calls)==1


@pytest.mark.parametrize('bad',['partial','wrong_app','wrong_base','failure'])
def test_failed_snapshot_preserves_people_and_last_success(directory_service,bad):
    h,service,_=directory_service; service.sync(h.wid,'u-manager'); before,_=h.read()
    h.clock[0]='2026-09-27T10:05:00+08:00'
    def fetch(*args):
        if bad=='failure': raise OSError('not published')
        value=snapshot([person('ou_replacement')])
        if bad=='partial': value['complete']=False
        if bad=='wrong_app': value['app_id']='other'
        if bad=='wrong_base': value['base_token']='other'
        return value
    service.fetcher=fetch
    with pytest.raises(HTTPException): service.sync(h.wid,'u-manager')
    state,_=h.read()
    assert state['users']==before['users'] and state['projects']==before['projects']
    assert state['people_directory_status']['last_success_at']==before['people_directory_status']['last_success_at']
    assert state['people_directory_status']['last_attempt_at']==h.clock[0]


def test_empty_snapshot_preserves_existing_active_users(directory_service):
    h,service,_=directory_service; service.sync(h.wid,'u-manager')
    service.fetcher=lambda *args:snapshot([])
    result=service.sync(h.wid,'u-manager'); state,_=h.read()
    assert result['status']=='review_required' and result['stats']['missing_retained']==1
    assert next(u for u in state['users'] if u['id']=='ou_new')['active']


def test_permissions_rechecked_before_commit_and_before_external_io(directory_service):
    h,service,calls=directory_service
    def revoke(*args):
        with h.sessions.begin() as db:
            row=db.get(h.P,(h.wid,'u-manager')); user=deepcopy(row.data); user['active']=False; row.data=user
        return snapshot()
    service.fetcher=revoke
    with pytest.raises(HTTPException) as exc: service.sync(h.wid,'u-manager')
    assert exc.value.status_code==403
    state,_=h.read(); assert not any(u['id']=='ou_new' for u in state['users'])
    with pytest.raises(HTTPException): service.sync(h.wid,'u-manager')
    assert len(calls)==1


@pytest.mark.parametrize('wid',['demo-tenant','test-lark-tenant','lark-other'])
def test_wrong_company_and_isolated_workspaces_never_fetch(directory_service,wid):
    _,service,calls=directory_service
    with pytest.raises(HTTPException): service.sync(wid,'u-manager')
    assert not calls


def test_worker_throttles_and_configuration_change_does_not_mix_app_ids(directory_service):
    h,service,calls=directory_service; service.sync(h.wid,'u-manager')
    assert service.run_due(h.wid) is None and len(calls)==1
    h.clock[0]='2026-09-27T10:05:00+08:00'
    service.run_due(h.wid); assert len(calls)==2
    h.cfg['LARK_APP_ID']='different'
    with pytest.raises(HTTPException): service.sync(h.wid,'u-manager')
    assert len(calls)==2


def test_actor_from_another_application_cannot_trigger_directory_io(directory_service):
    h,service,calls=directory_service
    with h.sessions.begin() as db:
        row=db.get(h.P,(h.wid,'u-manager')); data=deepcopy(row.data)
        data['identity_app_id']='another-app'; row.data=data
    with pytest.raises(HTTPException): service.sync(h.wid,'u-manager')
    assert not calls


def test_overlapping_stale_snapshot_never_replaces_newer_committed_directory(directory_service):
    h,service,_=directory_service
    def outer_fetch(*args):
        service.fetcher=lambda *args:snapshot([person('ou_newer')])
        service.sync(h.wid,'u-manager')
        return snapshot([person('ou_stale')])
    service.fetcher=outer_fetch
    with pytest.raises(HTTPException) as exc: service.sync(h.wid,'u-manager')
    assert exc.value.status_code==409
    state,_=h.read()
    assert any(u['id']=='ou_newer' for u in state['users'])
    assert not any(u['id']=='ou_stale' for u in state['users'])
    assert state['people_directory_status']['sync_revision']==1
    assert state['people_directory_status']['status']=='ready'


def test_late_network_failure_does_not_replace_newer_directory_success(directory_service):
    h,service,_=directory_service
    def outer_fetch(*args):
        service.fetcher=lambda *args:snapshot([person('ou_newer')])
        service.sync(h.wid,'u-manager')
        raise OSError('older request failed after newer commit')
    service.fetcher=outer_fetch
    with pytest.raises(HTTPException) as exc:service.sync(h.wid,'u-manager')
    assert exc.value.status_code==502
    state,_=h.read()
    assert state['people_directory_status']['status']=='ready'
    assert state['people_directory_status']['sync_revision']==1
    assert any(u['id']=='ou_newer' for u in state['users'])


def test_mentions_validate_ids_preserve_history_and_queue_one_recipient(harness):
    h=harness; ws,_=h.read(); p=ws['projects'][0]; user=next(u for u in ws['users'] if u['id']=='u-manager')
    p['execution_system']='workbench'
    body={'action':'comment_add','project_id':p['id'],'payload':{'body':'請同事核對','mentions':['u-pm','u-pm']}}
    jobs=deepcopy(ws['jobs']); apply_action(ws,user,body,True)
    saved=p['comments'][-1]; assert saved['mentions']==['u-pm']
    assert len(ws['jobs'])==len(jobs)+1 and ws['jobs'][-1]['kind']=='mention'
    assert saved['notifications'][0]['job_id']==ws['jobs'][-1]['id']
    next(u for u in ws['users'] if u['id']=='u-pm').update(name='更名',active=False)
    assert saved['mentions']==['u-pm']
    with pytest.raises(HTTPException): apply_action(ws,user,body,True)
    body['payload']['mentions']=['同名文字']
    with pytest.raises(HTTPException): apply_action(ws,user,body,True)
    assert len(p['comments'])==1


def test_roster_timer_live_gate_and_configured_interval(harness,monkeypatch):
    h=harness;clock=['2026-09-27T10:00:00+08:00']
    monkeypatch.setattr(directory,'now',lambda:clock[0])
    service=PeopleDirectoryService(h.sessions,h.W,h.B,h.P,h.cfg,
        fetcher=lambda *args:snapshot(),adapter_factory=h.service.adapter_factory)
    service.sync(h.wid,'u-manager')
    h.cfg['LARK_LIVE_READ_ROSTER_TTL_SECONDS']='120'
    clock[0]='2026-09-27T10:01:59+08:00'
    assert service.run_due(h.wid) is None
    clock[0]='2026-09-27T10:02:00+08:00'
    assert service.run_due(h.wid)['sync_revision']==2
    h.cfg['LARK_LIVE_READ_ENABLED']='true';clock[0]='2026-09-27T12:00:00+08:00'
    before=h.read()
    assert service.run_due(h.wid) is None and h.read()==before
