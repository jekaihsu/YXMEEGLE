from sqlalchemy import event
from .test_sop_lark_projection import p, row
from .sop_import.lark_projection import drain_lock


def test_complete_does_not_erase_newer_enqueue(p):
    p.worker.drain()
    values = p.fake.records['rec1']['fields']
    from .sop_import.outbox import latest
    with p.sessions.begin() as db:
        latest(db, 'lark-org', 'SRC-test', 't1').state = 'none'
    injected = [False]
    def enqueue_before_update(connection, cursor, statement, parameters, context, many):
        if statement.startswith('UPDATE sop_lark_outbox') and not injected[0]:
            injected[0] = True
            connection.exec_driver_sql("UPDATE sop_lark_outbox SET target_revision=2, state='none'")
    event.listen(p.engine, 'before_cursor_execute', enqueue_before_update)
    try:
        p.worker.complete('lark-org', 'SRC-test', 't1', values)
    finally:
        event.remove(p.engine, 'before_cursor_execute', enqueue_before_update)
    assert injected[0]
    assert (row(p).target_revision, row(p).state) == (2, 'none')
