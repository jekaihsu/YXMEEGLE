"""PDF deadlines anchored to explicit, evidenced business events.

No source status, upload timestamp or daily report is inferred to be an event.
Existing contract dates and work already started are never silently rescheduled.
"""
from copy import deepcopy
from .workflow import require, find, uid, now, event, valid_date, http_url, all_tasks


RULE_VERSION='2026-09-27.1'
# key, node, signed working-day offset, task title, exact responsible role.
# '$group' means the explicitly selected recipient/executing technical group.
RULES={
    'inquiry_received':[
        ('quote_number','sales',0,'建立報價編號','quotation'),
        ('inquiry_contact','sales',1,'通知業主報價成立並確認需求與時程','pm'),
        ('quote_provide','sales',3,'提出報價並通知業主','quotation'),
    ],
    'quote_issued':[('quote_followup','sales',10,'追蹤未回簽報價狀況','quotation')],
    'contract_signed':[
        ('case_register','sales',1,'建立案件編號並製作案件回傳本','admin'),
        ('signed_contact','pm',2,'得標後聯絡業主確認進場與成果需求','pm'),
        ('confirmation_send','confirmation',5,'製作確認單並正式傳遞各單位','pm'),
    ],
    'dispatch_scheduled':[
        ('dispatch_date_contact','field',-3,'派工前聯絡業主確認派工日期','pm'),
        ('dispatch_detail_contact','field',-3,'派工前聯絡確認外業工作細節','group_owner'),
    ],
    'field_stage_completed':[('field_completion_notice','field',2,'外業完工或階段完成通知業主','pm')],
    'confirmation_received':[('group_register','$group',1,'建立工作總表並分派各組長','group_supervisor')],
    'work_completed':[('completion_confirmation','$group',3,'提交完工確認單供專案經理簽核','group_owner')],
    'billing_eligible':[('pricing_submit','pricing',3,'達成計價條件後繳交計價單','pm')],
    'delivery_submitted':[('delivery_notice','pricing',0,'通知業主成果已繳交並確認計價內容','assistant')],
}
TECHNICAL={'field','control','mapping','report'}


def _evidence(p,data,production):
    proof={}
    if data.get('evidence_id'):
        e=find(p['evidence'],data['evidence_id'],'事件佐證')
        require(e.get('status')=='accepted' and not e.get('withdrawn'),'事件佐證尚未核定或已撤下',409)
        proof['evidence_id']=e['id']
    if data.get('file_id'):
        f=find(p['files'],data['file_id'],'事件文件')
        require(not f.get('withdrawn'),'事件文件已撤下',409)
        if production and f.get('storage')=='local': require(f.get('remote_status')=='verified','事件文件尚未核實存入公司 Lark',409)
        proof['file_id']=f['id']
    if data.get('evidence_url'): proof['evidence_url']=http_url(data['evidence_url'])
    require(proof,'需提供事件文件、核定佐證或來源連結，不能以同步時間推算',422)
    return proof


def _responsible(p,node,role,override,ws):
    from .operations import active_user
    if override:
        return active_user(ws,override)['id']
    ident=node.get('owner_id') if role=='group_owner' else node.get('supervisor_id') if role=='group_supervisor' else p.get(role+'_id')
    if ident:
        active_user(ws,ident)
        return ident
    return ''


def _fixed(task):
    return bool(task.get('contract_fixed_date') or task.get('contract_due_date') or task.get('due_date_policy')=='contract_fixed')


def _started(task):
    return bool(task.get('started_at') or task.get('completed_at') or task.get('status') not in ('pending',None))


def _materialize(ws,p,record,user):
    from .operations import add_workdays, digest, invalidate
    created=[]
    for rule_id,node_key,offset,title,role in RULES[record['event_type']]:
        node_key=record.get('node_key') if node_key=='$group' else node_key
        node=next((n for n in p['nodes'] if n['key']==node_key),None)
        require(node is not None,'SOP 規則所需節點不存在',409)
        binding=record['task_bindings'].get(rule_id)
        followups=p.get('sop_followups',[])
        task=find(node['tasks'],binding,'期限對應任務') if binding else next((t for t in node['tasks']+followups if t.get('sop_rule_id')==rule_id and t.get('sop_event_stream')==record['stream_id']),None)
        calculated=add_workdays(record['date'],offset,ws['calendar'])
        provenance=dict(event_id=record['id'],event_version=record['version'],rule_id=rule_id,rule_version=RULE_VERSION,anchor_date=record['date'],workday_offset=offset,calculated_due=calculated,calendar_hash=digest(ws['calendar']),calendar_snapshot=deepcopy(ws['calendar']))
        if task is None:
            owner=_responsible(p,node,role,record['assignees'].get(rule_id),ws)
            task=dict(id=uid(),title=title,owner_id=owner,status='pending',required=True,start_date=None,due_date=calculated,original_due_date=calculated,started_at=None,completed_at=None,points=None,work_item_id=None,description='依核定 SOP 業務事件計算公司工作日期限',input='',output='',comments=[],revision=p['revision'],owner_inherited=False,sop_rule_id=rule_id,sop_event_stream=record['stream_id'],sop_owner_role=role,assignment_status='assigned' if owner else 'pending_assignment',sop_due_provenance=provenance)
            if node.get('status')=='completed':
                task.update(node_id=node['id'],completion_scope='post_completion_followup',required=False)
                p.setdefault('sop_followups',[]).append(task)
            else:
                node['tasks'].append(task); invalidate(node,'新增具佐證的 SOP 期限工作')
            created.append(task['id'])
        else:
            prior=task.get('sop_due_provenance')
            if prior!=provenance or task.get('due_date')!=calculated:
                task.setdefault('sop_deadline_history',[]).append(dict(due_date=task.get('due_date'),provenance=deepcopy(prior),at=now()))
            manual=bool(task.get('due_date') and (not prior or task['due_date']!=prior.get('calculated_due')))
            if task.get('due_date')!=calculated and (_fixed(task) or _started(task) or manual):
                for conflict in p['sop_deadline_conflicts']:
                    if conflict['task_id']==task['id'] and conflict['status']=='pending': conflict['status']='superseded'
                reason='contract_fixed' if _fixed(task) else 'work_started' if _started(task) else 'existing_manual_date'
                p['sop_deadline_conflicts'].append(dict(id=uid(),task_id=task['id'],node_id=node['id'],event_id=record['id'],event_stream=record['stream_id'],current_due=task.get('due_date'),proposed_due=calculated,provenance=provenance,status='pending',reason=reason,created_at=now()))
            else:
                task.update(due_date=calculated,sop_due_provenance=provenance,sop_rule_id=rule_id,sop_event_stream=record['stream_id'])
                if not task.get('original_due_date'): task['original_due_date']=calculated
            # Existing assignments are deliberately retained on every revision.
        if task['id'] not in record.setdefault('task_ids',[]): record['task_ids'].append(task['id'])
    return created


def recalculate_calendar(ws,user):
    """Reapply known anchors only; protected schedules become review conflicts."""
    from .operations import refresh_project_state
    for p in ws['projects']:
        current=[e for e in p.get('sop_events',[]) if not e.get('superseded_by')]
        if not current: continue
        p.setdefault('sop_deadline_conflicts',[])
        for record in current: _materialize(ws,p,record,user)
        refresh_project_state(p,ws)


def apply_sop_deadline(ws,user,body):
    from .operations import active_user, digest, lead, refresh_project_state
    action=body['action']; data=body.get('payload') or {}
    if action not in ('sop_event_record','sop_deadline_resolve','sop_followup_complete'): return False
    active_user(ws,user['id']); p=find(ws['projects'],body.get('project_id'),'案件')
    if action=='sop_followup_complete':
        from .case_cutover import require_execution
        require_execution(ws,p)
        task=find(p.get('sop_followups',[]),data.get('id'),'完成後追蹤工作')
        require(user['id']==task.get('owner_id'),'只有追蹤工作負責人可以交付',403)
        require(task['status']=='pending','追蹤工作已交付',409)
        output=data.get('output')
        require(isinstance(output,str) and output.strip(),'需提供追蹤成果',422)
        task.update(status='completed',completed_at=now(),output=output.strip())
        event(ws,user,action,p['id'],task.get('node_id'),task['id'],'交付完成後追蹤工作；原完成節點與審核保留')
        return True
    require(lead(user,p) or user['id']==p.get('admin_id'),'需案件 PM、行政或主管記錄業務事件')
    p.setdefault('sop_events',[]); p.setdefault('sop_deadline_conflicts',[])
    if action=='sop_event_record':
        kind=data.get('event_type'); require(kind in RULES,'未知 SOP 業務事件',422)
        scope=str(data.get('scope_key','')).strip(); require(scope and len(scope)<=120,'需明確事件範圍，例如報價版本或工作批次',422)
        day=valid_date(data.get('date'))
        node_key=data.get('node_key') if kind in ('confirmation_received','work_completed') else None
        if kind in ('confirmation_received','work_completed'): require(node_key in TECHNICAL,'需明確指定收件／執行組別',422)
        proof=_evidence(p,data,ws.get('environment')=='production')
        stream=digest({'type':kind,'scope':scope,'node':node_key})
        prior=next((e for e in reversed(p['sop_events']) if e['stream_id']==stream and not e.get('superseded_by')),None)
        bindings=data.get('task_bindings',deepcopy(prior['task_bindings']) if prior else {}) or {}
        assignees=data.get('assignees',deepcopy(prior['assignees']) if prior else {}) or {}
        require(isinstance(bindings,dict) and isinstance(assignees,dict),'工作對照與負責人需為規則識別對照表',422)
        keys={r[0] for r in RULES[kind]}
        require(set(bindings)<=keys and set(assignees)<=keys,'提供的規則不屬於此事件',422)
        for ident in assignees.values(): active_user(ws,ident)
        for key,ident in bindings.items():
            require(isinstance(ident,str) and ident,'任務識別格式錯誤',422)
            rule=next(r for r in RULES[kind] if r[0]==key); expected=node_key if rule[1]=='$group' else rule[1]
            require(any(n['key']==expected and t['id']==ident for n,t in all_tasks(p)),'對照任務不在規則指定節點',422)
        require(len(set(bindings.values()))==len(bindings),'同一任務不能綁定多個不同 SOP 期限規則',422)
        if prior: require(bindings==prior['task_bindings'],'更正事件日期不得偷偷變更既有工作對照',409)
        content=dict(event_type=kind,scope_key=scope,node_key=node_key,date=day,evidence=proof,task_bindings=bindings,assignees=assignees,note=str(data.get('note','')).strip())
        fingerprint=digest(content)
        if prior and prior['content_hash']==fingerprint: return True
        if prior:
            require(data.get('replaces_id')==prior['id'],'事件已存在；更正須指定目前版本，不能覆寫歷史',409)
            require(str(data.get('reason','')).strip(),'事件更正需記錄原因',422)
        else: require(not data.get('replaces_id'),'找不到可取代的事件範圍',409)
        record=dict(content,id=uid(),stream_id=stream,version=prior['version']+1 if prior else 1,content_hash=fingerprint,recorded_by=user['id'],recorded_at=now(),rule_version=RULE_VERSION,replaces_id=prior['id'] if prior else None,reason=data.get('reason',''))
        p['sop_events'].append(record)
        if prior: prior['superseded_by']=record['id']
        _materialize(ws,p,record,user)
    else:
        from .business_policy import can_business_override
        require(can_business_override(user) or user['id']==p.get('supervisor_id'),'期限衝突需案件主管核對')
        conflict=find(p['sop_deadline_conflicts'],data.get('id'),'期限衝突')
        require(conflict['status']=='pending','期限衝突已處理或有新版本',409)
        reason=str(data.get('reason','')).strip(); require(reason,'需記錄期限核對理由',422)
        resolution=data.get('resolution'); require(resolution in ('keep_existing','apply_proposed'),'期限處理方式錯誤',422)
        node=find(p['nodes'],conflict['node_id']); task=find(node['tasks']+p.get('sop_followups',[]),conflict['task_id'])
        require(task.get('due_date')==conflict['current_due'],'目前排程已變更，請重新核對事件',409)
        if resolution=='apply_proposed':
            require(not _fixed(task),'契約固定日期不能由 SOP 事件覆寫',409)
            require(not _started(task),'已開工或已完成工作需依正式變更／展延流程處理',409)
            task['due_date']=conflict['proposed_due']; task['sop_due_provenance']=deepcopy(conflict['provenance'])
        conflict.update(status='resolved',resolution=resolution,reason_note=reason,reviewed_by=user['id'],reviewed_at=now())
    refresh_project_state(p,ws)
    event(ws,user,action,p['id'],message='記錄具佐證的 SOP 事件或期限核對')
    return True
