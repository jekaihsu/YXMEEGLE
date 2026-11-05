"""Request freshness must be bounded independently of retained source volume."""
from sqlalchemy import create_engine,event
from sqlalchemy.orm import Session,sessionmaker
from .models import Base,CacheRow
from .live_read.coordinator import RefreshCoordinator


def test_status_batches_datasets_and_does_not_decode_retained_snapshots(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'status.db'))
    Base.metadata.create_all(engine)
    sessions=sessionmaker(engine)
    coordinator=RefreshCoordinator(sessions,CacheRow,{'sources':None,'roster':None,'attendance':None},
        {'LARK_LIVE_READ_ENABLED':'true','LARK_WORKER_IDENTITY':'application'})
    with sessions.begin() as db:
        for dataset in ('sources','roster','attendance'):
            db.add(CacheRow(id=coordinator._key('lark-a',dataset),data={
                'as_of':'2020-01-01T00:00:00+08:00','snapshot':{'huge':'x'*1000000},
                'last_error':'denied' if dataset=='roster' else None,
                'error_code':'ReadNeedsPermission' if dataset=='roster' else None,
                'missing_scopes':['contact:read'] if dataset=='roster' else []}))
    decoded=[];queries=[]
    import json
    def decode(raw):decoded.append(len(raw));return json.loads(raw)
    engine.dialect._json_deserializer=decode
    engine.dialect._type_memos.clear();engine.clear_compiled_cache()
    def observe(conn,cur,statement,*_):queries.append(statement)
    event.listen(engine,'before_cursor_execute',observe)
    try:
        result=coordinator.status('lark-a')
        assert len(queries)==1
        assert sum(decoded)<2000
        assert result['datasets']['sources']['status']=='stale'
        assert result['datasets']['roster']['status']=='needs-permission'
        assert result['datasets']['roster']['missing_scopes']==['contact:read']
        assert coordinator.status('lark-b')['datasets']['sources']['status']=='never'
    finally:
        coordinator.close();engine.dispose()


def test_page_ensure_does_not_start_lark_but_backend_ensure_still_can(tmp_path):
    from .request_timing import Timings,_current
    engine=create_engine('sqlite:///'+str(tmp_path/'ensure.db'))
    Base.metadata.create_all(engine)
    sessions=sessionmaker(engine)
    calls=[]
    def refresh(wid):calls.append(wid);return {'fingerprint':'ok'}
    from .test_live_read_coordinator import SynchronousExecutor
    coordinator=RefreshCoordinator(sessions,CacheRow,{'sources':refresh},
        {'LARK_LIVE_READ_ENABLED':'true','LARK_WORKER_IDENTITY':'application'},executor=SynchronousExecutor())
    coordinator.executor.shutdown=lambda **_:None
    timing=Timings();timing.method='GET';token=_current.set(timing)
    try:
        assert coordinator.ensure('lark-a','sources')['status']=='never'
        assert calls==[]
    finally:_current.reset(token)
    try:
        assert coordinator.ensure('lark-a','sources',wait=True)['status']=='fresh'
        assert calls==['lark-a']
    finally:coordinator.close();engine.dispose()


def test_registered_identity_holders_keep_non_case_sources():
    from . import case_redaction as cr
    plan=cr.Plan(frozenset({'recVisibleCase'}),frozenset({'recHiddenCase'}),frozenset())
    out={key:['recHiddenCase','recWorkItem','recVisibleCase','recWorkItem']
         for key in ('source_visible_record_ids','record_ids','link_record_ids')}
    cr.apply(out,plan)
    assert all(value==['recWorkItem','recVisibleCase','recWorkItem'] for value in out.values())
    assert plan.fallback==0


def test_workspace_source_fence_is_one_atomic_query(tmp_path):
    from .models import WorkspaceRow
    from .source_metadata_reads import read_workspace_generation
    engine=create_engine('sqlite:///'+str(tmp_path/'fence.db'));Base.metadata.create_all(engine)
    statements=[]
    with Session(engine) as db:
        db.add(WorkspaceRow(id='a',version=9,data={}))
        db.add(CacheRow(id='a',data={'status':False,'last_attempt_at':{'nested':[1,None]},'last_sync':'null','as_of':0}))
        db.commit()
        def observe(conn,cur,statement,*_):statements.append(statement)
        event.listen(engine,'before_cursor_execute',observe)
        assert read_workspace_generation(db,CacheRow,WorkspaceRow,'a')==(9,False,{'nested':[1,None]},'null',0)
        assert len(statements)==1
        assert read_workspace_generation(db,CacheRow,WorkspaceRow,'missing')==(None,)*5
        db.delete(db.get(CacheRow,'a'));db.commit()
        assert read_workspace_generation(db,CacheRow,WorkspaceRow,'a')==(9,None,None,None,None)
    engine.dispose()
