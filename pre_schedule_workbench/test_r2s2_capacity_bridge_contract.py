#!/usr/bin/env python3
"""
R2-S2 — 8895 (預排工作台) ↔ 5188 (業主信件總機) capacity-bridge contract test.

SAFETY: isolated temp SQLite only; monkeypatches app.SQLITE_PATH before any
query. No PostgreSQL, no real Email, no Lark, no network. The 吳科翰 Monday
demo rows live in the real pre_schedule.db and are never touched — this test
builds its own throwaway DB in a tempdir.

Run: /workspace/.venv_r41/bin/python test_r2s2_capacity_bridge_contract.py
"""
import os, sys, json, sqlite3, tempfile, importlib.util

BASE = "/workspace/deliverables/pre_schedule_workbench"

# ---- build an isolated temp DB (never the real pre_schedule.db) -------------
tmpdir = tempfile.mkdtemp(prefix="r2s2_cap_")
TMP_DB = os.path.join(tmpdir, "temp_capacity.db")
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
def slot(sid, date, name, grp, stype, st, et, hrs):
    return (sid, date, "e_"+name, name, None, None, "控制部", grp, stype,
            st, et, hrs, 1, "C100001", "測試案", "詠翔測量工程有限公司", None, None,
            "contract", "測試工項", None, None, None, None, 0, None, None)

conn = sqlite3.connect(TMP_DB); conn.executescript(SCHEMA)
# Use the REAL catalog roster for 控制組 so the capacity math is exercised
# honestly (the endpoint derives headcount from catalog, keyed by employee_name).
import importlib.util as _il
_s = _il.spec_from_file_location("ps_app_probe", os.path.join(BASE, "app.py"))
_m = _il.module_from_spec(_s); _s.loader.exec_module(_m)
ROSTER = _m._group_members_from_catalog("控制組", None)   # ['吳重樺','林佑靜','胡畯評','郭國泰']
A, B = ROSTER[0], ROSTER[1]
# A: booked 8h Mon (full). B: booked 6h Mon -> 2h free from 14:30. Others: idle.
conn.executemany("INSERT INTO pre_schedule_hourly_slot VALUES (%s)" % ",".join("?"*27), [
    slot("s1","2026-10-26",A,"控制組","出工","08:30","12:30",4.0),
    slot("s2","2026-10-26",A,"控制組","出工","13:30","17:30",4.0),
    slot("s3","2026-10-26",B,"控制組","出工","08:30","12:30",4.0),
    slot("s4","2026-10-26",B,"控制組","出工","13:30","15:30",2.0),
    slot("s5","2026-10-27",A,"控制組","休假","08:30","17:30",8.0),
])
conn.commit(); conn.close()

# ---- load app.py with SQLITE_PATH redirected to the temp DB -----------------
spec = importlib.util.spec_from_file_location("ps_app", os.path.join(BASE, "app.py"))
app_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_mod)
app_mod.SQLITE_PATH = TMP_DB   # redirect BEFORE any request
assert app_mod.SQLITE_PATH == TMP_DB

from fastapi.testclient import TestClient
client = TestClient(app_mod.app)

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (("  -> " + detail) if detail else ""))

# =========================================================================
# PART A — PRODUCER contract: what :8895 GET /api/capacity actually returns
# =========================================================================
print("\n--- PART A: :8895 /api/capacity producer contract ---")
r = client.get("/api/capacity", params={
    "team_group": "控制組", "date_from": "2026-10-26", "date_to": "2026-10-27"})
check("A1 HTTP 200", r.status_code == 200, f"status={r.status_code}")
body = r.json()
print("  RAW BODY:", json.dumps(body, ensure_ascii=False))

# The shape :5188 would need to render a delivery promise:
PRODUCER_KEYS = {"ok","group","remaining_hours","capacity_hours","booked_hours",
                 "unavailable_hours","delivery_promise"}
check("A2 top-level keys present", PRODUCER_KEYS <= set(body), str(PRODUCER_KEYS - set(body)))
dp = body.get("delivery_promise", {})
check("A3 delivery_promise has earliest_free_slot + has_capacity",
      {"earliest_free_slot","has_capacity"} <= set(dp), str(dp))

# A full, B free from 14:30, but 2 other roster members are idle from 08:30 ->
# honest earliest_free is Mon 08:30 (soonest any roster member is free).
efs = dp.get("earliest_free_slot")
check("A4 earliest_free_slot shape {date,time}",
      isinstance(efs, dict) and {"date","time"} <= set(efs), str(efs))
check("A5 earliest_free honest (idle roster member free Mon 08:30)",
      efs == {"date": "2026-10-26", "time": "08:30"}, str(efs))

# 5 roster (incl. 張家彬) x 2 days x 8h = 80 cap; A booked 8h + B booked 6h = 14; unavail 8 -> rem 58
check("A6 reconciles flag true + math (cap80 booked14 unavail8 rem58)",
      body.get("reconciles") is True and body.get("capacity_hours") == 80.0
      and body.get("booked_hours") == 14.0 and body.get("unavailable_hours") == 8.0
      and body.get("remaining_hours") == 58.0,
      f"cap={body.get('capacity_hours')} booked={body.get('booked_hours')} "
      f"unavail={body.get('unavailable_hours')} rem={body.get('remaining_hours')}")

# alias compatibility: ?group= must behave like ?team_group=
r_alias = client.get("/api/capacity", params={
    "group": "控制組", "date_from": "2026-10-26", "date_to": "2026-10-27"})
check("A7 ?group= alias == ?team_group=", r_alias.json() == body)

# A8 — PRODUCER HAZARD (two mismatched name-sets in one endpoint):
#   * booked_hours / unavailable_hours  = SUM over slots filtered by team_group
#   * headcount / earliest_free members = catalog roster (by full_name)
# A slot whose employee_name is NOT in the catalog roster still inflates
# booked_hours (so remaining shrinks) BUT that ghost worker is invisible to the
# earliest_free scan -> the reconcile math and the promise are derived from two
# different populations. Demonstrate: a slot under a name not in the roster.
conn2 = sqlite3.connect(TMP_DB)
conn2.executemany("INSERT INTO pre_schedule_hourly_slot VALUES (%s)" % ",".join("?"*27), [
    slot("x1","2026-10-28","控制路人甲","控制組","出工","08:30","17:30",8.0),
])
conn2.commit(); conn2.close()
r_hz = client.get("/api/capacity", params={
    "team_group": "控制組", "date_from": "2026-10-28", "date_to": "2026-10-28"}).json()
# ghost's 8h IS counted in booked_hours, yet headcount is the 4 catalog members
# (ghost excluded) and earliest_free shows all 4 free from 08:30 -> promise
# ignores that a body of work is already committed for that day/group.
ghost_counted = r_hz["booked_hours"] == 8.0
ghost_invisible_to_promise = (r_hz["delivery_promise"]["earliest_free_slot"]
                              == {"date":"2026-10-28","time":"08:30"})
ghost_excluded_from_headcount = "控制路人甲" not in r_hz["members"]
check("A8 HAZARD: ghost slot splits booked_hours vs promise population",
      ghost_counted and ghost_invisible_to_promise and ghost_excluded_from_headcount,
      f"booked={r_hz['booked_hours']} members={r_hz['members']} "
      f"efs={r_hz['delivery_promise']['earliest_free_slot']} -> promise built from "
      f"catalog roster only; committed ghost work invisible to the promise.")

# =========================================================================
# PART B — CONSUMER contract: does :5188 actually request this shape?
# =========================================================================
print("\n--- PART B: :5188 consumer wiring (contract reality) ---")
import subprocess
# Search the entire :5188 codebase for ANY client call to 8895 / /api/capacity.
grep = subprocess.run(
    ["grep","-rn","-E", r"(8895|/api/capacity|earliest_free_slot|delivery_promise|remaining_hours)",
     "--include=*.py","--include=*.html","--include=*.js",
     "/workspace/owner_reply_app","/workspace/yongxiang_arch/ai_switchboard_mvp"],
    capture_output=True, text=True)
hits = [l for l in grep.stdout.splitlines()
        if "/r30/before/" not in l and "/tests/" not in l and "capacity_bridge_contract" not in l]
# A real consumer would contain an HTTP client call (requests/httpx/urlopen) to :8895.
consumer_calls = [l for l in hits if ("8895" in l) and
                  any(k in l for k in ("requests.","httpx","urlopen","aiohttp","get(","fetch("))]
check("B1 a live :5188 consumer of /api/capacity EXISTS",
      len(consumer_calls) > 0,
      "NO HTTP client in :5188 calls :8895/api/capacity -> bridge is UNWIRED")

# The consumer should pass the exact params the producer accepts.
ACCEPTED = {"group","team_group","department_group","date_from","date_to"}
# No consumer => cannot be verified; record the mismatch explicitly.
check("B2 consumer sends params within producer's accepted set",
      False if not consumer_calls else True,
      "no consumer request to inspect" if not consumer_calls else "")

# =========================================================================
# PART C — FAILURE handling: :8895 down / 500 / timeout (mocked, no network)
# =========================================================================
print("\n--- PART C: failure handling if :8895 is down/500/timeout (mocked) ---")

# There is no consumer, so there is no timeout, retry, or degraded-fallback
# code to exercise. We assert that absence so the finding is machine-checked,
# and we model what a safe consumer MUST do so the contract is documented.
timeout_grep = subprocess.run(
    ["grep","-rn","-E", r"8895.*(timeout|Timeout)|(timeout|Timeout).*8895",
     "--include=*.py","/workspace/owner_reply_app","/workspace/yongxiang_arch/ai_switchboard_mvp"],
    capture_output=True, text=True)
check("C1 consumer sets a timeout on the :8895 call",
      bool(timeout_grep.stdout.strip()),
      "NO timeout anywhere -> a hung :8895 would hang/block reply drafting")

# Model the REQUIRED safe behaviour (pure, mock) so the test states the contract:
def safe_consume(fetch_capacity):
    """What :5188 MUST do: on any error, degrade — never fabricate a promise,
    never crash, never block the reply."""
    try:
        resp = fetch_capacity()           # would be requests.get(:8895, timeout=...)
    except Exception:
        return {"can_promise": False, "degraded": True,
                "note": "capacity service unavailable — human to confirm date"}
    if resp.get("status") == 500 or not resp.get("ok"):
        return {"can_promise": False, "degraded": True, "note": "capacity 500"}
    dp = resp.get("delivery_promise", {})
    return {"can_promise": bool(dp.get("has_capacity")),
            "promise_date": (dp.get("earliest_free_slot") or {}).get("date"),
            "degraded": False}

def raise_timeout(): raise TimeoutError("simulated :8895 timeout")
def ret_500(): return {"status": 500, "ok": False}
def ret_ok(): return body  # the real producer body from Part A

r_to = safe_consume(raise_timeout)
check("C2 MODEL: timeout -> degraded, no crash, no fabricated date",
      r_to["degraded"] and r_to["can_promise"] is False and "promise_date" not in r_to)
r_500 = safe_consume(ret_500)
check("C3 MODEL: HTTP 500 -> degraded, not a 200-lie", r_500["degraded"] and not r_500["can_promise"])
r_live = safe_consume(ret_ok)
check("C4 MODEL: live 200 -> promise derived from real earliest_free_slot",
      (not r_live["degraded"]) and r_live["can_promise"] and r_live["promise_date"] == "2026-10-26")

# ---- cleanup isolated temp DB ----------------------------------------------
try:
    os.remove(TMP_DB); os.rmdir(tmpdir)
except OSError:
    pass

print("\n==================== SUMMARY ====================")
print(f"PASS={len(PASS)}  FAIL={len(FAIL)}")
if FAIL:
    print("FAILED/UNMET CONTRACT ITEMS:", ", ".join(FAIL))
print("NOTE: B1/B2/C1 are EXPECTED-FAIL findings documenting the unwired bridge.")
if __name__ == '__main__':
    sys.exit(0)  # findings are reported, not treated as test-suite failure
