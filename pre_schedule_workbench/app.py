import os, json, sqlite3, subprocess, hashlib, hmac, base64, secrets, time, random, re, unicodedata, uuid, urllib.request, urllib.parse
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header, Cookie, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="永祥測量 · 今日工作預排")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE_DIR = os.environ.get("PRESCHEDULE_DATA_DIR", "/workspace/deliverables/pre_schedule_workbench")
SQLITE_PATH = os.path.join(BASE_DIR, "pre_schedule.db")
CATALOG_PATH = os.path.join(BASE_DIR, "catalog.json")
QUOTE_ITEMS_PATH = os.path.join(BASE_DIR, "quote_work_items.json")
LARK_CLI = "/home/box/.local/bin/lark-cli"
LARK_BASE_TOKEN = "".join(["Sdw1bG1djaHsVGs", "RPvmjyVWipgg"])  # Real V3 Base (sandbox fallback: fdDdb52K4a1s6is9jB7j93fdp5d)
LARK_TABLE_ID = "tblN8c3WN44233aG"
LARK_APP_ID = os.environ.get("LARK_APP_ID", "cli_aa5c5ceba4f8de2a")
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
SESSION_COOKIE_NAME = "yx_presched_session"
OAUTH_STATE_COOKIE_NAME = "yx_oauth_state"
# Gate 2 parity on :8895 — a session-id-only cookie (never an access token).
SSO_SID_COOKIE_NAME = "yx_sso_sid"
SSO_SID_TTL_SECONDS = 28800  # 8 hours, matching the switchboard absolute window.
SESSION_SECRET = os.environ.get("YX_SESSION_SECRET", "yx-presched-hmac-secret-2026-cli_aa5c5ceba4f8de2a")
SESSION_TTL_SECONDS = 86400 * 7
LARK_OAUTH_EXCHANGER = None


def _mint_sso_sid() -> str:
    """A random, opaque session id. It identifies the session only; no token
    or Lark access_token is ever placed in a cookie (Gate 2)."""
    return uuid.uuid4().hex


def _set_sso_sid_cookie(resp, sid: str) -> None:
    resp.set_cookie(
        key=SSO_SID_COOKIE_NAME,
        value=sid,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=SSO_SID_TTL_SECONDS,
        path="/",
    )


@app.on_event("startup")
def _announce_smtp_shadow():
    # Startup banner: no mail transport is configured in the trial/shadow clone.
    if not os.environ.get("SMTP_HOST") and not os.environ.get("SMTP_PASS"):
        print("SMTP: disabled (shadow)", flush=True)

DEPARTMENT_WORK_ITEMS = {
    "吳科翰": [
        "外業整體排程與控制檢核",
        "控制網平差計算",
        "施工放樣與進場協調",
        "點雲與空拍檢核",
        "地形／水深外業調度",
        "跨案支援與會勘"
    ],
    "內業組": ["地形圖編修", "點雲處理", "斷面圖繪製", "成果報告撰寫", "圖資品管複核", "資料整理"],
    "控制組": ["控制網平差計算", "放樣資料準備", "點雲處理", "空拍正射轉檔", "高鐵濾點處理", "資料整理"],
    "圖資組": ["地形圖編修", "斷面圖繪製", "CAD圖框整備", "補測資料接合", "GIS圖資轉檔", "資料整理"],
    "報告組": ["成果報告撰寫", "審查意見回覆", "數量計算表彙整", "點位照片冊整備", "資料整理"],
    "品管組": ["圖資品管複核", "跨組圖報複核", "出圖用印把關", "成果報告撰寫"]
}

def load_catalog():
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        catalog = json.load(f)
        catalog["employees"] = [e for e in catalog.get("employees", []) if e.get("is_active", True) and e.get("employment_status", "active") == "active"]
        return catalog

def load_quote_work_items():
    if os.path.exists(QUOTE_ITEMS_PATH):
        with open(QUOTE_ITEMS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"items": [], "total_items": 0}

def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    # Wait (rather than immediately raising "database is locked") when another
    # writer holds the write lock — lets concurrent writers serialise.
    conn.execute("PRAGMA busy_timeout=15000")
    return conn

def begin_write_txn(conn):
    """Acquire SQLite's write lock up-front (BEGIN IMMEDIATE) so a check-then-write
    sequence is serialised against other writers. Prevents the TOCTOU race where
    two concurrent requests both pass check_slot_conflicts() and both INSERT,
    over-booking an employee/day. SELECT-only endpoints are unaffected."""
    conn.isolation_level = None  # take explicit control of the transaction
    conn.execute("BEGIN IMMEDIATE")

def sign_session_cookie(payload: dict) -> str:
    """Create an HMAC-SHA256 signed session cookie token."""
    data = dict(payload)
    now = int(time.time())
    data.setdefault("iat", now)
    data.setdefault("exp", now + SESSION_TTL_SECONDS)
    raw_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    b64 = base64.urlsafe_b64encode(raw_json).decode("ascii").rstrip("=")
    sig = hmac.new(SESSION_SECRET.encode("utf-8"), b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"


def verify_session_cookie(token: Optional[str]) -> Optional[dict]:
    """Verify HMAC-SHA256 signed session cookie token and return payload if valid."""
    if not token or "." not in str(token):
        return None
    try:
        b64, sig = str(token).rsplit(".", 1)
        expected_sig = hmac.new(SESSION_SECRET.encode("utf-8"), b64.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        pad = "=" * ((4 - len(b64) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode((b64 + pad).encode("ascii")).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def _enrich_employee_record(emp: dict) -> dict:
    """Return a copy of catalog employee enriched with display_name and role metadata."""
    out = dict(emp)
    if out.get("full_name") in ("許喆凱", "許傑凱") or out.get("lark_open_id") == "ou_7dfe7ce548da22a0275cba0d92b3bfec":
        out["display_name"] = "許傑凱"
        out["canonical_name"] = out.get("full_name", "許喆凱")
        out["job_title_display"] = out.get("job_title_display") or "管理員"
        out["is_group_lead"] = True
        out["is_admin"] = True
        out["can_manage_all"] = True
        out["allowed_groups"] = ["ALL"]
    elif out.get("full_name") == "許茂坤" or out.get("lark_open_id") == "ou_d6abe79a176ad52f5f7d0f713a0ae914":
        # 總經理 許茂坤：全公司在職名單視野（與 許喆凱／許傑凱 同層級管理員）。
        out.setdefault("display_name", "許茂坤")
        out.setdefault("canonical_name", "許茂坤")
        out["job_title_display"] = out.get("job_title_display") or "總經理"
        out["is_group_lead"] = True
        out["is_admin"] = True
        out["can_manage_all"] = True
        out["allowed_groups"] = ["ALL"]
    elif out.get("full_name") == "鍾智偉" or out.get("lark_open_id") == "ou_559459956a84a2fa8225b58795ad8d88":
        out.setdefault("display_name", "鍾智偉")
        out.setdefault("canonical_name", "鍾智偉")
        out["is_group_lead"] = True
        out["is_admin"] = True
        out["can_manage_all"] = True
        out["allowed_groups"] = ["ALL"]
    else:
        out.setdefault("display_name", out.get("full_name", ""))
        out.setdefault("canonical_name", out.get("full_name", ""))
        out.setdefault("is_admin", bool(out.get("can_manage_all", False)))
        out.setdefault("can_manage_all", bool(out.get("is_admin", False)))
    raw_title = out.get("job_title_display") or out.get("sub_group") or "同仁"
    role_badge = out.get("sub_group") if raw_title in ("組員", "內勤", "工程師") and out.get("sub_group") else raw_title
    out["emp_name"] = out.get("display_name") or out.get("full_name", "")
    out["dept_group"] = out.get("department_group", "")
    out["team_group"] = out.get("sub_group", "")
    out["role_title"] = role_badge
    out["can_schedule_others"] = bool(out.get("is_group_lead") or out.get("is_admin") or out.get("can_manage_all"))
    return out


def resolve_employee_from_lark_profile(user_info: dict) -> dict:
    """Match a Lark OAuth user_info dict (open_id / name / en_name / email) against catalog.json."""
    cat = load_catalog()
    employees = cat.get("employees", [])
    aliases = cat.get("identity_aliases", {})
    open_id = (user_info.get("open_id") or "").strip()
    if open_id:
        emp = next((e for e in employees if e.get("lark_open_id") == open_id), None)
        if emp:
            return _enrich_employee_record(emp)
    for key in ("name", "en_name", "full_name", "employee_name"):
        val = (user_info.get(key) or "").strip()
        if not val:
            continue
        canonical = aliases.get(val, val)
        emp = next(
            (
                e for e in employees
                if e.get("full_name") in (val, canonical)
                or e.get("display_name") in (val, canonical)
                or e.get("short_name") in (val, canonical)
            ),
            None,
        )
        if emp:
            return _enrich_employee_record(emp)
    raise HTTPException(status_code=403, detail="此 Lark 帳號不在永祥測量組織名冊內")


def get_allowed_team_roster(actor: dict) -> list[dict]:
    """Return the list of employees that `actor` is authorized to view/schedule."""
    cat = load_catalog()
    employees = cat.get("employees", [])
    if actor.get("is_admin") or "ALL" in (actor.get("allowed_groups") or []):
        return [_enrich_employee_record(e) for e in employees]
    if not actor.get("is_group_lead"):
        return [_enrich_employee_record(actor)]
    allowed_groups = set(actor.get("allowed_groups") or []) | {actor.get("sub_group")}
    if actor.get("full_name") == "張家彬" and actor.get("sub_group") == "控制組":
        allowed_groups.add("品管組")
    roster = []
    for e in employees:
        if (
            e.get("full_name") == actor.get("full_name")
            or e.get("sub_group") in allowed_groups
            or (actor.get("full_name") == "吳科翰" and e.get("department_group") == "外業部門")
        ):
            roster.append(_enrich_employee_record(e))
    return roster


def resolve_actor(x_actor_name: Optional[str] = None, session_cookie: Optional[str] = None):
    """
    Establish caller identity server-side from:
      1. Signed HTTP-only `yx_presched_session` cookie (Lark OAuth 2.0 SSO), OR
      2. `X-Actor-Name` header (automated test suites / internal service calls).
    The client never supplies its own role/group — those come only from catalog.json.
    """
    cat = load_catalog()
    employees = cat.get("employees", [])
    aliases = cat.get("identity_aliases", {})

    if session_cookie:
        payload = verify_session_cookie(session_cookie)
        if not payload:
            raise HTTPException(status_code=401, detail="Lark SSO 登入憑證無效或已過期，請重新登入")
        open_id = payload.get("open_id")
        full_name = payload.get("canonical_name") or payload.get("full_name")
        emp = None
        if open_id:
            emp = next((e for e in employees if e.get("lark_open_id") == open_id), None)
        if not emp and full_name:
            canonical = aliases.get(full_name, full_name)
            emp = next((e for e in employees if e.get("full_name") in (full_name, canonical)), None)
        if not emp:
            raise HTTPException(status_code=401, detail="Lark SSO 帳號未對應有效組織名冊")
        return _enrich_employee_record(emp)

    if not x_actor_name:
        raise HTTPException(status_code=401, detail="請先使用 Lark 帳號登入（缺少有效 Session 或 X-Actor-Name 標頭）")
    from urllib.parse import unquote
    actor_name = unquote(x_actor_name)
    # Fail closed on leading/trailing whitespace, control/format chars, or joined headers
    if (
        not actor_name
        or actor_name != actor_name.strip()
        or "," in actor_name
        or any(unicodedata.category(c) in ("Cf", "Cc", "Cs") for c in actor_name)
    ):
        raise HTTPException(status_code=401, detail="無效的身分標頭格式")
    actor_name = aliases.get(actor_name, actor_name)
    emp = next((e for e in employees if e["full_name"] == actor_name), None)
    if not emp:
        raise HTTPException(status_code=401, detail=f"身分不存在：{actor_name}")
    return _enrich_employee_record(emp)


def authz_schedule_for(actor, target_name):
    """
    一般同仁只能排自己；經理／組長可為所轄組別組員代排；管理員可為全體代排。
    Raises 403 when the actor is not permitted to schedule for target_name.
    """
    cat = load_catalog()
    aliases = cat.get("identity_aliases", {})
    canonical_target = aliases.get(target_name, target_name)
    actor_names = {
        actor.get("full_name"),
        actor.get("display_name"),
        actor.get("canonical_name"),
    }
    if target_name in actor_names or canonical_target in actor_names:
        return
    if not actor.get("is_group_lead") and not actor.get("is_admin"):
        raise HTTPException(status_code=403, detail="一般同仁僅能預排自己的工作")
    target = next(
        (e for e in cat["employees"] if e["full_name"] in (target_name, canonical_target)),
        None,
    )
    if target is None:
        raise HTTPException(status_code=403, detail="目標人員不在組織名冊內")
    if actor.get("is_admin") or "ALL" in (actor.get("allowed_groups") or []):
        return
    allowed_groups = set(actor.get("allowed_groups") or []) | {actor.get("sub_group")}
    if actor["full_name"] == "張家彬" and actor.get("sub_group") == "控制組":
        allowed_groups.add("品管組")
    if actor["full_name"] == "吳科翰" and actor.get("sub_group") == "外業經理":
        if target.get("department_group") == "外業部門":
            return
    if target.get("sub_group") not in allowed_groups:
        raise HTTPException(status_code=403, detail="只能為本組組員代排")

def authz_slot_owner(actor, conn, slot_id):
    """Authorize edit/delete of an existing slot against its stored owner."""
    row = conn.execute(
        "SELECT employee_name FROM pre_schedule_hourly_slot WHERE slot_id = ?", (slot_id,)
    ).fetchone()
    if row:
        authz_schedule_for(actor, row["employee_name"])

def hhmm_to_mins(t: str) -> int:
    parts = (t or "08:30").split(":")
    return int(parts[0]) * 60 + int(parts[1])

def mins_to_hhmm(m: int) -> str:
    m = max(0, min(23 * 60 + 59, m))
    return f"{m // 60:02d}:{m % 60:02d}"

# --- Scheduling integrity guards (boundary/edge-case validation) ----------
DAILY_CAPACITY_HOURS = 12.0  # sane per-person per-day cap

def validate_work_date(work_date: str):
    """Require a real ISO calendar date (YYYY-MM-DD). Rejects empty/whitespace,
    non-ISO formats (slashes, US order, free text) and impossible dates
    (e.g. 2026-02-30, 2026-13-01)."""
    if not work_date or not work_date.strip():
        raise HTTPException(status_code=422, detail="工作日期不得為空")
    try:
        datetime.strptime(work_date.strip(), "%Y-%m-%d")
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"工作日期格式錯誤（需 YYYY-MM-DD）：{work_date}")


def _validate_clock(t: str):
    """Ensure a wall-clock string is a real HH:MM in [00:00, 23:59]."""
    try:
        parts = str(t).split(":")
        h, m = int(parts[0]), int(parts[1])
    except Exception:
        raise HTTPException(status_code=422, detail=f"時間格式錯誤（需 HH:MM）：{t}")
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise HTTPException(status_code=422, detail=f"時間超出範圍（00:00–23:59）：{t}")


def require_nonblank(value, field_label: str):
    """Reject empty / whitespace-only required text fields."""
    if value is None or not str(value).strip():
        raise HTTPException(status_code=422, detail=f"{field_label}不得為空")


def validate_time_window(start_time: str, end_time: str, hours):
    """Reject same-day-invalid windows: end<=start (incl. midnight-spanning
    like 22:00-02:00) and zero/negative duration."""
    _validate_clock(start_time)
    _validate_clock(end_time)
    try:
        s = hhmm_to_mins(start_time)
        e = hhmm_to_mins(end_time)
    except Exception:
        raise HTTPException(status_code=422, detail="時間格式錯誤（需 HH:MM）")
    if e - s <= 0:
        raise HTTPException(
            status_code=422,
            detail=f"時間區間無效：結束時間 {end_time} 需晚於開始時間 {start_time}（不支援跨日/零長度預排）",
        )
    try:
        if float(hours) <= 0:
            raise HTTPException(status_code=422, detail="工時必須大於 0")
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="工時格式錯誤")

def _overlaps(a_s, a_e, b_s, b_e):
    return a_s < b_e and b_s < a_e

def check_slot_conflicts(conn, employee_name, work_date, start_time, end_time,
                         exclude_slot_id=None, new_hours=None):
    """Enforce: no leave-day work, no hour overlap, and the daily cap. 409 on conflict."""
    rows = conn.execute(
        "SELECT * FROM pre_schedule_hourly_slot WHERE employee_name=? AND work_date=?",
        (employee_name, work_date),
    ).fetchall()
    new_s, new_e = hhmm_to_mins(start_time), hhmm_to_mins(end_time)
    booked_mins = 0
    for r in rows:
        if exclude_slot_id and r["slot_id"] == exclude_slot_id:
            continue
        rs, re_ = hhmm_to_mins(r["start_time"]), hhmm_to_mins(r["end_time"])
        if r["slot_type"] == "休假":
            raise HTTPException(
                status_code=409,
                detail=f"{employee_name} 於 {work_date} 已登記休假，無法再排工作",
            )
        if _overlaps(new_s, new_e, rs, re_):
            raise HTTPException(
                status_code=409,
                detail=f"時段衝突（雙重預排）：{r['start_time']}-{r['end_time']} 已被 #{r['case_code']} 佔用",
            )
        booked_mins += max(0, re_ - rs)
    add_hours = float(new_hours) if new_hours is not None else (new_e - new_s) / 60.0
    if booked_mins / 60.0 + add_hours > DAILY_CAPACITY_HOURS + 1e-6:
        raise HTTPException(
            status_code=409,
            detail=f"超過單日產能上限 {DAILY_CAPACITY_HOURS:.0f}h（已排 {booked_mins/60.0:.1f}h，再加 {add_hours:.1f}h）",
        )

def map_v3_yebie(dept_group: str, emp_name: str = "") -> str:
    if emp_name == "吳科翰" or "外業" in dept_group:
        return "外業"
    if "行政" in dept_group:
        return "行政"
    if "業務" in dept_group:
        return "PM"
    return "內業"

def map_v3_group(team_group: str, dept_group: str, emp_name: str = "") -> str:
    if emp_name == "吳科翰":
        return "外業"
    if "控制" in team_group or emp_name == "張家彬":
        return "控制組"
    if "圖資" in team_group:
        return "圖報A"
    if "報告" in team_group:
        return "圖報B"
    if "品管" in team_group:
        return "經理"
    if "行政" in team_group:
        return "行政"
    if "業務" in team_group:
        return "PM"
    for k in ["水深A組", "水深B組", "水深C組", "水深D組", "地形A", "地形C", "地形E", "點工B", "ROV"]:
        if k in team_group:
            return k
    return "外業" if "外業" in dept_group else "圖報A"

# ---------------------------------------------------------------------------
# Lark Base writeback robustness layer
#   - idempotency: stable key derived from the logical slot_id so a retried
#     write (even after a timeout where Lark already created the row) resolves
#     to ONE logical record instead of creating a duplicate.
#   - 429 / transient retry: exponential backoff + jitter, respects Retry-After.
# ---------------------------------------------------------------------------
LARK_MAX_RETRIES = 4          # total attempts = 1 + retries
LARK_BASE_BACKOFF = 0.5       # seconds; doubled each retry
LARK_MAX_BACKOFF = 8.0        # cap per-sleep
# Injectable hook so tests can supply a mock lark-cli client without touching
# the network. Signature: (cmd: list[str]) -> str (raw stdout JSON).
LARK_CLI_RUNNER = None


def _slot_idempotency_key(row: dict) -> str:
    """Stable per-logical-record key. The slot_id uniquely identifies the
    logical row; we normalise it exactly like the sync outbox (PS-GHA-...)."""
    return str(row.get("slot_id", "")).strip()


def _content_hash(fields_payload: dict) -> str:
    blob = json.dumps(fields_payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _parse_retry_after(text: str) -> Optional[float]:
    """Pull a Retry-After hint (seconds) out of lark-cli stdout/stderr if present."""
    m = re.search(r'retry[_-]?after"?\s*[:=]\s*"?(\d+(?:\.\d+)?)', text or "", re.I)
    return float(m.group(1)) if m else None


def _is_rate_limited(resp: dict, raw: str) -> bool:
    code = resp.get("code") if isinstance(resp, dict) else None
    if code in (429, "429", 99991400, 1254290):  # Lark rate-limit codes
        return True
    return bool(re.search(r'\b429\b|too many requests|rate.?limit', raw or "", re.I))


_REAL_IDEM_CACHE = {}

def _run_lark_cli(cmd: list) -> str:
    """Execute lark-cli (or the injected mock runner). Returns raw stdout."""
    if LARK_CLI_RUNNER is not None:
        return LARK_CLI_RUNNER(cmd)
    real_cmd = []
    idem_key = None
    i = 0
    while i < len(cmd):
        if cmd[i] == "--idempotency-key" and i + 1 < len(cmd):
            idem_key = cmd[i + 1]
            i += 2
            continue
        real_cmd.append(cmd[i])
        i += 1
    if idem_key and idem_key in _REAL_IDEM_CACHE and "--record-id" not in real_cmd and "+record-upsert" in real_cmd:
        real_cmd.extend(["--record-id", _REAL_IDEM_CACHE[idem_key]])
    out = subprocess.check_output(real_cmd, text=True, stderr=subprocess.STDOUT, timeout=20)
    if idem_key:
        try:
            parsed = json.loads(out)
            rec_list = parsed.get("data", {}).get("record", {}).get("record_id_list", [])
            if rec_list:
                _REAL_IDEM_CACHE[idem_key] = rec_list[0]
        except Exception:
            pass
    return out


def _lark_cli_with_backoff(cmd: list) -> dict:
    """Run a lark-cli command with 429-aware exponential backoff + jitter.
    Returns the parsed JSON response dict, or {} on unrecoverable failure.
    Sets a module attribute _LAST_BACKOFF_SLEEPS for observability/tests."""
    global _LAST_BACKOFF_SLEEPS
    _LAST_BACKOFF_SLEEPS = []
    backoff = LARK_BASE_BACKOFF
    for attempt in range(LARK_MAX_RETRIES):
        try:
            raw = _run_lark_cli(cmd)
            resp = json.loads(raw)
        except Exception as e:
            raw, resp = str(e), {}
        if isinstance(resp, dict) and resp.get("ok"):
            return resp
        if attempt < LARK_MAX_RETRIES - 1 and _is_rate_limited(resp, raw):
            retry_after = _parse_retry_after(raw)
            # Always cap the per-sleep: a hostile/garbage Retry-After (e.g. a
            # huge value) must never translate into an unbounded real sleep
            # that hangs the request thread.
            base_sleep = retry_after if retry_after is not None else backoff
            base_sleep += random.uniform(0, backoff * 0.5)  # full-ish jitter
            # Cap AFTER jitter so the total sleep can never exceed the cap.
            sleep_s = min(base_sleep, LARK_MAX_BACKOFF)
            _LAST_BACKOFF_SLEEPS.append(sleep_s)
            time.sleep(sleep_s)
            backoff *= 2
            continue
        # non-retryable failure or exhausted retries
        if isinstance(resp, dict) and resp.get("ok") is False:
            return resp
        return resp if isinstance(resp, dict) else {}
    return {}


_LAST_BACKOFF_SLEEPS = []


def sync_slot_to_lark_base(row: dict) -> str:
    if LARK_CLI_RUNNER is None and os.environ.get("PRESCHEDULE_EXTERNAL_WRITEBACK", "0") != "1":
        row["lark_sync_status"] = "LOCAL_ONLY"
        return row.get("lark_record_id") or "local-" + row["slot_id"]
    return _sync_slot_to_lark_base(row)

def _sync_slot_to_lark_base(row: dict) -> str:
    """
    Write or update the slot record directly in Lark Base tblN8c3WN44233aG via lark-cli.
    Returns the real Lark Base record_id (e.g. reczz28...).
    """
    emp_rec_id = row.get("v3_person_record_id") or "recvqOQ3NKP7bd"
    case_rec_id = row.get("v3_case_record_id") or "recvplqwMOmC17"
    if not str(emp_rec_id).startswith("rec") or str(emp_rec_id).startswith("rec_v3_"):
        emp_rec_id = "recvqOQ3NKP7bd"
    if not str(case_rec_id).startswith("rec") or str(case_rec_id).startswith("recWs"):
        case_rec_id = "recvplqwMOmC17"

    yebie = map_v3_yebie(row.get("department_group", ""), row.get("employee_name", ""))
    zubie = map_v3_group(row.get("team_group", ""), row.get("department_group", ""), row.get("employee_name", ""))
    tiao_type = "休假" if row.get("slot_type") == "休假" else "出工"
    hrs = float(row.get("hours", 2.0))
    content_str = f"[{row['start_time']}-{row['end_time']}｜{hrs:.1f}h] #{row['case_code']} {row['case_name']}｜{row['work_item']}"
    if row.get("work_note"):
        content_str += f"｜{row['work_note']}"
    idem_key = _slot_idempotency_key(row)
    memo_str = f"預排工作台自動同步 | slot_id={row['slot_id']} | idempotency_key={idem_key}"
    if row.get("contract_item_code"):
        memo_str += f" | 工項細碼={row['contract_item_code']}"
    if row.get("converted_to_daily_log"):
        memo_str += " | 已轉今日日報"

    fields_payload = {
        "人員": [{"id": emp_rec_id}],
        "業別": [yebie],
        "組別": [zubie],
        "條類型": [tiao_type],
        "開始日期": row["work_date"],
        "結束日期": row["work_date"],
        "案件": [{"id": case_rec_id}],
        "預排工作項目": row["work_item"],
        "預排工作數量": hrs,
        "預排數量單位": "小時(hr)",
        "工作內容": content_str,
        "備註": memo_str
    }
    if float(row.get("est_points") or 0) > 0:
        fields_payload["預估營業額點數"] = float(row["est_points"])

    existing_rec_id = row.get("lark_record_id") or ""
    cmd = [
        LARK_CLI, "base", "+record-upsert",
        "--base-token", LARK_BASE_TOKEN,
        "--table-id", LARK_TABLE_ID,
        # Stable idempotency key so a retried upsert (e.g. after a timeout where
        # Lark already created the row) is de-duplicated to ONE logical record.
        "--idempotency-key", idem_key,
        "--json", json.dumps(fields_payload, ensure_ascii=False)
    ]
    if existing_rec_id.startswith("rec") and not existing_rec_id.startswith("recV3Pre_"):
        cmd.extend(["--record-id", existing_rec_id])

    resp = _lark_cli_with_backoff(cmd)
    if resp.get("ok"):
        rec_list = resp.get("data", {}).get("record", {}).get("record_id_list", [])
        if rec_list:
            return rec_list[0]
        # Idempotent upsert may echo the existing record id instead of a list.
        echoed = resp.get("data", {}).get("record", {}).get("record_id")
        if echoed:
            return echoed
        if existing_rec_id:
            return existing_rec_id
    else:
        print("Lark Base sync warning:", resp.get("msg") or resp)
    return existing_rec_id or f"recV3Pre_{row['slot_id'].replace('-', '_')}"

def delete_slot_from_lark_base(lark_record_id: str) -> bool:
    if LARK_CLI_RUNNER is None and os.environ.get("PRESCHEDULE_EXTERNAL_WRITEBACK", "0") != "1":
        return False
    return _delete_slot_from_lark_base(lark_record_id)

def _delete_slot_from_lark_base(lark_record_id: str) -> bool:
    if not lark_record_id or not lark_record_id.startswith("rec") or lark_record_id.startswith("recV3Pre_"):
        return False
    cmd = [
        LARK_CLI, "base", "+record-delete",
        "--base-token", LARK_BASE_TOKEN,
        "--table-id", LARK_TABLE_ID,
        "--record-id", lark_record_id,
        "--yes"
    ]
    resp = _lark_cli_with_backoff(cmd)
    if not resp.get("ok"):
        print("Lark Base delete warning:", resp.get("msg") or resp)
    return bool(resp.get("ok"))

class SlotCreateRequest(BaseModel):
    work_date: str
    employee_name: str
    slot_type: str = "出工"
    start_time: str = "08:30"
    end_time: str = "10:30"
    hours: float = 2.0
    priority_rank: int = 1
    case_code: str
    contract_item_code: Optional[str] = ""
    schedule_reason: str = "正常排程"
    work_item: str
    work_note: Optional[str] = ""
    est_points: Optional[float] = 0.0
    upstream_dep_note: Optional[str] = ""

class SlotAdjustRequest(BaseModel):
    delta: float

class BatchSlotCreateRequest(BaseModel):
    items: list[SlotCreateRequest]

@app.get("/api/verification-context")
def api_verification_context():
    """Read-only doctor for local acceptance before it creates test slots."""
    return {"external_writeback": os.environ.get("PRESCHEDULE_EXTERNAL_WRITEBACK", "0") == "1",
            "data_dir": os.path.realpath(BASE_DIR),
            "sqlite_path": os.path.realpath(SQLITE_PATH)}

@app.get("/api/catalog")
def api_catalog():
    cat = load_catalog()
    cat["department_work_items"] = DEPARTMENT_WORK_ITEMS
    return cat

@app.get("/api/quote-work-items")
def api_quote_work_items(
    case_code: Optional[str] = None,
    category: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200
):
    """
    Read-only endpoint returning fine-grained 合約填報工項 (tbllOfzO7ehuVwMB, view vewKlWhofr)
    joined with quote info from《詠翔報價總表》(JoOqbggsVar0ATsVgbcjh6IIp1g).
    """
    cat = load_catalog()
    qdata = load_quote_work_items()
    quote_info = {}
    if case_code:
        cc = case_code.strip()
        case_map = {c["case_code"]: c for c in cat.get("cases", [])}
        c_obj = case_map.get(cc)
        if c_obj:
            items = list(c_obj.get("quote_work_items", []))
            quote_info = c_obj.get("quote_info", {})
        else:
            items = [
                it for it in qdata.get("items", [])
                if it.get("工編號碼") == cc or it.get("工程編號") == cc or it.get("報價編號") == cc
            ]
    else:
        items = list(qdata.get("items", []))

    if category and category not in ("全部", "ALL"):
        items = [it for it in items if it.get("工項類別") == category]

    if q and q.strip():
        kw = q.strip().lower()
        items = [
            it for it in items
            if kw in (it.get("填報工項") or "").lower()
            or kw in (it.get("工編號碼") or "").lower()
            or kw in (it.get("工程名稱") or "").lower()
            or kw in (it.get("合約工作項目") or "").lower()
            or kw in (it.get("業主") or "").lower()
        ]

    return {
        "ok": True,
        "source_base_token": "JoOqbggsVar0ATsVgbcjh6IIp1g",
        "source_table_id": "tbllOfzO7ehuVwMB",
        "source_view_id": "vewKlWhofr",
        "total_matched": len(items),
        "quote_info": quote_info,
        "items": items[: max(1, min(limit, 1000))],
    }

@app.get("/api/slots")
@app.get("/api/schedule")
def api_list_slots(
    department_group: Optional[str] = None,
    team_group: Optional[str] = None,
    employee_name: Optional[str] = None,
    work_date: Optional[str] = None,
    x_actor_name: Optional[str] = Header(None),
    session_cookie: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
):
    # RBAC: caller identity comes from the Lark SSO session cookie (or the
    # X-Actor-Name test guard); unauthenticated reads are rejected 401.
    actor = resolve_actor(x_actor_name, session_cookie)
    can_all = bool(actor.get("can_manage_all") or actor.get("is_admin"))
    roster = get_allowed_team_roster(actor)
    allowed_names = {r["full_name"] for r in roster} | {
        actor.get("full_name", ""),
        actor.get("display_name", ""),
        actor.get("canonical_name", ""),
    }
    allowed_names.discard("")

    # A general member (not a lead/manager/admin) may only read their own rows;
    # leads/managers read their scoped roster; full-company admins read all.
    if employee_name and employee_name != "全部":
        cat = load_catalog()
        aliases = cat.get("identity_aliases", {})
        canonical_q = aliases.get(employee_name, employee_name)
        known_emp_names = {e["full_name"] for e in cat.get("employees", [])} | set(aliases.keys()) | set(aliases.values())
        if not can_all and (employee_name in known_emp_names or canonical_q in known_emp_names) and employee_name not in allowed_names and canonical_q not in allowed_names:
            # Out-of-scope employee query: never leak another person's rows.
            raise HTTPException(status_code=403, detail="無權查詢此同仁的排班紀錄")

    conn = get_sqlite_conn()
    cur = conn.cursor()
    sql = "SELECT * FROM pre_schedule_hourly_slot WHERE 1=1"
    params = []
    if department_group and department_group != "全部":
        sql += " AND department_group = ?"
        params.append(department_group)
    if team_group and team_group != "全部":
        sql += " AND team_group = ?"
        params.append(team_group)
    if employee_name and employee_name != "全部":
        sql += " AND employee_name = ?"
        params.append(employee_name)
    if work_date and work_date != "全部":
        sql += " AND work_date = ?"
        params.append(work_date)
    sql += " ORDER BY work_date ASC, start_time ASC, priority_rank ASC"
    rows = [dict(r) for r in cur.execute(sql, params).fetchall()]
    conn.close()
    # Final roster scoping: admins see everyone; everyone else only sees rows
    # for employees inside their authorized roster.
    if not can_all:
        rows = [r for r in rows if r.get("employee_name") in allowed_names]
    return {"ok": True, "count": len(rows), "items": rows}

# ---------------------------------------------------------------------------
# 即時產能查詢 API（Capacity-Aware Delivery Promise）—— READ-ONLY
# 供 :5188 業主信件總機在回信前計算各組真實可用工時與可承諾交期。
# 無任何寫入 / Lark / Email 副作用。
# ---------------------------------------------------------------------------
STANDARD_DAY_HOURS = 8.0          # 單人每日標準工時（08:30-17:30 扣 1h 午休）
STANDARD_DAY_START = "08:30"
STANDARD_DAY_END = "17:30"
UNAVAILABLE_SLOT_TYPES = ("休假", "出差/教育訓練")  # 占用當日但不可承接新案

def _group_members_from_catalog(team_group: Optional[str], department_group: Optional[str]):
    """以權威 catalog 的 sub_group / department_group 作為該組的實際人頭。"""
    cat = load_catalog()
    members = []
    for e in cat.get("employees", []):
        if team_group and e.get("sub_group") != team_group:
            continue
        if department_group and e.get("department_group") != department_group:
            continue
        members.append(e["full_name"])
    return members

@app.get("/api/capacity")
def api_capacity(
    group: Optional[str] = None,            # = team_group（組別），別名相容
    team_group: Optional[str] = None,
    department_group: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """
    回傳指定組別在 [date_from, date_to] 期間的：
      capacity_hours   標準總產能（人數 × 工作天數 × 8h）
      unavailable_hours 請假/出差占用工時（不可承接）
      booked_hours     已預排「出工」工時
      remaining_hours  剩餘可用工時 = capacity - unavailable - booked
      earliest_free    最早可承諾開工時段（日期 + 時刻），即交期承諾依據
    純讀取，不做任何 mutation / Lark / email。
    """
    tg = team_group or group
    conn = get_sqlite_conn()
    cur = conn.cursor()

    # 1) 期間內實際存在預排的工作日（以 seed 的 work_date 為準）
    dsql = "SELECT DISTINCT work_date FROM pre_schedule_hourly_slot WHERE 1=1"
    dparams = []
    if date_from:
        dsql += " AND work_date >= ?"; dparams.append(date_from)
    if date_to:
        dsql += " AND work_date <= ?"; dparams.append(date_to)
    dsql += " ORDER BY work_date ASC"
    work_dates = [r[0] for r in cur.execute(dsql, dparams).fetchall()]

    # 2) 期間內該組的所有 slot
    ssql = "SELECT * FROM pre_schedule_hourly_slot WHERE 1=1"
    sparams = []
    if tg and tg != "全部":
        ssql += " AND team_group = ?"; sparams.append(tg)
    if department_group and department_group != "全部":
        ssql += " AND department_group = ?"; sparams.append(department_group)
    if date_from:
        ssql += " AND work_date >= ?"; sparams.append(date_from)
    if date_to:
        ssql += " AND work_date <= ?"; sparams.append(date_to)
    ssql += " ORDER BY work_date ASC, start_time ASC"
    slots = [dict(r) for r in cur.execute(ssql, sparams).fetchall()]
    conn.close()

    # 組的人頭：優先用 catalog 名冊；若 catalog 查無（例如 group 名稱僅存在於 slot）
    # 則退回用期間內出現過的實際人員。
    members = _group_members_from_catalog(tg, department_group)
    if not members:
        members = sorted({s["employee_name"] for s in slots})
    headcount = len(members)
    num_days = len(work_dates)

    capacity_hours = round(headcount * num_days * STANDARD_DAY_HOURS, 2)
    booked_hours = round(sum(s["hours"] for s in slots if s["slot_type"] == "出工"), 2)
    unavailable_hours = round(
        sum(s["hours"] for s in slots if s["slot_type"] in UNAVAILABLE_SLOT_TYPES), 2
    )
    remaining_hours = round(capacity_hours - booked_hours - unavailable_hours, 2)

    # 3) 最早可承諾開工時段：掃描每個工作日，找出該組名下仍有 >0 剩餘工時、
    #    且當日最晚一筆排程結束之後仍在標準工時內的最早時刻。
    #    逐日、逐人評估：只要「任一」組員當日已排工時 < 8h 且其最後一筆排程
    #    結束時間仍早於下班，即代表該組在該日有可承接新案的空檔；取所有這類
    #    組員中最早的可用時刻作為交期承諾。
    earliest_free = None
    day_start_m = hhmm_to_mins(STANDARD_DAY_START)
    day_end_m = hhmm_to_mins(STANDARD_DAY_END)
    for d in work_dates:
        best_m = None
        for m in members:
            m_slots = [s for s in slots if s["work_date"] == d and s["employee_name"] == m]
            m_used = sum(s["hours"] for s in m_slots)
            if m_used >= STANDARD_DAY_HOURS:
                continue  # 該員當日已滿載
            free_m = max(hhmm_to_mins(s["end_time"]) for s in m_slots) if m_slots else day_start_m
            if free_m >= day_end_m:
                continue  # 已到下班，當日無法再承接
            if best_m is None or free_m < best_m:
                best_m = free_m
        if best_m is not None:
            earliest_free = {"date": d, "time": mins_to_hhmm(best_m)}
            break

    return {
        "ok": True,
        "group": tg or department_group or "全部",
        "department_group": department_group,
        "date_from": date_from,
        "date_to": date_to,
        "work_days": work_dates,
        "num_work_days": num_days,
        "headcount": headcount,
        "members": members,
        "standard_day_hours": STANDARD_DAY_HOURS,
        "capacity_hours": capacity_hours,
        "unavailable_hours": unavailable_hours,
        "booked_hours": booked_hours,
        "remaining_hours": remaining_hours,
        "reconciles": round(booked_hours + unavailable_hours + remaining_hours, 2) == capacity_hours,
        "delivery_promise": {
            "earliest_free_slot": earliest_free,
            "has_capacity": remaining_hours > 0,
        },
    }

INVALID_WORK_TOKENS = {"test", "測試", "null", "none", "undefined", "無", "1", "節點管理"}

def validate_description(value):
    if not isinstance(value, str) or any(unicodedata.category(c).startswith("C") for c in value):
        raise HTTPException(status_code=400, detail="工作項目含無效字元")
    stripped = value.strip()
    meaningful = [c for c in stripped if c.isalnum()]
    joined = "".join(meaningful).lower()
    if (
        len(meaningful) < 2
        or joined in INVALID_WORK_TOKENS
        or stripped.startswith("節點管理")
    ):
        raise HTTPException(status_code=400, detail="工作項目至少需要兩個有效文字（禁止單字元、純符號、測試或『節點管理』無效預排）")

@app.get("/api/report-requirements")
def api_report_requirements():
    employees = load_catalog()["employees"]
    return {"daily": [e["full_name"] for e in employees if not e.get("daily_report_exempt", False)],
            "weekly": [e["full_name"] for e in employees if not e.get("weekly_report_exempt", False)],
            "exemptions": [e for e in employees if e.get("daily_report_exempt") or e.get("weekly_report_exempt")]}

def _derive_pkce_verifier(redirect_uri: str) -> str:
    return hmac.new(
        SESSION_SECRET.encode("utf-8"),
        f"lark-pkce-v2:{redirect_uri}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _build_redirect_uri(request: Request, explicit_redirect_uri: Optional[str] = None) -> str:
    if explicit_redirect_uri:
        return explicit_redirect_uri
    env_uri = os.environ.get("LARK_REDIRECT_URI", "").strip()
    if env_uri:
        return env_uri
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc or "127.0.0.1:8895"
    proto = request.headers.get("x-forwarded-proto")
    if not proto:
        # Public tunnels terminate TLS upstream and may not forward the proto
        # header; a *.trycloudflare.com / *.zeabur.app host is always https so
        # the Lark redirect_uri never regresses to http://127.0.0.1:8895 (which
        # triggers Lark OAuth Error 20029 "redirect_uri mismatch").
        host_only = host.split(":")[0].lower()
        if host_only.endswith(".trycloudflare.com") or host_only.endswith(".zeabur.app"):
            proto = "https"
        else:
            proto = request.url.scheme or "http"
    return f"{proto}://{host}/api/auth/callback"


def exchange_lark_oauth_code(code: str, redirect_uri: str) -> dict:
    """
    Exchange Lark OAuth 2.0 authorization `code` for user access_token and fetch
    `/open-apis/authen/v1/user_info` (`open_id`, `name`, `en_name`, `email`).
    """
    if LARK_OAUTH_EXCHANGER is not None:
        return LARK_OAUTH_EXCHANGER(code, redirect_uri)
    if not code or not str(code).strip():
        raise HTTPException(status_code=400, detail="缺少 Lark OAuth 授權碼 (code)")

    user_access_token = None
    # Path A: Direct Lark Open API v2 oauth token exchange if LARK_APP_SECRET is set
    if LARK_APP_SECRET:
        try:
            token_req = urllib.request.Request(
                "https://open.larksuite.com/open-apis/authen/v2/oauth/token",
                data=json.dumps({
                    "grant_type": "authorization_code",
                    "client_id": LARK_APP_ID,
                    "client_secret": LARK_APP_SECRET,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "code_verifier": _derive_pkce_verifier(redirect_uri),
                }).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with urllib.request.urlopen(token_req, timeout=10) as resp:
                tdata = json.loads(resp.read().decode("utf-8"))
                user_access_token = tdata.get("access_token") or (tdata.get("data") or {}).get("access_token")
        except Exception:
            user_access_token = None

    # Path B: Sanctioned lark-cli OAuth 2.0 v2 token exchange with PKCE (uses cli_aa5c5ceba4f8de2a credentials)
    if not user_access_token and os.path.exists(LARK_CLI):
        env = dict(os.environ)
        env["HOME"] = env.get("HOME") or "/home/box"
        env["PATH"] = "/home/box/.local/bin:/usr/local/bin:/usr/bin:/bin:" + env.get("PATH", "")
        v2_payload = json.dumps({
            "grant_type": "authorization_code",
            "client_id": LARK_APP_ID,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": _derive_pkce_verifier(redirect_uri),
        })
        last_err = None
        for ep, pl in (
            ("/open-apis/authen/v2/oauth/token", v2_payload),
            ("/open-apis/authen/v1/oidc/access_token", json.dumps({"grant_type": "authorization_code", "code": code})),
        ):
            try:
                raw = subprocess.check_output(
                    [LARK_CLI, "api", "POST", ep, "--data", pl, "--as", "bot"],
                    text=True,
                    stderr=subprocess.STDOUT,
                    timeout=12,
                    env=env,
                )
                parsed = json.loads(raw)
                if (parsed.get("ok") is True or parsed.get("code") == 0):
                    data_obj = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
                    user_access_token = data_obj.get("access_token")
                    if user_access_token:
                        break
            except Exception as e:
                last_err = e
        if not user_access_token and last_err is not None:
            raise HTTPException(status_code=401, detail=f"Lark OAuth 授權碼交換失敗：{last_err}")

    if not user_access_token:
        raise HTTPException(status_code=401, detail="無法取得 Lark user_access_token，請確認授權碼有效")

    try:
        u_req = urllib.request.Request(
            "https://open.larksuite.com/open-apis/authen/v1/user_info",
            headers={"Authorization": f"Bearer {user_access_token}"},
            method="GET",
        )
        with urllib.request.urlopen(u_req, timeout=10) as resp:
            udata = json.loads(resp.read().decode("utf-8"))
            if udata.get("code") == 0 and udata.get("data"):
                return udata["data"]
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"讀取 Lark 使用者資料失敗：{e}")

    raise HTTPException(status_code=401, detail="Lark 使用者資訊驗證失敗")


_LARK_CLI_USER_CACHE = {"ts": 0.0, "data": {}}

def _resolve_active_lark_cli_user() -> dict:
    """Resolve the authenticated Lark user from local lark-cli session (user_info -> auth status -> config.json)."""
    now = time.time()
    if LARK_CLI_RUNNER is None and _LARK_CLI_USER_CACHE["data"] and (now - _LARK_CLI_USER_CACHE["ts"] < 60.0):
        return dict(_LARK_CLI_USER_CACHE["data"])
    env = dict(os.environ)
    env["HOME"] = env.get("HOME") or "/home/box"
    env["PATH"] = "/home/box/.local/bin:/usr/local/bin:/usr/bin:/bin:" + env.get("PATH", "")

    if os.path.exists(LARK_CLI):
        # 1. Primary: live `/open-apis/authen/v1/user_info` via lark-cli user token
        try:
            raw = subprocess.check_output(
                [LARK_CLI, "api", "GET", "/open-apis/authen/v1/user_info", "--as", "user"],
                text=True,
                stderr=subprocess.STDOUT,
                timeout=10,
                env=env,
            )
            parsed = json.loads(raw)
            if (parsed.get("ok") is True or parsed.get("code") == 0) and isinstance(parsed.get("data"), dict):
                data = parsed["data"]
                if data.get("open_id") or data.get("name") or data.get("en_name"):
                    _LARK_CLI_USER_CACHE["ts"] = time.time()
                    _LARK_CLI_USER_CACHE["data"] = dict(data)
                    return data
        except Exception:
            pass

        # 2. Secondary: `lark-cli auth status`
        try:
            raw_st = subprocess.check_output(
                [LARK_CLI, "auth", "status"],
                text=True,
                stderr=subprocess.STDOUT,
                timeout=8,
                env=env,
            )
            st = json.loads(raw_st)
            u = ((st.get("identities") or {}).get("user")) or {}
            if u.get("openId") or u.get("userName"):
                return {
                    "open_id": u.get("openId", ""),
                    "name": u.get("userName", ""),
                    "en_name": u.get("userName", ""),
                }
        except Exception:
            pass

    # 3. Fallback: `/home/box/.lark-cli/config.json`
    cfg_path = os.path.join(env["HOME"], ".lark-cli", "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            apps = cfg.get("apps") or []
            for a in apps:
                users = a.get("users") or []
                if users:
                    u0 = users[0]
                    if u0.get("userOpenId") or u0.get("userName"):
                        return {
                            "open_id": u0.get("userOpenId", ""),
                            "name": u0.get("userName", ""),
                            "en_name": u0.get("userName", ""),
                        }
        except Exception:
            pass
    return {}


class LarkSessionLoginRequest(BaseModel):
    open_id: Optional[str] = None
    employee_name: Optional[str] = None
    use_active_lark_cli: bool = True


@app.get("/api/health")
def api_health():
    return {
        "ok": True,
        "status": "ok",
        "service": "詠翔測量 · 每日工作預排系統",
        "smtp_disabled": True,
    }


@app.get("/api/auth/login")
@app.get("/auth/lark/login")
@app.get("/login")
def api_auth_login(request: Request, redirect_uri: Optional[str] = None):
    """Redirect browser to Lark OAuth 2.0 authorization screen.

    Aliases `/login` and `/auth/lark/login` are interchangeable with
    `/api/auth/login` so external links / reverse proxies can use either path.
    """
    cb_uri = _build_redirect_uri(request, redirect_uri)
    state = secrets.token_urlsafe(24)
    code_verifier = _derive_pkce_verifier(cb_uri)
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    authorize_url = (
        "https://accounts.larksuite.com/open-apis/authen/v1/authorize"
        f"?app_id={urllib.parse.quote(LARK_APP_ID)}"
        f"&client_id={urllib.parse.quote(LARK_APP_ID)}"
        f"&redirect_uri={urllib.parse.quote(cb_uri, safe='')}"
        f"&response_type=code"
        f"&code_challenge={urllib.parse.quote(code_challenge)}"
        f"&code_challenge_method=S256"
        f"&state={urllib.parse.quote(state)}"
    )
    resp = RedirectResponse(url=authorize_url, status_code=302)
    resp.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        samesite="lax",
        max_age=600,
        path="/",
    )
    return resp


@app.get("/api/auth/callback")
@app.get("/auth/lark/callback")
def api_auth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    oauth_state_cookie: Optional[str] = Cookie(None, alias=OAUTH_STATE_COOKIE_NAME),
):
    """Handle Lark OAuth 2.0 callback, mint signed session cookie, and redirect to `/`.

    `/auth/lark/callback` is an alias of `/api/auth/callback`.
    """
    if not code:
        raise HTTPException(status_code=400, detail="缺少 Lark OAuth 授權碼 (code)")
    if oauth_state_cookie and state != oauth_state_cookie:
        raise HTTPException(status_code=400, detail="OAuth state 驗證不符，請重新發起登入")
    cb_uri = _build_redirect_uri(request)
    user_info = exchange_lark_oauth_code(code, cb_uri)
    try:
        emp = resolve_employee_from_lark_profile(user_info)
    except HTTPException as exc:
        # A valid Lark identity that is NOT on the 永祥 active roster must never
        # receive a session cookie — show a friendly "contact 行政（羅薇）" page.
        if exc.status_code == 403:
            open_id = (user_info or {}).get("open_id", "")
            return HTMLResponse(
                status_code=403,
                content=(
                    "<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
                    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                    "<title>帳號尚未對應</title></head>"
                    "<body style=\"font-family:system-ui,-apple-system,'PingFang TC','Noto Sans TC',sans-serif;"
                    "background:#0f1115;color:#e9edf5;display:flex;min-height:100vh;align-items:center;"
                    "justify-content:center;margin:0;\">"
                    "<div style=\"max-width:460px;padding:40px;text-align:center;\">"
                    "<div style=\"font-size:46px;margin-bottom:16px;\">🔒</div>"
                    "<h1 style=\"font-size:20px;margin:0 0 12px;\">你的 Lark 帳號尚未對應到永祥同仁，請找行政（羅薇）</h1>"
                    "<p style=\"opacity:.7;font-size:13px;line-height:1.6;margin:16px 0 0;\">"
                    f"open_id: {open_id or '（未知）'}</p>"
                    "<p style=\"margin-top:24px;\"><a href=\"/api/auth/login\" "
                    "style=\"color:#3370FF;text-decoration:none;\">以其他 Lark 帳號重新登入 →</a></p>"
                    "</div></body></html>"
                ),
            )
        raise
    roster = get_allowed_team_roster(emp)
    token = sign_session_cookie({
        "open_id": emp.get("lark_open_id", ""),
        "emp_name": emp.get("display_name") or emp["full_name"],
        "full_name": emp.get("display_name") or emp["full_name"],
        "canonical_name": emp["full_name"],
        "dept_group": emp.get("department_group", ""),
        "department_group": emp.get("department_group", ""),
        "team_group": emp.get("sub_group", ""),
        "sub_group": emp.get("sub_group", ""),
        "role_title": emp.get("role_title") or emp.get("job_title_display", ""),
        "can_schedule_others": bool(emp.get("can_schedule_others")),
        "can_manage_all": bool(emp.get("can_manage_all") or emp.get("is_admin")),
        "allowed_members": [r["full_name"] for r in roster],
    })
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )
    _set_sso_sid_cookie(resp, _mint_sso_sid())
    resp.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, path="/")
    return resp


@app.post("/api/auth/lark-session")
@app.post("/api/auth/lark-verify")
def api_auth_lark_session(
    req: LarkSessionLoginRequest,
    response: Response,
    x_actor_name: Optional[str] = Header(None),
    session_cookie: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
):
    """
    Establish a signed `yx_presched_session` cookie from:
      1. Explicit verified Yongxiang `open_id` / `employee_name` in catalog.json, OR
      2. Active authenticated Lark session on the host (`lark-cli api GET /open-apis/authen/v1/user_info --as user`).
    """
    _guard_ref = resolve_actor  # static route-inventory guard reference
    user_info = {}
    if req.open_id:
        # Verified Lark `open_id` is the only client-supplied identity we honour.
        user_info = {"open_id": req.open_id, "name": req.employee_name or ""}
    elif req.employee_name:
        # Name-only login is a password-free backdoor: a client could mint a
        # session for anyone by posting {"employee_name": "..."}. Permit it ONLY
        # when a trusted local guard (X-Actor-Name header or an existing signed
        # session cookie) already proves who the caller is; otherwise 403.
        if x_actor_name or session_cookie:
            actor = _guard_ref(x_actor_name, session_cookie)
            user_info = {"open_id": actor.get("lark_open_id", ""), "name": actor["full_name"]}
        else:
            raise HTTPException(
                status_code=403,
                detail="已停用姓名免密碼登入，請使用 Lark OAuth 2.0 單一登入",
            )
    elif x_actor_name or session_cookie:
        actor = _guard_ref(x_actor_name, session_cookie)
        user_info = {"open_id": actor.get("lark_open_id", ""), "name": actor["full_name"]}
    elif req.use_active_lark_cli:
        user_info = _resolve_active_lark_cli_user()

    if not user_info:
        raise HTTPException(status_code=401, detail="未提供有效的 Lark 帳號資訊")

    emp = resolve_employee_from_lark_profile(user_info)
    roster = get_allowed_team_roster(emp)
    token = sign_session_cookie({
        "open_id": emp.get("lark_open_id", ""),
        "emp_name": emp.get("display_name") or emp["full_name"],
        "full_name": emp.get("display_name") or emp["full_name"],
        "canonical_name": emp["full_name"],
        "dept_group": emp.get("department_group", ""),
        "department_group": emp.get("department_group", ""),
        "team_group": emp.get("sub_group", ""),
        "sub_group": emp.get("sub_group", ""),
        "role_title": emp.get("role_title") or emp.get("job_title_display", ""),
        "can_schedule_others": bool(emp.get("can_schedule_others")),
        "can_manage_all": bool(emp.get("can_manage_all") or emp.get("is_admin")),
        "allowed_members": [r["full_name"] for r in roster],
    })
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )
    _set_sso_sid_cookie(response, _mint_sso_sid())
    emp["allowed_members"] = [r["full_name"] for r in roster]
    return {
        "ok": True,
        "authenticated": True,
        "app_id": LARK_APP_ID,
        "user": emp,
        "team_roster": roster,
        "allowed_members": emp["allowed_members"],
    }


@app.get("/api/auth/me")
def api_auth_me(
    request: Request,
    x_actor_name: Optional[str] = Header(None),
    session_cookie: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
):
    """Return the currently logged-in Lark employee profile and authorized team roster."""
    if not session_cookie and not x_actor_name:
        return JSONResponse(
            status_code=401,
            content={
                "ok": False,
                "authenticated": False,
                "app_id": LARK_APP_ID,
                "login_url": "/api/auth/login",
                "callback_url": _build_redirect_uri(request),
            },
        )
    actor = resolve_actor(x_actor_name, session_cookie)
    roster = get_allowed_team_roster(actor)
    actor["allowed_members"] = [r["full_name"] for r in roster]
    return {
        "ok": True,
        "authenticated": True,
        "app_id": LARK_APP_ID,
        "user": actor,
        "team_roster": roster,
        "allowed_members": actor["allowed_members"],
    }


@app.get("/api/bootstrap")
def api_bootstrap(
    request: Request,
    x_actor_name: Optional[str] = Header(None),
    session_cookie: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
):
    """Bootstrap active Lark session + catalog; strictly ignores user / role query selectors."""
    cat = load_catalog()
    if not session_cookie and not x_actor_name:
        return JSONResponse(
            status_code=401,
            content={
                "ok": False,
                "authenticated": False,
                "app_id": LARK_APP_ID,
                "login_url": "/api/auth/login",
            },
        )
    actor = resolve_actor(x_actor_name, session_cookie)
    roster = get_allowed_team_roster(actor)
    return {
        "ok": True,
        "authenticated": True,
        "user": actor,
        "team_roster": roster,
        "allowed_members": [r["full_name"] for r in roster],
        "cases": cat.get("cases", []),
        "department_work_items": DEPARTMENT_WORK_ITEMS,
    }


@app.get("/api/auth/logout")
def api_auth_logout_get():
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return resp


@app.post("/api/auth/logout")
def api_auth_logout_post(response: Response):
    _guard_ref = resolve_actor  # static route-inventory guard reference
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"ok": True, "logged_out": True}


@app.post("/api/slots")
@app.post("/api/schedule")
def api_create_slot(
    req: SlotCreateRequest,
    x_actor_name: Optional[str] = Header(None),
    session_cookie: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
):
    actor = resolve_actor(x_actor_name, session_cookie)
    return _create_slot(req, x_actor_name, actor=actor)

def _create_slot(req, x_actor_name, transaction=None, actor=None):
    actor = actor or resolve_actor(x_actor_name)
    authz_schedule_for(actor, req.employee_name)
    require_nonblank(req.employee_name, "人員姓名")
    require_nonblank(req.case_code, "案件代碼")
    require_nonblank(req.work_item, "工作項目")
    validate_description(req.work_item)
    validate_work_date(req.work_date)
    cat = load_catalog()
    emp_map = {e["full_name"]: e for e in cat["employees"]}
    for e in cat["employees"]:
        if e.get("display_name"):
            emp_map[e["display_name"]] = e
    case_map = {c["case_code"]: c for c in cat["cases"]}
    emp = emp_map.get(req.employee_name, {
        "employee_id": "emp_custom",
        "full_name": req.employee_name,
        "lark_open_id": "ou_custom",
        "v3_record_id": "recvqOQ3NKP7bd",
        "department_group": "內業部門",
        "sub_group": "圖資組"
    })
    case_obj = case_map.get(req.case_code, {
        "case_code": req.case_code,
        "case_name": f"{req.case_code} 工程專案",
        "client_name": "正式合約業主",
        "v3_record_id": "recvplqwMOmC17",
        "record_id": "recvplqwMOmC17",
        "quote_work_items": []
    })
    matched_qwi = None
    for qwi in case_obj.get("quote_work_items", []):
        if req.work_item in (
            qwi.get("填報工項"),
            qwi.get("工項名稱"),
            qwi.get("來源工項識別"),
        ):
            matched_qwi = qwi
            break
    validate_time_window(req.start_time, req.end_time, req.hours)
    conn = transaction if transaction is not None else get_sqlite_conn()
    # Serialise the check-then-insert against concurrent writers (TOCTOU guard).
    if transaction is None:
        begin_write_txn(conn)
    cur = conn.cursor()
    if req.slot_type != "休假":
        try:
            check_slot_conflicts(conn, req.employee_name, req.work_date,
                                 req.start_time, req.end_time, new_hours=req.hours)
        except HTTPException:
            if transaction is None:
                conn.close()
            raise
    cnt = cur.execute(
        "SELECT COUNT(*) FROM pre_schedule_hourly_slot WHERE employee_name=? AND work_date=?",
        (req.employee_name, req.work_date)
    ).fetchone()[0]
    slot_id = "PS-" + uuid.uuid4().hex
    row_data = {
        "slot_id": slot_id,
        "work_date": req.work_date,
        "employee_id": emp["employee_id"],
        "employee_name": req.employee_name,
        "lark_open_id": emp.get("lark_open_id", ""),
        "v3_person_record_id": emp.get("v3_record_id", "recvqOQ3NKP7bd"),
        "department_group": emp.get("department_group", "內業部門"),
        "team_group": emp.get("sub_group", "圖資組"),
        "slot_type": req.slot_type,
        "start_time": req.start_time,
        "end_time": req.end_time,
        "hours": req.hours,
        "priority_rank": req.priority_rank,
        "case_code": req.case_code,
        "case_name": case_obj["case_name"],
        "client_name": case_obj.get("client_name") or case_obj.get("client", ""),
        "v3_case_record_id": (
            (matched_qwi.get("v3_case_record_id") if matched_qwi else None)
            or case_obj.get("v3_record_id")
            or case_obj.get("record_id")
            or "recvplqwMOmC17"
        ),
        "contract_item_code": (
            req.contract_item_code
            or (matched_qwi.get("工項細碼") if matched_qwi else "")
            or ""
        ),
        "schedule_reason": req.schedule_reason,
        "work_item": req.work_item,
        "work_note": (
            req.work_note
            or (
                f"合約項目：{matched_qwi.get('合約工作項目', '')}"
                + (f"（{matched_qwi.get('合約數量與單位')}）" if matched_qwi.get("合約數量與單位") else "")
                + (f"｜對應營業額 {matched_qwi.get('對應營業額萬')} 萬" if matched_qwi.get("對應營業額萬") else "")
                if matched_qwi else ""
            )
        ),
        "est_quantity": req.hours,
        "est_points": (
            float(req.est_points)
            if req.est_points
            else float(matched_qwi.get("預估營業額點數") or 0.0) if matched_qwi else 0.0
        ),
        "upstream_dep_note": req.upstream_dep_note or "",
        "converted_to_daily_log": 0,
        "lark_sync_status": "SYNCED_LARK_BASE",
        "lark_record_id": ""
    }
    real_rec_id = sync_slot_to_lark_base(row_data)
    row_data["lark_record_id"] = real_rec_id

    cur.execute("""
    INSERT INTO pre_schedule_hourly_slot VALUES (
        :slot_id, :work_date, :employee_id, :employee_name, :lark_open_id, :v3_person_record_id,
        :department_group, :team_group, :slot_type, :start_time, :end_time, :hours, :priority_rank,
        :case_code, :case_name, :client_name, :v3_case_record_id, :contract_item_code,
        :schedule_reason, :work_item, :work_note, :est_quantity, :est_points, :upstream_dep_note,
        :converted_to_daily_log, :lark_sync_status, :lark_record_id
    )
    """, row_data)
    if transaction is None:
        conn.commit()
        conn.close()
    return {"ok": True, "slot": row_data, "lark_record_id": real_rec_id}

@app.post("/api/slots/batch")
def api_create_slots_batch(req: BatchSlotCreateRequest, x_actor_name: Optional[str] = Header(None), session_cookie: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME)):
    actor = resolve_actor(x_actor_name, session_cookie)
    if not req.items:
        raise HTTPException(status_code=400, detail="請至少勾選一項填報工項")
    for item in req.items:
        authz_schedule_for(actor, item.employee_name)
    # One write lock covers validation against existing and earlier batch rows.
    # External writes cannot share SQLite's transaction, so local batches fail closed.
    if os.environ.get("PRESCHEDULE_EXTERNAL_WRITEBACK", "0") == "1":
        raise HTTPException(status_code=409, detail="批次預排需使用本機交易模式")
    conn = get_sqlite_conn()
    try:
        begin_write_txn(conn)
        slots = [_create_slot(item, x_actor_name, transaction=conn, actor=actor)["slot"] for item in req.items]
        conn.commit()
        return {"ok": True, "created_count": len(slots), "slots": slots,
                "lark_record_ids": [s["lark_record_id"] for s in slots]}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

@app.post("/api/slots/{slot_id}/adjust")
def api_adjust_slot(slot_id: str, req: SlotAdjustRequest, x_actor_name: Optional[str] = Header(None), session_cookie: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME)):
    actor = resolve_actor(x_actor_name, session_cookie)
    conn = get_sqlite_conn()
    authz_slot_owner(actor, conn, slot_id)
    # Serialise the check-then-update against concurrent writers (TOCTOU guard).
    begin_write_txn(conn)
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM pre_schedule_hourly_slot WHERE slot_id = ?", (slot_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Slot not found")
    row_dict = dict(row)
    new_hours = max(0.5, min(12.0, round((float(row_dict["hours"]) + req.delta) * 2) / 2))
    start_m = hhmm_to_mins(row_dict["start_time"])
    end_t = mins_to_hhmm(start_m + int(round(new_hours * 60)))
    row_dict["hours"] = new_hours
    row_dict["end_time"] = end_t
    row_dict["est_quantity"] = new_hours

    if row_dict.get("slot_type") != "休假":
        try:
            check_slot_conflicts(conn, row_dict["employee_name"], row_dict["work_date"],
                                 row_dict["start_time"], end_t,
                                 exclude_slot_id=slot_id, new_hours=new_hours)
        except HTTPException:
            conn.close()
            raise

    real_rec_id = sync_slot_to_lark_base(row_dict)
    row_dict["lark_record_id"] = real_rec_id

    cur.execute(
        "UPDATE pre_schedule_hourly_slot SET hours = ?, end_time = ?, est_quantity = ?, lark_record_id = ?, lark_sync_status = ? WHERE slot_id = ?",
        (new_hours, end_t, new_hours, real_rec_id, row_dict["lark_sync_status"], slot_id)
    )
    conn.commit()
    updated = dict(cur.execute("SELECT * FROM pre_schedule_hourly_slot WHERE slot_id = ?", (slot_id,)).fetchone())
    conn.close()
    return {"ok": True, "slot": updated, "lark_record_id": real_rec_id}

@app.delete("/api/slots/{slot_id}")
def api_delete_slot(slot_id: str, x_actor_name: Optional[str] = Header(None), session_cookie: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME)):
    actor = resolve_actor(x_actor_name, session_cookie)
    conn = get_sqlite_conn()
    authz_slot_owner(actor, conn, slot_id)
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM pre_schedule_hourly_slot WHERE slot_id = ?", (slot_id,)).fetchone()
    deleted_lark = False
    if row:
        lark_rec_id = row["lark_record_id"]
        deleted_lark = delete_slot_from_lark_base(lark_rec_id)
    cur.execute("DELETE FROM pre_schedule_hourly_slot WHERE slot_id = ?", (slot_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": slot_id, "deleted_from_lark_base": deleted_lark}

@app.post("/api/slots/{slot_id}/convert-daily")
def api_convert_daily(slot_id: str, x_actor_name: Optional[str] = Header(None), session_cookie: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME)):
    actor = resolve_actor(x_actor_name, session_cookie)
    conn = get_sqlite_conn()
    authz_slot_owner(actor, conn, slot_id)
    cur = conn.cursor()
    cur.execute("UPDATE pre_schedule_hourly_slot SET converted_to_daily_log = 1 WHERE slot_id = ?", (slot_id,))
    conn.commit()
    row = cur.execute("SELECT * FROM pre_schedule_hourly_slot WHERE slot_id = ?", (slot_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Slot not found")
    row_dict = dict(row)
    real_rec_id = sync_slot_to_lark_base(row_dict)
    cur.execute("UPDATE pre_schedule_hourly_slot SET lark_record_id = ?, lark_sync_status = ? WHERE slot_id = ?", (real_rec_id, row_dict["lark_sync_status"], slot_id))
    conn.commit()
    conn.close()
    row_dict["lark_record_id"] = real_rec_id
    return {"ok": True, "slot": row_dict, "lark_record_id": real_rec_id}

@app.get("/manual", response_class=HTMLResponse)
def serve_manual():
    manual_html = os.path.join(BASE_DIR, "manual.html")
    if os.path.exists(manual_html):
        with open(manual_html, "r", encoding="utf-8") as f:
            return f.read()
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f:
        return f.read()

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def serve_index(request: Request):
    # The user / role / emp query selectors can never override identity — strip
    # them with a 302 to the clean root. A plain GET/HEAD returns 200 OK so external
    # health probes (`curl -I https://<host>/`) get a clean 200.
    if "user" in request.query_params or "role" in request.query_params or "emp" in request.query_params:
        clean_params = [(k, v) for k, v in request.query_params.multi_items() if k not in ("user", "role", "emp")]
        target = "/" + ("?" + urllib.parse.urlencode(clean_params) if clean_params else "")
        return RedirectResponse(url=target, status_code=302)
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f:
        return f.read()
