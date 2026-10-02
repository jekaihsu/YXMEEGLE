"""Packaging acceptance must run outside the source checkout's import path."""
import json
from pathlib import Path
import shutil

from scripts import deploy_prepare
from scripts.verify_stage_package import verify_stage


def test_staged_app_and_catalog_work_without_repository_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy_prepare, 'RUNTIME', tmp_path)
    stage = deploy_prepare.staging()
    assert (stage / 'backend' / 'sop_source_contracts.json').is_file()
    manifest = json.loads((tmp_path / 'zeabur-stage-manifest.json').read_text())
    assert any(f['path'] == 'backend/sop_source_contracts.json' for f in manifest['files'])
    receipt = json.loads((tmp_path / (stage.name + '-smoke.json')).read_text())
    assert receipt['ok'] and receipt['checks']['workspace']
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
