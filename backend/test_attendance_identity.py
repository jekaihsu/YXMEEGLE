from datetime import datetime,timezone,timedelta
import pytest
from fastapi import HTTPException
from .attendance_identity import AttendanceIdentityResolver,valid_identity
from .production_access import access_mode,require_access,readonly_sync_actor


def people(count):return [{'id':'ou_'+str(i),'identity_app_id':'app'} for i in range(count)]


class Adapter:
    def __init__(self):self.calls=[];self.transform=lambda items:items
    def request(self,method,path,**kwargs):
        assert method=='GET' and path=='/contact/v3/users/batch'
        self.calls.append(kwargs)
        return {'items':self.transform([{'open_id':oid,'user_id':'employee'+oid[3:],'name':'do not store','email':'do not store'} for oid in reversed(kwargs['params']['user_ids'])])}


def test_two_batches_exact_ids_unordered_and_minimum_projection():
    adapter=Adapter();checks=[];source=people(51)
    result=AttendanceIdentityResolver(adapter,'app','tenant',lambda:checks.append(True)).fetch(source)
    assert len(adapter.calls)==2 and len(checks)==4
    assert len(result['mappings'])==51 and not result['issues']
    assert result['mappings']['ou_0']['employee_id']=='employee0'
    assert set(result['mappings']['ou_0'])=={'open_id','employee_id','employee_type','app_id','tenant','verified_at','source'}
    assert valid_identity({**source[0],'attendance_identity':result['mappings']['ou_0']},'app','tenant')
    assert not valid_identity({**source[0],'attendance_identity':result['mappings']['ou_0']},'other','tenant')


@pytest.mark.parametrize('kind',['unknown','duplicate_open','duplicate_employee'])
def test_malformed_identifiers_reject_whole_projection(kind):
    adapter=Adapter()
    def transform(items):
        if kind=='unknown':items[0]['open_id']='ou_unknown'
        elif kind=='duplicate_open':items.append(items[0])
        else:items[0]['user_id']=items[1]['user_id']
        return items
    adapter.transform=transform
    with pytest.raises(HTTPException):AttendanceIdentityResolver(adapter,'app','tenant',lambda:None).fetch(people(2))


def test_partial_missing_user_id_reports_issue_without_guessing():
    adapter=Adapter();adapter.transform=lambda items:[{'open_id':'ou_0','name':'same name'}]
    result=AttendanceIdentityResolver(adapter,'app','tenant',lambda:None).fetch(people(2))
    assert not result['mappings']
    assert {i['reason'] for i in result['issues']}=={'employee_id_unavailable','contact_identity_not_returned'}


def test_authorization_revoked_after_response_prevents_result():
    count=[]
    def check():
        count.append(True)
        if len(count)>1:raise HTTPException(403,'revoked')
    with pytest.raises(HTTPException):AttendanceIdentityResolver(Adapter(),'app','tenant',check).fetch(people(1))


def member(clock):return {'id':'ou_1','active':True,'identity_app_id':'app','directory_status':'employed',
    'directory_source':{'app_id':'app','record_id':'record'},'directory_last_seen_at':clock.isoformat()}


def test_fifteen_minute_boundary_recovery_admin_never_grants_business():
    clock=datetime.now(timezone.utc);person=member(clock-timedelta(seconds=900))
    assert access_mode(person,'app',now=clock)=='normal'
    person['directory_last_seen_at']=(clock-timedelta(seconds=901)).isoformat()
    assert access_mode(person,'app',now=clock)=='denied'
    person.update(role='manager',bootstrap_admin=True)
    assert access_mode(person,'app',now=clock)=='recovery'
    with pytest.raises(HTTPException):require_access(person,'app',now=clock)
    assert require_access(person,'app',allow_recovery=True,now=clock)=='recovery'
    assert access_mode({**person,'active':False},'app',now=clock)=='denied'


@pytest.mark.parametrize('stamp',['','2026-09-29T00:00:00','invalid',None])
def test_invalid_directory_timestamp_cannot_admit(stamp):
    person=member(datetime.now(timezone.utc));person['directory_last_seen_at']=stamp
    assert access_mode(person,'app')=='denied'


def test_company_readonly_authority_independent_of_manual_actor():
    cfg={'LARK_APP_ID':'app','LARK_WORKER_ORGANIZATION':'tenant','LARK_ALLOWED_TENANTS':'tenant','LARK_WORKER_IDENTITY':'application'}
    state={'environment':'production','people_directory_connection':{'enabled':True,'actor_id':'departed'}}
    assert readonly_sync_actor(state,cfg,'people_directory_connection')['role']=='system'
    state['environment']='test'
    with pytest.raises(HTTPException):readonly_sync_actor(state,cfg,'people_directory_connection')
