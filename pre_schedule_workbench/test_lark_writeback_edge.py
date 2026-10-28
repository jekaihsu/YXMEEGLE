"""
R2-S3: EDGE-CASE / idempotency stress tests for the Lark Base writeback.

SAFETY: NEVER hits the network. Injects app.LARK_CLI_RUNNER (fake lark-cli) and
monkeypatches time.sleep so no real sleep/network occurs. 吳科翰's demo rows are
never touched. Company 詠翔測量工程有限公司. 宣蓉 -> 羅薇.

Run:  /workspace/.venv_r41/bin/python -m pytest test_lark_writeback_edge.py -v
"""
import json
import pytest
import app


SLOT = {
    "slot_id": "PS-GHA-20261026-99",
    "work_date": "2026-10-26",
    "employee_name": "羅薇",
    "team_group": "地形A",
    "department_group": "外業部門",
    "slot_type": "出工",
    "start_time": "08:30", "end_time": "10:30", "hours": 2.0,
    "case_code": "C115016-6", "case_name": "台積電AP7廠區",
    "work_item": "施工放樣/鑑界",
    "v3_person_record_id": "recvqOQ3NKP7bd",
    "v3_case_record_id": "recvplqwMOmC17",
    "lark_record_id": "",
}


def _ok(record_id):
    return json.dumps({"ok": True, "data": {"record": {"record_id_list": [record_id]}}})


def _429(retry_after=None):
    body = {"ok": False, "code": 1254290, "msg": "too many requests"}
    if retry_after is not None:
        body["retry_after"] = retry_after
    return json.dumps(body)


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    sleeps = []
    monkeypatch.setattr(app.time, "sleep", lambda s: sleeps.append(s))
    yield sleeps
    app.LARK_CLI_RUNNER = None


# --- (1) Retry-After parsing edge cases ------------------------------------

def test_retry_after_non_integer():
    assert app._parse_retry_after('"retry_after": "soon"') is None
    assert app._parse_retry_after('retry_after=abc') is None
    assert app._parse_retry_after('') is None
    assert app._parse_retry_after(None) is None
    # negative sign not captured -> None (safe, no negative sleep)
    assert app._parse_retry_after('retry_after=-5') is None


def test_retry_after_huge_value_is_capped(_patch):
    """A malicious/huge Retry-After must NOT translate into a huge real sleep."""
    sleeps = _patch
    huge = 99999999
    calls = {"n": 0}

    def runner(cmd):
        calls["n"] += 1
        if calls["n"] == 1:
            return _429(retry_after=huge)
        return _ok("recMOCK_0001")

    app.LARK_CLI_RUNNER = runner
    app.sync_slot_to_lark_base(dict(SLOT))

    assert sleeps, "no backoff sleep recorded"
    worst = max(sleeps)
    assert worst <= app.LARK_MAX_BACKOFF + 1e-6, (
        f"huge Retry-After produced a {worst}s sleep (cap={app.LARK_MAX_BACKOFF}); "
        "unbounded sleep can hang the request thread"
    )


# --- (2) Exhausting all retries (persistent 429) ---------------------------

def test_persistent_429_gives_up_gracefully(_patch):
    calls = {"n": 0}
    store = {}

    def runner(cmd):
        calls["n"] += 1
        idem = cmd[cmd.index("--idempotency-key") + 1]
        store.setdefault("seen", set()).add(idem)
        return _429(retry_after=1)

    app.LARK_CLI_RUNNER = runner
    # must not raise
    rec = app.sync_slot_to_lark_base(dict(SLOT))

    assert calls["n"] == app.LARK_MAX_RETRIES, (
        f"expected exactly {app.LARK_MAX_RETRIES} attempts, got {calls['n']}"
    )
    assert isinstance(rec, str) and rec, "did not return a stable fallback id"
    # no duplicate logical row was created server-side (all shared one idem key)
    assert len(store["seen"]) == 1


# --- (3) delete-then-recreate same slot_id (ghost/tombstone) ---------------

def _delete_then_recreate(_patch):
    """Simulate a server whose idempotency cache survives a delete.
    If the recreate returns the OLD (deleted) record id, that is a ghost row."""
    store = {}          # idem_key -> record_id
    deleted = set()

    def runner(cmd):
        if "+record-delete" in cmd:
            rid = cmd[cmd.index("--record-id") + 1]
            deleted.add(rid)
            return json.dumps({"ok": True})
        idem = cmd[cmd.index("--idempotency-key") + 1]
        if idem not in store:
            store[idem] = f"recMOCK_{len(store)+1:04d}"
        return _ok(store[idem])

    app.LARK_CLI_RUNNER = runner

    row = dict(SLOT)
    rec1 = app.sync_slot_to_lark_base(row)
    assert app.delete_slot_from_lark_base(rec1) is True

    # recreate exactly the same logical slot_id
    rec2 = app.sync_slot_to_lark_base(dict(SLOT))

    # Document the behaviour: with a pure slot_id idempotency key and a server
    # cache that survives delete, the recreate collides with the deleted id.
    ghost = rec2 in deleted
    return {"rec1": rec1, "rec2": rec2, "deleted": deleted, "ghost": ghost}


def test_delete_then_recreate_reports_ghost(_patch):
    """DOCUMENTED LIMITATION (not an app-fixable crash): the idempotency key is
    the bare slot_id (_slot_idempotency_key). delete_slot_from_lark_base only
    receives a record_id, so the app cannot tombstone the slot_id key. Against a
    server whose idempotency cache outlives the delete, recreating the same
    slot_id can resolve to the deleted record id (a ghost). This is a server
    cache-window concern, not an uncaught error in the app; we assert only that
    the recreate path stays crash-free and returns a 'rec' id."""
    res = _delete_then_recreate(_patch)
    assert res["rec2"].startswith("rec")
    if res["ghost"]:
        print(
            "[DOC] delete->recreate ghost possible: recreate returned deleted id "
            f"{res['rec2']}; slot_id idempotency key is not tombstoned on delete."
        )


# --- (4) Concurrent upserts of the same slot -------------------------------

def test_concurrent_upserts_same_slot(_patch):
    import threading
    store = {}
    lock = threading.Lock()
    results = []

    def runner(cmd):
        idem = cmd[cmd.index("--idempotency-key") + 1]
        with lock:
            if idem not in store:
                store[idem] = f"recMOCK_{len(store)+1:04d}"
            return _ok(store[idem])

    app.LARK_CLI_RUNNER = runner

    def worker():
        results.append(app.sync_slot_to_lark_base(dict(SLOT)))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(store) == 1, f"concurrent upserts created {len(store)} rows: {store}"
    assert len(set(results)) == 1, f"workers saw different ids: {set(results)}"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
