import json
import httpx
import pytest

from .models import WorkspaceRow
from .sop_import.lark_projection import Projection, ProjectionClient
from .test_sop_lark_projection import p
from scripts import sop_v4_canary as canary


def test_canary_is_inert_without_explicit_yes(tmp_path, monkeypatch):
    monkeypatch.setattr('sys.argv', ['sop_v4_canary.py', '--database-url', 'sqlite://', '--manifest', str(tmp_path / 'receipt.json')])
    with pytest.raises(SystemExit) as exc:
        canary.main()
    assert exc.value.code == 2
    assert not (tmp_path / 'receipt.json').exists()


def test_canary_and_cleanup_with_injected_fake_only(p, tmp_path, monkeypatch):
    for key, value in p.cfg.items():
        monkeypatch.setenv(key, value)
    with p.sessions.begin() as db:
        db.get(WorkspaceRow, 'lark-org').data = {'storage_schema': 2, 'environment': 'production',
                                              'settings': {'external_enabled': True}}
    monkeypatch.setattr(canary, 'Projection', lambda sessions, cfg, load: Projection(sessions, cfg, load, transport=httpx.MockTransport(p.fake)))
    monkeypatch.setattr(canary, 'ProjectionClient', lambda cfg, **kwargs: ProjectionClient(cfg, httpx.MockTransport(p.fake), **kwargs))
    manifest = tmp_path / 'canary.json'
    args = ['sop_v4_canary.py', '--yes', '--database-url', str(p.engine.url), '--manifest', str(manifest)]
    monkeypatch.setattr('sys.argv', args)
    canary.main()
    recorded = json.loads(manifest.read_text())
    assert len(p.fake.records) == 3
    assert set(recorded['record_ids']) == set(p.fake.records)
    assert all(r['fields']['專案編號'] == canary.PROJECT for r in p.fake.records.values())
    monkeypatch.setattr('sys.argv', args + ['--cleanup'])
    canary.main()
    assert p.fake.records == {}
    with p.sessions() as db:
        assert all(row.state == 'paused' for row in p.worker.current_rows(db, 'lark-org', canary.PROJECT))


def test_cleanup_refuses_unrecorded_row(p, tmp_path, monkeypatch):
    for key, value in p.cfg.items():
        monkeypatch.setenv(key, value)
    with p.sessions.begin() as db:
        db.get(WorkspaceRow, 'lark-org').data = {'storage_schema': 2, 'environment': 'production',
                                              'settings': {'external_enabled': True}}
    monkeypatch.setattr(canary, 'ProjectionClient', lambda cfg, **kwargs: ProjectionClient(cfg, httpx.MockTransport(p.fake), **kwargs))
    p.fake.records = {'recExtra': {'record_id': 'recExtra', 'fields': {'專案編號': canary.PROJECT}}}
    manifest = tmp_path / 'canary.json'
    manifest.write_text(json.dumps({'workspace_id': 'lark-org', 'project_id': canary.PROJECT, 'record_ids': []}))
    monkeypatch.setattr('sys.argv', ['sop_v4_canary.py', '--yes', '--cleanup', '--database-url', str(p.engine.url), '--manifest', str(manifest)])
    with pytest.raises(RuntimeError, match='Cleanup scope'):
        canary.main()
    assert 'recExtra' in p.fake.records
    assert not any(call[0] == 'DELETE' for call in p.fake.calls)
