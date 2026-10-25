from sqlalchemy import select

from .models import AuditRow
from .test_sop_local_case import local, create, FORM, call, persisted


def setup(local, import_tasks=False):
    app, client, signin, _ = local
    draft, _ = create(client, {**FORM, 'import_tasks': import_tasks})
    pid = draft['case']['project_id']
    signin('u-pm')
    return app, client, signin, pid, f'/api/projects/{pid}'


def test_assign_complete_reopen_is_local_revision_checked_and_audited(local):
    app, client, signin, pid, url = setup(local)
    change_workspace(app, prepare_completion)
    nodes = call(client, 'GET', url + '/sop-tasks')['local_nodes']
    assert len(nodes) == 9 and nodes[0]['can']['complete']
    path = url + '/sop-nodes/sales'
    call(client, 'POST', path, {'action': 'assign', 'expected_revision': 0, 'owner_id': 'u-field'})
    call(client, 'POST', path, {'action': 'complete', 'expected_revision': 0, 'reason': '核對完成'}, 409)
    call(client, 'POST', path, {'action': 'complete', 'expected_revision': 1, 'reason': '核對完成'})
    [case], _, _ = persisted(app)
    assert case['nodes'][0]['status'] == 'completed'
    assert case['nodes'][0]['owner_id'] == 'u-field'
    call(client, 'POST', path, {'action': 'reject', 'expected_revision': 2, 'reason': '補充資料'})
    [case], _, _ = persisted(app)
    assert case['nodes'][0]['status'] == 'in_progress'
    with app.state.sessions() as db:
        events = list(db.scalars(select(AuditRow).where(AuditRow.action.like('local_node_%'))))
    assert len(events) == 3 and all(e.data['project_id'] == pid for e in events)


def test_tasks_financial_gates_authority_and_flag_remain_enforced(local):
    app, client, signin, pid, url = setup(local, True)
    nodes = call(client, 'GET', url + '/sop-tasks')['local_nodes']
    assert not nodes[0]['can']['complete']
    call(client, 'POST', url + '/sop-nodes/sales', {'action': 'complete', 'expected_revision': 0, 'reason': '略過'}, 409)
    call(client, 'POST', url + '/sop-nodes/pricing', {'action': 'complete', 'expected_revision': 0, 'reason': '核對'}, 409)
    signin('u-field')
    call(client, 'POST', url + '/sop-nodes/sales', {'action': 'assign', 'expected_revision': 0, 'owner_id': 'u-field'}, 403)
    signin('u-pm')
    app.state.sop_import.writes_enabled = lambda: False
    call(client, 'POST', url + '/sop-nodes/sales', {'action': 'assign', 'expected_revision': 0, 'owner_id': 'u-field'}, 503)


def test_local_command_refuses_blank_reasons(local):
    app, client, signin, pid, url = setup(local)
    call(client, 'POST', url + '/sop-nodes/sales', {'action': 'complete', 'expected_revision': 0, 'reason': '  '}, 422)


def test_formal_case_cannot_use_local_completion(local):
    app, client, signin, ids = local
    signin('u-manager')
    with app.state.sessions() as db:
        from .models import BusinessRow
        from .test_sop_quotes import WID
        formal = next(r.entity_id for r in db.scalars(select(BusinessRow).where(BusinessRow.workspace_id == WID, BusinessRow.kind == 'projects')) if r.data.get('case_visibility') == 'source_reference' and r.data.get('case_type') != 'intake')
    call(client, 'POST', f'/api/projects/{formal}/sop-nodes/sales', {'action':'complete', 'expected_revision':0, 'reason':'核對'}, 409)


def change_workspace(app, change):
    from . import storage
    from .models import BusinessRow, WorkspaceRow
    from .test_sop_quotes import WID
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, WID)
        state = storage.load(db, BusinessRow, row)
        change(state)
        row.data = storage.save(db, BusinessRow, WID, state)


def prepare_completion(state):
    state['people_directory_status'] = {'app_id': 'local-test'}
    for user in state['users']:
        user.update(directory_status='employed', directory_source={'app_id': 'local-test', 'record_id': user['id']})
    case = next(p for p in state['projects'] if p.get('planning_origin') == 'local')
    node = case['nodes'][0]
    case['evidence'] = [{'id': rule['key'], 'node_id': node['id'], 'key': rule['key'], 'status': 'accepted'} for rule in node['requirements']]


def test_completion_exposes_and_enforces_legacy_missing_reason(local):
    app, client, signin, pid, url = setup(local)
    node = call(client, 'GET', url + '/sop-tasks')['local_nodes'][0]
    assert not node['can']['complete']
    assert node['complete_disabled_reason'].startswith('尚未完成：')
    failed = call(client, 'POST', url + '/sop-nodes/sales', {'action': 'complete', 'expected_revision': 0, 'reason': '核對'}, 409)
    assert failed['reason'] == node['complete_disabled_reason']


def test_financial_and_skipped_nodes_cannot_be_rejected_or_completed(local):
    app, client, signin, pid, url = setup(local)
    def completed(state):
        case = next(p for p in state['projects'] if p['id'] == pid)
        for n in case['nodes']:
            n['status'] = 'approved_skipped' if n['key'] == 'sales' else 'completed'
    change_workspace(app, completed)
    for key in ('pricing', 'settlement', 'sales'):
        for action in ('reject', 'complete'):
            call(client, 'POST', url + '/sop-nodes/' + key, {'action': action, 'expected_revision': 0, 'reason': '核對'}, 409)
    call(client, 'POST', url + '/sop-nodes/pm', {'action': 'assign', 'expected_revision': 0, 'owner_id': 'u-field'}, 409)


def test_assignment_requires_active_production_admission_and_cascades(local):
    app, client, signin, pid, url = setup(local)
    path = url + '/sop-nodes/sales'
    call(client, 'POST', path, {'action': 'assign', 'expected_revision': 0, 'owner_id': 'u-field'}, 409)
    change_workspace(app, prepare_completion)
    change_workspace(app, lambda state: next(u for u in state['users'] if u['id'] == 'u-field').update(active=False))
    call(client, 'POST', path, {'action': 'assign', 'expected_revision': 0, 'owner_id': 'u-field'}, 409)
    def with_tasks(state):
        next(u for u in state['users'] if u['id'] == 'u-field')['active'] = True
        case = next(p for p in state['projects'] if p['id'] == pid)
        case['nodes'][0]['tasks'] = [{'id': 'inherited', 'status': 'pending', 'owner_id': '', 'owner_inherited': True, 'required': False},
                                   {'id': 'explicit', 'status': 'pending', 'owner_id': 'u-pm', 'owner_inherited': False, 'required': False}]
    change_workspace(app, with_tasks)
    call(client, 'POST', path, {'action': 'assign', 'expected_revision': 0, 'owner_id': 'u-field'})
    [case], _, _ = persisted(app)
    assert [t['owner_id'] for t in case['nodes'][0]['tasks']] == ['u-field', 'u-pm']


def test_policy_block_disables_local_actions_with_same_write_reason(local):
    from .sop_import.models import CasePolicy
    from .test_sop_quotes import WID
    app, client, signin, pid, url = setup(local)
    with app.state.sessions.begin() as db:
        db.delete(db.get(CasePolicy, (WID, pid)))
    app.state.sop_import.auto_active = lambda: True
    for policy, keys, expected in ((None, [], 'legacy_case_requires_opt_in'), ('managed', ['pm'], 'node_not_enrolled')):
        if policy:
            with app.state.sessions.begin() as db:
                db.add(CasePolicy(workspace_id=WID, project_id=pid, policy=policy, node_keys=keys, revision=1, decided_by='u-pm', decided_at=0, reason='測試', facts={}))
        node = call(client, 'GET', url + '/sop-tasks')['local_nodes'][0]
        assert not any(node['can'].values())
        failed = call(client, 'POST', url + '/sop-nodes/sales', {'action': 'assign', 'expected_revision': 0, 'owner_id': 'u-field'}, 409)
        assert failed['code'] == expected
        assert failed['reason'] == node['disabled_reason']


def test_technical_completion_requires_distinct_active_review_seats(local, monkeypatch):
    app, client, signin, pid, url = setup(local)
    monkeypatch.setattr('backend.sop_import.local_nodes.missing', lambda p, n, ws: [])
    node = next(n for n in call(client, 'GET', url + '/sop-tasks')['local_nodes'] if n['key'] == 'field')
    assert not node['can']['complete']
    assert '確認人尚未完整分派' in node['complete_disabled_reason']
    call(client, 'POST', url + '/sop-nodes/field', {'action': 'complete', 'expected_revision': 0, 'reason': '核對'}, 409)
