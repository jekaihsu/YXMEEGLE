"""Shared assignment, scheduled activation and explicit personal delivery rules."""
from copy import deepcopy
import hashlib
import json
from datetime import date
from .source_lifecycle import declared, needs_review
from .workflow import all_tasks, blocked, event, find, now, require

RULE_VERSION = 'workflow-2026-09-28.1'
SYSTEM = {'id': 'system:scheduler', 'role': 'system'}


def assignable(ws,person):
    if not person or not person.get('active',True): return False
    if ws.get('environment')!='production': return True
    from .production_access import admitted
    return admitted(person,ws.get('people_directory_status',{}).get('app_id'))


def audit_change(ws, actor, action, p, n=None, t=None, before=None, after=None, reason='', trigger='manual'):
    item=event(ws,actor or SYSTEM,action,p['id'],n['id'] if n else None,t['id'] if t else None,reason or action)
    item.update(before=deepcopy(before),after=deepcopy(after),rule_version=RULE_VERSION,trigger=trigger)
    if t: item['principal_id']=t.get('owner_id')
    return item


def assign_task(ws,p,n,t,owner,actor=None,inherited=False,reason=''):
    if owner:
        person=find(ws['users'],owner,'負責人')
        require(assignable(ws,person),'不能指派已停用、離職或尚未核實名冊身分的人員',409)
    before={k:t.get(k) for k in ('owner_id','owner_inherited')}
    after={'owner_id':owner or '', 'owner_inherited':inherited}
    if before==after: return
    t.update(after)
    t.setdefault('assignment_history',[]).append(dict(before=before,after=deepcopy(after),actor_id=(actor or SYSTEM)['id'],at=now(),reason=reason,rule_version=RULE_VERSION))
    audit_change(ws,actor,'task_assignment',p,n,t,before,after,reason,'inheritance' if inherited else 'manual')


def inherit_new_task(ws,p,n,t,actor=None):
    """Source additions never replace an existing task's explicit override."""
    if t.get('owner_id') or t.get('owner_inherited') is False: return
    owner=n.get('owner_id','')
    if owner and not any(u['id']==owner and assignable(ws,u) for u in ws['users']): return
    assign_task(ws,p,n,t,owner,actor,True,'新任務沿用節點負責人')


def assign_node(ws,p,n,owner,actor,reason=''):
    if owner: require(assignable(ws,find(ws['users'],owner,'負責人')),'不能指派已停用、離職或尚未核實名冊身分的人員',409)
    old=n.get('owner_id','')
    for t in n['tasks']:
        inherited=t.get('owner_inherited',t.get('owner_id')==old and not t.get('manual_updated'))
        if inherited and t['status'] not in ('completed','superseded'):
            assign_task(ws,p,n,t,owner,actor,True,reason or '節點負責人改派，保留個別指定')
    n['owner_id']=owner or ''
    if old!=n['owner_id']: audit_change(ws,actor,'node_assignment',p,n,before={'owner_id':old},after={'owner_id':n['owner_id']},reason=reason)


def execution_reasons(ws,p,n,t):
    from .sop_contracts import execution_reasons as sop_execution_reasons
    reasons=sop_execution_reasons(p,n,t)
    if p.get('archived_at') or p.get('migrated_to') or p.get('source_missing') or needs_review(p) or declared(p)=='中止' or p.get('execution_status')=='completed': reasons.append('案件已暫停、結案或來源待核對')
    if n.get('archived_at') or n.get('status') in ('approved_skipped','archived','superseded'): reasons.append('節點已跳過或封存')
    if t.get('status') in ('paused','superseded','completed') or blocked(ws,p,t): reasons.append('任務已完成、暫停或封存')
    if t.get('source_missing') or t.get('source_change_pending') or t.get('source_reassignment_pending'): reasons.append('來源工項異動待核對')
    owner=next((u for u in ws['users'] if u['id']==t.get('owner_id') and assignable(ws,u)),None)
    if not owner: reasons.append('尚未指派有效負責人')
    contact=(t.get('sop_rule_id') in ('dispatch_date_contact','dispatch_detail_contact') or
             t.get('sop_task_key')=='dispatch_prerequisites' and
             t.get('sop_contract_version')=='sop-contracts-20260930.1')
    if n['key']=='field' and not contact and t.get('status') not in ('completed','superseded'):
        permit=next((e for e in reversed(p.get('evidence',[])) if e.get('node_id')==n['id'] and e.get('key')=='permits' and not e.get('withdrawn')),None)
        if not permit or permit['status'] not in ('accepted','not_applicable'): reasons.append('行政公務證明尚未齊備')
    for ident in t.get('input_task_ids',[]):
        dep=next((x for _,x in all_tasks(p) if x['id']==ident),None)
        if not dep or dep['status']!='completed' or not str(dep.get('output') or '').strip(): reasons.append('指定前置成果尚未交付；核准跳過不能替代實際交付資料'); break
    return reasons


def activation_reasons(ws,p,n,t,clock=None):
    clock=clock or now(); reasons=execution_reasons(ws,p,n,t)
    if t['status']!='pending': reasons.append('任務不在待啟用狀態')
    if n['status']=='completed': reasons.append('節點已完成')
    if p.get('case_type')=='intake': reasons.append('接案尚未轉正式案件')
    if declared(p)=='已結案': reasons.append('來源標示結案；工作台待核對，不自動重新啟用工作')
    if needs_review(p): reasons.append('來源案件狀態待核對；未確認前不自動啟用工作')
    scheduled=t.get('start_date')
    try:
        if not scheduled: reasons.append('尚未排定開始日期')
        elif date.fromisoformat(scheduled)>date.fromisoformat(clock[:10]): reasons.append('尚未到排程日期')
    except (ValueError,TypeError): reasons.append('排程日期無效')
    return list(dict.fromkeys(reasons))


def activate_scheduled(ws,clock=None):
    clock=clock or now(); activated=[]
    from .case_cutover import execution_allowed
    for p in ws['projects']:
        if not execution_allowed(ws,p) or needs_review(p) or declared(p) in ('已完工','已結案','中止'):continue
        for n,t in all_tasks(p):
            if t['status']!='pending' or activation_reasons(ws,p,n,t,clock): continue
            before={'status':t['status'],'started_at':t.get('started_at')}
            t.update(status='in_progress',activated_at=clock,activation_source='schedule')
            n.update(status='in_progress'); n.setdefault('activated_at',clock)
            audit_change(ws,SYSTEM,'task_activate',p,n,t,before,{'status':t['status'],'activated_at':clock,'started_at':t.get('started_at')},'排程日已到且前置條件齊備；未記錄實際作業開始','schedule')
            activated.append(t['id'])
        if any(t['id'] in activated for _,t in all_tasks(p)):
            from .operations import refresh_project_state
            refresh_project_state(p,ws)
    return activated


def confirmation_hash(p,n,t):
    scope={'project_id':p['id'],'node_id':n['id'],'task':{k:t.get(k) for k in ('id','revision','owner_id','status','output','input_task_ids','source_snapshot','source_change_pending','source_reassignment_pending')},
           'inputs':[{k:x.get(k) for k in ('id','revision','status','output')} for _,x in all_tasks(p) if x['id'] in t.get('input_task_ids',[])],
           'requirements':n.get('requirements',[]),'sop_version':p.get('sop_version')}
    return hashlib.sha256(json.dumps(scope,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def batch_complete(ws,user,body):
    items=(body.get('payload') or {}).get('items')
    require(isinstance(items,list) and 0<len(items)<=50,'請選擇 1 至 50 項本人工作',422)
    resolved=[]; seen=set()
    # Validate the entire batch before touching a single task, also outside DB callers.
    for item in items:
        require(isinstance(item,dict),'確認項目格式錯誤',422)
        p=find(ws['projects'],item.get('project_id'),'案件'); n=find(p['nodes'],item.get('node_id'),'節點'); t=find(n['tasks'],item.get('task_id'),'任務')
        identity=(p['id'],n['id'],t['id']); require(identity not in seen,'同一任務不可重複確認',422); seen.add(identity)
        require(user.get('active',True) and t.get('owner_id')==user['id'],'只能一次確認本人負責的項目',403)
        require(item.get('revision')==t.get('revision') and item.get('confirmation_hash')==confirmation_hash(p,n,t),'任務內容或指派已變更，請核對最新版本',409)
        reasons=execution_reasons(ws,p,n,t); require(not reasons,'、'.join(reasons),409)
        require(t['status'] in ('in_progress','rework'),'任務尚未啟用，請先開始作業',409)
        output=item.get('output'); require(isinstance(output,str) and output.strip(),'每項工作都需成果說明',422)
        resolved.append((p,n,t,output.strip(),item['confirmation_hash']))
    for p,n,t,output,fingerprint in resolved:
        before={k:t.get(k) for k in ('status','output','completed_at')}
        t.update(status='completed',completed_at=now(),output=output)
        t.setdefault('confirmations',[]).append(dict(actor_id=user['id'],principal_id=t['owner_id'],at=t['completed_at'],revision=t['revision'],confirmation_hash=fingerprint,request_id=body.get('request_id'),output=output))
        audit_change(ws,user,'task_complete',p,n,t,before,{k:t.get(k) for k in before},'本人一次確認並交付成果','batch_confirmation')
    from .operations import refresh_project_state
    for p in {p['id']:p for p,_,_,_,_ in resolved}.values(): refresh_project_state(p,ws)
