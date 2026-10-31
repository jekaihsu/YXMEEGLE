from .test_backend import app, client, role
from .test_ai_api import BODY, Fake, events, rows, live_server


def question(app, client):
    app.state.ai_providers = {'claude': Fake()}
    result = events(client.post('/api/ai/chat', json=BODY))
    assert result[0]['usage_id'] == rows(app)[-1].id
    return result[0]['usage_id']


def test_feedback_round_trip(app, client):
    from sqlalchemy import select
    from .ai.ledger import AiFeedbackRow
    uid = question(app, client)
    created = None
    for rating, reason in [('up', None), ('up', None), ('down', 'wrong'), ('none', None)]:
        body = dict(usage_id=uid, rating=rating, reason=reason)
        response = client.post('/api/ai/feedback', json=body)
        assert response.status_code == 200
        assert response.json() == body
        with app.state.sessions() as db:
            feedback = db.scalars(select(AiFeedbackRow)).all()
            if rating == 'none':
                assert feedback == []
            else:
                row, = feedback
                assert (row.rating, row.reason) == (1 if rating == 'up' else -1, reason)
                created = created or row.created_at
                assert row.created_at == created and row.updated_at >= row.created_at
    role(client, 'u-manager')
    assert client.get('/api/ai/usage').json()['totals']['feedback'] == dict(up=0, down=0, rated=0, up_rate=None)


def test_feedback_validation(app, client):
    uid = question(app, client)
    for extra in [dict(rating='bad'), dict(rating='up', reason='wrong'), dict(rating='none', reason='other'),
                  dict(rating='down', reason='bad'), dict(extra=True), dict(usage_id='')]:
        body = dict(usage_id=uid, rating='up')
        body.update(extra)
        assert client.post('/api/ai/feedback', json=body).status_code == 422


def test_feedback_ownership_and_unknown(app, client, monkeypatch):
    from time import perf_counter
    from .ai import ledger
    original = ledger.owns_usage
    lookups = []

    def counted(*args):
        lookups.append(args[-1])
        return original(*args)

    monkeypatch.setattr(ledger, 'owns_usage', counted)
    uid = question(app, client)
    role(client, 'u-control')
    started = perf_counter()
    responses = [client.post('/api/ai/feedback', json=dict(usage_id=value, rating='up')) for value in (uid, 'missing')]
    assert [r.status_code for r in responses] == [404, 404]
    assert responses[0].json() == responses[1].json()
    assert perf_counter() - started < 1
    assert lookups == [uid, 'missing']


def test_feedback_rate_limit(app, client):
    uid = question(app, client)
    for _ in range(60):
        assert client.post('/api/ai/feedback', json=dict(usage_id=uid, rating='up')).status_code == 200
    assert client.post('/api/ai/feedback', json=dict(usage_id=uid, rating='none')).status_code == 429


def test_feedback_wait_for_ledger_off_loop(app, client, live_server, monkeypatch):
    import httpx
    import threading
    from .ai import ledger
    entered, release = threading.Event(), threading.Event()
    original = ledger.record
    owns = ledger.owns_usage
    lookups = []

    def counted(*args):
        lookups.append(args[-1])
        return owns(*args)

    monkeypatch.setattr(ledger, 'owns_usage', counted)

    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        original(*args, **kwargs)
    monkeypatch.setattr(ledger, 'record', delayed)
    app.state.ai_providers = {'claude': Fake()}
    with httpx.Client(base_url=live_server, cookies=dict(client.cookies.items())) as connection:
        with connection.stream('POST', '/api/ai/chat', json=BODY) as response:
            import json
            uid = next(json.loads(line[6:])['usage_id'] for line in response.iter_lines() if line.startswith('data: '))
            assert entered.wait(2)
            timer = threading.Timer(.15, release.set)
            timer.start()
            try:
                assert connection.post('/api/ai/feedback', json=dict(usage_id=uid, rating='up')).status_code == 200
            finally:
                release.set()
                timer.join()
    assert lookups == [uid, uid]


def test_feedback_aggregation_and_rating_filters(app, client):
    from .ai.ledger import AiFeedbackRow
    from sqlalchemy import select
    role(client, 'u-manager')
    for provider, rating, reason in [('claude', 'up', None), ('gpt', 'down', 'wrong'),
                                     ('claude', 'down', 'slow'), ('gpt', None, None)]:
        app.state.ai_providers = {provider: Fake()}
        result = events(client.post('/api/ai/chat', json=dict(BODY, model=provider)))
        if rating:
            body = dict(usage_id=result[0]['usage_id'], rating=rating, reason=reason)
            assert client.post('/api/ai/feedback', json=body).status_code == 200
    result = client.get('/api/ai/usage').json()
    assert result['totals']['questions'] == 4
    assert result['totals']['feedback'] == dict(up=1, down=2, rated=3, up_rate=1/3)
    assert result['reasons'] == dict(wrong=1, incomplete=0, slow=1, other=0, unspecified=0)
    assert [(r['provider'], r['up'], r['down']) for r in result['by_provider']] == [('claude', 1, 1), ('gpt', 0, 1)]
    assert result['by_person'][0]['up'] == result['by_day'][0]['up'] == 1
    assert result['by_person'][0]['down'] == result['by_day'][0]['down'] == 2
    assert [(r['rating'], r['reason']) for r in result['recent']] == [(None, None), ('down', 'slow'), ('down', 'wrong'), ('up', None)]
    for rating, count in [('up', 1), ('down', 2), ('none', 1)]:
        filtered = client.get('/api/ai/usage', params=dict(rating=rating)).json()
        assert filtered['totals']['questions'] == count
        assert sum(r['questions'] for r in filtered['by_provider']) == count
        assert sum(r['questions'] for r in filtered['by_day']) == count
        assert sum(r['questions'] for r in filtered['by_person']) == count
        assert len(filtered['recent']) == count
        if rating == 'none':
            assert filtered['totals']['feedback']['up_rate'] is None
    assert client.get('/api/ai/usage?rating=bad').status_code == 422
    with app.state.sessions() as db:
        assert len(db.scalars(select(AiFeedbackRow)).all()) == 3


def test_postgres_statements_compile(app, client):
    from sqlalchemy.dialects import postgresql
    from sqlalchemy import event
    from .ai import ledger
    statements = []
    with app.state.sessions() as db:
        engine = db.get_bind()
    def check(conn, clause, *args):
        statements.append(str(clause.compile(dialect=postgresql.dialect())))
    event.listen(engine, 'before_execute', check)
    try:
        for rating in [None, 'up', 'down', 'none']:
            ledger.query(app.state.sessions, 'w', '2026-01-01', '2026-12-31', rating=rating)
    finally:
        event.remove(engine, 'before_execute', check)
    assert len(statements) == 28
    assert any('LEFT OUTER JOIN ai_feedback' in s for s in statements)
    assert 'ON CONFLICT (usage_id, actor_id) DO UPDATE' in str(ledger.feedback_statement('postgresql', 'u', 'a', 1, None).compile(dialect=postgresql.dialect()))


def test_usage_feedback_change_between_reads_keeps_snapshot(app, client, monkeypatch):
    from sqlalchemy.orm import Session
    from .ai import ledger
    uid = question(app, client)
    role(client, 'u-manager')
    with app.state.sessions() as db:
        db.connection().exec_driver_sql('PRAGMA journal_mode=WAL')
        usage = db.get(ledger.AiUsageRow, uid)
        actor = usage.actor_id
    original = Session.execute
    changed = False

    def interleaved(self, statement, *args, **kwargs):
        nonlocal changed
        result = original(self, statement, *args, **kwargs)
        if not changed and 'anon_1.rank' in str(statement):
            changed = True
            ledger.feedback(app.state.sessions, uid, actor, 'down', None)
        return result

    monkeypatch.setattr(Session, 'execute', interleaved)
    response = client.get('/api/ai/usage?rating=down')
    assert changed and response.status_code == 200
    result = response.json()
    assert result['totals']['questions'] == 0
    assert result['by_person'] == result['by_day'] == result['by_provider'] == result['recent'] == []
    assert client.get('/api/ai/usage?rating=down').json()['totals']['questions'] == 1


def test_usage_unspecified_down_reason_reconciles(app, client):
    uid = question(app, client)
    assert client.post('/api/ai/feedback', json=dict(usage_id=uid, rating='down')).status_code == 200
    role(client, 'u-manager')
    result = client.get('/api/ai/usage').json()
    assert result['reasons'] == dict(wrong=0, incomplete=0, slow=0, other=0, unspecified=1)
    assert sum(result['reasons'].values()) == result['totals']['feedback']['down']


def test_unknown_feedback_burst_has_one_lookup_per_id_and_no_write_budget(app, client, monkeypatch):
    from .ai import ledger, routes
    uid = question(app, client)
    original = ledger.owns_usage
    lookups = []

    def counted(*args):
        lookups.append(args[-1])
        return original(*args)

    async def no_polling(*args):
        raise AssertionError('unknown feedback must not poll or wait')

    monkeypatch.setattr(ledger, 'owns_usage', counted)
    monkeypatch.setattr(routes.asyncio, 'sleep', no_polling)
    for i in range(60):
        response = client.post('/api/ai/feedback', json=dict(usage_id=f'unknown-{i}', rating='up'))
        assert response.status_code == 404
        assert response.json() == {'detail': '找不到提問'}
    assert len(lookups) == 60
    assert client.post('/api/ai/feedback', json=dict(usage_id=uid, rating='up')).status_code == 200
