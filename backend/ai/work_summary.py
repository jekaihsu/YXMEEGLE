"""Completion evidence from workflow identity and the live node-assignment projection."""
import httpx

from .tools import pick, ReadDenied

SKIPPED = {'略過', 'skipped', 'not_applicable', 'approved_skipped'}
DONE = {'completed', 'done', 'verified', '已完成'}
CLOSED = DONE | {'superseded', 'not_applicable', 'skipped', 'cancelled', 'canceled', '取消', '略過', 'approved_skipped'}
LABELS = {'completed': '已完成', 'done': '已完成', 'verified': '已確認完成',
          'in_progress': '進行中', 'pending': '待處理', 'paused': '暫停中', 'blocked': '受阻',
          'not_started': '未開始', 'active': '進行中', 'waiting': '等待前置條件', 'overdue': '逾期',
          'review': '待審核', 'pending_review': '待審核', 'in_review': '待審核', 'unknown': '狀態待確認',
          'rework': '退回修正', 'skipped': '略過', 'superseded': '舊版留存',
          'not_applicable': '不適用', 'cancelled': '取消', 'canceled': '取消', 'approved_skipped': '核准跳過'}


def summarize(detail, assignments=None):
    section = detail.get('sections', {}).get('workflow_nodes')
    if section is None:
        return {'unavailable': '無法確認：工作流程無法讀取'}
    rows = []
    for n in section.get('rows', []):
        tasks = n.get('tasks', [])
        rows.append(dict(**pick(n, 'key', 'label'), node_key=n.get('node_id', '').rsplit('-', 1)[-1],
            status=LABELS.get(n.get('status'), n.get('status') or '狀態待確認'),
            completed=n.get('status') in DONE, skipped=n.get('status') in SKIPPED, tasks_done=sum(t.get('status') in DONE for t in tasks),
            tasks_total=sum(t.get('status') not in CLOSED - DONE for t in tasks), basis='workflow_nodes'))
    workflow_nodes = dict(done=sum(n['completed'] for n in rows), total=sum(not n['skipped'] for n in rows))
    workflow_counts = dict(done=sum(n['tasks_done'] for n in rows), total=sum(n['tasks_total'] for n in rows))
    for n in (assignments or {}).get('nodes', []):
        key = n['key']
        previous = next((r for r in rows if r['node_key'] == key or r['label'] == n['label']), None)
        counts = n.get('tasks', {})
        current = dict(key=key, node_key=key, label=n['label'], status=n['derived_status'],
            completed=n['derived_status'] in DONE, skipped=n['derived_status'] in SKIPPED, tasks_done=counts.get('done'), tasks_total=counts.get('total'),
            basis='node_assignments.derived_status',
            workflow_evidence=pick(previous or {}, 'status', 'completed', 'skipped', 'tasks_done', 'tasks_total', 'basis'))
        if previous is None:
            rows.append(current)
        else:
            rows[rows.index(previous)] = current
    result = dict(rows=rows, workflow_completed_nodes=workflow_nodes, workflow_completed_tasks=workflow_counts,
        skipped_nodes=sum(n['skipped'] for n in rows),
        completed_tasks_basis='node_assignments' if (assignments or {}).get('nodes') else 'workflow_nodes', completed_nodes=dict(done=sum(n['completed'] for n in rows), total=sum(not n['skipped'] for n in rows)),
        completed_tasks=dict(done=sum(n['tasks_done'] or 0 for n in rows), total=sum(n['tasks_total'] or 0 for n in rows)))
    if not rows or set(section.get('states', [])) & {'unknown', 'read_failed', 'forbidden', 'loading', 'unlocated'}:
        result['unavailable'] = '無法確認：工作流程來源未提供完整資料'
    if any(n['tasks_done'] is None or n['tasks_total'] is None for n in rows):
        result['unavailable'] = '無法確認：部分任務計數未提供'
    if any(n['status'] in {'unknown', '狀態待確認'} for n in rows):
        result['unavailable'] = '無法確認：部分節點狀態未知'
    if assignments and assignments.get('unavailable'):
        result['assignment_unavailable'] = '無法確認：節點指派來源無法取得；僅列工作流程資料'
    if assignments and assignments.get('stale'):
        result['unavailable'] = '無法確認：節點指派資料可能過期'
    completion_notes(result)
    return result


async def add_sop(reader, project_id, summary):
    try:
        value = await reader.get('/api/projects/' + project_id + '/sop-tasks')
    except (ReadDenied, httpx.HTTPStatusError, httpx.TimeoutException):
        summary['sop_tasks'] = {'unavailable': '無法確認：SOP 任務資料無法取得'}
        summary.pop('completion_note', None)
        return
    summary['sop_tasks'] = dict(basis='sop_tasks.case_counts', **pick(value, 'case_counts'))
    if value.get('case_counts', {}).get('total'):
        summary['completion_note'] = '工作流程／Lark 任務與 SOP 檢查清單分別計數，可能重疊，不可相加'
    for node in summary.get('rows', []):
        counts = value.get('node_counts', {}).get(node['node_key'])
        if counts and counts.get('total'):
            node['sop_tasks_done'] = counts['done']
            node['sop_tasks_total'] = counts['total']
    completion_notes(summary)


def completion_notes(summary):
    sources = [('工作流程節點', summary.get('workflow_completed_nodes', {})),
               ('工作流程任務', summary.get('workflow_completed_tasks', {})),
               ('目前節點', summary.get('completed_nodes', {})),
               ('目前任務', summary.get('completed_tasks', {}))]
    sop = summary.get('sop_tasks', {}).get('case_counts')
    if sop is not None:
        sources.append(('SOP 檢查清單', sop))
    summary.pop('completion_note', None)
    summary.pop('completion_conflict', None)
    conflicts = any((e := row.get('workflow_evidence')) and
                    (e['completed'] != row['completed'] or
                     ((e['completed'] or (e['tasks_done'] or 0) > 0) and
                      not row['completed'] and row['tasks_done'] == 0))
                    for row in summary.get('rows', []))
    counts = '；'.join(f"{label}已完成 {c.get('done')}／{c.get('total')}" for label, c in sources)
    if conflicts:
        summary['completion_conflict'] = '完成來源不一致：' + counts
    elif sources and all(c.get('done') == 0 for _, c in sources) and not summary.get('unavailable'):
        summary['completion_note'] = '目前可確認資料中，已完成節點與任務均為 0'
    elif sop and sop.get('total'):
        summary['completion_note'] = '工作流程／Lark 任務與 SOP 檢查清單分別計數，可能重疊，不可相加'
