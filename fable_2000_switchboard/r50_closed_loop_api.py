"""Clone-only API shared by Owner Communication and PM Solution (Operon 3-Section Dual-Mode + Single-Responder Lock + Event-Driven Inbox Trigger).
Enforces R52 Hard Locks #1 (PENDING_JK_FINAL_APPROVAL), #2 (ALLOWED_TEST_RECIPIENT = 'jekai@yxsurvey.com.tw'), and #3 (Explicit Recipient Badge).
"""
import json
import uuid
from lark_cli_watcher_agent import (
    ACTOR, ALLOWED_TEST_RECIPIENT, COLLISION_STATUS, INBOX_ADDRESS, MODE,
    OPERON_TOP_METRICS, PENDING_JK_FINAL_APPROVAL, TRIGGER_ARCH, WEBHOOK_ROUTINE,
    build_operon_workflow_card, enforce_test_recipient_allowlist, enqueue,
    ensure_schema, literal, rows, sql,
)


def operon_artifacts(collisions_prevented_count=0, db_kpis=None, db_matrix=None):
    from r50_part2_runtime import projection
    return projection()


def snapshot(case_code=None, dataset_kind='SANDBOX_OBSERVED'):
    from r50_part2_runtime import api_snapshot
    return api_snapshot(case_code, dataset_kind)


def dispatch(data, require_multi=False):
    """Resolve all assignees before atomically creating any dispatch rows."""
    if 'test_recipient' in data:
        enforce_test_recipient_allowlist(data['test_recipient'])
    card = str(uuid.UUID(data['card_id']))
    names = data.get('recipient_names')
    ids = data.get('target_employee_ids')
    if names is not None and ids is not None:
        raise ValueError('use recipient_names or target_employee_ids')
    if names is not None:
        if not isinstance(names, list) or not names or any(not isinstance(n, str) or not n.strip() for n in names):
            raise ValueError('recipient_names must be a nonempty list of names')
        names = list(dict.fromkeys(n.strip() for n in names))
        employees = rows('SELECT employee_id,employee_name FROM v_active_employee_directory WHERE employee_name IN ('+
                         ','.join(literal(n) for n in names)+')')
        targets = []
        for name in names:
            matches = [e['employee_id'] for e in employees if e['employee_name'] == name]
            if len(matches) != 1:
                raise ValueError('unknown or ambiguous active colleague: '+name)
            targets.append(matches[0])
    elif ids is not None:
        if not isinstance(ids, list) or not ids:
            raise ValueError('target_employee_ids must be a nonempty list')
        targets = list(dict.fromkeys(str(uuid.UUID(i)) for i in ids))
    elif data.get('target_employee_id'):
        targets = [str(uuid.UUID(data['target_employee_id']))]
    else:
        employees = rows("SELECT e.id FROM public.employee e JOIN public.yezhu_workbench_case w ON w.pm=e.full_name JOIN public.r50_owner_draft r ON r.case_code=w.code WHERE r.card_id="+literal(card)+" AND e.employment_status='active' AND e.org_id='YX'")
        if len(employees)!=1:
            raise ValueError('Select one active colleague for this draft')
        targets = [str(employees[0]['id'])]
    if require_multi and len(targets) < 2:
        raise ValueError('dispatch-multi requires at least two distinct colleagues')
    ensure_schema()
    dispatch_ids = json.loads(sql(f'SELECT r50_multi_dispatch_v1({literal(card)},{literal(ACTOR)},{literal(json.dumps(targets))}::jsonb);'))
    dispatched = rows('SELECT * FROM lark_cli_outbound_dispatch WHERE dispatch_id IN ('+
                      ','.join(literal(d) for d in dispatch_ids)+') ORDER BY created_at,dispatch_id')
    return dict(ok=True, mode=MODE, external_messages_sent=0,
                allowed_test_recipient=ALLOWED_TEST_RECIPIENT,
                dispatch_id=dispatch_ids[0], dispatch_ids=dispatch_ids, dispatches=dispatched)


def act(action, data):
    if not isinstance(data, dict):
        raise ValueError('payload must be an object')
    if data.get('mode', 'SANDBOX_LOOPBACK') != 'SANDBOX_LOOPBACK':
        raise ValueError('sandbox only')
    if 'test_recipient' in data or 'recipient_email' in data:
        enforce_test_recipient_allowlist(data.get('test_recipient') or data.get('recipient_email'))
    if action in ('push', 'dispatch', 'dispatch-multi'):
        return dispatch(data, require_multi=action=='dispatch-multi')
    if action in ('card-action', 'nl-chat'):
        from r50_part2_runtime import ingest
        result = ingest(data, 'card' if action=='card-action' else 'nl')
        outcome = result['outcome']
        jk_status = PENDING_JK_FINAL_APPROVAL if outcome in ('ACCEPTED_APPROVE', 'ACCEPTED_EDIT_APPROVE') else 'PENDING_COLLEAGUE'
        return dict(
            result,
            ok=outcome.startswith(('ACCEPTED', 'QUERY', 'CANDIDATE', 'ALREADY')),
            status=outcome,
            jk_final_send_status=jk_status,
            auto_send_blocked=True,
            allowed_test_recipient=ALLOWED_TEST_RECIPIENT,
            mode=MODE,
            external_messages_sent=0,
        )
    if action in ('reply', 'webhook-trigger', 'inbox-trigger'):
        raise ValueError('Use a verified card-action or nl-chat channel envelope')
    if action == 'final-send':
        target_rec = enforce_test_recipient_allowlist(data.get('test_recipient', ALLOWED_TEST_RECIPIENT))
        actor_id = str(data.get('actor_id') or ACTOR)
        if actor_id != ACTOR:
            raise ValueError('JK_FINAL_CONFIRMATION_REQUIRED: only JK can finalize send from PENDING_JK_FINAL_APPROVAL')
        from r50_part2_safety import connect
        with connect() as conn:
            result = conn.execute(
                'SELECT public.jk_finalize(%s,%s,%s,%s) r',
                (data['group_id'], ACTOR, data['approval_id'], data['approved_digest'])
            ).fetchone()['r']
        return dict(
            result,
            ok=result['outcome'] == 'SENT_FROM_JK_DRYRUN',
            mode=MODE,
            allowed_test_recipient=target_rec,
            external_messages_sent=0,
        )
    raise ValueError('unknown action')


def handle(handler, method, payload=None):
    from urllib.parse import urlparse, parse_qs
    path = urlparse(handler.path).path
    if not path.startswith('/api/r50/'):
        return False
    try:
        if method == 'GET' and path in ('/api/r50/state', '/api/r50/overview'):
            q = parse_qs(urlparse(handler.path).query)
            result = snapshot(q.get('case_code', [None])[0], q.get('dataset_kind', ['SANDBOX_OBSERVED'])[0])
        elif method == 'POST':
            result = act(path.rsplit('/', 1)[-1], payload or {})
        else:
            raise ValueError('unknown endpoint')
        handler._send(409 if not result.get('ok', True) or result.get('status') == COLLISION_STATUS else 200, result)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        handler._send(409, dict(ok=False, mode=MODE, external_messages_sent=0, error=str(error)))
    return True
