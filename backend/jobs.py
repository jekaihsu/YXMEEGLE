"""Durable worker with conservative recovery and workspace-scoped checkpoints."""
import hashlib
from copy import deepcopy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, update
from . import storage
from .policy import upgrade
from .source_lifecycle import declared, needs_review
from .workflow import now, find, require, event
from .operations import queue, is_workday, next_due, operator, capable, active_user
from .lark_adapter import application_adapter, RemoteFailure
from .learning import cutoff
from .remote_policy import connection_policy, require_same_policy

LABELS={'client_contact':'業主聯繫','correction':'成果補正檢查','receivable':'案件收款追蹤','subcontract_receivable':'下包入帳追蹤','daily_progress':'每日進度檢查','field_schedule':'外業預排','indoor_schedule':'內業預排','weekly_review':'每週檢討','monthly':'月考評與結算'}

class PermissionCheckedClient:
    """Revalidate at each HTTP boundary, including reads before a conditional write."""
    def __init__(self,client,check): self.client=client; self.check=check
    def request(self,*args,**kwargs): self.check(); return self.client.request(*args,**kwargs)
    def get(self,*args,**kwargs): self.check(); return self.client.get(*args,**kwargs)
    def close(self): return self.client.close()


def reflect_job_status(state,job,status,message):
    """A lost lease must be visible on its business record, not only the queue."""
    payload=job['payload']
    if job['kind']=='mention':
        from .mention_notifications import reflect
        reflect(state,job,status,message)
    elif job['kind']=='input':
        find(state['input_revisions'],payload['input_id'])['status']=status
    elif job['kind']=='capability':
        award=next((a for a in state['capability_awards'] if a['id']==payload.get('award_id')),None)
        if not award: return
        plan=next((p for p in state['training_plans'] if p['id']==award.get('training_id')),None)
        award.update(remote_status=status,remote_error=message)
        if plan and (plan.get('award_id')==award['id'] or not plan.get('award_id') and plan.get('version')==award.get('training_version')):
            plan.update(remote_status=status,remote_error=message)
    elif job['kind']=='training_record':
        plan=next((p for p in state['training_plans'] if p['id']==payload.get('training_id')),None)
        if plan and plan['version']==payload.get('version'): plan.update(record_sync_status=status,record_error=message)
    elif job['kind']=='file':
        item=find(find(state['projects'],payload['project_id'])['files'],payload['file_id'])
        item.update(remote_status=status,remote_error=message)
    elif job['kind']=='confirmation':
        issue=find(find(state['projects'],payload['project_id'])['confirmation_issues'],payload['issue_id'])
        issue.update(status=status,error=message)


def schedule(ws,clock=None):
    clock=clock or now(); today=clock[:10]; upgrade(ws)
    from .case_cutover import execution_allowed
    from .workflow_rules import activate_scheduled
    activate_scheduled(ws,clock)
    for p in ws['projects']:
        if not execution_allowed(ws,p):continue
        if p.get('case_type')=='intake': continue
        if not p.get('pm_id'): continue
        if needs_review(p) or declared(p) in ('報價中','已結案','中止') or p.get('execution_status')=='completed': continue
        definitions=[('daily_progress',p['pm_id']),('field_schedule',next((n['owner_id'] for n in p['nodes'] if n['key']=='field'),'')),('indoor_schedule',p['supervisor_id']),('weekly_review',p['pm_id'])]
        if declared(p)=='執行中' or p['execution_status']=='in_progress': definitions.append(('client_contact',p['pm_id']))
        for kind,owner in definitions:
            if not owner or any(r['project_id']==p['id'] and r['kind']==kind for r in ws['recurring']): continue
            ident='routine-'+hashlib.sha256((p['id']+kind).encode()).hexdigest()[:24]
            ws['recurring'].append(dict(id=ident,project_id=p['id'],kind=kind,title=LABELS[kind],owner_id=owner,supervisor_id=p['supervisor_id'],status='active',start_date=today,due_date=today if kind=='daily_progress' else next_due(kind,today,ws),history=[]))
    due={}; source_projects={}
    for r in ws['recurring']:
        if r['kind']=='monthly':
            if r['status']=='active':
                r.update(status='disabled',disabled_reason='業主裁示停用考評；財務結算另依案件流程',disabled_at=clock)
            continue
        if r['status']!='active': continue
        p=next((p for p in ws['projects'] if p['id']==r['project_id']),None); kind=r['kind']
        if not p or not execution_allowed(ws,p) or p.get('case_type')=='intake' or needs_review(p):continue
        instant=datetime.fromisoformat(clock)
        if instant.tzinfo is None:instant=instant.replace(tzinfo=ZoneInfo('Asia/Taipei'))
        r['deadline']=cutoff(ws,r['owner_id'],r['due_date'],clock=instant)
        r['cutoff_time']=r['deadline']['time']
        r['deadline_status']=r['deadline']['status']
        r['overdue']=False
        if r['deadline'].get('reason')=='employee_identity_unverified':continue
        if r['deadline_status']=='ready':
            try:
                deadline=datetime.fromisoformat(r['deadline']['at']);instant=datetime.fromisoformat(clock)
                if instant.tzinfo is None:instant=instant.replace(tzinfo=ZoneInfo('Asia/Taipei'))
                if deadline.tzinfo is None:raise ValueError('Deadline timezone missing')
                r['overdue']=instant>deadline
            except (KeyError,ValueError,TypeError):r['deadline_status']='pending_schedule'
        financial=kind in ('receivable','subcontract_receivable')
        if kind=='client_contact' and declared(p) in ('已完工','已結案'): continue
        if declared(p)=='中止' and not financial: continue
        if declared(p) in ('已完工','已結案') and kind in ('daily_progress','field_schedule','indoor_schedule','weekly_review'): continue
        if financial and r.get('batch_id') and any(b['id']==r['batch_id'] and b['status']=='paid' for b in p['payment_batches']): continue
        if r['due_date']>today: continue
        targets={r['owner_id']}
        if r['overdue'] and r['deadline_status']=='ready': targets.update((p['pm_id'],r.get('supervisor_id')))
        for ident in targets:
            if not ident or not any(u['id']==ident and u.get('active',True) for u in ws['users']): continue
            source_projects.setdefault(ident,set()).add(p['id'])
            deadline_day=r['deadline'].get('at',r['due_date'])[:10]
            due.setdefault(ident,[]).append(f"{p['code']} · {LABELS.get(kind,r['title'])} · {deadline_day} {r['cutoff_time'] or '班表截止待設定'}")
    if not is_workday(date.fromisoformat(today),ws['calendar']) or clock[11:16]<ws['settings']['digest_time']: return
    for ident,lines in due.items():
        key='digest:'+today+':'+ident
        if any(j['key']==key for j in ws['jobs']): continue
        actor=active_user(ws,ident)
        queue(ws,'digest',actor,{'recipients':[ident],'text':'今日工作提醒\n'+'\n'.join(lines),
            'source_project_ids':sorted(source_projects[ident]),'source_scope':'case_digest_v1'},key)

class Worker:
    def __init__(self,sessions,workspace_model,business_model,people_model,cfg,upload_dir,adapter_factory=application_adapter):
        self.sessions=sessions; self.W=workspace_model; self.B=business_model; self.P=people_model; self.cfg=cfg; self.upload_dir=upload_dir; self.adapter_factory=adapter_factory

    def commit(self,db,row,state):
        expected=row.version; state['version']=expected+1
        root=storage.save(db,self.B,row.id,state)
        changed=db.execute(update(self.W).where(self.W.id==row.id,self.W.version==expected).values(data=root,version=expected+1))
        require(changed.rowcount==1,'背景工作版本衝突',409)

    def state(self,db,row):
        state=upgrade(storage.load(db,self.B,row))
        from .workspace_environment import normalize_environment
        from .case_cutover import initialize_execution_system
        normalize_environment(state,row.id,self.cfg)
        initialize_execution_system(state)
        if row.id.startswith(('lark-','test-lark-')):
            org=row.id.removeprefix('test-')
            profiles={r.person_id:r.data for r in db.scalars(select(self.P).where(self.P.organization_id==org))}
            state['users']=[deepcopy(profiles.get(u['id'],u)) for u in state['users']]
        from .production_access import set_company_admin_authority
        state['native_approval_authority']={'app_id':self.cfg.get('LARK_APP_ID'),'tenant':self.cfg.get('LARK_WORKER_ORGANIZATION')}
        set_company_admin_authority(state,self.cfg)
        return state

    def refresh_delegations(self,wid):
        """Refresh named approval instances read-only; uncertainty removes authority."""
        from .learning_sources import leave_refresh_due, read_application_leave
        if not wid.startswith('lark-') or self.cfg.get('LARK_WORKER_IDENTITY')!='application' or wid!='lark-'+self.cfg.get('LARK_WORKER_ORGANIZATION',''): return
        clock=now()
        with self.sessions.begin() as db:
            row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update())
            if not row: return
            state=self.state(db,row)
            if state.get('environment') in ('demo','test'): return
            codes={d.get('approval_instance_id') for d in state['delegations'] if d.get('source')=='approval' and d.get('status')=='active' and d.get('end_date','')>=clock[:10]}
            prior={a['id']:deepcopy(a) for a in state['approved_leave_delegations']}
            codes={c for c in codes if c and leave_refresh_due(prior.get(c),clock)}
            if not codes: return
            for code in codes:
                cached=next((a for a in state['approved_leave_delegations'] if a['id']==code),None)
                if cached: cached['last_refresh_attempt_at']=clock
                else: state['approved_leave_delegations'].append({'id':code,'status':'UNKNOWN','last_refresh_attempt_at':clock})
            state['leave_source_status']={'status':'refreshing','last_attempt_at':clock}
            self.commit(db,row,state)
        adapter=None; results={}; errors=[]
        try:
            adapter=self.adapter_factory(self.cfg)
            for code in sorted(codes):
                try:
                    result=read_application_leave(adapter,code)
                    result['last_refresh_attempt_at']=clock; results[code]=result
                except Exception as exc:
                    message=str(getattr(exc,'detail',exc)) if isinstance(exc,RemoteFailure) or hasattr(exc,'detail') else '請假審批無法核實'
                    results[code]={**prior.get(code,{}),'id':code,'status':'UNKNOWN','last_verified_at':prior.get(code,{}).get('verified_at'),'verified_at':None,'last_refresh_attempt_at':clock,'verification_error':message}
                    errors.append(code)
        except Exception as exc:
            message=str(exc) if isinstance(exc,RemoteFailure) else '背景審批連線無法使用'
            for code in codes:
                results[code]={**prior.get(code,{}),'id':code,'status':'UNKNOWN','last_verified_at':prior.get(code,{}).get('verified_at'),'verified_at':None,'last_refresh_attempt_at':clock,'verification_error':message}
            errors=list(codes)
        finally:
            if adapter: adapter.client.close()
        with self.sessions.begin() as db:
            row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update()); state=self.state(db,row)
            by_id={a['id']:a for a in state['approved_leave_delegations']}
            for code,result in results.items():
                # Do not overwrite a newer manual refresh completed while I/O ran.
                current=by_id.get(code,{})
                if (current.get('verified_at') or '')>clock: continue
                by_id[code]=result
            state['approved_leave_delegations']=list(by_id.values())
            state['leave_source_status']={'status':'error' if errors else 'ready','last_attempt_at':clock,'failed_instance_ids':errors}
            self.commit(db,row,state)

    def checkpoint(self,wid,jid,token,mutate):
        with self.sessions.begin() as db:
            row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update()); state=self.state(db,row); job=find(state['jobs'],jid)
            require(job.get('lease_token')==token and job['status']=='running','背景工作租約失效',409)
            mutate(state,job); self.commit(db,row,state)

    def authorize(self,wid,jid,token,test,policy=None):
        """Reload permissions immediately before each remote effect."""
        with self.sessions() as db:
            row=db.get(self.W,wid); state=self.state(db,row); job=find(state['jobs'],jid)
        require(job.get('lease_token')==token and job['status']=='running','工作已失去執行權',409)
        actor=active_user(state,job['actor_id']); payload=job['payload']
        from .case_cutover import require_execution
        if payload.get('project_id'):require_execution(state,find(state['projects'],payload['project_id']))
        current_policy=connection_policy(wid,state,self.cfg,job['kind'])
        if job['kind']=='digest' and not current_policy['simulated']:
            from .source_case_policy import visible_project
            from .case_cutover import execution_allowed
            ids=payload.get('source_project_ids')
            if (payload.get('source_scope')!='case_digest_v1' or not isinstance(ids,list)
                    or not ids or any(not isinstance(i,str) or not i for i in ids)):
                raise RemoteFailure('摘要缺少可核實的來源案件，停止外送','blocked')
            by_id={p['id']:p for p in state.get('projects',[])}
            if any(i not in by_id or not visible_project(state,by_id[i])
                    or not execution_allowed(state,by_id[i]) for i in ids):
                raise RemoteFailure('摘要來源包含舊案、未知案件或未核定案件，停止外送','blocked')
        if not current_policy['simulated']:
            from .production_access import access_mode
            if access_mode(actor,self.cfg.get('LARK_APP_ID'),cfg=self.cfg)!='normal':
                raise RemoteFailure('執行人名冊資格已過期或待核實；本工作停止外送','blocked')
        if policy is not None: require_same_policy(policy,current_policy)
        if current_policy['simulated']!=test: raise RemoteFailure('工作連線模式已改變','blocked')
        if job['kind']=='confirmation':
            p=find(state['projects'],payload['project_id']); issue=find(p['confirmation_issues'],payload['issue_id'])
            require(actor['id'] in p['issuer_ids'] or capable(actor,'issue_confirmation'),'發出權限已撤銷')
            require(p['pm_id']==issue['pm_id'],'PM已變更，請重新發出確認單',409)
            e=find(p['evidence'],issue['evidence_id'])
            require(not e.get('withdrawn') and e['status']=='accepted','確認單內容已失效',409)
            for recipient in payload['recipients']: active_user(state,recipient)
        elif job['kind']=='input':
            i=find(state['input_revisions'],payload['input_id']); m=find(state['input_mappings'],i['mapping_id']); p=find(state['projects'],i['project_id']); n=find(p['nodes'],i['node_id'])
            require(operator(actor,p,n) and m['enabled'] and not i.get('superseded'),'Input 權限或版本已失效')
            require(payload.get('project_id')==p['id'] and m.get('project_id')==p['id'] and m.get('node_id')==n['id'],'Input 案件與排隊紀錄不一致',409)
            require_execution(state,p)
            if not test:
                import json
                from .input_registration import validate_plan,registration_fields
                require(m.get('mode')=='append_registration' and i.get('registration_plan'),'Input 必須使用獨立登錄；舊欄位覆寫已停用',409)
                fields=registration_fields(self.cfg,current_policy)
                require(fields==i['registration_plan'].get('destination',{}).get('fields'),'Input 登錄欄位核定設定已變更',409)
                validate_plan(i['registration_plan'],current_policy)
            if not test: require((m.get('mode')=='append_registration' or m['verified']) and m['base_token']==current_policy['base_token'],'Input目的未核實')
            if not test and current_policy.get('table_id'): require(m['table_id']==current_policy['table_id'],'Input 登錄表不在核定目的')
        elif job['kind']=='file':
            p=find(state['projects'],payload['project_id']); f=find(p['files'],payload['file_id']); n=next((n for n in p['nodes'] if n['id']==f.get('node_id')),None)
            require(operator(actor,p,n) and not f.get('withdrawn'),'文件權限或版本已失效')
        elif job['kind']=='mention':
            from .mention_notifications import check_notification
            check_notification(state,actor,payload,self.cfg,test)
        elif job['kind'] in ('capability','training_record'):
            raise RemoteFailure('業主裁示停用：能力與訓練紀錄禁止回寫','blocked')
        return state,actor

    def run_one(self,wid):
        self.refresh_delegations(wid)
        with self.sessions.begin() as db:
            row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update()); state=self.state(db,row); before=deepcopy(state); schedule(state)
            for j in state['jobs']:
                if j['kind']=='digest' and LABELS['monthly'] in j.get('payload',{}).get('text','') and j['status'] not in ('succeeded','canceled','cancelled'):
                    j.update(status='blocked',error='此舊提醒含已停用的月考評，禁止發送；其他工作請看工作台')
                    j.pop('lease_token',None); j.pop('lease_until',None)
                    continue
                if j['kind'] in ('capability','training_record') and j['status'] not in ('succeeded','canceled','cancelled'):
                    from .capability_write_policy import PAUSED_MESSAGE
                    message='業主裁示不回寫' if j['kind']=='capability' else '業主裁示停用'
                    if not j.get('policy_blocked_at'):
                        j.update(policy_blocked_at=now(),status_before_policy_block=j['status'],error_before_policy_block=j.get('error'))
                    j.update(status='blocked',error=message+'：'+PAUSED_MESSAGE)
                    j.pop('lease_token',None)
                    j.pop('lease_until',None)
                    reflect_job_status(state,j,'blocked',j['error'])
                    continue
                if j['status']=='running' and j.get('lease_until','')<now():
                    j.update(status='outcome_unknown',error='前次執行中斷，須核實遠端效果')
                    reflect_job_status(state,j,j['status'],j['error'])
            # One lease per workspace prevents concurrent writes to the same remote cell.
            job=None if any(j['status']=='running' for j in state['jobs']) else next((j for j in state['jobs'] if j['status']=='queued' and j.get('next_attempt_at','')<=now()),None)
            if not job:
                if state!=before: self.commit(db,row,state)
                return None
            from .workflow import uid
            token=uid(); job.update(status='running',lease_token=token,lease_until=(datetime.fromisoformat(now())+timedelta(minutes=10)).isoformat(),attempts=job['attempts']+1)
            self.commit(db,row,state); job=deepcopy(job)
        jid=job['id']; test=True; policy=None
        adapter=None; remote_completed=False; remote_attempted=False;file_receipt_saved=False
        try:
            policy=connection_policy(wid,state,self.cfg,job['kind']); test=policy['simulated']
            state,actor=self.authorize(wid,jid,token,test,policy); payload=job['payload']; kind=job['kind']
            if not test:
                adapter=self.adapter_factory(self.cfg)
                adapter.client=PermissionCheckedClient(adapter.client,lambda:self.authorize(wid,jid,token,test,policy))
            if kind=='mention':
                from .mention_notifications import check_notification, notification_text, reflect
                p,comment=check_notification(state,actor,payload,self.cfg,test)
                receipt=next((s['receipt'] for s in job.get('steps',[]) if s['key']=='notification'),None)
                if receipt is None:
                    text='測試工作區標註通知（僅模擬）' if test else notification_text(p,comment,payload,self.cfg,actor)
                    remote_attempted=not test
                    receipt={'recipient':payload['recipient_id'],'message_id':'simulated-'+jid,'simulated':True} if test else adapter.message(payload['recipient_id'],text,hashlib.sha256((wid+job['key']).encode()).hexdigest()[:32])
                    remote_completed=not test
                    receipt['simulated']=test
                    self.checkpoint(wid,jid,token,lambda s,j:j['steps'].append({'key':'notification','receipt':receipt,'at':now()}))
                def finish_mention(s,j):
                    j.update(status='succeeded',finished_at=now(),receipt=receipt,simulated=test)
                    reflect(s,j,'simulated' if test else 'succeeded',receipt=receipt)
                self.checkpoint(wid,jid,token,finish_mention)
            elif kind in ('confirmation','digest'):
                if kind=='confirmation':
                    p=find(state['projects'],payload['project_id']); issue=find(p['confirmation_issues'],payload['issue_id'])
                    if not (actor['id'] in p['issuer_ids'] or capable(actor,'issue_confirmation')): raise RemoteFailure('發出者授權已撤銷','blocked')
                    if p['pm_id']!=issue['pm_id']: raise RemoteFailure('指定PM已變更，需核對確認單','blocked')
                for recipient in payload['recipients']:
                    self.authorize(wid,jid,token,test,policy)
                    active_user(state,recipient)
                    if any(s['key']==recipient for s in job['steps']): continue
                    remote_attempted=not test
                    receipt={'recipient':recipient,'message_id':'simulated-'+jid+'-'+recipient,'simulated':True} if test else adapter.message(recipient,payload['text'],hashlib.sha256((jid+recipient).encode()).hexdigest()[:32])
                    remote_completed=not test
                    self.checkpoint(wid,jid,token,lambda s,j: j['steps'].append({'key':recipient,'receipt':receipt,'at':now()}))
                    remote_completed=False;remote_attempted=False
                def finish(s,j):
                    if kind=='confirmation':
                        p=find(s['projects'],payload['project_id']); issue=find(p['confirmation_issues'],payload['issue_id']); issue.update(status='simulated' if test else 'issued',issued_at=now(),receipts=deepcopy(j['steps']))
                        from .sop_execution import formal_issue,record_fan_out
                        # Preview/simulated issuance never hands off or fans out.
                        if formal_issue(issue) and not any(h.get('issue_id')==issue['id'] or h.get('version')==issue['version'] for h in p['handoffs']):
                            p['handoffs'].append({'issue_id':issue['id'],'version':issue['version'],'pm_id':issue['pm_id'],'at':now(),'simulated':False})
                        record_fan_out(p,issue)
                    j.update(status='succeeded',finished_at=now(),simulated=test)
                self.checkpoint(wid,jid,token,finish)
            elif kind in ('capability','training_record'):
                raise RemoteFailure('業主裁示停用：能力與訓練紀錄禁止回寫','blocked')
            elif kind=='input':
                state,actor=self.authorize(wid,jid,token,test,policy)
                i=find(state['input_revisions'],payload['input_id']); m=find(state['input_mappings'],i['mapping_id']); p=find(state['projects'],i['project_id']); n=find(p['nodes'],i['node_id'])
                if not operator(actor,p,n) or not m['enabled'] or i.get('superseded'): raise RemoteFailure('回寫授權、映射或版本已失效','blocked')
                if not test and m['base_token']!=policy['base_token']: raise RemoteFailure('回寫目的不在核定連線白名單','blocked')
                if not test and policy.get('table_id') and m['table_id']!=policy['table_id']: raise RemoteFailure('Input 登錄表不在核定目的','blocked')
                if test:receipt={'value':i['value'],'verified':True,'simulated':True}
                else:
                    from .input_registration import RegistrationAdapter
                    receipt=RegistrationAdapter(adapter).submit(i['registration_plan'],policy)
                    receipt['value']=deepcopy(i['value'])
                    remote_completed=True
                receipt.update(simulated=test,remote_mode=policy['mode'],base_token=None if test else policy['base_token'])
                def finish(s,j):
                    target=find(s['input_revisions'],i['id']); target.update(status='succeeded',receipt=receipt,finished_at=now()); find(s['input_mappings'],m['id'])['remote_value']=receipt['value']; j.update(status='succeeded',finished_at=now(),receipt=receipt,simulated=test,remote_mode=policy['mode'])
                self.checkpoint(wid,jid,token,finish)
            elif kind=='file':
                state,actor=self.authorize(wid,jid,token,test,policy)
                p=find(state['projects'],payload['project_id']); f=find(p['files'],payload['file_id'])
                if not operator(actor,p) and not any(operator(actor,p,n) and n['id']==f.get('node_id') for n in p['nodes']): raise RemoteFailure('文件上傳權已撤銷','blocked')
                path=self.upload_dir/hashlib.sha256(wid.encode()).hexdigest()/f['id']
                receipt=next((x['receipt'] for x in job['steps'] if x['key']=='upload'),None)
                if receipt and (receipt.get('simulated',False)!=test or not test and (receipt.get('remote_mode')!=policy['mode'] or receipt.get('destination_root')!=policy['drive_root'])): raise RemoteFailure('既有上傳回執的環境或目的不符，需先核對遠端檔案','blocked')
                if job.get('retry_only')=='verify_file' and not receipt:
                    raise RemoteFailure('唯讀恢復缺少原上傳回執；禁止重新上傳','outcome_unknown')
                file_receipt_saved=bool(receipt)
                if not receipt:
                    if not path.is_file(): raise RemoteFailure('本地文件不存在','blocked')
                    if test: receipt={'file_token':'simulated-'+f['id'],'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'simulated':True}
                    else:
                        parent=policy['drive_root']
                        if not parent: raise RemoteFailure('公司Drive根目錄尚未設定','blocked')
                        node=next((n for n in p['nodes'] if n['id']==f.get('node_id')),None)
                        names=[p['code']+'-'+p['id'][:8],node['name'] if node else '案件',{'input':'Input','output':'Output','evidence':'佐證'}[f['direction']]]
                        for index,name in enumerate(names):
                            self.authorize(wid,jid,token,test,policy)
                            key='folder:'+str(index)
                            stored=next((x['receipt'] for x in job['steps'] if x['key']==key),None)
                            if stored:
                                require(stored.get('parent')==parent and stored.get('name')==name
                                    and stored.get('destination_root')==policy['drive_root'] and stored.get('remote_mode')==policy['mode'],
                                    '資料夾恢復目的已變更，須核對原遠端紀錄',409)
                                parent=stored['folder_token']
                                continue
                            remote_attempted=True
                            folder_token=adapter.folder(parent,name)
                            remote_completed=True
                            folder_receipt={'parent':parent,'name':name,'folder_token':folder_token,
                                'destination_root':policy['drive_root'],'remote_mode':policy['mode']}
                            self.checkpoint(wid,jid,token,lambda s,j:j['steps'].append({'key':key,'receipt':folder_receipt,'at':now()}))
                            parent=folder_token
                            remote_completed=False;remote_attempted=False
                        self.authorize(wid,jid,token,test,policy)
                        remote_attempted=True
                        receipt=adapter.upload(path,parent,f['id']+'-'+f['name'])
                        remote_completed=True
                    receipt.update(simulated=test,remote_mode=policy['mode'],destination_root=None if test else policy['drive_root'])
                    self.checkpoint(wid,jid,token,lambda s,j:j['steps'].append({'key':'upload','receipt':receipt,'at':now()}))
                    file_receipt_saved=True
                    remote_completed=False;remote_attempted=False
                if not test:
                    self.authorize(wid,jid,token,test,policy)
                    adapter.verify_file(receipt['file_token'],receipt['sha256'])
                def finish(s,j):
                    target=find(find(s['projects'],p['id'])['files'],f['id']); target.update(remote_receipt=receipt,remote_status='simulated' if test else 'verified',remote_url='' if test else 'https://'+self.cfg.get('LARK_COMPANY_DOMAIN','yong-xiang-survey.jp.larksuite.com')+'/file/'+receipt['file_token']); j.update(status='succeeded',finished_at=now(),simulated=test,remote_mode=policy['mode'])
                self.checkpoint(wid,jid,token,finish)
            else: raise RemoteFailure('未知背景工作','blocked')
        except Exception as exc:
            if remote_completed: status='outcome_unknown'; message='遠端已回應，但本地回執未完成保存；需核實，禁止直接重送'
            elif job['kind']=='file' and remote_attempted:status='outcome_unknown';message='Drive 寫入結果尚未核實；禁止重新建立資料夾或上傳'
            elif job['kind']=='file' and file_receipt_saved:
                status='failed';message='原上傳回執已保存，但讀回未完成；重試只查驗原檔，不重新上傳'
            elif isinstance(exc,RemoteFailure): status=exc.status; message=str(exc)
            elif remote_attempted and not hasattr(exc,'status_code'): status='outcome_unknown'; message='通知送出期間發生未核實錯誤；須查核遠端結果，禁止直接重送'
            else: status='blocked'; message=getattr(exc,'detail','背景工作失敗，請檢查服務紀錄')
            retry=status=='retry' and job['attempts']<5
            def fail(s,j):
                delay=max(min(3600,60*2**job['attempts']),getattr(exc,'retry_after',0) or 0)
                j.update(status='queued' if retry else 'failed' if status=='retry' else status,error=message,next_attempt_at=(datetime.fromisoformat(now())+timedelta(seconds=delay)).isoformat())
                if job['kind']=='file' and file_receipt_saved:j['retry_only']='verify_file'
                reflect_job_status(s,j,j['status'],message)
            self.checkpoint(wid,jid,token,fail)
        finally:
            if adapter: adapter.client.close()
        return jid
