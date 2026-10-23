"""Canonical, read-only personal Home task presentation.

Authority and readiness are recomputed from the authoritative workspace. This
module never changes assignment, dates, approvals, or task state. Unknown
reasons and forecasts stay unknown instead of being filled with guesses.
"""
from datetime import date, timedelta

from .case_cutover import execution_allowed
from .operations import delegation_valid, is_workday
from .source_lifecycle import declared, needs_review
from .workflow import is_owner, now
from .workflow_rules import activation_reasons, execution_reasons


CLOSED = ('completed', 'superseded')
ACTION_STATUSES = ('pending', 'in_progress', 'rework')


def local_work_instance(project, task):
    if project.get('source_kind') in ('demo', 'mock', 'simulation') or task.get('origin') in ('simulation', 'sop_definition', 'lark'):
        return False
    if not task.get('owner_id') or (task.get('source_identity') or {}).get('table_id') in ('tblcPZPmezkyeVb7', 'tblsoyGcC6K5AipF'):
        return False
    from .home_queues import _valid_timestamp
    history = task.get('assignment_history')
    latest = history[-1] if isinstance(history, list) and history and isinstance(history[-1], dict) else {}
    after = latest.get('after')
    explicitly_assigned = bool(latest.get('actor_id') and _valid_timestamp(latest.get('at'))
                               and isinstance(after, dict) and after.get('owner_id') == task['owner_id'])
    template = task.get('owner_inherited') or task.get('sop_definition_version') or task.get('sop_task_key') or task.get('source_identity')
    return explicitly_assigned or not template


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat() if value else None
    except ValueError:
        return None


def _person(ws, ident):
    return next((u.get('name') or ident for u in ws.get('users', []) if u.get('id') == ident), None)


def _proxy(ws, project, task, user):
    if not user or not user.get('active', True) or task.get('owner_id') == user.get('id'):
        return None
    principal = next((u for u in ws.get('users', []) if u.get('id') == task.get('owner_id') and u.get('active', True)), None)
    if not principal:
        return None
    today = now()[:10]
    for d in ws.get('delegations', []):
        if (d.get('project_id') != project.get('id') or d.get('principal_id') != principal['id']
                or d.get('delegate_id') != user['id'] or d.get('seat') != 'owner' or d.get('scope') != 'tasks'
                or task.get('id') not in d.get('task_ids', []) or d.get('status') != 'active'
                or not d.get('start_date', '') <= today <= d.get('end_date', '')
                or not delegation_valid(ws, d, at_use=True)):
            continue
        return dict(delegation_id=d.get('id'), principal_id=principal['id'], principal_name=principal.get('name') or principal['id'],
                    delegate_id=user['id'], start_date=d['start_date'], end_date=d['end_date'],
                    basis={'supervisor':'主管核定代理','approval':'已驗證核准代理'}.get(d.get('source'),'代理依據待核對'),
                    source=d.get('source'))
    return None


def _prerequisites(ws, project, task):
    tasks={item.get('id'):item for node in project.get('nodes', []) for item in node.get('tasks', [])}
    result=[]
    for ident in dict.fromkeys(x for x in task.get('input_task_ids', []) if isinstance(x, str) and x):
        upstream=tasks.get(ident)
        if upstream is None:
            result.append(dict(task_id=ident, title=None, owner_id=None, owner_name=None, status=None,
                               output_present=False, source_batch_id=None, missing=True, ready=False))
        else:
            owner=upstream.get('owner_id')
            output_present=bool(str(upstream.get('output') or '').strip())
            result.append(dict(task_id=ident, title=upstream.get('title') or None, owner_id=owner,
                               owner_name=_person(ws, owner), status=upstream.get('status'),
                               output_present=output_present, source_batch_id=upstream.get('source_batch_id'), missing=False,
                               ready=upstream.get('status')=='completed' and output_present))
    return result


def _task_event(ws, project, node, task, action):
    rows=(event for event in ws.get('events', []) if event.get('action') == action
          and event.get('project_id') == project.get('id') and event.get('node_id') == node.get('id')
          and event.get('task_id') == task.get('id') and str(event.get('message') or '').strip())
    return max(rows, key=lambda event:event.get('created_at') or '', default=None)


def _pause(ws, project, node, task):
    if project.get('execution_status') != 'paused' and task.get('status') != 'paused':
        return None
    event=_task_event(ws,project,node,task,'task_pause_for_change') if task.get('status')=='paused' else None
    if event:
        return dict(reason=event['message'],source='task_pause_event',event_id=event.get('id'))
    approval=next((a for a in ws.get('approvals', []) if a.get('project_id')==project.get('id')
        and a.get('type')=='change' and a.get('frozen') and task.get('id') in a.get('task_ids', [])
        and str(a.get('reason') or '').strip()),None)
    if approval and task.get('status')=='paused':
        return dict(reason=approval['reason'],source='frozen_change_approval',event_id=None,approval_id=approval.get('id'))
    if declared(project)=='中止':
        return dict(reason='來源案件已中止',source='verified_lifecycle',event_id=None)
    if needs_review(project):
        return dict(reason='來源案件狀態待核對',source='lifecycle_verification',event_id=None)
    return dict(reason=None,source='unavailable',event_id=None)


def _correction(ws,project,node,task):
    if task.get('status')!='rework' and node.get('status')!='rework':
        return None
    event=_task_event(ws,project,node,task,'task_return') if task.get('status')=='rework' else None
    if event and event['message']!='task_return':
        return dict(reason=event['message'],source='task_return_event',event_id=event.get('id'))
    # A returned node review is node-scoped; label that scope rather than
    # pretending its vote was a direct task return.
    cycles=node.get('review_cycles') or []
    current=cycles[-1] if cycles else None
    if node.get('status')=='rework' and current and current.get('status')=='returned':
        votes=[vote for vote in current.get('votes', [])
               if vote.get('result')=='returned' and str(vote.get('reason') or '').strip()]
        if votes:
            latest=max(votes,key=lambda v:v.get('created_at') or '')
            return dict(reason=f"節點審核退回：{latest['reason']}",source='node_review_vote',event_id=None)
    return dict(reason=None,source='unavailable',event_id=None)


def _risk(ws,project,task,as_of):
    current=_day(task.get('due_date')); original=_day(task.get('original_due_date')); as_day=_day(as_of)
    calendar_days=workdays=None; workday_status='unavailable'
    if current and as_day and current<as_day:
        start,end=date.fromisoformat(current),date.fromisoformat(as_day)
        calendar_days=(end-start).days
        cal=ws.get('calendar')
        if (calendar_days<=36525 and isinstance(cal,dict) and isinstance(cal.get('holidays'),list)
                and isinstance(cal.get('workdays'),list)
                and all(_day(value)==value for field in ('holidays','workdays') for value in cal[field])):
            try:
                # Count the workdays after the deadline, through the data date.
                workdays=sum(is_workday(start+timedelta(days=offset),cal) for offset in range(1,calendar_days+1))
                workday_status='workspace_calendar'
            except (TypeError,ValueError):
                workdays=None
    return dict(original_due_date=original,current_due_date=current,estimated_due_date=None,
                overdue_calendar_days=calendar_days,overdue_workdays=workdays,workday_status=workday_status,
                disposition='paused' if project.get('execution_status')=='paused' or task.get('status')=='paused' else task.get('status'),
                pause_clock='unavailable',delivery_impact='unavailable')


def _delivery_links(project,task):
    """Report exact stored identifiers, never infer schedule or delivery impact."""
    links=[]
    for batch in project.get('delivery_batches', []):
        snapshots=batch.get('task_snapshots') or []
        if any(item.get('id')==task.get('id') for item in snapshots):
            basis='task_snapshot_id'
        elif task.get('id') in batch.get('work_item_ids', []):
            basis='task_id'
        elif task.get('work_item_id') and task['work_item_id'] in batch.get('work_item_ids', []):
            basis='work_item_id'
        else:
            continue
        links.append(dict(batch_id=batch.get('id'),status=batch.get('status'),match_basis=basis))
    return links


def build_home_task(ws,p,n,t,user,as_of):
    """Return authority, blockers and complete presentation for one task.

    ``kind`` is one navigation lane. Proxy, prerequisites and risk remain
    independent facts so a paused or returned proxy retains its basis.
    """
    proxy=_proxy(ws,p,t,user)
    assigned=bool(user and user.get('active',True) and (t.get('owner_id')==user.get('id') or proxy))
    can_execute=bool(user and is_owner(user,t,ws,project=p))
    execution=execution_reasons(ws,p,n,t)
    activation=activation_reasons(ws,p,n,t,clock=as_of) if t.get('status')=='pending' else []
    if not assigned:
        return dict(assigned=False,can_execute=can_execute,execution_blockers=execution,
                    activation_blockers=activation,detail=None)
    prerequisites=_prerequisites(ws,p,t)
    pause=_pause(ws,p,n,t); correction=_correction(ws,p,n,t)
    as_day=_day(as_of); start=_day(t.get('start_date'))
    future=bool(start and as_day and start>as_day)
    actionable=bool(assigned and can_execute and execution_allowed(ws,p) and p.get('execution_status')!='paused'
                    and p.get('case_type')!='intake' and t.get('status') in ACTION_STATUSES
                    and not execution and not activation and not future)
    kind=reason=None
    if assigned and t.get('status') not in CLOSED:
        if pause:
            kind,reason='paused',pause['reason'] or '暫停原因待核對'
        elif correction:
            kind,reason='correction',correction['reason'] or '退回原因未記錄'
        elif proxy:
            kind,reason='proxy',f"代理 {proxy['principal_name']}；{proxy['start_date']} 至 {proxy['end_date']}；{proxy['basis'] or '代理依據待核對'}"
        elif future:
            kind,reason='upcoming',f'排定 {start} 開始'
        elif execution or activation or not can_execute or not execution_allowed(ws,p):
            kind,reason='prerequisite',(execution or activation or ['執行資格或案件歸屬待核對'])[0]
        elif _day(t.get('due_date')) and as_day and _day(t.get('due_date'))>as_day:
            kind,reason='upcoming',f"預計 {_day(t.get('due_date'))} 到期"
    blockers=list(dict.fromkeys([*execution,*activation]))
    detail=dict(task_id=t.get('id'),project_id=p.get('id'),project_code=p.get('code'),node_id=n.get('id'),
                title=t.get('title') or '未命名任務',actionable=actionable,kind=kind,reason=reason,blockers=blockers,
                proxy=proxy,prerequisites=prerequisites,pause=pause,correction=correction,risk=_risk(ws,p,t,as_of),
                delivery_links=_delivery_links(p,t))
    return dict(assigned=assigned,can_execute=can_execute,execution_blockers=execution,
                activation_blockers=activation,detail=detail)


def build_sop_home_task(project, task, links, user, users, writes_enabled):
    from .sop_import.domain import Applicability, Lifecycle
    roles = [role for role, ident in task.participants.items() if ident == user['id']]
    executor = task.participants.get('executor')
    person = next((u for u in users if u['id'] == executor), {})
    blockers = []
    if not writes_enabled:
        blockers.append('SOP 任務暫停寫入')
    if task.applicability != Applicability.APPLICABLE:
        blockers.append('需先確認任務適用')
    if task.state == Lifecycle.BLOCKED:
        blockers.append('任務受阻，請先繼續或退回待處理')
    status = {'pending': 'todo', 'archived': 'cancelled'}.get(task.state.value, task.state.value)
    if task.applicability == Applicability.NOT_APPLICABLE and task.state != Lifecycle.ARCHIVED:
        status = 'skipped'
    return {'id': 'sop_task/' + task.id, 'kind': 'sop_task', 'origin': 'sop_local', 'source': None,
            'case': {**{k: project.get(k) for k in ('id', 'code', 'name')}, 'relation_state': 'verified'},
            'node_key': links[0].node_key if links else None, 'node_keys': [l.node_key for l in links],
            'title': task.title, 'status': status, 'source_status': None, 'assignment_state': 'assigned',
            'assignment_roles': roles, 'applicability': task.applicability.value,
            'assignees': [{'id': executor, 'name': person.get('name') or executor, 'avatar_url': None}] if executor else [],
            'assigned_by': None, 'deadline': task.local.get('due_date'), 'next_due': None,
            'original_deadline': None, 'deadline_basis': 'sop_task',
            'can_execute': 'executor' in roles and not blockers and task.state in {Lifecycle.PENDING, Lifecycle.IN_PROGRESS},
            'blocked_reasons': blockers, 'detail': None, 'result': task.local.get('result'),
            'target': {'view': 'project', 'project': project['id'], 'tab': 'flow',
                       'task': task.id, 'task_source': 'sop_local', 'section': 'assigned-sop'},
            '_mine': 'executor' in roles, '_review': bool(set(roles) & {'checker', 'confirmer'})}
