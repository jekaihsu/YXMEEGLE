from .test_sop_projection_gates import p, row, SimpleNamespace


def test_disabled_status_hides_receipt_coordinates(p):
    p.worker.drain()
    p.cfg['SOP_LARK_PROJECTION_ENABLED'] = 'false'
    with p.sessions() as db:
        from .sop_import.models import LocalTask
        status = p.worker.status(db, SimpleNamespace(wid='lark-org', state=p.state, project=p.project),
                                 db.get(LocalTask, ('lark-org', 't1')))
    assert status['state'] == '未啟用'
    assert not any(status.get(key) for key in ('base_id', 'table_id', 'record_id'))
