"""Deterministic fictional company-scale data for first-load regression checks.

Ported from /tmp/yx_perf/measure.py; shapes come from backend.seed. Smaller
workspaces retain 65 users so manager, PM and member identities remain stable.
"""
from .seed import seed, STAGES, TITLES

BASE_COUNTS = dict(projects=319, tasks=7230, events=7915, work_schedules=1441,
                   contract_items=573, recurring=550, daily_unmatched=535,
                   source_quotes=322, source_confirmations=212, users=65)
ASSUMED_COUNTS = dict(daily_reports=9000, approvals=300, files=1500, comments=900)

def build_scaled_workspace(n_projects=319):
    """Return fresh fictional state with linearly scaled related collections.

    Default counts reproduce the planner's 319-project workload (7,018 tasks:
    the original generator adds at most one extra task per project). Daily
    reports, files, comments and approvals are assumed volumes, not prod facts.
    No random IDs, clocks, database access or external services are used.
    """
    if isinstance(n_projects, bool) or not isinstance(n_projects, int) or n_projects < 1:
        raise ValueError('n_projects must be a positive integer')
    counts = {key: max(1, round(value * n_projects / 319))
              for key, value in BASE_COUNTS.items()}
    assumed = {key: max(1, round(value * n_projects / 319))
               for key, value in ASSUMED_COUNTS.items()}
    counts['projects'] = n_projects
    ws=seed(True); ws['environment']='demo'; ws['as_of']='2026-10-07'
    for k in ('work_schedules','recurring','daily_unmatched','contract_items','source_quotes','source_confirmations','approvals','events'): ws.setdefault(k,[])
    depts=['專案管理','外業組','控制組','圖資組','報告組','管理部']
    users=[]
    for i in range(BASE_COUNTS['users']):
        role='manager' if i<3 else 'pm' if i<15 else 'member'
        users.append(dict(id=f'ou_{i:03d}',name=f'員工{i:03d}',role=role,department=depts[i%len(depts)],avatar='員',active=True,capabilities=[]))
    users[0]['id']='u-manager'; users[3]['id']='u-pm'
    ws['users']=users
    pms=[u['id'] for u in users if u['role']=='pm']; members=[u['id'] for u in users if u['role']=='member']
    extra_tasks=counts['tasks']-counts['projects']*sum(len(v) for v in TITLES.values())
    for idx in range(counts['projects']):
        pid=f'p{idx+1:03d}'; active=idx%9; pm=pms[idx%len(pms)]
        p=dict(id=pid,code=f'C11{5000+idx}',name=f'第{idx+1}號測量案件 現況地形與控制點',client=f'客戶單位{idx%40}',pm_id=pm,supervisor_id='u-manager',admin_id=pm,status='in_progress' if idx%5 else 'completed',priority=['high','medium','low'][idx%3],due_date=f'2026-{10+idx%3:02d}-{1+idx%28:02d}',original_due_date='2026-10-16',created_at='2026-09-01T09:00:00+08:00',started_at='2026-09-01T09:00:00+08:00',description='依工程確認單帶入工項與排程。',contract_amount=100000+idx*1000,estimated_points=12.5,source_url=f'https://example.invalid/base/{idx}',source_kind='lark',source_status='執行中',revision=1,case_type='formal',case_visibility='new_case',execution_system='workbench',nodes=[],files=[],comments=[],daily_reports=[])
        for ni,(key,label,_) in enumerate(STAGES):
            owner=members[(idx+ni)%len(members)]
            status='completed' if ni<active else 'in_progress' if ni==active else 'pending'
            due=f'2026-10-{min(2+ni,28):02d}'
            node=dict(id=f'{pid}-{key}',name=label,key=key,owner_id=owner,collaborator_ids=[],status=status,start_date='2026-09-21',due_date=due,original_due_date=due,started_at='2026-09-21T09:00:00+08:00' if ni<=active else None,completed_at='2026-09-23T17:00:00+08:00' if ni<active else None,tasks=[],review_cycles=[])
            titles=list(TITLES[key])
            if extra_tasks>0 and ni==3: titles.append('補充工項'); extra_tasks-=1
            for ti,title in enumerate(titles,1):
                node['tasks'].append(dict(id=f'{pid}-{key}-t{ti}',title=title,owner_id=owner,status=status if ti==1 or ni<active else 'pending',required=True,start_date='2026-09-21',due_date=due,original_due_date=due,started_at=node['started_at'] if ti==1 or ni<active else None,completed_at=node['completed_at'],points=1.25*ti if key in ('field','control','mapping','report') else None,work_item_id=f'{pid}-survey',description='依工程確認單帶入工項，完成後填寫成果說明。',input='已核准確認單與前階段成果',output='成果已校核並交接' if ni<active else '',comments=[],revision=1,owner_inherited=True))
            p['nodes'].append(node)
        ws['projects'].append(p)
    projects=ws['projects']
    for i in range(assumed['daily_reports']):
        p=projects[i%len(projects)]
        p['daily_reports'].append(dict(id=f'dr{i}',date=f'2026-{1+i%9:02d}-{1+i%28:02d}',department=depts[i%6],case_code=p['code'],person=f'員工{i%65:03d}',description='現場觀測及控制點複測',points=2.5,source_url=f'https://example.invalid/daily/{i}',source_record_id=f'rec{i}'))
    for i in range(assumed['files']):
        p=projects[i%len(projects)]
        p['files'].append(dict(id=f'f{i}',file_key=f'k{i}',category_id='other',name=f'成果檔案{i}.pdf',node_id=p['nodes'][i%9]['id'],direction='output',version='1',uploaded_by=p['pm_id'],created_at='2026-09-20T09:00:00+08:00',size=12345,sha256='0'*64,url=f'/api/files/f{i}/download',storage='local'))
    for i in range(assumed['comments']):
        p=projects[i%len(projects)]
        p['comments'].append(dict(id=f'c{i}',author_id=p['pm_id'],body='請確認本週排程與成果檢核。',created_at='2026-09-20T09:00:00+08:00',mentions=[]))
    for i in range(assumed['approvals']):
        p=projects[i%len(projects)]
        ws['approvals'].append(dict(id=f'a{i}',project_id=p['id'],type='change',status=['pending','approved','rejected'][i%3],title='控制點變更',reason='業主設計調整',task_ids=[p['nodes'][4]['tasks'][0]['id']],dates=[],created_by=p['pm_id'],created_at='2026-09-20T09:00:00+08:00',history=[]))
    for i in range(counts['events']):
        p=projects[i%len(projects)]
        ws['events'].append(dict(id=f'e{i}',project_id=p['id'],actor_id=p['pm_id'],action=['task_complete','task_start','source_sync','comment'][i%4],message=f'完成工項 {p["code"]} 控制點平差計算並交接成果',created_at=f'2026-{1+i%9:02d}-{1+i%28:02d}T09:{i%60:02d}:00+08:00'))
    for i in range(counts['work_schedules']):
        u=users[i%len(users)]
        ws['work_schedules'].append(dict(id=f'ws{i}',user_id=u['id'],day=f'2026-10-{1+(i//65)%28:02d}',end_time='17:30',version=1,active=True,basis='attendance_schedule',status='ready',normal_off_time='17:30',history=[],updated_at='2026-10-01T00:00:00+08:00',source_verified_at='2026-10-01T00:00:00+08:00'))
    for i in range(counts['recurring']):
        p=projects[i%len(projects)]
        ws['recurring'].append(dict(id=f'r{i}',project_id=p['id'],kind='payment',title='收付款追蹤',owner_id=p['pm_id'],supervisor_id='u-manager',status='active',start_date='2026-09-01',due_date='2026-10-15',history=[],batch_id=None))
    for i in range(counts['daily_unmatched']):
        ws['daily_unmatched'].append(dict(id=f'du{i}',date='2026-10-01',department=depts[i%6],case_code=f'X{i}',person=f'員工{i%65:03d}',description='現場觀測',points=1.0,source_url=f'https://example.invalid/daily/u{i}',reason='案件編號無法配對'))
    def src(i,kind):
        return dict(id=f'{kind}{i}',entity_id=f'base/tbl/{kind}{i}',kind=kind,project_id=projects[i%len(projects)]['id'],project_ids=[projects[i%len(projects)]['id']],source_identity={'base_token':'base','table_id':'tbl','record_id':f'{kind}{i}'},source_url=f'https://example.invalid/{kind}/{i}',status='active',fields={'工程編號':projects[i%len(projects)]['code'],'工程名稱':'現況測量','契約價格(未稅)':100000,'備註':'依報價總表'},updated_at='2026-10-01T00:00:00+08:00')
    ws['contract_items']=[dict(src(i,'contract'),title='控制點測量',quantity=10,unit='點',unit_price=1500) for i in range(counts['contract_items'])]
    ws['source_quotes']=[dict(src(i,'quote'),confirmation_ids=[]) for i in range(counts['source_quotes'])]
    ws['source_confirmations']=[dict(src(i,'confirmation'),quote_ids=[]) for i in range(counts['source_confirmations'])]
    return ws
