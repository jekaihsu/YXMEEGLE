"""Issue #57: pilot snapshots retain downloadable, verified attachment versions."""
import hashlib
from copy import deepcopy

import pytest
from sqlalchemy import select

from . import storage
from .app import AuditRow, BusinessRow, WorkspaceRow
from .test_production_access import company


def snapshot(app, wid):
    with app.state.sessions() as db:
        row = db.get(WorkspaceRow, wid)
        return row.version, deepcopy(storage.load(db, BusinessRow, row))


def prepare_uploads(tmp_path, empty_target=False):
    app, client = company(tmp_path)
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, 'lark-company')
        state = storage.load(db, BusinessRow, row)
        project = state['projects'][0]
        project.update(pm_id='u-manager', execution_system='workbench', case_visibility='new_case', files=[])
        pid = project['id']
        row.data = storage.save(db, BusinessRow, row.id, state)
        if empty_target:
            target = db.get(WorkspaceRow, 'test-lark-company')
            state = storage.load(db, BusinessRow, target)
            state['projects'] = []
            target.data = storage.save(db, BusinessRow, target.id, state)
    assert client.post('/api/workspace/switch', json={'environment': 'production'}).status_code == 200
    payloads = [b'formal proof version one', b'formal proof version two']
    files = []
    for payload in payloads:
        ws = client.get('/api/workspace').json()
        response = client.post('/api/files', data={
            'project_id': pid, 'direction': 'evidence', 'version': ws['version'],
            'file_key': files[0]['file_key'] if files else '',
        }, files={'file': ('synthetic-pilot.txt', payload, 'text/plain')})
        assert response.status_code == 200, response.text
        project = next(p for p in response.json()['projects'] if p['id'] == pid)
        files.append(project['files'][-1])
    return app, client, pid, files, payloads


@pytest.mark.parametrize('empty_target', [True, False])
def test_http_pilot_snapshot_preserves_all_local_versions_and_formal_state(tmp_path, empty_target):
    app, client, pid, files, payloads = prepare_uploads(tmp_path, empty_target)
    before = snapshot(app, 'lark-company')
    for item, payload in zip(files, payloads):
        response = client.get(item['url'])
        assert response.status_code == 200 and response.content == payload
    response = client.post('/api/pilot/copy', json={'project_id': pid})
    assert response.status_code == 200, response.text
    assert client.post('/api/workspace/switch', json={'environment': 'test'}).status_code == 200
    ws = client.get('/api/workspace').json()
    copied = next(p for p in ws['projects'] if p['id'] == response.json()['project_id'])
    assert copied['files'] == files
    assert [f['version'] for f in copied['files']] == ['1', '2']
    target = app.state.upload_dir / hashlib.sha256(b'test-lark-company').hexdigest()
    for item, payload in zip(copied['files'], payloads):
        assert item['storage'] == 'local'
        assert hashlib.sha256((target / item['id']).read_bytes()).hexdigest() == item['sha256']
        download = client.get(item['url'])
        assert download.status_code == 200 and download.content == payload
    assert snapshot(app, 'lark-company') == before
    assert client.post('/api/workspace/switch', json={'environment': 'production'}).status_code == 200
    for item, payload in zip(files, payloads):
        download = client.get(item['url'])
        assert download.status_code == 200 and download.content == payload


@pytest.mark.parametrize('failure', ['missing', 'size', 'sha256', 'database'])
def test_failed_pilot_copy_rolls_back_snapshot_and_copied_bytes(tmp_path, monkeypatch, failure):
    app, client, pid, files, payloads = prepare_uploads(tmp_path)
    source = app.state.upload_dir / hashlib.sha256(b'lark-company').hexdigest()
    last = source / files[-1]['id']
    if failure == 'missing':
        last.unlink()
    elif failure == 'size':
        last.write_bytes(b'x')
    elif failure == 'sha256':
        last.write_bytes(b'x' * len(payloads[-1]))
    before_source = snapshot(app, 'lark-company')
    before_target = snapshot(app, 'test-lark-company')
    source_bytes = {p.name: p.read_bytes() for p in source.iterdir()}
    target = app.state.upload_dir / hashlib.sha256(b'test-lark-company').hexdigest()
    target.mkdir(exist_ok=True)
    sentinel = target / 'existing-unrelated-file'
    sentinel.write_bytes(b'keep')
    if failure == 'database':
        save = storage.save

        def fail_after_save(db, model, wid, state):
            result = save(db, model, wid, state)
            if wid == 'test-lark-company':
                raise RuntimeError('synthetic database failure')
            return result

        monkeypatch.setattr(storage, 'save', fail_after_save)
        with pytest.raises(RuntimeError, match='synthetic database failure'):
            client.post('/api/pilot/copy', json={'project_id': pid})
    else:
        response = client.post('/api/pilot/copy', json={'project_id': pid})
        assert response.status_code == 409, response.text
        assert response.json()['detail'] == {
            'missing': '正式附件檔案不存在', 'size': '正式附件大小不符',
            'sha256': '正式附件校驗失敗',
        }[failure]
    assert snapshot(app, 'lark-company') == before_source
    assert snapshot(app, 'test-lark-company') == before_target
    assert {p.name: p.read_bytes() for p in source.iterdir()} == source_bytes
    assert {p.name: p.read_bytes() for p in target.iterdir()} == {sentinel.name: b'keep'}
    with app.state.sessions() as db:
        assert not any(row.action == 'pilot_copy' for row in db.scalars(select(AuditRow)))
