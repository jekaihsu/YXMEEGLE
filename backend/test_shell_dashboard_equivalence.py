"""The shell dashboard must show exactly what the legacy Dashboard computes from the full workspace (frontend/src/App.tsx Dashboard)."""
import pytest
from . import app as backend_app
from .test_perf_budget import scaled_client
from .test_shell import ON, switch

CLOSED = ('completed', 'superseded')
SHOWN = 5  # Dashboard: [...overdue, ...dueToday].slice(0, 5); pending.slice(0, 2)


def half_enabled(state):
    """Every other case has a verified lifecycle (not derived as paused), so both paused and executable cases carry dated tasks."""
    for i, p in enumerate(state['projects']):
        if i % 2: p['source_lifecycle'] = dict(state='mapped', reasons=[], canonical='執行中', relationship='已關聯確認單'); p['execution_status'] = 'in_progress'
        else: p['execution_status'] = 'paused'


def legacy_dashboard(w):
    """Python port of the legacy Dashboard numbers and lists, from the full /api/workspace body."""
    today = w['as_of'][:10]
    # VCC-119 rule (frontend/src/executableTasks.ts): assigned to the viewer, case not paused, open.
    rows = [(p, n, t) for p in w['projects'] for n in p['nodes'] for t in n['tasks'] if t.get('can_execute') is True and p.get('execution_status') != 'paused']
    active = lambda t: t['status'] not in CLOSED
    overdue = [r for r in rows if r[2]['due_date'] and r[2]['due_date'][:10] < today and active(r[2])]
    due_today = [r for r in rows if active(r[2]) and (r[2]['due_date'] or '')[:10] == today]
    name = lambda uid: next((u['name'] for u in w['users'] if u['id'] == uid), '尚未指派')
    pending = [a for a in w['approvals'] if a['status'] == 'pending']
    return dict(
        my_overdue=sum(t.get('can_execute') is True for _, _, t in overdue), other_overdue=sum(t.get('can_execute') is not True for _, _, t in overdue), overdue=len(overdue), due_today=len(due_today), active=None, pending=len(pending),
        attention=[dict(task_id=t['id'], title=t['title'], project_id=p['id'], project_code=p['code'], node_name=n['name'], assignee=name(t.get('owner_id')),
                        due_date=t['due_date']) for p, n, t in (overdue + due_today)[:SHOWN]],
        approvals=[(a['id'], a['title'], a['type'], a['project_id']) for a in pending[:2]],
        formal=sum(p['case_type'] != 'intake' for p in w['projects']), intake=sum(p['case_type'] == 'intake' for p in w['projects']))


def shell_dashboard(s):
    names = {u['id']: u['name'] for u in s['users']}
    c = s['counts']
    return dict(my_overdue=c['my_overdue_tasks'], other_overdue=c['overdue_tasks']-c['my_overdue_tasks'], overdue=c['overdue_tasks'], due_today=c['due_today_tasks'], active=None, pending=c['approvals_pending'],
                attention=[dict(task_id=a['task_id'], title=a['title'], project_id=a['project_id'], project_code=a['project_code'], node_name=a['node_name'],
                                assignee=names.get(a['assignee_id'], '尚未指派'), due_date=a['due_date']) for a in s['attention'][:SHOWN]],
                approvals=[(a['id'], a['title'], a['type'], a['project_id']) for a in s['pending_approvals']],
                formal=sum(p['case_type'] != 'intake' for p in s['projects']), intake=sum(p['case_type'] == 'intake' for p in s['projects']))


@pytest.mark.parametrize('uid', ['u-manager', 'u-pm', 'ou_017', 'ou_018'])
@pytest.mark.parametrize('today', ['2026-10-06', '2026-10-09', '2026-11-30'])
def test_shell_dashboard_equals_legacy_dashboard(tmp_path, monkeypatch, uid, today):
    monkeypatch.setattr(backend_app, 'now', lambda: today + 'T09:00:00+08:00')
    with scaled_client(tmp_path, 40, mutate=half_enabled, **ON) as (app, client):
        switch(client, uid)
        full = client.get('/api/workspace').json(); shell = client.get('/api/workspace?scope=shell').json()
        legacy = legacy_dashboard(full)
        if uid in ('ou_017', 'ou_018'): assert legacy['overdue'] + legacy['due_today'] > 0  # these members own dated tasks on executable cases
        assert shell['pending_approvals']
        assert shell_dashboard(shell) == legacy
        assert len(shell['attention']) >= min(SHOWN, legacy['overdue'] + legacy['due_today'])


def test_manager_owning_no_tasks_still_sees_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(backend_app, 'now', lambda: '2026-10-06T09:00:00+08:00')
    with scaled_client(tmp_path, 40, mutate=half_enabled, **ON) as (app, client):
        switch(client, 'u-manager')
        full = client.get('/api/workspace').json(); shell = client.get('/api/workspace?scope=shell').json()
        assert not any(t['owner_id'] == 'u-manager' for p in full['projects'] for n in p['nodes'] for t in n['tasks'])
        assert shell['counts']['overdue_tasks'] == 0 and shell['attention'] == [] and shell['pending_approvals']  # Home counts only the viewer's executable work
        assert shell_dashboard(shell) == legacy_dashboard(full)


def test_shell_dashboard_never_leaks_hidden_cases(tmp_path, monkeypatch):
    from sqlalchemy import update
    from . import workspace_environment
    from .models import ProjectIndex
    monkeypatch.setattr(backend_app, 'now', lambda: '2026-10-06T09:00:00+08:00')
    with scaled_client(tmp_path, 12, **ON) as (app, client):
        switch(client, 'u-pm')
        with app.state.sessions.begin() as db:
            db.execute(update(ProjectIndex).where(ProjectIndex.project_id.in_(['p001', 'p002', 'p003'])).values(case_visibility='excluded_history'))
        monkeypatch.setattr(workspace_environment, 'normalize_environment', lambda state, wid, cfg: state.update(environment='production') or state)
        shell = client.get('/api/workspace?scope=shell').json()
        hidden = {'p001', 'p002', 'p003'}
        assert not any(a['project_id'] in hidden for a in shell['attention'] + shell['pending_approvals'])
        everything = legacy_dashboard(client.get('/api/workspace').json())  # full path hides via source_case_policy only if the state says so; counts must not exceed it
        assert shell['counts']['overdue_tasks'] <= everything['overdue']
