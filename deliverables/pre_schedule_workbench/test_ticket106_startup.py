import json
import subprocess
from pathlib import Path
import pytest
import app


def test_active_roster_and_rov_policy():
    employees = app.load_catalog()['employees']
    assert not {'朱登輝','劉允中','張昭宜','鄭光瑞'} & {e['full_name'] for e in employees}
    rov = next(e for e in employees if e['full_name'] == '張爲斌')
    assert rov['sub_group'] == 'ROV組'
    assert rov['job_title_display'] == 'ROV組組長'
    requirements = app.api_report_requirements()
    assert all('張爲斌' not in requirements[k] for k in ('daily','weekly'))

@pytest.mark.parametrize('name',['吳科翰','張家彬','許茂坤','許傑凱','羅薇'])
def test_manager_scope(name):
    actor = app.resolve_actor(name)
    roster = app.get_allowed_team_roster(actor)
    assert len(roster) > 1
    for target in roster:
        app.authz_schedule_for(actor,target['full_name'])
    if name == '吳科翰':
        assert any(e['full_name']=='張爲斌' for e in roster)
        assert len({e['sub_group'] for e in roster}) > 1


def test_dynamic_dates_and_prompt():
    html = Path(app.__file__).with_name('index.html').read_text()
    start = html.index('    function taipeiToday(')
    end = html.index('    function minutesToHHMM', start)
    js = html[start:end] + '''
const assert = require('assert');
assert.equal(taipeiToday(new Date('2026-10-27T16:01:00Z')), '2026-10-28');
assert.equal(taipeiToday(new Date('2026-10-27T15:59:00Z')), '2026-10-27');
assert.equal(offsetDate('2026-12-31',1),'2027-01-01');
assert.equal(offsetDate('2026-11-01',-1),'2026-10-31');
assert.equal(formatDateWithDay('2026-10-28'),'2026-10-28 (週三)');
'''
    subprocess.run(['node','-e',js],check=True)
    assert 'onclick="setDate(offsetDate(taipeiToday(), 0))"' in html
    assert 'activeDate: taipeiToday()' in html
    assert '"btnConvertDaily").hidden = Boolean(activeInfo.daily_report_exempt)' in html


def test_clone_active_ids_and_report_policy():
    import os
    env = dict(os.environ, PGHOST='127.0.0.1', PGPORT='5432', PGUSER='postgres', PGPASSWORD='postgres', PGDATABASE='yongxiang_plumb_r39_clone', PGOPTIONS='-c default_transaction_read_only=on')
    sql = """select json_build_object(
      'db',current_database(),
      'ids',(select json_agg(id::text order by id) from employee where employment_status='active'),
      'rov',(select json_build_object('group',e.group_name,'daily',p.daily_required,'weekly',p.weekly_required) from employee e join employee_report_policy p on e.id=p.employee_id where e.full_name='張爲斌'),
      'daily_rov',(select count(*) from daily_report_required_employee_v where full_name='張爲斌'),
      'weekly_rov',(select count(*) from weekly_report_required_employee_v where full_name='張爲斌'))"""
    data = json.loads(subprocess.check_output(['psql','-X','-At','-v','ON_ERROR_STOP=1','-c',sql],env=env,text=True))
    assert data['db']=='yongxiang_plumb_r39_clone'
    assert set(data['ids'])=={e['employee_id'] for e in app.load_catalog()['employees']}
    assert data['rov']=={'group':'ROV組','daily':False,'weekly':False}
    assert data['daily_rov']==data['weekly_rov']==0
