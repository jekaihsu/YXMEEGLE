"""Explicit case ownership during the Meegle -> workbench company cutover.

Source discovery is never permission to execute a case. Unclassified formal
cases remain readable, with their existing results/history retained.
"""
from copy import deepcopy
from .workflow import require,find,now,event

SYSTEMS=frozenset({'pending','meegle','workbench'})
LABELS={'pending':'待確認歸屬','meegle':'Meegle 舊案（唯讀參考）','workbench':'工作台執行'}


def execution_system(project):
    value=project.get('execution_system')
    return value if value in SYSTEMS else 'pending'


def isolated(ws):
    return ws.get('environment') in ('demo','test')


def execution_allowed(ws,project):
    # Missing environment must not grant production business authority.
    return isolated(ws) or project.get('case_visibility')!='excluded_history' and execution_system(project)=='workbench'


def require_execution(ws,project):
    system=execution_system(project)
    require(execution_allowed(ws,project),
            '此案仍在 Meegle 執行，工作台僅供唯讀參考' if system=='meegle' else
            '案件歸屬尚未核定，請管理員確認由工作台執行後再操作',409)


def initialize_execution_system(ws):
    """Idempotent formal migration; no case or task history is removed."""
    if isolated(ws):return []
    changed=[]
    for project in ws.get('projects',[]):
        if project.get('execution_system') in SYSTEMS:continue
        project['execution_system']='pending'
        project['execution_assignment']={'basis':'unclassified_source_or_existing_case',
            'recorded_by':'system:cutover','recorded_at':now(),
            'reason':'來源讀入不代表新案；等待管理員核定執行系統'}
        changed.append(project['id'])
    if changed:
        event(ws,{'id':'system:cutover'},'case_execution_initialize',
              message=f'{len(changed)} 個案件標記待確認歸屬；成果與歷史保留')
    return changed


def assign_execution(ws,actor,project_id,target,reason):
    """Administrator decision, separate from ordinary business case actions."""
    require(actor.get('active',True) and actor.get('role')=='manager','需管理員核定案件歸屬',403)
    require(isinstance(target,str) and target in SYSTEMS,'執行系統須為待確認、Meegle 或工作台',422)
    require(isinstance(reason,str) and bool(reason.strip()) and len(reason.strip())<=1000,
            '請填寫 1 至 1000 字的歸屬核定原因',422)
    project=find(ws.get('projects',[]),project_id,'案件')
    require(project.get('case_visibility')!='excluded_history','舊案已隔離保存，不可改派為工作台新案',409)
    previous=execution_system(project)
    decision={'from':previous,'to':target,'recorded_by':actor['id'],
              'recorded_at':now(),'reason':reason.strip(),'basis':'administrator_decision'}
    project['execution_system']=target
    project['execution_assignment']=deepcopy(decision)
    project.setdefault('execution_assignment_history',[]).append(deepcopy(decision))
    event(ws,actor,'case_execution_assign',project_id,
          message=f'案件歸屬：{LABELS[previous]} → {LABELS[target]}；{reason.strip()}')
    return decision


def reconcile_merged_execution(ws,target,candidates):
    """Identity reconciliation cannot silently move Meegle work to workbench."""
    decisions={p['id']:execution_system(p) for p in candidates}
    if isolated(ws) or len(set(decisions.values()))<=1:return False
    target['execution_system']='pending'
    target['execution_assignment']={'basis':'merged_ownership_requires_review','recorded_by':'system:cutover',
        'recorded_at':now(),'reason':'合併來源案件的執行歸屬不同，需管理員重新核定','previous_decisions':decisions}
    event(ws,{'id':'system:cutover'},'case_execution_merge_review',target['id'],
          message='來源案件合併的執行歸屬不同，已停留待確認；所有原紀錄保留')
    return True


def project_execution_view(ws,project):
    system=execution_system(project)
    return {'execution_system':system,'execution_system_label':LABELS[system],
            'execution_allowed':execution_allowed(ws,project),
            'execution_readonly_reason':None if execution_allowed(ws,project) else
                ('舊案留在 Meegle 完成' if system=='meegle' else '等待管理員核定案件歸屬')}


def admission_fields(project,allowed):
    """Read-only admission facts for list surfaces; never grants or changes authority."""
    system=execution_system(project)
    reason=None if allowed else project.get('execution_readonly_reason') or (
        '舊案留在 Meegle 完成' if system=='meegle' else '等待管理員核定案件歸屬')
    return {'execution_system':system,'execution_system_label':LABELS[system],
            'execution_readonly_reason':reason,'case_visibility':project.get('case_visibility')}


def resolve_action_projects(ws,body):
    """Resolve stored ownership, never trust supplied project for indirect actions."""
    action=body.get('action',''); data=body.get('payload') or {}
    pid=body.get('project_id'); owners=[]
    references={
        'input_mapping_disable':('input_mappings','id'),
        'input_draft':('input_mappings','mapping_id'),
        'input_submit':('input_revisions','id'),
        'sop_apply':('sop_requests','id'),
        'delegation_revoke':('delegations','id'),
        'recurring_complete':('recurring','id'),
        'recurring_review':('recurring','id'),
        'daily_approve':('daily_reviews','id'),
        'handover_approve':('handover_requests','id'),
        'handover_accept':('handover_requests','id'),
    }
    if action.startswith('approval_') and action!='approval_create' or action=='change_resume':
        references[action]=('approvals','approval_id')
    if action.startswith('node_skip_') and action!='node_skip_create':
        references[action]=('node_skip_requests','id')
    if action in references:
        collection,key=references[action]
        item=find(ws.get(collection,[]),data.get(key),'操作紀錄')
        owners.append(item.get('project_id'))
        require(bool(owners[-1]),'操作紀錄缺少案件歸屬，請先核對',409)
    if action=='job_retry':
        job=find(ws.get('jobs',[]),data.get('id'),'背景工作')
        job_pid=(job.get('payload') or {}).get('project_id')
        if job_pid:owners.append(job_pid)
        else:require(job.get('kind') not in ('input','file','mention','confirmation','approval'),
                     '背景工作缺少案件歸屬，請先核對',409)
    require(not pid or not owners or all(owner==pid for owner in owners),
            '指定案件與操作紀錄的實際歸屬不一致',409)
    if action=='task_batch_complete':
        items=data.get('items')
        require(isinstance(items,list) and 0<len(items)<=50,'請選擇 1 至 50 項本人工作',422)
        for item in items:
            require(isinstance(item,dict) and bool(item.get('project_id')),'批次項目缺少案件識別',422)
            owners.append(item['project_id'])
    if pid:owners.append(pid)
    return [find(ws.get('projects',[]),owner,'案件') for owner in dict.fromkeys(owners)]
