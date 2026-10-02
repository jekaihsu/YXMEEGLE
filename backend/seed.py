"""Deterministic, fictional data. Never mixed with connected customer records."""
from copy import deepcopy

STAGES = [('sales','報價','u-pm'),('pm','PM 派工','u-pm'),('confirmation','確認單','u-pm'),('field','外業','u-field'),('control','控制','u-control'),('mapping','圖資','u-map'),('report','報告','u-report'),('pricing','計價請款','u-pm'),('settlement','入帳結算','u-pm')]
USERS = [dict(id=i,name=n,role=r,department=d,avatar=n[:1]) for i,n,r,d in [('u-pm','林育寬','pm','專案管理'),('u-field','陳柏翰','member','外業組'),('u-control','李家彬','member','控制組'),('u-map','王怡婷','member','圖資組'),('u-report','黃雅雯','member','報告組'),('u-manager','張智偉','manager','管理部'),('u-agent','周子安','member','控制組')]]
TITLES = {'sales':['核對報價範圍與版本','確認業主需求與回簽'], 'pm':['指派各組負責人','確認跨組排期'], 'confirmation':['確認合約工項與數量','傳遞工程確認單'], 'field':['控制點佈設與觀測','原地形及高程測量','整理觀測原始資料'], 'control':['控制點平差計算','檢查坐標與精度','提交控制成果'], 'mapping':['地形圖建置與接圖','圖面品管與修正','提交圖資成果'], 'report':['測量報告編製','成果目錄與附件校核'], 'pricing':['核對實作數量與計價單','確認請款文件'], 'settlement':['核對入帳紀錄','檢視 Base 結算結果']}

def seed(empty=False):
    ws = dict(version=1,as_of='2026-09-25',users=deepcopy(USERS) if not empty else [],projects=[],approvals=[],events=[],calendar=dict(holidays=['2026-09-28'],workdays=[]),source_status=dict(status='unconfigured',last_sync=None,message='尚未設定 Lark 來源；示範案件與正式資料隔離'))
    if empty:
        ws['calendar']={'holidays':[],'workdays':[]}
        return ws
    ws['environment']='demo'
    cases=[('C115236','桃園捷運綠線控制點測量','桃園軌道工程處', 'control', 'high',109590),('C115238-01','新竹濱海地形測量','北區水利工程處','mapping','high',447840),('C115241','臺中河道斷面測量','中部河川管理局','field','medium',680000),('C115247','臺北都市更新現況測量','都市更新工程公司','report','medium',325000),('C115251','臺南工區放樣與查核','南方建設公司','confirmation','low',185000),('C115253','高雄港區水深測量','港灣工程公司','pricing','high',920000),('C115258','宜蘭邊坡監測工程','東部工程顧問公司','pm','medium',None)]
    keys=[x[0] for x in STAGES]
    for idx,(code,name,client,current,priority,amount) in enumerate(cases,1):
        pid=f'p{idx}'; active=keys.index(current)
        p=dict(id=pid,code=code,name=name,client=client,pm_id='u-pm',status='in_progress',priority=priority,due_date='2026-10-16',original_due_date='2026-10-16',created_at='2026-09-01T09:00:00+08:00',started_at='2026-09-01T09:00:00+08:00',description='示範案件。報價與工項自來源帶入，於此管理排程、交接與成果。',contract_amount=amount,estimated_points=round((amount or 0)/30000,2) if amount else None,source_url='',source_kind='demo',revision=1,nodes=[],files=[],comments=[],daily_reports=[])
        for ni,(key,label,owner) in enumerate(STAGES):
            status='completed' if ni<active else 'in_progress' if ni==active else 'pending'
            due='2026-09-24' if idx==1 and key=='control' else f'2026-10-{min(2+ni,28):02d}'
            node=dict(id=f'{pid}-{key}',name=label,key=key,owner_id=owner,collaborator_ids=['u-agent'] if key=='control' else [],status=status,start_date='2026-09-21',due_date=due,original_due_date=due,started_at='2026-09-21T09:00:00+08:00' if ni<=active else None,completed_at='2026-09-23T17:00:00+08:00' if ni<active else None,tasks=[])
            for ti,title in enumerate(TITLES[key],1):
                task=dict(id=f'{pid}-{key}-t{ti}',title=title,owner_id=owner,status=status if ti==1 or ni<active else 'pending',required=True,start_date='2026-09-21',due_date=due,original_due_date=due,started_at=node['started_at'] if ti==1 or ni<active else None,completed_at=node['completed_at'],points=round(1.25*ti,2) if key in ['field','control','mapping','report'] else None,work_item_id=f'{pid}-survey' if ti!=2 else f'{pid}-terrain',description='依工程確認單帶入工項，完成後填寫成果說明。',input='已核准確認單與前階段成果',output='成果已校核並交接' if ni<active else '',comments=[],revision=1)
                task['owner_inherited']=True
                if idx==1 and key=='control' and ti==1: task['proxy']={'user_id':'u-agent','start_date':'2026-09-25','end_date':'2026-09-30'}
                dependency={'control':'field-t3','mapping':'control-t3','report':'mapping-t3','pricing':'report-t2'}.get(key)
                if dependency and ti==1: task['input_task_ids']=[f'{pid}-{dependency}']
                node['tasks'].append(task)
            p['nodes'].append(node)
        p['daily_reports']=[dict(id=f'{pid}-dr1',date='2026-09-24',department='外業組',case_code=code,person='陳柏翰',description='現場觀測及控制點複測',points=2.5,source_url='')]
        if idx!=1: p['daily_reports'].append(dict(id=f'{pid}-dr2',date='2026-09-25',department='控制組',case_code=code,person='李家彬',description='開始辦理本案控制資料檢核',points=1.25,source_url=''))
        ws['projects'].append(p)
    ws['events']=[dict(id='seed-event',project_id='p1',actor_id='u-pm',action='seed',message='建立示範工作區；金額與人名均為展示資料',created_at='2026-09-25T08:30:00+08:00')]
    return ws
