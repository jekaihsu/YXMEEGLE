from copy import deepcopy
import pytest
from .attendance_schedule import AttendanceScheduleReader,normal_end


def person():return {'id':'ou_a','attendance_identity':{'source':'oauth_user_info','verified_at':'2026-09-28T12:00:00+08:00',
    'open_id':'ou_a','employee_type':'employee_id','employee_id':'employee-verified','app_id':'app','tenant':'tenant'}}

class Fake:
    def __init__(self):self.calls=[]
    def request(self,method,path,**kwargs):
        self.calls.append((method,path,kwargs))
        if method=='POST':return {'user_daily_shifts':[{'user_id':'employee-verified','month':202609,'day_no':28,'shift_id':'s1'}]}
        return {'shift_id':'s1','is_flexible':False,'punch_time_rule':[{'on_time':'09:00','off_time':'18:00'}]}


def test_schedule_uses_verified_employee_mapping_and_fixed_rule_not_actual_punch():
    fake=Fake();calls=[];reader=AttendanceScheduleReader(fake,'app','tenant',lambda:calls.append(True))
    result=reader.fetch([person()],'2026-09-28','2026-09-29')
    assert result['rows'][0]['normal_off_time']=='18:00' and result['rows'][0]['normal_off_at'].endswith('18:00:00+08:00')
    assert result['rows'][1]['status']=='pending_schedule'
    assert fake.calls[0][2]['json']['user_ids']==['employee-verified']
    assert len(calls)==len(fake.calls)==2
    assert fake.calls[0][1]=='/attendance/v1/user_daily_shifts/query'  # read-only POST


@pytest.mark.parametrize('bad',['missing','app','tenant','open_id'])
def test_unknown_identity_never_guesses_or_queries_everyone(bad):
    p=person()
    if bad=='missing':p.pop('attendance_identity')
    else:p['attendance_identity'][{'app':'app_id','tenant':'tenant','open_id':'open_id'}[bad]]='other'
    fake=Fake();result=AttendanceScheduleReader(fake,'app','tenant',lambda:None).fetch([p],'2026-09-28','2026-09-28')
    assert result['status']=='pending_schedule' and not fake.calls


def test_cross_midnight_is_explicit_and_flexible_or_ambiguous_rules_stay_pending():
    shift={'is_flexible':False,'punch_time_rule':[{'on_time':'18:00','off_time':'26:00'}]}
    row=normal_end('2026-09-28',shift)
    assert row['off_day_offset']==1 and row['normal_off_at'].startswith('2026-09-29T02:00')
    shift['punch_time_rule'][0]['off_time']='02:00'
    assert normal_end('2026-09-28',shift)['status']=='pending_schedule'
    shift['is_flexible']=True
    assert normal_end('2026-09-28',shift)['status']=='pending_schedule'


def test_schedule_batches_58_people_and_authorizes_each_request():
    people=[]
    for i in range(58):
        p=person();p['id']=f'ou_{i}';p['attendance_identity'].update(open_id=p['id'],employee_id=f'employee-{i}');people.append(p)
    class Batches:
        def __init__(self):self.batches=[]
        def request(self,method,path,**kwargs):
            batch=kwargs['json']['user_ids'];self.batches.append(batch)
            return {'user_daily_shifts':[]}
    adapter=Batches();authorized=[]
    result=AttendanceScheduleReader(adapter,'app','tenant',lambda:authorized.append(True)).fetch(people,'2026-09-28','2026-10-04')
    assert list(map(len,adapter.batches))==[50,8] and len(authorized)==2
    assert len(set(sum(adapter.batches,[])))==58
    assert len(result['rows'])==406 and all(r['status']=='pending_schedule' and 'normal_off_time' not in r for r in result['rows'])


def test_schedule_rejects_other_batch_identity_even_when_in_overall_request():
    from fastapi import HTTPException
    people=[]
    for i in range(51):
        p=person();p['id']=f'ou_{i}';p['attendance_identity'].update(open_id=p['id'],employee_id=f'employee-{i}');people.append(p)
    class WrongBatch:
        def request(self,*args,**kwargs):return {'user_daily_shifts':[{'user_id':'employee-50'}]}
    with pytest.raises(HTTPException):AttendanceScheduleReader(WrongBatch(),'app','tenant',lambda:None).fetch(people,'2026-09-28','2026-09-28')
