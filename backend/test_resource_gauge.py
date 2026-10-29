import os
from pathlib import Path
from . import resource_gauge as gauge
from .test_source_sync import harness


def test_process_gauge_accounts_current_rss_and_cpu_without_commands():
    if not Path('/proc/self/stat').exists(): return
    row = next(row for row in gauge.processes() if row['pid'] == os.getpid())
    assert row['rss_bytes'] > 0 and row['cpu_seconds'] >= 0 and row['threads'] >= 1
    assert 'cmd' not in row


def test_idle_activity_does_not_require_a_polling_thread(tmp_path, monkeypatch):
    monkeypatch.setattr(gauge, 'ACTIVITY', tmp_path/'activity')
    monkeypatch.setattr(gauge, '_last_activity', 0)
    assert not gauge.user_active()
    gauge.mark_activity()
    assert gauge.user_active()
    os.utime(gauge.ACTIVITY, (0, 0))
    assert not gauge.user_active()


def test_empty_worker_does_not_decode_workspace(harness, tmp_path, monkeypatch):
    from .jobs import Worker
    from . import storage
    h = harness
    state, _ = h.read()
    state['jobs'] = []
    state['delegations'] = []
    for project in state['projects']:
        for node in project['nodes']:
            for task in node['tasks']: task['start_date'] = None
    with h.sessions.begin() as db:
        row = db.get(h.W, h.wid)
        row.data = storage.save(db, h.B, h.wid, state)
    worker = Worker(h.sessions, h.W, h.B, h.P, h.cfg, tmp_path)
    monkeypatch.setattr(worker, 'state', lambda *a: (_ for _ in ()).throw(AssertionError('full decode')))
    assert worker.run_one(h.wid) is None


def test_stage_log_keeps_interval_and_process_cpu_separate(monkeypatch, caplog):
    import time
    monkeypatch.setattr(gauge, 'processes', lambda: [dict(pid=os.getpid(), cpu_seconds=123, rss_bytes=4096)])
    gauge.log_stage('test', time.monotonic(), time.process_time())
    assert '"cpu_seconds": 123' in caplog.text
    assert '"stage_cpu_seconds":' in caplog.text


def test_read_timers_do_not_count_as_user_activity(tmp_path, monkeypatch):
    monkeypatch.setattr(gauge, 'ACTIVITY', tmp_path/'activity')
    monkeypatch.setattr(gauge, '_last_activity', 0)
    for path in ('/api/home-panels', '/api/my-work', '/api/live/status', '/api/source-health'):
        gauge.mark_activity(path)
    assert not gauge.user_active()
    gauge.mark_activity('/api/projects/example/first-screen')
    assert gauge.user_active()
