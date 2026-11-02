"""Progress presentation stays independent of the fail-closed lifecycle gate."""
import pytest
from .test_lifecycle_fail_closed import setup, lark, BAD
from .operations import refresh_project_state, TECHNICAL, project_summary
from .workspace_projection import public_copy
from .company_dashboard import overview

@pytest.mark.parametrize('node_state,prior,expected', [
    (None, 'paused', 'pending'), ('pending', 'paused', 'pending'),
    ('in_progress', 'paused', 'in_progress'), ('rework', 'paused', 'in_progress'),
    ('completed', 'paused', 'in_progress'), (None, 'in_progress', 'in_progress'),
])
def test_unverified_progress(setup, node_state, prior, expected):
    ws,p,n,_=setup
    lark(p,BAD['blank'])
    n=next(node for node in p['nodes'] if node['key']=='sales')
    p['nodes']=[n] if node_state else []
    if node_state: n['status']=node_state
    p['execution_status']=prior
    refresh_project_state(p,ws)
    assert p['execution_status']==p['status']=='paused'
    assert p['progress_status']==expected
    refresh_project_state(p,ws)
    # Once fail-closed pauses execution, nodes remain the source of progress.
    assert p['progress_status']==(expected if node_state else 'pending')
    assert public_copy(p)['progress_status']==p['progress_status']
    assert project_summary(ws,p)['progress_status']==p['progress_status']
    row=overview(ws)['cases'][0]
    assert row['progress_status']==p['progress_status'] and row['execution_status']=='paused'


def test_declared_stop(setup):
    ws,p,n,_=setup
    lark(p,dict(state='mapped',canonical='中止',reasons=[]))
    p['nodes']=[n]; n['status']='in_progress'
    refresh_project_state(p,ws)
    assert p['progress_status']==p['execution_status']=='paused'


def test_engineering_completion_wins_over_lifecycle_gate(setup):
    ws,p,_,_=setup
    lark(p,BAD['blank'])
    p['nodes']=[n for n in p['nodes'] if n['key'] in TECHNICAL]
    for n in p['nodes']: n['status']='completed'
    refresh_project_state(p,ws)
    assert p['progress_status']==p['execution_status']=='engineering_complete'


def test_settlement_and_engineering_completed(setup):
    ws,p,_,_=setup
    lark(p,BAD['blank'])
    p['payment_reconciliation']={'confirmed': True}
    for n in p['nodes']: n['status']='completed'
    refresh_project_state(p,ws)
    assert p['progress_status']==p['execution_status']=='completed'
