"""Server-side workflow invariants, independent of transport and storage."""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from urllib.parse import urlsplit
from copy import deepcopy
from fastapi import HTTPException
from .seed import seed, STAGES

def now(): return datetime.now(timezone(timedelta(hours=8))).isoformat()
def uid(): return uuid4().hex
def fail(message, code=400): raise HTTPException(code, message)
def require(ok, message='權限不足', code=403):
    if not ok: fail(message, code)
def find(items, ident, label='資料'):
    found=next((x for x in items if x['id']==ident),None)
    if not found: fail(f'{label}不存在',404)
    return found
def valid_date(value):
    try:
        parsed=date.fromisoformat(value)
        if parsed.isoformat()!=value: raise ValueError()
    except (ValueError, TypeError): fail('日期需為 YYYY-MM-DD')
    return value
def http_url(value):
    from .input_validation import safe_reference_url
    return safe_reference_url(value)
def is_pm(user,project):
    from .business_policy import can_business_override
    return bool(user.get('active',True) and (user['id']==project.get('pm_id') or can_business_override(user)))
def is_owner(user,task,ws,project=None):
    from .operations import delegation_valid
    today=now()[:10]
    if project is None:
        project=next((p for p in ws['projects'] if any(t['id']==task['id'] for _,t in all_tasks(p))),None)
    principal=next((u for u in ws['users'] if u['id']==task['owner_id']),None)
    if not user.get('active',True) or not principal or not principal.get('active',True): return False
    delegated=any(d['principal_id']==task['owner_id'] and d['delegate_id']==user['id'] and d['project_id']==project['id'] and d['seat']=='owner' and d.get('scope')=='tasks' and task['id'] in d.get('task_ids',[]) and d['start_date']<=today<=d['end_date'] and d['status']=='active' and delegation_valid(ws,d,at_use=True) for d in ws.get('delegations',[])) if project else False
    from .business_policy import can_business_override
    return task['owner_id']==user['id'] or delegated or can_business_override(user)
def edit_node(user,p,n): return is_pm(user,p) or n['owner_id']==user['id']
def all_tasks(p): return [(n,t) for n in p['nodes'] for t in n['tasks']]
def event(ws,user,action,pid=None,nid=None,tid=None,message=None):
    item=dict(id=uid(),project_id=pid,node_id=nid,task_id=tid,actor_id=user['id'],action=action,message=message or action,created_at=now())
    ws['events'].insert(0,item)
    return item
def impacted(p,approval):
    selected=[(n,t) for n,t in all_tasks(p) if t['id'] in approval['task_ids']]
    order={key:i for i,(key,_,_) in enumerate(STAGES)}
    ids={t['id'] for n,t in selected}
    for n,t in selected:
        if t.get('work_item_id'):
            ids.update(x['id'] for m,x in all_tasks(p) if x.get('work_item_id')==t['work_item_id'] and order[m['key']]>=order[n['key']] and x['status']!='superseded')
    return [(n,t) for n,t in all_tasks(p) if t['id'] in ids]
def blocked(ws,p,t):
    return any(a['project_id']==p['id'] and a['type']=='change' and a.get('frozen') and any(x['id']==t['id'] for _,x in impacted(p,a)) for a in ws['approvals'])

def freeze_change(ws,p,approval,actor):
    """Called at the durable native submit attempt, never while preparing a draft."""
    if approval.get('type')!='change' or approval.get('frozen'): return
    targets=impacted(p,approval)
    require(targets and not any(blocked(ws,p,t) for _,t in targets),'範圍與既有變更重疊或已不存在',409)
    approval['previous_statuses']={t['id']:t['status'] for _,t in targets}
    from .workflow_rules import audit_change
    for node,task in targets:
        before={'status':task['status']}; task['status']='paused'
        audit_change(ws,actor,'task_pause_for_change',p,node,task,before,{'status':'paused'},approval['reason'],'native_approval')
    approval['frozen']=True
def refresh_node(n):
    active=[t for t in n['tasks'] if t['status']!='superseded']
    if active:
        starts=[t['start_date'] for t in active if t.get('start_date')]; dues=[t['due_date'] for t in active if t.get('due_date')]
        if starts: n['start_date']=min(starts)
        if dues: n['due_date']=max(dues)

def apply_action(ws,user,body,demo=True):
    from .input_validation import validate_action
    validate_action(body)
    action=body['action']; payload=body.get('payload') or {}; pid=body.get('project_id'); nid=body.get('node_id'); tid=body.get('task_id')
    if action=='task_batch_complete':
        from .workflow_rules import batch_complete
        return batch_complete(ws,user,body)
    if action=='demo_reset':
        require(demo and user['role']=='manager'); version=ws['version']; ws.clear(); ws.update(seed()); ws['version']=version
        event(ws,user,action,message='重設示範工作區'); return
    if action=='calendar_update':
        require(user['role']=='manager' or 'calendar_edit' in user.get('capabilities',[]))
        ws['calendar']={k:sorted(set(valid_date(x) for x in payload.get(k,[]))) for k in ('holidays','workdays')}
        from .sop_deadlines import recalculate_calendar
        recalculate_calendar(ws,user)
        event(ws,user,action,message='更新工作日曆'); return
    approval=None
    if action.startswith('approval_') and action!='approval_create' or action=='change_resume':
        approval=find(ws['approvals'],payload.get('approval_id'),'申請'); pid=approval['project_id']; nid=approval.get('node_id')
    p=find(ws['projects'],pid,'案件'); n=find(p['nodes'],nid,'節點') if nid else None
    from .case_cutover import require_execution
    require_execution(ws,p)
    t=find(n['tasks'],tid,'任務') if tid and n else None
    if tid and not t:
        pair=next(((a,b) for a,b in all_tasks(p) if b['id']==tid),None)
        if not pair: fail('任務不存在',404)
        n,t=pair; nid=n['id']
    if action in ('task_start','task_complete','task_return'):
        require(t is not None,'請指定任務',400); require(is_owner(user,t,ws),'只有任務負責人或有效代理人可操作')
        require(not blocked(ws,p,t),'設計變更範圍已暫停，請先完成變更或明確恢復',409)
        require(t['status'] not in ('superseded','paused'),'任務不可操作',409)
        if action in ('task_start','task_complete'):
            from .workflow_rules import execution_reasons
            reasons=execution_reasons(ws,p,n,t); require(not reasons,'、'.join(reasons),409)
        if action=='task_start':
            require(t['status'] in ('pending','rework') or t['status']=='in_progress' and t.get('activation_source')=='schedule' and not t.get('started_at'),'任務已開始或完成',409)
            t.update(status='in_progress',started_at=now()); t.setdefault('activated_at',t['started_at']); t.setdefault('activation_source','manual')
            n['status']='in_progress'; n['started_at']=n['started_at'] or now()
        elif action=='task_complete':
            require(t['status'] in ('in_progress','rework'),'請先開始任務',409)
            output=str(payload.get('output',t.get('output',''))).strip(); require(bool(output),'請填寫成果說明',400)
            t.update(status='completed',completed_at=now(),output=output)
        else:
            require(bool(str(payload.get('reason','')).strip()),'退回需填寫原因',400)
            t.update(status='rework',completed_at=None); n.update(status='in_progress',completed_at=None)
            t['comments'].append(dict(id=uid(),author_id=user['id'],body=payload['reason'],created_at=now()))
    elif action in ('task_add','task_update'):
        require(n is not None,'請指定節點',400); require(edit_node(user,p,n))
        assigned=payload.get('owner_id') if 'owner_id' in payload else (n.get('owner_id') or None) if action=='task_add' else None
        if assigned is not None or 'owner_id' in payload:
            person=find(ws['users'],assigned,'負責人')
            require(person.get('active',True),'不能指派已停用或離職的人員',409)
        if action=='task_update':
            require(t is not None,'請指定任務',400); require(t['status']!='superseded' and not blocked(ws,p,t),'任務已封存或因變更暫停',409)
            if t.get('due_date') and 'due_date' in payload and payload['due_date']!=t['due_date']: fail('已排定期限須透過展延申請修改',409)
            if t.get('start_date') and 'start_date' in payload and payload['start_date']!=t['start_date']: fail('已排定起日不可直接改寫；請保留原始排期',409)
        else:
            require(bool(str(payload.get('title','')).strip()),'請填任務名稱',400)
            t=dict(id=uid(),title=payload['title'],owner_id=n['owner_id'],status='pending',required=bool(payload.get('required',True)),start_date=None,due_date=None,original_due_date=None,started_at=None,completed_at=None,points=None,work_item_id=payload.get('work_item_id') or None,description='',input='',output='',comments=[],revision=p['revision'])
            n['tasks'].append(t); n.update(status='in_progress' if n['status']=='completed' else n['status'],completed_at=None); tid=t['id']
        for field in ('owner_id','title','start_date','due_date','points','description'):
            if field not in payload: continue
            value=payload[field]
            if field=='owner_id':
                from .workflow_rules import assign_task
                assign_task(ws,p,n,t,value,user,False,payload.get('reason','個別指定任務負責人'))
            if field=='title': require(bool(str(value).strip()),'任務名稱不可空白',400)
            if field in ('start_date','due_date') and value: valid_date(value)
            if field=='points' and value is not None: require(isinstance(value,(int,float)) and not isinstance(value,bool) and value>=0,'點數需為非負數',400)
            t[field]=value
        require(not(t.get('start_date') and t.get('due_date')) or t['start_date']<=t['due_date'],'截止日不能早於開始日',400)
        if not t['original_due_date']: t['original_due_date']=t['due_date']
        if action=='task_add' and 'owner_id' not in payload:
            from .workflow_rules import assign_task
            assign_task(ws,p,n,t,n.get('owner_id',''),user,True,'新增任務沿用節點負責人')
        refresh_node(n)
    elif action=='node_complete':
        from .operations import submit_review
        require(n is not None,'請指定節點',400); submit_review(ws,user,p,n)
    elif action=='participants_update':
        require(is_pm(user,p))
        # Validate every assignment before changing any inherited ownership.
        for item in payload.get('nodes',[]):
            find(p['nodes'],item.get('node_id'),'節點')
            for ident in [item.get('owner_id')]+item.get('collaborator_ids',[]):
                person=find(ws['users'],ident,'參與人員')
                from .workflow_rules import assignable
                require(assignable(ws,person),'不能指派已停用、離職或尚未核實名冊身分的人員',409)
        for item in payload.get('nodes',[]):
            node=find(p['nodes'],item.get('node_id'),'節點'); find(ws['users'],item.get('owner_id'),'負責人')
            for cid in item.get('collaborator_ids',[]): find(ws['users'],cid,'協作人')
            from .workflow_rules import assign_node, audit_change
            assign_node(ws,p,node,item['owner_id'],user,payload.get('reason','統一設定參與人員'))
            prior=list(node.get('collaborator_ids',[])); node['collaborator_ids']=list(dict.fromkeys(item.get('collaborator_ids',[])))
            if prior!=node['collaborator_ids']: audit_change(ws,user,'node_collaborators',p,node,before={'collaborator_ids':prior},after={'collaborator_ids':node['collaborator_ids']})
    elif action=='comment_add':
        text=str(payload.get('body','')).strip(); require(bool(text),'留言不可空白',400)
        mentions=payload.get('mentions',[])
        require(isinstance(mentions,list) and len(mentions)<=50 and all(isinstance(x,str) for x in mentions),'標註需為有效的人員 ID 清單（最多 50 人）',422)
        mentions=list(dict.fromkeys(mentions))
        for ident in mentions:
            person=find(ws['users'],ident,'標註同事')
            require(person.get('active',True),'不能標註已停用或離職的人員',409)
            directory_app=ws.get('people_directory_status',{}).get('app_id')
            require(not directory_app or not person.get('identity_app_id') or person['identity_app_id']==directory_app,
                    '標註人員身分屬於另一應用，需先核對',409)
        from .mention_notifications import reserve_mentions
        reserve_mentions(ws,user,mentions)
        comment=dict(id=uid(),author_id=user['id'],body=text,mentions=mentions,created_at=now(),node_id=nid)
        (t if t else p)['comments'].append(comment)
        from .mention_notifications import enqueue_mentions
        enqueue_mentions(ws,user,p,n,t,comment,demo)
    elif action=='file_link':
        require(is_pm(user,p) or (n and (n['owner_id']==user['id'] or any(is_owner(user,x,ws) for x in n['tasks']))))
        require(payload.get('direction') in ('input','output'),'文件用途需為 input/output',400)
        from .file_categories import validate_category
        category=payload.get('category_id') or 'other'; validate_category(ws,category); ident=uid()
        key=payload.get('file_key')
        related=[f for f in p['files'] if f.get('file_key',f['id'])==key] if key else []
        if key:
            require(bool(related),'原文件不存在，不能新增版本',404)
            require(all(f.get('node_id')==(nid or None) and f.get('category_id','other')==category and f['direction']==payload['direction'] for f in related),'新版本須維持原文件節點、分類及用途',409)
        try: version=1+max((int(f.get('version',1)) for f in related),default=0)
        except (TypeError,ValueError): require(False,'原文件版本格式需先核對',409)
        p['files'].append(dict(id=ident,file_key=key or ident,category_id=category,name=str(payload.get('name') or '參考文件'),node_id=nid or None,direction=payload['direction'],version=str(version),uploaded_by=user['id'],created_at=now(),size=0,url=http_url(payload.get('url')),storage='link'))
    elif action=='approval_create':
        kind=payload.get('type'); require(kind in ('change','extension'),'申請類型錯誤',400)
        require(is_pm(user,p) or any(x['owner_id']==user['id'] for x in p['nodes']))
        task_ids=list(dict.fromkeys(payload.get('task_ids',[]))); dates=payload.get('dates',[])
        if kind=='extension': task_ids=list(dict.fromkeys(task_ids+[x.get('task_id') for x in dates]))
        require(bool(task_ids),'請指定影響任務',400)
        for ident in task_ids:
            target=next((x for _,x in all_tasks(p) if x['id']==ident),None); require(target is not None and target['status']!='superseded','影響任務不存在或已封存',400)
        require(bool(str(payload.get('reason','')).strip()),'請填寫申請原因',400)
        require(kind!='extension' or bool(dates),'展延需提供新期限',400)
        for d in dates:
            require(d.get('task_id') in task_ids,'日期對應任務不在申請範圍',400); valid_date(d.get('due_date'))
            target=next(x for _,x in all_tasks(p) if x['id']==d['task_id'])
            require(not target.get('start_date') or d['due_date']>=target['start_date'],'期限不能早於開始日',400)
        ref=payload.get('reference_url',''); http_url(ref) if ref else None
        approval=dict(id=uid(),project_id=p['id'],type=kind,title=payload.get('title') or ('設計變更' if kind=='change' else '期限展延'),status='draft',reason=payload['reason'],node_id=payload.get('node_id') or nid,task_ids=task_ids,dates=deepcopy(dates),owner_confirmed=False,client_confirmed=False,lark_status='draft',created_by=user['id'],created_at=now(),executed_at=None,reference_url=ref,attachments=payload.get('attachments',[]),history=[],project_revision=p['revision'],frozen=False)
        ws['approvals'].insert(0,approval)
    elif approval:
        require(is_pm(user,p) or approval['created_by']==user['id'] or user['id']==next((x['owner_id'] for x in p['nodes'] if x['id']==approval['node_id']),None))
        if action=='approval_submit':
            require(demo,'尚未設定原生 Lark 審批送審介面；已保留草稿，可查詢既有審批，尚未送審或暫停工作',503)
            require(approval['status']=='draft','只有草稿可以送審',409)
            if approval['type']=='change':
                freeze_change(ws,p,approval,user)
            approval.update(status='pending',lark_status='pending')
        elif action=='approval_confirm':
            require(demo,'正式工作區不支援模擬核准',403); require(user['role']=='manager','模擬雙方確認需主管身份')
            require(approval['status']=='pending','申請不是待審狀態',409); party=payload.get('party'); require(party in ('owner','client'),'確認方錯誤',400)
            approval[party+'_confirmed']=True
            if approval['lark_status']=='approved' and approval['owner_confirmed'] and approval['client_confirmed']: approval['status']='approved'
        elif action=='approval_lark':
            require(demo,'尚未啟用 Lark 原生審批寫入',403); require(user['role']=='manager')
            require(approval['status']=='pending','申請不是待審狀態',409); result=payload.get('result'); require(result in ('approved','rejected'),'審批結果錯誤',400)
            approval['lark_status']=result
            if result=='rejected': approval['status']='rejected'
            elif approval['type']=='extension' or (approval['owner_confirmed'] and approval['client_confirmed']): approval['status']='approved'
        elif action=='approval_execute':
            require(is_pm(user,p)); require(approval['status']=='approved','申請尚未核准或已執行',409)
            require(approval['project_revision']==p['revision'],'案件版本已變更，請重新建立申請',409)
            if not demo:
                from .native_requests import receipt_valid
                require(receipt_valid(ws,p,n,approval,require_fresh=True),'原生審批回執未核實、已過期或範圍已變更，請先重新查回',409)
            new_dates={x['task_id']:x['due_date'] for x in approval['dates']}
            if approval['type']=='change':
                if demo: require(approval['owner_confirmed'] and approval['client_confirmed'] and approval['lark_status']=='approved','三方確認尚未齊備',409)
                else:
                    from .native_requests import change_lines_valid
                    require(change_lines_valid(ws,p,n,approval),'主管確認、業主佐證與原生審批三線尚未齊備或已改版',409)
                replacement_ids={}; replacements=[]
                for node,old in impacted(p,approval):
                    replacement=deepcopy(old); replacement.update(id=uid(),status='pending',started_at=None,completed_at=None,output='',revision=p['revision']+1,replaces_task_id=old['id'])
                    for key in ('activated_at','activation_source','confirmations'): replacement.pop(key,None)
                    replacement_ids[old['id']]=replacement['id']; replacements.append(replacement)
                    if old['id'] in new_dates: replacement['due_date']=new_dates[old['id']]
                    old['status']='superseded'; node['tasks'].append(replacement); node.update(status='in_progress',completed_at=None); refresh_node(node)
                for replacement in replacements:
                    if 'input_task_ids' in replacement: replacement['input_task_ids']=[replacement_ids.get(dep,dep) for dep in replacement['input_task_ids']]
                approval['frozen']=False
            else:
                for node,task in all_tasks(p):
                    if task['id'] in new_dates:
                        require(task['status']!='superseded','任務已改版，請重新申請',409); task['due_date']=new_dates[task['id']]; refresh_node(node)
                dues=[x['due_date'] for _,x in all_tasks(p) if x['status']!='superseded' and x.get('due_date')]
                if dues: p['due_date']=max(([p['due_date']] if p.get('due_date') else [])+dues)
            p['revision']+=1; approval.update(status='executed',executed_at=now())
        elif action=='approval_withdraw':
            require(not approval.get('native_binding',{}).get('attempted'),
                    '已送出 Lark 的申請須由原申請人使用撤回審批入口，查回取消後才完成撤回',409)
            require(approval['status'] in ('draft','pending','approved'),'此申請不可撤回',409); approval['status']='withdrawn'
        elif action=='change_resume':
            require(approval['type']=='change' and approval['status'] in ('rejected','withdrawn','invalidated') and approval.get('frozen'),'此變更無待恢復工作',409)
            from .native_approval import remote_binding_resolved
            require(remote_binding_resolved(approval),'原生審批結果尚未核實；不可解除變更暫停',409)
            require(bool(str(payload.get('reason','')).strip()),'恢復需填寫原因',400)
            for _,task in impacted(p,approval): task['status']=approval.get('previous_statuses',{}).get(task['id'],'pending')
            approval['frozen']=False
        else: fail('未知操作')
        approval['history'].append(dict(action=action,actor_id=user['id'],created_at=now(),message=payload.get('reason') or action))
    else: fail('未知操作')
    from .operations import refresh_project_state
    refresh_project_state(p,ws)
    event(ws,user,action,p['id'],nid,tid,payload.get('reason') or payload.get('title') or action)
    if action in ('task_start','task_complete','task_return') and t and user['id']!=t['owner_id']:
        ws['events'][0]['principal_id']=t['owner_id']
