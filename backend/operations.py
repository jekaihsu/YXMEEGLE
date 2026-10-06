"""Versioned operational rules; mutations run inside the workspace transaction."""
import hashlib
import json
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from .source_lifecycle import declared, needs_review
from .policy import upgrade, CAPABILITIES, TECHNICAL, FINANCIAL
from .workflow import require, find, now, uid, event, blocked, all_tasks, valid_date, http_url
from .business_policy import can_business_override

def capable(user, capability):
    return user.get('active',True) and (user.get('role')=='manager' or capability in user.get('capabilities',[]))

def active_user(ws, ident):
    u=find(ws['users'],ident,'人員'); require(u.get('active',True),'人員已停權',403); return u

def lead(user,p):
    from .business_policy import can_business_override
    return user['id'] in (p.get('pm_id'),p.get('supervisor_id')) or can_business_override(user)

def operator(user,p,n=None):
    return lead(user,p) or user['id']==p.get('admin_id') or n is not None and (user['id'] in [n.get('owner_id'),n.get('supervisor_id')]+n.get('collaborator_ids',[]) or any(t['owner_id']==user['id'] for t in n['tasks']))

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def decimal(value):
    try: result=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError): require(False,'請輸入有效金額',422)
    require(result.is_finite() and result>=0,'金額需為有限非負數',422)
    return result

def is_workday(day,cal):
    return day.isoformat() in cal['workdays'] or day.weekday()<5 and day.isoformat() not in cal['holidays']

def add_workdays(start,count,cal):
    d=date.fromisoformat(start)
    require(isinstance(count,int) and not isinstance(count,bool),'工作日偏移需為整數',422)
    direction=1 if count>=0 else -1
    remaining=abs(count)
    while remaining:
        d+=timedelta(days=direction)
        if is_workday(d,cal): remaining-=1
    return d.isoformat()

def next_due(kind,start,ws):
    d=date.fromisoformat(start); cfg=ws['settings']; cal=ws['calendar']
    if kind in ('client_contact','correction','receivable','subcontract_receivable'): return add_workdays(start,cfg['followup_workdays'],cal)
    if kind=='daily_progress': return add_workdays(start,1,cal)
    if kind=='monthly':
        first=(d.replace(day=28)+timedelta(days=4)).replace(day=1)
        return add_workdays((first-timedelta(days=1)).isoformat(),cfg['monthly_workday'],cal)
    weekday=cfg[{'field_schedule':'field_weekday','indoor_schedule':'indoor_weekday','weekly_review':'review_weekday'}[kind]]
    d+=timedelta(days=(weekday-d.weekday())%7 or 7)
    while not is_workday(d,cal): d+=timedelta(days=1)
    return d.isoformat()

def queue(ws,kind,actor,payload,key):
    previous=next((j for j in ws['jobs'] if j['key']==key),None)
    if previous:
        require(previous['payload']==payload,'相同工作識別的內容不一致',409); return previous
    job=dict(id=uid(),kind=kind,actor_id=actor['id'],payload=deepcopy(payload),key=key,status='queued',attempts=0,created_at=now(),steps=[],error=None,next_attempt_at=now())
    ws['jobs'].append(job); return job

def evidence_for(p,n,key):
    return next((e for e in reversed(p['evidence']) if e['node_id']==n['id'] and e['key']==key and not e.get('withdrawn') and not e.get('superseded_for_current')),None)

def confirmation_current(p,n,issue):
    evidence=evidence_for(p,n,'confirmation')
    # Evidence IDs identify immutable submissions; replacements receive a new ID.
    if not issue or not evidence or evidence.get('status')!='accepted': return False
    recipients=issue.get('recipients'); version=issue.get('version')
    if not isinstance(recipients,list) or not version: return False
    return bool(issue.get('evidence_id')==evidence.get('id')
                and issue.get('pm_id')==p['pm_id']
                and issue.get('fingerprint')==digest({'version':version,
                    'evidence':evidence.get('id'),'pm':p['pm_id'],'recipients':recipients,
                    **({'groups':issue['recipient_groups']} if issue.get('recipient_groups') else {})}))


def daily_evidence_current(p,e):
    if not e.get('daily_id'): return True
    from .v4_sources import daily_source_version
    daily=next((d for d in p.get('daily_reports',[]) if d['id']==e['daily_id'] and not d.get('source_missing')),None)
    return bool(daily and e.get('daily_source_version') and e['daily_source_version']==daily_source_version(daily))


def reconcile_daily_evidence(ws):
    """Invalidate only explicit consumers of the changed daily, never its whole case."""
    for p in ws['projects']:
        for e in p.get('evidence',[]):
            if not e.get('daily_id') or e.get('withdrawn') or e.get('status')=='invalidated': continue
            if daily_evidence_current(p,e): continue
            e.update(status='invalidated',invalidated_at=now(),invalidated_reason='引用日報版本或案件關聯已變更，請重新引用核對')
            n=next((node for node in p['nodes'] if node['id']==e['node_id']),None)
            if n:
                invalidate(n,'引用日報版本或案件關聯已變更')
                event(ws,{'id':'system:source-sync','name':'來源同步'},'daily_evidence_invalidated',p['id'],n['id'],message=e['invalidated_reason'])

def delivery_fingerprint(item):
    return digest({k:item.get(k) for k in ('work_item_ids','quantity','unit','evidence_ids','task_snapshots','version')})

def delivery_reviewer_ids(p,item):
    selected=set(item.get('work_item_ids',[])); reviewers=[]
    for node in p['nodes']:
        if any(task['id'] in selected or task.get('work_item_id') in selected for task in node['tasks']):
            reviewers.append(node.get('supervisor_id') or p.get('supervisor_id',''))
    return list(dict.fromkeys(ident for ident in reviewers if ident))

def delivery_current(p,item):
    if item.get('status')!='approved' or item.get('superseded_by'): return False
    if item.get('content_hash')!=delivery_fingerprint(item): return False
    current_reviewers=set(delivery_reviewer_ids(p,item))
    valid_approvals={a.get('actor_id') for a in item.get('approvals',[]) if a.get('content_hash')==item.get('content_hash')}
    if not current_reviewers or current_reviewers!=set(item.get('required_reviewer_ids',[])) or valid_approvals!=current_reviewers: return False
    for ident in item.get('evidence_ids',[]):
        e=next((e for e in p['evidence'] if e['id']==ident),None)
        if not e or e.get('withdrawn') or e.get('status')!='accepted': return False
        if e.get('file_id') and not any(f['id']==e['file_id'] and not f.get('withdrawn') for f in p['files']): return False
    for snapshot in item.get('task_snapshots',[]):
        task=next((t for _,t in all_tasks(p) if t['id']==snapshot['id']),None)
        if not task or any(task.get(k)!=snapshot.get(k) for k in ('revision','status','output')): return False
    return True

def payment_delivery_valid(p,batch):
    if batch.get('phase')=='advance' and not batch.get('delivery_references'):
        return bool(str(batch.get('contract_evidence','')).strip() and str(batch.get('claim_evidence','')).strip())
    refs=batch.get('delivery_references',[])
    if not refs: return False
    for ref in refs:
        item=next((x for x in p.get('delivery_batches',[]) if x['id']==ref['id']),None)
        if not item or not delivery_current(p,item) or item['version']!=ref['version'] or item['content_hash']!=ref['content_hash']: return False
    return True

def delivery_references(p,identifiers,batch_id=None,kind=None):
    require(isinstance(identifiers,list) and identifiers and all(isinstance(x,str) and x for x in identifiers) and len(set(identifiers))==len(identifiers),'需指定不重複的已核定交付批次',422)
    refs=[]
    for ident in identifiers:
        item=find(p.get('delivery_batches',[]),ident,'交付批次')
        require(delivery_current(p,item),'交付批次尚未核定、已換版或證據已失效',409)
        for other in p['payment_batches']:
            if other['id']==batch_id or other.get('kind')!=kind or other.get('status')=='cancelled': continue
            used_ids={r['id'] for r in other.get('delivery_references',[])}
            require(not any(d['id'] in used_ids and d.get('lineage_id',d['id'])==item.get('lineage_id',item['id']) for d in p.get('delivery_batches',[])),'此交付批次已有同類款項，請修訂原款項避免重複請款',409)
        refs.append(dict(id=ident,version=item['version'],content_hash=item['content_hash']))
    return refs

def attestation_hash(item):
    return digest({k:item.get(k) for k in ('contract_amount','budget','currency','tax_basis','evidence','kind','phase','amount','date','contract_evidence','claim_evidence','acceptance_evidence','delivery_references','technical_approved_by')})

def refresh_payment_status(ws,p,batch):
    # Recording money and confirming money are separate events. Legacy receipts
    # without signed attestations remain pending until explicitly checked.
    verified=Decimal(0)
    for receipt in batch.get('receipts',[]):
        votes=valid_attestations(ws,p,receipt)
        receipt['verified']=set(votes)=={'pm','admin'} and len(set(votes.values()))==2
        receipt['status']='verified' if receipt['verified'] else 'pending'
        if receipt['verified']: verified+=decimal(receipt['amount'])
    batch['recorded_amount']=str(sum((decimal(r['amount']) for r in batch.get('receipts',[])),Decimal(0)))
    batch['verified_amount']=str(verified)
    if batch.get('status') in ('draft','needs_review','cancelled'): return
    if not payment_delivery_valid(p,batch):
        batch['status']='needs_review'; batch['review_reason']='交付批次未綁定或版本已失效'; return
    batch['status']='paid' if verified==decimal(batch['amount']) and verified>0 else 'partially_paid' if verified>0 else 'approved'

def refresh_project_state(p,ws):
    from .node_skip import refresh_skips, valid_waiver
    refresh_skips(ws,p)
    p.setdefault('delivery_batches',[])
    for item in p['delivery_batches']:
        if item['status']=='approved' and not delivery_current(p,item):
            item.update(status='invalidated',invalidated_reason='交付成果、文件或工項版本已變更')
    if ws.get('environment')=='production':
        for node in p['nodes']:
            if node['key'] in FINANCIAL and node['status']=='completed' and not financial_confirmation(ws,p,node,require_fresh=False):
                invalidate(node,'原生財務共同核准已失效或尚未核實')
    financial_changed=False
    for batch in p.get('payment_batches',[]):
        before=(batch.get('status'),batch.get('verified_amount'))
        refresh_payment_status(ws,p,batch)
        if before!=(batch.get('status'),batch.get('verified_amount')): financial_changed=True
    if financial_changed:
        p['payment_reconciliation']={'confirmed':False}
        for node in p['nodes']:
            if node['key'] in FINANCIAL: invalidate(node,'款項或交付核實狀態變更')
    technical=[n for n in p['nodes'] if n['key'] in TECHNICAL]
    engineering=bool(technical) and all(n['status']=='completed' or valid_waiver(ws,p,n) for n in technical)
    p['engineering_waivers']=[n['skip_request_id'] for n in technical if valid_waiver(ws,p,n)]
    settlement=next((n for n in p['nodes'] if n['key']=='settlement'),None)
    from .finance_readiness import financial_readiness
    financially_settled=financial_readiness(ws,p)['ready'] if ws.get('environment')=='production' else bool(p.get('payment_reconciliation',{}).get('confirmed'))
    if settlement and settlement['status']=='completed' and (not engineering or settlement_preconditions(p,ws) or not financially_settled or p.get('migration_review_required') or p.get('migration_conflicts') or p.get('migration_finance_reapproval_required')):
        invalidate(settlement,'工程交付或收付款尚未核實完成')
    if settlement and settlement['status']=='completed' and engineering:
        p['execution_status']='completed'
    elif engineering: p['execution_status']='engineering_complete'
    elif needs_review(p) or declared(p)=='中止': p['execution_status']='paused'
    elif p.get('execution_status') in ('in_progress','engineering_complete','completed') or any(n['status'] in ('in_progress','rework','completed') for n in p['nodes']): p['execution_status']='in_progress'
    else: p['execution_status']='pending'
    p['status']=p['execution_status']

def settlement_preconditions(p,ws):
    from .node_skip import valid_waiver
    return [key for key in ('sales','pm','confirmation','pricing') if not any(node['key']==key and (node['status']=='completed' or valid_waiver(ws,p,node)) for node in p['nodes'])]


def financial_confirmation(ws,p,n,require_fresh=True):
    from .native_requests import receipt_valid
    return next((item for item in ws.get('financial_requests',[]) if item.get('project_id')==p['id']
                 and item.get('node_id')==n['id'] and item.get('status')=='approved'
                 and receipt_valid(ws,p,n,item,require_fresh=require_fresh)),None)


def missing(p,n,ws):
    if n['status']=='approved_skipped': return ['此節點為核准跳過，不能當作完成或交付成果']
    from .sop_contracts import completion_reasons
    issues=completion_reasons(p,n)
    if any(c['node_id']==n['id'] and c['status']=='pending' for c in p.get('sop_deadline_conflicts',[])): issues.append('SOP 期限異動尚待主管核對')
    from .sop_execution import node_closure_reasons
    issues.extend(node_closure_reasons(ws,p,n))
    if n['key'] in FINANCIAL:
        if ws.get('environment')=='production' and not financial_confirmation(ws,p,n): issues.append('此節點尚未取得有效的 Lark 原生財務共同核准')
        if p.get('migration_review_required') or p.get('migration_conflicts'): issues.append('來源案件合併尚待主管核對')
        if p.get('migration_finance_reapproval_required'): issues.append('合併後財務基準尚未重新共同核定')
    for rule in n['requirements']:
        item=evidence_for(p,n,rule['key'])
        if not item or item['status'] not in ('accepted','not_applicable'): issues.append(rule['label'])
        elif item.get('daily_id') and not daily_evidence_current(p,item): issues.append('日報關聯或版本已變更，請重新引用核對')
        elif item.get('file_id'):
            document=next((f for f in p['files'] if f['id']==item['file_id'] and not f.get('withdrawn')),None)
            if not document: issues.append('文件已撤下')
            elif ws.get('environment')=='production' and document.get('storage')=='local' and document.get('remote_status')!='verified': issues.append('交付文件尚未核實存入公司 Lark')
    if any(t['required'] and t['status'] not in ('completed','superseded') for t in n['tasks']): issues.append('必做 SOP 尚未完成')
    if any(blocked(ws,p,t) for t in n['tasks']): issues.append('設計變更尚未解除')
    if any(x['project_id']==p['id'] and x.get('node_id')==n['id'] and x['status']!='succeeded' for x in ws['input_revisions'] if not x.get('superseded')): issues.append('Input 尚未核實存回 Lark')
    if n['key']=='confirmation':
        issue=p['confirmation_issues'][-1] if p['confirmation_issues'] else None
        if not confirmation_current(p,n,issue) or issue['status'] not in ('issued','simulated'): issues.append('確認單尚未取得全部發出回執')
        elif set(issue['recipients'])!={a['user_id'] for a in issue.get('acknowledgments',[])}: issues.append('各組尚未確認此版本確認單')
    if n['key']=='settlement':
        from .node_skip import valid_waiver
        if settlement_preconditions(p,ws): issues.append('報價、派工、確認單及計價節點尚未完成或核准不適用')
        if any(node['status']!='completed' and not valid_waiver(ws,p,node) for node in p['nodes'] if node['key'] in TECHNICAL): issues.append('適用工程交付尚未全部完成')
        if ws.get('environment')=='production':
            from .finance_readiness import financial_readiness
            issues.extend(financial_readiness(ws,p)['missing'])
        else:
            if not any(v['status']=='approved' for v in p['finance_versions']): issues.append('財務基準尚未核定')
            if not p.get('payment_reconciliation',{}).get('confirmed'): issues.append('收付款總額尚未核對結清')
            if any(b['status']!='paid' for b in p['payment_batches']): issues.append('收付款尚未結清')
            if any(not payment_delivery_valid(p,b) for b in p['payment_batches']): issues.append('請款交付版本尚未核實')
            if any(not r.get('verified') or set(valid_attestations(ws,p,r))!={'pm','admin'} or len(set(valid_attestations(ws,p,r).values()))!=2 for b in p['payment_batches'] for r in b.get('receipts',[])): issues.append('實際收付款尚未完成雙方核對')
    return issues

def review_hash(p,n):
    evidence=[e for e in p['evidence'] if e['node_id']==n['id'] and not e.get('withdrawn') and not e.get('superseded_for_current')]
    files={e.get('file_id') for e in evidence if e.get('file_id')}
    return digest({'tasks':[{k:t.get(k) for k in ('id','status','output','revision','owner_id','required','input_task_ids','source_snapshot')} for t in n['tasks']],
                   'requirements':n['requirements'],'seats':seats(p,n) if n['key'] not in FINANCIAL else None,'review_mode':n['review_mode'],
                   'evidence':evidence,'files':[{k:f.get(k) for k in ('id','version','sha256','storage','remote_status','remote_file_token','withdrawn','url')} for f in p['files'] if f['id'] in files],
                   'finance':p['finance_versions'] if n['key'] in FINANCIAL else None,'payments':p['payment_batches'] if n['key'] in FINANCIAL else None,'reconciliation':p.get('payment_reconciliation') if n['key']=='settlement' else None})

def invalidate(n, reason):
    for cycle in n['review_cycles']:
        if cycle['status'] in ('pending','approved') and not cycle.get('historical_scope'):
            cycle['status']='invalidated'; cycle['invalidated_reason']=reason
    if n['status']=='completed': n['status']='rework'; n['completed_at']=None


def begin_additional_scope(n,reason):
    """New batch obligations reopen the aggregate while retaining prior approvals."""
    for cycle in n['review_cycles']:
        if cycle['status']=='pending':
            cycle.update(status='invalidated',invalidated_reason=reason)
        elif cycle['status']=='approved':
            cycle['historical_scope']=True
    n.setdefault('scope_history',[]).append({'reason':reason,'previous_status':n['status'],'previous_completed_at':n.get('completed_at'),'opened_at':now()})
    if n['status']=='completed': n.update(status='in_progress',completed_at=None)

def seats(p,n):
    if n['key'] in FINANCIAL: return {'pm':p.get('pm_id',''),'admin':p.get('admin_id','')}
    result={f'person:{x}':x for x in n['reviewers']} if n.get('reviewers') else {'owner':n['owner_id']}
    if n['key'] in TECHNICAL: result['supervisor']=n.get('supervisor_id') or p.get('supervisor_id','')
    return result

def can_vote(ws,user,p,seat,representative):
    active_user(ws,representative)
    if user['id']==representative: return True
    today=now()[:10]
    return any(d['principal_id']==representative and d['delegate_id']==user['id'] and d['project_id']==p['id'] and d['seat']==seat and d.get('scope')=='review' and d['start_date']<=today<=d['end_date'] and d['status']=='active' and delegation_valid(ws,d,at_use=True) and (seat not in ('pm','admin') or capable(user,'finance_approve')) for d in ws['delegations'])

def delegation_valid(ws,item,at_use=False):
    if not item.get('qualification_evidence') or not item.get('qualified'): return False
    if item.get('source')=='approval':
        from .learning_sources import approval_is_fresh, approval_in_period
        approval=next((a for a in ws.get('approved_leave_delegations',[]) if a['id']==item.get('approval_instance_id')),None)
        return bool(approval_is_fresh(approval,now()) and (not at_use or approval_in_period(approval,now())) and approval.get('principal_id')==item['principal_id'] and approval.get('delegate_id')==item['delegate_id'] and str(approval.get('from',''))[:10]<=item['start_date']<=item['end_date']<=str(approval.get('to',''))[:10])
    return item.get('source')=='supervisor'

def valid_attestations(ws,p,item):
    valid={}
    for v in item.get('attestations',[]):
        if v.get('content_hash')!=attestation_hash(item): continue
        if p.get(v['seat']+'_id')!=v['principal_id']: continue
        actor=next((u for u in ws['users'] if u['id']==v['actor_id'] and u.get('active',True)),None)
        principal=next((u for u in ws['users'] if u['id']==v['principal_id'] and u.get('active',True)),None)
        if actor and principal and can_vote(ws,actor,p,v['seat'],v['principal_id']): valid[v['seat']]=v['actor_id']
    return valid

def require_financial_pair(ws,p,item):
    votes=valid_attestations(ws,p,item)
    require(set(votes)=={'pm','admin'} and len(set(votes.values()))==2,'需 PM 與行政兩位不同操作者核對本項',409)

def submit_review(ws,user,p,n):
    require(not (ws.get('environment')=='production' and n['key'] in FINANCIAL),'正式財務須走 Lark 原生共同核准，再核實條件完成節點',403)
    require(operator(user,p,n),'沒有本節點送審權')
    errors=missing(p,n,ws); require(not errors,'尚未完成：'+'、'.join(errors),409)
    current=next((c for c in reversed(n['review_cycles']) if c['status']=='pending'),None)
    fingerprint=review_hash(p,n)
    if current and current['content_hash']==fingerprint: return current
    targets=seats(p,n); require(targets and all(targets.values()),'確認人尚未完整分派',409)
    for ident in targets.values(): active_user(ws,ident)
    if n['key'] in FINANCIAL: require(len(set(targets.values()))==2,'PM 與行政必須是兩位不同的人',409)
    else: require(len(set(targets.values()))==len(targets),'不同確認職責須由不同人擔任；負責人不可兼主管確認',409)
    invalidate(n,'重新送審')
    cycle=dict(id=uid(),status='pending',content_hash=fingerprint,mode='all' if n['key'] in FINANCIAL else n['review_mode'],seats=targets,votes=[],created_at=now(),submitted_by=user['id'],rule_version=p['sop_version'])
    n['review_cycles'].append(cycle); return cycle

def vote(ws,user,p,n,data):
    require(not (ws.get('environment')=='production' and n['key'] in FINANCIAL),'正式財務不使用本地票，請查回 Lark 原生共同核准',403)
    cycle=find(n['review_cycles'],data.get('cycle_id'),'審核輪次')
    require(cycle['status']=='pending','此審核輪次已結束',409)
    require(cycle['content_hash']==review_hash(p,n),'內容已改版，請重新送審',409)
    seat=data.get('seat'); require(seat in cycle['seats'],'確認職責不存在',422)
    representative=cycle['seats'][seat]
    require(seats(p,n).get(seat)==representative,'職責已變更，請重新整理',409)
    require(can_vote(ws,user,p,seat,representative),'沒有此職責的有效確認權')
    require(not any(v['actor_id']==user['id'] and v['seat']!=seat and v['result']=='approved' and not v.get('invalidated') for v in cycle['votes']),'不同職責須由不同實際操作者確認，代理人也不能兼投兩票',409)
    result=data.get('result'); require(result in ('approved','returned'),'確認結果錯誤',422)
    if result=='returned': require(bool(str(data.get('reason','')).strip()),'退回需填理由',422)
    prior=next((v for v in cycle['votes'] if v['seat']==seat and not v.get('invalidated')),None)
    if prior: prior['invalidated']='同方重新確認'
    cycle['votes'].append(dict(seat=seat,principal_id=representative,actor_id=user['id'],result=result,reason=data.get('reason',''),created_at=now()))
    if result=='returned': cycle['status']='returned'; n.update(status='rework',completed_at=None); return
    valid=set(); actors=set()
    for v in cycle['votes']:
        if v['result']!='approved' or v.get('invalidated') or seats(p,n).get(v['seat'])!=v['principal_id']: continue
        voter=next((u for u in ws['users'] if u['id']==v['actor_id'] and u.get('active',True)),None)
        principal=next((u for u in ws['users'] if u['id']==v['principal_id'] and u.get('active',True)),None)
        if voter and principal and can_vote(ws,voter,p,v['seat'],v['principal_id']):
            require(v['actor_id'] not in actors,'既有確認由同一操作者兼投，請重新送交確認',409)
            actors.add(v['actor_id']); valid.add(v['seat'])
    passed=(len(valid)==len(cycle['seats'])) if cycle['mode']=='all' else bool(valid-{'supervisor'})
    if n['key'] in TECHNICAL: passed=passed and 'supervisor' in valid
    if passed:
        errors=missing(p,n,ws); require(not errors,'尚未完成：'+'、'.join(errors),409)
        cycle['status']='approved'; cycle['completed_at']=now(); n.update(status='completed',completed_at=now())
        if all(x['status']=='completed' for x in p['nodes'] if x['key'] in TECHNICAL): p['execution_status']='engineering_complete'
        if n['key']=='settlement': p['execution_status']='completed'

def apply_operation(ws,user,body,demo=False,cfg=None):
    from .input_validation import validate_action
    validate_action(body)
    """Returns False for legacy task actions, True for handled actions."""
    upgrade(ws); action=body['action']; data=body.get('payload') or {}
    from .case_cutover import resolve_action_projects,require_execution
    for target in resolve_action_projects(ws,body):require_execution(ws,target)
    if action in ('input_mapping','input_draft','input_submit'):
        require(demo,'正式 Input 請使用專用登錄入口，不再設定來源格子或修改來源紀錄',409)
    if action.startswith(('finance_','payment_')):
        require(demo,'正式帳務與金額由來源管理；請使用指定的財務申請與共同核准流程',403)
    if action in ('schedule_set','quote_review'):
        from .management import apply_management
        return apply_management(ws,user,body)
    if action.startswith('node_skip_'):
        from .node_skip import apply_skip
        return apply_skip(ws,user,body,demo)
    if action in ('sop_event_record','sop_deadline_resolve','sop_followup_complete'):
        from .sop_deadlines import apply_sop_deadline
        return apply_sop_deadline(ws,user,body)
    if action in ('sop_condition_propose','sop_condition_confirm'):
        from .sop_execution import apply_condition
        return apply_condition(ws,user,body)
    if action=='sop_round_open':
        from .sop_execution import apply_round
        return apply_round(ws,user,body)
    if action in ('sop_applicability_propose','sop_applicability_confirm'):
        from .sop_applicability import apply_applicability
        return apply_applicability(ws,user,body)
    if not action.startswith(('admin_','sop_','evidence_','review_','finance_','payment_','delivery_','migration_','recurring_','input_','confirmation_','daily_','handover_','document_','job_','delegation_','project_roles')) and action not in ('node_complete','financial_finalize'): return False
    active_user(ws,user['id'])
    pid=body.get('project_id'); nid=body.get('node_id')
    p=find(ws['projects'],pid,'案件') if pid else None
    n=find(p['nodes'],nid,'節點') if p and nid else None
    if p: p.setdefault('delivery_batches',[])
    if p and action in ('finance_approve','payment_approve','payment_reconcile'):
        require(not (p.get('migration_review_required') or p.get('migration_conflicts')),'來源案件合併尚待主管核對',409)
        if action!='finance_approve': require(not p.get('migration_finance_reapproval_required'),'合併後財務基準尚未重新共同核定',409)
    if action=='admin_person':
        require(capable(user,'manage_people'))
        ident=str(data.get('id','')).strip(); require(bool(ident),'請提供已核對的 Lark open_id 或測試人員識別',422)
        target=next((x for x in ws['users'] if x['id']==ident),None)
        require(demo or target is not None,'正式人員須由已核實的公司名冊建立，不能手填帳號造人',403)
        role=data.get('role',(target or {}).get('role','member')); require(role in ('manager','pm','member'),'角色錯誤',422)
        if role=='manager' or (target or {}).get('role')=='manager': require(user['role']=='manager','只有最高管理員可以調整管理員身分',403)
        caps=list(dict.fromkeys(data.get('capabilities',(target or {}).get('capabilities',[])))); require(set(caps)<=set(CAPABILITIES),'未知操作權限',422)
        if ('approve_capability' in caps) != ('approve_capability' in (target or {}).get('capabilities',[])):
            require('approve_capability' in user.get('capabilities',[]),'只有明確指定的能力認定者可授予或撤回認定權限',403)
        require(user['role']=='manager' or role!='manager' and set(caps)<=set(user.get('capabilities',[])),'不可授予超出自身的管理權')
        active=bool(data.get('active',(target or {}).get('active',True)))
        if target and target['role']=='manager' and (role!='manager' or not active): require(any(u['id']!=ident and u['role']=='manager' and u.get('active',True) for u in ws['users']),'不可移除最後一位管理員',409)
        if not target: target={'id':ident}; ws['users'].append(target)
        previous=deepcopy(target)
        target.update(name=str(data.get('name') or target.get('name') or ident),department=str(data.get('department',target.get('department',''))),role=role,capabilities=caps,active=active,default_workspace=data.get('default_workspace',target.get('default_workspace','test' if role=='manager' else 'production')))
        require(target['default_workspace'] in ('test','production'),'預設工作區錯誤',422)
        target['avatar']=target['name'][:1]; target['authz_version']=target.get('authz_version',0)+1
        for project in ws['projects']: refresh_project_state(project,ws)
        event(ws,user,action,message=json.dumps({'person':ident,'before':previous,'after':target},ensure_ascii=False)); return True
    if action=='admin_settings':
        require(user['role']=='manager')
        allowed=set(ws['settings'])
        require(set(data)<=allowed,'未知設定',422)
        proposed={**ws['settings'],**data}
        require(proposed.get('deadline_basis')=='scheduled_shift' and proposed.get('cutoff_time') is None,'截止時間必須依個人正常班表，不能改為固定時間',422)
        require(proposed.get('source_sync_seconds')==300,'來源同步固定每五分鐘',422)
        require(proposed.get('test_connection_mode') in ('simulation','isolated_live'),'測試連線模式錯誤',422)
        from .policy import defaults
        approved=defaults()
        for key in ('v4_base','quote_base','capability_base'):
            require(proposed.get(key)==approved[key],'案件與能力來源僅限使用者已核定的 Base',422)
        for key in ('digest_time',):
            try: datetime.strptime(proposed[key],'%H:%M')
            except (ValueError,TypeError): require(False,'時間格式需為 HH:MM',422)
        for key in ('field_weekday','indoor_weekday','review_weekday'): require(isinstance(proposed[key],int) and 0<=proposed[key]<=6,'星期設定錯誤',422)
        for key in ('monthly_workday','followup_workdays'): require(isinstance(proposed[key],int) and 1<=proposed[key]<=20,'工作日數需為1至20',422)
        require(proposed['timezone']=='Asia/Taipei','本版使用台北時間',422)
        require(not proposed['test_base'] or proposed['test_base'] not in (proposed['v4_base'],proposed['quote_base'],proposed['capability_base']),'測試 Base 不可指向正式來源',422)
        require(not proposed.get('input_base') or proposed['input_base'] not in (proposed['v4_base'],proposed['quote_base'],proposed['capability_base'],proposed['test_base']),'Input 登錄 Base 不可指向來源或測試 Base',422)
        require(not proposed.get('test_input_table') or proposed['test_input_table']!=proposed.get('input_table'),'隔離測試 Input 表不可混用正式表',422)
        require(not proposed['test_drive_root'] or proposed['test_drive_root']!=proposed['drive_root'],'測試目錄不可指向正式目錄',422)
        if cfg is not None and ('drive_root' in data or 'test_drive_root' in data):
            for key in ('drive_root','test_drive_root'): require(isinstance(proposed.get(key),str),'Drive 目錄需為文字',422)
            approved,test_root=cfg.get('LARK_DRIVE_ROOT'),cfg.get('LARK_TEST_DRIVE_ROOT')
            require(not proposed['drive_root'] or ws.get('environment')!='production' or (proposed['drive_root']==approved and proposed['drive_root']!=test_root),'正式 Drive 目錄須等同伺服器核定目錄且不得為測試目錄',422)
            require(not proposed['test_drive_root'] or proposed['test_drive_root']!=approved,'測試目錄不可指向伺服器核定的正式目錄',422)
        ws['settings']=proposed
    elif action=='sop_draft':
        require(capable(user,'edit_sop'))
        source=find(ws['sop_templates'],data.get('source_id'),'SOP 範本')
        version=deepcopy(source); version.update(id=uid(),version=max(s['version'] for s in ws['sop_templates'])+1,status='draft',created_by=user['id'],created_at=now())
        if data.get('nodes'):
            require({s['key'] for s in data['nodes']}=={s['key'] for s in source['nodes']},'需保留全部既有節點',422)
            for s in data['nodes']:
                require(s.get('review_mode') in ('all','any') and s.get('tasks') and all(isinstance(t,str) and t.strip() for t in s['tasks']),'SOP任務與模式錯誤',422)
                require(isinstance(s.get('requirements'),list) and all(isinstance(r.get('key'),str) and r.get('label') for r in s['requirements']),'文件規則錯誤',422)
            version['nodes']=deepcopy(data['nodes'])
            for node in version['nodes']:
                original=next(s for s in source['nodes'] if s['key']==node['key'])
                if 'task_definitions' not in node:
                    definitions=[]
                    for title in node['tasks']:
                        prior=[d for d in original.get('task_definitions',[]) if d['title']==title]
                        definitions.append(deepcopy(prior[0]) if len(prior)==1 else {'key':uid(),'title':title,'source_scope':'local-draft'})
                    node['task_definitions']=definitions
                defs=node['task_definitions']
                require(isinstance(defs,list) and len(defs)==len(node['tasks']) and all(isinstance(d,dict) and isinstance(d.get('key'),str) and d['key'].strip() and isinstance(d.get('title'),str) and d['title'].strip() for d in defs)
                        and len({d['key'] for d in defs})==len(defs) and [d['title'] for d in defs]==node['tasks'],'SOP 任務識別或標題對應不完整',422)
        from .sop_applicability import validate_template
        validate_template(version)
        ws['sop_templates'].append(version)
    elif action=='sop_publish':
        require(capable(user,'publish_sop')); t=find(ws['sop_templates'],data.get('id'),'SOP')
        from .sop_applicability import validate_template
        validate_template(t)
        require(t['status']=='draft','只能發布草稿',409); t.update(status='published',published_by=user['id'],published_at=now())
    elif action=='sop_request':
        require(p and lead(user,p)); t=find(ws['sop_templates'],data.get('id'),'SOP')
        require(t['status']=='published','只能套用已發布版本',422)
        ws['sop_requests'].append(dict(id=uid(),project_id=p['id'],target_id=t['id'],status='pending',reason=str(data.get('reason','')),requested_by=user['id'],from_version=p['sop_version']))
    elif action=='sop_apply':
        req=find(ws['sop_requests'],data.get('id'),'改版申請'); p=find(ws['projects'],req['project_id'])
        require(lead(user,p)); require(req['status']=='pending' and req['from_version']==p['sop_version'],'申請已失效',409)
        require(not any(c.get('status')=='pending' for node in p['nodes'] for c in node.get('review_cycles',[])),
                '案件仍有送審中的範圍，請先處理審核再套用 SOP',409)
        from .native_approval import abandoned_not_created
        require(not any(item.get('project_id')==p['id'] and item.get('native_binding',{}).get('attempted')
                        and item.get('status') not in ('executed','applied')
                        and not abandoned_not_created(item)
                        and item.get('native_receipt',{}).get('external_status') not in ('REJECTED','CANCELED','DELETED')
                        for collection in ('approvals','node_skip_requests','financial_requests') for item in ws.get(collection,[])),
                '原生審批仍有未處理的核准或未知結果，請先核實範圍再套用 SOP',409)
        t=find(ws['sop_templates'],req['target_id'])
        from .sop_contracts import merge_project_tasks
        merge_project_tasks(ws,p,t,user)
        for node in p['nodes']:
            definition=next(d for d in t['nodes'] if d['key']==node['key'])
            if node['status']=='completed': continue
            node['requirements']=deepcopy(definition['requirements']); node['review_mode']=definition['review_mode']; invalidate(node,'SOP改版')
        p['sop_version']=t['id']; req.update(status='approved',approved_by=user['id'],approved_at=now())
    elif action=='project_roles':
        from .business_policy import can_manage_roles
        require(p and (lead(user,p) or can_manage_roles(user)))
        protected={'supervisor_id','node_supervisor_id','reviewers','review_mode'}
        require(not (protected & data.keys()) or can_manage_roles(user),'審核主管與通過規則須由人員權限管理者設定；PM 不得自行變更',403)
        previous={'pm':p['pm_id'],'admin':p['admin_id']}
        from .workflow_rules import assignable, audit_change
        before_roles={key:p.get(key) for key in ('pm_id','admin_id','supervisor_id','sales_id','quotation_id','assistant_id','issuer_ids')}
        before_node={key:n.get(key) for key in ('owner_id','supervisor_id','reviewers','review_mode')} if n else None
        assignments=[data[k] for k in ('pm_id','admin_id','supervisor_id','sales_id','quotation_id','assistant_id','owner_id','node_supervisor_id') if data.get(k)]+data.get('issuer_ids',[])+data.get('reviewers',[])
        require(all(assignable(ws,find(ws['users'],ident,'負責人')) for ident in assignments),'新職責須指派已核實的在職人員',409)
        for key in ('pm_id','admin_id','supervisor_id','sales_id','quotation_id','assistant_id'):
            if key in data:
                if data[key]: active_user(ws,data[key])
                p[key]=data[key]
        if before_roles.get('pm_id')!=p.get('pm_id') or before_roles.get('sales_id')!=p.get('sales_id'):
            for review in p.get('quote_reviews',[]):
                if review.get('status')=='pending':
                    review.update(status='invalidated',invalidated_at=now(),invalidated_reason='PM 或業務職責已改派，原投票失效')
        for node in p['nodes']:
            for task in node['tasks']:
                role=task.get('sop_owner_role')
                if role not in ('quotation','assistant') or role+'_id' not in data: continue
                if task.get('owner_id') or task.get('status')!='pending': continue
                owner=p.get(role+'_id')
                if owner:
                    from .workflow_rules import assign_task
                    assign_task(ws,p,node,task,owner,user,False,'補齊報價組／工務助理，承接尚未指派期限任務')
                    task['assignment_status']='assigned'
        require(not p['pm_id'] or not p['admin_id'] or p['pm_id']!=p['admin_id'],'PM與行政須為不同人',422)
        if 'issuer_ids' in data:
            for ident in data['issuer_ids']: active_user(ws,ident)
            p['issuer_ids']=list(dict.fromkeys(data['issuer_ids']))
        if n:
            for key,target_key in (('owner_id','owner_id'),('node_supervisor_id','supervisor_id')):
                if key in data:
                    if data[key]: active_user(ws,data[key])
                    if target_key=='owner_id':
                        from .workflow_rules import assign_node
                        assign_node(ws,p,n,data[key],user,data.get('reason','案件角色改派'))
                    else: n[target_key]=data[key]
            if 'reviewers' in data:
                for ident in data['reviewers']: active_user(ws,ident)
                n['reviewers']=list(dict.fromkeys(data['reviewers']))
            if 'review_mode' in data:
                require(data['review_mode'] in ('all','any'),'模式錯誤',422); n['review_mode']=data['review_mode']
            if n['key'] not in FINANCIAL: invalidate(n,'確認人或規則調整')
        for node in p['nodes']:
            for c in node['review_cycles']:
                if c['status']!='pending' or node['key'] not in FINANCIAL: continue
                for seat,new in [('pm',p['pm_id']),('admin',p['admin_id'])]:
                    if new!=previous[seat]:
                        c.setdefault('seat_history',[]).append({'seat':seat,'previous':c['seats'][seat],'new':new,'at':now()}); c['seats'][seat]=new
                        for v in c['votes']:
                            if v['seat']==seat: v['invalidated']='職責交接'
        if previous!={'pm':p['pm_id'],'admin':p['admin_id']}: p['handoffs'].append({'before':previous,'after':{'pm':p['pm_id'],'admin':p['admin_id']},'actor':user['id'],'at':now()})
        after_roles={key:p.get(key) for key in before_roles}
        after_node={key:n.get(key) for key in before_node} if n else None
        if before_roles!=after_roles or before_node!=after_node:
            audit_change(ws,user,'project_role_assignment',p,n,before={'project':before_roles,'node':before_node},after={'project':after_roles,'node':after_node},reason=data.get('reason','角色配置調整'))
    elif action=='delegation_set':
        require(p and (user['role']=='manager' or user['id']==p['supervisor_id']))
        for key in ('principal_id','delegate_id'): active_user(ws,data.get(key))
        require(data['principal_id']!=data['delegate_id'],'代理人不可與本人相同',422)
        require(data.get('qualified') is True and str(data.get('qualification_note','')).strip(),'需確認代理資格並記錄依據',422)
        require(str(data.get('qualification_evidence','')).strip(),'需引用能力認定或主管資格審查證據',422)
        for key in ('start_date','end_date'): valid_date(data.get(key))
        require(data['start_date']<=data['end_date'],'代理期間錯誤',422)
        seat=data.get('seat'); scope=data.get('scope'); source=data.get('source')
        require(seat in ('owner','pm','admin','supervisor') and scope in ('tasks','review'),'代理職責或範圍錯誤',422)
        require(source in ('approval','supervisor'),'需指定已核准請假審批或主管指定來源',422)
        raw_task_ids=data.get('task_ids',[])
        require(isinstance(raw_task_ids,list) and all(isinstance(x,str) and x for x in raw_task_ids),'代理任務識別格式錯誤',422)
        task_ids=list(dict.fromkeys(raw_task_ids))
        if scope=='tasks':
            require(seat=='owner' and task_ids,'工作代理需明確指定任務',422)
            for ident in task_ids:
                pair=next(((node,t) for node,t in all_tasks(p) if t['id']==ident),None)
                require(pair and pair[1]['owner_id']==data['principal_id'],'代理任務不屬於被代理人',422)
                if pair[0]['key'] in ('control','mapping','report'): require(source=='approval','內業代理須核對已核准請假審批',409)
        else:
            require(seat in ('pm','admin','supervisor') and p.get(seat+'_id')==data['principal_id'],'被代理人非目前案件確認職責',422)
            require(not task_ids,'確認代理不可混入任務範圍',422)
            if seat in ('pm','admin'):
                require(capable(user,'manage_handover') and capable(active_user(ws,data['delegate_id']),'finance_approve'),'財務代理須經交接管理者指定且代理人已有財務確認權')
        delegation={k:data[k] for k in ('principal_id','delegate_id','seat','start_date','end_date','qualified','qualification_note','qualification_evidence','source','scope')}
        delegation.update(id=uid(),project_id=p['id'],status='active',approved_by=user['id'],task_ids=task_ids,approval_instance_id=data.get('approval_instance_id'))
        require(delegation_valid(ws,delegation),'代理來源尚未核實或與核准請假人員、期間不符',409)
        ws['delegations'].append(delegation)
    elif action=='delegation_revoke':
        d=find(ws['delegations'],data.get('id')); p=find(ws['projects'],d['project_id']); require(user['role']=='manager' or user['id']==p['supervisor_id']); d['status']='revoked'
    elif action=='evidence_submit':
        require(p and n and operator(user,p,n)); require(any(r['key']==data.get('key') for r in n['requirements']),'未知交付項目',422)
        note=str(data.get('note','')).strip(); require(note,'需填資料或不適用理由',422)
        na=bool(data.get('not_applicable'))
        if na: require(lead(user,p),'由PM提出不適用')
        url=str(data.get('url','')); file_id=data.get('file_id'); daily_id=data.get('daily_id')
        if url: http_url(url)
        if file_id: require(not find(p['files'],file_id).get('withdrawn'),'文件已撤下',409)
        daily_version=None
        if daily_id:
            from .v4_sources import daily_source_version
            daily=find(p['daily_reports'],daily_id,'案件日報')
            require(not daily.get('source_missing'),'來源日報已不存在，不能當作交付證明',409)
            daily_version=daily_source_version(daily)
        require(na or bool(url or file_id or daily_id),'需引用文件、日報或佐證連結',422)
        additional=data.get('new_batch') is True
        require(not additional or n['key'] in TECHNICAL and data['key'] in ('deliverable','field_report'),'新批次模式僅用於技術成果；修訂或財務證據須走原覆核',422)
        replacement=data.get('replaces_evidence_id')
        if replacement:
            old=find(p['evidence'],replacement,'修訂證據')
            require(not additional and old['node_id']==n['id'] and old['key']==data['key'],'修訂證據不屬於本節點或資料項目',422)
        for old in p['evidence']:
            if old['node_id']==n['id'] and old['key']==data['key']:
                if additional and not old.get('withdrawn'): old['superseded_for_current']=True
                elif not additional and (old['id']==replacement if replacement else not old.get('superseded_for_current')): old['withdrawn']=True
        p['evidence'].append(dict(id=uid(),node_id=n['id'],key=data['key'],note=note,url=url,file_id=file_id,daily_id=daily_id,daily_source_version=daily_version,status='na_requested' if na else 'submitted' if n['key'] in TECHNICAL else 'accepted',submitted_by=user['id'],created_at=now()))
        if additional: begin_additional_scope(n,'新增獨立成果批次；既有批次核准保留')
        else: invalidate(n,'交付資料換版')
    elif action=='evidence_approve':
        require(p is not None,'請指定案件',422); e=find(p['evidence'],data.get('id'),'交付資料'); n=find(p['nodes'],e['node_id'])
        require(can_business_override(user) or user['id'] in (p['supervisor_id'],n.get('supervisor_id')),'需對應主管覆核')
        require(e['status'] in ('submitted','na_requested') and not e.get('withdrawn'),'資料已失效',409)
        require(daily_evidence_current(p,e),'引用日報版本已變更，請重新提交交付資料',409)
        e.update(status='not_applicable' if e['status']=='na_requested' else 'accepted',approved_by=user['id'],approved_at=now()); invalidate(n,'交付覆核更新')
    elif action=='document_withdraw':
        require(p and operator(user,p)); f=find(p['files'],data.get('id')); require(str(data.get('reason','')).strip(),'撤下需填理由',422)
        f.update(withdrawn=True,withdrawn_reason=data['reason'],withdrawn_by=user['id'])
        for node in p['nodes']:
            if any(e.get('file_id')==f['id'] and e['node_id']==node['id'] for e in p['evidence']): invalidate(node,'文件撤下')
    elif action=='financial_finalize':
        require(not demo and ws.get('environment')=='production','此操作僅核實正式原生財務核准；測試使用明示模擬流程',409)
        require(p and n and n['key'] in FINANCIAL and operator(user,p,n),'沒有此財務節點核實權',403)
        errors=missing(p,n,ws);require(not errors,'尚未完成：'+'、'.join(errors),409)
        native=financial_confirmation(ws,p,n,require_fresh=True)
        require(native is not None,'需重新查回同節點有效原生財務共同核准',409)
        if n['status']!='completed':
            n['review_cycles'].append(dict(id=uid(),status='approved',mode='native',content_hash=review_hash(p,n),
                seats={'pm':p['pm_id'],'admin':p['admin_id']},votes=[],created_at=now(),completed_at=now(),
                submitted_by=user['id'],native_request_id=native['id'],native_verified_at=native['native_receipt']['verified_at'],rule_version=p['sop_version']))
            n.update(status='completed',completed_at=now())
    elif action in ('review_submit','node_complete'):
        require(p and n,'請指定節點',422); submit_review(ws,user,p,n)
    elif action=='review_vote':
        require(p and n,'請指定節點',422); vote(ws,user,p,n,data)
    elif action=='migration_review':
        require(p and (user['role']=='manager' or user['id']==p.get('supervisor_id')),'需案件主管核對來源合併')
        require(p.get('migration_review_required') or p.get('migration_conflicts'),'此案件沒有待核對的合併',409)
        reason=str(data.get('reason','')).strip(); require(reason,'需記錄合併人員、工作與財務的核對結果',422)
        conflicts=deepcopy(p.get('migration_conflicts',{}))
        p.setdefault('migration_review_history',[]).append(dict(id=uid(),actor_id=user['id'],at=now(),reason=reason,conflicts=conflicts,migration_history=deepcopy(p.get('migration_history',[]))))
        p.update(migration_review_required=False,migration_conflicts={})
        if 'finance' in conflicts:
            p['migration_finance_reapproval_required']=True
            p['payment_reconciliation']={'confirmed':False}
            # Historical approvals are retained; pending baselines need fresh
            # signatures after the manager has resolved the merge.
            for version in p['finance_versions']:
                if version.get('status')=='draft':
                    version.setdefault('attestation_history',[]).extend(deepcopy(version.get('attestations',[])))
                    version['attestations']=[]
        for node in p['nodes']:
            if node['key'] in FINANCIAL: invalidate(node,'來源合併核對更新')
    elif action=='delivery_submit':
        require(p is not None,'請指定案件',422)
        selected=data.get('work_item_ids',[]); evidence_ids=data.get('evidence_ids',[])
        require(isinstance(selected,list) and selected and all(isinstance(x,str) and x for x in selected) and len(set(selected))==len(selected),'需指定不重複的交付工項',422)
        require(isinstance(evidence_ids,list) and evidence_ids and all(isinstance(x,str) and x for x in evidence_ids),'需引用已核定成果證據',422)
        tasks=[]; nodes=[]
        for ident in selected:
            pairs=[(node,t) for node,t in all_tasks(p) if t['id']==ident or t.get('work_item_id')==ident]
            require(pairs,'交付工項不存在',404)
            for node,task in pairs:
                require(node['key'] in TECHNICAL and task['status'] in ('in_progress','completed') and not blocked(ws,p,task),'工項尚未作業或已暫停、退回',409)
                if task['id'] not in [t['id'] for t in tasks]: tasks.append(task); nodes.append(node)
        require(all(operator(user,p,node) for node in nodes),'沒有所有交付組別的建立權')
        evidence_ids=list(dict.fromkeys(evidence_ids))
        evidence=[find(p['evidence'],ident,'交付證據') for ident in evidence_ids]
        require(all(e['status']=='accepted' and not e.get('withdrawn') for e in evidence),'交付證據尚未核定或已撤下',409)
        require(all(any(e['node_id']==node['id'] and e['key'] in ('deliverable','field_report') for e in evidence) for node in nodes),'每個交付組別須引用對應成果證據',409)
        quantity=decimal(data.get('quantity')); require(quantity>0,'交付數量需大於零',422)
        unit=str(data.get('unit','')).strip(); require(unit,'需填交付單位',422)
        previous=find(p['delivery_batches'],data['replaces_id'],'既有交付版本') if data.get('replaces_id') else None
        if previous:
            require(not previous.get('superseded_by'),'此版本已被替代',409)
            require(str(data.get('reason','')).strip(),'交付換版需填理由',422)
        ident=uid()
        item=dict(id=ident,lineage_id=previous.get('lineage_id',previous['id']) if previous else ident,version=previous['version']+1 if previous else 1,replaces_id=previous['id'] if previous else None,work_item_ids=selected,quantity=str(quantity),unit=unit,evidence_ids=evidence_ids,status='submitted',task_snapshots=[{k:t.get(k) for k in ('id','revision','status','output')} for t in tasks],required_reviewer_ids=list(dict.fromkeys(node.get('supervisor_id') or p.get('supervisor_id') for node in nodes)),approvals=[],created_by=user['id'],created_at=now(),reason=data.get('reason',''))
        require(all(item['required_reviewer_ids']),'交付組別主管尚未指定',409)
        item['content_hash']=delivery_fingerprint(item)
        if previous: previous.update(superseded_by=ident,status='superseded')
        p['delivery_batches'].append(item)
        p['payment_reconciliation']={'confirmed':False}
    elif action=='delivery_review':
        require(p is not None,'請指定案件',422); item=find(p['delivery_batches'],data.get('id'),'交付批次')
        require(item['status']=='submitted' and not item.get('superseded_by'),'交付批次已核定、退回或換版',409)
        current_reviewers=delivery_reviewer_ids(p,item)
        require(current_reviewers and user['id'] in current_reviewers,'需由現任交付組主管核定交付')
        item['required_reviewer_ids']=current_reviewers
        item['approvals']=[a for a in item['approvals'] if a.get('actor_id') in current_reviewers and a.get('content_hash')==item['content_hash']]
        result=data.get('result'); require(result in ('approved','returned'),'交付核定結果錯誤',422)
        if result=='returned':
            require(str(data.get('reason','')).strip(),'退回需填理由',422); item.update(status='returned',returned_by=user['id'],reason=data['reason'])
        else:
            item['approvals']=[a for a in item['approvals'] if a['actor_id']!=user['id']]+[dict(actor_id=user['id'],at=now(),content_hash=item['content_hash'])]
            if set(item['required_reviewer_ids'])<={a['actor_id'] for a in item['approvals']}:
                item.update(status='approved',approved_at=now())
                require(delivery_current(p,item),'交付引用資料已變更，請重新提交版本',409)
    elif action=='finance_propose':
        require(p and (operator(user,p) or capable(user,'finance_edit')))
        amount=str(decimal(data.get('contract_amount'))); budget=str(decimal(data.get('budget')))
        require(str(data.get('evidence','')).strip(),'需回簽文件與核對依據',422)
        p['finance_versions'].append(dict(id=uid(),status='draft',contract_amount=amount,budget=budget,currency=str(data.get('currency','TWD')),tax_basis=str(data.get('tax_basis','未稅')),evidence=data['evidence'],created_by=user['id'],created_at=now()))
    elif action=='finance_approve':
        require(p and capable(user,'finance_approve')); v=find(p['finance_versions'],data.get('id'))
        require_financial_pair(ws,p,v)
        require(v['status']=='draft','版本已核定',409); v.update(status='approved',approved_by=user['id'],approved_at=now()); p['contract_amount']=float(v['contract_amount'])
        p['migration_finance_reapproval_required']=False
        p['payment_reconciliation']={'confirmed':False}
        for node in p['nodes']:
            if node['key'] in FINANCIAL: invalidate(node,'財務基準換版')
    elif action=='finance_allocate':
        require(p and (operator(user,p) or capable(user,'finance_edit')))
        amount=decimal(data.get('total')); parts=data.get('parts',[])
        require(parts and sum((decimal(x.get('amount')) for x in parts),Decimal(0))==amount,'分攤金額合計需等於成本總額',422)
        for x in parts: find(ws['projects'],x.get('project_id'))
        require(data.get('source_id') and data.get('reason'),'需成本來源與分攤依據',422)
        require(not any(a['source_id']==data['source_id'] and a['status'] in ('draft','approved') for a in ws['cost_allocations']),'此成本已有分攤，需先撤回草稿或另建調整來源',409)
        ws['cost_allocations'].append(dict(id=uid(),source_id=data['source_id'],project_id=p['id'],total=str(amount),parts=[dict(project_id=x['project_id'],amount=str(decimal(x['amount']))) for x in parts],reason=data['reason'],status='draft',created_by=user['id']))
    elif action=='finance_allocation_approve':
        require(capable(user,'finance_approve')); a=find(ws['cost_allocations'],data.get('id')); require(a['status']=='draft','分攤已核准',409); a.update(status='approved',approved_by=user['id'],approved_at=now())
    elif action=='finance_attest':
        require(p is not None,'請指定案件',422)
        category=data.get('category'); require(category in ('baseline','batch','receipt'),'核對類別錯誤',422)
        if category=='baseline': item=find(p['finance_versions'],data.get('id')); require(item['status']=='draft','已核定基準不需重簽',409)
        else:
            batch=find(p['payment_batches'],data.get('batch_id') or data.get('id'))
            item=find(batch.get('receipts',[]),data.get('id')) if category=='receipt' else batch
            if category=='batch': require(batch['status']=='draft','款項已核准',409)
        seat=data.get('seat'); require(seat in ('pm','admin'),'需選擇 PM 或行政',422)
        principal=p[seat+'_id']; require(principal and p['pm_id']!=p['admin_id'],'請指定不同的PM及行政代表',409)
        require(can_vote(ws,user,p,seat,principal),'無此職責的有效核對權')
        others={s:a for s,a in valid_attestations(ws,p,item).items() if s!=seat}
        require(user['id'] not in others.values(),'兩方須由不同實際操作者確認',409)
        require(str(data.get('evidence','')).strip(),'需填寫核對依據',422)
        item['attestations']=[v for v in item.get('attestations',[]) if v['seat']!=seat]+[dict(seat=seat,principal_id=principal,actor_id=user['id'],evidence=data['evidence'],at=now(),content_hash=attestation_hash(item))]
        p['payment_reconciliation']={'confirmed':False}
    elif action=='payment_create':
        require(p and operator(user,p)); kind=data.get('kind'); require(kind in ('receivable','subcontract'),'款項種類錯誤',422)
        phase=data.get('phase','progress'); require(phase in ('advance','progress','final'),'期別錯誤',422)
        require(str(data.get('contract_evidence','')).strip() and str(data.get('claim_evidence','')).strip(),'需合約條件及請款證據',422)
        if kind=='subcontract' and phase!='advance': require(data.get('acceptance_evidence'),'成果款需驗收證據',422)
        amount=decimal(data.get('amount')); require(amount>0,'款項金額需大於零',422)
        refs=delivery_references(p,data.get('delivery_batch_ids',[]),kind=kind) if phase!='advance' or data.get('delivery_batch_ids') else []
        p['payment_batches'].append(dict(id=uid(),kind=kind,phase=phase,amount=str(amount),status='draft',contract_evidence=data['contract_evidence'],claim_evidence=data['claim_evidence'],acceptance_evidence=data.get('acceptance_evidence',''),delivery_references=refs,technical_approved_by=None,created_by=user['id'],created_at=now()))
        p['payment_reconciliation']={'confirmed':False}
        for node in p['nodes']:
            if node['key'] in FINANCIAL: invalidate(node,'新增款項')
    elif action=='payment_accept':
        require(p and user['id']==p['supervisor_id']); b=find(p['payment_batches'],data.get('id')); require(b['status']=='draft','款項已送審',409); b['technical_approved_by']=user['id']
    elif action=='payment_revise':
        require(p and operator(user,p)); b=find(p['payment_batches'],data.get('id'))
        require(str(data.get('reason','')).strip(),'款項換版需填理由',422)
        require(b['status']!='cancelled','款項已取消',409)
        refs=delivery_references(p,data.get('delivery_batch_ids',[]),batch_id=b['id'],kind=b['kind'])
        b.setdefault('revision_history',[]).append(dict(delivery_references=deepcopy(b.get('delivery_references',[])),attestations=deepcopy(b.get('attestations',[])),status=b['status'],at=now(),actor_id=user['id'],reason=data['reason']))
        b.update(delivery_references=refs,attestations=[],technical_approved_by=None,status='draft')
        p['payment_reconciliation']={'confirmed':False}
    elif action=='payment_approve':
        require(p and capable(user,'finance_approve')); b=find(p['payment_batches'],data.get('id')); require(b['status']=='draft','款項非草稿',409)
        require(payment_delivery_valid(p,b),'須綁定有效核定交付版本後重新確認',409)
        require_financial_pair(ws,p,b)
        require(b['kind']!='subcontract' or b['phase']=='advance' or b['technical_approved_by'],'成果款需組主管驗收',409); b.update(status='approved',approved_by=user['id'],approved_at=now())
        kind='receivable' if b['kind']=='receivable' else 'subcontract_receivable'
        if not any(r.get('batch_id')==b['id'] and r['kind']==kind for r in ws['recurring']): ws['recurring'].append(dict(id=uid(),project_id=p['id'],kind=kind,title='收付款追蹤',owner_id=p['admin_id'] or p['pm_id'],supervisor_id=p['supervisor_id'],start_date=now()[:10],due_date=next_due(kind,now()[:10],ws),status='active',history=[],batch_id=b['id']))
    elif action=='payment_record':
        require(p and operator(user,p)); b=find(p['payment_batches'],data.get('id')); require(b['status'] in ('approved','partially_paid'),'請先核准款項',409)
        amount=decimal(data.get('amount')); require(amount>0 and amount+sum((decimal(x['amount']) for x in b.get('receipts',[])),Decimal(0))<=decimal(b['amount']),'本次實收付金額超過未清款項',422)
        require(str(data.get('evidence','')).strip(),'需實際收付款證據',422); valid_date(data.get('date'))
        b.setdefault('receipts',[]).append(dict(id=uid(),amount=str(amount),date=data['date'],evidence=data['evidence'],actor_id=user['id'],status='pending',verified=False,attestations=[]))
        refresh_payment_status(ws,p,b)
        p['payment_reconciliation']={'confirmed':False}
    elif action=='payment_reconcile':
        require(p and capable(user,'finance_approve'))
        for batch in p['payment_batches']: refresh_payment_status(ws,p,batch)
        v=next((v for v in reversed(p['finance_versions']) if v['status']=='approved'),None); require(v,'需先核定基準',409)
        receivables=sum((decimal(b['amount']) for b in p['payment_batches'] if b['kind']=='receivable'),Decimal(0))
        require(receivables==decimal(v['contract_amount']) and all(b['status']=='paid' for b in p['payment_batches']),'應收總額與核定合約或實收付尚未結清',409)
        for batch in p['payment_batches']:
            require(payment_delivery_valid(p,batch),'請款交付版本尚未核實',409)
            for receipt in batch.get('receipts',[]): require_financial_pair(ws,p,receipt)
        require(data.get('evidence') and data.get('all_payables_declared') is True,'需確認全部下包應付款已登錄並提供核對證據',422)
        p['payment_reconciliation']=dict(confirmed=True,evidence=data['evidence'],actor_id=user['id'],at=now(),finance_id=v['id'])
    elif action=='recurring_create':
        require(p and lead(user,p)); kind=data.get('kind'); require(kind in ('client_contact','correction','receivable','subcontract_receivable','daily_progress','field_schedule','indoor_schedule','weekly_review','monthly'),'週期種類錯誤',422)
        active_user(ws,data.get('owner_id')); valid_date(data.get('start_date'))
        ws['recurring'].append(dict(id=uid(),project_id=p['id'],kind=kind,owner_id=data['owner_id'],supervisor_id=p['supervisor_id'],title=str(data.get('title') or kind),start_date=data['start_date'],due_date=next_due(kind,data['start_date'],ws),status='active',history=[],batch_id=data.get('batch_id')))
    elif action=='recurring_complete':
        r=find(ws['recurring'],data.get('id')); p=find(ws['projects'],r['project_id']); require(user['id']==r['owner_id'] or lead(user,p))
        require(r['status']=='active','此追蹤已結束',409)
        require(data.get('evidence'),'請記錄本次追蹤結果與佐證',422)
        if data.get('finished'):
            if r['kind']=='client_contact': require(declared(p) in ('已完工','已結案') or p['execution_status'] in ('engineering_complete','completed'),'工程完成前持續聯繫',409)
            elif r['kind'] in ('receivable','subcontract_receivable'):
                settled=any(b['id']==r.get('batch_id') and b['status']=='paid' for b in p['payment_batches']) if r.get('batch_id') else p.get('payment_reconciliation',{}).get('confirmed')
                require(settled,'款項尚未核實結清',409)
            elif r['kind']=='correction': require(can_business_override(user) or user['id']==p['supervisor_id'],'補正須由主管確認驗收')
            else: require(False,'例行工作持續執行，請記錄本期結果',409)
        approval=r['kind'] in ('field_schedule','indoor_schedule','monthly')
        require(not any(x.get('status')=='pending' for x in r['history']),'本期已送審',409)
        r['history'].append(dict(id=uid(),at=now(),actor_id=user['id'],evidence=data['evidence'],status='pending' if approval else 'accepted'))
        if not approval: r['due_date']=next_due(r['kind'],now()[:10],ws)
        if data.get('finished'): r['status']='completed'
    elif action=='recurring_review':
        r=find(ws['recurring'],data.get('id')); p=find(ws['projects'],r['project_id']); entry=find(r['history'],data.get('entry_id'))
        require(entry['status']=='pending','本期非待審狀態',409)
        reviewer=p['supervisor_id'] if r['kind']=='monthly' else p['pm_id']
        require(user['id']==reviewer or can_business_override(user),'需指定PM或主管核准')
        require(data.get('result') in ('accepted','returned') and data.get('evidence'),'需核准或退回及依據',422)
        entry.update(status=data['result'],reviewed_by=user['id'],reviewed_at=now(),review_evidence=data['evidence'])
        if data['result']=='accepted': r['due_date']=next_due(r['kind'],now()[:10],ws)
    elif action=='daily_propose':
        from .v4_sources import daily_source_version,daily_mapping_version
        require(p is not None,'請指定案件',422); ident=data.get('daily_id')
        entry=next((d for d in ws['daily_unmatched']+[d for pr in ws['projects'] for d in pr['daily_reports']] if d['id']==ident),None); require(entry,'日報不存在',404)
        require(lead(user,p) or user['id'] in entry.get('source_actor_ids',[]),'需由已核實日報填報人或案件主管補充關聯')
        require(data.get('reason'),'需填核對依據',422)
        require(not entry.get('source_missing'),'來源日報目前不存在，不能新增配對核准',409)
        ws['daily_reviews'].append(dict(id=uid(),daily_id=ident,project_id=p['id'],source_fields=deepcopy(entry.get('source_fields',{})),source_version=daily_source_version(entry),mapping_version=daily_mapping_version(entry),entry=deepcopy(entry),reason=data['reason'],requested_by=user['id'],status='pending'))
    elif action=='daily_approve':
        from .v4_sources import daily_mapping_version,review_mapping_version
        require(capable(user,'review_mapping')); r=find(ws['daily_reviews'],data.get('id')); require(r['status']=='pending','已核對',409); p=find(ws['projects'],r['project_id'])
        current=[d for d in ws['daily_unmatched']+[d for pr in ws['projects'] for d in pr['daily_reports']] if d['id']==r['daily_id']]
        require(len(current)==1 and not current[0].get('source_missing') and daily_mapping_version(current[0])==review_mapping_version(r),'日報來源關聯已變更或不存在，請重新提出配對核對',409)
        for project in ws['projects']: project['daily_reports']=[d for d in project['daily_reports'] if d['id']!=r['daily_id']]
        ws['daily_unmatched']=[d for d in ws['daily_unmatched'] if d['id']!=r['daily_id']]
        entry=deepcopy(current[0]); entry.update(case_code=p['code'],match_basis='manual_review',case_mapping_status='matched'); p['daily_reports'].append(entry); r.update(status='approved',approved_by=user['id'],approved_at=now())
    elif action=='handover_request':
        require(p and lead(user,p)); active_user(ws,data.get('to_id')); active_user(ws,data.get('from_id')); require(data.get('reason'),'請填交接原因',422)
        ws['handover_requests'].append(dict(id=uid(),project_id=p['id'],from_id=data['from_id'],to_id=data['to_id'],reason=data['reason'],status='pending',requested_by=user['id']))
    elif action=='handover_approve':
        require(capable(user,'manage_handover')); h=find(ws['handover_requests'],data.get('id')); require(h['status']=='pending','交接已處理',409); h.update(status='awaiting_acceptance',approved_by=user['id'])
    elif action=='handover_accept':
        h=find(ws['handover_requests'],data.get('id')); require(h['to_id']==user['id'],'需接手人接受'); require(h['status']=='awaiting_acceptance','交接尚未核准',409); p=find(ws['projects'],h['project_id'])
        active_user(ws,h['to_id']); prior=h['from_id']; replacement=h['to_id']
        require(not (p['pm_id']==prior and p['admin_id']==replacement or p['admin_id']==prior and p['pm_id']==replacement),'交接會造成PM與行政同人',409)
        for key in ('pm_id','admin_id','supervisor_id'):
            if p[key]==prior: p[key]=replacement
        for node in p['nodes']:
            if node['owner_id']==prior: node['owner_id']=replacement
            if node.get('supervisor_id')==prior: node['supervisor_id']=replacement
            if prior in node.get('reviewers',[]):
                node['reviewers']=[replacement if ident==prior else ident for ident in node['reviewers']]
            for t in node['tasks']:
                if t['owner_id']==prior and t['status'] not in ('completed','superseded'): t['owner_id']=replacement
            for c in node['review_cycles']:
                if c['status']=='pending':
                    for seat,ident in list(c['seats'].items()):
                        if ident==prior:
                            c['seats'][seat]=replacement
                            for v in c['votes']:
                                if v['seat']==seat: v['invalidated']='職責交接'
        for r in ws['recurring']:
            if r['project_id']==p['id'] and r['owner_id']==prior and r['status']=='active': r['owner_id']=replacement
        h.update(status='accepted',accepted_at=now()); p['handoffs'].append(deepcopy(h))
    elif action=='confirmation_issue':
        require(p and (user['id'] in p['issuer_ids'] or capable(user,'issue_confirmation')),'沒有確認單發出權')
        active_user(ws,p['pm_id']); version=str(data.get('version','')).strip(); raw_recipients=data.get('recipients',[])
        require(isinstance(raw_recipients,list) and all(isinstance(x,str) for x in raw_recipients),'收件人格式不正確',422)
        recipients=list(dict.fromkeys(raw_recipients))
        require(version and recipients,'需版本與收件人',422)
        for ident in recipients: active_user(ws,ident)
        node=next(x for x in p['nodes'] if x['key']=='confirmation'); evidence=evidence_for(p,node,'confirmation')
        require(evidence and evidence['status']=='accepted','需核定確認單資料',409)
        groups=data.get('recipient_groups') or {}
        from .sop_execution import fan_out_targets
        require(isinstance(groups,dict) and set(groups)<=set(recipients) and all(isinstance(v,list) and v and all(isinstance(x,str) for x in v) and set(v)<=set(fan_out_targets()) for v in groups.values()),'收件人組別須屬 state_4 的下游節點',422)
        groups={k:sorted(set(v)) for k,v in groups.items()}
        fingerprint=digest({'version':version,'evidence':evidence['id'],'pm':p['pm_id'],'recipients':recipients,**({'groups':groups} if groups else {})})
        prior=next((i for i in p['confirmation_issues'] if i['version']==version),None)
        if prior: require(prior['fingerprint']==fingerprint,'同版本發出內容不同，請使用新版本',409)
        else:
            issue=dict(id=uid(),version=version,status='queued',fingerprint=fingerprint,pm_id=p['pm_id'],recipients=recipients,recipient_groups=groups,evidence_id=evidence['id'],issued_by=user['id'],created_at=now())
            p['confirmation_issues'].append(issue)
            queue(ws,'confirmation',user,{'project_id':p['id'],'issue_id':issue['id'],'recipients':recipients,'text':f"確認單 {p['code']} {p['name']} v{version} 已正式發出。PM：{active_user(ws,p['pm_id'])['name']}。請至工作台確認。"},'confirmation:'+issue['id'])
    elif action=='confirmation_ack':
        require(p is not None,'請指定案件',422); issue=find(p['confirmation_issues'],data.get('id'))
        node=next(x for x in p['nodes'] if x['key']=='confirmation')
        require(confirmation_current(p,node,issue),'確認單資料或發出範圍已變更，請重新發出',409)
        require(issue['status'] in ('issued','simulated'),'確認單尚未成功發出',409)
        require(user['id'] in issue['recipients'],'只能由指定收件人確認')
        require(str(data.get('evidence','')).strip(),'需填寫組別確認紀錄',422)
        issue['acknowledgments']=[a for a in issue.get('acknowledgments',[]) if a['user_id']!=user['id']]+[dict(user_id=user['id'],evidence=data['evidence'],at=now())]
        invalidate(node,'收件組別確認更新')
    elif action=='input_mapping':
        require(capable(user,'manage_sources')); require(p and n,'請指定案件與節點',422)
        if ws.get('environment')=='production':
            from .remote_policy import FORMAL_BASES
            require(data.get('base_token') not in FORMAL_BASES and data.get('base_token')==ws['settings'].get('input_base') and
                    data.get('table_id') and data.get('table_id')==ws['settings'].get('input_table'),
                    '正式 Input 只允許專用登錄表，不可寫回來源 Base',422)
        require(data.get('field_name') not in ('狀態','案件狀態','案件已入帳') and not data.get('connector_managed'),'狀態與連接器管理欄禁止回寫',422)
        require(data.get('type') in ('text','number','date','checkbox','select','person','link'),'欄位型別不支援或唯讀',422)
        for key in ('key','label','base_token','table_id','field_id','field_name','record_id'): require(str(data.get(key,'')).strip(),f'缺少 {key}',422)
        require(not any(m['project_id']==p['id'] and m['node_id']==n['id'] and m['key']==data['key'] and m['enabled'] for m in ws['input_mappings']),'同語意已有唯一目的，先停用既有映射',409)
        m={k:deepcopy(data[k]) for k in ('key','label','base_token','table_id','field_id','field_name','record_id','type')}; m.update(id=uid(),project_id=p['id'],node_id=n['id'],enabled=True,verified=False,options=data.get('options',[]),created_by=user['id']); ws['input_mappings'].append(m)
    elif action=='input_mapping_disable':
        require(capable(user,'manage_sources')); find(ws['input_mappings'],data.get('id'))['enabled']=False
    elif action=='input_draft':
        m=find(ws['input_mappings'],data.get('mapping_id')); p=find(ws['projects'],m['project_id']); n=find(p['nodes'],m['node_id']); require(operator(user,p,n)); require(m['enabled'],'映射已停用',409)
        value=data.get('value')
        if value is not None:
            if m['type']=='number': value=str(decimal(value))
            elif m['type']=='date': valid_date(value)
            elif m['type']=='checkbox': require(isinstance(value,bool),'需布林值',422)
            elif m['type']=='select': require(value in m['options'],'選項不存在',422)
            elif m['type']=='text': require(isinstance(value,str),'需文字值',422)
            elif m['type']=='person':
                require(isinstance(value,list),'需人員陣列',422)
                for ident in value: active_user(ws,ident)
            elif m['type']=='link': require(isinstance(value,list) and all(isinstance(v,str) and v.startswith('rec') for v in value),'需來源紀錄識別',422)
        old=[i for i in ws['input_revisions'] if i['mapping_id']==m['id'] and not i.get('superseded')]
        require(not any(i['status'] in ('queued','running','outcome_unknown') for i in old),'上一筆寫入尚未核實',409)
        for i in old: i['superseded']=True
        ws['input_revisions'].append(dict(id=uid(),mapping_id=m['id'],project_id=p['id'],node_id=n['id'],value=value,base_value=deepcopy(m.get('remote_value')),status='draft',actor_id=user['id'],created_at=now()))
        invalidate(n,'Input換版')
    elif action=='input_submit':
        i=find(ws['input_revisions'],data.get('id')); m=find(ws['input_mappings'],i['mapping_id']); p=find(ws['projects'],i['project_id']); n=find(p['nodes'],i['node_id']); require(operator(user,p,n)); require(i['status']=='draft' and not i.get('superseded'),'只能送出有效草稿',409)
        require(m['enabled'] and (m['verified'] or demo),'目的欄位尚未查證',409)
        i['status']='queued'; queue(ws,'input',user,{'input_id':i['id'],'mapping_id':m['id'],'project_id':p['id']},'input:'+i['id'])
    elif action=='job_retry':
        from .capability_write_policy import PAUSED_MESSAGE
        require(find(ws['jobs'],data.get('id'))['kind'] not in ('capability','training_record'),PAUSED_MESSAGE,403)
        j=find(ws['jobs'],data.get('id')); require(user['role']=='manager' or user['id']==j['actor_id']); require(j['status'] in ('failed','blocked'),'未知結果須核實，不能盲目重送',409); j.update(status='queued',next_attempt_at=now(),error=None)
    else: return False
    # Financial edits invalidate pending approvals without altering imported V4 status.
    if p and action.startswith(('finance_','payment_')):
        for node in p['nodes']:
            if node['key'] in FINANCIAL: invalidate(node,'財務內容更新')
    if p: refresh_project_state(p,ws)
    event(ws,user,action,p['id'] if p else None,n['id'] if n else None,message=data.get('reason') or action)
    return True

def project_summary(ws,p):
    from .sop_runtime import topology_projection
    from .node_skip import valid_waiver, skip_summary
    refresh_project_state(p,ws)
    from .finance_readiness import financial_readiness
    settlement=next((n for n in p['nodes'] if n['key']=='settlement'),None)
    closure_missing=missing(p,settlement,ws) if settlement else ['尚無結算節點']
    closure={'status':'completed' if p['execution_status']=='completed' else 'blocked' if closure_missing else 'ready','missing':closure_missing,
             'financial':financial_readiness(ws,p),'source_status_is_not_completion':True}
    return {'project_id':p['id'],'sop_topology':topology_projection(p),'source_status':p.get('source_status'),'execution_status':p['execution_status'],'closure':closure,'source_conflicts':p.get('source_conflicts',{}),'migration_review_required':bool(p.get('migration_review_required') or p.get('migration_conflicts')),'migration_conflicts':p.get('migration_conflicts',{}),'migration_finance_reapproval_required':p.get('migration_finance_reapproval_required',False),'progress':{'completed_nodes':sum(n['status']=='completed' for n in p['nodes']),'approved_skipped_nodes':sum(valid_waiver(ws,p,n) for n in p['nodes']),'total_nodes':len(p['nodes'])},'nodes':[{'id':n['id'],'name':n['name'],'source_completed':n.get('source_completed',False),'status':n['status'],'missing':missing(p,n,ws),'skip':skip_summary(ws,p,n),'review':n['review_cycles'][-1] if n['review_cycles'] else None} for n in p['nodes']]}
