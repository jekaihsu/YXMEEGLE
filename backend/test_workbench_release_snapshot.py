import json
import pytest
from scripts import workbench_release_snapshot as release


def test_prepare_creates_separate_exclusive_named_attempt(tmp_path,monkeypatch):
    monkeypatch.setattr(release,'DIRECTORY',tmp_path/'release')
    original=release.snapshot.DIRECTORY
    result=release.execute('prepare')
    assert result['remote_created'] is False
    attempt=json.loads((release.DIRECTORY/'attempt.json').read_text())
    assert attempt['purpose']=='formal-release-20260930'
    assert attempt['source_service_id']=='6ab61834a4c05a5bcb57ad69'
    assert release.snapshot.DIRECTORY==original
    with pytest.raises(FileExistsError):release.execute('prepare')


def test_recovery_scoped_directory_reset_even_on_failure(tmp_path,monkeypatch):
    monkeypatch.setattr(release,'DIRECTORY',tmp_path/'release');release.execute('prepare')
    original=release.snapshot.DIRECTORY
    def recover(operation):
        assert operation=='recover' and release.snapshot.DIRECTORY==release.DIRECTORY
        raise RuntimeError('unknown')
    monkeypatch.setattr(release.snapshot,'execute',recover)
    with pytest.raises(RuntimeError):release.execute('recover')
    assert release.snapshot.DIRECTORY==original


def test_no_arbitrary_path_operation():
    with pytest.raises(release.snapshot.SnapshotError):release.execute('../arbitrary')


def test_capture_unknown_outcome_cannot_be_dispatched_twice(tmp_path,monkeypatch):
    monkeypatch.setattr(release,'DIRECTORY',tmp_path/'release')
    release.execute('prepare')
    calls=[]
    def unknown(operation,attempt):
        calls.append(operation)
        raise RuntimeError('transport outcome unknown')
    monkeypatch.setattr(release.snapshot,'run_remote',unknown)
    with pytest.raises(RuntimeError):release.execute('capture')
    with pytest.raises(FileExistsError):release.execute('capture')
    assert calls==['create']


def test_existing_receipt_only_returns_status_without_remote_capture(tmp_path,monkeypatch):
    monkeypatch.setattr(release,'DIRECTORY',tmp_path/'release')
    release.execute('prepare')
    (release.DIRECTORY/'receipt.json').write_text('{}')
    def forbidden(*args):raise AssertionError('No second capture')
    monkeypatch.setattr(release.snapshot,'run_remote',forbidden)
    calls=[]
    monkeypatch.setattr(release.snapshot,'execute',lambda operation:calls.append(operation) or {'ok':True})
    assert release.execute('capture')['ok']
    assert calls==['status']
