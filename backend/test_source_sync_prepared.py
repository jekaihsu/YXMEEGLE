"""Changed snapshots keep diffs outside the lock and preserve concurrent local edits."""
from copy import deepcopy

import pytest
from sqlalchemy import event

from . import storage
from .test_source_sync import records, snapshot
from .test_source_sync_refresh_cost import harness, sqlite_harness, sync  # noqa: F401


def changed(h):
    rows=records()
    rows[0]['fields']['狀態']='已結案'
    h.clock[0]='2026-09-27T10:05:00+08:00'
    h.service.fetcher=lambda _: snapshot(h.clock[0],deepcopy(rows))


def test_changed_refresh_does_not_read_business_rows_under_the_lock(harness, monkeypatch):
    h=harness
    sync(h)
    changed(h)
    begin=h.sessions.begin
    locked=[False]; statements=[]; plans=[]
    class Locked:
        def __enter__(self):
            self.context=begin(); locked[0]=True
            return self.context.__enter__()
        def __exit__(self,*args):
            try: return self.context.__exit__(*args)
            finally: locked[0]=False
    monkeypatch.setattr(h.sessions,'begin',Locked)
    original=storage.prepare_save
    def prepare(*args,**kwargs):
        assert not locked[0]
        result=original(*args,**kwargs); plans.append(result)
        return result
    monkeypatch.setattr(storage,'prepare_save',prepare)
    def capture(conn,cursor,statement,parameters,context,many):
        if locked[0] and statement.lstrip().startswith('SELECT') and 'business_records' in statement:
            statements.append(statement)
    engine=h.sessions.kw['bind']
    event.listen(engine,'before_cursor_execute',capture)
    try: sync(h)
    finally: event.remove(engine,'before_cursor_execute',capture)
    state,_=h.read()
    assert state['projects'][0]['source_status']=='已結案'
    assert len(plans)==1 and plans[0]['writes']
    # Only immutable-event IDs and their ordinal floor may be queried at commit.
    assert all('business_records.data' not in statement for statement in statements)


@pytest.mark.parametrize('bump_version',[False,True])
def test_changed_plan_is_discarded_when_a_local_writer_commits(harness,monkeypatch,bump_version):
    h=harness
    sync(h)
    changed(h)
    prepare=h.service._prepare
    def raced(*args,**kwargs):
        prepared=prepare(*args,**kwargs)
        assert prepared['write_plan'] is not None
        with h.sessions.begin() as db:
            row=db.get(h.W,h.wid); state=storage.load(db,h.B,row)
            project=state['projects'][0]
            project['comments'].append({'id':'concurrent-comment','body':'retain me'})
            project['case_policy']={'local_decision':'retain me'}
            project['nodes'][0]['tasks'][0]['comments'].append({'id':'task-note','body':'retain me'})
            state['approvals'].append({'id':'local-approval','project_id':project['id'],'type':'extension','status':'draft','history':[]})
            if bump_version:
                row.version+=1; state['version']=row.version
            row.data=storage.save(db,h.B,h.wid,state)
        return prepared
    monkeypatch.setattr(h.service,'_prepare',raced)
    sync(h)
    state,_=h.read(); project=state['projects'][0]
    assert project['source_status']=='已結案'
    assert project['comments']==[{'id':'concurrent-comment','body':'retain me'}]
    assert project['case_policy']=={'local_decision':'retain me'}
    assert project['nodes'][0]['tasks'][0]['comments']==[{'id':'task-note','body':'retain me'}]
    assert any(a['id']=='local-approval' for a in state['approvals'])


def test_prepared_refresh_retains_local_business_state(harness,monkeypatch):
    h=harness
    sync(h)
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid); state=storage.load(db,h.B,row)
        project=state['projects'][0]
        project['comments'].append({'id':'local-comment','body':'keep me'})
        project['case_policy']={'local_decision':'keep me'}
        project['nodes'][0]['tasks'][0]['comments'].append({'id':'local-note','body':'keep me'})
        state['approvals'].append({'id':'local-approval','project_id':project['id'],'type':'extension','status':'draft','history':[]})
        row.data=storage.save(db,h.B,h.wid,state)
    # Revalidate after the local write, then change source content with a valid proof.
    sync(h)
    before,_=h.read()
    changed(h)
    def forbidden(*args,**kwargs): raise AssertionError('expected the prepared delta')
    with monkeypatch.context() as patch:
        patch.setattr(storage,'save',forbidden)
        sync(h)
    after,_=h.read()
    assert after['projects'][0]['source_status']=='已結案'
    assert after['projects'][0]['comments']==before['projects'][0]['comments']
    assert after['projects'][0]['case_policy']==before['projects'][0]['case_policy']
    assert after['projects'][0]['nodes'][0]['tasks']==before['projects'][0]['nodes'][0]['tasks']
    assert after['approvals']==before['approvals']
