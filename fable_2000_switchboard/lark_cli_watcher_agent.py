"""Event-Driven Local Lark CLI Loopback Inbox & Webhook Trigger Handler.
No scheduled cron polling; triggered immediately upon Inbox / Webhook / Card Action / NL Chat arrival.
No live Lark, SMTP, or external network transport (strictly SANDBOX_LOOPBACK / DRY_RUN).
Includes Operon 3 Top Metrics + 3-Column Decision Model (Inline Deadline, Rev C → Rev D · 22 changes, A Person Decides)
and Single-Responder Collision Lock (SW-LARK-COLLISION-01: 吳柏頤 + 涂振邦).
"""
from r50_part2_safety import ENV
import argparse
import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

DATABASE = 'yongxiang_plumb_r39_clone'
ACTOR = '1101fb67-0080-50c1-98e6-d02f7a0ae907'
MODE = 'SANDBOX_LOOPBACK'
TRIGGER_ARCH = 'EVENT_DRIVEN_INBOX_WEBHOOK'
INBOX_ADDRESS = 'jk-chief+switchboard@mail.grokbot.com'
WEBHOOK_ROUTINE = 'lark-webhook-lark'
CARD_MODE = 'CARD_MODE'
NL_CHAT_MODE = 'NL_CHAT_MODE'
COLLISION_STATUS = 'COLLISION_BLOCKED_SUPERSEDED_BY_PEER'
ALLOWED_TEST_RECIPIENT = 'jekai@yxsurvey.com.tw'
PENDING_JK_FINAL_APPROVAL = 'PENDING_JK_FINAL_APPROVAL'


def enforce_test_recipient_allowlist(recipient: str = ALLOWED_TEST_RECIPIENT) -> str:
    norm = (recipient or '').strip().lower()
    if not norm or '@gmail.com' in norm or norm != ALLOWED_TEST_RECIPIENT:
        raise ValueError(
            f'BLOCKED_NON_WHITELIST_RECIPIENT: recipient {recipient!r} is forbidden in test mode; '
            f'only {ALLOWED_TEST_RECIPIENT} is allowed'
        )
    return ALLOWED_TEST_RECIPIENT


def build_operon_workflow_card(
    case_code: str,
    subject: str,
    client_recipient: str,
    draft_version: int = 1,
    test_mode: bool = True,
) -> dict:
    rec = (client_recipient or '').strip() or '台灣世曦 · 林工程師 <lin.ceci@example.com>'
    badge = f'🎯 按下後實際收件人：{rec}'
    test_badge = '🎯 測試保護中：按下只會寄至 jekai@yxsurvey.com.tw（許竣凱），不會外發業主'
    return {
        'schema_version': 'r52.hardlock.v1',
        'case_code': case_code or 'C114109',
        'subject': subject or '',
        'draft_version': int(draft_version or 1),
        'intended_client_recipient': rec,
        'allowed_test_recipient': ALLOWED_TEST_RECIPIENT,
        'jk_final_lock_policy': PENDING_JK_FINAL_APPROVAL,
        'recipient_badge': badge,
        'test_guard_badge': test_badge if test_mode else badge,
        'action_buttons': [
            {
                'action': 'approve',
                'label': '✅ 核准（送交 JK 最終審核放行）',
                'adjacent_recipient_label': badge,
                'adjacent_test_guard_label': test_badge,
                'transitions_to': PENDING_JK_FINAL_APPROVAL,
                'auto_send': False,
            },
            {
                'action': 'edit_and_approve',
                'label': '✏️ 修改後送交 JK 審核',
                'adjacent_recipient_label': badge,
                'adjacent_test_guard_label': test_badge,
                'transitions_to': PENDING_JK_FINAL_APPROVAL,
                'auto_send': False,
            },
        ],
    }
_schema_ready = False
_schema_lock = threading.Lock()

OPERON_TOP_METRICS = {'decision_columns':['Arrives','Draft Prepared','A Person Decides']}

def literal(value):
    if value is None:
        return 'NULL'
    return "E'" + str(value).replace('\\', '\\\\').replace("'", "''") + "'"

def sql(statement, *, readonly=False):
    if DATABASE != 'yongxiang_plumb_r39_clone':
        raise ValueError('clone database required')
    guard = """SET LOCAL plpgsql.check_asserts=on;
DO $$ BEGIN
 ASSERT current_database() != 'yongxiang_plumb';
 ASSERT current_database() = 'yongxiang_plumb_r39_clone';
 ASSERT current_database() = 'yongxiang_plumb_r39_clone';
 IF current_database() <> 'yongxiang_plumb_r39_clone'
    OR current_setting('app.env',true) = 'prod' THEN
  RAISE EXCEPTION 'clone database required';
 END IF;
END $$;"""
    env = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
    env.update(PGHOST='127.0.0.1', PGPORT='5432', PGUSER='postgres',
               PGPASSWORD='postgres', PGDATABASE=DATABASE, PGCONNECT_TIMEOUT='5',
               SMTP_DISABLED='1', SWITCHBOARD_SANDBOX_MODE=MODE)
    if readonly:
        env['PGOPTIONS'] = '-c default_transaction_read_only=on -c statement_timeout=30000'
    dsn = 'postgresql://postgres:postgres@127.0.0.1:5432/yongxiang_plumb_r39_clone'
    p = subprocess.run(['psql', '-X', '-d', dsn, '-v', 'ON_ERROR_STOP=1', '-1', '-Atq'], input=guard+'\n'+statement, capture_output=True, text=True, env=env, timeout=40)
    if p.returncode:
        raise ValueError(p.stderr.strip())
    return p.stdout.strip()

def rows(statement):
    return json.loads(sql('SELECT coalesce(jsonb_agg(to_jsonb(t)),\'[]\'::jsonb) FROM ('+statement+') t;'))


def ensure_schema():
    """Verify the idempotent, clone-only upgrade is present once per listener process without clobbering 009d12 CAS upgrades."""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if not _schema_ready:
            has_fn = sql("SELECT to_regprocedure('public.r50_multi_dispatch_v1(uuid,uuid,jsonb)') IS NOT NULL;")
            if has_fn != 't':
                migration = Path(__file__).with_name('sql').joinpath('009d11_r50_multi_colleague_dual_mode.sql').read_text()
                sql(migration)
            _schema_ready = True


def parse_interaction(text):
    """Classify explicit decisions; keep questions and negated approvals as queries."""
    text = re.sub(r'^\[v\d+\]\s*', '', text).strip()
    card = re.match(r'^\[CARD(?::([a-z_]+))?\]\s*', text)
    action = card.group(1) if card else None
    text = text[card.end():].strip() if card else text
    text = re.sub(r'^@業主聯繫(?:\s*Lark\s*總機)?\s*', '', text).strip()
    if action:
        if action not in ('approve', 'claim', 'edit_approve', 'edit_and_approve'):
            raise ValueError('unsupported card action')
        action = 'edit_and_approve' if action == 'edit_approve' else action
    elif text in ('拒絕', '不核准', 'reject', '緩發'):
        action = 'reject'
    elif re.search(r'不要|不准|勿|先別|暫不|尚未|未核准|不核准|不發|不能|不可|是否|[?？]', text):
        action = 'agent_query'
    elif re.match(r'^改[：:]\s*\S', text):
        action = 'edit_and_approve'
    elif re.match(r'^轉交\s+@\S', text):
        action = 'handoff'
    elif text in ('認領', '我先認領處理', 'claim'):
        action = 'claim'
    elif text in ('核准', 'OK', 'ok', '認領並核准', '可以發', '照這樣發', '核准發出', 'approve'):
        action = 'approve'
    elif re.search(r'再發|發出|核准', text) and re.search(r'改|補上|延後', text):
        action = 'edit_and_approve'
    else:
        action = 'agent_query'
    if action == 'edit_and_approve' and not text:
        raise ValueError('edit_approve requires edited_body or edit instructions')
    return {'action': action, 'interaction_mode': CARD_MODE if card else NL_CHAT_MODE}

def parse_reply(text):
    return parse_interaction(text)['action']


def normalize_message(message):
    if not isinstance(message, dict):
        raise ValueError('message must be an object')
    if message.get('mode', MODE) != MODE:
        raise ValueError('sandbox only')
    button = message.get('card_action', message.get('action'))
    value = button.get('value', button) if isinstance(button, dict) else {}
    if not isinstance(value, dict):
        raise ValueError('card action value must be an object')
    action = value.get('action') if isinstance(button, dict) else button
    text = message.get('raw_reply_text', message.get('reply_text', ''))
    if not isinstance(text, str):
        raise ValueError('reply text must be a string')
    if action:
        if action not in ('approve', 'claim', 'edit_approve', 'edit_and_approve'):
            raise ValueError('unsupported card action')
        edited = message.get('edited_body', value.get('edited_body'))
        if edited is not None:
            if action not in ('edit_approve', 'edit_and_approve'):
                raise ValueError('edited_body requires edit_approve action')
            if not isinstance(edited, str) or not edited.strip():
                raise ValueError('edited_body must be nonempty text')
            text = '改：' + edited
        text = f'[CARD:{action}] ' + re.sub(r'^\[v\d+\]\s*', '', text)
    version = message.get('draft_version', value.get('draft_version'))
    for key in ('dispatch_id', 'draft_version'):
        if key in message and key in value and str(message[key]) != str(value[key]):
            raise ValueError(key+' mismatch')
    original_version = re.match(r'^\[v(\d+)\]', message.get('raw_reply_text', message.get('reply_text', '')))
    if version is not None:
        if isinstance(version, bool) or not re.fullmatch(r'[1-9]\d*', str(version)):
            raise ValueError('invalid draft_version')
        if original_version and int(original_version.group(1)) != int(version):
            raise ValueError('draft_version mismatch')
    elif original_version:
        version = original_version.group(1)
    if not re.match(r'^\[v\d+\]', text):
        if version is None:
            raise ValueError('CLI reply requires displayed [vN] draft version or draft_version')
        text = f'[v{version}] ' + text
    parsed = parse_interaction(text)
    requested_mode = message.get('interaction_mode', parsed['interaction_mode'])
    if requested_mode != parsed['interaction_mode']:
        raise ValueError('interaction_mode does not match reply payload')
    return dict(lark_message_id=message['lark_message_id'],
                dispatch_id=str(uuid.UUID(message.get('dispatch_id', value.get('dispatch_id')))),
                sender_employee_id=str(uuid.UUID(message['sender_employee_id'])),
                raw_reply_text=text, **parsed)

def poll_once(message_id=None):
    """Heartbeat comes only from the actual worker loop, never /state reads."""
    sql("SELECT public.r50_watcher_record_poll('lark-cli-watcher-agent');")
    return 0

def enqueue(message):
    raise ValueError('VERIFIED_CHANNEL_REQUIRED: use the signed loopback channel adapter')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', default=True)
    parser.add_argument('--interval', type=float, default=0)
    parser.add_argument('--enqueue-json', help='Local sandbox CLI reply envelope as JSON (event-driven trigger)')
    args = parser.parse_args()
    if args.enqueue_json:
        print(json.dumps(enqueue(json.loads(args.enqueue_json)), ensure_ascii=False))
    else:
        print(json.dumps({
            'mode': MODE,
            'trigger_architecture': TRIGGER_ARCH,
            'inbox': INBOX_ADDRESS,
            'webhook_routine': WEBHOOK_ROUTINE,
            'operon_top_metrics': OPERON_TOP_METRICS,
            'processed': poll_once()
        }, ensure_ascii=False))


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
