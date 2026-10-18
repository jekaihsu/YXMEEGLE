"""Two workers racing on one file-backed SQLite database through separate engines and service instances."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .test_dispatch_publish import SCHEDULE, TASKS, approve, call, commit, h, preview  # noqa: F401


def two_workers(h):
    """A second process: its own engine and service instance on the same database file."""
    engine = create_engine(h.url, connect_args={'check_same_thread': False, 'timeout': 20})
    return h.build(store=sessionmaker(engine, expire_on_commit=False)), engine


def both_past_the_fresh_read(h):
    gate = Barrier(2, timeout=10)

    def wait(request, proceed):
        gate.wait()
        return proceed()
    h.fake.on('GET', f'/{SCHEDULE}/records', wait, times=2)


def test_overlapping_commits_one_wins_the_other_conflicts_and_keeps_its_draft(h):
    other, engine = two_workers(h)
    first = preview(h, draft_id='draft-first-01')
    second = preview(h, title='C 區外業', start='2026-10-20T10:00+08:00', end='2026-10-20T14:00+08:00',
                     draft_id='draft-second-1')
    call(h, 'ou_pm', 'put', '/api/v2/dispatch/drafts/draft-second-1', {'proposal': {'title': 'C 區外業'}})
    approve(h, first['preview_id'])
    approve(h, second['preview_id'])
    both_past_the_fresh_read(h)
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(commit, h, 'cmd-race-first-1', first['preview_id'])
        b = pool.submit(commit, h, 'cmd-race-second', second['preview_id'], other)
        responses = {'first': a.result(), 'second': b.result()}
    assert sorted(r.status_code for r in responses.values()) == [200, 409]
    winner = next(k for k, r in responses.items() if r.status_code == 200)
    loser = responses['second' if winner == 'first' else 'first'].json()
    won = responses[winner].json()['command']
    assert loser['code'] == 'reservation_conflict'
    assert {(c['kind'], c['ref'], c['command_id'], c['title']) for c in loser['conflicts']} == {
        ('instrument', 'recI1', won['command_id'], 'B 區外業' if winner == 'first' else 'C 區外業'),
        ('person', 'recP3', won['command_id'], 'B 區外業' if winner == 'first' else 'C 區外業'),
        ('person', 'recP2', won['command_id'], 'B 區外業' if winner == 'first' else 'C 區外業')}
    assert {c['interval']['start'] for c in loser['conflicts']} == {
        '2026-10-20T08:00+08:00' if winner == 'first' else '2026-10-20T10:00+08:00'}
    assert [f['命令編號'] for f in h.fake.task_rows().values() if f.get('命令編號')] == [won['command_id']]
    assert call(h, 'ou_pm', 'get', '/api/v2/dispatch/drafts/draft-second-1').json()['proposal'] == {'title': 'C 區外業'}
    assert call(h, 'ou_pm', 'get', f"/api/v2/dispatch/previews/{second['preview_id']}").status_code == 200
    engine.dispose()


def test_one_command_id_sent_twice_at_once_writes_once(h):
    other, engine = two_workers(h)
    found = preview(h)
    approve(h, found['preview_id'])
    both_past_the_fresh_read(h)
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(commit, h, 'cmd-race-same-01', found['preview_id'])
        b = pool.submit(commit, h, 'cmd-race-same-01', found['preview_id'], other)
        results = [a.result(), b.result()]
    # The second request sees the stored command: still pending (202) or already committed (200), never a new write.
    assert 200 in [r.status_code for r in results] and {r.status_code for r in results} <= {200, 202}
    assert {r.json()['command']['command_id'] for r in results} == {'cmd-race-same-01'}
    assert len(h.fake.creates()) == 1
    assert call(h, 'ou_pm', 'get', '/api/v2/commands/cmd-race-same-01').json()['command']['state'] == 'committed'
    assert len([f for f in h.fake.task_rows().values() if f.get('命令編號')]) == 1
    engine.dispose()
