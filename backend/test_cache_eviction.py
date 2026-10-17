import pytest

from .node_assignment.cache import StaleCache
from .test_live_read_client import Clock


@pytest.mark.parametrize('write', ['put', 'get'])
def test_snapshot_rotations_are_bounded_and_expired_entries_evicted(write):
    clock = Clock()
    cache = StaleCache(60, 900, clock)
    for rotation in range(40):
        key = f'token-{rotation}'
        value = {'complete': True, 'records': [rotation]}
        if write == 'put':
            cache.put(key, value)
        else:
            assert cache.get(key, lambda: value).value == value
    assert len(cache._entries) == 32
    assert 'token-0' not in cache._entries
    assert cache.get('token-39', lambda: None).value['records'] == [39]
    clock.now = 901
    assert cache.get('new-token', lambda: {'records': ['new']}).value == {'records': ['new']}
    assert len(cache._entries) == 1
    assert len(cache._versions) == 0


def test_lru_access_preserves_recently_used_snapshot():
    cache = StaleCache(60, 900)
    for rotation in range(32):
        cache.put(rotation, rotation)
    assert cache.get(0, lambda: -1).value == 0
    cache.put(32, 32)
    assert len(cache._entries) == 32
    assert 0 in cache._entries
    assert 1 not in cache._entries
    assert cache.get(1, lambda: 'reloaded').value == 'reloaded'
    assert len(cache._entries) == 32


def test_implicit_source_token_rotations_do_not_retain_unbounded_snapshots(monkeypatch):
    from . import sources
    clock = Clock()
    cache = StaleCache(60, 900, clock)
    monkeypatch.setattr(sources, '_source_cache', cache)
    monkeypatch.setattr(sources, '_schema_cache', StaleCache(1800, 1800, clock))
    monkeypatch.setattr(sources, '_fetch_sources', lambda token, *args, **kwargs:
                        {'complete': True, 'status': 'ready', 'records': [{'record_id': token}]})
    for rotation in range(40):
        result = sources.fetch_sources(f'token-{rotation}', {})
        assert result['records'] == [{'record_id': f'token-{rotation}'}]
        assert result['stale'] is False
    assert len(cache._entries) == 32
    clock.now = 901
    assert sources.fetch_sources('latest', {})['records'] == [{'record_id': 'latest'}]
    assert len(cache._entries) == 1
