import pytest
from sqlalchemy import event
from .test_sop_lark_projection import p
from .test_sop_import import h, apply, URL
from .sop_import import lark_projection as projection


def test_unknown_project_has_friendly_cli_error(p, monkeypatch, capsys):
    from .models import WorkspaceRow
    from .seed import seed
    with p.sessions.begin() as db:
        state = seed()
        state.pop('environment', None)
        state['projects'] = []
        db.get(WorkspaceRow, 'lark-org').data = state
    monkeypatch.setenv('LARK_WORKER_ORGANIZATION', 'org')
    monkeypatch.setenv('LARK_ALLOWED_TENANTS', 'org')
    monkeypatch.setattr('sys.argv', ['projection', '--database-url', str(p.engine.url), '--workspace', 'lark-org', '--check', 'missing'])
    with pytest.raises(SystemExit) as error:
        projection.main()
    assert error.value.code == 2
    assert 'Project not found' in capsys.readouterr().err


def test_task_list_batches_projection_status_reads(h):
    apply(h)
    h.service.projection = projection.Projection(h.sessions, h.cfg, lambda wid: {})
    selects = []
    engine = h.sessions.kw['bind']
    def count(connection, cursor, statement, parameters, context, many):
        if statement.startswith('SELECT') and 'sop_lark_outbox' in statement:
            selects.append(statement)
    event.listen(engine, 'before_cursor_execute', count)
    try:
        response = h.client.get(URL + '/sop-tasks')
    finally:
        event.remove(engine, 'before_cursor_execute', count)
    assert response.status_code == 200 and len(response.json()['tasks']) > 1
    assert len(selects) <= 1


def test_shared_seal_preserves_partial_load_fallback(p):
    from . import storage
    from .models import BusinessRow, WorkspaceRow
    from .workspace_seal import seal
    with p.sessions.begin() as db:
        db.add(BusinessRow(workspace_id='lark-org', kind='projects', entity_id='legacy', parent_id='', ordinal=0,
                           data={'id': 'legacy', 'source_kind': 'lark'}))
    with p.sessions() as db, pytest.raises(storage.PartialUnavailable):
        seal(db, db.get(WorkspaceRow, 'lark-org'), {'environment': 'production', 'projects': [], 'users': []},
             {**p.cfg, 'LARK_ALLOWED_TENANTS': 'org'}, scoped=True)
