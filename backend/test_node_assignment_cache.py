import threading

from .node_assignment.cache import StaleCache
from .node_assignment.service import actor_for


def test_read_refresh_is_nonblocking_single_flight_and_write_put_wins():
    now = [0]
    cache = StaleCache(60, 900, lambda: now[0])
    cache.put('case', 'old')
    now[0] = 61
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    def load():
        entered.set()
        release.wait(2)
        done.set()
        return 'obsolete'
    result = cache.get('case', load, revalidate=True)
    assert (result.value, result.stale, result.stale_reason) == ('old', True, 'refreshing')
    assert entered.wait(1)
    cache.get('case', lambda: (_ for _ in ()).throw(AssertionError('duplicate')), revalidate=True)
    cache.put('case', 'written')
    release.set()
    assert done.wait(1)
    assert cache.get('case', load).value == 'written'


def test_session_manager_override_without_roster():
    for user, expected in [({'role': 'manager'}, True), ({'role': 'member'}, False),
                           ({'role': 'manager', 'manager_revoked': True}, False),
                           ({'role': 'manager', 'active': False}, False)]:
        assert actor_for({'id': 'ou_admin', **user}, None).override is expected


def test_failed_background_refresh_keeps_last_good_value(caplog):
    now = [0]
    cache = StaleCache(60, 900, lambda: now[0])
    cache.put('case', 'good')
    now[0] = 61
    failed = threading.Event()
    def load():
        failed.set()
        raise RuntimeError('synthetic failure')
    result = cache.get('case', load, revalidate=True)
    assert result.value == 'good' and result.stale_reason == 'refreshing'
    assert failed.wait(1)
    assert cache.get('case', lambda: 'fresh', allow_stale=False).value == 'fresh'
