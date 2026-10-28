"""
Round-2 edge / boundary case tests for the 永祥 pre-schedule workbench.

Targets app.py (the X-Actor-Name auth-wrapped variant).  Set via YX_APP_MODULE.

These do NOT repeat S02 (test_edge_cases.py): cross-day, leave conflict,
5-cases/8h, overlap, adjust grow/shrink, delete. Instead they probe UNCOVERED
boundaries:
  (1) date-handling boundaries: month-end, year boundary, non-ISO / malformed
      work_date, out-of-range HH:MM clock values.
  (2) malformed-input robustness: negative duration as string, extremely long
      names, emoji/unicode in employee & case fields, SQL-injection-shaped
      strings (confirm parameterized queries).
  (3) leave that partially overlaps a work slot (half-day leave + half-day work
      same day) -> capacity / blocking behaviour.
  (4) deleting / adjusting a slot not in the current day's window (other day,
      wrong id).
  (5) empty / whitespace-only required fields.

SAFETY:
- Isolated temp SQLite DB (never the real pre_schedule.db / PostgreSQL prod).
- Lark Base sync/delete stubbed -> no real Lark/Email, 吳科翰 demo rows untouched.

Run: /workspace/.venv_r41/bin/python -m pytest test_edge_cases_r2.py -v
"""
import os, sqlite3, importlib, tempfile
from urllib.parse import quote
import pytest
from fastapi.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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

PERSON = "吳柏頤"          # real catalog employee (group lead)
DATE = "2026-11-02"         # a Monday, far from 吳科翰's demo rows
CASE = "C115055-1"          # real catalog case

APP_MODULE = os.environ.get("YX_APP_MODULE", "app")


@pytest.fixture()
def client(monkeypatch):
    appmod = importlib.import_module(APP_MODULE)
    importlib.reload(appmod)

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.executescript(DDL)
    conn.commit()
    conn.close()

    monkeypatch.setattr(appmod, "SQLITE_PATH", tmp.name)
    monkeypatch.setattr(appmod, "sync_slot_to_lark_base", lambda row: "recTESTSTUB")
    monkeypatch.setattr(appmod, "delete_slot_from_lark_base", lambda rid: True)

    c = TestClient(appmod.app, raise_server_exceptions=False)
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


def rows_for(client, **where):
    conn = sqlite3.connect(client._dbfile)
    conn.row_factory = sqlite3.Row
    q = "SELECT * FROM pre_schedule_hourly_slot WHERE 1=1"
    params = []
    for k, v in where.items():
        q += f" AND {k}=?"
        params.append(v)
    out = [dict(r) for r in conn.execute(q, params).fetchall()]
    conn.close()
    return out


# ---------------------------------------------------------------------------
# (1) Date-handling boundaries
# ---------------------------------------------------------------------------
def test_1_month_end_accepted(client):
    """Last day of a month is a normal valid work_date."""
    r = create(client, work_date="2026-11-30")
    assert r.status_code == 200, f"month-end date should be accepted, got {r.status_code}: {r.text}"


def test_1_year_boundary_independent(client):
    """Dec 31 and Jan 1 of next year are distinct days: same-time slots on each
    must both succeed (no cross-year capacity/overlap bleed)."""
    r1 = create(client, work_date="2026-12-31", start_time="08:00", end_time="10:00")
    r2 = create(client, work_date="2027-01-01", start_time="08:00", end_time="10:00")
    assert r1.status_code == 200 and r2.status_code == 200, (
        f"year-boundary days must be independent, got {r1.status_code}/{r2.status_code}")


def test_1_invalid_calendar_date(client):
    """2026-02-30 / 2026-13-01 are impossible calendar dates; a scheduling
    system should reject them rather than silently store garbage."""
    bad = create(client, work_date="2026-02-30")
    assert bad.status_code in (400, 422), (
        f"impossible calendar date should be rejected, got {bad.status_code}")


def test_1_non_iso_date_rejected(client):
    """Non-ISO formats (slashes, US order, free text) should be rejected."""
    for d in ["2026/11/02", "11-02-2026", "Nov 2 2026", "20261102"]:
        r = create(client, work_date=d)
        assert r.status_code in (400, 422), (
            f"non-ISO date {d!r} should be rejected, got {r.status_code}")


def test_1_out_of_range_clock_rejected(client):
    """25:00 / 12:60 are out-of-range wall-clock values; must not be stored as
    a valid window."""
    r1 = create(client, start_time="08:00", end_time="25:00", hours=2.0)
    assert r1.status_code in (400, 422), f"end=25:00 should be rejected, got {r1.status_code}"
    r2 = create(client, start_time="08:00", end_time="09:60", hours=2.0)
    assert r2.status_code in (400, 422), f"minute=60 should be rejected, got {r2.status_code}"


# ---------------------------------------------------------------------------
# (2) Malformed-input robustness
# ---------------------------------------------------------------------------
def test_2_negative_hours_string_rejected(client):
    """hours given as the string "-2" must be rejected (not silently stored)."""
    r = client.post("/api/slots", json=mk(hours="-2"))
    assert r.status_code == 422, f"negative string hours should be rejected, got {r.status_code}: {r.text}"


def test_2_non_numeric_hours_rejected(client):
    r = client.post("/api/slots", json=mk(hours="abc"))
    assert r.status_code == 422, f"non-numeric hours should be rejected, got {r.status_code}"


def test_2_extremely_long_name(client):
    """A 5000-char employee_name should not crash the server (500)."""
    long = "超" * 5000
    r = client.post("/api/slots",
                    json=mk(employee_name=long),
                    headers={"X-Actor-Name": quote(long)})
    # Unknown actor -> 401 is fine. The invariant: never a 500 / crash.
    assert r.status_code != 500, f"long name crashed server: {r.status_code}: {r.text[:200]}"


def test_2_emoji_unicode_fields(client):
    """Emoji / exotic unicode in free-text fields must round-trip safely."""
    note = "emoji 🧪🔧 零幅 ✅ ​‮"
    r = create(client, work_note=note, work_item="點雲處理 🛰️")
    assert r.status_code == 200, f"unicode fields should be accepted, got {r.status_code}: {r.text}"
    stored = rows_for(client, slot_id=r.json()["slot"]["slot_id"])[0]
    assert stored["work_note"] == note, "unicode work_note must round-trip unchanged"


def test_2_sql_injection_shaped_strings(client):
    """Injection-shaped strings must be treated as data (parameterized queries),
    never executed. The table must survive."""
    evil = "C1'; DROP TABLE pre_schedule_hourly_slot;--"
    r = create(client, case_code=evil, work_note="x' OR '1'='1")
    assert r.status_code == 200, f"injection-shaped data should store harmlessly, got {r.status_code}: {r.text}"
    # Table still exists and the literal string was stored verbatim.
    got = rows_for(client, slot_id=r.json()["slot"]["slot_id"])
    assert got and got[0]["case_code"] == evil, "injection string must be stored verbatim as data"
    # Filter query path is also parameterized.
    r2 = client.get("/api/slots", params={"employee_name": "x' OR '1'='1"})
    assert r2.status_code == 200 and r2.json()["count"] == 0


# ---------------------------------------------------------------------------
# (3) Partial-day leave overlapping a work slot
# ---------------------------------------------------------------------------
def test_3_halfday_leave_blocks_work_same_day(client):
    """A morning half-day leave (08:00-12:00) plus an afternoon work slot on the
    SAME day. Current policy: any 休假 row on a day blocks all work that day.
    Verify the behaviour is deterministic and capacity math is not corrupted."""
    r1 = create(client, slot_type="休假", start_time="08:00", end_time="12:00", hours=4.0)
    assert r1.status_code == 200, f"half-day leave create failed: {r1.text}"
    r2 = create(client, slot_type="出工", start_time="13:00", end_time="17:00", hours=4.0, priority_rank=2)
    assert r2.status_code == 409, (
        f"work on a day with a leave row is blocked by policy, got {r2.status_code}")


def test_3_leave_then_leave_same_day(client):
    """Two leave rows same day should not raise a conflict against each other
    (leave creates skip the conflict check entirely)."""
    assert create(client, slot_type="休假", start_time="08:00", end_time="12:00", hours=4.0).status_code == 200
    assert create(client, slot_type="休假", start_time="13:00", end_time="17:00", hours=4.0,
                  priority_rank=2).status_code == 200


# ---------------------------------------------------------------------------
# (4) Adjust / delete outside current day's window
# ---------------------------------------------------------------------------
def test_4_adjust_slot_on_other_day(client):
    """Adjusting a slot dated on a different day than 'today' must still work
    against that slot's own stored work_date (window is per-slot, not global)."""
    a = create(client, work_date="2027-03-15", start_time="08:00", end_time="10:00", hours=2.0).json()["slot"]
    r = client.post(f"/api/slots/{a['slot_id']}/adjust", json={"delta": 1.0})
    assert r.status_code == 200, f"adjust of other-day slot failed: {r.status_code}: {r.text}"
    assert r.json()["slot"]["hours"] == 3.0


def test_4_adjust_nonexistent_slot(client):
    r = client.post("/api/slots/PS-NOPE-00000000-01-000/adjust", json={"delta": 1.0})
    assert r.status_code == 404, f"adjusting a missing slot should 404, got {r.status_code}"


def test_4_delete_other_day_slot(client):
    """Deleting a slot dated on a far-off day should succeed and only remove
    that slot."""
    a = create(client, work_date="2027-06-30", start_time="08:00", end_time="10:00", hours=2.0).json()["slot"]
    b = create(client, work_date=DATE, start_time="08:00", end_time="10:00", hours=2.0).json()["slot"]
    d = client.delete(f"/api/slots/{a['slot_id']}")
    assert d.status_code == 200 and d.json()["ok"]
    assert rows_for(client, slot_id=a["slot_id"]) == []
    assert len(rows_for(client, slot_id=b["slot_id"])) == 1, "unrelated slot must survive"


# ---------------------------------------------------------------------------
# (5) Empty / whitespace-only required fields
# ---------------------------------------------------------------------------
def test_5_empty_employee_name_rejected(client):
    r = client.post("/api/slots", json=mk(employee_name=""), headers={"X-Actor-Name": quote("")})
    assert r.status_code in (401, 422), f"empty employee_name should be rejected, got {r.status_code}"


def test_5_whitespace_employee_name_rejected(client):
    r = client.post("/api/slots", json=mk(employee_name="   "),
                    headers={"X-Actor-Name": quote("   ")})
    assert r.status_code in (401, 422), f"whitespace employee_name should be rejected, got {r.status_code}"


def test_5_empty_work_date_rejected(client):
    r = create(client, work_date="")
    assert r.status_code in (400, 422), f"empty work_date should be rejected, got {r.status_code}"


def test_5_whitespace_case_code_rejected(client):
    r = create(client, case_code="   ")
    assert r.status_code in (400, 422), f"whitespace case_code should be rejected, got {r.status_code}"


def test_5_empty_work_item_rejected(client):
    r = create(client, work_item="")
    assert r.status_code in (400, 422), f"empty work_item should be rejected, got {r.status_code}"


def test_5_invalid_placeholder_and_jiedian_work_item_rejected(client):
    """Single-char, symbol-only, placeholder, or 節點管理 work_item strings must be rejected."""
    for bad_item in [".", "-", "無", "1", "測試", "test", "節點管理", "節點管理: 自主管理"]:
        r = create(client, work_item=bad_item)
        assert r.status_code in (400, 422), f"invalid work_item {bad_item!r} should be rejected, got {r.status_code}"
