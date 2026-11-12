from copy import deepcopy
from datetime import date,datetime,timezone
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from .test_source_sync import harness
from .test_attendance_schedule import person,Fake
from .attendance_service import AttendanceScheduleService,merge_schedules
from .learning import cutoff
from . import storage


def make(h):
    p=person();p['id']='u-manager';p['attendance_identity'].update(open_id='u-manager',app_id='app1')
    with h.sessions.begin() as db:
        profile=db.get(h.P,(h.wid,'u-manager'));profile.data={**profile.data,'attendance_identity':p['attendance_identity'],
            'directory_last_seen_at':datetime.now(timezone.utc).isoformat(),
            'directory_status':'employed','directory_source':{'app_id':'app1','record_id':'manager-roster'}}
    fake=Fake();fake.client=SimpleNamespace(close=lambda:None)
    return AttendanceScheduleService(h.sessions,h.W,h.B,h.P,h.cfg,adapter_factory=lambda cfg:fake),fake


def test_service_persists_verified_schedule_and_failure_retains_history(harness):
    h=harness;service,fake=make(h)
    status=service.sync(h.wid,'u-manager','2026-09-28','2026-09-28')
    state,_=h.read();rows=deepcopy(state['work_schedules'])
    assert status['ready_count']==1 and rows[0]['end_time']=='18:00'
    assert cutoff(state,'u-manager','2026-09-28')['at']=='2026-09-28T18:00:00+08:00'
    fake.request=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('network'))
    with pytest.raises(HTTPException):service.sync(h.wid,'u-manager','2026-09-28','2026-09-28')
    state,_=h.read()
    assert state['work_schedules']==rows and state['attendance_schedule_status']['last_success_at']==status['last_success_at']
    assert state['attendance_schedule_status']['status']=='error'


def test_missing_employee_id_is_pending_without_remote_request(harness):
    h=harness;calls=[]
    service=AttendanceScheduleService(h.sessions,h.W,h.B,h.P,h.cfg,adapter_factory=lambda cfg:SimpleNamespace(client=SimpleNamespace(close=lambda:None),request=lambda *a,**k:calls.append(a)))
    status=service.sync(h.wid,'u-manager','2026-09-28','2026-09-28')
    assert not calls and status['status']=='pending_schedule'
    row=h.read()[0]['work_schedules'][0]
    assert row['active'] is False and row['end_time'] is None


def test_manual_override_survives_refresh_and_ignores_old_remote_midnight_fields():
    ws={'work_schedules':[{'id':'manual','user_id':'u','day':'2026-09-28','end_time':'17:00','active':True,'version':2,
        'basis':'company_schedule','normal_off_at':'2026-09-29T02:00:00+08:00','off_day_offset':1}]}
    before=deepcopy(ws)
    result={'rows':[],'fetched_at':'2026-09-28T12:00:00+08:00'}
    assert merge_schedules(ws,result,[{'id':'u'}],date(2026,9,28),date(2026,9,28))==(0,1)
    assert ws==before and cutoff(ws,'u','2026-09-28')['at']=='2026-09-28T17:00:00+08:00'


def test_cross_midnight_and_disappeared_shift_preserve_revision_history():
    ws={'work_schedules':[]};people=[{'id':'u'}];day=date(2026,9,28)
    result={'fetched_at':'2026-09-28T12:00:00+08:00','rows':[{'user_id':'u','day':day.isoformat(),'status':'ready',
      'normal_off_time':'02:00','normal_off_at':'2026-09-29T02:00:00+08:00','off_day_offset':1}]}
    merge_schedules(ws,result,people,day,day)
    assert cutoff(ws,'u',day.isoformat())['off_day_offset']==1
    merge_schedules(ws,result,people,day,day)
    assert ws['work_schedules'][0]['version']==1 and not ws['work_schedules'][0]['history']
    result['rows']=[];merge_schedules(ws,result,people,day,day)
    row=ws['work_schedules'][0]
    assert not row['active'] and row['version']==2 and row['history'][0]['normal_off_time']=='02:00'
    assert cutoff(ws,'u',day.isoformat())['status']=='pending_schedule'


def test_configuration_change_before_http_and_revoked_actor_fail_closed(harness):
    h=harness;service,fake=make(h)
    original=service.adapter_factory
    def swapped(cfg):
        result=original(cfg);h.cfg['LARK_APP_ID']='rotated';return result
    service.adapter_factory=swapped
    with pytest.raises(HTTPException):service.sync(h.wid,'u-manager','2026-09-28','2026-09-28')
    assert not fake.calls and not h.read()[0]['work_schedules']


def test_scheduler_requires_enabled_connection_and_throttles(harness):
    h=harness;service,fake=make(h)
    assert service.run_due(h.wid) is None
    service.sync(h.wid,'u-manager','2026-09-28','2026-09-28')
    count=len(fake.calls)
    assert service.run_due(h.wid) is None and len(fake.calls)==count


def test_actor_disabled_between_query_and_shift_read_stops_commit(harness):
    h=harness;service,fake=make(h);original=fake.request
    def revoke(method,path,**kwargs):
        result=original(method,path,**kwargs)
        if method=='POST':
            with h.sessions.begin() as db:
                p=db.get(h.P,(h.wid,'u-manager'));p.data={**p.data,'active':False}
        return result
    fake.request=revoke
    with pytest.raises(HTTPException):service.sync(h.wid,'u-manager','2026-09-28','2026-09-28')
    assert len(fake.calls)==1 and not h.read()[0]['work_schedules']


@pytest.mark.parametrize('legacy',['missing','null'])
def test_legacy_formal_environment_inferred_and_persisted_only_with_sync(harness,legacy):
    h=harness;service,fake=make(h)
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);data=deepcopy(row.data)
        if legacy=='missing':data.pop('environment',None)
        else:data['environment']=None
        row.data=data
    with h.sessions() as db:
        row=db.get(h.W,h.wid)
        assert service._state(db,row)['environment']=='production'
        assert row.data.get('environment') is None
    result=service.sync(h.wid,'u-manager','2026-09-28','2026-09-28')
    assert result['ready_count']==1 and h.read()[0]['environment']=='production'


@pytest.mark.parametrize('environment',['demo','test'])
def test_explicit_isolated_environment_never_promoted(harness,environment):
    h=harness;service,fake=make(h)
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);row.data={**row.data,'environment':environment}
    with pytest.raises(HTTPException) as exc:service.sync(h.wid,'u-manager','2026-09-28','2026-09-28')
    assert exc.value.status_code==403 and not fake.calls
    assert h.read()[0]['environment']==environment


def test_legacy_inference_rejects_other_company_namespace(harness):
    h=harness;service,fake=make(h)
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);row.data={**row.data,'environment':None}
    h.cfg['LARK_WORKER_ORGANIZATION']='different'
    with h.sessions() as db:
        assert service._state(db,db.get(h.W,h.wid)).get('environment') is None
    with pytest.raises(HTTPException):service.sync(h.wid,'u-manager','2026-09-28','2026-09-28')
    assert not fake.calls and h.read()[0].get('environment') is None


def test_contact_identity_resolution_persists_only_verified_mapping_and_reuses_cache(harness):
    h=harness
    with h.sessions.begin() as db:
        old=db.get(h.P,(h.wid,'u-manager'));person=deepcopy(old.data);db.delete(old)
        person['id']='ou_manager';person['identity_app_id']='app1'
        person.update(directory_status='employed',directory_source={'app_id':'app1','record_id':'manager-roster'})
        db.add(h.P(organization_id=h.wid,person_id=person['id'],data=person))
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        state['users']=[person];row.data=storage.save(db,h.B,h.wid,state)
    calls=[]
    def request(method,path,**kwargs):
        calls.append((method,path,kwargs))
        return {'items':[{'open_id':'ou_manager','user_id':'employee1','email':'not stored'}]}
    fake=SimpleNamespace(request=request,client=SimpleNamespace(close=lambda:None))
    service=AttendanceScheduleService(h.sessions,h.W,h.B,h.P,h.cfg,adapter_factory=lambda cfg:fake)
    result=service.resolve_identities(h.wid,'ou_manager')
    assert result['resolved']==1 and len(calls)==1
    with h.sessions() as db:
        m=db.get(h.P,(h.wid,'ou_manager')).data['attendance_identity']
        assert m['source']=='contact_user_batch' and m['employee_id']=='employee1' and 'email' not in m
    assert service.resolve_identities(h.wid,'ou_manager')['resolved']==0 and len(calls)==1


def test_background_schedule_refresh_does_not_require_original_manual_actor(harness):
    h=harness;service,fake=make(h)
    service.sync(h.wid,'u-manager','2026-09-28','2026-09-28')
    with h.sessions.begin() as db:
        profile=db.get(h.P,(h.wid,'u-manager'));profile.data={**profile.data,'active':False}
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        state['attendance_schedule_status']['last_attempt_at']='2020-01-01T00:00:00+00:00'
        row.data=storage.save(db,h.B,h.wid,state)
    # Company authorization persists; disabled employee is excluded, not used
    # as a permanent credential for refreshing everybody else's schedules.
    assert service.run_due(h.wid) is not None


def test_contact_sync_mixed_roster_keeps_unverified_admin_pending_and_queries_58(harness):
    h=harness;h.cfg['LARK_ATTENDANCE_IDENTITY_RESOLUTION']='contact'
    with h.sessions.begin() as db:
        admin=db.get(h.P,(h.wid,'u-manager'))
        # Independent admission does not give the administrator a roster identity,
        # even when an older attendance mapping exists.
        admin.data={**admin.data,'attendance_identity':{**person()['attendance_identity'],
            'open_id':'u-manager','app_id':'app1'}}
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        state['users']=[admin.data]
        for i in range(60):
            staff={'id':f'ou_staff{i}','name':'Synthetic staff','role':'member','active':True,
                'identity_app_id':'app1' if i<58 else None,'directory_status':'employed',
                'directory_source':{'app_id':'app1','record_id':f'roster{i}'}}
            state['users'].append(staff)
            db.add(h.P(organization_id=h.wid,person_id=staff['id'],data=staff))
        row.data=storage.save(db,h.B,h.wid,state)
    calls=[]
    def request(method,path,**kwargs):
        calls.append((method,path,kwargs))
        if path=='/contact/v3/users/batch':
            return {'items':[{'open_id':oid,'user_id':'employee'+oid.removeprefix('ou_staff')}
                for oid in kwargs['params']['user_ids']]}
        assert path=='/attendance/v1/user_daily_shifts/query'
        return {'user_daily_shifts':[]}
    fake=SimpleNamespace(request=request,client=SimpleNamespace(close=lambda:None))
    service=AttendanceScheduleService(h.sessions,h.W,h.B,h.P,h.cfg,adapter_factory=lambda cfg:fake)
    status=service.sync(h.wid,'u-manager','2026-09-28','2026-10-04')
    contact=[c[2]['params']['user_ids'] for c in calls if c[0]=='GET']
    shifts=[c[2]['json']['user_ids'] for c in calls if c[0]=='POST']
    assert [len(batch) for batch in contact]==[50,8]
    assert [len(batch) for batch in shifts]==[50,8]
    assert all('u-manager' not in batch and 'ou_staff58' not in batch and 'ou_staff59' not in batch for batch in contact)
    state,_=h.read()
    assert state['attendance_identity_status']['resolved']==58
    assert len(state['attendance_identity_status']['issues'])==3
    assert status['status']=='pending_schedule' and len(status['issues'])==3
    pending=[r for r in state['work_schedules'] if r['user_id'] in ('u-manager','ou_staff58','ou_staff59')]
    assert len(pending)==21 and all(not r['active'] and r['reason']=='employee_identity_unverified' for r in pending)
    # A subsequent run with cached verified IDs still preserves pending issues,
    # without sending the unverified cohort to Contact or failing the full sync.
    calls.clear()
    again=service.sync(h.wid,'u-manager','2026-09-28','2026-10-04')
    assert again['status']=='pending_schedule'
    assert all(c[0]=='POST' for c in calls)


def test_attendance_timer_live_gate_and_configured_interval(harness,monkeypatch):
    from . import attendance_service
    h=harness;service,fake=make(h);clock=['2026-09-27T10:00:00+08:00']
    monkeypatch.setattr(attendance_service,'now',lambda:clock[0])
    service.sync(h.wid,'u-manager','2026-09-28','2026-09-28')
    h.cfg['LARK_LIVE_READ_ATTENDANCE_TTL_SECONDS']='600'
    clock[0]='2026-09-27T10:09:59+08:00'
    assert service.run_due(h.wid) is None
    calls=[];service.sync=lambda *args:calls.append(args) or {'ready':True}
    clock[0]='2026-09-27T10:10:00+08:00'
    assert service.run_due(h.wid)=={'ready':True} and len(calls)==1
    h.cfg['LARK_LIVE_READ_ENABLED']='true';clock[0]='2026-09-27T12:00:00+08:00'
    before=h.read()
    assert service.run_due(h.wid) is None and len(calls)==1 and h.read()==before
