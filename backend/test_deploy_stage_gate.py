"""Both deployment entrypoints must reject an unmanifested stage before launch."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

# The operator scripts import their siblings by bare name when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workbench_cloud_setup as cloud  # noqa: E402
import workbench_formal_release as formal  # noqa: E402
from stage_inventory import inventory_digest  # noqa: E402


def build(root, stage_name):
    runtime = root / '.runtime'
    stage = runtime / stage_name
    (stage / 'backend').mkdir(parents=True)
    payload = b'print("reviewed")\n'
    (stage / 'backend' / 'app.py').write_bytes(payload)
    files = [{'path': 'backend/app.py', 'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}]
    return runtime, stage, files


def write_receipts(runtime, stage, files, manifest_name, digest=None):
    (runtime / manifest_name).write_text(json.dumps({'directory': str(stage), 'files': files}))
    (runtime / (stage.name + '-smoke.json')).write_text(
        json.dumps({'ok': True, 'inventory_sha256': digest or inventory_digest(files)}))


class FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return type('Result', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()


@pytest.fixture
def cloud_env(tmp_path, monkeypatch):
    runtime, stage, files = build(tmp_path, 'zeabur-stage-test')
    write_receipts(runtime, stage, files, 'zeabur-stage-manifest.json')
    fake = FakeRun()
    monkeypatch.setattr(cloud, 'ROOT', tmp_path)
    monkeypatch.setattr(cloud, 'STATE', runtime / 'cloud-staging')
    (runtime / 'cloud-staging').mkdir()
    monkeypatch.setattr(cloud.subprocess, 'run', fake)
    return stage, files, fake, runtime


@pytest.fixture
def formal_env(tmp_path, monkeypatch):
    runtime, stage, files = build(tmp_path, formal.STAGE)
    write_receipts(runtime, stage, files, formal.STAGE + '-manifest.json')
    fake = FakeRun()
    monkeypatch.setattr(formal, 'ROOT', tmp_path)
    monkeypatch.setattr(formal, 'STATE', runtime / 'formal-state')
    monkeypatch.setattr(formal.subprocess, 'run', fake)
    return stage, files, fake, runtime


def deploy_cloud():
    cloud.deploy([{'name': cloud.APP, '_id': 'svc-synthetic'}])


def tamper_extra(stage):
    (stage / 'backend' / 'private.json').write_text('{"synthetic":true}')


def tamper_symlink(stage):
    (stage / 'backend' / 'alias.py').symlink_to(stage / 'backend' / 'app.py')


def tamper_missing(stage):
    (stage / 'backend' / 'app.py').unlink()


def tamper_changed(stage):
    (stage / 'backend' / 'app.py').write_bytes(b'print("tampered")\n')


TAMPERS = [tamper_extra, tamper_symlink, tamper_missing, tamper_changed]


@pytest.mark.parametrize('tamper', TAMPERS)
def test_cloud_setup_rejects_before_launch(cloud_env, tamper):
    stage, _, fake, _ = cloud_env
    tamper(stage)
    with pytest.raises(ValueError):
        deploy_cloud()
    assert fake.calls == []


@pytest.mark.parametrize('tamper', TAMPERS)
def test_formal_release_rejects_before_launch(formal_env, tamper):
    stage, _, fake, _ = formal_env
    tamper(stage)
    with pytest.raises(ValueError):
        formal.run()
    assert fake.calls == []
    assert not (formal.STATE / 'attempt.json').exists()


def test_cloud_setup_clean_manifest_dispatches_once(cloud_env):
    stage, _, fake, _ = cloud_env
    deploy_cloud()
    assert len(fake.calls) == 1
    assert fake.calls[0][1]['cwd'] != stage
    assert not fake.calls[0][1]['cwd'].exists()


def test_cloud_setup_rejects_smoke_bound_to_other_inventory(cloud_env):
    stage, files, fake, runtime = cloud_env
    write_receipts(runtime, stage, files, 'zeabur-stage-manifest.json', digest='0' * 64)
    with pytest.raises(RuntimeError, match='bound to a different inventory'):
        deploy_cloud()
    assert fake.calls == []


def test_formal_release_clean_manifest_passes_inventory_gate(formal_env):
    # Later gates (staging proof receipt) are absent here, so the run stops
    # there: the inventory and smoke binding passed and nothing was launched.
    _, _, fake, _ = formal_env
    with pytest.raises(FileNotFoundError, match='release-source-staging'):
        formal.run()
    assert fake.calls == []


def test_formal_release_rejects_smoke_bound_to_other_inventory(formal_env):
    stage, files, fake, runtime = formal_env
    write_receipts(runtime, stage, files, formal.STAGE + '-manifest.json', digest='0' * 64)
    with pytest.raises(RuntimeError, match='bound to a different inventory'):
        formal.run()
    assert fake.calls == []


def test_cloud_dispatch_uses_reviewed_copy_when_original_changes(cloud_env, monkeypatch):
    stage, files, _, _ = cloud_env
    calls = []

    def run(*args, **kwargs):
        tamper_extra(stage)
        tamper_changed(stage)
        snapshot = kwargs['cwd']
        assert sorted(p.relative_to(snapshot).as_posix() for p in snapshot.rglob('*') if p.is_file()) == ['backend/app.py']
        assert hashlib.sha256((snapshot / 'backend/app.py').read_bytes()).hexdigest() == files[0]['sha256']
        calls.append(snapshot)
        return type('Result', (), {'returncode': 0})()

    monkeypatch.setattr(cloud.subprocess, 'run', run)
    deploy_cloud()
    assert len(calls) == 1
    assert not calls[0].exists()
