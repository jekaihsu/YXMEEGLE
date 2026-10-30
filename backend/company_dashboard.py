"""Company-readable business counters from the existing safe workspace projection."""
from collections import Counter,defaultdict
from datetime import date,datetime,timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from zoneinfo import ZoneInfo
from .source_lifecycle import declared
from .case_cutover import admission_fields

# Keep files/evidence, finance, review cycles and authority collections: public_ws
# recomputes their validity before overview reads the resulting counters.
READ_OMIT_KINDS=('events','project_comments','project_daily_reports','work_schedules',
                 'recurring','daily_unmatched','daily_reviews','source_work_items')

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

def numeric_value(value):
    if value is None or isinstance(value, bool): return None
    try:
        number = Decimal(str(value).strip().replace(',', ''))
        return number if number.is_finite() else None
    except InvalidOperation: return None


def source_instant(value):
    if value is None or isinstance(value, bool): return None
    if isinstance(value, (int, float)) or isinstance(value, str) and value.isdigit() and len(value) == 13:
        try: return datetime.fromtimestamp(float(value) / 1000, timezone.utc)
        except (ValueError, OverflowError, OSError): return None
    if not isinstance(value, str): return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo('Asia/Taipei'))
    except ValueError: return None


def actual_date(value):
    parsed = source_instant(value)
    return parsed.astimezone(ZoneInfo('Asia/Taipei')).date() if parsed else None


UNVERIFIED='待核對'
DEADLINE_BUCKETS=('intake','formal_executing','formal_unverified','other')
CLOSED_TASK=('superseded','not_applicable','skipped','cancelled','canceled')


def deadline_bucket(project,relationship):
    """Group past-due stored task dates by case relationship and status, without inferring date provenance."""
    if relationship=='待確認單' or project.get('case_type')=='intake':return 'intake'
    return {'執行中':'formal_executing','來源狀態待核對':'formal_unverified'}.get(project.get('source_status'),'other')


def source_overdue(project,today):
    """Count open, dated, past-due tasks on a case the workbench does not run; date origin is unknown."""
    from .sop_contracts import disabled_task
    count=0
    for node in project.get('nodes',[]):
        for task in node.get('tasks',[]):
            if task.get('status') in CLOSED_TASK or task.get('status')=='completed' or disabled_task(task):continue
            due=actual_date(task.get('due_date'))
            count+=int(due is not None and due<today)
    return count


def overview(workspace,*,offset=0,limit=100,q='',group='',source_status='',attention='',lifecycle='',clock=None,sort='urgency',direction='asc',owner='',complete_read=False):
    # complete_read is the route's complete READ_OMIT_KINDS projection; source
    # truncation and source partial flags still determine business completeness.
    if sort not in ('urgency','code','name','due') or direction not in ('asc','desc'): raise ValueError('unsupported company sort')
    clock=clock or datetime.now(timezone.utc);today=clock.astimezone(ZoneInfo('Asia/Taipei')).date()
    totals=Counter(cases=0,confirmed_cases=0,intake_records=0,workbench_cases=0,tasks_total=0,tasks_completed=0,tasks_overdue=0,
                   pending_local_reviews=0,pending_native_reviews=0,deliveries_confirmed=0)
    source_counts=Counter();execution_counts=Counter();lifecycle_state_counts=Counter();lifecycle_counts=Counter();missing=Counter(task_due_date=0,group=0,source_status=0)
    groups=defaultdict(lambda:Counter(cases=0,tasks_total=0,tasks_completed=0,tasks_overdue=0))
    rows=[]
    native=Counter();seen_native=set();deadline_cases=Counter();deadline_tasks=Counter()
    for collection in ('approvals','node_skip_requests','financial_requests'):
        for item in workspace.get(collection,[]):
            if collection=='approvals' and item.get('kind') in ('change','extension'): continue
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
        verified=declared(p)
        reasons=list(raw_lifecycle.get('reasons') or [])
        entry={'relationship':raw_lifecycle.get('relationship') or ('待確認單' if p.get('case_type')=='intake' else '已關聯確認單'),
                   'state':'mapped' if verified else 'needs_verification','canonical':verified,
                   'reasons':reasons if verified is None and reasons else [] if verified else ['unreviewed'],
                   'source_canonical':raw_lifecycle.get('canonical')}
        entry['quote_workflow']=[{'raw':w.get('raw',''),'kind':w.get('kind','other')} for w in raw_lifecycle.get('quote_workflow') or []]
        lifecycle_state_counts[entry['state']]+=1;lifecycle_counts[entry['canonical'] or UNVERIFIED]+=1
        runnable=p.get('execution_allowed') is True
        totals['workbench_cases']+=int(runnable)
        if not runnable:
            late=source_overdue(p,today);key=deadline_bucket(p,entry['relationship'])
            deadline_cases[key]+=int(late>0);deadline_tasks[key]+=late
        next_dates=[]
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
                if not complete and due is not None: next_dates.append(due)
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
                     'pm_id':p.get('pm_id'),'next_due':min(next_dates).isoformat() if next_dates else None,'deadline_basis':'local_workflow',
                     'groups':sorted(project_groups),'source_status':status,'source_lifecycle':entry,'execution_status':execution,
                     **admission_fields(p,runnable),
                     'workbench_execution_enabled':runnable,**dict(counts)})
    filtered=[r for r in rows if (not q or q.casefold() in (r['code']+' '+r['name']).casefold())
        and (not group or group in r['groups'] or group=='未分組' and not r['groups'])
        and (not owner or r['pm_id']==owner)
        and (not source_status or r['source_status']==source_status)
        and (not lifecycle or (r['source_lifecycle']['canonical'] or UNVERIFIED)==lifecycle)
        and (not attention or attention=='overdue' and r['tasks_overdue']>0
             or attention=='review' and r['pending_local_reviews']+r['pending_native_reviews']>0)]
    filtered.sort(key=lambda r:(r['code'],r['id']))
    if sort == 'urgency':
        filtered.sort(key=lambda r:(-int(r['tasks_overdue']>0),-int(r['pending_local_reviews']+r['pending_native_reviews']>0),
                                   -int(r['execution_status'] in ('paused','blocked')),
                                   r['next_due'] is None,r['next_due'] or '',r['code'],r['id']))
    elif sort == 'due':
        known=[r for r in filtered if r['next_due'] is not None]
        known.sort(key=lambda r:r['next_due'],reverse=direction=='desc')
        filtered=known+[r for r in filtered if r['next_due'] is None]
    else:
        filtered.sort(key=lambda r:r[sort].casefold(),reverse=direction=='desc')
    source=workspace.get('source_status') or {}
    complete=source.get('status')=='ready' and not source.get('partial') and not source.get('truncated') and (not workspace.get('_partial') or complete_read)
    snapshot_version=hashlib.sha256(json.dumps([workspace.get('version'),source.get('last_sync'),rows],sort_keys=True,default=str).encode()).hexdigest()[:24]
    return {'as_of':today.isoformat(),'checked_at':clock.isoformat(),'date_basis':'Asia/Taipei; actual task due_date only',
        'source':{'status':source.get('status','missing'),'last_success_at':source.get('last_sync'),
                  'mapping_status':source.get('mapping_status','unknown')},
        'totals':{**dict(totals),'source_status_counts':dict(source_counts),'execution_status_counts':dict(execution_counts),'lifecycle_state_counts':dict(lifecycle_state_counts),'lifecycle_counts':dict(lifecycle_counts)},
        'source_deadlines':{'cases':sum(deadline_cases.values()),'tasks':sum(deadline_tasks.values()),
            'buckets':[{'key':key,'cases':deadline_cases[key],'tasks':deadline_tasks[key]} for key in DEADLINE_BUCKETS]},
        'missing':dict(missing),'groups':[{'group':key,**dict(value)} for key,value in sorted(groups.items())],
        'count_scope':'authorized_workspace_snapshot','filter_scope':'matching_loaded_source_cases','complete':complete,
        'snapshot_version':snapshot_version,'source_as_of':source.get('last_sync'),
        'query_echo':{'q':q,'group':group,'source_status':source_status,'attention':attention,'lifecycle':lifecycle,'sort':sort,'direction':direction,'owner':owner},
        'total_count':len(filtered) if complete else None,'loaded_count':len(filtered),
        'cases':filtered[offset:offset+limit],'pagination':{'offset':offset,'limit':limit,'total':len(filtered),'has_more':offset+limit<len(filtered)},
        'metric_scope':'task progress counts only executable workbench cases; source business status is independent'}
