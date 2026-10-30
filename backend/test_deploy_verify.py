import json
import sys

import httpx
import pytest

from scripts.deploy_verify import verification_passed


def test_deploy_verification_requires_every_check_to_pass():
    assert verification_passed({'checks': {'html': True, 'assets': True}})
    assert not verification_passed({'checks': {'html': True, 'assets': False}})
    assert not verification_passed({'checks': {}})
    assert not verification_passed({'checks': {'assets': 1}})
    assert not verification_passed({})
    assert not verification_passed({'checks': None})


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        assert self.status_code < 400

    def json(self):
        return self._payload


class _FakeClient:
    """Stands in for httpx.Client so main() never touches the network."""

    def __init__(self, remote_index, asset_status=200):
        self.remote_index = remote_index
        self.asset_status = asset_status

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kwargs):
        if url.endswith('/api/health'):
            return _FakeResponse(payload={'database': 'postgresql'})
        if '/assets/' in url:
            if isinstance(self.asset_status, Exception):
                raise self.asset_status
            return _FakeResponse(status_code=self.asset_status)
        return _FakeResponse(text=self.remote_index)


def _run_assets_main(monkeypatch, tmp_path, capsys, remote_index, asset_status=200, local_index='<script src="/assets/new.js"></script>'):
    from scripts import deploy_verify
    (tmp_path / 'frontend/dist').mkdir(parents=True)
    (tmp_path / 'frontend/dist/index.html').write_text(local_index, encoding='utf-8')
    monkeypatch.setattr(deploy_verify, 'ROOT', tmp_path)
    monkeypatch.setattr(deploy_verify, 'RUNTIME', tmp_path / '.runtime')
    monkeypatch.setattr(deploy_verify.httpx, 'Client', _FakeClient(remote_index, asset_status))
    monkeypatch.setattr(sys, 'argv', ['deploy_verify.py', 'assets'])
    try:
        deploy_verify.main()
        code = 0
    except SystemExit as exc:
        code = exc.code
    result = json.loads(capsys.readouterr().out)
    receipt = json.loads((tmp_path / '.runtime/zeabur-verification-assets.json').read_text(encoding='utf-8'))
    assert receipt == result
    return code, result


def test_main_exits_zero_when_assets_match(monkeypatch, tmp_path, capsys):
    code, result = _run_assets_main(monkeypatch, tmp_path, capsys, '<script src="/assets/new.js"></script>')
    assert code == 0
    assert result['ok'] is True


def test_main_exits_nonzero_when_remote_assets_are_stale(monkeypatch, tmp_path, capsys):
    code, result = _run_assets_main(monkeypatch, tmp_path, capsys, '<script src="/assets/old.js"></script>')
    assert code == 1
    assert result['ok'] is False
    assert result['checks']['latest_frontend_assets'] is False
    assert result['checks']['asset_downloads'] is False


def test_main_exits_nonzero_when_both_asset_lists_are_empty(monkeypatch, tmp_path, capsys):
    code, result = _run_assets_main(monkeypatch, tmp_path, capsys, '<html></html>', local_index='<html></html>')
    assert code == 1
    assert result['ok'] is False
    assert result['expected_assets'] == result['assets'] == []
    assert result['checks']['latest_frontend_assets'] is False
    assert result['checks']['asset_downloads'] is False


@pytest.mark.parametrize('asset_status', [404, httpx.ReadTimeout('asset download timed out')], ids=['404', 'timeout'])
def test_main_exits_nonzero_when_asset_download_fails(monkeypatch, tmp_path, capsys, asset_status):
    code, result = _run_assets_main(monkeypatch, tmp_path, capsys, '<script src="/assets/new.js"></script>', asset_status=asset_status)
    assert code == 1
    assert result['ok'] is False
    assert result['checks']['latest_frontend_assets'] is True
    assert result['checks']['asset_downloads'] is False
