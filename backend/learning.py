"""Training decisions and shift deadlines. Approval never fabricates remote success."""
from copy import deepcopy
from datetime import date, time,datetime
from zoneinfo import ZoneInfo
from .workflow import require, find, uid, now, event, http_url
from .operations import active_user, capable, queue, digest
from .policy import upgrade
from .capability_write_policy import PAUSED_MESSAGE


def recognizes(user):
    # Unlike generic manager permissions, capability recognition is explicitly granted.
    return user.get('active', True) and 'approve_capability' in user.get('capabilities', [])


def trainer(user, plan=None):
    return capable(user, 'manage_training') or bool(plan and user['id'] == plan.get('trainer_id'))


def cutoff(ws, user_id, day, *, clock=None):
    from .attendance_identity import schedule_subject_verified
    if not schedule_subject_verified(ws,user_id,clock=clock):
        return {'status':'pending_schedule','time':None,'basis':'scheduled_shift','reason':'employee_identity_unverified'}
    matches=[s for s in ws.get('work_schedules',[]) if s['user_id']==user_id and s['day']==day and s.get('active',True)]
    if len(matches)!=1:
        return {'status':'pending_schedule' if not matches else 'schedule_conflict','time':None,'basis':'scheduled_shift'}
    s=matches[0]
    if s.get('basis')=='attendance_schedule':
        try:
            end=datetime.fromisoformat(s['normal_off_at'])
            if end.tzinfo is None or s.get('status')!='ready':raise ValueError('Unverified schedule')
            offset=(end.date()-date.fromisoformat(day)).days
            if offset not in (0,1) or offset!=s.get('off_day_offset'):raise ValueError('Inconsistent schedule day')
        except (KeyError,ValueError,TypeError):
            return {'status':'pending_schedule','time':None,'basis':'scheduled_shift'}
    else:
        # Manual overrides may retain older remote fields; derive only manual time.
        end=datetime.combine(date.fromisoformat(day),time.fromisoformat(s['end_time']),ZoneInfo('Asia/Taipei'))
        offset=0
    return {'status':'ready','time':s['end_time'],'at':end.isoformat(),'off_day_offset':offset,
            'basis':'scheduled_shift','schedule_id':s['id'],'version':s['version']}


def record_change(ws, plan, user, action):
    plan.setdefault('history',[]).append({'action':action,'actor_id':user['id'],'at':now(),'version':plan['version']})
    plan['updated_at']=now()
    plan['record_sync_status']='writeback_paused'


def apply_learning(ws,user,body,test=False):
    action=body['action']; data=body.get('payload') or {}
    if not action.startswith(('training_','capability_','learning_')): return False
    if action.startswith(('training_','capability_','learning_')):
        from .features import require_learning
        require_learning()
    upgrade(ws); active_user(ws,user['id'])
    if action=='training_save':
        require(trainer(user),'需要訓練管理權限',403)
        plan=find(ws['training_plans'],data['id'],'訓練') if data.get('id') else None
        require(not plan or plan['status']=='planned','已提交的訓練不可覆寫；請建立新的訓練紀錄',409)
        title=str(data.get('title','')).strip(); require(bool(title),'請填訓練名稱',422)
        trainee=active_user(ws,data.get('trainee_id')); instructor=active_user(ws,data.get('trainer_id') or user['id'])
        skills=list(dict.fromkeys(data.get('skill_ids') or [])); require(bool(skills),'請選能力地圖項目',422)
        for ident in skills:
            skill=find(ws['capability_catalog'],ident,'技能'); require(skill.get('active',True),'技能已停用',409)
        try: planned=date.fromisoformat(str(data.get('planned_date',''))).isoformat()
        except ValueError: require(False,'請填有效訓練日期',422)
        if not plan:
            plan=dict(id=uid(),version=0,status='planned',history=[],created_by=user['id'],created_at=now()); ws['training_plans'].append(plan)
        plan.update(title=title,trainee_id=trainee['id'],trainer_id=instructor['id'],skill_ids=skills,planned_date=planned,version=plan['version']+1)
        record_change(ws,plan,user,action)
    elif action=='training_return':
        plan=find(ws['training_plans'],data.get('id'),'訓練')
        require(trainer(user,plan) and user['id']!=plan['trainee_id'],'需要非本人訓練覆核者',403)
        require(plan['status']=='submitted','只能退回待覆核成果',409)
        reason=str(data.get('reason','')).strip(); require(reason,'請填退回原因',422)
        plan.setdefault('submissions',[]).append({'version':plan['version'],'summary':plan.get('summary'),'evidence_urls':deepcopy(plan.get('evidence_urls',[])),'submitted_by':plan.get('submitted_by'),'returned_by':user['id'],'reason':reason,'at':now()})
        plan.update(status='planned',return_reason=reason,version=plan['version']+1)
        record_change(ws,plan,user,action)
    elif action=='learning_retry':
        require(False,PAUSED_MESSAGE,403)
    elif action in ('training_submit','training_pass','capability_approve'):
        plan=find(ws['training_plans'],data.get('training_id') or data.get('id'),'訓練')
        if action=='training_submit':
            require(trainer(user,plan) or user['id']==plan['trainee_id'],'無此訓練提交權',403)
            require(plan['status']=='planned','此訓練已提交',409)
            urls=list(dict.fromkeys(data.get('evidence_urls') or [])); summary=str(data.get('summary','')).strip()
            require(bool(summary) and bool(urls),'請提供訓練成果與佐證連結',422)
            require(all(isinstance(url,str) and http_url(url) for url in urls),'佐證連結必須為 HTTP(S)',422)
            plan.update(status='submitted',summary=summary,evidence_urls=urls,submitted_by=user['id'])
        elif action=='training_pass':
            require(trainer(user,plan),'需要訓練覆核權限',403)
            require(user['id']!=plan['trainee_id'],'不可認定自己的訓練通過',403)
            require(plan['status']=='submitted','需先提交訓練成果',409)
            plan.update(status='recognition_pending',passed_by=user['id'],passed_at=now())
        else:
            require(recognizes(user),'需要明確授予能力認定權限',403)
            require(user['id']!=plan['trainee_id'],'不能自行認定能力',403)
            require(plan['status']=='recognition_pending','需先完成訓練覆核',409)
            award=dict(id=uid(),training_id=plan['id'],user_id=plan['trainee_id'],skill_ids=deepcopy(plan['skill_ids']),approved_by=user['id'],approved_at=now(),status='approved',remote_status='writeback_paused',training_version=plan['version'])
            ws['capability_awards'].append(award)
            plan.update(status='approved',award_id=award['id'],remote_status='writeback_paused')
        plan['version']+=1; record_change(ws,plan,user,action)
    elif action=='learning_standard_set':
        require(recognizes(user),'標準須由你或指定認定者核定',403)
        kind=str(data.get('kind','')); require(kind in ('survival','capability_target','assessment'),'標準類型錯誤',422)
        title=str(data.get('title','')).strip(); value=str(data.get('value','')).strip()
        require(title and value,'請填標準名稱與定義，不能以空白或預設分數代替',422)
        try: effective=date.fromisoformat(str(data.get('effective_from',''))).isoformat()
        except ValueError: require(False,'請提供生效日期',422)
        ws['learning_standards'].append(dict(id=uid(),kind=kind,title=title,value=value,effective_from=effective,approved_by=user['id'],approved_at=now(),status='approved',calculation_status='definition_only'))
    else: require(False,'未知訓練／班表操作',422)
    event(ws,user,action,body.get('project_id'),message='保存訓練、能力、報價或班表決策')
    return True
