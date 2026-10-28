"""Verified sandbox event adapter and read-only Operon projection."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time
from r50_part2_safety import connect

SECRET_PATH = Path(__file__).with_name('.sandbox_context_key')


def _secret():
    if not SECRET_PATH.exists():
        try:
            fd = os.open(SECRET_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as f:
                f.write(secrets.token_bytes(32))
    return SECRET_PATH.read_bytes()


def issue_context(dispatch_id, actor_open_id):
    """Server-only issuance after resolving a recipient in the clone."""
    with connect() as c:
        row = c.execute('''SELECT d.dispatch_id,d.employee_id,g.card_id,g.draft_version,h.current_digest,
          e.lark_open_id FROM public.dispatch d JOIN public.dispatch_group g ON g.dispatch_group_id=d.group_id
          JOIN public.draft_head h ON h.card_id=g.card_id JOIN public.employee e ON e.id=d.employee_id
          WHERE d.dispatch_id=%s AND e.lark_open_id=%s AND e.employment_status='active' ''',
          (dispatch_id, actor_open_id)).fetchone()
    if row is None:
        raise ValueError('NOT_RECIPIENT')
    data = dict(dispatch_id=str(row['dispatch_id']), actor_open_id=actor_open_id,
                draft_version=row['draft_version'], digest=row['current_digest'],
                nonce=secrets.token_hex(16), expires=int(time.time())+3600)
    encoded = base64.urlsafe_b64encode(json.dumps(data, sort_keys=True).encode()).decode()
    return encoded + '.' + hmac.new(_secret(), encoded.encode(), hashlib.sha256).hexdigest()


def verify_context(token):
    encoded, sig = token.split('.', 1)
    if not hmac.compare_digest(sig, hmac.new(_secret(), encoded.encode(), hashlib.sha256).hexdigest()):
        raise ValueError('UNAUTHORIZED_CONTEXT')
    data = json.loads(base64.urlsafe_b64decode(encoded))
    if data['expires'] < time.time():
        raise ValueError('EXPIRED_CONTEXT')
    return data


def parse_nl(text, current_version):
    """Only the two exact, versioned approval grammars can approve."""
    match = re.fullmatch(r'\[v([1-9]\d*)\]\s*(核准|OK|改：([\s\S]+))', text.strip())
    if match:
        if int(match[1]) != current_version:
            return {'intent': 'STALE', 'version': int(match[1]), 'payload': {'raw_text': text}}
        return {'intent': 'EDIT_APPROVE' if match[3] else 'APPROVE',
                'version': int(match[1]), 'payload': {'raw_text': text, 'body': match[3]}}
    if re.search(r'改|補上|延後|調整', text):
        return {'intent': 'NL_ADJUST', 'version': current_version,
                'payload': {'raw_text': text, 'requires_confirmation': True}}
    if re.search(r'可以吧|如果|核准|就發|認領', text):
        return {'intent': 'CLARIFY_REPLY', 'version': current_version, 'payload': {'raw_text': text}}
    return {'intent': 'QUERY', 'version': current_version, 'payload': {'raw_text': text}}


def ingest(message, channel):
    """channel is selected by the verified server endpoint, never parsed from text.

    Only the signed local loopback adapter is supported. Vendor event IDs and
    vendor delivery/idempotency semantics remain outside this sandbox contract.
    """
    if channel not in ('card', 'nl'):
        raise ValueError('VERIFIED_CHANNEL_REQUIRED')
    ctx = verify_context(message['context_token'])
    if message.get('actor_open_id') != ctx['actor_open_id']:
        raise ValueError('UNAUTHORIZED_ACTOR')
    with connect() as c:
        emp = c.execute('SELECT id FROM public.employee WHERE lark_open_id=%s AND employment_status=\'active\'',
                        (ctx['actor_open_id'],)).fetchone()
        if emp is None:
            raise ValueError('ACTOR_INACTIVE')
        if channel == 'card':
            event = message['callback_event_id']
            intent = message['intent']
            if intent not in ('CLAIM','APPROVE','EDIT_APPROVE','REJECT','HANDOFF_SUGGEST'):
                raise ValueError('unsupported card intent')
            version = ctx['draft_version']
            payload = {'body': message.get('body')}
        else:
            event = message['message_id']
            parsed = parse_nl(message['text'], ctx['draft_version'])
            intent, version, payload = parsed['intent'], parsed['version'], parsed['payload']
        return c.execute('SELECT public.handle_action(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) r',
            ('sandbox:verified',event,ctx['dispatch_id'],emp['id'],
             'CARD_MODE' if channel == 'card' else 'NL_CHAT_MODE',intent,version,ctx['digest'],
             json.dumps(payload))).fetchone()['r']


def projection(case_code=None, dataset_kind='SANDBOX_OBSERVED'):
    if dataset_kind not in ('REHEARSAL', 'SANDBOX_OBSERVED', 'LIVE'):
        raise ValueError('Unknown dataset cohort')
    with connect() as c:
        c.execute("SELECT set_config('app.usage_dataset_kind',%s,false)", (dataset_kind,))
        rows = c.execute('SELECT * FROM public.r50_workflow_matrix_v WHERE dataset_kind=%s AND (%s::text IS NULL OR case_code=%s) ORDER BY case_code,card_id',
                         (dataset_kind,case_code,case_code)).fetchall()
        metrics = c.execute('SELECT * FROM public.r50_workflow_metrics_v WHERE dataset_kind=%s',
                            (dataset_kind,)).fetchall()
        usage = c.execute('SELECT * FROM public.r50_usage_summary_v').fetchall()
        records = c.execute('''SELECT f.* FROM public.r50_pm_finalized_v f JOIN public.r50_work_item w USING(card_id)
             WHERE w.dataset_kind=%s AND (%s::text IS NULL OR w.case_code=%s)
             ORDER BY finalized_at DESC LIMIT 30''',(dataset_kind,case_code,case_code)).fetchall()
        collisions = c.execute('''SELECT count(*) n FROM public.dispatch d JOIN public.dispatch_group g
           ON g.dispatch_group_id=d.group_id JOIN public.r50_work_item w USING(card_id)
           WHERE d.status='SUPERSEDED_BY_PEER' AND w.dataset_kind=%s''',(dataset_kind,)).fetchone()['n']
        blocked = c.execute('''SELECT count(*) n FROM public.action_event
           WHERE outcome LIKE 'COLLISION_BLOCKED%%' AND dataset_kind=%s''',(dataset_kind,)).fetchone()['n']
        deadlines = c.execute('''SELECT count(*) FILTER(WHERE deadline_at IS NOT NULL) n,
          count(*) FILTER(WHERE deadline_at IS NOT NULL AND coalesce(f.finalized_at,clock_timestamp())>deadline_at) missed
          FROM public.r50_work_item w LEFT JOIN public.finalization f USING(card_id) WHERE w.dataset_kind=%s''',
          (dataset_kind,)).fetchone()
    return dict(operon_db_workflow_matrix=rows,operon_workflow_rows=rows,
        operon_workflow_matrix=[dict(stage=s) for s in ('Arrives','Draft Prepared','A Person Decides')],
        operon_metrics=metrics,operon_kpis=dict(dataset_kind=dataset_kind,collisions_prevented_count=collisions,
             blocked_attempts=blocked,deadlines_missed=deadlines['missed'] if deadlines['n'] else None,
             deadlines_cohort_n=deadlines['n'],collision_definition='被 superseded 的 peer 派工數'),
        operon_top_metrics={'decision_columns':['Arrives','Draft Prepared','A Person Decides']},
        drawing_diff_card=None,survey_register_card=None,usage=usage,records=records,
        actual_sends=0,external_messages_sent=0)


def api_snapshot(case_code=None, dataset_kind='SANDBOX_OBSERVED'):
    """Canonical read-only snapshot for both the existing screen and review UI."""
    result = projection(case_code, dataset_kind)
    with connect() as c, c.transaction():
        c.execute('SET TRANSACTION READ ONLY')
        dispatches = c.execute('''SELECT x.*, d.status canonical_status,g.dispatch_group_id group_id,
           g.active_approval_id approval_id,a.approved_digest,e.lark_open_id actor_open_id
           FROM public.dispatch d JOIN public.lark_cli_outbound_dispatch x USING(dispatch_id)
           JOIN public.dispatch_group g ON g.dispatch_group_id=d.group_id
           JOIN public.draft_head h ON h.card_id=g.card_id AND h.current_version=g.draft_version
           JOIN public.r50_work_item w ON w.card_id=g.card_id
           JOIN public.employee e ON e.id=d.employee_id
           LEFT JOIN public.approval_snapshot a ON a.approval_id=g.active_approval_id
           WHERE w.dataset_kind=%s AND (%s::text IS NULL OR w.case_code=%s)
           ORDER BY x.created_at DESC LIMIT 50''',(dataset_kind,case_code,case_code)).fetchall()
        drafts = c.execute('''SELECT h.card_id,w.case_code,h.current_version draft_version
           FROM public.draft_head h JOIN public.r50_work_item w USING(card_id)
           WHERE w.dataset_kind=%s AND (%s::text IS NULL OR w.case_code=%s)''',
           (dataset_kind,case_code,case_code)).fetchall()
        watcher = c.execute('SELECT *,watcher_alive alive FROM public.r50_watcher_status_v').fetchall()
    for d in dispatches:
        if d['actor_open_id']:
            try:
                d['context_token'] = issue_context(d['dispatch_id'],d['actor_open_id'])
            except ValueError:
                d['context_token'] = None
    result.update(ok=True,mode='SANDBOX_LOOPBACK',dispatches=dispatches,drafts=drafts,
        watcher=watcher,watcher_alive=any(w['watcher_alive'] for w in watcher),
        replies=[],peer_lock_notifications=[],collision_interceptions=[],queue=[],
        card_actions_count=sum(u['card_actions_count'] for u in result['usage']),
        nl_chat_count=sum(u['nl_chat_turns_count'] for u in result['usage']),
        trigger_architecture='SANDBOX_LOOPBACK',dataset_kind=dataset_kind)
    return result


def save_revision(case_code, letter, expected_version):
    """Legacy screens use the same atomic version transition, with stale checks."""
    with connect() as c, c.transaction():
        cards = c.execute('SELECT card_id FROM public.r50_owner_draft WHERE case_code=%s',(case_code,)).fetchall()
        if not cards:
            return None
        if len(cards)!=1:
            raise ValueError('Select the specific inbound work item before revising')
        card=cards[0]['card_id']
        # Same aggregate -> root order as lock_group; no child locks held here.
        c.execute('SELECT 1 FROM public.yezhu_workbench_case WHERE code=%s FOR UPDATE',(case_code,))
        h=c.execute('SELECT * FROM public.draft_head WHERE card_id=%s FOR UPDATE',(card,)).fetchone()
        if int(expected_version)!=h['current_version']:
            raise ValueError('STALE_DRAFT_VERSION')
        body=letter.get('body',letter.get('text',''))
        version=c.execute('SELECT public.bump_draft_version(%s,%s) v',(card,body)).fetchone()['v']
        letter=dict(letter,body=body,text=body,version=version)
        from psycopg.types.json import Jsonb
        c.execute('UPDATE public.yezhu_workbench_case SET letter_state=%s WHERE code=%s',(Jsonb(letter),case_code))
        return version
