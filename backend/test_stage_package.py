"""Packaging acceptance must run outside the source checkout's import path."""
import json
import hashlib
from pathlib import Path
import shutil
import pytest

from scripts import deploy_prepare
from scripts.verify_stage_package import verify_stage
from scripts.stage_inventory import verify_stage_inventory


def test_staged_app_and_catalog_work_without_repository_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy_prepare, 'RUNTIME', tmp_path)
    stage = deploy_prepare.staging()
    assert (stage / 'backend' / 'sop_source_contracts.json').is_file()
    manifest = json.loads((tmp_path / 'zeabur-stage-manifest.json').read_text())
    assert any(f['path'] == 'backend/sop_source_contracts.json' for f in manifest['files'])
    receipt = json.loads((tmp_path / (stage.name + '-smoke.json')).read_text())
    assert receipt['ok'] and receipt['checks']['workspace'] and receipt['inventory_sha256']
    assert (tmp_path / (stage.name + '-manifest.json')).is_file()
    # Even poisoned production settings must not reach the isolated probe.
    monkeypatch.setenv('DATABASE_URL', 'postgresql://do-not-connect.invalid/production')
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('LARK_APP_SECRET', 'must-not-leak')
    result = verify_stage(stage)
    assert result['ok'], result
    assert result['checks']['workspace'] and result['checks']['staged_imports_only']
    assert not list(stage.rglob('*.db'))
    assert not list(stage.rglob('__pycache__'))


def test_missing_staged_catalog_fails_even_when_checkout_has_it(tmp_path):
    backend = Path(deploy_prepare.ROOT) / 'backend'
    stage = tmp_path / 'incomplete'
    destination = stage / 'backend'
    destination.mkdir(parents=True)
    for source in backend.glob('*.py'):
        if not source.name.startswith('test_'):
            shutil.copyfile(source, destination / source.name)
    assert (backend / 'sop_source_contracts.json').is_file()
    result = verify_stage(stage)
    assert result == {'ok': False, 'reason': 'missing_sop_source_contracts', 'returncode': 1}


def test_stage_inventory_rejects_extra_or_missing_files(tmp_path):
    stage = tmp_path / 'stage'
    stage.mkdir()
    payload = b'reviewed'
    (stage / 'app.py').write_bytes(payload)
    entry = {'path': 'app.py', 'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
    verify_stage_inventory(stage, [entry])
    (stage / 'private.json').write_text('{"unreviewed":true}')
    with pytest.raises(ValueError, match='inventory differs'):
        verify_stage_inventory(stage, [entry])


def test_stage_inventory_rejects_symlinks_and_unsafe_manifest_paths(tmp_path):
    stage = tmp_path / 'stage'
    stage.mkdir()
    payload = stage / 'app.py'
    payload.write_text('safe')
    entry = {'path': 'app.py', 'size': 4, 'sha256': hashlib.sha256(b'safe').hexdigest()}
    (stage / 'alias.py').symlink_to(payload)
    with pytest.raises(ValueError, match='symlink'):
        verify_stage_inventory(stage, [entry])
    (stage / 'alias.py').unlink()
    with pytest.raises(ValueError, match='Unsafe'):
        verify_stage_inventory(stage, [{**entry, 'path': '../app.py'}])


def test_snapshot_rejects_bytes_changed_during_copy(tmp_path, monkeypatch):
    from scripts.stage_inventory import deployment_snapshot, inventory_digest
    stage = tmp_path / 'stage'
    stage.mkdir()
    source = stage / 'app.py'
    source.write_bytes(b'reviewed')
    entries = [{'path': 'app.py', 'size': 8, 'sha256': hashlib.sha256(b'reviewed').hexdigest()}]
    original_read = Path.read_bytes
    reads = 0

    def read(path):
        nonlocal reads
        if path == source:
            reads += 1
            if reads == 2:
                source.write_bytes(b'tampered')
        return original_read(path)

    monkeypatch.setattr(Path, 'read_bytes', read)
    with pytest.raises(ValueError, match='snapshot changed'):
        with deployment_snapshot(stage, entries, inventory_digest(entries)):
            pytest.fail('Changed copy must never reach dispatch')


def test_snapshot_cleanup_on_dispatch_failure(tmp_path):
    from scripts.stage_inventory import deployment_snapshot, inventory_digest
    stage = tmp_path / 'stage'
    stage.mkdir()
    (stage / 'app.py').write_bytes(b'reviewed')
    entries = [{'path': 'app.py', 'size': 8, 'sha256': hashlib.sha256(b'reviewed').hexdigest()}]
    with pytest.raises(RuntimeError, match='dispatch failed'):
        with deployment_snapshot(stage, entries, inventory_digest(entries)) as snapshot:
            assert snapshot != stage
            assert (snapshot / 'app.py').read_bytes() == b'reviewed'
            raise RuntimeError('dispatch failed')
    assert not snapshot.exists()
