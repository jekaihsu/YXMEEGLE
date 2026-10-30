"""A scoped case read keeps rows shared with another visible case, exactly as a full load does."""
from .test_p2_int_routes import http, build_state  # noqa: F401
from . import storage

def test_scoped_case_detail_keeps_rows_shared_with_another_visible_case(http, monkeypatch):
    app, client, seat, signin = http
    state, pid, hid = build_state()
    other = state['projects'][2]
    other.update(case_visibility='new_case', execution_system='workbench', source_kind='lark')
    k = next(c for c in state['contract_items'] if c['id'].endswith('recK1'))
    k['task_refs'] = [{'project_id': other['id'], 'task_id': 'x'}]
    state['source_confirmations'][0]['project_ids'] = [pid, other['id']]
    seat(state); signin()
    real = storage.load_partial
    a = client.get(f'/api/case-detail/{pid}')
    def full(db, model, row, **kw):
        return storage.load(db, model, row) if kw.get('project_ids') is not None else real(db, model, row, **kw)
    monkeypatch.setattr(storage, 'load_partial', full)
    b = client.get(f'/api/case-detail/{pid}')
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
