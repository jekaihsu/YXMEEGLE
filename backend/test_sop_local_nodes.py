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
