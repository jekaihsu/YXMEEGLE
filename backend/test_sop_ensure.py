from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select, func
from .test_sop_import import h, URL
from .sop_import.models import LocalTask, ImportRun, Family


def test_ensure_once_and_reads_do_not_write(h):
    with h.sessions() as db:
        assert db.scalar(select(func.count()).select_from(LocalTask)) == 0
    assert h.client.get(URL + '/sop-tasks').status_code == 200
    with h.sessions() as db:
        assert db.scalar(select(func.count()).select_from(LocalTask)) == 0
    assert h.client.post(URL + '/sop/ensure').json() == {'state': 'started'}
    with h.sessions() as db:
        ids = list(db.scalars(select(LocalTask.id).order_by(LocalTask.id)))
    assert len(ids) == 38
    assert h.client.post(URL + '/sop/ensure').json() == {'state': 'already_started'}
    with h.sessions() as db:
        assert list(db.scalars(select(LocalTask.id).order_by(LocalTask.id))) == ids
        assert db.scalar(select(func.count()).select_from(ImportRun)) == 1


def test_ensure_concurrent(h):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: h.client.post(URL + '/sop/ensure').json(), range(2)))
    assert sorted(r['state'] for r in results) == ['already_started', 'started']
    with h.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ImportRun)) == 1
        keys = list(db.scalars(select(LocalTask.source_row_key)))
        assert len(keys) == len(set(keys))


def test_ensure_viewer(h):
    h.who[0] = 'member'
    assert h.client.post(URL + '/sop/ensure').json() == {'state': 'not_permitted', 'reason': 'sop_import_forbidden'}
    with h.sessions() as db:
        assert db.scalar(select(func.count()).select_from(LocalTask)) == 0


def test_ensure_flags_and_template(h):
    h.cfg['SOP_TASK_WRITES_ENABLED'] = 'false'
    assert h.client.post(URL + '/sop/ensure').json() == {'state': 'not_ready', 'reason': 'writes_disabled'}
    h.cfg['SOP_TASK_WRITES_ENABLED'] = 'true'
    with h.sessions.begin() as db:
        for family in db.scalars(select(Family)):
            family.lifecycle = 'retired'
    assert h.client.post(URL + '/sop/ensure').json() == {'state': 'not_ready', 'reason': 'no_template'}


def test_ensure_matches_default_preview(h):
    preview = h.client.post(URL + '/sop-import/preview', json={'template_version_id': h.vid}).json()
    selected = sorted(preview['selection']['row_keys'])
    assert h.client.post(URL + '/sop/ensure').json() == {'state': 'started'}
    with h.sessions() as db:
        assert sorted(db.scalars(select(LocalTask.source_row_key))) == selected


def test_ensure_does_not_opt_in_legacy(h):
    from .sop_import.models import CasePolicy
    with h.sessions.begin() as db:
        db.add(CasePolicy(workspace_id='w', project_id='p1', policy='legacy', revision=1,
                          decided_by='manager', decided_at=100, reason='existing', facts={}, node_keys=[]))
    assert h.client.post(URL + '/sop/ensure').json() == {'state': 'not_ready', 'reason': 'legacy_case_requires_opt_in'}
    with h.sessions() as db:
        assert db.get(CasePolicy, ('w', 'p1')).policy == 'legacy'
        assert db.scalar(select(func.count()).select_from(LocalTask)) == 0
