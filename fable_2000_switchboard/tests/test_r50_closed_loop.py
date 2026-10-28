"""R50 clone integration checks. Ordinary fixtures roll back all writes.

The concurrency check keeps uniquely named sandbox audit records because ownership
must commit across two real PostgreSQL sessions to exercise the first-claim race.
"""
import concurrent.futures
import json
import threading
import uuid

import psycopg
import pytest

import lark_cli_watcher_agent as watcher
import r50_closed_loop_api as api

NAMES = ['吳柏頤', '涂振邦']


@pytest.fixture(scope='session', autouse=True)
def _guard_test_session_db():
    watcher.ensure_schema()
    assert watcher.sql('SELECT current_database();') == 'yongxiang_plumb_r39_clone'


def seed(conn):
    code = 'R50TEST-' + uuid.uuid4().hex
    state = dict(version=1, text='工程回覆。單價：20 萬，交期：2026-10-28。', subj='R50 sandbox verification')
    conn.execute("""INSERT INTO yezhu_workbench_case
        SELECT (jsonb_populate_record(NULL::yezhu_workbench_case,to_jsonb(w)||%s::jsonb)).*
        FROM yezhu_workbench_case w LIMIT 1""",
        (json.dumps(dict(code=code, pm=NAMES[0], letter_state=state)),))
    card = conn.execute('INSERT INTO r50_owner_draft(case_code) VALUES(%s) RETURNING card_id', (code,)).fetchone()[0]
    return str(card), code


@pytest.fixture
def sandbox(monkeypatch):
    with psycopg.connect(dbname=watcher.DATABASE) as conn:
        assert conn.execute('SELECT current_database()').fetchone()[0] != 'yongxiang_plumb'
        card, code = seed(conn)

        def transaction_sql(statement):
            try:
                with conn.transaction():
                    cursor = conn.cursor()
                    cursor.execute(statement)
                    output = []
                    while True:
                        if cursor.description:
                            for row in cursor.fetchall():
                                value = row[0]
                                output.append(json.dumps(value) if isinstance(value, (dict, list)) else str(value))
                        if not cursor.nextset():
                            break
                    return '\n'.join(output)
            except psycopg.Error as error:
                raise ValueError(str(error)) from error

        monkeypatch.setattr(watcher, 'sql', transaction_sql)
        monkeypatch.setattr(api, 'sql', transaction_sql)
        try:
            yield conn, card, code
        finally:
            conn.rollback()


def dispatch(card, action='dispatch-multi'):
    result = api.act(action, dict(card_id=card, recipient_names=NAMES))
    return {r['target_employee_name']: r for r in result['dispatches']}


def envelope(row, **kwargs):
    return dict(lark_message_id='r50-test-' + uuid.uuid4().hex,
                dispatch_id=row['dispatch_id'], sender_employee_id=row['target_employee_id'],
                draft_version=row['draft_version'], **kwargs)


@pytest.mark.parametrize('action', ['dispatch', 'dispatch-multi', 'push'])
def test_multi_dispatch_is_idempotent_and_atomic(sandbox, action):
    conn, card, _ = sandbox
    first = dispatch(card, action)
    assert {r['dispatch_id'] for r in first.values()} == {r['dispatch_id'] for r in dispatch(card, action).values()}
    assert len(first) == 2
    with pytest.raises(ValueError, match='unknown or ambiguous'):
        api.act(action, dict(card_id=card, recipient_names=[NAMES[0], 'missing-test-colleague']))
    assert conn.execute('SELECT count(*) FROM lark_cli_outbound_dispatch WHERE card_id=%s', (card,)).fetchone()[0] == 2


def test_approve_supersedes_peer_and_returns_collision_banner(sandbox):
    conn, card, _ = sandbox
    targets = dispatch(card)
    winner, peer = (targets[n] for n in NAMES)
    approved = api.act('card-action', envelope(winner, action={'value': {'action': 'approve'}}))
    assert approved['status'] == 'DONE'
    notice = conn.execute('SELECT notice_text,lark_cli_dryrun_cmd,dispatch_mode FROM r50_peer_lock_notification WHERE winning_dispatch_id=%s', (winner['dispatch_id'],)).fetchone()
    assert notice[0] == '🔒 此信件已由 吳柏頤 核准發出，系統已鎖定防重複回覆，您無須重複回覆。'
    assert '--dry-run' in notice[1] and notice[2] == watcher.MODE
    message = envelope(peer, raw_reply_text='核准發出')
    blocked = api.act('nl-chat', message)
    assert blocked['status'] == watcher.COLLISION_STATUS
    assert blocked['peer_lock_banner'] == notice[0]
    assert blocked['external_messages_sent'] == 0 and not blocked['ok']
    assert api.act('nl-chat', message) == blocked
    assert conn.execute('SELECT count(*) FROM r50_collision_interception_log WHERE blocked_dispatch_id=%s', (peer['dispatch_id'],)).fetchone()[0] == 1
    assert conn.execute('SELECT reply_status FROM lark_cli_outbound_dispatch WHERE dispatch_id=%s', (peer['dispatch_id'],)).fetchone()[0] == 'SUPERSEDED_BY_PEER'


def test_claim_does_not_send_and_owner_can_edit_then_approve(sandbox):
    conn, card, _ = sandbox
    targets = dispatch(card)
    winner, peer = (targets[n] for n in NAMES)
    assert api.act('card-action', envelope(winner, card_action='claim'))['ok']
    assert conn.execute('SELECT reply_status,jk_final_send_status FROM lark_cli_outbound_dispatch WHERE dispatch_id=%s', (winner['dispatch_id'],)).fetchone() == ('CLAIMED', 'PENDING_COLLEAGUE')
    assert api.act('reply', envelope(peer, raw_reply_text='還需要補哪些圖？'))['status'] == watcher.COLLISION_STATUS
    result = api.act('nl-chat', envelope(winner, raw_reply_text='@業主聯繫 Lark 總機 把單價改 18 萬、交期延後三天再發'))
    assert result['ok'] and result['interaction_mode'] == 'NL_CHAT_MODE'
    body = conn.execute('SELECT edited_body FROM lark_cli_inbound_reply WHERE lark_message_id=%s', (result['queued']['lark_message_id'],)).fetchone()[0]
    assert body == '工程回覆。單價：18 萬，交期：2026-10-31。'
    assert api.act('nl-chat', envelope(winner, raw_reply_text='核准發出，補上 Sheet 114 圖號'))['ok']
    assert api.act('card-action', envelope(winner, card_action='approve'))['ok']
    sent = api.act('final-send', dict(dispatch_id=winner['dispatch_id']))
    assert api.act('final-send', dict(dispatch_id=winner['dispatch_id'])) == sent
    final_body, synthetic = conn.execute('SELECT body_text,is_synthetic FROM client_communication WHERE id=%s', (sent['comm_id'],)).fetchone()
    assert '18 萬' in final_body and '2026-10-31' in final_body and 'Sheet 114' in final_body and synthetic
    assert conn.execute('SELECT count(*) FROM lark_cli_outbound_dispatch WHERE card_id=%s AND comm_id IS NOT NULL', (card,)).fetchone()[0] == 1
    modes = conn.execute("SELECT DISTINCT interaction_mode FROM colleague_agent_usage_event WHERE dispatch_id=%s AND event_type<>'dispatch'", (winner['dispatch_id'],)).fetchall()
    assert {r[0] for r in modes} == {'CARD_MODE', 'NL_CHAT_MODE'}


def test_structured_edit_approve_and_mode_usage(sandbox):
    conn, card, code = sandbox
    target = dispatch(card)[NAMES[0]]
    body = "更新後的完整草稿。附件路徑 C:\\drawings\\114。"
    result = api.act('card-action', envelope(target, card_action='edit_approve', edited_body=body))
    assert result['ok']
    assert conn.execute('SELECT edited_body FROM lark_cli_inbound_reply WHERE lark_message_id=%s', (result['queued']['lark_message_id'],)).fetchone()[0] == body
    overview = api.snapshot(code)
    assert overview['card_actions_count'] >= 1
    assert all('nl_chat_count' in u and 'card_actions_count' in u for u in overview['usage'])


def test_sender_and_version_failures_cannot_claim(sandbox):
    conn, card, code = sandbox
    targets = dispatch(card)
    winner, peer = (targets[n] for n in NAMES)
    wrong_sender = envelope(winner, raw_reply_text='核准')
    wrong_sender['sender_employee_id'] = peer['target_employee_id']
    result = api.act('reply', wrong_sender)
    assert result['status'] == 'REJECTED' and 'wrong sender' in result['error']
    stale = envelope(winner, raw_reply_text='核准')
    stale['draft_version'] = 2
    result = api.act('reply', stale)
    assert result['status'] == 'REJECTED' and 'stale reply draft_version' in result['error']
    conn.execute("UPDATE yezhu_workbench_case SET letter_state=jsonb_set(letter_state,'{version}','2') WHERE code=%s", (code,))
    result = api.act('reply', envelope(winner, raw_reply_text='核准'))
    assert result['status'] == 'REJECTED' and 'stale draft_version' in result['error']
    assert conn.execute('SELECT count(*) FROM r50_draft_claim WHERE card_id=%s', (card,)).fetchone()[0] == 0


def test_unsupported_partial_edit_cannot_approve(sandbox):
    conn, card, _ = sandbox
    target = dispatch(card)[NAMES[0]]
    result = api.act('reply', envelope(target, raw_reply_text='把單價改 18 萬、刪除附件再發'))
    assert result['status'] == 'REJECTED' and 'unsupported edit instructions' in result['error']
    assert conn.execute('SELECT reply_status FROM lark_cli_outbound_dispatch WHERE dispatch_id=%s', (target['dispatch_id'],)).fetchone()[0] == 'WAITING_COLLEAGUE'


def test_late_assignee_is_already_superseded_and_http_returns_banner(sandbox):
    conn, card, _ = sandbox
    winner = api.act('dispatch', dict(card_id=card, recipient_names=[NAMES[0]]))['dispatches'][0]
    api.act('reply', envelope(winner, raw_reply_text='核准發出'))
    peer = dispatch(card)[NAMES[1]]
    assert peer['reply_status'] == 'SUPERSEDED_BY_PEER'

    class Handler:
        path = '/api/r50/card-action'

        def _send(self, status, result):
            self.status, self.result = status, result

    handler = Handler()
    assert api.handle(handler, 'POST', envelope(peer, card_action='claim'))
    assert handler.status == 409 and handler.result['status'] == watcher.COLLISION_STATUS
    assert NAMES[0] in handler.result['peer_lock_banner']
    with pytest.raises(ValueError, match='superseded by peer'):
        api.act('final-send', dict(dispatch_id=peer['dispatch_id']))
    assert conn.execute('SELECT count(*) FROM lark_cli_outbound_dispatch WHERE card_id=%s AND comm_id IS NOT NULL', (card,)).fetchone()[0] == 0


def test_non_clone_target_is_rejected_before_connection(monkeypatch):
    monkeypatch.setattr(watcher, 'DATABASE', 'yongxiang_plumb')
    with pytest.raises(ValueError, match='clone database required'):
        watcher.sql('SELECT 1')


def test_database_guard_survives_disabled_asserts(sandbox):
    conn, _, _ = sandbox
    with pytest.raises(psycopg.Error, match='clone database required'):
        with conn.transaction():
            conn.execute("SET LOCAL plpgsql.check_asserts=off")
            conn.execute("SET LOCAL app.env='prod'")
            conn.execute('SELECT r50_safe()')


@pytest.mark.parametrize('text,action', [
    ('[v1] [CARD:claim]', 'claim'),
    ('[v1] [CARD] 核准', 'approve'),
    ('[v1] 把單價改 18 萬、交期延後三天再發', 'edit_and_approve'),
    ('[v1] 核准發出，補上 Sheet 114 圖號', 'edit_and_approve'),
    ('[v1] 不要核准發出，單價改 18 萬', 'agent_query'),
    ('[v1] 是否核准發出？', 'agent_query'),
    ('[v1] 不核准', 'reject'),
])
def test_python_and_database_parser_parity(sandbox, text, action):
    conn, _, _ = sandbox
    parsed = conn.execute('SELECT r50_parse_interaction(%s)', (text,)).fetchone()[0]
    assert watcher.parse_reply(text) == parsed['action'] == action
    assert watcher.parse_interaction(text)['interaction_mode'] == parsed['interaction_mode']


def test_reject_modes_versions_and_reused_message_payload(sandbox):
    _, card, _ = sandbox
    target = dispatch(card)[NAMES[0]]
    with pytest.raises(ValueError, match='sandbox only'):
        watcher.enqueue(envelope(target, raw_reply_text='核准', mode='LIVE'))
    with pytest.raises(ValueError, match='requires displayed'):
        watcher.enqueue({k:v for k,v in envelope(target, raw_reply_text='核准').items() if k != 'draft_version'})
    with pytest.raises(ValueError, match='unsupported card action'):
        watcher.enqueue(envelope(target, card_action='approve] injected'))
    msg = envelope(target, card_action='claim')
    assert api.act('card-action', msg)['ok']
    with pytest.raises(ValueError, match='idempotency payload mismatch'):
        watcher.enqueue(dict(msg, card_action='approve'))


def test_overview_route_and_artifacts(sandbox):
    class Handler:
        path = '/api/r50/overview'

        def _send(self, status, result):
            self.status, self.result = status, result

    handler = Handler()
    assert api.handle(handler, 'GET') and handler.status == 200
    data = handler.result
    assert data['operon_kpis']['time_from_arrival_to_logging'] == '18s'
    assert data['operon_kpis']['submittal_pricing_turnaround'] == '4.2m'
    assert [r['stage'] for r in data['operon_workflow_matrix']] == ['Arrives', 'Draft Prepared', 'A Person Decides']
    assert sum(r['count'] for r in data['drawing_diff_card']['rows']) == 22
    assert [r['confidence'] for r in data['survey_register_card']['items']] == [0.99,0.97,0.96]
    assert data['survey_register_card']['source'] == 'SANDBOX_FIXTURE'


def test_real_concurrent_first_claim_and_final_send(monkeypatch):
    run = watcher.subprocess.run
    commands = []

    def database_only(command, **kwargs):
        assert command[0] == 'psql'
        assert '-1' in command and command[command.index('-d')+1] == 'yongxiang_plumb_r39_clone'
        commands.append(command)
        return run(command, **kwargs)

    monkeypatch.setattr(watcher.subprocess, 'run', database_only)
    with psycopg.connect(dbname=watcher.DATABASE) as conn:
        card, _ = seed(conn)
    targets = dispatch(card)
    barrier = threading.Barrier(2)

    def reply(name):
        barrier.wait(timeout=10)
        return api.act('reply', envelope(targets[name], raw_reply_text='核准發出'))

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(reply, NAMES))
    assert sorted(r['status'] for r in outcomes) == [watcher.COLLISION_STATUS, 'DONE']
    winner = next(targets[name] for name,result in zip(NAMES,outcomes) if result['ok'])
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        sends = list(pool.map(lambda _: api.act('final-send', dict(dispatch_id=winner['dispatch_id'])), range(2)))
    assert sends[0]['comm_id'] == sends[1]['comm_id']
    assert all(r['external_messages_sent'] == 0 for r in outcomes+sends)
    assert watcher.rows('SELECT count(*) AS n FROM lark_cli_outbound_dispatch WHERE card_id='+watcher.literal(card)+' AND comm_id IS NOT NULL')[0]['n'] == 1
    assert commands
