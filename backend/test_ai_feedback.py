from .test_backend import app, client, role
from .test_ai_api import BODY, Fake, events, rows


def question(app, client):
    app.state.ai_providers = {'claude': Fake()}
    result = events(client.post('/api/ai/chat', json=BODY))
    assert result[0]['usage_id'] == rows(app)[-1].id
    return result[0]['usage_id']


def test_feedback_round_trip(app, client):
    uid = question(app, client)
    for rating, reason in [('up', None), ('up', None), ('down', 'wrong'), ('none', None)]:
        body = dict(usage_id=uid, rating=rating, reason=reason)
        response = client.post('/api/ai/feedback', json=body)
        assert response.status_code == 200
        assert response.json() == body
    role(client, 'u-manager')
    assert client.get('/api/ai/usage').json()['totals']['feedback'] == dict(up=0, down=0, rated=0, up_rate=None)


def test_feedback_validation(app, client):
    uid = question(app, client)
    for extra in [dict(rating='bad'), dict(rating='up', reason='wrong'), dict(rating='none', reason='other'),
                  dict(rating='down', reason='bad'), dict(extra=True), dict(usage_id='')]:
        body = dict(usage_id=uid, rating='up')
        body.update(extra)
        assert client.post('/api/ai/feedback', json=body).status_code == 422


def test_feedback_ownership_and_unknown(app, client):
    uid = question(app, client)
    role(client, 'u-control')
    responses = [client.post('/api/ai/feedback', json=dict(usage_id=value, rating='up')) for value in (uid, 'missing')]
    assert [r.status_code for r in responses] == [404, 404]
    assert responses[0].json() == responses[1].json()


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
    assert result['reasons'] == dict(wrong=1, incomplete=0, slow=1, other=0)
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


def test_postgres_statements_compile(app, client, monkeypatch):
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
    assert any('LEFT OUTER JOIN ai_feedback' in s for s in statements)
    assert 'ON CONFLICT (usage_id, actor_id) DO UPDATE' in str(ledger.feedback_statement('postgresql', 'u', 'a', 1, None).compile(dialect=postgresql.dialect()))


from .test_ai_api import live_server
