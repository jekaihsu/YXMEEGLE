"""My Work read model (VCC-126): adapter input for frontend/src/myWorkView.ts.

Pure and read-only: no route, no storage, no network, no write. It reuses the
existing projections only (``filter_visible_cases``, ``build_home_task`` for
assignment, ``home_queues`` for awaiting confirmation). Nothing is inferred:
a parent case is verified only by an explicit relation, a due date is effective
only from a verified formal field, and every other fact stays unknown (omitted).

Read-input contract (``read``, supplied by the trusted caller; this module reads nothing):
``admitted`` is the existing production_access verdict (True/False/missing), ``failed`` and
``unlocated`` are terminal retrieval outcomes, ``loaded`` means a workspace was obtained,
``stale`` marks retained rows. Explicit terminal outcomes win over progress, in this order:
forbidden (``admitted`` is False) > read_failed > unlocated > loading (``loaded`` is not True)
> unknown (``admitted`` missing). A failed initial retrieval with ``loaded`` False is
therefore read_failed, never loading.

Trusted publication boundary: the output is passed through the existing case_redaction
response redactor (plan built from the pre-filter workspace, exactly as backend/app.py does),
except in the test/demo environments. The redactor's residual limits remain VCC-125.

``canSeeAwaitingConfirmation`` is the existing per-item authorization (``home_queues`` only
lists a confirmation the viewer may cast). No role is inferred: a supervisor with zero such
items sees no toggle until P1-INT proves an existing capability for it.
"""
from urllib.parse import quote

from . import case_redaction
from .data_state import data_state
from .home_details import _proxy, build_home_task
from .home_queues import CLOSED_TASKS, home_queues
from .source_case_policy import filter_visible_cases
from .workflow import now

# Statuses that are still open work. A status outside both sets stays unknown.
OPEN_TASKS = frozenset(('pending', 'in_progress', 'rework', 'paused'))
# Task fields proven to hold a verified formal due date. VCC-123 (deadline
# provenance) is unresolved, so none is proven: every due date stays unknown.
# due_date / original_due_date / estimated / pending / requested dates are not listed.
FORMAL_DUE_FIELDS = ()


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _route(project_id, node_id=None, task_id=None):
    """Existing SPA hash route (frontend/src/api.ts readRoute): view=project&project&node&task&tab."""
    parts = [('view', 'project'), ('project', project_id)]
    if node_id: parts.append(('node', node_id))
    if task_id: parts.append(('task', task_id))
    parts.append(('tab', 'flow'))
    return '/#' + '&'.join(f'{k}={quote(str(v), safe="")}' for k, v in parts)


def _effective_due(task):
    for field in FORMAL_DUE_FIELDS:
        value = _text(task.get(field))
        if value: return {'value': value, 'verified_formal': True}
    return {'verified_formal': False}


def _parent_verified(ws, project, node, task):
    """Explicit relation only: native containment, plus a contract task_ref for imported tasks."""
    if not isinstance(task.get('id'), str) or not isinstance(node.get('id'), str) or not isinstance(project.get('id'), str):
        return False
    if not task.get('source_identity'):
        return True  # workbench-native task created inside this node
    ref = {'project_id': project['id'], 'node_id': node['id'], 'task_id': task['id']}
    return any(isinstance(c, dict) and ref in (c.get('task_refs') or []) for c in ws.get('contract_items') or [])


def _unknown_outcome_tasks(ws):
    ids = set()
    for job in ws.get('jobs') or []:
        payload = job.get('payload') if isinstance(job, dict) else None
        if isinstance(payload, dict) and job.get('status') == 'outcome_unknown' and payload.get('task_id'):
            ids.add(payload['task_id'])
    return ids


def _malformed(task):
    """A task record the Home/queue helpers cannot index: bad id, status or owner shape."""
    status, owner = task.get('status'), task.get('owner_id')
    return (not _text(task.get('id')) or not (status is None or isinstance(status, str))
            or not (owner is None or isinstance(owner, str)))


def _projection(state, uid, viewer):
    """Copy of ``state`` safe to hand to the Home/queue helpers, plus whether anything was indeterminate.

    A record that is known to be someone else's (existing owner/delegation authority) and malformed is
    removed, so it can neither crash the helpers nor change a flag, count, row or assignment; a viewer
    prerequisite pointing at it then reads as missing, which stays blocked and visible. A malformed record
    that may be the viewer's, and any non-dict container, is removed too but makes the page partial.
    Well-formed records are shared untouched, so prerequisite and review-hash authority are unchanged.
    """
    partial = False
    projects = []
    for project in state.get('projects', []):
        if not isinstance(project, dict) or not _text(project.get('id')) or not isinstance(project.get('nodes'), list):
            partial = True; continue
        nodes = []
        for node in project['nodes']:
            if not isinstance(node, dict) or not isinstance(node.get('tasks'), list):
                partial = True; continue
            tasks = []
            for task in node['tasks']:
                if not isinstance(task, dict): partial = True; continue
                if _malformed(task):
                    mine = task.get('owner_id') == uid
                    if not mine:
                        try:
                            mine = bool(_proxy(state, project, task, viewer))
                        except (KeyError, TypeError, ValueError, AttributeError):
                            mine = True  # delegation data unreadable: it may be the viewer's
                    partial = partial or mine
                    continue
                tasks.append(task)
            nodes.append(dict(node, tasks=tasks) if len(tasks) != len(node['tasks']) else node)
        projects.append(dict(project, nodes=nodes))
    return dict(state, projects=projects), partial


def _blocked(*states):
    return {'rows': [], 'readState': data_state(*states), 'assignment': 'unknown', 'canSeeAwaitingConfirmation': False}


def build_my_work_input(ws, viewer, read=None):
    """Return ``{'rows','readState','assignment','canSeeAwaitingConfirmation'}`` for ``viewer``.

    ``read`` reports how the caller obtained ``ws`` (this module reads nothing):
    ``loaded``, ``admitted`` (the existing production_access verdict), ``failed``,
    ``unlocated`` and ``stale``. Missing information is never treated as success.
    """
    read = read if isinstance(read, dict) else {}
    if read.get('admitted') is False: return _blocked('forbidden')
    if read.get('failed'): return _blocked('read_failed')
    if read.get('unlocated'): return _blocked('unlocated')
    if read.get('loaded') is not True: return _blocked('loading')
    if read.get('admitted') is not True: return _blocked('unknown')
    uid = (viewer or {}).get('id')
    if not uid or not any(u.get('id') == uid and u.get('active', True) for u in ws.get('users', [])):
        return _blocked('unknown')

    partial = '_partial' in ws
    pre_filter = case_redaction.snapshot(ws)  # the redaction plan needs the original, unfiltered cases
    visible = filter_visible_cases(dict(ws))  # hidden cases vanish here, never as forbidden rows
    state, indeterminate = _projection(visible, uid, viewer)
    partial = partial or indeterminate
    as_of = ws.get('as_of') or now()[:10]
    unknown_outcome = _unknown_outcome_tasks(state)
    rows, ever_assigned = [], False
    for project in state.get('projects', []):
        nodes = project.get('nodes') if isinstance(project, dict) else None
        if not isinstance(nodes, list) or not _text(project.get('id')):
            partial = True; continue
        for node in nodes:
            tasks = node.get('tasks') if isinstance(node, dict) else None
            if not isinstance(tasks, list): partial = True; continue
            for task in tasks:
                if not isinstance(task, dict): partial = True; continue
                # Assignment first, from the existing owner/delegation authority: a task that cannot be the
                # viewer's never reaches validation or the full projection, so it cannot alter any page flag.
                if task.get('owner_id') != uid:
                    try:
                        mine = bool(_proxy(state, project, task, viewer))
                    except (KeyError, TypeError, ValueError, AttributeError):
                        partial = True; continue  # delegation data unreadable: it may be the viewer's
                    if not mine: continue
                if not _text(task.get('id')): partial = True; continue
                try:
                    home = build_home_task(state, project, node, task, viewer, as_of)
                except (KeyError, TypeError, ValueError, AttributeError):
                    partial = True; continue  # assignment cannot be established: never guess it
                if not home['assigned']: continue  # another person's task: no id, title or count
                ever_assigned = True
                status = task.get('status')
                if status in CLOSED_TASKS: continue
                verified = _parent_verified(state, project, node, task)
                row = {'id': task['id'], 'title': _text(task.get('title')), 'workflow_state': _text(status),
                       'effective_due': _effective_due(task), 'parent': {'verified': verified}}
                if status in OPEN_TASKS: row['ended'] = False
                if verified:
                    row['parent']['case_title'] = _text(project.get('name'))
                    owner = next((u for u in state.get('users', []) if u.get('id') == task.get('owner_id')), None)
                    if owner and _text(owner.get('name')): row['assignee_name'] = owner['name'].strip()
                    entry = [{'kind': 'task', 'exists': True, 'authorized': True, 'route': _route(project['id'], node['id'], task['id'])},
                             {'kind': 'case', 'exists': True, 'authorized': True, 'route': _route(project['id'])}]
                    detail = home.get('detail') or {}
                    entry.append({'kind': 'delivery', 'exists': True, 'authorized': detail.get('actionable') is True,
                                  'route': _route(project['id'], node['id'], task['id'])})
                    row['entry_points'] = entry
                    for key, field in (('required_input', 'input'), ('required_output', 'output'), ('pending_reason', None)):
                        value = _text(task.get(field)) if field else _text(detail.get('reason')) if detail.get('kind') != 'upcoming' else None  # upcoming text embeds a date
                        if value: row[key] = value
                if task['id'] in unknown_outcome: row['operation_outcome'] = 'unknown'
                rows.append({k: v for k, v in row.items() if v is not None})

    queues = home_queues(state, viewer)
    awaiting = queues.get('awaiting_confirmation', [])
    projects = {p.get('id'): p for p in state.get('projects', [])}
    for item in awaiting:
        project = projects.get(item.get('project_id'))
        node = next((n for n in (project or {}).get('nodes', []) if n.get('id') == item.get('node_id')), None)
        row = {'id': item['id'], 'title': _text(item.get('title')), 'queue': 'awaiting_my_confirmation',
               'ended': False, 'parent': {'verified': False}}
        if project and (node is not None or not item.get('node_id')):
            row['parent'] = {'verified': True, 'case_title': _text(project.get('name'))}
            row['entry_points'] = [{'kind': 'confirmation', 'exists': True, 'authorized': True,
                                    'route': _route(project['id'], item.get('node_id'))}]
        if _text(item.get('reason')): row['pending_reason'] = item['reason']
        if item.get('kind') in ('node_review', 'delivery_review', 'handover_acceptance'): row['handoff_state'] = item['kind']
        if item['id'] in unknown_outcome: row['operation_outcome'] = 'unknown'
        rows.append({k: v for k, v in row.items() if v is not None})

    flags = [name for name, on in (('partial', partial), ('stale', read.get('stale') is True)) if on]
    if flags:
        read_state = data_state(*flags, count=None if partial else len(rows))
    else:
        read_state = 'ready'
    out = {'rows': sorted(rows, key=lambda r: r['id']), 'readState': read_state,
           'assignment': 'assigned' if ever_assigned else 'unknown' if partial else 'unassigned',
            # Existing authorization: home_queues only lists a confirmation the viewer may cast (can_vote,
            # current reviewer seat or handover target). No such item proves nothing, so the toggle stays off.
           'canSeeAwaitingConfirmation': bool(awaiting)}
    # Same default as backend/app.py public_ws: the explicit environment, else derived from the surviving
    # (filtered) projects only, so a hidden demo case can never grant the test/demo exemption.
    environment = visible.get('environment', 'demo' if any(isinstance(p, dict) and p.get('source_kind') == 'demo' for p in visible.get('projects', [])) else 'production')
    if environment not in ('test', 'demo'):
        case_redaction.apply(out, case_redaction.make_plan(pre_filter, visible))
        out['rows'] = [{k: v for k, v in r.items() if v is not None} for r in out['rows'] if r.get('id') is not None]
    for row in out['rows']:  # the consumer's table and search read the row level title; only a verified parent supplies it
        if row['parent'].get('verified') and row['parent'].get('case_title'): row['case_title'] = row['parent']['case_title']
    return out
