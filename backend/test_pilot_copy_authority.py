"""A pilot copy cannot outlive the actor's company-manager role."""
import pytest
from .test_staff_oauth_acceptance import staff
from .test_review_mutation_authority import prepare
from .app import WorkspaceRow, BusinessRow
from . import storage


@pytest.mark.parametrize('revoke', [False, True])
def test_pilot_copy_rechecks_manager_before_copying(staff, monkeypatch, revoke):
    app, client = prepare(staff)
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, 'lark-company')
        state = storage.load(db, BusinessRow, row)
        state['projects'][0]['files'] = []
        row.data = storage.save(db, BusinessRow, row.id, state)
    from . import app as module
    original = module.json_object
    async def read_body(request):
        result = await original(request)
        if revoke:
            staff[3]({'role': 'member', 'capabilities': []})
        return result
    monkeypatch.setattr(module, 'json_object', read_body)
    response = client.post('/api/pilot/copy', json={'project_id': 'p1'})
    assert response.status_code == (403 if revoke else 200)
    with app.state.sessions() as db:
        target = db.get(WorkspaceRow, 'test-lark-company')
        state = storage.load(db, BusinessRow, target)
    if revoke:
        assert state['projects'] == []
        assert target.version == 1
    else:
        assert len(state['projects']) == 1
        assert state['projects'][0]['pilot_source_id'] == 'p1'
        assert state['projects'][0]['pm_id'] == 'ou_staff'
        assert target.version == 2
