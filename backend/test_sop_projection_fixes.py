from collections import Counter
import httpx
import pytest
from sqlalchemy import select
from .test_sop_lark_projection import p, row
from .sop_import.models import LocalTask, LarkOutbox, TaskEvent
from .sop_import.lark_projection import ProjectionClient
from .live_read.rate_limit import BudgetExceeded


def test_33_tasks_converge_with_fresh_budgets(p):
    with p.sessions.begin() as db:
        for i in range(2, 34):
            db.add(LocalTask(workspace_id='lark-org', id=f't{i}', project_id='SRC-test', template_family_id='family',
                             source_row_key=f's{i}', instance_scope='case', snapshot={}, title=f'T{i}', instructions='',
                             participants={}, applicability='applicable', state='pending', revision=1, local={}))
    def factory(before):
        elapsed = [0.0]
        class Bucket:
            def acquire(self, deadline):
                elapsed[0] += .5
                if elapsed[0] > deadline:
                    raise BudgetExceeded()
            def penalize(self, until): pass
        return ProjectionClient(p.cfg, httpx.MockTransport(p.fake), before_write=before,
                                bucket=Bucket(), clock=lambda: elapsed[0])
    p.worker.client_factory = factory
    for _ in range(4):
        p.worker.drain(limit=20)
        p.clock[0] += 700
    with p.sessions() as db:
        assert sum(r.state == 'done' for r in db.scalars(select(LarkOutbox))) == 33
    counts = Counter(c[1] for c in p.fake.calls if c[0] == 'PUT')
    assert len(counts) == 33 and set(counts.values()) == {1}


def test_reconcile_failure_preserves_done(p):
    p.worker.drain()
    def fail(*args, **kwargs):
        from .node_assignment.errors import Failure
        raise Failure('lark_unavailable', 'temporary')
    p.worker.reconcile = fail
    p.clock[0] += 601
    p.worker.drain()
    assert row(p).state == 'done'
