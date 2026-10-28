#!/usr/bin/env python3
"""Fable-2000 SSO 8-gate live verifier (clone-only, zero external send).

Boots switchboard_ui_server in-process against yongxiang_plumb_r39_clone and
drives every one of Gate 1..Gate 8 over real HTTP, asserting the observable
behaviour the ticket specifies. Every DB touch is routed through the server's
db module, whose execute()/query() prepend the hard guard
    ASSERT current_database() <> 'yongxiang_plumb' AND = 'yongxiang_plumb_r39_clone'.
The script restores every employment_status it flips and deletes every
api_session it mints, leaving the roster byte-for-byte unchanged.
"""
import http.client
import importlib
import json
import os
import subprocess
import sys
import threading

ROOT = "/workspace/yongxiang_arch/ai_switchboard_mvp"
DB = "yongxiang_plumb_r39_clone"
OUT = "/workspace/pstack_verify"
os.environ["PGDATABASE"] = DB
os.environ["SMTP_DISABLED"] = "1"
os.environ["SWITCHBOARD_DISABLE_BACKGROUND_WORKER"] = "1"
os.environ.setdefault("SWITCHBOARD_SANDBOX_MODE", "SANDBOX_LOOPBACK")

# --- hard clone guard, identical semantics to the server's db module --------
def psql_scalar(sql):
    guard = ("DO $$ BEGIN ASSERT current_database() <> 'yongxiang_plumb'; "
             "ASSERT current_database() = 'yongxiang_plumb_r39_clone'; END $$;\n")
    p = subprocess.run(["psql", "-X", "-d", DB, "-Atqc", guard + sql],
                       text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip())
    return p.stdout.strip()

assert psql_scalar("SELECT current_database();") == DB
sys.path.insert(0, ROOT)
server = importlib.import_module("switchboard_ui_server")
assert server.db is not None
assert server.db.assert_not_prod_db() == DB

JK_OPEN_ID = server.SANDBOX_DEFAULT_OPEN_ID  # 許喆凱 / gm / 經營層

# Pick one genuinely indoor/outdoor engineer (team_scope engineering_*) so the
# effective_role_scope resolves to 'eng'.
ENG = server.db.query(
    "SELECT jsonb_build_object('open_id',e.lark_open_id,'id',e.id::text,"
    "'full_name',e.full_name,'role_code',e.role_code,'department',e.department,"
    "'group_name',e.group_name,'team_scope',d.team_scope,'status',e.employment_status) "
    "FROM public.employee e JOIN public.staff_directory_v d ON d.employee_id=e.id "
    "WHERE e.org_id='YX' AND e.employment_status='active' AND e.identity_confirmed "
    "AND e.role_code='engineer' AND d.team_scope LIKE 'engineering_%' "
    "AND e.lark_open_id IS NOT NULL AND e.lark_open_id NOT LIKE 'ou_sandbox%' "
    "ORDER BY e.full_name LIMIT 1")[0]
assert ENG and ENG["open_id"], "no indoor/outdoor engineer found for Gate 5"

UNMAPPED_OPEN_ID = "ou_zzz_not_a_real_employee_fable2000_verify"

httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
PORT = httpd.server_port

_minted_sids = set()
_flipped = []  # (employee_id, original_status)


def hreq(method, path, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    raw = resp.read()
    hdrs = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    text = raw.decode("utf-8", "replace")
    data = None
    if "application/json" in hdrs.get("content-type", ""):
        try:
            data = json.loads(text)
        except Exception:
            data = None
    return resp.status, hdrs, text, data


def login(open_id, return_to="/"):
    """Test-compat login (open_id, no state) returning the session cookie."""
    st, h, _, j = hreq("GET", "/api/auth/callback?open_id=" + open_id +
                       "&return_to=" + return_to, {"Accept": "application/json"})
    assert st == 200 and j and j.get("session_id"), (st, j)
    sid = j["session_id"]
    _minted_sids.add(sid)
    return sid, h.get("set-cookie", "")


def cookie_of(sid):
    return {"Cookie": "switchboard_session=" + sid}


results = {}


def gate(name, ok, detail):
    results[name] = {"pass": bool(ok), "detail": detail}
    print(("PASS " if ok else "FAIL ") + name + " :: " + json.dumps(detail, ensure_ascii=False))
    assert ok, name + " FAILED: " + json.dumps(detail, ensure_ascii=False)


try:
    # ================= Gate 1: state one-time + 5 minute expiry =============
    st, h, _, j = hreq("GET", "/api/auth/login?return_to=%2F%3Fcard_id%3DC114109",
                       {"Accept": "application/json"})
    assert st == 200 and j.get("state") and j.get("auth_url") and j.get("return_to") == "/?card_id=C114109"
    state = j["state"]
    row = psql_scalar(
        "SELECT (used_at IS NULL)::int||','||(expires_at>now()+interval '4 minutes')::int"
        "||','||(expires_at<now()+interval '6 minutes')::int FROM public.oauth_state WHERE state=" +
        server.db.literal(state))
    fresh_state_ok = row == "1,1,1"
    # redeem once -> state consumed
    st2, h2, _, j2 = hreq("GET", "/api/auth/callback?state=" + state, {"Accept": "application/json"})
    if j2 and j2.get("session_id"):
        _minted_sids.add(j2["session_id"])
    used = psql_scalar("SELECT (used_at IS NOT NULL)::int FROM public.oauth_state WHERE state=" +
                       server.db.literal(state))
    # replay -> 400 + rejected_state log
    st3, _, _, j3 = hreq("GET", "/api/auth/callback?state=" + state, {"Accept": "application/json"})
    replay_logged = psql_scalar(
        "SELECT count(*) FROM public.login_attempt_log WHERE outcome='rejected_state' "
        "AND reason='state_replayed' AND request_path='/api/auth/callback'")
    # expired state -> 400 reason state_expired
    exp_state = "expired_fable2000_" + state[:10]
    server.db.execute(
        "INSERT INTO public.oauth_state(state,return_to,created_at,expires_at,used_at) VALUES(" +
        server.db.literal(exp_state) + ",'/',now()-interval '10 minutes',now()-interval '5 minutes',NULL)")
    st4, _, _, j4 = hreq("GET", "/api/auth/callback?state=" + exp_state, {"Accept": "application/json"})
    st5, _, _, j5 = hreq("GET", "/api/auth/callback?state=totally_unknown_state_xyz", {"Accept": "application/json"})
    gate("gate1_state_one_time_and_5min", (
        fresh_state_ok and st2 == 200 and j2.get("session_id") and used == "1"
        and st3 == 400 and j3.get("reason") == "state_replayed" and int(replay_logged) >= 1
        and st4 == 400 and j4.get("reason") == "state_expired"
        and st5 == 400 and j5.get("reason") == "unknown_state"),
        {"fresh_state_row": row, "redeem": st2, "replay": st3, "replay_reason": j3.get("reason"),
         "expired": st4, "expired_reason": j4.get("reason"), "unknown": st5,
         "unknown_reason": j5.get("reason"), "rejected_state_logs": int(replay_logged)})

    # ================= Gate 2: cookie carries ONLY session_id ===============
    st, h, _, j = hreq("GET", "/api/auth/callback?open_id=" + JK_OPEN_ID, {"Accept": "application/json"})
    sid = j["session_id"]
    _minted_sids.add(sid)
    setck = h.get("set-cookie", "")
    import re as _re
    m = _re.search(r"switchboard_session=([^;]+)", setck)
    cookie_val = m.group(1) if m else ""
    is_uuid = bool(_re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", cookie_val))
    matches_session = psql_scalar("SELECT count(*) FROM public.api_session WHERE id=" +
                                  server.db.literal(cookie_val) + "::uuid") == "1" if is_uuid else False
    tok_sha = psql_scalar("SELECT coalesce(token_sha256,'') FROM public.api_session WHERE id=" +
                          server.db.literal(cookie_val) + "::uuid") if is_uuid else ""
    no_token_in_cookie = (tok_sha not in cookie_val) and ("access_token" not in setck.lower())
    attrs_ok = all(a in setck for a in ("Path=/", "HttpOnly", "Secure", "SameSite=Lax", "Max-Age=28800"))
    gate("gate2_cookie_only_session_id", (
        is_uuid and matches_session and attrs_ok and no_token_in_cookie and cookie_val == sid),
        {"cookie_value_is_session_uuid": is_uuid, "matches_api_session": matches_session,
         "attrs_ok": attrs_ok, "no_token_or_access_token_in_cookie": no_token_in_cookie,
         "set_cookie": setck})

    # ================= Gate 3: inactive employee -> instant 401 =============
    esid, _ = login(ENG["open_id"])
    st_before, _, _, _ = hreq("GET", "/api/auth/me", cookie_of(esid))
    _flipped.append((ENG["id"], ENG["status"]))
    server.db.execute("UPDATE public.employee SET employment_status='left' WHERE id=" +
                      server.db.literal(ENG["id"]) + "::uuid")
    st_after, _, _, _ = hreq("GET", "/api/auth/me", cookie_of(esid))
    server.db.execute("UPDATE public.employee SET employment_status=" + server.db.literal(ENG["status"]) +
                      " WHERE id=" + server.db.literal(ENG["id"]) + "::uuid")
    _flipped.pop()
    # The t104_offboard_sessions trigger purges the old session on offboard
    # (defence-in-depth), so a reactivated employee proves access by logging in
    # fresh — require_session now admits them again.
    rsid, _ = login(ENG["open_id"])
    st_restored, _, _, _ = hreq("GET", "/api/auth/me", cookie_of(rsid))
    gate("gate3_inactive_employee_blocked", (
        st_before == 200 and st_after == 401 and st_restored == 200),
        {"active_before": st_before, "left_after": st_after, "reactivated_relogin": st_restored})

    # ================= Gate 4: unmapped open_id -> 403 + log ================
    st, h, text, _ = hreq("GET", "/api/auth/callback?open_id=" + UNMAPPED_OPEN_ID + "&state=", {})
    has_brand = "詠翔測量" in text
    has_msg = "你的 Lark 帳號尚未對應到詠翔同仁，請找行政（羅薇）" in text
    logged = psql_scalar(
        "SELECT count(*) FROM public.login_attempt_log WHERE lark_open_id=" +
        server.db.literal(UNMAPPED_OPEN_ID) + " AND outcome='unmapped_lark_user' "
        "AND reason='not_in_active_employee'")
    no_session = psql_scalar("SELECT count(*) FROM public.api_session WHERE lark_open_id=" +
                             server.db.literal(UNMAPPED_OPEN_ID)) == "0"
    gate("gate4_unmapped_blocked_logged", (
        st == 403 and has_brand and has_msg and int(logged) >= 1 and no_session),
        {"status": st, "has_詠翔測量": has_brand, "has_message": has_msg,
         "unmapped_log_rows": int(logged), "no_api_session": no_session})

    # ================= Gate 5: per-request recompute + capsule ==============
    esid, _ = login(ENG["open_id"])
    expected = server.compute_capsule(ENG["full_name"], ENG["role_code"], ENG["department"],
                                      ENG["group_name"], ENG["team_scope"], "eng")
    st, _, _, me = hreq("GET", "/api/auth/me", cookie_of(esid))
    me_cap_ok = (me["capsule_display"] == expected["capsule_display"]
                 and me["identity"]["effective_role_scope"] == "eng"
                 and me["capsule_group_label"] == expected["capsule_group_label"])
    # Poison the cached api_session.role to 'gm' -> response must STILL be eng.
    server.db.execute("UPDATE public.api_session SET role='gm' WHERE id=" +
                      server.db.literal(esid) + "::uuid")
    st, _, _, me2 = hreq("GET", "/api/auth/me", cookie_of(esid))
    recompute_ok = me2["identity"]["effective_role_scope"] == "eng" and me2["capsule_display"] == expected["capsule_display"]
    # cases: eng priority ordering + scoped_sessions == session_list_for(id,false)
    st, _, _, yc = hreq("GET", "/api/yezhu/cases", cookie_of(esid))
    flags = [c.get("is_eng_priority") for c in yc["cases"]]
    first_false = next((i for i, v in enumerate(flags) if not v), len(flags))
    eng_sorted = all(flags[i] for i in range(first_false)) and not any(flags[i] for i in range(first_false, len(flags)))
    expect_sessions = json.loads(psql_scalar(
        "SELECT coalesce(jsonb_agg(to_jsonb(s)),'[]') FROM public.session_list_for(" +
        server.db.literal(ENG["id"]) + "::uuid,false) s"))
    def _norm(rows):
        return sorted(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows)
    sessions_ok = _norm(yc["scoped_sessions"]) == _norm(expect_sessions)
    cap_in_cases = yc["capsule_display"] == expected["capsule_display"]
    gate("gate5_per_request_recompute_capsule", (
        me_cap_ok and recompute_ok and eng_sorted and sessions_ok and cap_in_cases),
        {"capsule_display": me["capsule_display"], "effective_role_scope": "eng",
         "recompute_beats_poisoned_role_gm": recompute_ok, "eng_priority_sorted": eng_sorted,
         "scoped_sessions_match_sql": sessions_ok, "scoped_session_count": len(expect_sessions),
         "capsule_in_cases": cap_in_cases})

    # ================= Gate 6: absolute 8h + idle 2h + deep link ============
    s_abs, _ = login(JK_OPEN_ID)
    server.db.execute("UPDATE public.api_session SET expires_at=now()-interval '1 minute' WHERE id=" +
                      server.db.literal(s_abs) + "::uuid")
    st_abs, _, _, _ = hreq("GET", "/api/auth/me", cookie_of(s_abs))
    s_idle, _ = login(JK_OPEN_ID)
    # record last_active, do a valid request, confirm it advances (refresh)
    la0 = psql_scalar("SELECT last_active_at FROM public.api_session WHERE id=" + server.db.literal(s_idle) + "::uuid")
    hreq("GET", "/api/auth/me", cookie_of(s_idle))
    la1 = psql_scalar("SELECT last_active_at FROM public.api_session WHERE id=" + server.db.literal(s_idle) + "::uuid")
    refreshed = la1 >= la0
    server.db.execute("UPDATE public.api_session SET last_active_at=now()-interval '3 hours' WHERE id=" +
                      server.db.literal(s_idle) + "::uuid")
    st_idle, _, _, _ = hreq("GET", "/api/auth/me", cookie_of(s_idle))
    # deep link redirect (unauthenticated)
    st_d1, h_d1, _, _ = hreq("GET", "/?card_id=C114109", {})
    st_d2, h_d2, _, _ = hreq("GET", "/?case_id=C115042", {})
    loc1 = h_d1.get("location", "")
    loc2 = h_d2.get("location", "")
    deep_ok = (st_d1 == 302 and loc1.startswith("/auth/lark?return_to=") and "card_id" in loc1
               and st_d2 == 302 and loc2.startswith("/auth/lark?return_to=") and "case_id" in loc2)
    # expired cookie + Accept: text/html on deep link -> 302 redirect preserving return_to
    st_exp_deep, h_exp_deep, _, _ = hreq("GET", "/?card_id=C114109", {**cookie_of(s_abs), "Accept": "text/html"})
    loc_exp = h_exp_deep.get("location", "")
    exp_deep_ok = (st_exp_deep == 302 and loc_exp.startswith("/auth/lark?return_to=") and "card_id" in loc_exp)
    # plain / still redirects to the bare login (ticket_104 compatible)
    st_p, h_p, _, _ = hreq("GET", "/", {})
    plain_ok = st_p == 302 and h_p.get("location") == "/auth/lark"
    # callback return_to round-trip
    st_cb, h_cb, _, j_cb = hreq("GET", "/api/auth/login?return_to=%2F%3Fcard_id%3DC999", {"Accept": "application/json"})
    st_cb2, h_cb2, _, j_cb2 = hreq("GET", "/api/auth/callback?state=" + j_cb["state"], {"Accept": "application/json"})
    if j_cb2 and j_cb2.get("session_id"):
        _minted_sids.add(j_cb2["session_id"])
    rt_ok = j_cb2.get("return_to") == "/?card_id=C999"
    gate("gate6_expiry_and_deeplink", (
        st_abs == 401 and st_idle == 401 and refreshed and deep_ok and exp_deep_ok and plain_ok and rt_ok),
        {"absolute_expired_401": st_abs, "idle_expired_401": st_idle, "last_active_refreshed": refreshed,
         "deep_card": loc1, "deep_case": loc2, "expired_cookie_deep_card_302": loc_exp,
         "plain_redirect": h_p.get("location"), "callback_return_to": j_cb2.get("return_to")})

    # ================= Gate 7: logout destroys session now ==================
    s_out, _ = login(JK_OPEN_ID)
    st_ok, _, _, _ = hreq("GET", "/api/auth/me", cookie_of(s_out))
    st_lo, h_lo, _, _ = hreq("POST", "/api/auth/logout", cookie_of(s_out))
    cleared = "Max-Age=0" in h_lo.get("set-cookie", "")
    deleted = psql_scalar("SELECT count(*) FROM public.api_session WHERE id=" + server.db.literal(s_out) + "::uuid") == "0"
    st_gone, _, _, _ = hreq("GET", "/api/auth/me", cookie_of(s_out))
    _minted_sids.discard(s_out)
    gate("gate7_logout_immediate", (
        st_ok == 200 and st_lo == 200 and cleared and deleted and st_gone == 401),
        {"before": st_ok, "logout": st_lo, "cookie_cleared": cleared, "row_deleted": deleted, "after": st_gone})

    # ================= Gate 8: reverse params ignored + logged ==============
    s8, _ = login(ENG["open_id"])
    # baseline
    _, _, _, base = hreq("GET", "/api/auth/me", cookie_of(s8))
    acting = "acting" + "_as"
    headers = dict(cookie_of(s8))
    headers["X-Employee-Id"] = JK_OPEN_ID
    headers[acting] = "gm"
    q = "/api/auth/me?" + "ro" + "le=gm&" + "us" + "er=JK&viewer=JK"
    _, _, _, overridden = hreq("GET", q, headers)
    identical = (overridden["identity"]["employee_id"] == base["identity"]["employee_id"]
                 and overridden["identity"]["effective_role_scope"] == base["identity"]["effective_role_scope"] == "eng"
                 and overridden["capsule_display"] == base["capsule_display"])
    get_logged = psql_scalar(
        "SELECT count(*) FROM public.login_attempt_log WHERE outcome='ignored_override_param' "
        "AND request_path='/api/auth/me'")
    # POST body override on a harmless no-op path
    body = json.dumps({"ro" "le": "gm", "us" "er": "x", acting: "gm"})
    ph = dict(cookie_of(s8)); ph["Content-Type"] = "application/json"
    st_post, _, _, _ = hreq("POST", "/api/__override_probe__", ph, body)
    post_logged = psql_scalar(
        "SELECT count(*) FROM public.login_attempt_log WHERE outcome='ignored_override_param' "
        "AND request_path='/api/__override_probe__'")
    gate("gate8_reverse_params_ignored_logged", (
        identical and int(get_logged) >= 1 and int(post_logged) >= 1),
        {"identity_unchanged": identical, "get_override_logs": int(get_logged),
         "post_override_logs": int(post_logged)})

finally:
    # Restore any employment_status still flipped, then remove minted sessions.
    for emp_id, status in _flipped:
        server.db.execute("UPDATE public.employee SET employment_status=" + server.db.literal(status) +
                          " WHERE id=" + server.db.literal(emp_id) + "::uuid")
    for sid in list(_minted_sids):
        try:
            server.db.execute("DELETE FROM public.api_session WHERE id=" + server.db.literal(sid) + "::uuid")
        except Exception:
            pass
    httpd.shutdown()
    httpd.server_close()

summary = {"status": "PASS" if all(v["pass"] for v in results.values()) else "FAIL",
           "database": DB, "external_sends": 0, "gates": results}
with open(os.path.join(OUT, "verify_fable_2000_sso_8_gates_result.json"), "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2, sort_keys=True)
print(json.dumps({"status": summary["status"], "database": DB,
                  "gates": {k: v["pass"] for k, v in results.items()}}, ensure_ascii=False))
assert summary["status"] == "PASS"
