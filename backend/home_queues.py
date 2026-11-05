"""Read-only personal queues backed by current, explicit workspace evidence."""
from datetime import datetime

from fastapi import HTTPException

from .case_cutover import execution_allowed
from .delivery_approval import active_seats, reviewer_seats
from .operations import can_vote, delegation_valid, delivery_fingerprint, review_hash, seats
from .policy import FINANCIAL
from .workflow import now

CLOSED_TASKS = frozenset(('completed', 'superseded', 'not_applicable', 'skipped', 'cancelled', 'canceled'))
CLOSED_NODES = frozenset(('completed', 'superseded', 'not_applicable', 'skipped', 'cancelled', 'canceled'))


def _item(ident, title, reason, project_id, kind, *, node_id=None, task_id=None):
    item = {'id': ident, 'title': title, 'reason': reason, 'project_id': project_id,
            'kind': kind, 'tab': 'flow'}
    if node_id is not None: item['node_id'] = node_id
    if task_id is not None: item['task_id'] = task_id
    return item


def _valid_timestamp(value):
    if not isinstance(value, str) or not value.strip(): return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def home_queues(ws, user):
    """Project only demonstrable current actions and assignments; never infer from PM role."""
    result = {'awaiting_confirmation': [], 'delegated_by_me': [], 'unavailable': []}
    uid = (user or {}).get('id')
    if not uid or not any(u.get('id') == uid and u.get('active', True) for u in ws.get('users', [])):
        return result
    people = {u.get('id'): u for u in ws.get('users', [])}
    from .home_details import local_work_instance
    projects = {p['id']: p for p in ws.get('projects', []) if p.get('id') and p.get('case_visibility') != 'excluded_history'}
    today = now()[:10]
    missing_assignment_history = False
    for p in projects.values():
        executable = execution_allowed(ws, p)
        for n in p.get('nodes', []):
            if executable and n.get('status') not in CLOSED_NODES and n.get('review_cycles'):
                cycle = n['review_cycles'][-1]
                if (cycle.get('status') == 'pending' and not cycle.get('historical_scope')
                        and not (ws.get('environment') == 'production' and cycle.get('simulated'))
                        and cycle.get('mode') != 'native'
                        and not (ws.get('environment') == 'production' and n.get('key') in FINANCIAL)):
                    try:
                        current_seats = seats(p, n)
                        current_hash = review_hash(p, n)
                    except (KeyError, TypeError, ValueError):
                        current_seats = {}; current_hash = None
                    if current_hash == cycle.get('content_hash'):
                        for seat, principal in (cycle.get('seats') or {}).items():
                            if current_seats.get(seat) != principal: continue
                            if any(v.get('seat') == seat and not v.get('invalidated') for v in cycle.get('votes', [])): continue
                            if any(v.get('actor_id') == uid and v.get('seat') != seat and v.get('result') == 'approved'
                                   and not v.get('invalidated') for v in cycle.get('votes', [])): continue
                            try:
                                authorized = can_vote(ws, user, p, seat, principal)
                            except (HTTPException, KeyError, TypeError):
                                authorized = False
                            if authorized:
                                result['awaiting_confirmation'].append(_item(
                                    f"review:{cycle['id']}:{seat}", n.get('name') or '節點確認',
                                    f'待你以 {seat} 職責確認本輪節點', p['id'], 'node_review', node_id=n['id']))
            for t in n.get('tasks', []):
                if t.get('status') in CLOSED_TASKS: continue
                if ws.get('environment') == 'production' and not local_work_instance(p,t): continue
                history = t.get('assignment_history')
                if not isinstance(history, list) or not history:
                    if t.get('owner_id') and t['owner_id'] != uid: missing_assignment_history = True
                    continue
                latest = history[-1]
                owner = t.get('owner_id')
                if not isinstance(latest, dict):
                    if owner and owner != uid: missing_assignment_history = True
                    continue
                after = latest.get('after')
                if (owner and owner != uid and
                        (not isinstance(after, dict) or not isinstance(after.get('owner_id'), str)
                         or not after['owner_id'].strip()
                         or not isinstance(latest.get('actor_id'), str) or not latest['actor_id'].strip()
                         or not _valid_timestamp(latest.get('at')))):
                    missing_assignment_history = True
                    continue
                if (latest.get('actor_id') == uid and owner and owner != uid
                        and after.get('owner_id') == owner):
                    owner_name = people.get(owner, {}).get('name') or owner
                    result['delegated_by_me'].append(_item(
                        f"assignment:{p['id']}:{n['id']}:{t['id']}", t.get('title') or '任務',
                        f'你已指派給 {owner_name}；依任務最新指派紀錄', p['id'], 'task_assignment',
                        node_id=n['id'], task_id=t['id']))
        if executable:
            for batch in p.get('delivery_batches', []):
                if batch.get('status') != 'submitted' or batch.get('superseded_by'): continue
                current = reviewer_seats(p, batch)
                if (current != batch.get('required_reviewer_seats')
                        or not active_seats(ws, current)
                        or batch.get('content_hash') != delivery_fingerprint(batch)): continue
                selected_nodes = [node_id for node_id, reviewer in current.items() if reviewer == uid]
                if not selected_nodes: continue
                approved = {node_id for vote in batch.get('approvals', [])
                            if vote.get('actor_id') == uid and vote.get('content_hash') == batch['content_hash']
                            for node_id in vote.get('node_ids', [])}
                pending = [node_id for node_id in selected_nodes if node_id not in approved]
                if pending:
                    result['awaiting_confirmation'].append(_item(
                        f"delivery:{batch['id']}", f"交付批次 {batch['id']}",
                        '待你以現任交付組主管身分核定', p['id'], 'delivery_review', node_id=pending[0]))
    for h in ws.get('handover_requests', []):
        p = projects.get(h.get('project_id'))
        if not p or not execution_allowed(ws, p): continue
        title = p.get('name') or p.get('code') or '案件交接'
        if h.get('status') == 'awaiting_acceptance' and h.get('to_id') == uid:
            result['awaiting_confirmation'].append(_item(
                f"handover:{h['id']}", title, '交接已核准，待你接受',
                p['id'], 'handover_acceptance'))
        if h.get('status') in ('pending', 'awaiting_acceptance') and h.get('from_id') == uid:
            result['delegated_by_me'].append(_item(
                f"handover-outgoing:{h['id']}", title,
                '你是交接中的原負責人；待核准或接手人接受', p['id'], 'handover_outgoing'))
    for d in ws.get('delegations', []):
        p = projects.get(d.get('project_id'))
        if (not p or d.get('principal_id') != uid or d.get('status') != 'active'
                or d.get('scope') != 'tasks' or d.get('seat') != 'owner'
                or not (str(d.get('start_date', '')) <= today <= str(d.get('end_date', '')))
                or not people.get(d.get('delegate_id'), {}).get('active', False)):
            continue
        try:
            if not delegation_valid(ws, d, at_use=True): continue
        except (KeyError, TypeError):
            continue
        task_ids = set(d.get('task_ids') or [])
        for n in p.get('nodes', []):
            for t in n.get('tasks', []):
                if t.get('id') not in task_ids or t.get('owner_id') != uid or t.get('status') in CLOSED_TASKS: continue
                delegate = people[d['delegate_id']].get('name') or d['delegate_id']
                result['delegated_by_me'].append(_item(
                    f"delegation:{d['id']}:{t['id']}", t.get('title') or '任務',
                    f'你授權 {delegate} 代理此任務至 {d["end_date"]}', p['id'], 'task_delegation',
                    node_id=n['id'], task_id=t['id']))
    if missing_assignment_history:
        result['unavailable'].append({'id': 'assignment-audit-unavailable', 'title': '部分交辦來源無法判定',
                                      'reason': '缺少任務 assignment_history 的 actor_id、after.owner_id 與 at；不能推定由誰指派。',
                                      'project_id': None, 'kind': 'assignment_audit_unavailable', 'tab': None})
    for key in ('awaiting_confirmation', 'delegated_by_me'):
        result[key].sort(key=lambda item: (item['project_id'], item.get('node_id', ''), item.get('task_id', ''), item['id']))
    return result
