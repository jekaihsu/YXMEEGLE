from types import SimpleNamespace
from .test_sop_lark_projection import p, row


def test_disabled_reads_do_not_wake_or_load_state(p):
    p.cfg['SOP_LARK_PROJECTION_ENABLED'] = 'false'
    p.worker.load_state = lambda wid: (_ for _ in ()).throw(AssertionError('disabled state load'))
    p.worker.request_reconcile('lark-org', 'SRC-test')
    assert not p.worker._wake.is_set()
    p.worker.drain()
