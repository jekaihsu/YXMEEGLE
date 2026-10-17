import socket
import subprocess
import sys
from pathlib import Path

import pytest

from . import features
from .ops_sync import flags
from .ops_sync.adapter import MockLarkAdapter

ROOT = Path(__file__).resolve().parent.parent


def test_flags_default_off_and_live_writer_hard_disabled(monkeypatch):
    assert not any([flags.FEATURE_OPS_SYNC, flags.FEATURE_OPS_SYNC_MOCK_UI, flags.FEATURE_OPS_SYNC_LARK_EVENTS,
                    flags.FEATURE_OPS_SYNC_LIVE_WRITES])
    assert flags.resolve_flags() == flags.OpsFlags()
    hostile = {k: True for k in ('FEATURE_OPS_SYNC', 'FEATURE_OPS_SYNC_MOCK_UI', 'FEATURE_OPS_SYNC_LARK_EVENTS',
                                 'FEATURE_OPS_SYNC_LIVE_WRITES')}
    resolved = flags.resolve_flags(hostile)
    assert resolved.ops_sync and resolved.mock_ui                    # local mock config may enable core + mock UI only
    assert not resolved.live_writes and not resolved.lark_events      # hard-disabled regardless of overrides

    calls = []
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: calls.append(('connect', a)))
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: calls.append(('create_connection', a)))
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: calls.append(('getaddrinfo', a)))
    with pytest.raises(flags.LiveWritesDisabled):
        flags.LiveLarkWriter(app_id='synthetic', secret='synthetic')
    with pytest.raises(flags.LiveWritesDisabled):
        flags.LiveLarkWriter()
    assert MockLarkAdapter.live is False
    assert calls == []                                                # zero network activity
    assert features.FEATURE_LEARNING is False                         # paused policy unchanged


def test_ops_sync_imports_no_network_client():
    code = ('import sys, backend.ops_sync.engine, backend.ops_sync.adapter, backend.ops_sync.flags;'
            'bad=[m for m in ("requests","httpx","aiohttp","urllib3","http.client","urllib.request","lark_oapi") if m in sys.modules];'
            'print(bad)')
    out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True)
    assert out.stdout.strip() == '[]', out.stderr
