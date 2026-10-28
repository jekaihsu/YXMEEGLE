"""
Edge / boundary case tests for the 永祥 pre-schedule workbench (:8895).

Covers: cross-day entries, leave conflicts, daily 8h capacity / overbooking,
general overlap detection, modify re-validation, delete + capacity release,
deleting a non-existent id.

SAFETY:
- Uses an isolated temp SQLite DB (never the real pre_schedule.db).
- Stubs the Lark Base sync/delete functions so NO real Lark call is made and
  吳科翰's demo rows are never touched.
- No Email / Lark sends.

Run:  /tmp/yxvenv/bin/python3 -m pytest test_edge_cases.py -v
"""
import os, sqlite3, importlib, tempfile
import pytest
from fastapi.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Full DDL copied from the live schema so the isolated DB matches production.
DDL = """
CREATE TABLE pre_schedule_hourly_slot (
    slot_id TEXT PRIMARY KEY,
    work_date TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    employee_name TEXT NOT NULL,
    lark_open_id TEXT,
    v3_person_record_id TEXT,
    department_group TEXT NOT NULL,
    team_group TEXT NOT NULL,
    slot_type TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    hours REAL NOT NULL,
    priority_rank INTEGER NOT NULL,
    case_code TEXT NOT NULL,
    case_name TEXT NOT NULL,
    client_name TEXT,
    v3_case_record_id TEXT,
    contract_item_code TEXT,
    schedule_reason TEXT NOT NULL,
    work_item TEXT NOT NULL,
    work_note TEXT,
    est_quantity REAL,
    est_points REAL,
    upstream_dep_note TEXT,
    converted_to_daily_log INTEGER,
    lark_sync_status TEXT,
    lark_record_id TEXT
)
"""

PERSON = "吳柏頤"          # a real catalog employee (group lead, business/PM)
DATE = "2026-11-02"         # a Monday far from 吳科翰's demo rows
CASE = "C115055-1"          # a real catalog case


# Target module: server.py is the app actually deployed on :8895 (no auth
# header), so validation fixes must live there. app.py is the auth-wrapped
# variant; the same fixes are mirrored into it. Override with YX_APP_MODULE.
APP_MODULE = os.environ.get("YX_APP_MODULE", "server")


@pytest.fixture()
def client(monkeypatch):
    """Fresh isolated DB + stubbed Lark per test."""
    appmod = importlib.import_module(APP_MODULE)
    importlib.reload(appmod)

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.executescript(DDL)
    conn.commit()
    conn.close()

    monkeypatch.setattr(appmod, "SQLITE_PATH", tmp.name)
    # Never touch real Lark Base.
    monkeypatch.setattr(appmod, "sync_slot_to_lark_base", lambda row: "recTESTSTUB")
    monkeypatch.setattr(appmod, "delete_slot_from_lark_base", lambda rid: True)

    c = TestClient(appmod.app, raise_server_exceptions=False)
    # app.py enforces identity via X-Actor-Name. Non-ASCII header values must
    # be percent-encoded on the wire (RFC 5987 style); app.py is patched to
    # URL-decode the header. server.py ignores the header entirely.
    from urllib.parse import quote
    c.headers.update({"X-Actor-Name": quote(PERSON)})
    c._dbfile = tmp.name
    yield c
    os.unlink(tmp.name)


def mk(**over):
    body = {
        "work_date": DATE,
        "employee_name": PERSON,
        "slot_type": "出工",
        "start_time": "08:00",
        "end_time": "10:00",
        "hours": 2.0,
        "priority_rank": 1,
        "case_code": CASE,
        "work_item": "控制網平差計算",
    }
    body.update(over)
    return body


def create(client, **over):
    return client.post("/api/slots", json=mk(**over))


# ---------------------------------------------------------------------------
# (a) Cross-day / spanning-midnight entries
# ---------------------------------------------------------------------------
def test_a_cross_day_rejected(client):
    """22:00-02:00 implies negative duration under same-day semantics; must be
    rejected (or at least never produce a negative/garbage duration)."""
    r = create(client, start_time="22:00", end_time="02:00", hours=4.0)
    assert r.status_code == 422, f"cross-day/midnight span should be rejected, got {r.status_code}: {r.text}"


def test_a_end_before_start_rejected(client):
    r = create(client, start_time="14:00", end_time="10:00", hours=4.0)
    assert r.status_code == 422, f"end<start should be rejected, got {r.status_code}"


def test_a_zero_duration_rejected(client):
    r = create(client, start_time="09:00", end_time="09:00", hours=0.0)
    assert r.status_code == 422, f"zero-length slot should be rejected, got {r.status_code}"


# ---------------------------------------------------------------------------
# (b) Leave-request conflict
# ---------------------------------------------------------------------------
def test_b_schedule_on_leave_blocked(client):
    r1 = create(client, slot_type="休假", start_time="08:00", end_time="17:00", hours=8.0)
    assert r1.status_code == 200, f"creating leave slot failed: {r1.text}"
    r2 = create(client, slot_type="出工", start_time="09:00", end_time="11:00", hours=2.0)
    assert r2.status_code == 409, f"work scheduled on a leave day must be blocked, got {r2.status_code}"


# ---------------------------------------------------------------------------
# (c) 5 cases = 8h fit exactly; 6th overlapping hour rejected
# ---------------------------------------------------------------------------
def test_c_five_cases_eight_hours_then_overbook(client):
    plan = [("08:00", "09:30", 1.5), ("09:30", "11:00", 1.5),
            ("13:00", "14:30", 1.5), ("14:30", "16:00", 1.5),
            ("16:00", "18:00", 2.0)]  # totals 8.0h, non-overlapping
    for i, (s, e, h) in enumerate(plan, 1):
        r = create(client, start_time=s, end_time=e, hours=h, priority_rank=i)
        assert r.status_code == 200, f"case {i} ({s}-{e}) should fit, got {r.status_code}: {r.text}"
    # 6th case overlapping an existing hour must be rejected (double-booking).
    r6 = create(client, start_time="10:00", end_time="12:00", hours=2.0, priority_rank=6)
    assert r6.status_code == 409, f"overlapping 6th case must be rejected, got {r6.status_code}"


def test_c_daily_capacity_cap(client):
    """Non-overlapping but exceeding a sane daily cap (>12h) should be rejected."""
    create(client, start_time="00:00", end_time="12:00", hours=12.0)
    r = create(client, start_time="12:00", end_time="15:00", hours=3.0, priority_rank=2)
    assert r.status_code == 409, f"exceeding daily capacity must be rejected, got {r.status_code}"


# ---------------------------------------------------------------------------
# (d) General overlap detection
# ---------------------------------------------------------------------------
def test_d_overlap_same_hour_rejected(client):
    r1 = create(client, start_time="08:00", end_time="10:00", hours=2.0)
    assert r1.status_code == 200
    r2 = create(client, start_time="09:00", end_time="11:00", hours=2.0, priority_rank=2)
    assert r2.status_code == 409, f"overlapping slot must be rejected, got {r2.status_code}"


def test_d_adjacent_ok(client):
    r1 = create(client, start_time="08:00", end_time="10:00", hours=2.0)
    r2 = create(client, start_time="10:00", end_time="12:00", hours=2.0, priority_rank=2)
    assert r1.status_code == 200 and r2.status_code == 200, "back-to-back slots should be allowed"


# ---------------------------------------------------------------------------
# (e) Modify (adjust) re-validation
# ---------------------------------------------------------------------------
def test_e_grow_into_conflict_rejected(client):
    a = create(client, start_time="08:00", end_time="10:00", hours=2.0).json()["slot"]
    create(client, start_time="11:00", end_time="13:00", hours=2.0, priority_rank=2)
    # Grow slot a by +2h -> 08:00-12:00, overlapping the 11:00 slot: must reject.
    r = client.post(f"/api/slots/{a['slot_id']}/adjust", json={"delta": 2.0})
    assert r.status_code == 409, f"growing into a conflict must be rejected, got {r.status_code}"


def test_e_shrink_ok(client):
    a = create(client, start_time="08:00", end_time="12:00", hours=4.0).json()["slot"]
    r = client.post(f"/api/slots/{a['slot_id']}/adjust", json={"delta": -2.0})
    assert r.status_code == 200 and r.json()["slot"]["hours"] == 2.0


# ---------------------------------------------------------------------------
# (f) Delete frees capacity; non-existent id graceful
# ---------------------------------------------------------------------------
def test_f_delete_frees_capacity(client):
    a = create(client, start_time="08:00", end_time="10:00", hours=2.0).json()["slot"]
    # overlapping create blocked while a exists
    assert create(client, start_time="09:00", end_time="11:00", hours=2.0, priority_rank=2).status_code == 409
    d = client.delete(f"/api/slots/{a['slot_id']}")
    assert d.status_code == 200 and d.json()["ok"]
    # now the slot is free
    assert create(client, start_time="09:00", end_time="11:00", hours=2.0, priority_rank=2).status_code == 200


def test_f_delete_nonexistent_graceful(client):
    r = client.delete("/api/slots/PS-DOES-NOT-EXIST-0000")
    assert r.status_code in (200, 404), f"deleting missing id should be graceful, got {r.status_code}"
    if r.status_code == 200:
        assert r.json()["deleted"] == "PS-DOES-NOT-EXIST-0000"
