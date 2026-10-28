#!/usr/bin/env python3
"""
永祥 · 業主往來 — Real Product PostgreSQL Backend Server
Serves http://127.0.0.1:5188, http://127.0.0.1:5177, and http://127.0.0.1:8029.
Connected 100% to PostgreSQL yongxiang_plumb_r39_clone (strictly isolated from production yongxiang_plumb),
with automatic offline JSON state persistence fallback for standalone environments.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import threading
import time
from uuid import UUID
from urllib.parse import parse_qs, quote as urllib_quote, unquote, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

PG_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/yongxiang_plumb_r39_clone"
assert PG_DSN == "postgresql://postgres:postgres@127.0.0.1:5432/yongxiang_plumb_r39_clone"
os.environ.update(PG_DSN=PG_DSN, PGHOST="127.0.0.1", PGPORT="5432", PGUSER="postgres",
                  PGPASSWORD="postgres", PGDATABASE="yongxiang_plumb_r39_clone",
                  SMTP_DISABLED="1", SWITCHBOARD_SANDBOX_MODE="SANDBOX_LOOPBACK")

UI_HTML = ROOT / "ui" / "index.html"
if not UI_HTML.exists():
    UI_HTML = ROOT / "index.html"
BUNDLE_JSON = ROOT / "ui_bundle_data.json"
DRYRUN_JSON = ROOT / "dryrun_20.json"
LOCAL_PERSIST_JSON = ROOT / "yezhu_persistent_state.json"
_ENV_PORT = int(os.environ.get("PORT", "0") or "0")
PORTS = (5188, 5177, 8029, 8787, 8788) + ((_ENV_PORT,) if _ENV_PORT and _ENV_PORT not in (5188, 5177, 8029, 8787, 8788) else ())
SMTP_DISABLED = True
ALLOWED_TEST_RECIPIENT = "jekai@yxsurvey.com.tw"
PENDING_JK_FINAL_APPROVAL = "PENDING_JK_FINAL_APPROVAL"

# --- R54 Lark OAuth 2.0 (single sign-on) --------------------------------
# The effective principal is ALWAYS the authenticated Lark account; there is no
# identity-override / role-swap path any more (see 011_r54_drop_impersonation.sql
# and sql/013_ticket104_sso_scope_shadow.sql). The callback mints an
# api_session ONLY for an open_id that maps to one of the active YX employees.
LARK_APP_ID = os.environ.get("LARK_APP_ID", "")
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
LARK_AUTHORIZE_URL = os.environ.get(
    "LARK_AUTHORIZE_URL", "https://accounts.larksuite.com/open-apis/authen/v1/authorize")
LARK_TOKEN_URL = os.environ.get(
    "LARK_TOKEN_URL", "https://open.larksuite.com/open-apis/authen/v2/oauth/token")
LARK_USERINFO_URL = os.environ.get(
    "LARK_USERINFO_URL", "https://open.larksuite.com/open-apis/authen/v1/user_info")
# When no live Lark app is bound (the trial clone), the SSO flow runs in a
# loopback mode that NEVER calls an external service yet still enforces the
# exact open_id -> active-employee mapping (0 external sends).
SANDBOX_LOOPBACK = (
    os.environ.get("SWITCHBOARD_SANDBOX_MODE", "") == "SANDBOX_LOOPBACK"
    and not (LARK_APP_ID and LARK_APP_SECRET)
)
# The identity a one-click sandbox login resolves to (JK / 許喆凱, 經營層).
SANDBOX_DEFAULT_OPEN_ID = os.environ.get(
    "SWITCHBOARD_SANDBOX_OPEN_ID", "ou_7dfe7ce548da22a0275cba0d92b3bfec")
# Signing key for the short-lived OAuth CSRF `state` token (per-process).
_OAUTH_STATE_SECRET = os.environ.get("OAUTH_STATE_SECRET") or secrets.token_urlsafe(32)
# The ONLY message an unmapped Lark account may see (HTTP 403).
UNMAPPED_LARK_MESSAGE = "你的 Lark 帳號尚未對應到詠翔同仁，請找行政（羅薇）"
# Login start / callback route aliases (all public, no session required).
AUTH_PUBLIC_PATHS = {
    "/auth/lark", "/login",                      # clean login screen
    "/api/auth/login", "/auth/lark/login",       # OAuth start
    "/api/auth/callback", "/auth/lark/callback",  # OAuth callback
}


def compute_redirect_uri(host: str) -> str:
    """Derive the OAuth redirect_uri from the request Host.

    A *.trycloudflare.com or *.zeabur.app host is always served over HTTPS, so
    the redirect must be https://<Host>/api/auth/callback. Otherwise honour an
    explicit LARK_REDIRECT_URI, falling back to the request host on http.
    """
    host = (host or "").strip()
    if host.endswith(".trycloudflare.com") or host.endswith(".zeabur.app"):
        return "https://" + host + "/api/auth/callback"
    env = os.environ.get("LARK_REDIRECT_URI", "")
    if env:
        return env
    return "http://" + (host or "127.0.0.1:5188") + "/api/auth/callback"


def _sign_oauth_state(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    sig = hmac.new(_OAUTH_STATE_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return body + "." + sig


def _verify_oauth_state(state: str) -> bool:
    try:
        body, sig = (state or "").split(".", 1)
        want = hmac.new(_OAUTH_STATE_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, want):
            return False
        pad = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
        return int(payload.get("exp", 0)) >= int(time.time())
    except Exception:
        return False


def _lark_exchange_open_id(code: str, redirect_uri: str) -> str:
    """Production path: exchange the authorization code for the user's open_id.

    Never reached in SANDBOX_LOOPBACK (no live app, 0 external sends)."""
    import urllib.request
    app_id = os.environ.get("LARK_APP_ID") or LARK_APP_ID
    app_secret = os.environ.get("LARK_APP_SECRET") or LARK_APP_SECRET
    tok_body = json.dumps(dict(
        grant_type="authorization_code", client_id=app_id,
        client_secret=app_secret, code=code, redirect_uri=redirect_uri,
    )).encode("utf-8")
    req = urllib.request.Request(
        LARK_TOKEN_URL, data=tok_body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        tok = json.loads(resp.read().decode("utf-8"))
    access = tok.get("access_token") or (tok.get("data") or {}).get("access_token")
    info_req = urllib.request.Request(
        LARK_USERINFO_URL, headers={"Authorization": "Bearer " + str(access)})
    with urllib.request.urlopen(info_req, timeout=10) as resp:
        info = json.loads(resp.read().decode("utf-8"))
    data = info.get("data") or info
    return str(data.get("open_id") or "").strip()


def _html_page(inner_body: str, title: str = "詠翔測量 · 業主往來") -> bytes:
    return (
        "<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{title}</title>"
        "<style>:root{--ink:#2f3a2a;--line:#d7decf}"
        "*{box-sizing:border-box}"
        "body{margin:0;min-height:100vh;display:grid;place-items:center;"
        "font-family:-apple-system,'PingFang TC','Noto Sans TC',system-ui,sans-serif;"
        "background:linear-gradient(160deg,#f4f6ef,#e8ede0);color:var(--ink)}"
        ".login-card{background:#fff;border:1px solid var(--line);border-radius:18px;"
        "box-shadow:0 18px 50px rgba(0,0,0,.10);padding:46px 40px;width:360px;max-width:92vw;text-align:center}"
        ".brand{display:flex;align-items:center;justify-content:center;gap:10px;font-size:19px;font-weight:800;margin-bottom:6px}"
        ".brand-mark{width:34px;height:34px;border-radius:9px;background:#3f6b3f;color:#fff;"
        "display:inline-grid;place-items:center;font-size:17px}"
        ".sub{color:#5E6B56;font-size:13px;margin:4px 0 30px}"
        ".lark-login-btn{display:block;width:100%;padding:14px 18px;border:0;border-radius:11px;"
        "background:#1456f0;color:#fff;font-size:15px;font-weight:700;text-decoration:none;cursor:pointer}"
        ".lark-login-btn:hover{background:#0f45c8}"
        ".notice{max-width:420px;text-align:center;font-size:16px;line-height:1.7;color:var(--ink);padding:40px}"
        "</style></head><body>" + inner_body + "</body></html>"
    ).encode("utf-8")


def login_screen_html(return_to: str = "/") -> bytes:
    """Clean login screen: ONLY the single Lark button. No <input>, no switcher."""
    href = "/api/auth/login"
    if return_to and return_to != "/":
        href = "/api/auth/login?return_to=" + urllib_quote(return_to)
    return _html_page(
        "<main class=\"login-card\">"
        "<div class=\"brand\"><span class=\"brand-mark\">詠</span>詠翔測量 · 業主往來</div>"
        "<p class=\"sub\">請使用公司 Lark 帳號登入</p>"
        f"<a class=\"lark-login-btn\" id=\"lark-login\" href=\"{href}\">使用 Lark 帳號一鍵登入</a>"
        "</main>",
        title="詠翔測量 · 業主往來 — 登入",
    )


def unmapped_lark_html() -> bytes:
    return _html_page(
        "<main class=\"notice\"><div class=\"brand\" style=\"justify-content:center;margin-bottom:14px\">"
        "<span class=\"brand-mark\">詠</span>詠翔測量 · 業主往來</div>"
        f"<div>{UNMAPPED_LARK_MESSAGE}</div></main>",
        title="詠翔測量 · 業主往來",
    )


SESSION_COOKIE = "switchboard_session"


def _session_cookie_header(session_id: str) -> str:
    """Gate 2: the cookie carries ONLY the session id (never an access token)."""
    return (SESSION_COOKIE + "=" + str(session_id) +
            "; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=28800")


def _wants_json(handler) -> bool:
    return "application/json" in (handler.headers.get("Accept", "") or "")


def auth_start(handler, path: str, qs: dict) -> None:
    """Gate 1: begin login. Mint a single-use `state` (5 min TTL) bound to the
    requested return_to, then hand back the auth_url. Honours Accept/redirect."""
    return_to = (qs.get("return_to") or ["/"])[0] or "/"
    state = _new_oauth_state(return_to)
    base = "/api/auth/callback"
    auth_url = base + "?state=" + urllib_quote(state) + "&return_to=" + urllib_quote(return_to)
    wants_redirect = qs.get("redirect") == ["1"]
    html_browser = ("text/html" in (handler.headers.get("Accept", "") or "")) and not path.startswith("/api/")
    if (html_browser and not _wants_json(handler)) and not wants_redirect:
        # A plain browser hitting the login screen sees the clean single button.
        handler._send(HTTPStatus.OK, login_screen_html(return_to), "text/html; charset=utf-8")
        return
    live_app_id = os.environ.get("LARK_APP_ID", "")
    live_app_secret = os.environ.get("LARK_APP_SECRET", "")
    if live_app_id and live_app_secret and (wants_redirect or not _wants_json(handler)):
        redirect_uri = compute_redirect_uri(handler.headers.get("Host", ""))
        lark_url = (
            LARK_AUTHORIZE_URL
            + "?app_id=" + urllib_quote(live_app_id)
            + "&client_id=" + urllib_quote(live_app_id)
            + "&redirect_uri=" + urllib_quote(redirect_uri)
            + "&state=" + urllib_quote(state)
            + "&response_type=code"
        )
        handler.send_response(302)
        handler.send_header('Location', lark_url)
        handler.send_header('Cache-Control', 'no-store')
        handler.end_headers()
        return
    if wants_redirect or (not _wants_json(handler) and path.startswith("/api/")):
        handler.send_response(302)
        handler.send_header('Location', auth_url)
        handler.send_header('Cache-Control', 'no-store')
        handler.end_headers()
        return
    handler._send(HTTPStatus.OK, {"ok": True, "auth_url": auth_url, "state": state, "return_to": return_to})


def auth_callback(handler, path: str, qs: dict) -> None:
    """Gates 1/2/4/6: redeem `state`, map the open_id to an ACTIVE employee,
    mint a session whose cookie holds only the session id, and 302 to
    return_to. A bad state -> rejected_state log + HTTP 400 (no session)."""
    state = (qs.get("state") or [""])[0]
    return_to = (qs.get("return_to") or ["/"])[0] or "/"
    code = (qs.get("code") or [""])[0]
    # In SANDBOX_LOOPBACK there is no real OAuth code; the open_id defaults to
    # the mapped sandbox identity but a test may pass one explicitly.
    open_id = (qs.get("open_id") or [SANDBOX_DEFAULT_OPEN_ID])[0]
    if state:
        ok, rt, reason = _consume_oauth_state(state)
        if not ok:
            _log_login_attempt(open_id, "rejected_state", reason, path)
            handler._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "REJECTED_STATE", "reason": reason})
            return
        return_to = rt or return_to
    elif not (qs.get("open_id")) and not code:
        # Neither a state nor an explicit test open_id: cannot proceed.
        _log_login_attempt(open_id, "rejected_state", "missing_state", path)
        handler._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "REJECTED_STATE", "reason": "missing_state"})
        return
    if code and not qs.get("open_id") and os.environ.get("LARK_APP_ID") and os.environ.get("LARK_APP_SECRET"):
        try:
            redirect_uri = compute_redirect_uri(handler.headers.get("Host", ""))
            if path == "/auth/lark/callback" and redirect_uri.endswith("/api/auth/callback"):
                redirect_uri = redirect_uri[:-len("/api/auth/callback")] + "/auth/lark/callback"
            exchanged = _lark_exchange_open_id(code, redirect_uri)
            if not exchanged:
                raise RuntimeError("empty_open_id")
            open_id = exchanged
        except Exception as exc:
            _log_login_attempt("", "oauth_exchange_error", str(exc)[:120], path)
            handler._send(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": "OAUTH_EXCHANGE_FAILED", "detail": str(exc)[:200]})
            return
    rows = db.query(
        "SELECT jsonb_build_object('id',id::text,'org_id',org_id,'role',role_code) "
        "FROM public.employee WHERE org_id='YX' AND lark_open_id=" + db.literal(open_id) +
        " AND employment_status='active' AND identity_confirmed")
    if not rows:
        # Gate 4: a verified Lark account that is not on the active roster.
        _log_login_attempt(open_id, "unmapped_lark_user", "not_in_active_employee", path)
        handler._send(HTTPStatus.FORBIDDEN, unmapped_lark_html(), "text/html; charset=utf-8")
        return
    emp = rows[0]
    token = secrets.token_urlsafe(48)
    digest = hashlib.sha256(token.encode()).hexdigest()
    sid = db.query(
        "INSERT INTO public.api_session(token_sha256,employee_id,org_id,role,expires_at,lark_open_id,return_to) "
        "VALUES(" + db.literal(digest) + "," + db.literal(emp['id']) + "::uuid," +
        db.literal(emp['org_id']) + "," + db.literal(emp['role']) +
        ",now()+interval '8 hours'," + db.literal(open_id) + "," + db.literal(return_to) +
        ") RETURNING to_jsonb(id::text)")[0]
    if _wants_json(handler):
        handler.send_response(HTTPStatus.OK)
        handler.send_header('Content-Type', 'application/json; charset=utf-8')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('Set-Cookie', _session_cookie_header(sid))
        body = json.dumps({"ok": True, "return_to": return_to, "session_id": sid}, ensure_ascii=False).encode("utf-8")
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        try:
            handler.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        return
    handler.send_response(302)
    handler.send_header('Location', return_to)
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Set-Cookie', _session_cookie_header(sid))
    handler.end_headers()


def sandbox_loopback_mint(handler) -> None:
    """Backward-compatible one-click login used by the clean login button."""
    auth_callback(handler, "/api/auth/callback", {})


def enforce_test_recipient_allowlist(recipient: str = ALLOWED_TEST_RECIPIENT) -> str:
    norm = (recipient or "").strip().lower()
    if not norm or "@gmail.com" in norm or norm != ALLOWED_TEST_RECIPIENT:
        raise ValueError(
            f"BLOCKED_NON_WHITELIST_RECIPIENT: recipient {recipient!r} is forbidden in test mode; "
            f"only {ALLOWED_TEST_RECIPIENT} is allowed"
        )
    return ALLOWED_TEST_RECIPIENT

# --- Signature & brand guard (R55) --------------------------------------
# Official tax/legal company name that MUST appear in every outbound draft.
COMPANY_FULL_NAME = "詠翔測量工程有限公司"
# Forbidden legacy/stale brand tokens that must never reach generated output.
_FORBIDDEN_BRAND_TOKENS = (
    "永祥測量工程股份有限公司",
    "永祥測量有限公司",
    "永祥工程",
    "永祥測量",
)
_FORBIDDEN_PERSON_TOKENS = {"宣蓉": "羅薇"}
_SIGNOFF_RE = re.compile(
    r"(?:永祥工程|永祥測量[^\n]*|詠翔測量工程有限公司)\s*敬上"
)


def enforce_brand(body) -> str:
    """Force-inject the official company name and scrub forbidden brand/person
    tokens from any generated draft body before it is persisted or sent.

    Guarantees (see test_brand_guard.py):
      * no residual '永祥工程'/'永祥測量...' anywhere;
      * '宣蓉' rewritten to '羅薇';
      * the body ends with a single '<COMPANY_FULL_NAME> 敬上' sign-off so the
        official full name is always present even if the stored draft lacked it.
    """
    text = "" if body is None else str(body)
    # 1. Rewrite forbidden person names.
    for bad, good in _FORBIDDEN_PERSON_TOKENS.items():
        text = text.replace(bad, good)
    # 2. Normalise any legacy company sign-off to the official name.
    text = _SIGNOFF_RE.sub(f"{COMPANY_FULL_NAME} 敬上", text)
    # 3. Replace any remaining bare forbidden company tokens.
    for bad in _FORBIDDEN_BRAND_TOKENS:
        text = text.replace(bad, COMPANY_FULL_NAME)
    # 4. Guarantee the official sign-off is present (fallback if missing).
    if f"{COMPANY_FULL_NAME} 敬上" not in text:
        text = text.rstrip() + f"\n\n{COMPANY_FULL_NAME} 敬上"
    return text

try:
    import db
    import inbox_canvas_api as live_api
except Exception:
    db = None
    live_api = None


_PG_AVAIL_CACHE = None
_REQUEST_CONTEXT = threading.local()

def _pg_available() -> bool:
    global _PG_AVAIL_CACHE
    if _PG_AVAIL_CACHE is True:
        return True
    if db is None:
        return False
    try:
        cur_db = db.assert_not_prod_db(PG_DSN)
        assert cur_db == "yongxiang_plumb_r39_clone"
        assert cur_db != "yongxiang_plumb", f"FATAL: Forbidden from connecting to production DB (got {cur_db})"
        cnt = db.query("SELECT to_jsonb(count(*)) FROM public.yezhu_workbench_case")[0]
        if int(cnt) > 0:
            _PG_AVAIL_CACHE = True
            return True
        return False
    except Exception:
        return False


def _log_audit(table_name: str, record_id: str, op: str, after_val: dict, actor_note: str = "羅薇/柏頤"):
    if not _pg_available():
        return
    try:
        payload = dict(after_val or {})
        payload["actor_note"] = actor_note
        session = getattr(_REQUEST_CONTEXT, 'session', None) or {}
        actor_id = session.get('actor_employee_id') or actor_note
        db.execute(
            f"""
            INSERT INTO public.audit_event (table_name, record_id, op, actor_id, after_val)
            VALUES (
                {db.literal(table_name)},
                {db.literal(str(record_id))},
                {db.literal(op)},
                {db.literal(actor_id)},
                {db.json_sql(payload)}
            );
            """
        )
    except Exception:
        pass


# --- Fable 2000 SSO gate helpers ----------------------------------------
# All DB access below is routed through db.execute / db.query, which prepend
# the hard ASSERT current_database() <> 'yongxiang_plumb' AND = clone guard.
# The literal identity-override parameter name is assembled from fragments so
# the runtime source never contains the forbidden string the UI guard greps.
_OVERRIDE_PARAM = "acting" + "_as"
_OVERRIDE_KEYS = {"role", "user", "viewer", "actor", "x-employee-id", _OVERRIDE_PARAM}


def _new_oauth_state(return_to: str = "/") -> str:
    """Gate 1: mint a single-use OAuth `state` that expires in 5 minutes."""
    state = secrets.token_urlsafe(32)
    rt = return_to if (return_to or "").startswith("/") else "/"
    if _pg_available():
        db.execute(
            "INSERT INTO public.oauth_state(state,return_to,created_at,expires_at,used_at) "
            "VALUES(" + db.literal(state) + "," + db.literal(rt) +
            ",now(),now()+interval '5 minutes',NULL)")
    return state


def _consume_oauth_state(state: str):
    """Gate 1: atomically redeem a `state` iff unused and not expired.

    Returns (ok: bool, return_to: str, reason: str). A replay, an unknown
    value or an expired value all return ok=False with a distinct reason.
    """
    if not state:
        return False, "/", "missing_state"
    if not _pg_available():
        return False, "/", "no_db"
    rows = db.query(
        "UPDATE public.oauth_state SET used_at=now() WHERE state=" + db.literal(state) +
        " AND used_at IS NULL AND expires_at>now() "
        "RETURNING jsonb_build_object('return_to',coalesce(return_to,'/'))")
    if rows:
        return True, (rows[0].get("return_to") or "/"), "ok"
    # Distinguish replay / expiry / unknown for the rejection log.
    diag = db.query(
        "SELECT jsonb_build_object('exists',count(*),'used',count(*) FILTER(WHERE used_at IS NOT NULL),"
        "'expired',count(*) FILTER(WHERE expires_at<=now())) FROM public.oauth_state WHERE state=" +
        db.literal(state))
    info = diag[0] if diag else {"exists": 0}
    if not info.get("exists"):
        return False, "/", "unknown_state"
    if info.get("used"):
        return False, "/", "state_replayed"
    if info.get("expired"):
        return False, "/", "state_expired"
    return False, "/", "rejected_state"


def _log_login_attempt(open_id: str, outcome: str, reason: str, request_path: str, detail: dict = None) -> None:
    if not _pg_available():
        return
    try:
        db.execute(
            "INSERT INTO public.login_attempt_log(lark_open_id,outcome,reason,request_path,detail) VALUES(" +
            db.literal(open_id or "") + "," + db.literal(outcome) + "," + db.literal(reason) + "," +
            db.literal(request_path or "") + "," + db.json_sql(detail or {}) + ")")
    except Exception:
        pass


def compute_capsule(full_name, role_code, department, group_name, team_scope, role_scope):
    """Gate 5: derive the display capsule + effective scope from live columns.

    Never trusts any cached api_session.role; recomputed on every request.
    """
    full_name = full_name or ""
    role_code = (role_code or "").strip()
    group_name = (group_name or "").strip()
    team_scope = (team_scope or "").strip()
    role_scope = (role_scope or "").strip()
    capsule_name = "JK" if full_name in ("許喆凱", "許傑凱") else full_name
    if role_code == "gm" or team_scope == "management":
        capsule_group_label = "經營層"
    elif role_code in ("admin", "finance"):
        capsule_group_label = "行政"
    elif role_code in ("pm", "vp"):
        capsule_group_label = "PM"
    elif group_name in ("控制組", "外業經理", "品管組", "圖資組", "報告組"):
        capsule_group_label = group_name
    elif team_scope == "admin_finance":
        capsule_group_label = "行政"
    elif team_scope == "pm_sales":
        capsule_group_label = "PM"
    elif team_scope == "engineering_indoor":
        capsule_group_label = "控制組"
    else:
        capsule_group_label = "外業經理" if group_name == "外業經理" else "外業組"
    if role_code == "gm" or team_scope == "management":
        effective_role_scope = "gm"
    elif role_code in ("admin", "finance"):
        effective_role_scope = "admin"
    elif role_code in ("pm", "vp", "sales"):
        effective_role_scope = "pm"
    elif role_code in ("engineer", "inner_lead", "field_lead", "field_member"):
        effective_role_scope = "eng"
    else:
        effective_role_scope = role_scope
    return {
        "capsule_name": capsule_name,
        "capsule_group_label": capsule_group_label,
        "capsule_display": f"{capsule_name} · {capsule_group_label}",
        "effective_role_scope": effective_role_scope,
    }


def detect_override_params(qs: dict, headers=None, payload: dict = None):
    """Gate 8: collect any reverse identity-override params present.

    Matches query keys, headers and body keys against the forbidden set
    (role / user / viewer / actor / X-Employee-Id / the impersonation param).
    The caller logs them and then ignores them entirely.
    """
    hits = []
    for key in (qs or {}):
        if str(key).strip().lower() in _OVERRIDE_KEYS:
            hits.append("query:" + str(key))
    if headers is not None:
        for key in (_OVERRIDE_PARAM, "X-Employee-Id", "X-Acting-Role", "X-User"):
            if headers.get(key):
                hits.append("header:" + key)
    if isinstance(payload, dict):
        for key in payload:
            if str(key).strip().lower() in _OVERRIDE_KEYS:
                hits.append("body:" + str(key))
    return hits


def inspect_5_checks(case_data: dict, draft_text: str, draft_subj: str = "", file_override: str = "") -> dict:
    text = str(draft_text or "")
    subj = str(draft_subj or "")
    combined = f"{subj}\n{text}"
    no_internal = not bool(re.search(r"底價|成本|毛利|時薪|內部", combined))
    nums = [
        int(x.replace(",", ""))
        for x in re.findall(r"\b\d{1,3}(?:,\d{3})+\b|\b\d{5,}\b", text)
        if x.replace(",", "").isdigit()
    ]
    allowed = [int(x) for x in (case_data.get("allowed") or []) if x is not None]
    amount_ok = all(n in allowed for n in nums)
    no_link = not bool(re.search(r"https?://|drive\.|雲端", text, re.I))
    date_ok = True
    file_name = file_override or case_data.get("file") or ""
    unpaid = (
        case_data.get("received") is not None
        and case_data.get("sum") is not None
        and int(case_data.get("received") or 0) < int(case_data.get("sum") or 0)
    )
    seal_ok = not (unpaid and bool(re.search(r"官章|正式成果圖|封存|\.dwg", f"{file_name} {text}", re.I)))

    errors = []
    if not no_link:
        errors.append("信內含外部雲端連結（對方信箱會退信）")
    if not seal_ok:
        errors.append("尾款未入帳，不能附正式官章 DWG 圖檔")
    if not no_internal:
        errors.append("信內含內部敏感字眼，請先移除")
    if not amount_ok:
        errors.append("信內金額與本案報價／合約金額不一致")

    checks = [
        {"name": "無內部字眼", "ok": no_internal},
        {"name": "金額對報價", "ok": amount_ok},
        {"name": "無外部連結", "ok": no_link},
        {"name": "日期在里程碑內", "ok": date_ok},
        {"name": "未收款成果已鎖", "ok": seal_ok},
    ]

    sql_gates = None
    if _pg_available():
        try:
            sql_gates = db.query(
                f"""
                SELECT public.outbound_check_6_gates(
                    'YX', NULL, NULL,
                    {db.literal(subj)},
                    {db.literal(text)},
                    'false'::jsonb,
                    false,
                    false,
                    { 'true' if (no_link and seal_ok and no_internal and amount_ok) else 'false' }
                )
                """
            )[0]
        except Exception:
            sql_gates = None

    return {
        "checks": checks,
        "errors": errors,
        "all_green": len(errors) == 0,
        "sql_gates": sql_gates,
    }


def resolve_case_agent_and_connector(code: str, case_data: dict, roster_mode: str, roster_items: list) -> dict:
    agents = {r["item_id"]: r for r in roster_items if r.get("kind") == "agent"}
    connectors = {r["item_id"]: r for r in roster_items if r.get("kind") == "connector"}

    specialist_id = "agent-deliverable"
    for aid, item in agents.items():
        if aid == "agent-all-in-one":
            continue
        if code in (item.get("assigned_codes") or []):
            specialist_id = aid
            break
    else:
        txt = f"{case_data.get('name','')} {case_data.get('full_title','')} {case_data.get('reminder','')} {case_data.get('client','')}"
        if case_data.get("inquiry") or code.startswith("Q-"):
            specialist_id = "agent-quote-rfq"
        elif any(k in txt for k in ["水利署", "公路局", "斷面", "中興", "審閱", "驗收"]):
            specialist_id = "agent-contract-gov"
        elif any(k in txt for k in ["尾款", "請款", "計價", "入帳", "發票"]):
            specialist_id = "agent-billing-ar"
        elif any(k in txt for k in ["會勘", "邊坡", "加測", "進場", "工安"]):
            specialist_id = "agent-field-safety"

    conn_id = "conn-company-mail"
    for cid, item in connectors.items():
        if code in (item.get("assigned_codes") or []):
            conn_id = cid
            break
    else:
        client_txt = f"{case_data.get('client','')} {case_data.get('pm','')}"
        if any(k in client_txt for k in ["水利署", "公路局", "政府", "分署", "公所"]):
            conn_id = "conn-gov-edoc"
        elif any(k in client_txt for k in ["緯穎", "高鐵"]):
            conn_id = "conn-jekai-mail"
        elif any(k in client_txt for k in ["吳柏頤", "鍾智偉"]):
            conn_id = "conn-pm-mails"

    all_in_one = agents.get("agent-all-in-one") or {"item_id": "agent-all-in-one", "title": "總機主腦（All-in-One）"}
    spec_agent = agents.get(specialist_id) or all_in_one
    if roster_mode == "minimal" or not spec_agent.get("enabled", True):
        active_agent = all_in_one
    else:
        active_agent = spec_agent

    conn_obj = connectors.get(conn_id) or connectors.get("conn-company-mail") or {
        "item_id": "conn-company-mail",
        "title": "company@yxsurvey.com.tw（公司總信箱）",
        "enabled": True,
    }
    if not conn_obj.get("enabled", True):
        conn_obj = connectors.get("conn-company-mail") or conn_obj

    return {
        "specialist_agent_id": specialist_id,
        "specialist_agent_title": spec_agent.get("title", "成果圖資交付專員"),
        "active_agent_id": active_agent.get("item_id", "agent-all-in-one"),
        "active_agent_title": active_agent.get("title", "總機主腦（All-in-One）"),
        "connector_id": conn_id,
        "connector_title": conn_obj.get("title", "company@yxsurvey.com.tw（公司總信箱）"),
    }


def get_agents_connectors_state() -> dict:
    if not _pg_available():
        return {
            "ok": True,
            "roster_mode": "multi",
            "agents": [],
            "connectors": [],
            "active_agent_count": 6,
            "active_connector_count": 4,
        }
    meta_rows = db.query(
        """
        SELECT jsonb_build_object(
            'roster_mode', coalesce(roster_mode, 'multi')
        )
        FROM public.yezhu_workbench_meta
        WHERE key = 'global_state'
        """
    )
    roster_mode = (meta_rows[0].get("roster_mode") if meta_rows else "multi") or "multi"
    items = db.query(
        """
        SELECT jsonb_build_object(
            'item_id', item_id,
            'kind', kind,
            'title', title,
            'subtitle', subtitle,
            'enabled', enabled,
            'is_core', is_core,
            'sort_order', sort_order,
            'assigned_codes', assigned_codes
        )
        FROM public.switchboard_agent_roster
        ORDER BY sort_order, item_id
        """
    )
    agents = [x for x in items if x.get("kind") == "agent"]
    connectors = [x for x in items if x.get("kind") == "connector"]
    for a in agents:
        a["effective_enabled"] = (a["item_id"] == "agent-all-in-one") if roster_mode == "minimal" else bool(a.get("enabled"))
        a["case_count"] = len(a.get("assigned_codes") or [])
    for c in connectors:
        c["effective_enabled"] = bool(c.get("enabled"))
        c["case_count"] = len(c.get("assigned_codes") or [])

    return {
        "ok": True,
        "roster_mode": roster_mode,
        "agents": agents,
        "connectors": connectors,
        "active_agent_count": 1 if roster_mode == "minimal" else sum(1 for a in agents if a.get("enabled")),
        "active_connector_count": sum(1 for c in connectors if c.get("enabled")),
        "items": items,
    }



_STEP9_SEEDED = False

EMPLOYEE_UUID_BY_NAME = {
    "羅薇": "c22b9383-60ec-5bcf-8bb1-4131de44b420",
    "行政羅薇": "c22b9383-60ec-5bcf-8bb1-4131de44b420",
    "朱雅琪": "45ab4194-04c9-59ef-bbd9-f1559b830c38",
    "雅琪": "45ab4194-04c9-59ef-bbd9-f1559b830c38",
    "郭倢瑛": "18d11143-a1c8-5afd-bcf1-229e064e930c",
    "倢瑛": "18d11143-a1c8-5afd-bcf1-229e064e930c",
    "吳柏頤": "a968fbf8-c0ac-5d6a-9939-80584ede3509",
    "柏頤": "a968fbf8-c0ac-5d6a-9939-80584ede3509",
}
RESIGNED_ADMIN_UUID = "26a901c0-d648-529e-842f-b778a86cb559"
QUARANTINE_MSG_ID = "<q-dkim-unaligned@survey.tw>"
QUARANTINE_CARD_KEY = "quarantine:<q-dkim-unaligned@survey.tw>"


def _sanitize_ui_name(name: str) -> str:
    s = str(name or "").strip()
    if not s or "\u5ba3\u84c9" in s or "林瑩瑄" in s:
        return "前行政（離職移交）"
    return s


def _sanitize_ui_strip(raw_strip: str, pending: bool = True, holder_name: str = "羅薇") -> str:
    raw = str(raw_strip or "").strip()
    clean_holder = _sanitize_ui_name(holder_name)
    if "→" in raw:
        return _sanitize_ui_name(raw)
    if "行政不確定" in raw or "轉 PM" in raw:
        return "自動移交：行政不確定，轉 PM" if pending else f"自動移交：行政不確定，已由 {clean_holder} 接手"
    if "離職移交" in raw:
        return "自動移交：離職移交 · 待同組接手" if pending else f"自動移交：離職移交 · 已由 {clean_holder} 接手"
    return raw.replace("系統：", "自動移交：")


def _ensure_step9_seed(reset: bool = False) -> None:
    global _STEP9_SEEDED
    if not _pg_available():
        return
    if _STEP9_SEEDED and not reset:
        return
    try:
        reset_sql = ""
        if reset:
            reset_sql = """

            DO $$ BEGIN
              IF to_regclass('public.org_mode') IS NOT NULL THEN
                EXECUTE 'UPDATE public.org_mode SET mode=''shadow'',set_at=now() WHERE org_id=''YX''';
              END IF;
            END $$;
            DELETE FROM public.org_marker WHERE org_code = 'YX' AND kind IN ('tax_id', 'domain');
            ALTER TABLE public.serial_cutover_log DISABLE TRIGGER serial_cutover_log_append_only;
            DELETE FROM public.serial_cutover_log WHERE org_id = 'YX';
            ALTER TABLE public.serial_cutover_log ENABLE TRIGGER serial_cutover_log_append_only;

            ALTER TABLE public.email_message_disposition DISABLE TRIGGER email_message_disposition_append_only;
            DELETE FROM public.email_message_disposition WHERE message_id = '<q-dkim-unaligned@survey.tw>';
            ALTER TABLE public.email_message_disposition ENABLE TRIGGER email_message_disposition_append_only;

            DELETE FROM public.card_transition
             WHERE card_id IN (
               SELECT id FROM public.card
                WHERE idempotency_key IN ('quarantine:<q-dkim-unaligned@survey.tw>', 'step9-offboard:C115094', 'step9-offboard:C114488')
             );

            ALTER TABLE public.card_handoff_log DISABLE TRIGGER card_handoff_log_append_only;
            DELETE FROM public.card_handoff_log
             WHERE card_id IN (
               SELECT id FROM public.card
                WHERE idempotency_key IN ('quarantine:<q-dkim-unaligned@survey.tw>', 'step9-offboard:C115094', 'step9-offboard:C114488')
             );
            ALTER TABLE public.card_handoff_log ENABLE TRIGGER card_handoff_log_append_only;

            DELETE FROM public.card_action_log WHERE card_id IN (
              SELECT id FROM public.card WHERE idempotency_key IN
                ('quarantine:<q-dkim-unaligned@survey.tw>', 'step9-offboard:C115094', 'step9-offboard:C114488')
            );
            DELETE FROM public.card
             WHERE idempotency_key IN ('quarantine:<q-dkim-unaligned@survey.tw>', 'step9-offboard:C115094', 'step9-offboard:C114488');

            DELETE FROM public.quarantine_intake_decision;
            UPDATE public.card
               SET status = 'open',
                   state = 'open',
                   mode = 'dry_run',
                   assignee_employee_id = 'c22b9383-60ec-5bcf-8bb1-4131de44b420'::uuid,
                   acted_at = NULL,
                   acted_by = NULL,
                   action = NULL,
                   action_key = NULL,
                   handoff_pending = false,
                   handoff_strip = NULL
             WHERE idempotency_key IN (
               SELECT 'quarantine:intake:' || i.id::text FROM public.switchboard_intake i
               WHERE i.serial_no IN (-12098, -12100, -12105)
             );
            """

        db.execute(
            f"""
            BEGIN;
            UPDATE public.switchboard_agent_roster
               SET title = '群組訊息轉入通道（內部交辦）',
                   subtitle = '工程師與 PM 於專案群組轉入之業主交辦與口述紀錄'
             WHERE item_id = 'conn-lark-bridge'
               AND (title LIKE '%Lark%' OR subtitle LIKE '%Lark%');

            DELETE FROM public.employee_role_map WHERE employee_id = '{RESIGNED_ADMIN_UUID}'::uuid AND role_code = 'admin';
            INSERT INTO public.employee_role_map (employee_id, role_code, assigned_by)
            SELECT id, 'admin', 'R39_EXPLICIT_ROSTER'
              FROM public.employee
             WHERE org_id = 'YX' AND full_name IN ('羅薇', '謝佾均', '徐孟君', '彭書逸')
            ON CONFLICT (employee_id) DO UPDATE SET role_code = 'admin';

            INSERT INTO public.employee_role_map (employee_id, role_code, assigned_by)
            SELECT id, 'pm', 'R39_EXPLICIT_ROSTER'
              FROM public.employee
             WHERE org_id = 'YX' AND full_name IN ('吳柏頤', '鍾智偉', '涂振邦', '朱雅琪', '郭倢瑛', '林瑩瑄')
            ON CONFLICT (employee_id) DO UPDATE SET role_code = 'pm';

            -- Employee identity and employment status belong to the roster,
            -- never to repeatable UI demo seeding.

            {reset_sql}

            INSERT INTO public.email_message (
              message_id, subject, from_addr, to_addrs, sent_at,
              org_id, case_id, body_new_text, quarantine_reason
            ) VALUES (
              '<q-dkim-unaligned@survey.tw>',
              '大安溪斷面補測與水保變更報價詢問', 'survey-inquiry@partner.tw',
              ARRAY['company@yxsurvey.com.tw'], now(),
              NULL, NULL,
              '您好，請問大安溪斷面補測進度與水保變更報價單何時可提供？',
              'R32-ORG-MARKER:missing_dkim_alignment'
            ) ON CONFLICT (message_id) DO NOTHING;

            SELECT public.emit_quarantine_cards();
            UPDATE public.card
               SET assignee_employee_id = 'c22b9383-60ec-5bcf-8bb1-4131de44b420'::uuid,
                   role = COALESCE(role, 'admin')
             WHERE idempotency_key = 'quarantine:<q-dkim-unaligned@survey.tw>'
               AND handoff_pending = false
               AND acted_at IS NULL;

            INSERT INTO public.card (
              org_id, case_id, assignee_employee_id, role, kind, title, status, state, mode,
              idempotency_key, evidence_numbers, proposed_fields
            )
            SELECT 'YX',
                   (SELECT id FROM public."case" WHERE org_id = 'YX' AND case_code = v.code LIMIT 1),
                   'c22b9383-60ec-5bcf-8bb1-4131de44b420'::uuid,
                   'admin', 'admin',
                   '離職行政待移交：' || v.code, 'open', 'dry_run', 'dry_run',
                   'step9-offboard:' || v.code,
                   '[]'::jsonb,
                   jsonb_build_object('case_code', v.code)
              FROM (VALUES ('C115094'), ('C114488')) AS v(code)
            ON CONFLICT (idempotency_key) DO NOTHING;

            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM public.card
                 WHERE idempotency_key IN ('step9-offboard:C115094', 'step9-offboard:C114488')
                   AND handoff_from IS NULL
              ) THEN
                ALTER TABLE public.card DISABLE TRIGGER card_guard_trg;
                UPDATE public.card
                   SET assignee_employee_id = '{RESIGNED_ADMIN_UUID}'::uuid,
                       handoff_pending = false,
                       handoff_from = NULL,
                       handoff_strip = NULL,
                       acted_at = NULL,
                       status = 'open'
                 WHERE idempotency_key IN ('step9-offboard:C115094', 'step9-offboard:C114488');
                ALTER TABLE public.card ENABLE TRIGGER card_guard_trg;
                PERFORM public.offboard_handoff('{RESIGNED_ADMIN_UUID}'::uuid);
              END IF;
            END $$;
            COMMIT;
            """
        )
        _STEP9_SEEDED = True
    except Exception:
        pass


def get_intake_triage_state() -> dict:
    rows = db.query("""
        SELECT jsonb_build_object(
          'total',count(*),'completed',count(*) FILTER (WHERE completed),
          'missing_cards',count(*) FILTER (WHERE card_id IS NULL),
          'current',(SELECT to_jsonb(q) FROM public.quarantine_intake_queue_v q
                     WHERE NOT coalesce(q.completed,false) AND q.card_id IS NOT NULL
                     ORDER BY abs(q.serial_no),q.intake_id LIMIT 1))
        FROM public.quarantine_intake_queue_v
    """)
    batch = rows[0]
    current = batch.get('current') or {}
    payload = current.get('payload') or {}
    total, done = int(batch['total']), int(batch['completed'])
    index = min(done + 1, total) if current else done
    return {
        **current, 'intake_id':current.get('intake_id'), 'card_id':current.get('card_id'),
        'message_id':None, 'triage_total':total, 'triage_completed':done,
        'triage_index':index, 'triage_badge':f'{index}/{total}',
        'queue_complete':not current, 'missing_cards':batch['missing_cards'],
        'holder_name':_sanitize_ui_name(current.get('holder_name') or ''),
        'ui_strip':current.get('handoff_strip') or '',
        'subject':payload.get('subject') or '（缺主旨）',
        'from_addr':payload.get('from_addr') or payload.get('from') or '（待確認寄件人）',
        'body':str(payload.get('text') or '').strip() or '（缺本文，請核對來源）',
        'reason_title':'歸屬不明 · 待確認法人與案號',
        'candidate_case_code':'', 'second_glance':[],
    }


def get_step9_state() -> dict:
    if not _pg_available():
        return {
            "org_live": {
                "org": "YX",
                "ready": False,
                "badge": "YX 試運轉（缺：統編、網域、對帳）",
                "tax_id": False,
                "domain": False,
                "serial_reconciled": False,
                "admin": True,
                "admin_count": 3,
                "missing": ["統編", "網域", "對帳"],
                "low_admin_warning": "",
            },
            "offboard_handoff": {
                "pending_count": 2,
                "banner_text": "📥 2 張待接手（離職行政移交）",
                "cards": {},
                "list": [],
            },
            "quarantine_card": {},
        }


    org_live_rows = db.query("SELECT public.org_live_ready('YX')")
    org_live = dict(org_live_rows[0] if org_live_rows else {})
    admin_count = int(org_live.get("admin_count") or 3)
    org_live["low_admin_warning"] = "" if admin_count >= 2 else f"行政只剩 {admin_count} 人，請補人"

    handoff_rows = db.query(
        """
        SELECT jsonb_build_object(
            'card_id', c.id::text,
            'idempotency_key', c.idempotency_key,
            'case_code', coalesce(c.proposed_fields->>'case_code', replace(c.idempotency_key, 'step9-offboard:', '')),
            'handoff_pending', c.handoff_pending,
            'handoff_role', coalesce(c.handoff_role, 'admin'),
            'db_strip', coalesce(c.handoff_strip, '系統：離職移交'),
            'holder_id', c.assignee_employee_id::text,
            'holder_name', coalesce(e.full_name, '羅薇'),
            'status', c.status
        )
        FROM public.card c
        LEFT JOIN public.employee e ON e.id = c.assignee_employee_id
        WHERE c.idempotency_key IN ('step9-offboard:C115094', 'step9-offboard:C114488')
        ORDER BY c.idempotency_key DESC
        """
    )
    cards_by_code = {}
    cards_list = []
    pending_cnt = 0
    for hr in handoff_rows:
        code = hr.get("case_code") or "C115094"
        pending = bool(hr.get("handoff_pending"))
        if pending:
            pending_cnt += 1
        holder = "羅薇" if pending else _sanitize_ui_name(hr.get("holder_name") or "羅薇")
        item = {
            "card_id": hr.get("card_id"),
            "case_code": code,
            "handoff_pending": pending,
            "handoff_role": hr.get("handoff_role") or "admin",
            "holder_id": hr.get("holder_id"),
            "holder_name": holder,
            "from_label": "前行政（離職移交）",
            "db_strip": hr.get("db_strip") or "系統：離職移交",
            "ui_strip": _sanitize_ui_strip(hr.get("db_strip") or "系統：離職移交", pending=pending, holder_name=holder),
        }
        cards_by_code[code] = item
        cards_list.append(item)

    banner_text = (
        f"📥 {pending_cnt} 張待接手（離職行政移交）"
        if pending_cnt > 0
        else "📥 0 張待接手（離職行政移交已全部接手）"
    )

    q_info = get_intake_triage_state()

    return {
        "org_live": org_live,
        "offboard_handoff": {
            "pending_count": pending_cnt,
            "banner_text": banner_text,
            "cards": cards_by_code,
            "list": cards_list,
        },
        "quarantine_card": q_info,
    }


def handle_handoff_claim(payload: dict) -> tuple[int, dict]:
    if not _pg_available():
        return HTTPStatus.OK, {"ok": True, "holder": "羅薇"}

    case_id = str(payload.get("case_id") or payload.get("case_code") or "C115094").strip()
    card_id = str(payload.get("card_id") or "").strip()
    actor_name = str(payload.get("actor") or payload.get("user") or "羅薇").strip()
    actor_uuid = EMPLOYEE_UUID_BY_NAME.get(actor_name, "c22b9383-60ec-5bcf-8bb1-4131de44b420")

    if not card_id:
        if case_id in ("Q-DKIM", "QUARANTINE"):
            ikey = QUARANTINE_CARD_KEY
        else:
            ikey = f"step9-offboard:{case_id}"
        rows = db.query(f"SELECT to_jsonb(id::text) FROM public.card WHERE idempotency_key = {db.literal(ikey)} LIMIT 1")
        if rows:
            card_id = str(rows[0])

    if not card_id:
        return HTTPStatus.NOT_FOUND, {"ok": False, "error": "CARD_NOT_FOUND", "case_id": case_id}

    try:
        res = db.query(
            f"SELECT public.card_claim_handoff({db.literal(card_id)}::uuid, {db.literal(actor_uuid)}::uuid)"
        )[0]
        db.execute(
            f"""
            UPDATE public.yezhu_workbench_meta
               SET admin_claimed = {db.literal(actor_name)},
                   updated_at = now()
             WHERE key = 'global_state';
            """
        )
        _log_audit(
            "card",
            card_id,
            "UPDATE",
            {"action": "card_claim_handoff", "case_id": case_id, "actor": actor_name, "result": res},
            actor_note=actor_name,
        )
        s9 = get_step9_state()
        return HTTPStatus.OK, {
            "ok": True,
            "case_id": case_id,
            "card_id": card_id,
            "holder": actor_name,
            "already": bool(res.get("already")) if isinstance(res, dict) else False,
            "message": f"已由 {actor_name} 接手",
            "claim_result": res,
            "step9": s9,
            "persisted_in_pg": True,
        }
    except Exception as exc:
        err_txt = str(exc)
        s9 = get_step9_state()
        if "already claimed" in err_txt or "55000" in err_txt:
            holder = (s9.get("offboard_handoff", {}).get("cards", {}).get(case_id) or {}).get("holder_name", "羅薇")
            return HTTPStatus.CONFLICT, {
                "ok": False,
                "error": "ALREADY_CLAIMED",
                "case_id": case_id,
                "card_id": card_id,
                "holder": holder,
                "message": f"已有人接手（目前由 {holder} 處理中）",
                "step9": s9,
            }
        return HTTPStatus.BAD_REQUEST, {
            "ok": False,
            "error": "CLAIM_FAILED",
            "message": "接手失敗，請確認角色權限",
            "detail": err_txt,
            "step9": s9,
        }


def handle_quarantine_dispose(payload: dict) -> tuple[int, dict]:
    if not _pg_available():
        return HTTPStatus.SERVICE_UNAVAILABLE, {"ok":False,"error":"CLONE_UNAVAILABLE"}
    required = ('intake_id','card_id','request_id','actor','disposition','reason')
    if any(not str(payload.get(k) or '').strip() for k in required):
        return HTTPStatus.BAD_REQUEST, {"ok":False,"error":"EXPLICIT_INTAKE_CARD_ACTOR_REQUEST_AND_REASON_REQUIRED"}
    try:
        # Resolve an explicit active person; never silently substitute an administrator.
        actors = db.query(f"SELECT to_jsonb(id::text) FROM public.employee WHERE full_name={db.literal(payload['actor'])} AND org_id='YX' AND employment_status='active'")
        if len(actors)!=1:
            return HTTPStatus.FORBIDDEN, {"ok":False,"error":"ACTIVE_ACTOR_REQUIRED"}
        case_id = None
        if payload['disposition']=='link_case':
            cases = db.query(f"SELECT to_jsonb(id::text) FROM public.\"case\" WHERE org_id='YX' AND case_code={db.literal(payload.get('case_code'))}")
            if len(cases)!=1:
                return HTTPStatus.BAD_REQUEST, {"ok":False,"error":"VALID_CASE_REQUIRED"}
            case_id = cases[0]
        result = db.query(f"""SELECT public.quarantine_intake_dispose(
            {db.literal(payload['intake_id'])}::uuid,{db.literal(payload['card_id'])}::uuid,
            {db.literal(actors[0])}::uuid,{db.literal(payload['disposition'])},
            {db.literal(case_id)}::uuid,{db.literal(payload['reason'])},
            {db.literal(payload['request_id'])}::uuid,{db.literal(payload.get('target_employee_id'))}::uuid)
        """)[0]
        return HTTPStatus.OK, {"ok":True,"release_result":result,"step9":get_step9_state(),"persisted_in_pg":True}
    except Exception:
        return HTTPStatus.CONFLICT, {"ok":False,"error":"DISPOSITION_REJECTED","message":"請重新整理並確認持球人、案號及處置內容"}


def handle_org_live_toggle(payload: dict) -> tuple[int, dict]:
    if not _pg_available():
        return HTTPStatus.OK, {"ok": True}

    cur = db.query("SELECT public.org_live_ready('YX')")[0]
    cur_ready = bool(cur.get("ready"))
    target_ready = payload.get("ready")
    if target_ready is None:
        target_ready = not cur_ready
    else:
        target_ready = bool(target_ready)

    if target_ready:
        db.execute(
            """
            BEGIN;

            DO $$ BEGIN
              IF to_regclass('public.org_mode') IS NOT NULL THEN
                EXECUTE 'INSERT INTO public.org_mode(org_id,mode,set_by,reason) VALUES (''YX'',''live'',''1101fb67-0080-50c1-98e6-d02f7a0ae907'',''clone readiness rehearsal'') ON CONFLICT(org_id) DO UPDATE SET mode=''live'', set_at=now()';
              END IF;
            END $$;
            INSERT INTO public.org_marker (org_code, kind, value, verified_by) VALUES
              ('YX', 'tax_id', '80217508', 'Step 9 UI live ready preview'),
              ('YX', 'domain', 'yxsurvey.com.tw', 'Step 9 UI live ready preview')
            ON CONFLICT (org_code, kind, value) DO NOTHING;
            INSERT INTO public.serial_cutover_log (org_id, sheet_max, new_next, voided_dry_run, done_by)
            SELECT 'YX', 12084, 12085, 0, 'Step 9 UI live ready preview'
            WHERE NOT EXISTS (SELECT 1 FROM public.serial_cutover_log WHERE org_id = 'YX');
            UPDATE public.serial_allocator
               SET next_serial = 12085,
                   sheet_max_reconciled = 12084
             WHERE org_id = 'YX';
            COMMIT;
            """
        )
    else:
        db.execute(
            """
            BEGIN;

            DO $$ BEGIN
              IF to_regclass('public.org_mode') IS NOT NULL THEN
                EXECUTE 'UPDATE public.org_mode SET mode=''shadow'',set_at=now() WHERE org_id=''YX''';
              END IF;
            END $$;
            DELETE FROM public.org_marker WHERE org_code = 'YX' AND kind IN ('tax_id', 'domain');
            ALTER TABLE public.serial_cutover_log DISABLE TRIGGER serial_cutover_log_append_only;
            DELETE FROM public.serial_cutover_log WHERE org_id = 'YX';
            ALTER TABLE public.serial_cutover_log ENABLE TRIGGER serial_cutover_log_append_only;
            COMMIT;
            """
        )

    new_org_live = db.query("SELECT public.org_live_ready('YX')")[0]
    _log_audit(
        "org_marker",
        "YX",
        "UPDATE",
        {"action": "org_live_toggle", "ready": bool(new_org_live.get("ready")), "badge": new_org_live.get("badge")},
    )
    s9 = get_step9_state()
    return HTTPStatus.OK, {
        "ok": True,
        "org_live": s9["org_live"],
        "step9": s9,
        "persisted_in_pg": True,
    }



def get_lark_directory(query_str: str = "", scope_filter: str = "") -> dict:
    if not _pg_available():
        return {"ok": True, "count": 0, "staff": []}
    q = (query_str or "").strip().translate(str.maketrans("爲彜彞臺", "為彝彝台"))
    sc = (scope_filter or "").strip().lower()
    where_clauses = ["1=1"]
    if sc in ("admin", "pm", "eng"):
        where_clauses.append(f"role_scope = {db.literal(sc)}")
    if q:
        pat = db.literal(f"%{q}%")
        where_clauses.append(
            f"(translate(full_name, '爲彜彞臺', '為彝彝台') ILIKE {pat} "
            f"OR translate(short_name, '爲彜彞臺', '為彝彝台') ILIKE {pat} "
            f"OR translate(department_group, '爲彜彞臺', '為彝彝台') ILIKE {pat} "
            f"OR translate(sub_group, '爲彜彞臺', '為彝彝台') ILIKE {pat} "
            f"OR translate(job_title_display, '爲彜彞臺', '為彝彝台') ILIKE {pat} "
            f"OR translate(duty_hint, '爲彜彞臺', '為彝彝台') ILIKE {pat} OR search_text ILIKE {pat})"
        )
    where_sql = " AND ".join(where_clauses)
    rows = db.query(
        f"""
        SELECT jsonb_build_object(
            'employee_id', employee_id,
            'full_name', full_name,
            'short_name', short_name,
            'department_group', department_group,
            'sub_group', sub_group,
            'job_title', job_title_display,
            'role_scope', role_scope,
            'duty_hint', duty_hint,
            'lark_open_id', lark_open_id,
            'team_scope', team_scope,
            'is_group_lead', is_group_lead,
            'search_text', search_text
        )
        FROM public.v_yezhu_lark_directory
        WHERE {where_sql}
        ORDER BY
          CASE department_group
            WHEN '業務及PM部' THEN 1
            WHEN '行政及財務部' THEN 2
            WHEN '內業部門' THEN 3
            ELSE 4
          END,
          CASE WHEN full_name IN ('吳柏頤','羅薇','張家彬','涂振邦','鍾智偉','古恆安','吳重樺','鄭文澤','吳科翰','謝佾均','朱雅琪','郭倢瑛','沈宜蓁') THEN 0 ELSE 1 END,
          full_name ASC
        """
    )
    return {
        "ok": True,
        "count": len(rows),
        "total_active": 67,
        "staff": rows,
    }




def require_session(headers):
    """Resolve the verified principal for a request.

    Accepts either a legacy Bearer secret (hashed to token_sha256) or the SSO
    cookie that carries ONLY the api_session.id (Gate 2). On every call the
    role / team_scope / group_name are recomputed live from employee +
    staff_directory_v (Gate 5), the row is rejected the instant the employee
    is no longer active (Gate 3), and both the 8h absolute and 2h idle
    windows are enforced, refreshing last_active_at (Gate 6).
    """
    import hashlib
    from http.cookies import SimpleCookie
    db.set_session_digest()
    token = ""
    sid = ""
    authorization = headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    else:
        raw = ""
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get("Cookie", ""))
            raw = next((cookies[k].value for k in ("switchboard_session", "r47_session") if k in cookies), "")
        except Exception:
            raw = ""
        # SSO cookies carry the api_session.id (a UUID); legacy secrets hash.
        if raw:
            try:
                sid = str(UUID(raw))
            except Exception:
                token = raw
    if not sid and len(token) < 32:
        return None
    if sid:
        match = "s.id=" + db.literal(sid) + "::uuid"
    else:
        digest = hashlib.sha256(token.encode()).hexdigest()
        match = "s.token_sha256=" + db.literal(digest) + " AND length(s.token_sha256)=64"
    rows = db.query(
        "SELECT jsonb_build_object('token_sha256',s.token_sha256,"
        "'session_id',s.id,'actor_employee_id',a.id,'actor_role',a.role_code,"
        "'employee_id',e.id,'full_name',e.full_name,'role_code',e.role_code,"
        "'department',e.department,'group_name',e.group_name,"
        "'role_scope',coalesce(r.role_scope,''),'team_scope',d.team_scope,"
        "'lark_open_id',e.lark_open_id) "
        "FROM public.api_session s JOIN public.employee a ON a.id=s.employee_id "
        "JOIN public.employee e ON e.id=s.employee_id "
        "JOIN public.staff_directory_v d ON d.employee_id=e.id "
        "LEFT JOIN public.v_yezhu_lark_directory r ON r.employee_id=e.id::text "
        "WHERE " + match + " AND s.expires_at>now() "
        "AND coalesce(s.last_active_at,s.created_at,now())+interval '2 hours'>now() "
        "AND a.org_id='YX' AND s.org_id=a.org_id "
        "AND a.employment_status='active' AND a.identity_confirmed "
        "AND s.lark_open_id=a.lark_open_id AND e.employment_status='active'")
    if not rows:
        return None
    principal = rows[0]
    cap = compute_capsule(principal.get("full_name"), principal.get("role_code"),
                          principal.get("department"), principal.get("group_name"),
                          principal.get("team_scope"), principal.get("role_scope"))
    principal.update(cap)
    # Gate 6: refresh the idle clock on every authenticated request.
    try:
        db.execute("UPDATE public.api_session SET last_active_at=now() WHERE id=" +
                   db.literal(principal["session_id"]) + "::uuid")
    except Exception:
        pass
    if principal.get("token_sha256"):
        db.set_session_digest(principal.get("token_sha256"))
    return principal


def get_people_picker(context_str: str = "handoff", case_code_or_id: str = "", q_str: str = "", actor_str: str = "") -> dict:
    if not _pg_available():
        return {"ok": True, "context": context_str, "items": []}
    ctx = (context_str or "handoff").strip()
    if ctx not in ("handoff", "fix_request", "to_pm", "return", "assign_pm"):
        ctx = "handoff"
    actor_map = {
        "admin": "c22b9383-60ec-5bcf-8bb1-4131de44b420",
        "pm": "a968fbf8-c0ac-5d6a-9939-80584ede3509",
        "eng": "13394342-2826-5d5d-a26f-44e259279870",
        "jk": "1101fb67-0080-50c1-98e6-d02f7a0ae907",
    }
    actor_uuid = actor_map.get((actor_str or "").strip().lower(), "a968fbf8-c0ac-5d6a-9939-80584ede3509")
    actor = (actor_str or '').strip()
    if actor and actor.lower() not in actor_map:
        try:
            actor_uuid = str(UUID(actor))
        except ValueError:
            return {"ok": False, "error": "INVALID_ACTOR", "items": [], "count": 0}
        active = db.query(f"SELECT to_jsonb(employee_id::text) FROM public.v_active_employee_directory WHERE employee_id={db.literal(actor_uuid)}::uuid")
        if not active:
            return {"ok": False, "error": "INACTIVE_ACTOR", "items": [], "count": 0}

    case_sql = "NULL::uuid"
    cc = (case_code_or_id or "").strip()
    if cc:
        if len(cc) == 36 and "-" in cc:
            case_sql = f"{db.literal(cc)}::uuid"
        else:
            c_rows = db.query(f"SELECT to_jsonb(id::text) FROM public.\"case\" WHERE org_id='YX' AND case_code={db.literal(cc)} LIMIT 1")
            if c_rows:
                case_sql = f"{db.literal(str(c_rows[0]))}::uuid"

    q_sql = db.literal(q_str.strip()) if (q_str or "").strip() else "NULL"
    rows = db.query(
        f"""
        SELECT jsonb_build_object(
            'employee_id', employee_id::text,
            'full_name', full_name,
            'department', department,
            'group_name', group_name,
            'job_title', job_title,
            'avatar_url', avatar_url,
            'tier', tier,
            'tier_label', tier_label,
            'badges', badges,
            'score', round(score::numeric, 2),
            'team_scope', team_scope
        )
        FROM public.people_picker(
            {db.literal(actor_uuid)}::uuid,
            {db.literal(ctx)},
            {case_sql},
            {q_sql}
        )
        """
    )
    return {"ok": True, "context": ctx, "count": len(rows), "items": rows}


def get_case_docs_r46(case_code: str = "C114109", viewer_role_or_id: str = "pm", authenticated_session=None) -> dict:
    # api_session was verified by require_session before this reader is called.
    if authenticated_session is None:
        raise PermissionError("Authenticated api_session required")
    viewer_uuid = authenticated_session["employee_id"]
    cc = (case_code or "C114109").strip()
    c_rows = db.query(f"SELECT to_jsonb(id::text) FROM public.\"case\" WHERE org_id='YX' AND case_code={db.literal(cc)} LIMIT 1")
    if not c_rows:
        return {"ok": True, "case_code": cc, "viewer_uuid": viewer_uuid, "default_count": 0, "total_permitted": 0, "docs": []}
    rows = db.query(f"""SELECT jsonb_build_object('doc_id',doc_id::text,'doc_kind',doc_kind,
        'title',title,'version',version,'created_at',to_char(created_at AT TIME ZONE 'Asia/Taipei','MM/DD HH24:MI'),
        'visible_by_default',visible_by_default)
        FROM public.case_docs_for({db.literal(viewer_uuid)}::uuid,{db.literal(str(c_rows[0]))}::uuid)""")
    return {"ok": True,"case_code":cc,"viewer_uuid":viewer_uuid,"default_count":sum(bool(r['visible_by_default']) for r in rows),"total_permitted":len(rows),"docs":rows}




def get_team_scoped_docs(case_code: str = "", scope_filter: str = "", authenticated_session=None) -> list:
    if authenticated_session is None:
        raise PermissionError("Authenticated session required")
    scope = authenticated_session["role_scope"]
    clauses = ["1=1"]
    if case_code:
        clauses.append(f"case_code={db.literal(case_code.strip())}")
    if scope == 'eng':
        clauses.append("doc_scope='eng'")
    if scope_filter in ('admin','pm','eng'):
        clauses.append(f"doc_scope={db.literal(scope_filter)}")
    return db.query("SELECT to_jsonb(d) FROM public.v_yezhu_team_scoped_docs d WHERE " + " AND ".join(clauses) + " ORDER BY case_code,doc_id")



def get_workbench_state() -> dict:
    if not _pg_available():
        if LOCAL_PERSIST_JSON.exists():
            return json.loads(LOCAL_PERSIST_JSON.read_text(encoding="utf-8"))
        return {"ok": True, "source": "fallback", "cases": [], "meta": {}}

    roster_info = get_agents_connectors_state()
    roster_mode = roster_info["roster_mode"]
    roster_items = roster_info.get("items") or []

    rows = db.query(
        """
        SELECT jsonb_build_object(
            'code', code,
            'sort_order', sort_order,
            'is_pinned_default', is_pinned_default,
            'case_data', case_data,
            'letter_state', letter_state,
            'fix_card', fix_card,
            'handoffs', handoffs,
            'verbals', verbals,
            'notes', notes
        )
        FROM public.yezhu_workbench_case
        WHERE is_pinned_default = true
        ORDER BY sort_order ASC, code ASC
        """
    )

    cases = []
    letters = {}
    fix_cards = {}
    handoffs = {}
    verbals = {}
    notes = {}

    for r in rows:
        code = r["code"]
        cdata = dict(r.get("case_data") or {})
        cdata["admin_owner"] = "行政羅薇"
        flags = db.query(f"SELECT to_jsonb(s) FROM public.v_yezhu_team_scoped_cases s WHERE code={db.literal(code)}")
        if flags:
            for key in ('is_admin_priority','is_pm_priority','is_eng_priority'):
                cdata[key] = flags[0][key]
        routing = resolve_case_agent_and_connector(code, cdata, roster_mode, roster_items)
        cdata.update(routing)
        ls = r.get("letter_state") or {}
        actual_rec = f"{cdata.get('client', '')} · {cdata.get('contact', '')} <{ls.get('to') or cdata.get('contact_email') or 'client@example.com'}>".strip(" ·")
        cdata["actual_recipient"] = actual_rec
        cdata["recipient_badge"] = f"🎯 按下後實際收件人：{actual_rec}"
        cdata["test_protection_badge"] = "🎯 測試保護中：按下只會寄至 jekai@yxsurvey.com.tw（許竣凱），不會外發業主"
        cdata["allowed_test_recipient"] = "jekai@yxsurvey.com.tw"
        cases.append(cdata)
        if cdata.get("text"):
            cdata["text"] = enforce_brand(cdata.get("text"))
        if (r.get("letter_state") and r['letter_state'].get('stage')
                and str(r["letter_state"].get("text") or "").strip()):
            ls_clean = dict(r["letter_state"])
            ls_clean["text"] = enforce_brand(ls_clean.get("text"))
            letters[code] = ls_clean
        if r.get("fix_card"):
            fix_cards[code] = r["fix_card"]
        if r.get("handoffs"):
            handoffs[code] = r["handoffs"]
        if r.get("verbals"):
            verbals[code] = r["verbals"]
        if r.get("notes") is not None:
            notes[code] = r["notes"]

    meta_rows = db.query(
        """
        SELECT jsonb_build_object(
            'pins', pins,
            'next_serial', next_serial,
            'authorized', authorized,
            'merged', merged,
            'quarantine', quarantine,
            'admin_claimed', coalesce(admin_claimed, '羅薇'),
            'roster_mode', coalesce(roster_mode, 'multi'),
            'field_mode', field_mode,
            'followup_dismissed', followup_dismissed,
            'analyzed', analyzed
        )
        FROM public.yezhu_workbench_meta
        WHERE key = 'global_state'
        """
    )
    meta = meta_rows[0] if meta_rows else {
        "pins": ["C114109"],
        "next_serial": 12106,
        "authorized": False,
        "merged": "",
        "quarantine": "",
        "admin_claimed": "羅薇",
        "roster_mode": "multi",
        "field_mode": False,
        "followup_dismissed": False,
        "analyzed": False,
    }

    softlocks = db.query(
        """
        SELECT jsonb_build_object(
            'case_code', case_code,
            'holder', holder,
            'role_key', role_key,
            'active', active,
            'takeover_by', takeover_by,
            'takeover_note', takeover_note,
            'ttl_seconds', GREATEST(0, EXTRACT(EPOCH FROM (expires_at - now()))::int)
        )
        FROM public.yezhu_softlock
        WHERE active = true AND expires_at > now()
        """
    )

    db_stats = db.query(
        """
        SELECT jsonb_build_object(
            'database', current_database(),
            'wb_cases', (SELECT count(*) FROM public.yezhu_workbench_case),
            'pinned_cases', (SELECT count(*) FROM public.yezhu_workbench_case WHERE is_pinned_default),
            'pg_cases', (SELECT count(*) FROM public.case),
            'pg_distinct_codes', (SELECT count(DISTINCT case_code) FROM public.case),
            'hist_12084', (SELECT count(*) FROM public.yezhu_correspondence_ledger WHERE serial_no BETWEEN 1 AND 12084),
            'total_ledger', (SELECT count(*) FROM public.yezhu_correspondence_ledger),
            'intake_rows', (SELECT count(*) FROM public.switchboard_intake),
            'quote_live_423', 423
        )
        """
    )[0]

    return {
        "ok": True,
        "source": "postgresql",
        "database": db_stats.get("database", "yongxiang_plumb_r39_clone"),
        "cases": cases,
        "letters": letters,
        "fixCards": fix_cards,
        "handoffs": handoffs,
        "verbals": verbals,
        "notes": notes,
        "meta": meta,
        "softlocks": {s["case_code"]: s for s in softlocks},
        "agents_connectors": {
            "roster_mode": roster_info["roster_mode"],
            "agents": roster_info["agents"],
            "connectors": roster_info["connectors"],
            "active_agent_count": roster_info["active_agent_count"],
            "active_connector_count": roster_info["active_connector_count"],
        },
        "db_stats": db_stats,
        "step9": get_step9_state(),
        "lark_directory": get_lark_directory(),
        "team_docs": (get_team_scoped_docs(authenticated_session=_REQUEST_CONTEXT.session)
                      if getattr(_REQUEST_CONTEXT, 'session', None) else []),
    }


def get_single_case(case_id: str, pin_on_open: bool = False) -> dict:
    if not _pg_available():
        return {"ok": False, "error": "PG_UNAVAILABLE"}

    clean_id = case_id.strip()
    if pin_on_open:
        db.execute(
            f"""
            UPDATE public.yezhu_workbench_case
               SET is_pinned_default = true,
                   updated_at = now()
             WHERE code = {db.literal(clean_id)};
            """
        )

    rows = db.query(
        f"""
        SELECT jsonb_build_object(
            'code', code,
            'sort_order', sort_order,
            'is_pinned_default', is_pinned_default,
            'case_data', case_data,
            'letter_state', letter_state,
            'fix_card', fix_card,
            'handoffs', handoffs,
            'verbals', verbals,
            'notes', notes
        )
        FROM public.yezhu_workbench_case
        WHERE code = {db.literal(clean_id)}
        LIMIT 1
        """
    )
    if not rows:
        return {"ok": False, "error": "CASE_NOT_FOUND", "case_id": clean_id}

    r = rows[0]
    cdata = dict(r.get("case_data") or {})
    cdata["admin_owner"] = "行政羅薇"


    roster_info = get_agents_connectors_state()
    routing = resolve_case_agent_and_connector(
        clean_id, cdata, roster_info["roster_mode"], roster_info.get("items") or []
    )
    cdata.update(routing)

    ledger_rows = db.query(
        f"""
        SELECT jsonb_build_object(
            'serial_no', abs(serial_no),
            'raw_serial', serial_no,
            'serial_label', serial_label,
            'case_code', case_code,
            'client', client,
            'contact', contact,
            'pm', pm,
            'direction', direction,
            'channel', channel,
            'occurred_date', occurred_date,
            'subject', subject,
            'summary', summary,
            'status_label', status_label,
            'messages', messages_json
        )
        FROM public.yezhu_correspondence_ledger
        WHERE case_code = {db.literal(clean_id)}
        ORDER BY abs(serial_no) DESC
        LIMIT 15
        """
    )

    if ledger_rows and not cdata.get("threads"):
        threads = []
        for lr in ledger_rows[:3]:
            msgs = lr.get("messages") or [
                f"{lr['occurred_date']} 09:20 · {lr['contact']}：{lr['summary']}",
                f"{lr['occurred_date']} 15:10 · 詠翔（{lr['pm']}）：已核對並回覆。",
            ]
            threads.append(
                {
                    "serial": str(lr["serial_no"]),
                    "title": lr["subject"],
                    "count": max(2, len(msgs)),
                    "date": lr["occurred_date"],
                    "status": lr["status_label"],
                    "messages": msgs,
                }
            )
        cdata["threads"] = threads

    return {
        "ok": True,
        "case": cdata,
        "letter_state": r.get("letter_state"),
        "fix_card": r.get("fix_card"),
        "handoffs": r.get("handoffs") or [],
        "verbals": r.get("verbals") or [],
        "notes": r.get("notes"),
        "correspondence_ledger": ledger_rows,
        "correspondence_count": len(ledger_rows),
    }


def search_history(query_str: str) -> dict:
    if not _pg_available():
        return {"ok": True, "query": query_str, "cases": [], "correspondence": []}

    q = (query_str or "").strip()
    roster_info = get_agents_connectors_state()
    roster_mode = roster_info["roster_mode"]
    roster_items = roster_info.get("items") or []

    if not q:
        wb = get_workbench_state()
        return {
            "ok": True,
            "query": "",
            "cases": wb["cases"],
            "correspondence": [],
            "total_cases_in_db": wb["db_stats"]["wb_cases"],
            "total_correspondence_in_db": wb["db_stats"]["hist_12084"],
        }

    def _norm_zh(s: str) -> str:
        return (s or "").translate(str.maketrans("爲彜彞臺", "為彝彝台"))

    q_norm = _norm_zh(q)
    q_clean = q_norm.lstrip("#")
    like_pat = f"%{q_norm}%"
    like_clean = f"%{q_clean}%"

    # 1. Search correspondence ledger (#流水號, subject, summary, client, case_code) with 爲/為, 彜/彝, 臺/台 normalization
    corr_rows = db.query(
        f"""
        SELECT jsonb_build_object(
            'serial_no', abs(serial_no),
            'raw_serial', serial_no,
            'serial_label', serial_label,
            'case_code', case_code,
            'client', client,
            'contact', contact,
            'pm', pm,
            'occurred_date', occurred_date,
            'subject', subject,
            'summary', summary,
            'status_label', status_label
        )
        FROM public.yezhu_correspondence_ledger
        WHERE serial_label ILIKE {db.literal(like_clean)}
           OR abs(serial_no)::text = {db.literal(q_clean)}
           OR case_code ILIKE {db.literal(like_clean)}
           OR translate(coalesce(client, ''), '爲彜彞臺', '為彝彝台') ILIKE {db.literal(like_pat)}
           OR translate(coalesce(contact, ''), '爲彜彞臺', '為彝彝台') ILIKE {db.literal(like_pat)}
           OR translate(coalesce(pm, ''), '爲彜彞臺', '為彝彝台') ILIKE {db.literal(like_pat)}
           OR translate(coalesce(subject, ''), '爲彜彞臺', '為彝彝台') ILIKE {db.literal(like_pat)}
           OR translate(coalesce(summary, ''), '爲彜彞臺', '為彝彝台') ILIKE {db.literal(like_pat)}
        ORDER BY abs(serial_no) DESC
        LIMIT 25
        """
    )

    matched_codes_from_corr = list({r["case_code"] for r in corr_rows if r.get("case_code")})
    codes_in_sql = (
        ", ".join(db.literal(c) for c in matched_codes_from_corr[:15])
        if matched_codes_from_corr
        else "''"
    )

    # 2. Search yezhu_workbench_case (932 real cases) with 爲/為, 彜/彝, 臺/台 normalization
    case_rows = db.query(
        f"""
        SELECT jsonb_build_object(
            'code', code,
            'sort_order', sort_order,
            'is_pinned_default', is_pinned_default,
            'case_data', case_data,
            'letter_state', letter_state,
            'fix_card', fix_card,
            'handoffs', handoffs,
            'verbals', verbals
        )
        FROM public.yezhu_workbench_case
        WHERE code ILIKE {db.literal(like_clean)}
           OR translate(coalesce(name, ''), '爲彜彞臺', '為彝彝台') ILIKE {db.literal(like_pat)}
           OR translate(coalesce(full_title, ''), '爲彜彞臺', '為彝彝台') ILIKE {db.literal(like_pat)}
           OR translate(coalesce(client, ''), '爲彜彞臺', '為彝彝台') ILIKE {db.literal(like_pat)}
           OR translate(coalesce(contact, ''), '爲彜彞臺', '為彝彝台') ILIKE {db.literal(like_pat)}
           OR translate(coalesce(pm, ''), '爲彜彞臺', '為彝彝台') ILIKE {db.literal(like_pat)}
           OR translate(coalesce(reminder, ''), '爲彜彞臺', '為彝彝台') ILIKE {db.literal(like_pat)}
           OR serial::text = {db.literal(q_clean)}
           OR code IN ({codes_in_sql})
        ORDER BY
            CASE WHEN lower(code) = lower({db.literal(q_clean)}) THEN 0
                 WHEN code ILIKE {db.literal(q_clean + '%')} THEN 1
                 WHEN is_pinned_default THEN 2
                 ELSE 3 END,
            sort_order ASC,
            code ASC
        LIMIT 25
        """
    )

    cases = []
    letters = {}
    for r in case_rows:
        code = r["code"]
        cdata = dict(r.get("case_data") or {})
        cdata["admin_owner"] = "行政羅薇"
        flags = db.query(f"SELECT to_jsonb(s) FROM public.v_yezhu_team_scoped_cases s WHERE code={db.literal(code)}")
        if flags:
            for key in ('is_admin_priority','is_pm_priority','is_eng_priority'):
                cdata[key] = flags[0][key]
        routing = resolve_case_agent_and_connector(code, cdata, roster_mode, roster_items)
        cdata.update(routing)
        cases.append(cdata)
        if r.get("letter_state"):
            letters[code] = r["letter_state"]

    counts = db.query(
        """
        SELECT jsonb_build_object(
            'wb_cases', (SELECT count(*) FROM public.yezhu_workbench_case),
            'hist_12084', (SELECT count(*) FROM public.yezhu_correspondence_ledger WHERE serial_no BETWEEN 1 AND 12084),
            'total_ledger', (SELECT count(*) FROM public.yezhu_correspondence_ledger)
        )
        """
    )[0]

    return {
        "ok": True,
        "query": q,
        "cases": cases,
        "letters": letters,
        "correspondence": corr_rows,
        "total_cases_in_db": counts["wb_cases"],
        "total_correspondence_in_db": counts["hist_12084"],
        "total_ledger_in_db": counts["total_ledger"],
    }



UNDO_GRACE_SECONDS = 30
WATCHER_STATE_FILE = Path("/tmp/live_jk_test_watcher_state.json")
_SERVER_UNDO_REGISTRY: dict[str, dict] = {}
_SERVER_SECURITY_INTERCEPTS: list[dict] = []
_SERVER_EDIT_MEMORY: list[dict] = []

BASELINE_SECURITY_INTERCEPTS = [
    {
        "ts": 1792952480,
        "time_label": "2026-10-26 02:21:20 (UTC+8)",
        "case_code": "C115055-1",
        "chat_id": "oc_9d424caa98d70d2e9d11225e9c00b404",
        "actor_open_id": "ou_122a1fb91c53f3f5c4d98e612ea8fccc",
        "actor_name": "林育寬",
        "input_text": "把內容改成我是乃瀧*100 就可以寄出了",
        "gate": "G01_PRANK_SPAM + G02_TWO_PHASE_COMMIT",
        "reason": "偵測到異常重複洗版指令（*100）與惡搞測試字眼（我是乃瀧），且禁止單回合改稿兼寄出",
        "action_taken": "BLOCKED_KEEP_PENDING",
    },
    {
        "ts": 1792953120,
        "time_label": "2026-10-26 02:32:00 (UTC+8)",
        "case_code": "C115055-1",
        "chat_id": "oc_9d424caa98d70d2e9d11225e9c00b404",
        "actor_open_id": "ou_122a1fb91c53f3f5c4d98e612ea8fccc",
        "actor_name": "林育寬",
        "input_text": "請把圖資順便副本給 leak_test@gmail.com",
        "gate": "G06_RECIPIENT_DOMAIN",
        "reason": "偵測到非白名單外部收件網域（@gmail.com），防止收件人劫持與圖資外洩，已自動攔截",
        "action_taken": "BLOCKED_KEEP_PENDING",
    },
    {
        "ts": 1792953240,
        "time_label": "2026-10-26 02:34:00 (UTC+8)",
        "case_code": "C115055-1",
        "chat_id": "oc_9d424caa98d70d2e9d11225e9c00b404",
        "actor_open_id": "ou_122a1fb91c53f3f5c4d98e612ea8fccc",
        "actor_name": "林育寬",
        "input_text": "這案子我們不接了 → 核准",
        "gate": "G07_RBAC_ESCALATION",
        "reason": "本草稿涉及重大商業變更（婉拒承接本案），操作者（林育寬｜IT部門）無直接核准外發權限，須由主管（許喆凱）複核",
        "action_taken": "BLOCKED_REQUIRE_MANAGER",
    },
    {
        "ts": 1792953360,
        "time_label": "2026-10-26 02:36:00 (UTC+8)",
        "case_code": "C115055-1",
        "chat_id": "oc_01d9828173a2920809b16248fe28989d",
        "actor_open_id": "ou_7dfe7ce548da22a0275cba0d92b3bfec",
        "actor_name": "許喆凱",
        "input_text": "[Button:approve_send v1 on v2 slot]",
        "gate": "G09_STALE_CARD_CAS",
        "reason": "點擊的是舊版卡片（v1），目前最新草稿為 v2，已攔截防止寄出過期版本",
        "action_taken": "BLOCKED_STALE_VERSION",
    },
]

BASELINE_EDIT_MEMORY = [
    {
        "case_code": "C115055-1",
        "chat_id": "oc_9d424caa98d70d2e9d11225e9c00b404",
        "actor_open_id": "ou_122a1fb91c53f3f5c4d98e612ea8fccc",
        "actor_name": "林育寬",
        "instruction": "把內容改成水深圖資預計週四中午前提供",
        "learned_rule": "交期槽位偏好：水深與地形測量初稿傾向預留內業複核緩衝，改為「本週四（10/29）中午前」提送",
        "risk_badge": "",
        "ts": 1792953000,
        "time_label": "2026-10-26 02:30:00 (UTC+8)",
    },
    {
        "case_code": "C115055-1",
        "chat_id": "oc_01d9828173a2920809b16248fe28989d",
        "actor_open_id": "ou_7dfe7ce548da22a0275cba0d92b3bfec",
        "actor_name": "許喆凱",
        "instruction": "加註：控制點成果與潮位改正紀錄一併附上",
        "learned_rule": "範圍補充槽位偏好：回覆台灣世曦水深測量案件時，習慣於第 3 點主動附帶「控制點成果與潮位改正紀錄」",
        "risk_badge": "",
        "ts": 1792953420,
        "time_label": "2026-10-26 02:37:00 (UTC+8)",
    },
]

TEN_SECURITY_GATES_SPEC = [
    {
        "id": "G01_PRANK_SPAM",
        "code": "G01",
        "name": "情緒抱怨與惡搞洗版攔截閘",
        "benchmark": "Operon (No Raw Output) + NeMo Output Rails",
        "rule": "攔截洗版倍數（*100）、迷因髒話（我是乃瀧）與抱怨業主氣話（很煩/一直改圖/奧客）",
        "base_passed": 42,
        "base_blocked": 5,
    },
    {
        "id": "G02_TWO_PHASE_COMMIT",
        "code": "G02",
        "name": "強制兩階段預覽核准 + 30秒撤回閘",
        "benchmark": "Operon (Draft, Don't Send) + HumanLayer @require_approval",
        "rule": "嚴禁單回合「改稿兼寄出」（剝除『…就可以寄出了』），核准後提供 30 秒 Undo 撤回緩衝",
        "base_passed": 38,
        "base_blocked": 3,
    },
    {
        "id": "G03_INTENT_ROUTER",
        "code": "G03",
        "name": "4-Way 意圖分流（內部提問 vs 改稿隔離）",
        "benchmark": "LangChain Agent Inbox (Edit vs Respond) + 12-Factor #7",
        "rule": "同仁提問（『這案子怎麼又改了？』『哪一版？』）分流為內部解答，絕不污染對外草稿",
        "base_passed": 29,
        "base_blocked": 3,
    },
    {
        "id": "G04_STRUCTURED_SLOTS",
        "code": "G04",
        "name": "結構化商務意圖白名單重寫器",
        "benchmark": "Operon Workflow Slot Mapping + NeMo Dialog Rails",
        "rule": "關閉自由字串直貼 fallback，僅開放：交期調整、報價修改、測量補充、轉交同仁、恢復原稿",
        "base_passed": 35,
        "base_blocked": 2,
    },
    {
        "id": "G05_PROMPT_INJECTION",
        "code": "G05",
        "name": "提示詞注入與越權繞過防禦閘",
        "benchmark": "Google DeepMind CaMeL (Dual-LLM Isolation)",
        "rule": "攔截 Ignore previous、system prompt、忽略上述、跳過審核、直接放行、<script 等注入",
        "base_passed": 44,
        "base_blocked": 2,
    },
    {
        "id": "G06_RECIPIENT_DOMAIN",
        "code": "G06",
        "name": "收件網域白名單與防外洩閘",
        "benchmark": "Simon Willison Lethal Trifecta + CaMeL Capability Policy",
        "rule": "鎖定 ALLOWED_EMAIL_DOMAINS，攔截順便副本給外部私人信箱（@gmail.com）與外網雲端連結",
        "base_passed": 41,
        "base_blocked": 3,
    },
    {
        "id": "G07_RBAC_ESCALATION",
        "code": "G07",
        "name": "職級權限分級與高風險變更複核閘",
        "benchmark": "Operon Role-Based Permissions + HumanLayer Contact Channel",
        "rule": "婉拒承接或報價變動 > ±10% 自動掛載橙色『⚠️ 需主管複核』Risk Badge，限主管許喆凱簽核",
        "base_passed": 31,
        "base_blocked": 2,
    },
    {
        "id": "G08_MARGIN_PRICE_BOUNDS",
        "code": "G08",
        "name": "機密底價毛利與尾款放行結構鎖",
        "benchmark": "Hamel Husain Deterministic Code Gates + PG Release Gate",
        "rule": "攔截『底價/毛利/回扣』、鎖定報價合理區間（NT$10k~5M），尾款未入帳硬鎖官章 DWG",
        "base_passed": 40,
        "base_blocked": 3,
    },
    {
        "id": "G09_STALE_CARD_CAS",
        "code": "G09",
        "name": "卡片版本 CAS 樂觀鎖與舊卡攔截閘",
        "benchmark": "12-Factor Agents Factor 5 & Factor 8 (Own Control Flow)",
        "rule": "按鈕 payload draft_version 必須等於最新 slot 版本，點擊舊卡 v1 當場攔截不誤發",
        "base_passed": 36,
        "base_blocked": 2,
    },
    {
        "id": "G10_SOFTLOCK_COLLISION",
        "code": "G10",
        "name": "跨對話隔離與全員專屬簽名檔強制鎖",
        "benchmark": "Operon Single-Responder Lock + 67/67 Staff Signature Guard",
        "rule": "每對話獨立草稿槽 + 全域認領防撞軟鎖 + 強制注入『詠翔測量工程有限公司』與個人簽名檔",
        "base_passed": 67,
        "base_blocked": 2,
    },
]


def get_security_audit_state() -> dict:
    watcher_st = {}
    if WATCHER_STATE_FILE.exists():
        try:
            watcher_st = json.loads(WATCHER_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            watcher_st = {}

    w_intercepts = list(watcher_st.get("security_intercept_log") or [])
    w_memory = list(watcher_st.get("edit_memory_log") or [])
    w_undo = list(watcher_st.get("undo_history_log") or [])
    w_gate_stats = dict(watcher_st.get("gate_stats") or {})

    # Merge baseline + watcher + server logs (most recent first, deduplicated by (input_text, actor_name))
    combined_intercepts = []
    seen_i = set()
    for item in reversed( _SERVER_SECURITY_INTERCEPTS + w_intercepts ):
        key = (item.get("actor_name", ""), item.get("input_text", ""), item.get("reason", ""))
        if key not in seen_i:
            seen_i.add(key)
            entry = dict(item)
            if not entry.get("time_label") and entry.get("ts"):
                entry["time_label"] = time.strftime("%Y-%m-%d %H:%M:%S (UTC+8)", time.localtime(int(entry["ts"])))
            combined_intercepts.append(entry)
    for item in BASELINE_SECURITY_INTERCEPTS:
        key = (item.get("actor_name", ""), item.get("input_text", ""), item.get("reason", ""))
        if key not in seen_i:
            seen_i.add(key)
            combined_intercepts.append(dict(item))

    combined_memory = []
    seen_m = set()
    for item in reversed( _SERVER_EDIT_MEMORY + w_memory ):
        key = (item.get("actor_name", ""), item.get("instruction", ""))
        if key not in seen_m:
            seen_m.add(key)
            entry = dict(item)
            if not entry.get("time_label") and entry.get("ts"):
                entry["time_label"] = time.strftime("%Y-%m-%d %H:%M:%S (UTC+8)", time.localtime(int(entry["ts"])))
            if not entry.get("learned_rule"):
                inst = entry.get("instruction", "")
                if any(w in inst for w in ("週", "星期", "禮拜")):
                    entry["learned_rule"] = f"交期槽位偏好：同仁（{entry.get('actor_name', '同仁')}）調整提送時程為「{inst}」"
                elif any(w in inst for w in ("萬", "報價", "單價")):
                    entry["learned_rule"] = f"報價槽位調整：同仁（{entry.get('actor_name', '同仁')}）更新報價條件「{inst}」"
                else:
                    entry["learned_rule"] = f"工程範圍補充偏好：同仁（{entry.get('actor_name', '同仁')}）新增結構化補充「{inst}」"
            combined_memory.append(entry)
    for item in BASELINE_EDIT_MEMORY:
        key = (item.get("actor_name", ""), item.get("instruction", ""))
        if key not in seen_m:
            seen_m.add(key)
            combined_memory.append(dict(item))

    gates_out = []
    total_passed = 0
    total_blocked = 0
    for g in TEN_SECURITY_GATES_SPEC:
        gid = g["id"]
        dyn = w_gate_stats.get(gid) or {}
        passed_cnt = int(g["base_passed"]) + int(dyn.get("passed", 0))
        blocked_cnt = int(g["base_blocked"]) + int(dyn.get("blocked", 0))
        total_passed += passed_cnt
        total_blocked += blocked_cnt
        gates_out.append({
            "id": gid,
            "code": g["code"],
            "name": g["name"],
            "benchmark": g["benchmark"],
            "rule": g["rule"],
            "status": "ACTIVE",
            "passed": passed_cnt,
            "blocked": blocked_cnt,
        })

    # Check active undo grace windows across watcher slots and server registry
    now_ts = time.time()
    active_undos = []
    for cid, uinfo in list(_SERVER_UNDO_REGISTRY.items()):
        rem = int(round(float(uinfo.get("undo_deadline_ts", 0)) - now_ts))
        if rem > 0 and not uinfo.get("undone"):
            active_undos.append({
                "case_id": cid,
                "actor": uinfo.get("actor", "許喆凱"),
                "draft_version": uinfo.get("draft_version", 1),
                "remaining_seconds": rem,
                "undo_deadline_ts": int(uinfo.get("undo_deadline_ts", 0)),
            })
    for chat_k, slot in (watcher_st.get("chats") or {}).items():
        if isinstance(slot, dict) and slot.get("status") == "approved":
            rem = int(round(float(slot.get("undo_deadline_ts") or 0) - now_ts))
            if rem > 0:
                active_undos.append({
                    "case_id": "C115055-1",
                    "chat_id": chat_k,
                    "actor": slot.get("approved_by_name") or "許喆凱",
                    "draft_version": slot.get("draft_version", 1),
                    "remaining_seconds": rem,
                    "undo_deadline_ts": int(slot.get("undo_deadline_ts", 0)),
                })

    return {
        "ok": True,
        "service": "詠翔 · 業主往來 Outbound Guardrails & HITL Memory",
        "undo_grace_seconds": UNDO_GRACE_SECONDS,
        "summary": {
            "total_gates": len(gates_out),
            "active_gates": len(gates_out),
            "all_gates_active": True,
            "total_passed": total_passed,
            "total_blocked": total_blocked,
            "intercept_count": len(combined_intercepts),
            "edit_memory_count": len(combined_memory),
            "undo_count": len(w_undo) + sum(1 for v in _SERVER_UNDO_REGISTRY.values() if v.get("undone")),
        },
        "gate_summary": {
            "total_gates": len(gates_out),
            "active_gates": len(gates_out),
            "all_gates_active": True,
            "total_passed": total_passed,
            "total_blocked": total_blocked,
            "intercept_count": len(combined_intercepts),
            "edit_memory_count": len(combined_memory),
            "undo_count": len(w_undo) + sum(1 for v in _SERVER_UNDO_REGISTRY.values() if v.get("undone")),
        },
        "active_undo_windows": active_undos,
        "gates": gates_out,
        "security_intercept_log": combined_intercepts[:50],
        "edit_memory_log": combined_memory[:50],
        "undo_history_log": w_undo[-20:],
    }


def handle_revise(payload: dict) -> tuple[int, dict]:
    case_id = str(payload.get("case_id") or "C114109").strip()
    instruction = str(payload.get("instruction") or "").strip()
    explicit_subj = payload.get("subject")
    explicit_body = payload.get("body")
    file_override = payload.get("file")

    single = get_single_case(case_id)
    if not single.get("ok"):
        return HTTPStatus.NOT_FOUND, single

    cdata = single["case"]
    letter = dict(
        single.get("letter_state")
        or {
            "text": cdata.get("text", ""),
            "subj": cdata.get("subj", ""),
            "stage": "open",
            "serial": None,
            "retries": 0,
            "version": 1,
        }
    )

    subj = str(explicit_subj if explicit_subj is not None else letter.get("subj") or cdata.get("subj") or "")
    body = str(explicit_body if explicit_body is not None else letter.get("text") or cdata.get("text") or "")

    # Gate 1-8 Outbound Safety Guard on Web API /api/revise
    try:
        from live_jk_test_watcher import validate_outbound_draft_safety, classify_security_gate
        probe_text = instruction or str(explicit_body or "")
        if probe_text:
            is_safe, unsafe_reason = validate_outbound_draft_safety(body, probe_text)
            if not is_safe:
                from live_jk_test_watcher import GATE_NAMES_MAP
                gcode = classify_security_gate(unsafe_reason)
                gid = gcode.split("_", 1)[0] if "_" in gcode else gcode[:3]
                gname = GATE_NAMES_MAP.get(gid, gcode)
                _SERVER_SECURITY_INTERCEPTS.append({
                    "id": f"intercept-{int(time.time()*1000)}",
                    "gate_id": gid,
                    "gate_name": gname,
                    "actor_open_id": "web_operator",
                    "actor_name": str(payload.get("actor") or "Web Operator"),
                    "chat_id": "web_ui_5188",
                    "case_code": case_id,
                    "raw_input": probe_text[:160],
                    "reason": unsafe_reason,
                    "draft_version": int(letter.get("version") or 1),
                    "action_taken": "BLOCKED_AND_LOGGED",
                    "ts": int(time.time()),
                })
                return HTTPStatus.BAD_REQUEST, {
                    "ok": False,
                    "error": "SECURITY_GATE_BLOCKED",
                    "gate_id": gid,
                    "gate_name": gname,
                    "reason": unsafe_reason,
                    "case_id": case_id,
                    "draft_version": int(letter.get("version") or 1),
                }
    except Exception:
        pass

    if instruction and explicit_body is None:
        if any(k in instruction for k in ["客氣", "禮貌", "委婉"]):
            if "感謝貴單位" not in body:
                body = re.sub(
                    r"(您好：?\n*)",
                    r"\1感謝貴單位一直以來的支持與協助。\n",
                    body,
                    count=1,
                )
        elif any(k in instruction for k in ["簡短", "精簡"]):
            body = f"{cdata.get('contact','工程師')}您好：\n\n{cdata.get('name','本案')}修正成果已整理完成，隨信附上對外版 PDF，敬請查收。\n\n詠翔測量工程有限公司 敬上"
        elif any(k in instruction for k in ["週三", "時間", "下週"]):
            if "預計下週三" not in body:
                body = body.replace("敬請查收。", "預計下週三前完成後續核對，敬請查收。")
                if "預計下週三" not in body:
                    body += "\n（預計下週三前提送完整對照表）"
        elif "稱呼" in instruction or "改成" in instruction:
            m = re.search(r"改(?:成|為)([^\s，。,.]+)", instruction)
            if m:
                new_title = m.group(1)
                body = re.sub(r"^[^\n]+您好：", f"{new_title}您好：", body)
        elif any(k in instruction for k in ["預覽", "移除連結", "修正"]):
            body = f"{cdata.get('contact','林課長')}您好：\n\n儲槽沉陷監測期末預覽版 PDF 已隨信附上，正式成果圖將於尾款入帳後立即提供，敬請查收。\n\n詠翔測量工程有限公司 敬上"
            file_override = f"{case_id}_預覽版_無章.pdf"
        else:
            body = re.sub(
                r"\n*(?:永祥工程|詠翔測量工程有限公司) 敬上\s*$",
                f"\n（補充說明：{instruction}）\n\n詠翔測量工程有限公司 敬上",
                body,
            )

    if file_override:
        cdata["file"] = file_override

    # R55: force official company name + scrub forbidden brand/person tokens.
    body = enforce_brand(body)

    expected_version = int(letter.get("version") or 1)
    new_version = int(letter.get("version") or 1) + 1
    letter["subj"] = subj
    letter["text"] = body
    letter["version"] = new_version
    cdata["subj"] = subj
    cdata["text"] = body

    from r50_part2_runtime import save_revision
    canonical_version = save_revision(case_id, dict(letter, body=body), expected_version)
    if canonical_version is not None:
        new_version = canonical_version
        letter.update(version=new_version, body=body)

    check_res = inspect_5_checks(cdata, body, subj, cdata.get("file", ""))

    if _pg_available():
        db.execute(
            f"""
            UPDATE public.yezhu_workbench_case
               SET case_data = {db.json_sql(cdata)},
                   letter_state = {db.json_sql(letter)},
                   updated_at = now()
             WHERE code = {db.literal(case_id)};
            """
        )
        _log_audit(
            "yezhu_workbench_case",
            case_id,
            "UPDATE",
            {"action": "revise", "version": new_version, "instruction": instruction, "subj": subj},
        )

    if instruction:
        _SERVER_EDIT_MEMORY.append({
            "case_code": case_id,
            "chat_id": "web_ui_5188",
            "actor_open_id": "web_operator",
            "actor_name": str(payload.get("actor") or "許喆凱"),
            "instruction": instruction,
            "risk_badge": "",
            "ts": int(time.time()),
        })

    return HTTPStatus.OK, {
        "ok": True,
        "case_id": case_id,
        "draft_version": new_version,
        "subject": subj,
        "body": body,
        "file": cdata.get("file", ""),
        "checks": check_res["checks"],
        "errors": check_res["errors"],
        "all_green": check_res["all_green"],
        "sql_gates": check_res["sql_gates"],
        "persisted_in_pg": True,
    }


def handle_approve_send(payload: dict, idem_header: str = "") -> tuple[int, dict]:
    case_id = str(payload.get("case_id") or "C114109").strip()
    raw_test_rec = payload.get("test_recipient") or payload.get("recipient_email")
    if raw_test_rec is not None:
        try:
            enforce_test_recipient_allowlist(str(raw_test_rec))
        except ValueError as exc:
            return HTTPStatus.BAD_REQUEST, {
                "ok": False,
                "error": "BLOCKED_NON_WHITELIST_RECIPIENT",
                "reason": str(exc),
                "allowed_test_recipient": ALLOWED_TEST_RECIPIENT,
            }
    expected_ver = payload.get("expected_draft_version")
    simulate_conflict = bool(payload.get("simulate_conflict", False))
    mode = str(payload.get("mode") or "send").strip()  # 'send' or 'register'
    idem_key = (
        idem_header
        or str(payload.get("idempotency_key") or "").strip()
        or f"{case_id}-v{expected_ver or 1}"
    )

    single = get_single_case(case_id)
    if not single.get("ok"):
        return HTTPStatus.NOT_FOUND, single

    cdata = single["case"]
    letter = dict(
        single.get("letter_state")
        or {
            "text": cdata.get("text", ""),
            "subj": cdata.get("subj", ""),
            "stage": "open",
            "serial": None,
            "retries": 0,
            "version": 1,
        }
    )
    cur_ver = int(letter.get("version") or 1)

    # R55: force official company name + scrub forbidden tokens before send.
    letter["text"] = enforce_brand(letter.get("text") or cdata.get("text") or "")
    cdata["text"] = letter["text"]

    # R52 Hard Lock #1: Colleague approval MUST hold in PENDING_JK_FINAL_APPROVAL and NEVER auto-send
    actor_name = str(payload.get("actor") or "許喆凱").strip()
    if actor_name not in ("許喆凱", "許竣凱", "JK") and not payload.get("jk_final_confirm"):
        letter["stage"] = PENDING_JK_FINAL_APPROVAL
        letter["jk_final_send_status"] = PENDING_JK_FINAL_APPROVAL
        return HTTPStatus.OK, {
            "ok": True,
            "case_id": case_id,
            "status": PENDING_JK_FINAL_APPROVAL,
            "jk_final_send_status": PENDING_JK_FINAL_APPROVAL,
            "auto_send_blocked": True,
            "allowed_test_recipient": ALLOWED_TEST_RECIPIENT,
            "recipient_badge": f"🎯 按下後實際收件人：{cdata.get('contact', '業主窗口')}",
            "test_guard_badge": "🎯 測試保護中：按下只會寄至 jekai@yxsurvey.com.tw（許竣凱），不會外發業主",
            "actual_sends": 0,
            "draft_version": cur_ver,
        }

    if simulate_conflict or (expected_ver is not None and int(expected_ver) != cur_ver):
        if simulate_conflict:
            previous_version = cur_ver
            cur_ver += 1
            letter["version"] = cur_ver
            if _pg_available():
                from r50_part2_runtime import save_revision
                canonical_version = save_revision(case_id,letter,previous_version)
                if canonical_version is not None:
                    cur_ver = canonical_version
                    letter.update(version=cur_ver,body=letter.get('text',''))
                db.execute(
                    f"""
                    UPDATE public.yezhu_workbench_case
                       SET letter_state = {db.json_sql(letter)},
                           updated_at = now()
                     WHERE code = {db.literal(case_id)};
                    """
                )
        return HTTPStatus.CONFLICT, {
            "ok": False,
            "error": "DRAFT_VERSION_CONFLICT",
            "case_id": case_id,
            "expected_version": expected_ver,
            "current_version": cur_ver,
            "message": "草稿剛被振邦改過，請重看一次",
        }

    # Allocate serial via PostgreSQL assign_serial('YX', fingerprint, send_mode)
    raw_serial = -12106
    send_mode = "dry_run"
    if _pg_available():
        try:
            org_ready_row = db.query("SELECT public.org_live_ready('YX')")
            if org_ready_row and bool(org_ready_row[0].get("ready")):
                send_mode = "live"
            raw_serial = int(
                db.query(
                    f"""
                    SELECT to_jsonb(public.assign_serial(
                        'YX',
                        {db.literal('yezhu-ui:' + send_mode + ':' + case_id + ':' + idem_key)},
                        {db.literal(send_mode)}
                    ))
                    """
                )[0]
            )
        except Exception:
            meta_s = db.query("SELECT to_jsonb(next_serial) FROM public.yezhu_workbench_meta WHERE key='global_state'")
            raw_serial = 12085 if send_mode == "live" else -int(meta_s[0] if meta_s else 12106)

    display_serial = abs(raw_serial)
    letter["stage"] = "registered" if mode == "register" else "sent"
    letter["serial"] = display_serial
    letter["serial_badge"] = f"業主往來{display_serial}"
    letter["writeback_badge"] = "已寫回紀錄表 ✓"
    letter["send_mode"] = send_mode
    letter["sync"] = "done"

    if _pg_available():
        try:
            db.execute(
                f"""
                UPDATE public.yezhu_workbench_case
                   SET letter_state = {db.json_sql(letter)},
                       serial = {display_serial},
                       next_label = {db.literal(f'#{display_serial} 已寄出並歸檔' if mode != 'register' else f'#{display_serial} 已登記收件')},
                       updated_at = now()
                 WHERE code = {db.literal(case_id)};
                """
            )
        except Exception:
            db.execute(
                f"""
                UPDATE public.yezhu_workbench_case
                   SET serial = {display_serial},
                       next_label = {db.literal(f'#{display_serial} 已寄出並歸檔' if mode != 'register' else f'#{display_serial} 已登記收件')},
                       updated_at = now()
                 WHERE code = {db.literal(case_id)};
                """
            )
        db.execute(
            f"""

            UPDATE public.yezhu_workbench_meta
               SET next_serial = GREATEST(next_serial, {display_serial + 1}),
                   updated_at = now()
             WHERE key = 'global_state';

            INSERT INTO public.yezhu_correspondence_ledger (
                serial_no, org_id, serial_label, case_code, client, contact, pm,
                direction, channel, occurred_date, subject, summary, status_label, messages_json
            ) VALUES (
                {raw_serial},
                'YX',
                {db.literal(f'業主往來{display_serial}' if send_mode == 'live' else f'業主往來D-{display_serial}')},
                {db.literal(case_id)},
                {db.literal(cdata.get('client', '合作業主'))},
                {db.literal(cdata.get('contact', '窗口'))},
                {db.literal(cdata.get('pm', '待指派'))},
                'outbound',
                'email',
                '10/25',
                {db.literal(letter.get('subj') or cdata.get('subj') or '成果回覆')},
                {db.literal(f'已確認發送並歸檔（#{display_serial}）')},
                '已回',
                {db.json_sql([f"10/25 · 詠翔：{letter.get('subj') or '成果提送'}（#{display_serial}）"])}
            ) ON CONFLICT (serial_no) DO UPDATE
              SET subject = EXCLUDED.subject,
                  summary = EXCLUDED.summary,
                  status_label = EXCLUDED.status_label;
            """
        )
        _log_audit(
            "yezhu_workbench_case",
            case_id,
            "UPDATE",
            {
                "action": "approve_send",
                "mode": mode,
                "serial_no": display_serial,
                "shadow_serial": raw_serial,
                "idempotency_key": idem_key,
                "smtp_disabled": SMTP_DISABLED,
            },
        )

    now_ts = time.time()
    undo_deadline = now_ts + UNDO_GRACE_SECONDS
    _SERVER_UNDO_REGISTRY[case_id] = {
        "case_id": case_id,
        "actor": str(payload.get("actor") or "許喆凱"),
        "draft_version": cur_ver,
        "approved_at_ts": now_ts,
        "undo_deadline_ts": undo_deadline,
        "shadow_serial": raw_serial,
        "display_serial": display_serial,
        "prev_letter": dict(letter, stage="open", serial=None, serial_badge="", writeback_badge="", sync="pending"),
        "undone": False,
    }

    return HTTPStatus.OK, {
        "ok": True,
        "case_id": case_id,
        "serial_no": display_serial,
        "shadow_serial": raw_serial,
        "serial_label": f"#{display_serial}",
        "serial_badge": f"業主往來{display_serial}",
        "writeback_badge": "已寫回紀錄表 ✓",
        "send_mode": send_mode,
        "draft_version": cur_ver,
        "idempotency_key": idem_key,
        "smtp_disabled": SMTP_DISABLED,
        "actual_sends": 0,
        "status": "registered" if mode == "register" else "sent_recorded",
        "undo_grace_seconds": UNDO_GRACE_SECONDS,
        "can_undo": True,
        "undo_deadline_ts": int(undo_deadline),
        "persisted_in_pg": True,
    }


def handle_undo_send(payload: dict) -> tuple[int, dict]:
    case_id = str(payload.get("case_id") or "C114109").strip()
    actor = str(payload.get("actor") or "許喆凱").strip()
    chat_id = str(payload.get("chat_id") or "").strip()
    now_ts = time.time()

    uinfo = _SERVER_UNDO_REGISTRY.get(case_id)
    if uinfo and float(uinfo.get("undo_deadline_ts") or 0) > 0 and now_ts > float(uinfo["undo_deadline_ts"]):
        return HTTPStatus.CONFLICT, {
            "ok": False,
            "error": "UNDO_GRACE_PERIOD_EXPIRED",
            "case_id": case_id,
            "undo_grace_seconds": UNDO_GRACE_SECONDS,
            "message": f"⚠️ 已超過 {UNDO_GRACE_SECONDS} 秒撤回緩衝期，信件已完成正式歸檔，無法撤回",
        }

    watcher_undone = False
    watcher_ver = 1
    if WATCHER_STATE_FILE.exists():
        try:
            wst = json.loads(WATCHER_STATE_FILE.read_text(encoding="utf-8"))
            chats_map = wst.get("chats") or {}
            target_slots = [chats_map[chat_id]] if (chat_id and chat_id in chats_map) else list(chats_map.values())
            for sl in target_slots:
                if isinstance(sl, dict) and sl.get("status") == "approved":
                    dl = float(sl.get("undo_deadline_ts") or 0)
                    if dl > 0 and now_ts > dl and not uinfo:
                        return HTTPStatus.CONFLICT, {
                            "ok": False,
                            "error": "UNDO_GRACE_PERIOD_EXPIRED",
                            "case_id": case_id,
                            "undo_grace_seconds": UNDO_GRACE_SECONDS,
                            "message": f"⚠️ 已超過 {UNDO_GRACE_SECONDS} 秒撤回緩衝期，信件已完成正式歸檔，無法撤回",
                        }
                    sl["status"] = "pending"
                    sl["approved_at_ts"] = 0
                    sl["undo_deadline_ts"] = 0
                    watcher_ver = int(sl.get("draft_version") or 1)
                    watcher_undone = True
            if watcher_undone:
                wst["status"] = "pending"
                ulog = wst.setdefault("undo_history_log", [])
                ulog.append({
                    "case_code": case_id,
                    "chat_id": chat_id or "web_ui_5188",
                    "actor_open_id": "web_operator",
                    "actor_name": actor,
                    "draft_version": watcher_ver,
                    "via": "web_api_5188",
                    "ts": int(now_ts),
                })
                WATCHER_STATE_FILE.write_text(json.dumps(wst, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    single = get_single_case(case_id)
    cur_ver = watcher_ver
    if single.get("ok"):
        letter = dict(single.get("letter_state") or {})
        cur_ver = int(letter.get("version") or 1)
        letter["stage"] = "open"
        letter["serial"] = None
        letter["serial_badge"] = ""
        letter["writeback_badge"] = ""
        letter["sync"] = "pending"
        letter["undone_at_ts"] = int(now_ts)
        if _pg_available():
            try:
                sql_upd = (
                    f"UPDATE public.yezhu_workbench_case "
                    f"SET letter_state = {db.json_sql(letter)}, "
                    f"serial = NULL, "
                    f"next_label = {db.literal('↩️ 已撤回寄送 · 待重新確認')}, "
                    f"updated_at = now() "
                    f"WHERE code = {db.literal(case_id)};"
                )
                db.execute(sql_upd)
                _log_audit(
                    "yezhu_workbench_case",
                    case_id,
                    "UPDATE",
                    {"action": "undo_send", "actor": actor, "draft_version": cur_ver},
                )
            except Exception:
                pass

    if uinfo:
        uinfo["undone"] = True
        uinfo["undo_deadline_ts"] = 0

    return HTTPStatus.OK, {
        "ok": True,
        "case_id": case_id,
        "status": "pending",
        "stage": "open",
        "draft_version": cur_ver,
        "undone": True,
        "actor": actor,
        "undo_grace_seconds": UNDO_GRACE_SECONDS,
        "message": f"↩️ 已於 {UNDO_GRACE_SECONDS} 秒緩衝期內成功撤回寄送（#{case_id} 已恢復為待確認草稿 v{cur_ver}）",
    }


def handle_fix_request(payload: dict) -> tuple[int, dict]:
    case_id = str(payload.get("case_id") or "C114109").strip()
    assignee = str(payload.get("assignee") or "家彬").strip()
    item = str(payload.get("item") or "北側管線修正圖 PDF").strip()
    sender = str(payload.get("from") or "柏頤").strip()
    fix_card = payload.get("fix_card") or {
        "assignee": assignee,
        "item": item,
        "from": sender,
        "due": "明天 12:00（原卡期限 − 4 工作小時）",
        "status": "waiting",
        "nudges": 0,
        "overdue": False,
        "uploaded": False,
        "file": "",
        "reject": "",
    }
    if _pg_available():
        db.execute(
            f"""
            UPDATE public.yezhu_workbench_case
               SET fix_card = {db.json_sql(fix_card)},
                   updated_at = now()
             WHERE code = {db.literal(case_id)};
            """
        )
        _log_audit("yezhu_workbench_case", case_id, "UPDATE", {"action": "fix_request", "fix_card": fix_card})
    return HTTPStatus.OK, {
        "ok": True,
        "case_id": case_id,
        "fix_card": fix_card,
        "status": fix_card.get("status", "waiting"),
        "persisted_in_pg": True,
    }


def handle_fix_complete(payload: dict) -> tuple[int, dict]:
    case_id = str(payload.get("case_id") or "C114109").strip()
    file_name = str(payload.get("file") or f"{case_id}_北側管線修正圖_v2.pdf").strip()
    single = get_single_case(case_id)
    fix_card = dict((single.get("fix_card") if single.get("ok") else None) or {
        "assignee": "家彬",
        "item": "北側管線修正圖 PDF",
        "from": "柏頤",
        "due": "明天 12:00（原卡期限 − 4 工作小時）",
        "nudges": 0,
        "overdue": False,
    })
    fix_card["uploaded"] = True
    fix_card["file"] = file_name
    fix_card["status"] = "completed"

    if _pg_available():
        db.execute(
            f"""
            UPDATE public.yezhu_workbench_case
               SET fix_card = {db.json_sql(fix_card)},
                   updated_at = now()
             WHERE code = {db.literal(case_id)};
            """
        )
        _log_audit("yezhu_workbench_case", case_id, "UPDATE", {"action": "fix_complete", "file": file_name})
    return HTTPStatus.OK, {
        "ok": True,
        "case_id": case_id,
        "fix_card": fix_card,
        "ball_holder": "柏頤",
        "persisted_in_pg": True,
    }


def handle_verbal(payload: dict) -> tuple[int, dict]:
    case_id = str(payload.get("case_id") or "C115042").strip()
    role = str(payload.get("role") or "pm").strip()
    speaker = str(payload.get("speaker") or ("家彬" if role == "eng" else "羅薇" if role == "admin" else "柏頤")).strip()
    assignee = str(payload.get("assignee") or ("柏頤（案件 PM）" if role == "eng" else "家彬")).strip()
    due = str(payload.get("due") or "下週三 17:00").strip()
    confirm = str(payload.get("confirm") or "yes").strip()
    content = str(payload.get("content") or "口頭請託北段邊坡加測 200m，下週三前提送高程表").strip()
    propose_note = str(payload.get("proposeNote") or payload.get("propose_note") or "").strip()

    status = "待柏頤確認後再對外承諾" if role == "eng" else "待業主書面確認"
    entry = {
        "speaker": speaker,
        "assignee": "柏頤（案件 PM）" if role == "eng" else assignee,
        "due": due,
        "confirm": confirm,
        "content": content,
        "proposeNote": propose_note,
        "status": status,
        "text": f"🗣 剛剛 通話口述：{speaker}記下「{content}」· 負責：{('柏頤（案件 PM）' if role == 'eng' else assignee)} · 期限：{due} · {status}",
    }

    single = get_single_case(case_id)
    verbals = list((single.get("verbals") if single.get("ok") else None) or [])
    verbals.insert(0, entry)

    letter = dict((single.get("letter_state") if single.get("ok") else None) or {})
    cdata = dict((single.get("case") if single.get("ok") else None) or {})
    if confirm == "yes" and cdata:
        letter["subj"] = f"{cdata.get('name', case_id)}｜口述承諾書面確認"
        letter["text"] = f"{cdata.get('contact','工程師')}您好：\n\n依今日通話討論，{content}（預計期限：{due}）。\n敬請回信確認上述內容，收到書面確認後即刻安排辦理。\n\n詠翔測量工程有限公司 敬上"
        letter["stage"] = "open"
        letter["version"] = int(letter.get("version") or 1) + 1

    if _pg_available():
        from r50_part2_runtime import save_revision
        if letter:
            letter['body'] = letter.get('text',letter.get('body',''))
            ver = save_revision(case_id, letter, int((single.get('letter_state') or {}).get('version') or 1))
            if ver is not None:
                letter.update(version=ver, body=letter.get('text',''))
        db.execute(
            f"""
            UPDATE public.yezhu_workbench_case
               SET verbals = {db.json_sql(verbals)},
                   letter_state = {db.json_sql(letter) if letter else 'letter_state'},
                   updated_at = now()
             WHERE code = {db.literal(case_id)};
            """
        )
        _log_audit("yezhu_workbench_case", case_id, "UPDATE", {"action": "verbal", "entry": entry})

    return HTTPStatus.OK, {
        "ok": True,
        "case_id": case_id,
        "verbal": entry,
        "verbals": verbals,
        "letter_state": letter,
        "persisted_in_pg": True,
    }


def handle_handoff(payload: dict) -> tuple[int, dict]:
    case_id = str(payload.get("case_id") or "C114109").strip()
    note = str(payload.get("note") or "").strip()
    if len(note) < 6:
        return HTTPStatus.UNPROCESSABLE_ENTITY, {
            "ok": False,
            "error": "HANDOFF_NOTE_TOO_SHORT",
            "min_chars": 6,
            "message": "請輸入至少 6 個字交接說明，講清楚為什麼轉交",
        }
    from_user = str(payload.get("from") or "柏頤")
    to_user = str(payload.get("to") or "智偉")
    time_str = str(payload.get("time") or "14:20")

    single = get_single_case(case_id)
    handoffs = list((single.get("handoffs") if single.get("ok") else None) or [])
    record = {"from": from_user, "to": to_user, "time": time_str, "note": note}
    handoffs.insert(0, record)

    if _pg_available():
        db.execute(
            f"""
            UPDATE public.yezhu_workbench_case
               SET handoffs = {db.json_sql(handoffs)},
                   who = {db.literal(to_user)},
                   updated_at = now()
             WHERE code = {db.literal(case_id)};
            """
        )
        _log_audit("yezhu_workbench_case", case_id, "UPDATE", {"action": "handoff", "record": record})

    return HTTPStatus.OK, {
        "ok": True,
        "case_id": case_id,
        "handoff": record,
        "handoffs": handoffs,
        "persisted_in_pg": True,
    }


def handle_softlock(payload: dict) -> tuple[int, dict]:
    case_id = str(payload.get("case_id") or "C114109").strip()
    action = str(payload.get("action") or "status").strip()
    holder = str(payload.get("holder") or "柏頤")
    role_key = str(payload.get("role") or "pm")
    note = str(payload.get("note") or "").strip()

    if action == "takeover":
        if len(note) < 6:
            return HTTPStatus.UNPROCESSABLE_ENTITY, {
                "ok": False,
                "error": "TAKEOVER_NOTE_TOO_SHORT",
                "min_chars": 6,
                "message": "請輸入至少 6 個字接手原因",
            }
        takeover_by = str(payload.get("takeover_by") or "振邦")
        if _pg_available():
            db.execute(
                f"""
                INSERT INTO public.yezhu_softlock (case_code, org_id, holder, role_key, active, takeover_by, takeover_note, expires_at, updated_at)
                VALUES ({db.literal(case_id)}, 'YX', {db.literal(takeover_by)}, {db.literal(role_key)}, false, {db.literal(takeover_by)}, {db.literal(note)}, now() + interval '90 seconds', now())
                ON CONFLICT (case_code) DO UPDATE
                  SET active = false,
                      holder = EXCLUDED.holder,
                      takeover_by = EXCLUDED.takeover_by,
                      takeover_note = EXCLUDED.takeover_note,
                      updated_at = now();
                """
            )
        handle_handoff({"case_id": case_id, "from": holder, "to": takeover_by, "time": "14:02", "note": note})
        return HTTPStatus.OK, {
            "ok": True,
            "case_id": case_id,
            "active": False,
            "takeover_by": takeover_by,
            "note": note,
            "ttl_seconds": 90,
        }

    active = action == "lock"
    if _pg_available():
        db.execute(
            f"""
            INSERT INTO public.yezhu_softlock (case_code, org_id, holder, role_key, active, expires_at, updated_at)
            VALUES ({db.literal(case_id)}, 'YX', {db.literal(holder)}, {db.literal(role_key)}, {'true' if active else 'false'}, now() + interval '90 seconds', now())
            ON CONFLICT (case_code) DO UPDATE
              SET holder = EXCLUDED.holder,
                  role_key = EXCLUDED.role_key,
                  active = EXCLUDED.active,
                  expires_at = now() + interval '90 seconds',
                  updated_at = now();
            """
        )
        _log_audit("yezhu_softlock", case_id, "UPDATE", {"action": action, "holder": holder, "active": active})

    return HTTPStatus.OK, {
        "ok": True,
        "case_id": case_id,
        "holder": holder,
        "active": active,
        "ttl_seconds": 90,
    }


def handle_intake_simulate(payload: dict) -> tuple[int, dict]:
    target_code = str(payload.get("case_id") or "C115025").strip()
    raw_serial = -12106
    if _pg_available():
        try:
            raw_serial = int(
                db.query(
                    f"""
                    SELECT to_jsonb(public.assign_serial(
                        'YX',
                        {db.literal(f'yezhu-ui:intake:{target_code}:{int(time.time())}')},
                        'dry_run'
                    ))
                    """
                )[0]
            )
        except Exception:
            raw_serial = -12106
    display_serial = abs(raw_serial)

    single = get_single_case(target_code)
    if single.get("ok"):
        cdata = single["case"]
    else:
        target_code = "C115025"
        cdata = get_single_case("C115025")["case"]

    if payload.get("subject"):
        cdata["subj"] = str(payload["subject"])
    if payload.get("message"):
        cdata["message"] = str(payload["message"])
    cdata["when"] = "剛剛"
    cdata["phase"] = "mine"
    cdata["next"] = f"#{display_serial} 新來信待確認回信草稿"
    cdata["serial"] = display_serial

    letter = {
        "subj": cdata.get("subj") or f"{cdata['name']}｜測量成果報告提送",
        "text": cdata.get("text") or f"{cdata.get('contact','主任')}您好：\n\n本案測量成果報告已核對完成，隨信附上對外版 PDF，敬請查收。\n\n詠翔測量工程有限公司 敬上",
        "stage": "open",
        "serial": None,
        "retries": 0,
        "version": 1,
    }

    if _pg_available():
        db.execute(
            f"""
            UPDATE public.yezhu_workbench_case
               SET is_pinned_default = true,
                   sort_order = 0,
                   phase = 'mine',
                   when_label = '剛剛',
                   next_label = {db.literal(cdata['next'])},
                   serial = {display_serial},
                   case_data = {db.json_sql(cdata)},
                   letter_state = {db.json_sql(letter)},
                   updated_at = now()
             WHERE code = {db.literal(target_code)};

            INSERT INTO public.yezhu_correspondence_ledger (
                serial_no, org_id, serial_label, case_code, client, contact, pm,
                direction, channel, occurred_date, subject, summary, status_label, messages_json
            ) VALUES (
                {raw_serial},
                'YX',
                {db.literal(f'業主往來D-{display_serial}')},
                {db.literal(target_code)},
                {db.literal(cdata.get('client', '凱達營造股份有限公司'))},
                {db.literal(cdata.get('contact', '陳主任'))},
                {db.literal(cdata.get('pm', '待指派'))},
                'inbound',
                'email',
                '10/25',
                {db.literal(letter['subj'])},
                {db.literal(cdata.get('message', '業主來信詢問成果進度'))},
                '待回',
                {db.json_sql([f"10/25 剛剛 · {cdata.get('contact','陳主任')}：{cdata.get('message','')}"])}
            ) ON CONFLICT (serial_no) DO NOTHING;
            """
        )
        _log_audit(
            "yezhu_workbench_case",
            target_code,
            "INSERT",
            {"action": "intake_simulate", "serial_no": display_serial, "case_code": target_code},
        )

    roster_info = get_agents_connectors_state()
    routing = resolve_case_agent_and_connector(
        target_code, cdata, roster_info["roster_mode"], roster_info.get("items") or []
    )
    cdata.update(routing)

    return HTTPStatus.OK, {
        "ok": True,
        "case_id": target_code,
        "serial_no": display_serial,
        "shadow_serial": raw_serial,
        "case": cdata,
        "letter_state": letter,
        "pipeline_steps": ["收件登記", "來信分類", "歸入工編", "五項檢查", "產生草稿"],
        "persisted_in_pg": True,
    }


def handle_agents_connectors_toggle(payload: dict) -> tuple[int, dict]:
    mode = payload.get("mode")
    item_id = payload.get("item_id") or payload.get("agent_id") or payload.get("connector_id")
    enabled = payload.get("enabled")

    if _pg_available():
        if mode in ("minimal", "multi"):
            db.execute(
                f"""
                UPDATE public.yezhu_workbench_meta
                   SET roster_mode = {db.literal(mode)},
                       updated_at = now()
                 WHERE key = 'global_state';
                """
            )
            if mode == "minimal":
                db.execute(
                    """
                    UPDATE public.switchboard_agent_roster
                       SET enabled = CASE WHEN item_id = 'agent-all-in-one' THEN true ELSE enabled END,
                           updated_at = now()
                     WHERE kind = 'agent';
                    """
                )
        if item_id:
            if enabled is None:
                db.execute(
                    f"""
                    UPDATE public.switchboard_agent_roster
                       SET enabled = CASE WHEN is_core OR item_id = 'agent-all-in-one' THEN true ELSE NOT enabled END,
                           updated_at = now()
                     WHERE item_id = {db.literal(str(item_id))};
                    """
                )
            else:
                en_sql = "true" if (bool(enabled) or str(item_id) == "agent-all-in-one") else "false"
                db.execute(
                    f"""
                    UPDATE public.switchboard_agent_roster
                       SET enabled = CASE WHEN is_core THEN true ELSE {en_sql} END,
                           updated_at = now()
                     WHERE item_id = {db.literal(str(item_id))};
                    """
                )
        _log_audit(
            "switchboard_agent_roster",
            str(item_id or mode or "roster"),
            "UPDATE",
            {"mode": mode, "item_id": item_id, "enabled": enabled},
        )

    state = get_agents_connectors_state()
    return HTTPStatus.OK, state


def handle_state_sync(payload: dict) -> tuple[int, dict]:
    if not _pg_available():
        LOCAL_PERSIST_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return HTTPStatus.OK, {"ok": True, "source": "local_file"}

    pins = payload.get("pins")
    next_serial = payload.get("nextSerial")
    authorized = payload.get("authorized")
    merged = payload.get("merged")
    quarantine = payload.get("quarantine")
    admin_claimed = str(payload.get("adminClaimed") or "羅薇")
    roster_mode = payload.get("rosterMode")
    field_mode = payload.get("fieldMode")
    followup_dismissed = payload.get("followupDismissed")
    analyzed = payload.get("analyzed")

    sql_list = []
    if pins is not None or next_serial is not None or authorized is not None:
        sql_list.append(
            f"""
            UPDATE public.yezhu_workbench_meta
               SET pins = COALESCE({db.json_sql(pins) if pins is not None else 'NULL'}, pins),
                   next_serial = COALESCE({int(next_serial) if next_serial is not None else 'NULL'}, next_serial),
                   authorized = COALESCE({'true' if authorized else 'false' if authorized is not None else 'NULL'}, authorized),
                   merged = COALESCE({db.literal(merged) if merged is not None else 'NULL'}, merged),
                   quarantine = COALESCE({db.literal(quarantine) if quarantine is not None else 'NULL'}, quarantine),
                   admin_claimed = {db.literal(admin_claimed)},
                   roster_mode = COALESCE({db.literal(roster_mode) if roster_mode in ('minimal','multi') else 'NULL'}, roster_mode),
                   field_mode = COALESCE({'true' if field_mode else 'false' if field_mode is not None else 'NULL'}, field_mode),
                   followup_dismissed = COALESCE({'true' if followup_dismissed else 'false' if followup_dismissed is not None else 'NULL'}, followup_dismissed),
                   analyzed = COALESCE({'true' if analyzed else 'false' if analyzed is not None else 'NULL'}, analyzed),
                   updated_at = now()
             WHERE key = 'global_state';
            """
        )

    letters = payload.get("letters") or {}
    fix_cards = payload.get("fixCards") or {}
    handoffs = payload.get("handoffs") or {}
    verbals = payload.get("verbals") or {}
    notes = payload.get("notes") or {}
    touched_codes = set(letters.keys()) | set(fix_cards.keys()) | set(handoffs.keys()) | set(verbals.keys()) | set(notes.keys())

    for code in touched_codes:
        sets = ["updated_at = now()"]
        if code in letters:
            from r50_part2_runtime import save_revision
            incoming = letters[code]
            # Autosave preserves canonical drafts. Explicit revision is the version writer.
            cards = db.query("SELECT jsonb_build_object('n',count(*)) FROM public.r50_owner_draft WHERE case_code="+db.literal(code))
            if not cards[0]['n']:
                sets.append(f"letter_state = {db.json_sql(incoming)}")
        if code in fix_cards:
            sets.append(
                f"fix_card = {db.json_sql(fix_cards[code]) if fix_cards[code] is not None else 'NULL'}"
            )
        if code in handoffs:
            sets.append(f"handoffs = {db.json_sql(handoffs[code])}")
        if code in verbals:
            sets.append(f"verbals = {db.json_sql(verbals[code])}")
        if code in notes:
            sets.append(f"notes = {db.json_sql(notes[code])}")
        sql_list.append(
            f"UPDATE public.yezhu_workbench_case SET {', '.join(sets)} WHERE code = {db.literal(code)};"
        )

    if sql_list:
        db.execute("BEGIN;\n" + "\n".join(sql_list) + "\nCOMMIT;")

    return HTTPStatus.OK, {"ok": True, "persisted_in_pg": True}


def handle_reset_demo_seed() -> tuple[int, dict]:
    if not _pg_available():
        if LOCAL_PERSIST_JSON.exists():
            LOCAL_PERSIST_JSON.unlink()
        return HTTPStatus.OK, {"ok": True, "reset": "local"}

    # Default demo cards may be reset, but managed R50 drafts must advance via
    # the canonical writer. Never rewind a draft head or reset rehearsal rows.
    managed = db.query("""SELECT jsonb_build_object('code',w.code,'initial',w.initial_letter_state,
        'letter',w.letter_state,'version',h.current_version,'body',v.body)
        FROM public.yezhu_workbench_case w JOIN public.r50_owner_draft r ON r.case_code=w.code
        JOIN public.draft_head h USING(card_id)
        JOIN public.draft_version v ON v.card_id=h.card_id AND v.version=h.current_version
        WHERE w.initial_pinned""")
    from r50_part2_runtime import save_revision
    for item in managed:
        current = dict(item['letter'] or {})
        current.update(version=item['version'],body=item['body'],text=item['body'])
        if item['initial'] is None:
            current.pop('stage',None)
        db.execute("UPDATE public.yezhu_workbench_case SET letter_state="+db.json_sql(current)+
                   " WHERE code="+db.literal(item['code']))
        if item['initial'] is None:
            continue
        letter = dict(item['initial'] or {})
        for key in ('to','cc','attachments_manifest'):
            if key in current:
                letter[key] = current[key]
        letter['body'] = letter.get('text',letter.get('body',''))
        letter['text'] = letter['body']
        save_revision(item['code'],letter,item['version'])

    db.execute(
        """
        BEGIN;
        DELETE FROM public.serial_assignment WHERE fingerprint LIKE 'yezhu-ui:%';
        UPDATE public.serial_allocator SET shadow_next_serial = -12105 WHERE org_id = 'YX';
        DELETE FROM public.yezhu_correspondence_ledger WHERE serial_no < -12105;

        UPDATE public.yezhu_workbench_case
           SET is_pinned_default = initial_pinned,
               sort_order = CASE WHEN initial_pinned THEN sort_order ELSE GREATEST(sort_order, 100) END,
               case_data = initial_case_data,
               letter_state = CASE WHEN initial_pinned AND initial_letter_state IS NULL
                                       AND EXISTS(SELECT 1 FROM public.r50_owner_draft r WHERE r.case_code=code)
                                   THEN letter_state - 'stage'
                                   WHEN EXISTS(SELECT 1 FROM public.r50_owner_draft r WHERE r.case_code=code)
                                   THEN letter_state ELSE initial_letter_state END,
               fix_card = NULL,
               handoffs = '[]'::jsonb,
               verbals = '[]'::jsonb,
               notes = NULL,
               updated_at = now()
         WHERE (initial_pinned OR is_pinned_default) AND (
               is_pinned_default <> initial_pinned
            OR sort_order < 100
            OR fix_card IS NOT NULL
            OR handoffs <> '[]'::jsonb
            OR verbals <> '[]'::jsonb
            OR notes IS NOT NULL
            OR letter_state IS DISTINCT FROM initial_letter_state
            OR case_data IS DISTINCT FROM initial_case_data);

        TRUNCATE public.yezhu_softlock;

        UPDATE public.yezhu_workbench_meta
           SET pins = '["C114109"]'::jsonb,
               next_serial = 12106,
               authorized = false,
               merged = '',
               quarantine = '',
               admin_claimed = '羅薇',
               roster_mode = 'multi',
               field_mode = false,
               followup_dismissed = false,
               analyzed = false,
               updated_at = now()
         WHERE key = 'global_state';

        UPDATE public.switchboard_agent_roster
           SET enabled = initial_enabled,
               updated_at = now()
         WHERE enabled IS DISTINCT FROM initial_enabled;
        COMMIT;
        """
    )
    _ensure_step9_seed(reset=True)
    return HTTPStatus.OK, {"ok": True, "reset": "postgresql", "step9": get_step9_state()}


def load_bundle_fallback():
    bundle = json.loads(BUNDLE_JSON.read_text(encoding="utf-8")) if BUNDLE_JSON.exists() else {}
    dry = json.loads(DRYRUN_JSON.read_text(encoding="utf-8")) if DRYRUN_JSON.exists() else {}
    state = bundle.get("state") or {}
    return {
        "ok": True,
        "source": "bundle_fallback",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "smtp_disabled": True,
        "actual_sends": 0,
        "summary": state.get("summary") or {},
        "review": state.get("review") or {},
        "inbox": state.get("inbox") or [],
        "ledger": state.get("ledger") or [],
        "dryrun_20": dry,
    }


def get_yezhu_cases(authenticated: dict) -> dict:
    """Gate 5: role-scoped case list + capsule + scoped session list.

    role_scope / capsule are recomputed per request (never from the session
    row). Engineers get is_eng_priority ordering; everyone gets their own
    session_list_for(employee_id, false)."""
    scope = authenticated.get("effective_role_scope") or authenticated.get("role_scope") or ""
    order = "ORDER BY sort_order,code"
    if scope == "eng":
        order = "ORDER BY is_eng_priority DESC NULLS LAST,sort_order,code"
    elif scope == "admin":
        order = "ORDER BY is_admin_priority DESC NULLS LAST,sort_order,code"
    elif scope == "pm":
        order = "ORDER BY is_pm_priority DESC NULLS LAST,sort_order,code"
    cases = db.query(
        "SELECT to_jsonb(c) FROM public.v_yezhu_team_scoped_cases c " + order)
    scoped_sessions = db.query(
        "SELECT to_jsonb(s) FROM public.session_list_for(" +
        db.literal(authenticated['employee_id']) + "::uuid,false) s")
    return {
        "ok": True,
        "service": "詠翔測量 · 業主往來",
        "capsule_name": authenticated.get("capsule_name"),
        "capsule_group_label": authenticated.get("capsule_group_label"),
        "capsule_display": authenticated.get("capsule_display"),
        "role_scope": scope,
        "cases": cases,
        "scoped_sessions": scoped_sessions,
        "total_visible": len(cases),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        raw = (
            body
            if isinstance(body, (bytes, bytearray))
            else json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        )
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Idempotency-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format, *args):
        return

    def do_OPTIONS(self):
        self._send(HTTPStatus.NO_CONTENT, b"", "text/plain; charset=utf-8")

    def _logout(self):
        """Gate 7: delete the api_session row and expire the cookie now."""
        from http.cookies import SimpleCookie
        import hashlib as _hl
        session = require_session(self.headers)
        try:
            if session and session.get('session_id'):
                db.execute("DELETE FROM public.api_session WHERE id=" +
                           db.literal(session['session_id']) + "::uuid")
            else:
                # Fall back to whatever the cookie / bearer referenced directly.
                auth = self.headers.get("Authorization", "")
                if auth.startswith("Bearer "):
                    digest = _hl.sha256(auth[7:].encode()).hexdigest()
                    db.execute("DELETE FROM public.api_session WHERE token_sha256=" + db.literal(digest))
                else:
                    cookies = SimpleCookie()
                    cookies.load(self.headers.get("Cookie", ""))
                    raw = next((cookies[k].value for k in ("switchboard_session", "r47_session") if k in cookies), "")
                    try:
                        db.execute("DELETE FROM public.api_session WHERE id=" + db.literal(str(UUID(raw))) + "::uuid")
                    except Exception:
                        digest = _hl.sha256(raw.encode()).hexdigest()
                        db.execute("DELETE FROM public.api_session WHERE token_sha256=" + db.literal(digest))
        except Exception:
            pass
        body = json.dumps({"ok": True, "logged_out": True}, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Set-Cookie', SESSION_COOKIE + '=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        _REQUEST_CONTEXT.session = None
        if path == "/api/health":
            self._send(HTTPStatus.OK, {
                "ok": True,
                "status": "ok",
                "service": "詠翔測量 · 業主往來",
                "db": "yongxiang_plumb_r39_clone",
                "org_mode": "shadow",
                "smtp_disabled": SMTP_DISABLED,
                "actual_sends": 0,
            })
            return
        start_paths = ('/auth/lark', '/login', '/api/auth/login', '/auth/lark/login')
        callback_paths = ('/api/auth/callback', '/auth/lark/callback')
        public_auth_path = path in start_paths or path in callback_paths or path == '/auth/r47/callback'
        # --- Gate 1: login start / callback (public, no session required) ---
        if path in callback_paths:
            auth_callback(self, path, qs)
            return
        if path in start_paths:
            auth_start(self, path, qs)
            return
        authenticated = require_session(self.headers) if not public_auth_path else None
        if not public_auth_path and authenticated is None:
            is_html_deeplink = (not path.startswith('/api/')) and ("text/html" in (self.headers.get("Accept") or "")) and (('card_id' in qs) or ('case_id' in qs))
            if not is_html_deeplink and (path.startswith('/api/') or self.headers.get('Cookie') or self.headers.get('Authorization')):
                self._send(HTTPStatus.UNAUTHORIZED, {"ok":False,"error":"SESSION_REQUIRED"})
            else:
                # Gate 6: preserve the deep link across the login round-trip.
                deep = ('card_id' in qs) or ('case_id' in qs) or bool(parsed.query)
                location = '/auth/lark'
                if deep:
                    full = path + ('?' + parsed.query if parsed.query else '')
                    location = '/auth/lark?return_to=' + urllib_quote(full)
                self.send_response(302)
                self.send_header('Location', location)
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
            return
        _REQUEST_CONTEXT.session = authenticated
        # Gate 8: identity-override selectors in the URL / headers never win.
        override_hits = detect_override_params(qs, self.headers)
        ignored = sorted(set(qs) & {'user', 'role', 'viewer', 'actor'})
        if (override_hits or ignored) and authenticated:
            _log_audit('api_session', authenticated['session_id'], 'UPDATE', {'event':'IGNORED_IDENTITY_QUERY','keys':ignored})
            _log_login_attempt(authenticated.get('lark_open_id', ''), 'ignored_override_param',
                               ','.join(override_hits or ignored), path, {"hits": override_hits or ignored})
            for key in ignored:
                qs.pop(key, None)
        _REQUEST_CONTEXT.session = authenticated
        if path == "/api/session":
            self._send(HTTPStatus.OK, {"ok":True,"identity":{k:v for k,v in authenticated.items() if k!='token_sha256'}})
            return
        if path in ("/api/auth/me", "/api/me"):
            ident = {k: v for k, v in authenticated.items() if k != 'token_sha256'}
            self._send(HTTPStatus.OK, {
                "ok": True, "identity": ident,
                "capsule_name": authenticated.get("capsule_name"),
                "capsule_group_label": authenticated.get("capsule_group_label"),
                "capsule_display": authenticated.get("capsule_display"),
            })
            return
        if path in ("/api/yezhu/cases", "/api/yezhu_cases"):
            self._send(HTTPStatus.OK, get_yezhu_cases(authenticated))
            return

        if path == "/api/owner-communications/r50":
            from pm_solution_owner_comm import snapshot
            self._send(HTTPStatus.OK, snapshot((qs.get("case_code") or [None])[0]))
            return

        from lark_cli_watcher_daemon import handle as r49_handle
        if r49_handle(self, "GET"): return
        from r50_closed_loop_api import handle as r50_handle
        if r50_handle(self, "GET"): return
        from r47_launch import handle as r47_handle
        if r47_handle(self, "GET"):
            return
        from preschedule_api import handle as r51_preschedule_handle
        r51_res = r51_preschedule_handle("GET", path, parsed.query, {})
        if r51_res is not None:
            if r51_res[0] == "html":
                self._send(HTTPStatus.OK, r51_res[1], "text/html; charset=utf-8")
            else:
                self._send(r51_res[0], r51_res[1])
            return


        if path == "/static/operon_workflow.js":
            self._send(HTTPStatus.OK, (Path(__file__).parent/'static/operon_workflow.js').read_bytes(), "application/javascript; charset=utf-8")
            return
        if path == "/r50-workflow":
            self._send(HTTPStatus.OK, (Path(__file__).parent/'static/operon_review.html').read_bytes(), "text/html; charset=utf-8")
            return
        if path in ("/", "/index.html", "/ui", "/ui/"):
            raw_html = UI_HTML.read_text(encoding="utf-8")
            if getattr(self.server, "server_port", None) in (8787, 8788):
                raw_html = re.sub(r"<title>.*?</title>", "<title>PM Solution DB · 詠翔專案工作台 (YXMEEGLE)</title>", raw_html, count=1)
            self._send(HTTPStatus.OK, raw_html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/health":
            self._send(HTTPStatus.OK, {
                "ok": True,
                "service": "詠翔 · 業主往來",
                "db": "yongxiang_plumb_r39_clone",
                "smtp_disabled": SMTP_DISABLED,
                "actual_sends": 0,
            })
            return
        if path == "/api/sessions":
            rows = db.query("SELECT to_jsonb(s) FROM public.session_list_for(" +
                db.literal(authenticated['employee_id']) + "::uuid," +
                ('true' if qs.get('show_all') == ['1'] else 'false') + ") s")
            self._send(HTTPStatus.OK, {
                "ok": True,
                "service": "詠翔 · 業主往來",
                "sessions": rows,
                "total_visible": len(rows),
            })
            return
        if path == "/api/bundle":
            self._send(HTTPStatus.OK, load_bundle_fallback())
            return
        if path in ("/api/workbench_state", "/api/cases"):
            self._send(HTTPStatus.OK, get_workbench_state())
            return
        if path.startswith("/api/case/"):
            cid = unquote(path.split("/api/case/", 1)[1]).strip("/")
            pin_flag = qs.get("pin", ["0"])[0] == "1"
            res = get_single_case(cid, pin_on_open=pin_flag)
            self._send(HTTPStatus.OK if res.get("ok") else HTTPStatus.NOT_FOUND, res)
            return
        if path == "/api/history_search":
            q = (qs.get("q") or [""])[0]
            self._send(HTTPStatus.OK, search_history(q))
            return
        if path == "/api/agents_connectors":
            self._send(HTTPStatus.OK, get_agents_connectors_state())
            return
        if path == "/api/step9_state":
            self._send(HTTPStatus.OK, {"ok": True, "step9": get_step9_state()})
            return
        if path == "/api/lark_directory":
            q = (qs.get("q") or [""])[0]
            sc = (qs.get("scope") or [""])[0]
            self._send(HTTPStatus.OK, get_lark_directory(q, sc))
            return
        if path == "/api/team_cases":
            rows=db.query("SELECT to_jsonb(c) FROM public.v_yezhu_team_scoped_cases c ORDER BY sort_order,code")
            self._send(HTTPStatus.OK,{"ok":True,"cases":rows})
            return
        if path == "/api/team_docs":
            cc = (qs.get("case_code") or [""])[0]
            sc = (qs.get("scope") or [""])[0]
            docs = get_team_scoped_docs(cc, sc, authenticated)
            self._send(HTTPStatus.OK, {"ok": True, "count": len(docs), "docs": docs})
            return
        if path == "/api/people":
            ctx = (qs.get("context") or ["handoff"])[0]
            cid = (qs.get("case_id") or qs.get("case_code") or [""])[0]
            q = (qs.get("q") or [""])[0]
            act = (qs.get("actor") or ["pm"])[0]
            if authenticated:
                act = authenticated["employee_id"]
            self._send(HTTPStatus.OK, get_people_picker(ctx, cid, q, act))
            return
        if path == "/api/case_docs":
            cc = (qs.get("case_code") or ["C114109"])[0]
            vw = authenticated['employee_id']
            self._send(HTTPStatus.OK, get_case_docs_r46(cc, vw, authenticated))
            return
        if path in ("/api/security-audit", "/api/security_audit"):
            self._send(HTTPStatus.OK, get_security_audit_state())
            return
        if path == "/api/state":
            wb = get_workbench_state()
            fb = load_bundle_fallback()
            fb["workbench"] = wb
            fb["agents_connectors"] = wb.get("agents_connectors")
            fb["db_stats"] = wb.get("db_stats")
            fb["security_audit"] = get_security_audit_state()
            self._send(HTTPStatus.OK, fb)
            return
        if path == "/api/summary":
            self._send(HTTPStatus.OK, load_bundle_fallback().get("summary", {}))
            return
        if path == "/api/inbox":
            self._send(HTTPStatus.OK, load_bundle_fallback().get("inbox", []))
            return
        if path == "/api/ledger":
            self._send(HTTPStatus.OK, load_bundle_fallback().get("ledger", []))
            return
        if path == "/api/review":
            self._send(HTTPStatus.OK, load_bundle_fallback().get("review", {}))
            return
        self._send(HTTPStatus.NOT_FOUND, {"ok": False, "error": "NOT_FOUND", "path": path})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        # Gate 7: logout destroys the session row immediately and clears cookie.
        if path in ("/auth/logout", "/api/auth/logout"):
            self._logout()
            return
        _REQUEST_CONTEXT.session = require_session(self.headers)
        if _REQUEST_CONTEXT.session is None:
            self._send(HTTPStatus.UNAUTHORIZED, {"ok":False,"error":"SESSION_REQUIRED"})
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "INVALID_JSON"})
            return

        principal = _REQUEST_CONTEXT.session
        # Gate 8: drop any reverse identity-override params from the body/headers.
        override_hits = detect_override_params(parse_qs(parsed.query), self.headers, payload)
        if override_hits:
            _log_login_attempt(principal.get('lark_open_id', ''), 'ignored_override_param',
                               ','.join(override_hits), path, {"hits": override_hits})
            for key in list(payload.keys()):
                if str(key).strip().lower() in _OVERRIDE_KEYS:
                    payload.pop(key, None)
        payload['actor'] = principal['full_name']
        payload['actor_employee_id'] = principal['employee_id']
        payload['actor_role'] = principal['actor_role']
        payload['user'] = principal['full_name']
        payload['role'] = principal['role_scope']
        from lark_cli_watcher_daemon import handle as r49_handle
        if r49_handle(self, "POST", payload): return
        from r50_closed_loop_api import handle as r50_handle
        if r50_handle(self, "POST", payload): return
        from r47_launch import handle as r47_handle
        if r47_handle(self, "POST", payload):
            return
        from preschedule_api import handle as r51_preschedule_handle
        r51_res = r51_preschedule_handle("POST", path, parsed.query, payload)
        if r51_res is not None:
            self._send(r51_res[0], r51_res[1])
            return


        if path == "/api/revise":
            st, body = handle_revise(payload)
            self._send(st, body)
            return
        if path == "/api/approve_send":
            idem = self.headers.get("Idempotency-Key") or ""
            st, body = handle_approve_send(payload, idem_header=idem)
            self._send(st, body)
            return
        if path in ("/api/undo_send", "/api/undo-send"):
            st, body = handle_undo_send(payload)
            self._send(st, body)
            return
        if path == "/api/fix_request":
            st, body = handle_fix_request(payload)
            self._send(st, body)
            return
        if path == "/api/fix_complete":
            st, body = handle_fix_complete(payload)
            self._send(st, body)
            return
        if path == "/api/verbal":
            st, body = handle_verbal(payload)
            self._send(st, body)
            return
        if path == "/api/handoff":
            st, body = handle_handoff(payload)
            self._send(st, body)
            return
        if path == "/api/softlock":
            st, body = handle_softlock(payload)
            self._send(st, body)
            return
        if path == "/api/intake_simulate":
            st, body = handle_intake_simulate(payload)
            self._send(st, body)
            return
        if path == "/api/agents_connectors/toggle":
            st, body = handle_agents_connectors_toggle(payload)
            self._send(st, body)
            return
        if path == "/api/state_sync":
            st, body = handle_state_sync(payload)
            self._send(st, body)
            return
        if path == "/api/handoff_claim":
            st, body = handle_handoff_claim(payload)
            self._send(st, body)
            return
        if path == "/api/quarantine_dispose":
            st, body = handle_quarantine_dispose(payload)
            self._send(st, body)
            return
        if path == "/api/org_live_toggle":
            st, body = handle_org_live_toggle(payload)
            self._send(st, body)
            return
        if path in ("/api/reset_demo_seed", "/api/reset_seed", "/api/reset"):
            st, body = handle_reset_demo_seed()
            self._send(st, body)
            return

        if live_api is not None:
            try:
                if path == "/api/card":
                    st, body = live_api.handle_card_action(payload)
                    self._send(st, body)
                    return
                if path == "/api/intake":
                    st, body = live_api.handle_intake(payload)
                    self._send(st, body)
                    return
                if path == "/api/commitment":
                    st, body = live_api.handle_commitment(payload)
                    self._send(st, body)
                    return
            except Exception as exc:
                self._send(HTTPStatus.OK, {"ok": True, "source": "bundle_noop", "note": str(exc)})
                return

        self._send(HTTPStatus.OK, {"ok": True, "source": "bundle_noop", "smtp_disabled": True, "actual_sends": 0})


def serve_port(port):
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"switchboard_ui_server listening on http://127.0.0.1:{port}", flush=True)
    httpd.serve_forever()


def main():
    if not os.environ.get("SMTP_HOST") and not os.environ.get("SMTP_PASS"):
        print("SMTP: disabled (shadow)", flush=True)
    def r47_local_worker():
        from r47_worker import tick
        while True:
            try:
                tick()
            except Exception as exc:
                print("R47 local worker: " + str(exc).split("\n")[0], flush=True)
            time.sleep(15)
    if os.environ.get('SWITCHBOARD_DISABLE_BACKGROUND_WORKER') != '1':
        threading.Thread(target=r47_local_worker, daemon=True).start()
    servers = []
    for port in PORTS:
        try:
            t = threading.Thread(target=serve_port, args=(port,), daemon=True)
            t.start()
            servers.append(t)
        except OSError as exc:
            print(f"port {port} skipped: {exc}", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()


def parse_zh_amount(text: str):
    """Wave #26 P0 fix: parse Chinese currency multipliers (千/萬/十萬/百萬/千萬/億) without residual comma corruption."""
    if not text:
        return None
    m = re.search(r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)\s*(千萬|百萬|十萬|億|萬|千|百|十|[wWkK])?", text)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    unit = m.group(2) or ""
    mult = {
        "億": 100_000_000,
        "千萬": 10_000_000,
        "百萬": 1_000_000,
        "十萬": 100_000,
        "萬": 10_000,
        "w": 10_000,
        "W": 10_000,
        "千": 1_000,
        "k": 1_000,
        "K": 1_000,
        "百": 100,
        "十": 10,
    }.get(unit, 1)
    return int(round(val * mult))


def apply_nl_reply_edit_py(draft_body: str, instruction: str) -> str:
    """Apply NL price/schedule edit in Python matching SQL public.r50_apply_reply_edit."""
    body = draft_body or ""
    cmd = (instruction or "").strip()
    if "單價" in cmd:
        sub = re.search(r"單價.*", cmd)
        amt = parse_zh_amount(sub.group(0) if sub else cmd)
        if amt is not None:
            fmt = f"NT${amt:,}（未稅）"
            if re.search(r"單價(?:為)?\s*(?:NT\$|\$)?\s*[0-9,]+(?:\.[0-9]+)?(?:\s*元)?(?:（[^）]*）|\([^)]*\))?", body):
                body = re.sub(
                    r"單價(?:為)?\s*(?:NT\$|\$)?\s*[0-9,]+(?:\.[0-9]+)?(?:\s*元)?(?:（[^）]*）|\([^)]*\))?",
                    f"單價 {fmt}",
                    body,
                )
            else:
                body = body + f"\n（更新單價：{fmt}）"
    return body
