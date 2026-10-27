from .test_sop_projection_fixes import p, row, LocalTask, ProjectionClient, httpx


def test_search_404_does_not_create_generation(p):
    p.worker.drain()
    with p.sessions.begin() as db:
        task = db.get(LocalTask, ('lark-org', 't1'))
        task.title, task.revision = 'edit', 2
    original = p.fake.__call__
    remaining = [1]
    def missing_search(request):
        if request.url.path.endswith('/search') and remaining[0]:
            remaining[0] -= 1
            return httpx.Response(404, json={'code': 1254041, 'data': {}})
        return original(request)
    p.worker.client_factory = lambda before: ProjectionClient(p.cfg, httpx.MockTransport(missing_search), before_write=before)
    p.worker.drain()
    assert row(p).generation == 1
    p.clock[0] += 700
    p.worker.drain()
    assert len(p.fake.records) == 1 and row(p).state == 'done'


def test_third_deleted_generation_pauses(p):
    from .sop_import.outbox import latest
    p.worker.drain()
    del p.fake.records['rec1']
    with p.sessions.begin() as db:
        current = latest(db, 'lark-org', 'SRC-test', 't1')
        current.generation, current.state = 3, 'none'
    p.worker.drain()
    assert row(p).generation == 3
    assert row(p).state == 'paused' and row(p).last_error == 'generation_limit'
