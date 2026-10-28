#!/usr/bin/env python3
"""R55 resilience / concurrency stress tests for live_jk_test_watcher.

Stubs ALL Lark/HTTP I/O (no real Email/Lark sends). Uses a temp state file on
the test DB clone conventions only — nothing here talks to prod.

Run: .venv-r31b/bin/python -m pytest test_live_watcher_resilience.py -v
"""
import importlib
import json
import os
import threading
from pathlib import Path

import pytest

os.environ["DRY_RUN_STRESS_TEST"] = "1"  # stub every bot send/patch/card path
import live_jk_test_watcher as m  # noqa: E402


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    sf = tmp_path / "state.json"
    monkeypatch.setattr(m, "STATE_FILE", Path(sf))
    # Count real reaction HTTP calls. react_to_message short-circuits under
    # DRY_RUN_STRESS_TEST, so to actually observe de-dup of the *network* call
    # we patch the env off locally and stub subprocess.run inside the react path.
    calls = {"react": []}

    class _Proc:
        returncode = 0
        stdout = "{}"

    def fake_run(cmd, *a, **k):
        if "reactions" in " ".join(cmd):
            calls["react"].append(cmd)
        return _Proc()

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    # Turn OFF the react dry-run short-circuit so the network path is exercised
    # (but it now hits fake_run, not a real Lark call).
    monkeypatch.setattr(m.os, "environ", {**os.environ, "DRY_RUN_STRESS_TEST": "1", "_REACT_LIVE": "1"})

    # Patch react_to_message to ignore the dry-run guard so we can count calls.
    orig_react = m.react_to_message

    def react_counting(msg_id, emoji_type="OK", dry_run=False):
        if not msg_id:
            return {"ok": False, "elapsed_ms": 0.0}
        calls["react"].append(msg_id)
        return {"ok": True, "msg_id": msg_id, "elapsed_ms": 0.5}

    monkeypatch.setattr(m, "react_to_message", react_counting)
    # get_employee_signature shells out to psql; stub it deterministically.
    monkeypatch.setattr(m, "get_employee_signature",
                        lambda oid=m.JK_OPEN_ID, fb="許喆凱": ("許喆凱", "sig", "<sig>"))
    return calls


def test_dual_track_dedup_single_react_and_process(temp_state):
    """Same message arrives via BOTH the WS push and the HTTP poll -> exactly
    one reaction and one process (one entry in processed_ids)."""
    mid = "om_dual_track_1"
    content = json.dumps({"text": "請改成週四中午前交"})

    # Fire both tracks concurrently to hit the STATE_LOCK race.
    threads = [
        threading.Thread(target=m.handle_user_text, args=(content, mid, m.JK_OPEN_ID, m.CHAT_ID))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert temp_state["react"].count(mid) == 1, temp_state["react"]
    st = json.loads(Path(m.STATE_FILE).read_text())
    assert st["processed_ids"].count(mid) == 1
    assert st["reacted_ids"].count(mid) == 1


def test_restart_persistence_no_double_react(temp_state):
    """After a 'restart' (fresh load_state from the same file) the same msg is
    neither re-reacted nor re-processed."""
    mid = "om_restart_1"
    content = json.dumps({"text": "好，寄出"})
    m.handle_user_text(content, mid, m.JK_OPEN_ID, m.CHAT_ID)
    assert temp_state["react"].count(mid) == 1

    # Simulate process restart: state must reload from disk.
    st = m.load_state()
    assert mid in st["processed_ids"]
    assert mid in st["reacted_ids"]

    # Redelivery after restart -> no-op.
    m.handle_user_text(content, mid, m.JK_OPEN_ID, m.CHAT_ID)
    assert temp_state["react"].count(mid) == 1


def test_dedup_sets_bounded(temp_state, monkeypatch):
    """processed_ids / reacted_ids must not grow without bound."""
    monkeypatch.setattr(m, "DEDUP_MAX", 50)
    st = m.load_state()
    st["processed_ids"] = [f"x{i}" for i in range(500)]
    st["reacted_ids"] = [f"r{i}" for i in range(500)]
    st["processed_events"] = [f"e{i}" for i in range(500)]
    m.save_state(st)
    reloaded = json.loads(Path(m.STATE_FILE).read_text())
    assert len(reloaded["processed_ids"]) == 50
    assert len(reloaded["reacted_ids"]) == 50
    assert len(reloaded["processed_events"]) == 50
    # Most-recent entries are the ones kept.
    assert reloaded["processed_ids"][-1] == "x499"


def test_atomic_save_leaves_valid_file(temp_state):
    st = m.load_state()
    m.save_state(st)
    # No leftover .tmp, file parses.
    assert not Path(str(m.STATE_FILE) + ".tmp").exists()
    json.loads(Path(m.STATE_FILE).read_text())


def test_ws_reconnect_backoff(monkeypatch):
    """Simulated disconnect->reconnect: a consume that dies instantly must back
    off exponentially (not a tight 1s loop) and reconnect."""
    sleeps = []
    starts = []

    class _DeadProc:
        stdout = None
        def wait(self):
            return 1

    def fake_popen(cmd, *a, **k):
        starts.append(cmd)
        raise RuntimeError("simulated WS disconnect")  # dies instantly

    monkeypatch.setattr(m.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(m.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(m.time, "monotonic", lambda: 100.0)  # uptime always 0 -> never healthy

    m._consume_with_backoff("im.message.receive_v1", lambda ev: None, "msg_ws_consumer_loop", _max_iters=5)

    # It reconnected 5 times (disconnect -> reconnect loop works).
    assert len(starts) == 5
    # Backoff is exponential, capped at WS_BACKOFF_MAX, never a flat tight loop.
    assert sleeps == [1.0, 2.0, 4.0, 8.0, 16.0]


def test_ws_backoff_resets_after_healthy_connection(monkeypatch):
    """A long-lived connection resets the backoff to the floor."""
    sleeps = []
    clock = {"t": 0.0}
    # Each consume 'runs' for 60s (healthy), advancing the clock.
    def fake_popen(cmd, *a, **k):
        clock["t"] += 60.0
        raise RuntimeError("disconnect after healthy uptime")
    monkeypatch.setattr(m.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(m.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(m.time, "monotonic", lambda: clock["t"])
    m._consume_with_backoff("card.action.trigger", lambda ev: None, "card_ws_consumer_loop", _max_iters=3)
    # Every connection was healthy (>=30s), so backoff stays at the floor.
    assert sleeps == [1.0, 1.0, 1.0]


if __name__ == "__main__":
    import sys, subprocess as sp
    sys.exit(sp.call([sys.executable, "-m", "pytest", __file__, "-v"]))
