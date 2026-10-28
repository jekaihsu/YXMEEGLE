"""
End-to-end tests for Lark OAuth 2.0 SSO authentication, HMAC-SHA256 session
cookies (`yx_presched_session`), and cookie-driven RBAC on `:8895`.

Covers the four QA Blocking "Act on" items:
  #1 OAuth redirect_uri never regresses to http://127.0.0.1:8895 (Lark 20029),
     login/callback route aliases, HEAD / -> 200.
  #2 Name-only password-free login backdoor is disabled (403); login screen has
     zero <input>s and no manual-name fallback.
  #3 GET /api/slots & /api/schedule enforce RBAC (401 unauth; staff self-only;
     leads scoped to their roster; full-company admins see everyone).
  #4 總經理 許茂坤 is a full-company admin (sees the whole active roster).
"""
import json, sqlite3
import pytest
from fastapi.testclient import TestClient
import app as appmod

CASE_CODE = "C115055-1"

# Canonical Lark open_ids straight from catalog.json.
OID_JK = "ou_7dfe7ce548da22a0275cba0d92b3bfec"        # 許喆凱 / 許傑凱 · 管理員
OID_MK = "ou_d6abe79a176ad52f5f7d0f713a0ae914"        # 許茂坤 · 總經理（全公司）
OID_HUANG = "ou_1f27d5a5e2ed4dc8fc2b7579443039ad"     # 黃馨加 · 報告組（一般組員）
OID_ZJB = "ou_4ff567bcedd4b403f76e48c19d6f5c8e"       # 張家彬 · 控制組（組長）
OID_WKH = "ou_e8708f8b380fc156887799e928afc479"       # 吳科翰 · 外業經理


def _active_employee_count():
    cat = json.load(open(appmod.CATALOG_PATH, encoding="utf-8"))
    return len(cat.get("employees", []))


@pytest.fixture()
def client(monkeypatch, tmp_path):
    db = tmp_path / "test_oauth_sso.db"
    cols = [
        "slot_id", "work_date", "employee_id", "employee_name", "lark_open_id",
        "v3_person_record_id", "department_group", "team_group", "slot_type",
        "start_time", "end_time", "hours", "priority_rank", "case_code", "case_name",
        "client_name", "v3_case_record_id", "contract_item_code", "schedule_reason",
        "work_item", "work_note", "est_quantity", "est_points", "upstream_dep_note",
        "converted_to_daily_log", "lark_sync_status", "lark_record_id",
    ]
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE pre_schedule_hourly_slot (%s)" % ",".join(cols))
    conn.commit()
    conn.close()

    monkeypatch.setattr(appmod, "SQLITE_PATH", str(db))
    monkeypatch.setattr(
        appmod,
        "LARK_CLI_RUNNER",
        lambda cmd: json.dumps({"ok": True, "data": {"record": {"record_id_list": ["recMOCKSSO"]}}}),
    )
    return TestClient(appmod.app)


def _seed_slot(employee_name, department_group, team_group, work_date="2099-03-01"):
    """Insert one minimal slot row straight into the monkeypatched test DB."""
    conn = sqlite3.connect(appmod.SQLITE_PATH)
    conn.execute(
        "INSERT INTO pre_schedule_hourly_slot "
        "(slot_id, work_date, employee_name, department_group, team_group, slot_type, "
        " start_time, end_time, hours, priority_rank, case_code, case_name, work_item, "
        " converted_to_daily_log, lark_sync_status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("PS-" + employee_name, work_date, employee_name, department_group, team_group,
         "出工", "08:30", "10:30", 2.0, 1, CASE_CODE, "測試案", "資料整理", 0, "LOCAL_ONLY"),
    )
    conn.commit()
    conn.close()


def _login_open_id(client, open_id):
    r = client.post("/api/auth/lark-verify", json={"open_id": open_id, "use_active_lark_cli": False})
    assert r.status_code == 200, f"open_id login failed: {r.status_code} {r.text}"
    return r


# --------------------------------------------------------------------------- #
# Baseline SSO / cookie behaviour
# --------------------------------------------------------------------------- #
def test_unauthenticated_auth_me_returns_401(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    body = r.json()
    assert body["authenticated"] is False
    assert body["app_id"] == "cli_aa5c5ceba4f8de2a"
    assert body["login_url"] == "/api/auth/login"


def test_oauth_login_redirects_to_lark_authorize_with_state_cookie(client):
    r = client.get(
        "/api/auth/login",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "when-boolean-timers-super.trycloudflare.com"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.larksuite.com/open-apis/authen/v1/authorize")
    assert "app_id=cli_aa5c5ceba4f8de2a" in loc
    assert "when-boolean-timers-super.trycloudflare.com%2Fapi%2Fauth%2Fcallback" in loc
    assert appmod.OAUTH_STATE_COOKIE_NAME in r.cookies


# --- Act on #1: redirect_uri must be https for *.trycloudflare.com even with no
#     x-forwarded-proto header (otherwise Lark raises OAuth Error 20029). -------
def test_trycloudflare_host_forces_https_redirect_uri(client):
    r = client.get(
        "/api/auth/login",
        headers={"Host": "breakfast-crops-rose-fairly.trycloudflare.com"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert (
        "redirect_uri=https%3A%2F%2Fbreakfast-crops-rose-fairly.trycloudflare.com%2Fapi%2Fauth%2Fcallback"
        in loc
    ), loc
    assert "127.0.0.1" not in loc


def test_zeabur_host_forces_https_redirect_uri(client):
    r = client.get(
        "/api/auth/login", headers={"Host": "yx-presched.zeabur.app"}, follow_redirects=False
    )
    assert "redirect_uri=https%3A%2F%2Fyx-presched.zeabur.app%2Fapi%2Fauth%2Fcallback" in r.headers["location"]


# --- Act on #1: login / callback route aliases are interchangeable. ---------
def test_login_route_aliases_all_redirect_to_lark(client):
    for path in ("/api/auth/login", "/auth/lark/login", "/login"):
        r = client.get(path, headers={"Host": "breakfast-crops-rose-fairly.trycloudflare.com"},
                       follow_redirects=False)
        assert r.status_code == 302, path
        assert r.headers["location"].startswith(
            "https://accounts.larksuite.com/open-apis/authen/v1/authorize"
        ), path


def test_callback_alias_rejects_missing_code(client):
    # /auth/lark/callback is wired to the same handler as /api/auth/callback.
    r = client.get("/auth/lark/callback", follow_redirects=False)
    assert r.status_code == 400


# --- Act on #1: HEAD / -> 200 OK, ?user=/?role= -> 302 clean redirect. ------
def test_root_supports_head_200_and_query_param_redirect(client):
    assert client.head("/").status_code == 200
    assert client.get("/").status_code == 200
    r = client.get("/?user=吳科翰&role=manager", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/"


def test_oauth_callback_exchanges_code_and_sets_signed_cookie_for_jk(client, monkeypatch):
    r_login = client.get("/api/auth/login", follow_redirects=False)
    state = r_login.cookies[appmod.OAUTH_STATE_COOKIE_NAME]

    monkeypatch.setattr(
        appmod,
        "LARK_OAUTH_EXCHANGER",
        lambda code, redirect_uri: {"open_id": OID_JK, "name": "jekai", "en_name": "jekai"},
    )
    r_cb = client.get(f"/api/auth/callback?code=mock_code_jk&state={state}", follow_redirects=False)
    assert r_cb.status_code == 302
    assert r_cb.headers["location"] == "/"
    assert appmod.SESSION_COOKIE_NAME in r_cb.cookies

    r_me = client.get("/api/auth/me")
    assert r_me.status_code == 200
    me = r_me.json()
    assert me["authenticated"] is True
    assert me["user"]["display_name"] == "許傑凱"
    assert me["user"]["is_admin"] is True
    # Admin sees the entire active roster (whole company). The active headcount
    # is owned by catalog.json (a parallel ticket prunes resigned staff), so we
    # assert against the live count rather than a frozen number.
    assert len(me["team_roster"]) == _active_employee_count()
    assert len(me["team_roster"]) >= 60


# --- Act on #1: an off-roster Lark identity gets a friendly page, no cookie. -
def test_callback_off_roster_identity_gets_no_cookie(client, monkeypatch):
    r_login = client.get("/api/auth/login", follow_redirects=False)
    state = r_login.cookies[appmod.OAUTH_STATE_COOKIE_NAME]
    monkeypatch.setattr(
        appmod,
        "LARK_OAUTH_EXCHANGER",
        lambda code, redirect_uri: {"open_id": "ou_strangernotinroster000000", "name": "路人甲"},
    )
    r_cb = client.get(f"/api/auth/callback?code=x&state={state}", follow_redirects=False)
    assert r_cb.status_code == 403
    assert appmod.SESSION_COOKIE_NAME not in r_cb.cookies
    assert "你的 Lark 帳號尚未對應到永祥同仁，請找行政（羅薇）" in r_cb.text


def test_oauth_callback_rejects_state_mismatch(client, monkeypatch):
    client.get("/api/auth/login", follow_redirects=False)
    monkeypatch.setattr(appmod, "LARK_OAUTH_EXCHANGER", lambda code, redirect_uri: {"open_id": OID_JK})
    r_cb = client.get("/api/auth/callback?code=mock_code&state=wrong_state", follow_redirects=False)
    assert r_cb.status_code == 400


def test_tampered_session_cookie_is_rejected_401(client):
    valid_token = appmod.sign_session_cookie({
        "open_id": OID_JK, "full_name": "許傑凱", "canonical_name": "許喆凱",
    })
    tampered = valid_token[:-4] + "0000"
    client.cookies.set(appmod.SESSION_COOKIE_NAME, tampered)
    r_me = client.get("/api/auth/me")
    assert r_me.status_code == 401
    r_slot = client.post(
        "/api/slots",
        json={
            "work_date": "2099-02-01", "employee_name": "朱雅雯", "slot_type": "出工",
            "start_time": "08:30", "end_time": "10:30", "hours": 2.0,
            "case_code": CASE_CODE, "work_item": "資料整理",
        },
    )
    assert r_slot.status_code == 401


# --------------------------------------------------------------------------- #
# Act on #2: name-only password-free login backdoor is disabled.
# --------------------------------------------------------------------------- #
def test_employee_name_passwordless_login_is_forbidden_403(client):
    for path in ("/api/auth/lark-session", "/api/auth/lark-verify"):
        r = client.post(path, json={"employee_name": "許茂坤", "use_active_lark_cli": False})
        assert r.status_code == 403, f"{path}: {r.status_code} {r.text}"
        assert "已停用姓名免密碼登入" in r.text
        assert appmod.SESSION_COOKIE_NAME not in r.cookies


def test_login_screen_has_zero_inputs_and_no_manual_name_fallback():
    import re
    from pathlib import Path
    html = (Path(appmod.BASE_DIR) / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<div id="larkLoginScreen".*?</div>\s*</div>\s*</div>', html, re.S)
    assert m is not None, "#larkLoginScreen block missing"
    login_block = m.group(0)
    assert "<input" not in login_block.lower()
    assert "<select" not in login_block.lower()
    assert "larkRosterNameInput" not in html
    assert "larkLoginNameInput" not in html
    assert "loginWithRosterName" not in html
    assert "loginByLarkDirectory" not in html
    assert "op-login-roster-row" not in html
    assert "或輸入同仁姓名" not in html
    assert "使用 Lark 帳號一鍵登入" in login_block
    # loginWithLarkSso must go straight to the OAuth redirect (no CLI hijack).
    assert 'window.location.href = "/api/auth/login"' in html
    assert 'employee_name: "吳科翰"' not in html


# --------------------------------------------------------------------------- #
# Act on #3 & #4: RBAC on GET /api/slots & /api/schedule.
# --------------------------------------------------------------------------- #
def test_slots_requires_authentication_401(client):
    assert client.get("/api/slots").status_code == 401
    assert client.get("/api/schedule").status_code == 401
    assert client.get("/api/slots?user=許茂坤&role=admin").status_code == 401


def test_slots_rbac_staff_self_only_lead_scoped_admin_all(client):
    # Seed one slot per person across several groups.
    _seed_slot("黃馨加", "內業部門", "報告組")
    _seed_slot("林佑靜", "內業部門", "控制組")
    _seed_slot("朱雅雯", "內業部門", "品管組")
    _seed_slot("鄭文澤", "內業部門", "圖資組")
    _seed_slot("吳科翰", "外業部門", "外業經理")

    # 1) 一般組員 黃馨加 (報告組) only sees her own row.
    _login_open_id(client, OID_HUANG)
    items = client.get("/api/slots").json()["items"]
    assert {i["employee_name"] for i in items} == {"黃馨加"}
    # Querying another employee out of scope -> 403.
    assert client.get("/api/slots?employee_name=林佑靜").status_code == 403
    client.post("/api/auth/logout")
    client.cookies.clear()

    # 2) 控制組組長 張家彬 sees 控制組 + 品管組 members, not 報告/圖資/外業.
    _login_open_id(client, OID_ZJB)
    names = {i["employee_name"] for i in client.get("/api/slots").json()["items"]}
    assert "林佑靜" in names and "朱雅雯" in names
    assert "黃馨加" not in names and "鄭文澤" not in names and "吳科翰" not in names
    client.post("/api/auth/logout")
    client.cookies.clear()

    # 3) 總經理 許茂坤 (全公司 admin) sees everyone seeded.
    _login_open_id(client, OID_MK)
    me = client.get("/api/auth/me").json()
    assert me["user"]["can_manage_all"] is True and me["user"]["is_admin"] is True
    assert len(me["team_roster"]) == _active_employee_count()
    names = {i["employee_name"] for i in client.get("/api/slots").json()["items"]}
    assert names == {"黃馨加", "林佑靜", "朱雅雯", "鄭文澤", "吳科翰"}


def test_cookie_rbac_staff_self_only_and_managers_scoped(client):
    # Staff member 黃馨加 (報告組) via verified open_id login.
    r_staff = _login_open_id(client, OID_HUANG)
    assert r_staff.json()["user"]["sub_group"] == "報告組"
    assert len(r_staff.json()["team_roster"]) == 1

    # Can schedule for self (pure cookie auth, no X-Actor-Name).
    r_self = client.post(
        "/api/slots",
        json={
            "work_date": "2099-02-02", "employee_name": "黃馨加", "slot_type": "出工",
            "start_time": "08:30", "end_time": "10:30", "hours": 2.0,
            "case_code": CASE_CODE, "work_item": "成果報告撰寫",
        },
    )
    assert r_self.status_code == 200

    # Blocked from scheduling for another employee.
    r_other = client.post(
        "/api/slots",
        json={
            "work_date": "2099-02-02", "employee_name": "鄭文澤", "slot_type": "出工",
            "start_time": "08:30", "end_time": "10:30", "hours": 2.0,
            "case_code": CASE_CODE, "work_item": "地形圖編修",
        },
    )
    assert r_other.status_code == 403
    client.post("/api/auth/logout")
    client.cookies.clear()

    # Field manager 吳科翰 (外業經理) can schedule 外業部門 staff (古恆安 · 地形A).
    r_wkh = _login_open_id(client, OID_WKH)
    assert r_wkh.json()["user"]["sub_group"] == "外業經理"
    r_field = client.post(
        "/api/slots",
        json={
            "work_date": "2099-02-03", "employee_name": "古恆安", "slot_type": "出工",
            "start_time": "08:30", "end_time": "10:30", "hours": 2.0,
            "case_code": CASE_CODE, "work_item": "施工放樣與進場協調",
        },
    )
    assert r_field.status_code == 200

    # Logout clears the session cookie.
    assert client.post("/api/auth/logout").status_code == 200
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401


def test_query_param_user_and_role_cannot_override_identity(client):
    # ?user= / ?role= never escalate on /api/auth/me or /api/bootstrap.
    assert client.get("/api/auth/me?user=吳科翰&role=admin").status_code == 401
    assert client.get("/api/bootstrap?user=吳科翰").status_code == 401

    # Log in as 黃馨加 via open_id; spoof params must not escalate her.
    r_login = _login_open_id(client, OID_HUANG)
    cookie_payload = appmod.verify_session_cookie(r_login.cookies[appmod.SESSION_COOKIE_NAME])
    assert cookie_payload["open_id"] == OID_HUANG
    assert cookie_payload["emp_name"] == "黃馨加"
    assert cookie_payload["team_group"] == "報告組"
    assert cookie_payload["can_schedule_others"] is False
    assert cookie_payload["allowed_members"] == ["黃馨加"]

    me_spoof = client.get("/api/auth/me?user=許喆凱&role=admin").json()
    assert me_spoof["user"]["full_name"] == "黃馨加"
    r_forbid = client.post(
        "/api/slots?user=許喆凱&role=admin",
        json={
            "work_date": "2099-02-05", "employee_name": "吳科翰", "slot_type": "出工",
            "start_time": "08:30", "end_time": "10:30", "hours": 2.0,
            "case_code": CASE_CODE, "work_item": "成果報告撰寫",
        },
    )
    assert r_forbid.status_code == 403


def test_control_group_lead_open_id_scope(client):
    r_zjb = _login_open_id(client, OID_ZJB)
    zjb_user = r_zjb.json()["user"]
    assert zjb_user["sub_group"] == "控制組"
    assert zjb_user["can_schedule_others"] is True
    assert "林佑靜" in zjb_user["allowed_members"]
    assert "朱雅雯" in zjb_user["allowed_members"]


# --- Act on #4: 總經理 許茂坤 is a full-company admin. ------------------------
def test_general_manager_xmk_is_full_company_admin(client):
    r = _login_open_id(client, OID_MK)
    user = r.json()["user"]
    assert user["full_name"] == "許茂坤"
    assert user["is_admin"] is True
    assert user["can_manage_all"] is True
    assert user["can_schedule_others"] is True
    assert user["allowed_groups"] == ["ALL"]
    assert len(r.json()["team_roster"]) == _active_employee_count()


def test_active_lark_cli_session_login_returns_200_and_sets_cookie(client):
    r = client.post("/api/auth/lark-session", json={"use_active_lark_cli": True})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["ok"] is True
    assert data["authenticated"] is True
    assert data["user"]["lark_open_id"] == OID_JK
    assert appmod.SESSION_COOKIE_NAME in r.cookies

    r_me = client.get("/api/auth/me")
    assert r_me.status_code == 200
    assert r_me.json()["authenticated"] is True
    assert r_me.json()["user"]["lark_open_id"] == OID_JK
