from copy import deepcopy
from datetime import datetime
import pytest

from .learning import cutoff
from .jobs import schedule
from .test_workflow_automation import setup


@pytest.mark.parametrize('change', [
    {'active':False}, {'directory_status':'left'}, {'directory_missing':True},
    {'identity_app_id':None}, {'identity_app_id':'other'}, {'directory_source':{}},
    {'directory_last_seen_at':'2026-09-29T17:00:00+08:00'},
])
def test_formal_stored_shift_cannot_escalate_after_identity_loss(setup,change):
    ws,p,n,user=setup
    ws['environment']='production';ws['people_directory_status']={'app_id':'app1'}
    p['execution_system']='workbench';ws['settings']['digest_time']='00:00'
    user.update(active=True,identity_app_id='app1',directory_status='employed',
        directory_source={'app_id':'app1','record_id':'verified'},
        directory_last_seen_at='2026-09-29T18:01:00+08:00')
    ws['work_schedules']=[{'id':'retained-shift','user_id':user['id'],'day':'2026-09-29',
        'active':True,'basis':'attendance_schedule','status':'ready',
        'normal_off_at':'2026-09-29T18:00:00+08:00','off_day_offset':0,'end_time':'18:00','version':1}]
    routine={'id':'retained-task','project_id':p['id'],'kind':'correction','title':'成果補正',
        'owner_id':user['id'],'supervisor_id':'u-manager','status':'active','due_date':'2026-09-29','history':[]}
    ws['recurring']=[routine]
    clock=datetime.fromisoformat('2026-09-29T18:01:00+08:00')
    assert cutoff(ws,user['id'],'2026-09-29',clock=clock)['status']=='ready'
    before=deepcopy(ws['work_schedules'])
    user.update(change)
    assert cutoff(ws,user['id'],'2026-09-29',clock=clock)['status']=='pending_schedule'
    schedule(ws,clock.isoformat())
    assert routine['overdue'] is False
    assert routine['deadline_status']=='pending_schedule'
    assert not any('成果補正檢查' in j['payload'].get('text','') for j in ws['jobs'])
    assert ws['work_schedules']==before


@pytest.mark.parametrize('environment',['demo','test'])
def test_simulated_manual_deadline_needs_no_lark_roster(environment):
    ws={'environment':environment,'work_schedules':[{'id':'manual','user_id':'local',
        'day':'2026-09-29','end_time':'18:00','active':True,'version':1}]}
    assert cutoff(ws,'local','2026-09-29')['status']=='ready'
