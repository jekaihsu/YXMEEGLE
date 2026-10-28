"""
R2-S4 — RBAC residual bypass red-team for pre_schedule_workbench/app.py

Adversarial tests on top of the S02 RBAC layer (resolve_actor / authz_schedule_for
/ authz_slot_owner). Focus areas:
  (1) header injection / spoofing (unicode, trailing space, dup header, case, URL-encode)
  (2) coverage: every state-mutating endpoint is guarded
  (3) stale ownership after a slot's owner moves sub_group

SAFETY: runs against an isolated temp SQLite DB (never prod PostgreSQL / the
real pre_schedule.db) and a mocked lark-cli runner (no network / no real Lark).
吳科翰's demo rows are never touched — we use our own seeded fixture rows.
"""
import json, os, shutil, sqlite3, tempfile, urllib.parse
import pytest
from fastapi.testclient import TestClient

import app as appmod

CASE_CODE = "C115055-1"

# ---- isolated environment ---------------------------------------------------
@pytest.fixture()
def client(monkeypatch, tmp_path):
    db = tmp_path / "test_rbac.db"
    # build schema matching prod columns
    cols = ['slot_id','work_date','employee_id','employee_name','lark_open_id',
            'v3_person_record_id','department_group','team_group','slot_type',
            'start_time','end_time','hours','priority_rank','case_code','case_name',
            'client_name','v3_case_record_id','contract_item_code','schedule_reason',
            'work_item','work_note','est_quantity','est_points','upstream_dep_note',
            'converted_to_daily_log','lark_sync_status','lark_record_id']
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE pre_schedule_hourly_slot (%s)" % ",".join(cols))
    conn.commit(); conn.close()

    monkeypatch.setattr(appmod, "SQLITE_PATH", str(db))
    # mock lark-cli: never touch network
    monkeypatch.setattr(appmod, "LARK_CLI_RUNNER",
                        lambda cmd: json.dumps({"ok": True, "data": {"record": {"record_id_list": ["recMOCK123"]}}}))
    return TestClient(appmod.base_app() if hasattr(appmod, "base_app") else appmod.app)


def seed_slot(db_path, slot_id, employee_name, team_group, dept="內業部門", stype="出工"):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO pre_schedule_hourly_slot "
        "(slot_id,work_date,employee_id,employee_name,team_group,department_group,"
        "slot_type,start_time,end_time,hours,priority_rank,case_code,case_name,"
        "converted_to_daily_log,lark_record_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (slot_id, "2099-01-05", "empX", employee_name, team_group, dept, stype,
         "08:30", "10:30", 2.0, 1, CASE_CODE, "案", 0, ""),
    )
    conn.commit(); conn.close()


def hdr(name, encode=True):
    # emulate how a browser/client would send a non-ASCII header: percent-encoded
    if encode and any(ord(c) > 127 for c in name):
        name = urllib.parse.quote(name)
    return {"X-Actor-Name": name}


CREATE_BODY = {
    "work_date": "2099-01-06", "slot_type": "出工", "start_time": "08:30",
    "end_time": "10:30", "hours": 2.0, "case_code": CASE_CODE, "work_item": "資料整理",
}


# =====================================================================
# (1) HEADER SPOOFING / INJECTION
# =====================================================================
def test_missing_header_401(client):
    r = client.post("/api/slots", json={**CREATE_BODY, "employee_name": "朱雅雯"})
    assert r.status_code == 401

def test_unknown_identity_401(client):
    r = client.post("/api/slots", json={**CREATE_BODY, "employee_name": "朱雅雯"},
                    headers=hdr("不存在的人"))
    assert r.status_code == 401

def test_trailing_space_does_not_resolve(client):
    # "張家彬 " (trailing space) must NOT resolve to the real lead
    r = client.post("/api/slots", json={**CREATE_BODY, "employee_name": "朱雅雯"},
                    headers={"X-Actor-Name": urllib.parse.quote("張家彬 ")})
    assert r.status_code == 401, "trailing-space name should fail closed, not escalate"

def test_leading_space_does_not_resolve(client):
    r = client.post("/api/slots", json={**CREATE_BODY, "employee_name": "朱雅雯"},
                    headers={"X-Actor-Name": urllib.parse.quote(" 張家彬")})
    assert r.status_code == 401

def test_case_variation_does_not_resolve(client):
    # Latin name in catalog is "Vincent"; "vincent"/"VINCENT" must not resolve
    r = client.post("/api/slots", json={**CREATE_BODY, "employee_name": "許喆凱"},
                    headers={"X-Actor-Name": "vincent"})
    assert r.status_code == 401

def test_unicode_nfkc_lookalike_does_not_resolve(client):
    # full-width / compatibility chars should not collapse into a valid identity
    r = client.post("/api/slots", json={**CREATE_BODY, "employee_name": "朱雅雯"},
                    headers={"X-Actor-Name": urllib.parse.quote("張家彬​")})  # zero-width space
    assert r.status_code == 401

def test_duplicate_header_first_value_used(client):
    # Two X-Actor-Name headers: a spoofer appends a lead after a self value.
    # Whatever value is picked, it must be a real catalog identity AND still be
    # subject to authz — never silently authorize the second (lead) value for
    # the first (member)'s request.
    member = "朱雅雯"
    lead = "張家彬"
    # httpx joins repeated headers with ", " → "朱雅雯, 張家彬" which is not a
    # catalog name → must 401 (fail closed), not resolve to either.
    raw = urllib.parse.quote(member) + ", " + urllib.parse.quote(lead)
    r = client.post("/api/slots", json={**CREATE_BODY, "employee_name": lead},
                    headers={"X-Actor-Name": raw})
    assert r.status_code in (401, 403), "duplicate/joined header must not escalate"


# =====================================================================
# (1b) ROLE ESCALATION — member cannot schedule for others
# =====================================================================
def test_member_cannot_schedule_other_group_member(client):
    r = client.post("/api/slots", json={**CREATE_BODY, "employee_name": "鄭文澤"},
                    headers=hdr("朱雅雯"))
    assert r.status_code == 403

def test_member_can_schedule_self(client):
    r = client.post("/api/slots", json={**CREATE_BODY, "employee_name": "朱雅雯"},
                    headers=hdr("朱雅雯"))
    assert r.status_code == 200

def test_lead_cannot_schedule_other_group(client):
    # 張家彬 leads 品管組; 鄭文澤 is in 圖資組 → cross-group must 403
    r = client.post("/api/slots", json={**CREATE_BODY, "employee_name": "鄭文澤"},
                    headers=hdr("張家彬"))
    assert r.status_code == 403

def test_lead_can_schedule_own_group_member(client):
    r = client.post("/api/slots", json={**CREATE_BODY, "employee_name": "朱雅雯"},
                    headers=hdr("張家彬"))
    assert r.status_code == 200


# =====================================================================
# (2) ENDPOINT COVERAGE — every mutating route guarded
# =====================================================================
def test_adjust_requires_auth(client):
    seed_slot(appmod.SQLITE_PATH, "SLOT-A", "朱雅雯", "品管組")
    r = client.post("/api/slots/SLOT-A/adjust", json={"delta": 1.0})
    assert r.status_code == 401

def test_adjust_blocks_cross_group_member(client):
    seed_slot(appmod.SQLITE_PATH, "SLOT-B", "鄭文澤", "圖資組")
    r = client.post("/api/slots/SLOT-B/adjust", json={"delta": 1.0}, headers=hdr("朱雅雯"))
    assert r.status_code == 403

def test_delete_requires_auth(client):
    seed_slot(appmod.SQLITE_PATH, "SLOT-C", "朱雅雯", "品管組")
    r = client.delete("/api/slots/SLOT-C")
    assert r.status_code == 401

def test_delete_blocks_cross_group(client):
    seed_slot(appmod.SQLITE_PATH, "SLOT-D", "鄭文澤", "圖資組")
    r = client.delete("/api/slots/SLOT-D", headers=hdr("朱雅雯"))
    assert r.status_code == 403

def test_convert_daily_requires_auth(client):
    seed_slot(appmod.SQLITE_PATH, "SLOT-E", "朱雅雯", "品管組")
    r = client.post("/api/slots/SLOT-E/convert-daily")
    assert r.status_code == 401

def test_convert_daily_blocks_cross_group(client):
    seed_slot(appmod.SQLITE_PATH, "SLOT-F", "鄭文澤", "圖資組")
    r = client.post("/api/slots/SLOT-F/convert-daily", headers=hdr("朱雅雯"))
    assert r.status_code == 403


def test_route_inventory_every_mutating_route_is_guarded():
    """Static cross-check: enumerate all routes; every state-mutating method
    (POST/PUT/PATCH/DELETE) handler must reference resolve_actor."""
    import inspect
    unguarded = []
    for route in appmod.app.routes:
        methods = getattr(route, "methods", set()) or set()
        mutating = methods & {"POST", "PUT", "PATCH", "DELETE"}
        if not mutating:
            continue
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        src = inspect.getsource(endpoint)
        if "resolve_actor" not in src:
            unguarded.append((sorted(mutating), route.path, endpoint.__name__))
    assert not unguarded, f"Unguarded mutating routes: {unguarded}"


# =====================================================================
# (3) STALE OWNERSHIP — owner moved sub_group after slot creation
# =====================================================================
def _patch_catalog(monkeypatch, employees):
    monkeypatch.setattr(appmod, "load_catalog", lambda: {"employees": employees, "cases": []})

def test_stale_owner_moved_out_lead_loses_access(client, monkeypatch):
    """A slot stored with team_group=品管組 for 朱雅雯. If 朱雅雯 later moves to
    圖資組 in the catalog, the 品管組 lead (張家彬) must NOT be able to edit it —
    authz follows live catalog membership, so this should 403 (fail closed)."""
    seed_slot(appmod.SQLITE_PATH, "SLOT-STALE1", "朱雅雯", "品管組")  # stored group stale
    _patch_catalog(monkeypatch, [
        {"full_name": "張家彬", "sub_group": "品管組", "is_group_lead": True},
        {"full_name": "朱雅雯", "sub_group": "圖資組", "is_group_lead": False},  # moved out
    ])
    r = client.post("/api/slots/SLOT-STALE1/adjust", json={"delta": 1.0}, headers=hdr("張家彬"))
    assert r.status_code == 403, "lead must lose access when owner moved out of group"

def test_stale_owner_moved_in_new_lead_gains_access(client, monkeypatch):
    """Converse: slot stored team_group=圖資組 for a person now in 品管組.
    The 品管組 lead gains access because authz uses live membership. This is the
    *intended* semantics; the test documents it so a regression is visible."""
    seed_slot(appmod.SQLITE_PATH, "SLOT-STALE2", "朱雅雯", "圖資組")  # stale stored group
    _patch_catalog(monkeypatch, [
        {"full_name": "張家彬", "sub_group": "品管組", "is_group_lead": True},
        {"full_name": "朱雅雯", "sub_group": "品管組", "is_group_lead": False},  # moved in
    ])
    r = client.post("/api/slots/SLOT-STALE2/adjust", json={"delta": 1.0}, headers=hdr("張家彬"))
    assert r.status_code == 200
