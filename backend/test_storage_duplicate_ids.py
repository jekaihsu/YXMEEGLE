from copy import deepcopy
import pytest
from sqlalchemy import select
from .test_backend import app, client
from .app import WorkspaceRow, BusinessRow
from . import storage


def _wid(app,client): return app.state.signer.loads(client.cookies.get('meegle_session'))['wid']


def _snapshot(db,wid):
    return sorted((r.kind,r.entity_id,r.parent_id,r.ordinal,repr(r.data)) for r in db.scalars(select(BusinessRow).where(BusinessRow.workspace_id==wid)))


def _reject(app,client,mutate,match):
    wid=_wid(app,client)
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,wid)
        before=_snapshot(db,wid); before_root=deepcopy(row.data); before_version=row.version
        state=storage.load(db,BusinessRow,row)
    mutate(state)
    invalid_state=deepcopy(state)
    with app.state.sessions.begin() as db:
        with pytest.raises(ValueError,match=match): storage.save(db,BusinessRow,wid,state)
        # Commit after catching the error so rollback cannot hide partial writes.
        assert not db.new and not db.dirty and not db.deleted
        assert state==invalid_state
    with app.state.sessions.begin() as db:
        assert _snapshot(db,wid)==before
        row=db.get(WorkspaceRow,wid)
        assert row.data==before_root and row.version==before_version


def test_duplicate_user_id_rejected_without_changing_db(app,client):
    def dup(state): state['users'].append({**state['users'][0],'name':'other'})
    _reject(app,client,dup,r'kind=users id=')


def test_duplicate_id_does_not_insert_migration_archive(app,client):
    def dup(state):
        state['migration_archive']={'synthetic':'legacy snapshot'}
        state['users'].extend([{'id':'duplicate-user','name':'first'},
                               {'id':'duplicate-user','name':'second'}])
    _reject(app,client,dup,r'kind=users id=duplicate-user')


def test_duplicate_nested_task_id_rejected(app,client):
    def dup(state):
        tasks=state['projects'][0]['nodes'][0]['tasks']; tasks.append(deepcopy(tasks[0]))
    _reject(app,client,dup,'kind=tasks')


def test_duplicate_task_id_across_nodes_rejected(app,client):
    def dup(state):
        nodes=state['projects'][0]['nodes']; nodes[1]['tasks'].append(deepcopy(nodes[0]['tasks'][0]))
    _reject(app,client,dup,'kind=tasks')


def test_duplicate_node_id_rejected(app,client):
    def dup(state):
        nodes=state['projects'][0]['nodes']; nodes.append(deepcopy(nodes[0]))
    _reject(app,client,dup,'kind=nodes')


def test_same_id_across_different_kinds_allowed(app,client):
    wid=_wid(app,client)
    with app.state.sessions.begin() as db:
        state=storage.load(db,BusinessRow,db.get(WorkspaceRow,wid))
        shared=state['users'][0]['id']
        state['projects'][0]['files'].append({'id':shared}); state['events'].append({'id':shared})
        row=db.get(WorkspaceRow,wid)
        row.data=storage.save(db,BusinessRow,wid,state)
    with app.state.sessions.begin() as db:
        saved=storage.load(db,BusinessRow,db.get(WorkspaceRow,wid))
        assert any(u['id']==shared for u in saved['users'])
        assert any(f['id']==shared for f in saved['projects'][0]['files'])
        assert any(e['id']==shared for e in saved['events'])
