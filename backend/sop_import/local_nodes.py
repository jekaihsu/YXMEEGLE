from copy import deepcopy

from sqlalchemy import select

from .. import audit, storage
from ..models import AuditRow, BusinessRow, WorkspaceRow
from ..workflow import now
from ..workflow_rules import audit_change
from .domain import Applicability, Lifecycle, NODE_MAP, require
from .models import TaskNodeLink


def eligible(project):
    return project.get('case_type') == 'intake' or not str(project.get('code') or '').strip()


def projection(service, db, ctx):
    from .service import can_manage
    if not eligible(ctx.project) or ctx.assigned_only:
        return []
    nodes = list(db.scalars(select(BusinessRow).where(BusinessRow.workspace_id == ctx.wid,
        BusinessRow.kind == 'nodes', BusinessRow.parent_id == ctx.project['id']).order_by(BusinessRow.ordinal)))
    tasks = service.tasks(db, ctx)
    links = list(db.scalars(select(TaskNodeLink).where(TaskNodeLink.workspace_id == ctx.wid,
        TaskNodeLink.project_id == ctx.project['id'])))
    result = []
    for row in nodes:
        n = row.data
        key = n.get('key')
        linked = [t for t in tasks if any(l.task_id == t.id and l.node_key == key for l in links)]
        legacy = list(db.scalars(select(BusinessRow).where(BusinessRow.workspace_id == ctx.wid,
            BusinessRow.kind == 'tasks', BusinessRow.parent_id == row.entity_id)))
        unfinished = any(t.state != Lifecycle.ARCHIVED and (t.applicability == Applicability.UNRESOLVED or
            t.applicability == Applicability.APPLICABLE and t.state != Lifecycle.DONE) for t in linked)
        unfinished = unfinished or any(t.data.get('required') and t.data.get('status') not in {'completed', 'superseded'} for t in legacy)
        reason = ('任務寫入尚未開放' if not service.writes_enabled() else '需由案件 PM 或管理者操作' if not can_manage(ctx)
                  else '此節點須依財務核准流程完成' if key in {'pricing', 'settlement'} else None)
        done = n.get('status') in {'completed', 'approved_skipped'}
        result.append({'key': key, 'id': row.entity_id, 'revision': n.get('workbench_revision', 0),
            'status': n.get('status', 'pending'), 'owner_id': n.get('owner_id'), 'completed_at': n.get('completed_at'),
            'reason': n.get('workbench_reason'), 'disabled_reason': reason,
            'complete_disabled_reason': '請先完成任務並確認適用條件' if unfinished else '節點已完成' if done else reason,
            'can': {'assign': not reason and not done, 'complete': not reason and not done and not unfinished,
                    'reject': not reason and n.get('status') == 'completed', 'create_task': not reason and not done}})
    return result


def mutate(service, ctx, key, body):
    from .service import authorize, fields, text
    fields(body, {'action', 'expected_revision', 'owner_id', 'reason'})
    require(key in NODE_MAP.values(), 'node_mapping_invalid')
    authorize(ctx, True)
    service.writable()
    action = body.get('action')
    require(action in {'assign', 'complete', 'reject'}, 'invalid_request')
    reason = text(body.get('reason', ''), 1000, empty=action == 'assign').strip()
    with service.sessions.begin() as db:
        service.lock_workspace_row(db, ctx.wid)
        fresh = ctx.refresh()
        authorize(fresh, True)
        require(eligible(fresh.project) and not fresh.assigned_only, 'local_node_only', 409)
        service.check_policy_write(db, fresh, [key])
        view = next((n for n in projection(service, db, fresh) if n['key'] == key), None)
        require(view is not None, 'node_mapping_invalid')
        require(type(body.get('expected_revision')) is int and body['expected_revision'] == view['revision'], 'node_revision_conflict', 409)
        require(view['can'][action], 'local_node_blocked', 409, reason=view.get('complete_disabled_reason') if action == 'complete' else view['disabled_reason'])
        row = db.get(WorkspaceRow, ctx.wid)
        require(row.data.get('storage_schema') == 2, 'import_unavailable', 503)
        state = storage.load(db, BusinessRow, row)
        project = next(p for p in state['projects'] if p['id'] == fresh.project['id'])
        node = next(n for n in project['nodes'] if n['key'] == key)
        before = deepcopy(node)
        if action == 'assign':
            owner = body.get('owner_id')
            require(isinstance(owner, str) and any(u['id'] == owner and u.get('active', True) for u in state['users']), 'participant_invalid')
            node['owner_id'] = owner
        else:
            node.update(status='completed' if action == 'complete' else 'in_progress',
                        completed_at=now() if action == 'complete' else None, workbench_reason=reason)
        node['workbench_revision'] = view['revision'] + 1
        audit_change(state, fresh.user, 'local_node_' + action, project, node, before=before, after=node, reason=reason)
        state['version'] = row.version + 1
        row.data = storage.save(db, BusinessRow, ctx.wid, state)
        row.version = state['version']
        db.add(audit.record(AuditRow, ctx.wid, fresh.user['id'], 'local_node_' + action,
            details={'project_id': project['id'], 'node_id': node['id'], 'before': before, 'after': deepcopy(node), 'reason': reason}))
        return {'node_key': key, 'revision': node['workbench_revision'], 'status': node['status']}
