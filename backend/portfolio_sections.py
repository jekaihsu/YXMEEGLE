"""Lifecycle facts and bounded windows of an immutable portfolio capture."""
KEYS = ('sop', 'notStarted', 'other', 'done')
FINISHED = {'completed', 'approved_skipped', 'skipped', '已完成', '略過'}
WAITING = {'not_started', 'pending', '未開始', '待處理'}
ACTIVE = {'in_progress', 'pending_review', 'awaiting_review', 'paused', '進行中', '待審核'}


def lifecycle(nodes, *, complete):
    statuses = [n.get('status') for n in nodes]
    if not complete or not statuses or any(s not in FINISHED | WAITING | ACTIVE for s in statuses):
        return '待核對'
    if all(s in FINISHED for s in statuses):
        return '已完成'
    if all(s in WAITING for s in statuses):
        return '尚未開始'
    first = next(s for s in statuses if s not in FINISHED)
    return '待審核' if first in {'pending_review', 'awaiting_review', '待審核'} else '暫停' if first == 'paused' else '進行中'


def annotate(item, *, complete):
    state = lifecycle(item['portfolio_nodes'], complete=complete)
    sop = item['sop_summary']
    item['lifecycle_state'] = state
    item['lifecycle_section'] = ('done' if state == '已完成' else 'notStarted' if state == '尚未開始'
        else 'other' if state == '待核對' else 'sop' if sop['policy'] == 'managed' or sop['imported_tasks'] else 'other')


def section_counts(db, items):
    """Aggregate the small classified projection once, in the capture transaction.

    Aggregate the *collapsed* capture, not raw index rows: duplicates and live
    overlays otherwise produce counts inconsistent with the visible population.
    The SQL input is just one section key per case, never node/source payloads.
    """
    import json
    from sqlalchemy import select, func, literal, cast
    from sqlalchemy.dialects.postgresql import JSONB
    payload = json.dumps([p['lifecycle_section'] for p in items])
    if db.get_bind().dialect.name == 'postgresql':
        values = func.jsonb_array_elements_text(cast(literal(payload), JSONB)).table_valued('value')
    else:
        values = func.json_each(payload).table_valued('value')
    return {**dict.fromkeys(KEYS, 0), **dict(db.execute(select(values.c.value, func.count()).group_by(values.c.value)).all())}


def filtered(result, filters, today):
    """Filter the complete capture before paging, retaining its immutable identity."""
    from datetime import date, timedelta
    q = str(filters.get('q', '')).strip().lower()
    soon = (date.fromisoformat(today) + timedelta(days=7)).isoformat()
    def attention(p):
        closed = p['lifecycle_state'] == '已完成'
        due = (p.get('due_date') or '')[:10]
        return not closed and (p.get('overdue_tasks', 0) > 0 or bool(due and due < today) or p.get('execution_status') in ('paused', 'blocked') or bool(due and today <= due <= soon))
    def matches(p):
        nodes = p['portfolio_nodes']
        current = next((n.get('key') for n in nodes if n.get('status') not in FINISHED), None)
        node = filters.get('node')
        return (q in ' '.join(str(p.get(k) or '') for k in ('code', 'name', 'client')).lower()
            and (not filters.get('client') or p['client'] == filters['client'])
            and (not filters.get('owner') or p['pm_id'] == filters['owner'])
            and (not filters.get('state') or p['lifecycle_state'] == filters['state'])
            and (not node or (p['lifecycle_state'] == '待核對' if node == 'unknown' else current == node))
            and (not filters.get('kind') or (p['case_type'] != 'intake' if filters['kind'] == 'formal' else p['case_type'] == 'intake'))
            and (not filters.get('attention') or attention(p)))
    items = [p for p in result['items'] if matches(p)]
    field = {'name': 'name', 'created': 'created_at'}.get(filters.get('sort'), 'due_date')
    items.sort(key=lambda p: (p.get('code') or '', p['id']))
    # Missing dates always sort last, as in compareTableValues.
    present = [p for p in items if p.get(field)]
    absent = [p for p in items if not p.get(field)]
    present.sort(key=lambda p: p[field], reverse=filters.get('direction') == -1)
    items = present + absent
    if field == 'due_date': items.sort(key=lambda p: not (p.get('overdue_tasks', 0) > 0 or bool(p.get('due_date') and p['due_date'][:10] < today) and p['lifecycle_state'] != '已完成'))
    result.update(items=items, workspace_total=result['total'], total=len(items))
    return result


def window(result, *, page, section='', replaced=False, size=25):
    """Counts describe the entire captured population; items describe only this window."""
    items = result['items']
    groups = {key: [p for p in items if p['lifecycle_section'] == key] for key in KEYS}
    result['facets'] = dict(clients=sorted({p.get('client') for p in items if p.get('client')}), owners=sorted({p.get('pm_id') for p in items if p.get('pm_id')}))
    result['unknown_total'] = sum(p['lifecycle_state'] == '待核對' for p in items)
    result['counts'] = dict(active=None if result['unknown_total'] else sum(p['lifecycle_state'] in ('進行中', '待審核', '暫停') for p in items),
        sop=None if any(p['lifecycle_state'] == '待核對' and (p['sop_summary']['policy'] == 'managed' or p['sop_summary']['imported_tasks']) for p in items) else sum((p['sop_summary']['policy'] == 'managed' or p['sop_summary']['imported_tasks']) and p['lifecycle_state'] != '已完成' for p in items))
    result['sections'] = {key: dict(total=result['section_counts'][key], next_page=2 if len(rows) > size else None) for key, rows in groups.items()}
    if replaced:
        # LIVE-1 recovery replaces the entire generation atomically.
        result.update(items=items, page=1, next_page=None)
        for value in result['sections'].values(): value['next_page'] = None
    elif section:
        start = (page - 1) * size
        result['items'] = groups[section][start:start + size]
        result['next_page'] = page + 1 if start + size < len(groups[section]) else None
        result['sections'][section]['next_page'] = result['next_page']
        result['page'] = page
    else:
        result['items'] = [p for rows in groups.values() for p in rows[:size]]
        result.update(page=1, next_page=None)
    return result
