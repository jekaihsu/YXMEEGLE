"""Company-readable business counters from the existing safe workspace projection."""
from collections import Counter,defaultdict
from datetime import date,datetime,timezone
from zoneinfo import ZoneInfo

GROUPS={'field':'外業組','control':'控制組','mapping':'圖資組','report':'報告組'}

def verified_native_pending(item):
    """Never turn a draft, simulated item, or stale unverified receipt into a pending review."""
    receipt=item.get('native_receipt') or {};binding=item.get('native_binding') or {}
    if item.get('simulated') or receipt.get('simulated') or binding.get('verification_failed_at'):return False
    if not binding.get('attempted') or receipt.get('binding_verified') is not True:return False
    ident=receipt.get('instance_code')
    if not ident or ident!=binding.get('instance_code'):return False
    if receipt.get('binding_hash') and receipt['binding_hash']!=binding.get('binding_hash'):return False
    # Cancellation can checkpoint a terminal binding receipt before its outer
    # business projection has caught up. Do not show that previous PENDING.
    bound=binding.get('receipt') or {}
    if bound.get('external_status') in ('APPROVED','REJECTED','CANCELED','DELETED','UNVERIFIED'):return False
    return receipt.get('external_status')=='PENDING'

def actual_date(value):
    if not isinstance(value,str):return None
    try:
        parsed=date.fromisoformat(value)
        return parsed if parsed.isoformat()==value else None
    except ValueError:return None

UNVERIFIED='待核對'


def overview(workspace,*,offset=0,limit=100,q='',group='',source_status='',attention='',lifecycle='',clock=None):
    clock=clock or datetime.now(timezone.utc);today=clock.astimezone(ZoneInfo('Asia/Taipei')).date()
    totals=Counter(cases=0,confirmed_cases=0,intake_records=0,workbench_cases=0,tasks_total=0,tasks_completed=0,tasks_overdue=0,
                   pending_local_reviews=0,pending_native_reviews=0,deliveries_confirmed=0)
    source_counts=Counter();execution_counts=Counter();lifecycle_state_counts=Counter();lifecycle_counts=Counter();missing=Counter(task_due_date=0,group=0,source_status=0)
    groups=defaultdict(lambda:Counter(cases=0,tasks_total=0,tasks_completed=0,tasks_overdue=0))
    rows=[]
    native=Counter();seen_native=set()
    for collection in ('approvals','node_skip_requests','financial_requests'):
        for item in workspace.get(collection,[]):
            receipt=item.get('native_receipt') or {}
            binding=item.get('native_binding') or {}
            ident=receipt.get('instance_code') or binding.get('instance_code')
            if ident and ident in seen_native:continue
            if verified_native_pending(item):
                native[item.get('project_id')]+=1
                if ident:seen_native.add(ident)
    for p in workspace.get('projects',[]):
        # Meegle-only legacy objects without a current Lark source are not company source cases.
        if p.get('source_kind')!='lark':continue
        status=p.get('source_status') or '未提供';execution=p.get('execution_status') or 'pending'
        totals['cases']+=1;source_counts[status]+=1;execution_counts[execution]+=1
        totals['confirmed_cases']+=int(p.get('case_type')=='formal')
        totals['intake_records']+=int(p.get('case_type')=='intake')
        if not p.get('source_status'):missing['source_status']+=1
        raw_lifecycle=p.get('source_lifecycle') or {}
        entry={'relationship':raw_lifecycle.get('relationship') or ('待確認單' if p.get('case_type')=='intake' else '已關聯確認單'),
                   'state':raw_lifecycle.get('state') or 'needs_verification','canonical':raw_lifecycle.get('canonical'),
                   'reasons':raw_lifecycle.get('reasons') or ['unreviewed']}
        entry['quote_workflow']=[{'raw':w.get('raw',''),'kind':w.get('kind','other')} for w in raw_lifecycle.get('quote_workflow') or []]
        lifecycle_state_counts[entry['state']]+=1;lifecycle_counts[entry['canonical'] or UNVERIFIED]+=1
        runnable=p.get('execution_allowed') is True
        totals['workbench_cases']+=int(runnable)
        project_groups=set();counts=Counter(tasks_total=0,tasks_completed=0,tasks_overdue=0,pending_local_reviews=0,deliveries_confirmed=0)
        for node in p.get('nodes',[]):
            name=node.get('department') or GROUPS.get(node.get('key'))
            if not runnable:continue
            if name:project_groups.add(name)
            from .policy import FINANCIAL
            from .sop_contracts import disabled_task
            if node.get('key') not in FINANCIAL:
                counts['pending_local_reviews']+=sum(c.get('status')=='pending' and not c.get('historical_scope') for c in node.get('review_cycles',[]))
            for task in node.get('tasks',[]):
                if task.get('status') in ('superseded','not_applicable','skipped','cancelled','canceled'):continue
                # SOP-disabled tasks stay as history but are not current workload.
                if disabled_task(task):continue
                complete=task.get('status')=='completed';due=actual_date(task.get('due_date'))
                overdue=not complete and due is not None and due<today
                counts['tasks_total']+=1;counts['tasks_completed']+=int(complete);counts['tasks_overdue']+=int(overdue)
                if not complete and due is None:missing['task_due_date']+=1
                if name:
                    groups[name]['tasks_total']+=1;groups[name]['tasks_completed']+=int(complete);groups[name]['tasks_overdue']+=int(overdue)
        # Accepted, nonwithdrawn delivery records are real workbench history,
        # even if the source case is currently reference-only.
        counts['deliveries_confirmed']=sum(e.get('status')=='accepted' and not e.get('withdrawn') for e in p.get('evidence',[]))
        if not project_groups:missing['group']+=1
        for name in project_groups:groups[name]['cases']+=1
        counts['pending_native_reviews']=native[p['id']]
        totals.update(counts)
        rows.append({'id':p['id'],'code':p.get('code',''),'name':p.get('name',''),'case_type':p.get('case_type','unknown'),'group':'、'.join(sorted(project_groups)) or '未分組',
                     'groups':sorted(project_groups),'source_status':status,'source_lifecycle':entry,'execution_status':execution,
                     'workbench_execution_enabled':runnable,**dict(counts)})
    filtered=[r for r in rows if (not q or q.casefold() in (r['code']+' '+r['name']).casefold())
        and (not group or group in r['groups'] or group=='未分組' and not r['groups'])
        and (not source_status or r['source_status']==source_status)
        and (not lifecycle or (r['source_lifecycle']['canonical'] or UNVERIFIED)==lifecycle)
        and (not attention or attention=='overdue' and r['tasks_overdue']>0
             or attention=='review' and r['pending_local_reviews']+r['pending_native_reviews']>0)]
    filtered.sort(key=lambda r:(r['code'],r['id']))
    source=workspace.get('source_status') or {}
    return {'as_of':today.isoformat(),'checked_at':clock.isoformat(),'date_basis':'Asia/Taipei; actual task due_date only',
        'source':{'status':source.get('status','missing'),'last_success_at':source.get('last_sync'),
                  'mapping_status':source.get('mapping_status','unknown')},
        'totals':{**dict(totals),'source_status_counts':dict(source_counts),'execution_status_counts':dict(execution_counts),'lifecycle_state_counts':dict(lifecycle_state_counts),'lifecycle_counts':dict(lifecycle_counts)},
        'missing':dict(missing),'groups':[{'group':key,**dict(value)} for key,value in sorted(groups.items())],
        'cases':filtered[offset:offset+limit],'pagination':{'offset':offset,'limit':limit,'total':len(filtered),'has_more':offset+limit<len(filtered)},
        'metric_scope':'task progress counts only executable workbench cases; source business status is independent'}
