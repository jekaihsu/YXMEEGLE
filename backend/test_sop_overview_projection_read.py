"""The intake overview reads the case's own slice of the workspace, with the node answers the full load gave."""
import json

from . import storage
from .models import BusinessRow
from .sop_import import local_nodes
from .test_sop_local_nodes import local, setup, change_workspace, prepare_completion, call  # noqa: F401


def full_load_reference(db, root, ctx):
    workspace = storage.load(db, BusinessRow, root)
    return workspace, next(p for p in workspace['projects'] if p['id'] == ctx.project['id'])


def test_intake_overview_does_not_load_the_whole_workspace(local, monkeypatch):
    app, client, signin, pid, url = setup(local)
    signin('u-manager')
    calls = []
    real = storage.load
    monkeypatch.setattr(storage, 'load', lambda *a, **k: calls.append(1) or real(*a, **k))
    assert call(client, 'GET', url + '/sop-tasks')['local_nodes']
    assert calls == []


def test_node_answers_match_the_full_load_for_every_node_and_state(local, monkeypatch):
    app, client, signin, pid, url = setup(local)
    change_workspace(app, prepare_completion)
    signin('u-manager')

    def same_as_full_load():
        ours = json.dumps(call(client, 'GET', url + '/sop-tasks')['local_nodes'], sort_keys=True, ensure_ascii=False)
        with monkeypatch.context() as patch:
            patch.setattr(local_nodes, 'case_workspace', full_load_reference)
            assert ours == json.dumps(call(client, 'GET', url + '/sop-tasks')['local_nodes'], sort_keys=True, ensure_ascii=False)
        return json.loads(ours)

    fresh = same_as_full_load()
    assert len(fresh) == 9 and any(n['complete_disabled_reason'] for n in fresh)
    call(client, 'POST', url + '/sop-nodes/sales', {'action': 'assign', 'expected_revision': 0, 'owner_id': 'u-field'})
    assigned = same_as_full_load()
    assert assigned[0]['owner_id'] == 'u-field' and assigned != fresh
