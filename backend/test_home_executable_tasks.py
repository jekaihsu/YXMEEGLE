"""VCC-119: Home overdue / due-today / attention count only executable work (frontend/src/executableTasks.ts mirrors this rule).

A task counts only when it is assigned to the viewer (can_execute), its case is not paused for execution and it is open.
"""
from contextlib import contextmanager
import pytest
from fastapi.testclient import TestClient
from . import app as backend_app, storage
from .app import BusinessRow, WorkspaceRow, create_app
from .perf_fixture import build_scaled_workspace
from .policy import upgrade
from .test_shell import ON, switch

VIEWER, OTHER = 'ou_020', 'ou_021'
AS_OF = '2026-10-07'


def task(ident, owner, due, status='pending'):
    return dict(id=ident, title=ident, owner_id=owner, status=status, required=True, start_date=AS_OF, due_date=due, original_due_date=due,
                started_at=None, completed_at=None, points=None, work_item_id=None, description='', input='', output='', comments=[], revision=1)


def shape(state):
    """Five cases: paused, enabled, and one paused case shaped like the staging template (unassigned, every task dated)."""
    state['as_of'] = AS_OF
    for p in state['projects']:
        for n in p['nodes']:
            n['owner_id'] = ''; n['status'] = 'pending'; n['tasks'] = []
    paused, live, template = state['projects'][:3]
    paused['execution_status'] = template['execution_status'] = 'paused'  # as stored for staging cases (unverified lifecycle)
    live['source_lifecycle'] = dict(state='mapped', reasons=[], canonical='執行中', relationship='已關聯確認單')  # verified lifecycle: the case is not derived as paused
    live['execution_status'] = 'in_progress'  # paused cases keep the lark default: unverified lifecycle derives 'paused'
    sales = lambda p: p['nodes'][0]['tasks']
    sales(paused).extend([task('pz-late1', VIEWER, '2026-10-01'), task('pz-late2', VIEWER, '2026-09-20'), task('pz-today', VIEWER, AS_OF)])
    sales(live).extend([task('lv-late1', VIEWER, '2026-10-01'), task('lv-late2', VIEWER, '2026-10-05T09:00:00+08:00'), task('lv-today', VIEWER, AS_OF),
                        task('lv-unassigned', '', '2026-10-01'), task('lv-other', OTHER, '2026-10-02'), task('lv-done', VIEWER, '2026-10-01', 'completed')])
    sales(template).extend([task('tp-late', '', '2026-09-10'), task('tp-late2', '', '2026-09-10')])


@contextmanager
def home_client(tmp_path, monkeypatch, mutate=shape, clock=AS_OF):
    monkeypatch.setattr(backend_app, 'now', lambda: clock + 'T09:00:00+08:00')
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/home.db', 'UPLOAD_DIR': str(tmp_path / 'uploads'), 'SESSION_SECRET': 'fictional-home-secret' * 3,
                      'APP_ENV': 'development', 'DEMO_MODE': 'true', 'LARK_LIVE_READ_ENABLED': 'false', 'LARK_APP_ID': '', 'LARK_APP_SECRET': '',
                      'LARK_ALLOWED_TENANTS': '', **ON})
    try:
        with TestClient(app) as client:
            assert client.get('/api/session').status_code == 200
            wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
            with app.state.sessions.begin() as db:
                row = db.get(WorkspaceRow, wid); state = build_scaled_workspace(5); mutate(state); upgrade(state)
                row.data = storage.save(db, BusinessRow, wid, state)
            switch(client, VIEWER)
            yield client
    finally:
        app.state.engine.dispose()


def home_rule(w):
    """Python port of frontend/src/executableTasks.ts over the full workspace body."""
    rows = [(p, t) for p in w['projects'] for n in p['nodes'] for t in n['tasks']
            if t.get('can_execute') is True and p.get('execution_status') != 'paused' and t['status'] not in ('completed', 'superseded')]
    today = w['as_of'][:10]
    late = [t['id'] for p, t in rows if t['due_date'] and t['due_date'][:10] < today]
    due = [t['id'] for p, t in rows if (t['due_date'] or '')[:10] == today]
    return dict(overdue=len(late), due_today=len(due), attention=late + due)


def test_paused_case_tasks_are_absent_from_full_shell_and_attention(tmp_path, monkeypatch):
    with home_client(tmp_path, monkeypatch) as client:
        full = client.get('/api/workspace').json(); shell = client.get('/api/workspace?scope=shell').json()
        assert {p['id']: p['execution_status'] for p in full['projects'][:3]} == {'p001': 'paused', 'p002': 'in_progress', 'p003': 'paused'}
        c = shell['counts']
        assert (c['overdue_tasks'], c['my_overdue_tasks'], c['due_today_tasks']) == (2, 2, 1)
        assert [a['task_id'] for a in shell['attention']] == ['lv-late1', 'lv-late2', 'lv-today']
        assert not {a['project_id'] for a in shell['attention']} & {'p001', 'p003'}


def test_unassigned_and_other_owner_tasks_do_not_count_on_an_enabled_case(tmp_path, monkeypatch):
    with home_client(tmp_path, monkeypatch) as client:
        shell = client.get('/api/workspace?scope=shell').json()
        ids = {a['task_id'] for a in shell['attention']}
        assert not ids & {'lv-unassigned', 'lv-other', 'lv-done'}
        assert shell['counts']['overdue_tasks'] == shell['counts']['my_overdue_tasks'] == 2


def test_enabled_assigned_tasks_still_appear_with_exact_counts(tmp_path, monkeypatch):
    with home_client(tmp_path, monkeypatch) as client:
        shell = client.get('/api/workspace?scope=shell').json()
        assert [(a['task_id'], a['project_id']) for a in shell['attention']] == [('lv-late1', 'p002'), ('lv-late2', 'p002'), ('lv-today', 'p002')]
        assert shell['counts']['due_today_tasks'] == 1


def test_sidebar_dashboard_and_shell_counts_are_identical(tmp_path, monkeypatch):
    with home_client(tmp_path, monkeypatch) as client:
        full = client.get('/api/workspace').json(); shell = client.get('/api/workspace?scope=shell').json()
        rule = home_rule(full); c = shell['counts']
        assert rule['overdue'] == c['overdue_tasks'] == c['my_overdue_tasks'] == 2  # sidebar badge reads my_overdue_tasks (shell) or the rule (full)
        assert rule['due_today'] == c['due_today_tasks'] == 1
        assert rule['attention'] == [a['task_id'] for a in shell['attention']]


def test_shell_keeps_assigned_paused_and_correction_work_visible(tmp_path, monkeypatch):
    def mutate(state):
        shape(state)
        state['projects'][1]['nodes'][0]['tasks'].append(task('lv-rework', VIEWER, '2026-10-20', 'rework'))
    with home_client(tmp_path, monkeypatch, mutate) as client:
        shell = client.get('/api/workspace?scope=shell').json()
        waiting = shell['home_waiting']
        ids = {item['task_id'] for item in waiting}
        assert {'pz-late1', 'pz-late2', 'pz-today', 'lv-rework'} <= ids
        assert not ids & {'lv-other', 'lv-unassigned', 'tp-late'}
        assert all(item['reason'] for item in waiting)


def test_full_shell_waiting_categories_and_actionable_counts_match(tmp_path, monkeypatch):
    def mutate(state):
        shape(state)
        node = state['projects'][1]['nodes'][0]
        node['tasks'].append({**task('lv-waiting', VIEWER, None), 'input_task_ids': ['missing-upstream']})
        node['tasks'].append(task('lv-correction', VIEWER, '2026-10-20', 'rework'))
        node['tasks'].append({**task('lv-upcoming', VIEWER, '2026-10-24'), 'start_date': '2026-10-20'})
    with home_client(tmp_path, monkeypatch, mutate) as client:
        full = client.get('/api/workspace').json(); shell = client.get('/api/workspace?scope=shell').json()
        visible = [(p, n, t) for p in full['projects'] for n in p['nodes'] for t in n['tasks']
                   if t.get('assigned_to_viewer') and t['status'] not in ('completed', 'superseded')]
        kinds = []
        for p, n, t in visible:
            kind = ('paused' if p['execution_status'] == 'paused' or t['status'] == 'paused' else
                    'correction' if t['status'] == 'rework' else
                    'upcoming' if t.get('start_date') and t['start_date'] > AS_OF else
                    'prerequisite' if t.get('execution_blockers') or t.get('activation_blockers') else
                    'upcoming' if t.get('due_date') and t['due_date'] > AS_OF else None)
            if kind: kinds.append((kind, t['id']))
        assert [(item['kind'], item['task_id']) for item in shell['home_waiting']] == kinds
        assert [item['task_id'] for item in shell['attention']] == ['lv-late1', 'lv-late2', 'lv-today']
        assert (shell['counts']['my_active_tasks'], shell['counts']['my_overdue_tasks'], shell['counts']['due_today_tasks']) == (4, 2, 1)
        assert shell['home_waiting_counts'] == {'paused': 3, 'prerequisite': 1, 'correction': 1, 'upcoming': 1}


def test_demo_future_start_uses_data_date_in_full_and_shell(tmp_path, monkeypatch):
    def mutate(state):
        shape(state)
        for project in state['projects']:
            project['source_kind'] = 'demo'
        state['projects'][1]['nodes'][0]['tasks'].append({**task('between-data-and-wall-clock', VIEWER, '2026-10-21'),
            'start_date': '2026-10-10'})
    with home_client(tmp_path, monkeypatch, mutate, clock='2026-10-13') as client:
        full = client.get('/api/workspace').json(); shell = client.get('/api/workspace?scope=shell').json()
        assert full['as_of'][:10] == shell['as_of'][:10] == AS_OF
        task_row = next(t for p in full['projects'] for n in p['nodes'] for t in n['tasks'] if t['id'] == 'between-data-and-wall-clock')
        assert task_row['assigned_to_viewer'] and '尚未到排程日期' in task_row['activation_blockers']
        assert ('upcoming', 'between-data-and-wall-clock') in [(item['kind'], item['task_id']) for item in shell['home_waiting']]


def test_valid_current_proxy_stays_visible_on_historical_data_date(tmp_path, monkeypatch):
    from . import workflow
    monkeypatch.setattr(workflow, 'now', lambda: '2026-10-13T09:00:00+08:00')
    def mutate(state):
        shape(state)
        for project in state['projects']:
            project['source_kind'] = 'demo'
        state.setdefault('delegations', []).append(dict(id='current-proxy',project_id='p002',principal_id=OTHER,delegate_id=VIEWER,
            seat='owner',scope='tasks',status='active',start_date='2026-10-10',end_date='2026-10-20',task_ids=['lv-other'],
            qualified=True,qualification_evidence='verified',source='supervisor',qualification_note='代理期間已核對'))
    with home_client(tmp_path, monkeypatch, mutate, clock='2026-10-13') as client:
        full = client.get('/api/workspace').json(); shell = client.get('/api/workspace?scope=shell').json()
        assert full['as_of'][:10] == shell['as_of'][:10] == AS_OF
        task_row = next(t for p in full['projects'] for n in p['nodes'] for t in n['tasks'] if t['id'] == 'lv-other')
        assert task_row['assigned_to_viewer']
        proxy = next(item for item in shell['home_waiting'] if item['task_id'] == 'lv-other')
        assert proxy['kind'] == 'proxy' and '2026-10-10 至 2026-10-20' in proxy['reason']
