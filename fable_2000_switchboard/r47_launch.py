"""Clone-only R47 routes; session identity always comes from api_session."""
import base64
import binascii
from contextlib import contextmanager
import hashlib
import hmac
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from uuid import UUID

RUN = '47000000-0000-0000-0000-000000000001'
ROOT = Path(__file__).resolve().parent

def b64(b): return base64.urlsafe_b64encode(b).decode().rstrip('=')
def un64(s): return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))
def keys():
    # JSON {kid: {key: high entropy secret, created_at: unix}}; keep retired keys for 72h.
    configured = os.environ.get('R47_LINK_KEYS')
    if configured:
        ring = json.loads(configured)
    else:
        path = ROOT / '.r47_link_keys.json'
        if not path.exists():
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as f:
                    json.dump({'r47-initial': {'key': secrets.token_urlsafe(48), 'created_at': int(time.time())}}, f)
            except FileExistsError:
                pass
        if path.stat().st_mode & 0o077: raise RuntimeError('link key file must be mode 0600')
        ring = json.loads(path.read_text())
    if not ring: raise RuntimeError('No signing key available')
    return ring

def sign(payload):
    ring = keys(); kid = os.environ.get('R47_LINK_KID', next(iter(ring)))
    key = ring[kid]
    if time.time() - key['created_at'] > 90 * 86400: raise RuntimeError('signing key rotation required')
    if len(key['key']) < 32: raise RuntimeError('signing key must have at least 32 characters')
    payload = dict(payload, kid=kid)
    raw = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode()
    return b64(raw) + '.' + b64(hmac.digest(key['key'].encode(), raw, 'sha256'))

def verify(token, purpose='link'):
    try:
        if len(token) > 8192: raise ValueError()
        data, sig = token.split('.'); raw = un64(data); p = json.loads(raw)
        key = keys()[p['kid']]['key']
        if not hmac.compare_digest(un64(sig), hmac.digest(key.encode(), raw, 'sha256')): raise ValueError()
        if p.get('purpose', 'link') != purpose: raise ValueError()
        if purpose == 'link':
            if p['v'] != 1 or not isinstance(p['rcpt'], str) or not p['n']: raise ValueError()
            UUID(p['card']); UUID(p['case']); int(p['exp'])
        elif p['exp'] < time.time(): raise ValueError()
        return p
    except (ValueError, KeyError, TypeError, UnicodeError, binascii.Error) as exc: raise ValueError('連結無效') from exc

def mint(card, case, recipient):
    return sign(dict(v=1, card=str(card), case=str(case), rcpt=recipient, exp=int(time.time())+72*3600, n=secrets.token_urlsafe(24)))

class _Pg2CompatConn:
    def __init__(self, raw):
        self._raw = raw
    def execute(self, sql, params=None):
        import psycopg2.extras
        cur = self._raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return cur
    def commit(self):
        self._raw.commit()

@contextmanager
def connection():
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(host='127.0.0.1', port=5432, user='postgres', password='postgres', dbname='yongxiang_plumb_r39_clone', row_factory=dict_row) as conn:
            name = conn.execute('SELECT current_database() AS name').fetchone()['name']
            assert name != 'yongxiang_plumb'
            assert name == 'yongxiang_plumb_r39_clone'
            yield conn
    except ImportError:
        import psycopg2
        raw = psycopg2.connect(dbname='yongxiang_plumb_r39_clone', user='postgres', password='postgres', host='127.0.0.1', port=5432)
        try:
            conn = _Pg2CompatConn(raw)
            name = conn.execute('SELECT current_database() AS name').fetchone()['name']
            assert name != 'yongxiang_plumb'
            assert name == 'yongxiang_plumb_r39_clone'
            yield conn
        finally:
            raw.close()

def identity(conn, headers):
    auth = headers.get('Authorization', '')
    cookie = SimpleCookie(); cookie.load(headers.get('Cookie', ''))
    token = auth[7:] if auth.startswith('Bearer ') else (cookie['switchboard_session'].value if 'switchboard_session' in cookie else (cookie['r47_session'].value if 'r47_session' in cookie else ''))
    if not token: return None
    row = conn.execute('''SELECT e.id,e.org_id,e.role_code,e.lark_open_id FROM public.api_session s
      JOIN public.employee e ON e.id=s.employee_id AND e.org_id=s.org_id
      WHERE s.token_sha256=%s AND s.expires_at>now() AND e.employment_status='active'
      AND e.identity_confirmed AND s.lark_open_id=e.lark_open_id''', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if row:
        conn.execute("SELECT set_config('app.current_employee_id',%s,true)", (str(row['id']),))
        conn.execute("SELECT set_config('app.r47_session_sha256',%s,true)", (hashlib.sha256(token.encode()).hexdigest(),))
    return row

def redirect(h, location, cookie=None):
    h.send_response(302); h.send_header('Location', location); h.send_header('Cache-Control','no-store')
    if cookie: h.send_header('Set-Cookie', cookie)
    h.end_headers()

def oidc_start(h, token):
    nonce = secrets.token_urlsafe(24)
    state = sign(dict(purpose='oidc', exp=int(time.time())+600, n=nonce, t=token))
    params = dict(app_id=os.environ['LARK_APP_ID'], redirect_uri=os.environ['LARK_REDIRECT_URI'], state=state)
    redirect(h, 'https://accounts.feishu.cn/open-apis/authen/v1/authorize?' + urlencode(params), 'r47_oidc='+nonce+'; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=600')

def oidc_callback(h, conn, qs):
    p = verify(qs['state'][0], 'oidc'); cookies = SimpleCookie(); cookies.load(h.headers.get('Cookie',''))
    if 'r47_oidc' not in cookies or not hmac.compare_digest(cookies['r47_oidc'].value,p['n']): raise ValueError('invalid OIDC state')
    body = dict(grant_type='authorization_code',client_id=os.environ['LARK_APP_ID'],client_secret=os.environ['LARK_APP_SECRET'],code=qs['code'][0],redirect_uri=os.environ['LARK_REDIRECT_URI'])
    def fetch(url, body=None, bearer=None):
        headers={'Content-Type':'application/json'}
        if bearer: headers['Authorization']='Bearer '+bearer
        with urlopen(Request(url,data=json.dumps(body).encode() if body else None,headers=headers),timeout=15) as r: return json.load(r)
    tok = fetch('https://open.feishu.cn/open-apis/authen/v2/oauth/token',body)
    info = fetch('https://open.feishu.cn/open-apis/authen/v1/user_info',bearer=tok['access_token'])['data']
    employee = conn.execute("SELECT id,org_id,role_code FROM public.employee WHERE org_id='YX' AND lark_open_id=%s AND employment_status='active' AND identity_confirmed",(info['open_id'],)).fetchone()
    if not employee:
        h._send(401,'你的 Lark 帳號尚未對應到詠翔同仁，請找行政（羅薇）'.encode('utf-8'),'text/plain; charset=utf-8')
        return
    token = secrets.token_urlsafe(48)
    conn.execute("INSERT INTO public.api_session(token_sha256,employee_id,org_id,role,expires_at,lark_open_id) VALUES(%s,%s,%s,%s,now()+interval '8 hours',%s)",(hashlib.sha256(token.encode()).hexdigest(),employee['id'],employee['org_id'],employee['role_code'],info['open_id']))
    conn.commit()
    destination = '/open?'+urlencode({'t':p['t']}) if p.get('t') else '/'
    redirect(h,destination,'r47_session='+token+'; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=28800')

def doorbell(conn, card_id, tier='immediate'):
    """Queue locally only; delivery remains the existing notification worker's responsibility."""
    row = conn.execute('''SELECT c.id,c.case_id,c.title,e.lark_open_id,e.field_mode_until FROM public.card c JOIN public.employee e ON e.id=c.assignee_employee_id WHERE c.id=%s AND e.employment_status='active' ''',(card_id,)).fetchone()
    if not row or not row['case_id'] or not row['lark_open_id']: raise ValueError('card recipient unavailable')
    # Fixed safe title prevents source data, serials, amounts and OTPs from leaking.
    title = (row['title'] or '業主來信待處理 · 球在你手上')[:40]
    if conn.execute("SELECT public.guard_hit('lark_notice',%s) hit", (title,)).fetchone()['hit']:
        title = '業主來信待處理 · 球在你手上'
    if row['field_mode_until'] and row['field_mode_until'].timestamp()>time.time(): title = title[:20] + '（你外業中，17:00 前不催）'
    token = mint(row['id'],row['case_id'],row['lark_open_id'])
    payload = dict(text=title,link=os.environ.get('R47_PUBLIC_URL','https://localhost')+'/open?'+urlencode({'t':token}),card_id=str(row['id']))
    conn.execute("INSERT INTO public.notification_outbox(channel,recipient_id,tier,dedupe_key,payload) VALUES('lark',%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING",(row['lark_open_id'],tier,'lark:'+str(card_id)+':'+row['lark_open_id']+('' if tier=='immediate' else ':'+tier),json.dumps(payload)))

def handle(h, method, payload=None):
    parsed = urlparse(h.path); path=parsed.path; qs=parse_qs(parsed.query)
    if path not in ('/label','/launch','/open','/auth/r47/callback') and not path.startswith('/api/r47/'): return False
    try:
        with connection() as conn:
            if path == '/auth/r47/callback': oidc_callback(h,conn,qs); return True
            p = None
            if path == '/open':
                try: p=verify(qs.get('t',[''])[0])
                except ValueError:
                    conn.execute("INSERT INTO public.deep_link_open_log(outcome) VALUES('invalid')"); conn.commit(); raise
            me = identity(conn,h.headers)
            if not me:
                if path == '/open': oidc_start(h,qs['t'][0]); return True
                h._send(401,{'error':'Lark SSO session required'}); return True
            if method == 'POST':
                # Cookie authentication also requires a same-origin request (CSRF protection).
                if not h.headers.get('Authorization','').startswith('Bearer '):
                    origin=h.headers.get('Origin',''); expected=os.environ.get('R47_PUBLIC_URL','')
                    if not origin or origin.rstrip('/')!=expected.rstrip('/'): raise PermissionError('origin required')
                data=payload or {}; run=str(UUID(data.get('run',RUN)))
                if path in ('/api/r47/shadow-draft-review','/api/r47/quote-choose','/api/r47/category-wrong'):
                    from inbox_canvas_api import r48_action
                    result=r48_action(conn,me,path,data)
                elif path == '/api/r47/label': result=conn.execute('SELECT public.label_submit(%s,%s,%s::jsonb) v',(run,data['sample_id'],json.dumps(data['label']))).fetchone()['v']
                elif path == '/api/r47/adjudicate': result=conn.execute('SELECT public.adjudicate_submit(%s,%s,%s,%s::jsonb) v',(run,data['sample_id'],data['choice'],json.dumps(data.get('custom')))).fetchone()['v']
                elif path == '/api/r47/card-act':
                    card=str(UUID(data['card_id']))
                    held=conn.execute("SELECT idempotency_key FROM public.card WHERE id=%s AND org_id=%s AND assignee_employee_id=%s AND state IN ('open','escalated','dry_run')",(card,me['org_id'],me['id'])).fetchone()
                    if not held: raise PermissionError('card is read-only or has moved')
                    if held['idempotency_key'].startswith('r48:quote-choose:'): raise ValueError('select a quote record first')
                    result=conn.execute('SELECT public.card_act(%s::uuid,%s::uuid,%s::text,%s::text) v',(card,me['id'],data['action'],data['idempotency_key'])).fetchone()['v']
                elif path in ('/api/r47/kill','/api/r47/live'):
                    fn='org_kill_switch' if path.endswith('/kill') else 'org_go_live'
                    conn.execute('SELECT public.'+fn+'(%s,%s)',(me['org_id'],data.get('reason'))); result=True
                else: h._send(404,{'error':'not found'}); return True
                conn.commit(); h._send(200,{'ok':True,'result':result}); return True
            if path in ('/label','/launch'):
                if path=='/label': conn.execute("SELECT public.r47_actor(%s,ARRAY['a','b','adjudicator'])",(RUN,))
                h._send(200,(ROOT/'ui/r47.html').read_bytes(),'text/html; charset=utf-8'); return True
            if path=='/open':
                result=conn.execute('SELECT public.resolve_deep_link_open(%s,%s,%s,%s) v',(p['card'],p['case'],p['rcpt'],me['id'])).fetchone()['v']
                if p['exp']<time.time() and result=='direct':
                    result='stale'; conn.execute("UPDATE public.deep_link_open_log SET outcome='stale' WHERE id=currval('public.deep_link_open_log_id_seq')")
                conn.commit()
                # A dedicated authenticated session view never renders the unrestricted legacy case endpoint.
                if result=='no_access': redirect(h,'/launch?notice=no_access')
                else: redirect(h,'/launch?'+urlencode(dict(case=p['case'],card=p['card'],outcome=result)))
                return True
            if path=='/api/r47/next':
                run=str(UUID(qs.get('run',[RUN])[0])); role=conn.execute("SELECT public.r47_actor(%s,ARRAY['a','b','adjudicator']) v",(run,)).fetchone()['v']
                row=conn.execute('SELECT public.adjudicate_next(%s) v',(run,)).fetchone()['v'] if role=='adjudicator' else conn.execute('SELECT * FROM public.label_next(%s)',(run,)).fetchone()
                h._send(200,dict(role=role,sample=row)); return True
            if path=='/api/r47/health':
                from inbox_canvas_api import r48_health
                panel=conn.execute('SELECT public.day1_health_panel(%s) v',(me['org_id'],)).fetchone()['v']
                panel.update(r48_health(conn,me))
                h._send(200,panel); return True
            if path=='/api/r47/session':
                case=str(UUID(qs['case'][0])); card=str(UUID(qs['card'][0]))
                visible=conn.execute('SELECT 1 FROM public.session_list_for(%s,false) WHERE case_id=%s',(me['id'],case)).fetchone()
                if not visible: raise PermissionError('no case access')
                row=conn.execute('''SELECT c.id,c.title,c.state,c.actions,c.handoff_strip,e.full_name assignee, c.assignee_employee_id=%s AND c.state IN ('open','escalated','dry_run') can_act FROM public.card c JOIN public.employee e ON e.id=c.assignee_employee_id WHERE c.id=%s AND c.case_id=%s AND c.org_id=%s''',(me['id'],card,case,me['org_id'])).fetchone()
                h._send(200,dict(card=row,case_id=case)); return True
            if path=='/api/r47/evidence':
                indicator=qs.get('indicator',[''])[0]
                if indicator=='intake': sql="SELECT m.id,m.case_id,m.subject,m.ingested_at FROM public.email_message m WHERE m.org_id=%s AND (m.ingested_at AT TIME ZONE 'Asia/Taipei')::date=(now() AT TIME ZONE 'Asia/Taipei')::date"
                elif indicator=='outbound': sql='SELECT id,case_id,delivery_status,sent_at FROM public.outbound_message WHERE org_id=%s'
                elif indicator=='sheet': sql='SELECT max_serial,observed_at,writeback_pending_since,source_ref FROM public.r47_sheet_observation WHERE org_id=%s'
                else: raise ValueError('unknown indicator')
                # Restrict details to the same case visibility used by deep links.
                rows=conn.execute(sql,(me['org_id'],)).fetchall()
                allowed={x['case_id'] for x in conn.execute('SELECT case_id FROM public.session_list_for(%s,false)',(me['id'],))}
                if indicator!='sheet': rows=[r for r in rows if r['case_id'] in allowed]
                h._send(200,rows); return True
            h._send(404,{'error':'not found'}); return True
    except Exception as exc:
        status=404 if path=='/label' else 403 if isinstance(exc,PermissionError) or 'InsufficientPrivilege' in type(exc).__name__ else 400
        if isinstance(exc,(RuntimeError,KeyError)) and path in ('/open','/auth/r47/callback'): status=503
        h._send(status,{'error':str(exc).split('\n')[0]}); return True
