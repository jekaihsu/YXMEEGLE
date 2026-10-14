"""Pure projection of a case snapshot into the public JSON shape."""
from .domain import (
    CHAIN, NODE_DEPARTMENTS, NODE_LABELS, NodeKey, NodeStatus, TaskFacts, TaskStatus, derive_chain,
    node_permissions, progress, summarize, task_counts, task_permissions)
from .lark_table import CaseSnapshot, NodeRow, TaskRow, iso_time
from .operations import facts_of, mirror

NO_ACTIONS = {'claim': False, 'assign': False, 'complete': False, 'approve': False, 'reject': False,
              'create_task': False}


def _user(ref):
    return ref.public() if ref else None


def node_warnings(key, row: NodeRow | None, duplicates, status, tasks, now_ms):
    warnings = []
    if duplicates:
        warnings.append('duplicate_assignment_key')
    if row is None:
        return warnings
    if row.status == NodeStatus.DONE.value and not row.approved:
        warnings.append('unapproved_completion')
    expected = mirror(row, status, task_counts(t.status for t in tasks), now_ms).get('status')
    if expected and row.status != expected:
        warnings.append('lark_status_drift')
    if status is NodeStatus.NOT_STARTED and any(t.status is TaskStatus.IN_PROGRESS for t in tasks):
        warnings.append('previous_node_not_done')
    return warnings


def node_view(key: NodeKey, snapshot: CaseSnapshot, status: NodeStatus, now_ms):
    rows = snapshot.rows.get(key, ())
    row = rows[0] if len(rows) == 1 else None
    tasks = snapshot.node_tasks(key)
    counts = task_counts(t.status for t in tasks)
    live_deadlines = [t.deadline for t in tasks if t.deadline and t.status is not TaskStatus.CANCELLED]
    view = {
        'key': key.value, 'label': NODE_LABELS[key], 'departments': list(NODE_DEPARTMENTS[key]),
        'record_id': row.record_id if row else None, 'revision': row.revision if row else None,
        'status': (row.status or None) if row else None, 'derived_status': status.value,
        'tasks': {'done': counts.done, 'total': counts.total}, 'progress': progress(status, counts),
        'owners': [u.public() for u in row.owners] if row else [],
        'assignment_method': (row.method or None) if row else None,
        'assigned_by': _user(row and row.assigned_by), 'approver': _user(row and row.approved and row.approver),
        'approved_at': iso_time(row.approved_at) if row and row.approved else None,
        'reject_reason': row.reject_reason if row and row.rejected else None,
        'started_at': iso_time(row and row.started_at), 'finished_at': iso_time(row and row.finished_at),
        'deadline': max(live_deadlines) if live_deadlines else None,
        'warnings': node_warnings(key, row, len(rows) > 1, status, tasks, now_ms),
    }
    if len(rows) > 1:
        view['duplicate_record_ids'] = [r.record_id for r in rows]
    return view


def task_view(task: TaskRow, allowed):
    return {'id': task.record_id, 'revision': task.revision, 'title': task.title, 'detail': task.detail,
            'assignee': _user(task.assignee), 'assigned_by': _user(task.assigned_by), 'department': task.department or None,
            'deadline': task.deadline, 'status': task.status.value, 'done_at': iso_time(task.done_at),
            'created_at': iso_time(task.created_at), 'can': allowed}


def _can(actor, key, status, snapshot, writes_enabled):
    rows = snapshot.rows.get(key, ())
    if not writes_enabled or len(rows) > 1:
        return dict(NO_ACTIONS)
    owners = frozenset(u.open_id for u in rows[0].owners) if rows else frozenset()
    return {action.value: ok for action, ok in node_permissions(actor, key, status, owners).items()}


def case_view(snapshot: CaseSnapshot, skipped, actor, writes_enabled, now_ms):
    statuses = derive_chain(facts_of(snapshot, skipped))
    summary = summarize(statuses)
    return statuses, {
        'code': snapshot.code,
        'summary': {'done': summary.done, 'total': summary.total,
                    'current_node': summary.current_node.value if summary.current_node else None},
        'nodes': [node_view(key, snapshot, statuses[key], now_ms) for key in CHAIN],
        'can': {key.value: _can(actor, key, statuses[key], snapshot, writes_enabled) for key in CHAIN},
        'warnings': list(snapshot.warnings),
    }


def node_detail(snapshot: CaseSnapshot, skipped, actor, roster, key: NodeKey, writes_enabled, now_ms):
    statuses, case = case_view(snapshot, skipped, actor, writes_enabled, now_ms)
    status = statuses[key]
    tasks = []
    for task in snapshot.node_tasks(key):
        allowed = task_permissions(actor, key, status, TaskFacts(
            task.status, task.assignee and task.assignee.open_id, task.assigned_by and task.assigned_by.open_id))
        tasks.append(task_view(task, allowed.__dict__ if writes_enabled else {k: False for k in allowed.__dict__}))
    # The roster serves the assignee picker only, so only someone who may assign sees it.
    people = [roster.public(p, key) for p in roster.assignable(key)] if roster and actor.manages(key) else []
    return {'code': case['code'], 'summary': case['summary'],
            'node': next(n for n in case['nodes'] if n['key'] == key.value), 'can': case['can'][key.value],
            'tasks': tasks, 'assignable_people': people, 'warnings': case['warnings']}
