"""Delivery approval seats are bound to the selected nodes, not just people."""
from copy import deepcopy

from .workflow import now
from .workflow_rules import assignable


def reviewer_seats(p, item):
    selected = set(item.get('work_item_ids', []))
    return {node['id']: node.get('supervisor_id') or p.get('supervisor_id', '')
            for node in p['nodes']
            if any(task['id'] in selected or task.get('work_item_id') in selected
                   for task in node['tasks'])}


def active_seats(ws, seats):
    people = {person['id']: person for person in ws['users']}
    return bool(seats) and all(assignable(ws, people.get(ident)) for ident in seats.values())


def approved_seats(ws, p, item):
    seats = reviewer_seats(p, item)
    if seats != item.get('required_reviewer_seats') or not active_seats(ws, seats):
        return False
    covered = set()
    for vote in item.get('approvals', []):
        if vote.get('content_hash') != item.get('content_hash'):
            continue
        covered.update(node_id for node_id in vote.get('node_ids', [])
                       if seats.get(node_id) == vote.get('actor_id'))
    return covered == set(seats)


def refresh_reviewers(ws, p, item):
    """Retire stale seats while retaining immutable copies of their votes."""
    if item.get('status') not in ('submitted', 'approved') or item.get('superseded_by'):
        return
    seats = reviewer_seats(p, item)
    previous = item.get('required_reviewer_seats')
    people = {person['id']: person for person in ws['users']}
    approvals = []
    for vote in item.get('approvals', []):
        nodes = [node_id for node_id in vote.get('node_ids', [])
                 if previous and previous.get(node_id) == seats.get(node_id) == vote.get('actor_id')
                 and assignable(ws, people.get(vote.get('actor_id')))
                 and vote.get('content_hash') == item.get('content_hash')]
        if nodes != vote.get('node_ids'):
            item.setdefault('approval_history', []).append({**deepcopy(vote),
                'invalidated_at': now(), 'invalidated_reason': '交付主管職責或在職狀態已變更'})
        if nodes:
            approvals.append({**vote, 'node_ids': nodes})
    if previous != seats:
        item.setdefault('reviewer_seat_history', []).append({
            'before': deepcopy(previous), 'after': deepcopy(seats), 'at': now()})
    item['required_reviewer_seats'] = seats
    item['required_reviewer_ids'] = list(dict.fromkeys(seats.values()))
    item['approvals'] = approvals
    if item['status'] == 'approved' and not approved_seats(ws, p, item):
        item.update(status='submitted', review_reason='交付主管職責或在職狀態已變更，須重新確認')
