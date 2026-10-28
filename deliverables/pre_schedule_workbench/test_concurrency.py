from urllib.parse import quote
"""
R2-S1 concurrency & perf audit for the pre-schedule workbench write endpoints
and GET /api/capacity.

SAFETY: uses an isolated temp SQLite DB only; all lark-cli calls are routed
through an injected mock runner (no network, no real Lark/Email).
"""
import os, sqlite3, threading, time, json, tempfile, importlib
import pytest
from fastapi.testclient import TestClient

import app as appmod

ACTOR = "張家彬"  # group lead (is_group_lead) -> may schedule for self
CASE = "C115055-1"
WORK_DATE = "2026-11-02"  # NOT a 吳科翰 Monday demo row

SCHEMA = """
CREATE TABLE pre_schedule_hourly_slot (
    slot_id TEXT PRIMARY KEY, work_date TEXT NOT NULL, employee_id TEXT NOT NULL,
    employee_name TEXT NOT NULL, lark_open_id TEXT, v3_person_record_id TEXT,
    department_group TEXT NOT NULL, team_group TEXT NOT NULL, slot_type TEXT NOT NULL,
    start_time TEXT NOT NULL, end_time TEXT NOT NULL, hours REAL NOT NULL,
    priority_rank INTEGER NOT NULL, case_code TEXT NOT NULL, case_name TEXT NOT NULL,
    client_name TEXT, v3_case_record_id TEXT, contract_item_code TEXT,
    schedule_reason TEXT NOT NULL, work_item TEXT NOT NULL, work_note TEXT,
    est_quantity REAL, est_points REAL, upstream_dep_note TEXT,
    converted_to_daily_log INTEGER, lark_sync_status TEXT, lark_record_id TEXT
);
"""


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    dbp = str(tmp_path / "test_ps.db")
    conn = sqlite3.connect(dbp)
    conn.executescript(SCHEMA)
    conn.commit(); conn.close()
    monkeypatch.setattr(appmod, "SQLITE_PATH", dbp)

    # Mock lark-cli: no network. Add a delay to widen the TOCTOU window so a
    # real race (if present) reliably manifests instead of being timing-luck.
    def mock_runner(cmd):
        time.sleep(0.15)
        return json.dumps({"ok": True, "data": {"record": {"record_id_list": ["recMOCK123"]}}})
    monkeypatch.setattr(appmod, "LARK_CLI_RUNNER", mock_runner)
    return dbp


def _payload(start, end, hours):
    return {
        "work_date": WORK_DATE, "employee_name": ACTOR, "slot_type": "出工",
        "start_time": start, "end_time": end, "hours": hours, "priority_rank": 1,
        "case_code": CASE, "work_item": "資料整理", "schedule_reason": "正常排程",
    }


def test_concurrent_double_submit_same_slot(temp_db, monkeypatch):
    """Two overlapping create requests fired in parallel. If the TOCTOU window is
    real, both pass check_slot_conflicts (which only SELECTs) and both INSERT,
    producing an overlapping double-booking that the validation is meant to reject.

    NOTE: we force a per-call-unique slot_id so that the (separate) slot_id
    PRIMARY-KEY collision bug does not accidentally mask the overlap race we are
    actually probing here."""
    import itertools
    counter = itertools.count()
    _orig_sync = appmod.sync_slot_to_lark_base
    def unique_sync(row):
        row["slot_id"] = row["slot_id"] + f"-uniq{next(counter)}"
        return _orig_sync(row)
    monkeypatch.setattr(appmod, "sync_slot_to_lark_base", unique_sync)

    client = TestClient(appmod.app)
    N = 2
    barrier = threading.Barrier(N)
    results = []
    lock = threading.Lock()

    def submit():
        barrier.wait()  # release all threads simultaneously
        r = client.post("/api/slots", json=_payload("08:30", "10:30", 2.0),
                        headers={"X-Actor-Name": quote(ACTOR)})
        with lock:
            results.append(r.status_code)

    threads = [threading.Thread(target=submit) for _ in range(N)]
    for t in threads: t.start()
    for t in threads: t.join()

    conn = sqlite3.connect(temp_db)
    rows = conn.execute(
        "SELECT start_time,end_time FROM pre_schedule_hourly_slot WHERE employee_name=? AND work_date=?",
        (ACTOR, WORK_DATE)).fetchall()
    conn.close()

    print(f"\n[double-submit] status codes={sorted(results)} rows_in_db={len(rows)} rows={rows}")
    # Exactly one should succeed (200); the other should be rejected 409.
    assert results.count(200) == 1, (
        f"RACE: {results.count(200)} of {N} concurrent identical submits succeeded "
        f"(expected 1). DB now has {len(rows)} overlapping slots: {rows}")
    assert len(rows) == 1, f"Over-booked: {len(rows)} overlapping slots exist"


def test_concurrent_capacity_overbook(temp_db):
    """Many parallel submits that are individually valid but collectively exceed
    the 12h daily cap. Validates whether the daily-capacity guard holds under
    concurrency (each is 3h; 5 of them = 15h > 12h cap)."""
    client = TestClient(appmod.app)
    N = 5
    barrier = threading.Barrier(N)
    results = []
    lock = threading.Lock()

    def submit(i):
        barrier.wait()
        # distinct non-overlapping windows so only the capacity cap can reject
        start = 8 * 60 + 30 + i * 180  # 3h apart
        s = f"{start//60:02d}:{start%60:02d}"
        e = f"{(start+180)//60:02d}:{(start+180)%60:02d}"
        r = client.post("/api/slots", json=_payload(s, e, 3.0),
                        headers={"X-Actor-Name": quote(ACTOR)})
        with lock:
            results.append(r.status_code)

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(N)]
    for t in threads: t.start()
    for t in threads: t.join()

    conn = sqlite3.connect(temp_db)
    total = conn.execute(
        "SELECT COALESCE(SUM(hours),0) FROM pre_schedule_hourly_slot WHERE employee_name=? AND work_date=?",
        (ACTOR, WORK_DATE)).fetchone()[0]
    conn.close()
    print(f"\n[capacity] status codes={sorted(results)} total_booked_hours={total} (cap=12)")
    assert total <= appmod.DAILY_CAPACITY_HOURS + 1e-6, (
        f"RACE: daily cap exceeded under concurrency: {total}h booked (cap 12h)")


def test_capacity_query_latency_large_dataset(temp_db):
    """Populate a large synthetic dataset and measure GET /api/capacity latency."""
    conn = sqlite3.connect(temp_db)
    tg = "品管組"
    dg = "內業部門"
    rows = []
    # 90 days x 50 slots/day = 4500 rows
    base = 20261001
    n = 0
    for day in range(90):
        d = f"2026-11-{(day%28)+1:02d}"
        for k in range(50):
            n += 1
            rows.append((f"S{n}", d, "eid", f"EMP{k%10}", "", "", dg, tg, "出工",
                         "08:30", "10:30", 2.0, 1, CASE, "case", "", "", "", "正常",
                         "資料整理", "", 2.0, 0.0, "", 0, "SYNCED", "recX"))
    conn.executemany(
        "INSERT INTO pre_schedule_hourly_slot VALUES (" + ",".join(["?"]*27) + ")", rows)
    conn.commit()
    cnt = conn.execute("SELECT COUNT(*) FROM pre_schedule_hourly_slot").fetchone()[0]
    conn.close()

    client = TestClient(appmod.app)
    # warm
    client.get("/api/capacity", params={"team_group": tg, "date_from": "2026-11-01", "date_to": "2026-11-30"})
    t0 = time.perf_counter()
    r = client.get("/api/capacity", params={"team_group": tg, "date_from": "2026-11-01", "date_to": "2026-11-30"})
    dt = time.perf_counter() - t0
    assert r.status_code == 200
    print(f"\n[capacity-perf] rows={cnt} latency={dt*1000:.1f}ms booked={r.json()['booked_hours']}")
    # Not a hard SLA assert; report the number. Flag only if pathologically slow.
    assert dt < 5.0, f"capacity query pathologically slow: {dt:.2f}s for {cnt} rows"
