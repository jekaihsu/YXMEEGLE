"""The local source package includes the pilot without test helpers."""
import json
from scripts import deploy_prepare, verify_stage_package


def test_stage_manifest_includes_pilot_runtime_only(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy_prepare, 'RUNTIME', tmp_path)
    monkeypatch.setattr(verify_stage_package, 'verify_stage', lambda stage: {'ok': True})
    stage = deploy_prepare.staging()
    paths = {entry['path'] for entry in json.loads(
        (tmp_path / 'zeabur-stage-manifest.json').read_text())['files']}
    expected = {p.relative_to(deploy_prepare.ROOT).as_posix()
                for p in (deploy_prepare.ROOT / 'backend/lark_pilot').rglob('*.py')
                if not p.name.startswith('test')}
    assert expected and expected <= paths
    assert all((stage / path).is_file() for path in expected)
    assert not any(path.startswith('backend/lark_pilot/test') for path in paths)
