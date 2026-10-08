"""VCC-97 P2-3: storage.save keeps index tables equal to a from-scratch rebuild."""
import random
from copy import deepcopy
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from backend import storage, index_tables
from backend.models import Base, BusinessRow, WorkspaceRow, ProjectIndex, TaskIndex, WorkspaceCounter
from backend.perf_fixture import build_scaled_workspace

STATUSES=('pending','in_progress','completed','approved_skipped')


def make(tmp_path,indexed,n=15):
    engine=create_engine('sqlite:///'+str(tmp_path/'m.db')); Base.metadata.create_all(engine)
    sessions=sessionmaker(engine,expire_on_commit=False,info={'index_tables':indexed})
    return engine,sessions


def commit(sessions,state):
    with sessions.begin() as db:
        row=db.get(WorkspaceRow,'w')
        if row is None: row=WorkspaceRow(id='w',version=0,data={}); db.add(row); db.flush()
        state['version']=row.version+1
        root=storage.save(db,BusinessRow,'w',state); row.version=state['version']; row.data=root


def load(sessions):
    with sessions() as db:
        row=db.get(WorkspaceRow,'w'); state=storage.load(db,BusinessRow,row); state['version']=row.version; return state


def rows(db,table):
    return sorted((tuple(sorted((k,v) for k,v in r._mapping.items() if k not in ('summary','source_version'))) for r in db.execute(select(table))))


def assert_matches_rebuild(sessions):
    state=load(sessions); projects,tasks=index_tables.project_rows('w',state)
    with sessions() as db:
        assert rows(db,TaskIndex.__table__)==sorted(tuple(sorted(t.items())) for t in tasks)
        got=rows(db,ProjectIndex.__table__)
        assert got==sorted(tuple(sorted((k,v) for k,v in p.items() if k not in ('summary','source_version'))) for p in projects)
        counters={(r.key,r.subject_id):r.value for r in db.execute(select(WorkspaceCounter.__table__))}
        assert counters==index_tables.counter_values(state)


def mutate(state,rng,serial):
    ps=state['projects']; p=rng.choice(ps); n=rng.choice(p['nodes']); t=rng.choice(n['tasks'])
    op=rng.randrange(9)
    if op==0: t['status']=rng.choice(STATUSES)
    elif op==1: t['owner_id']=rng.choice(state['users'])['id']
    elif op==2: t['due_date']=f'2026-11-{rng.randrange(1,28):02d}'
    elif op==3: n['tasks'].append(dict(deepcopy(t),id=f'new-t{serial}'))
    elif op==4 and len(n['tasks'])>1: n['tasks'].remove(t)
    elif op==5: ps.remove(p)
    elif op==6:
        q=deepcopy(p); q['id']=f'new-p{serial}'; q['code']=f'N{serial}'; q.update(files=[],comments=[],daily_reports=[])
        for node in q['nodes']:
            node['id']=f"{q['id']}-{node['key']}"
            for k,task in enumerate(node['tasks']): task['id']=f"{node['id']}-t{k}"
        ps.insert(rng.randrange(len(ps)+1),q)
    elif op==7: p['nodes'].reverse()
    else: state['approvals'].append(dict(id=f'na{serial}',project_id=p['id'],status=rng.choice(('pending','approved')),history=[])); state['daily_unmatched'].pop() if state['daily_unmatched'] else None


def test_random_mutations_keep_index_equal_to_rebuild(tmp_path):
    engine,sessions=make(tmp_path,True); state=build_scaled_workspace(15); commit(sessions,state); assert_matches_rebuild(sessions)
    rng=random.Random(97)
    for i in range(40):
        state=load(sessions)
        for _ in range(rng.randrange(1,4)):
            if state['projects'] and all(p['nodes'] for p in state['projects']): mutate(state,rng,f'{i}{rng.randrange(1000)}')
        commit(sessions,state); assert_matches_rebuild(sessions)
    engine.dispose()


def test_reorder_and_delete_all_projects(tmp_path):
    engine,sessions=make(tmp_path,True,4); state=build_scaled_workspace(4); commit(sessions,state)
    state=load(sessions); state['projects'].reverse(); commit(sessions,state); assert_matches_rebuild(sessions)
    state=load(sessions); state['projects']=[]; commit(sessions,state); assert_matches_rebuild(sessions)
    with sessions() as db: assert db.scalars(select(TaskIndex.__table__)).all()==[]
    engine.dispose()


def test_flag_off_writes_nothing(tmp_path):
    engine,sessions=make(tmp_path,False); commit(sessions,build_scaled_workspace(4))
    with sessions() as db:
        assert db.scalars(select(ProjectIndex.__table__)).all()==[] and db.scalars(select(WorkspaceCounter.__table__)).all()==[]
    engine.dispose()


def test_failed_save_rolls_back_index_with_records(tmp_path):
    engine,sessions=make(tmp_path,True,4); commit(sessions,build_scaled_workspace(4))
    state=load(sessions); state['projects'][0]['name']='changed'
    try:
        with sessions.begin() as db:
            storage.save(db,BusinessRow,'w',state); raise RuntimeError('409')
    except RuntimeError: pass
    assert_matches_rebuild(sessions)
    with sessions() as db: assert db.scalar(select(ProjectIndex.name).where(ProjectIndex.project_id==state['projects'][0]['id']))!='changed'
    engine.dispose()


def test_app_flag_wires_sessions_and_api_write_updates_index(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    from backend.models import AuditRow
    def app_for(flag):
        return create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/{flag}.db','UPLOAD_DIR':str(tmp_path/'u'),'SESSION_SECRET':'x'*40,'APP_ENV':'development','DEMO_MODE':'true','INDEX_TABLES_ENABLED':flag,'LARK_APP_ID':'','LARK_APP_SECRET':'','LARK_ALLOWED_TENANTS':''})
    off=app_for('false'); on=app_for('true')
    assert off.state.sessions().info['index_tables'] is False and on.state.sessions().info['index_tables'] is True
    with TestClient(on) as client:
        client.get('/api/session'); assert client.post('/api/demo/session',json={'user_id':'u-manager'}).status_code==200
        wid=on.state.signer.loads(client.cookies.get('meegle_session'))['wid']
        with on.state.sessions.begin() as db:
            row=db.get(WorkspaceRow,wid); state=storage.load(db,BusinessRow,row); state['version']=row.version+1
            row.version=state['version']; row.data=storage.save(db,BusinessRow,wid,state)
        with on.state.sessions() as db:
            assert db.scalar(select(ProjectIndex.project_id).where(ProjectIndex.workspace_id==wid)) is not None or not state['projects']
    for a in (off,on): a.state.engine.dispose()


def test_reconcile_repairs_generation_gap_even_when_rows_match(tmp_path):
    from backend import index_reads
    engine, sessions = make(tmp_path, True)
    state = build_scaled_workspace(2)
    commit(sessions, state)
    with sessions.begin() as db:
        db.info['index_tables'] = False
        row = db.get(WorkspaceRow, 'w')
        state = storage.load(db, BusinessRow, row)
        state['version'] = row.version + 1
        row.data = storage.save(db, BusinessRow, 'w', state)
        row.version = state['version']
    commit(sessions, load(sessions))
    with sessions.begin() as db:
        row = db.get(WorkspaceRow, 'w')
        state = storage.load(db, BusinessRow, row)
        assert index_reads.ready(db, BusinessRow, row) is False
        report = index_tables.reconcile(db, BusinessRow, 'w', state)
        assert report['healthy'] is False and report['dirty_projects'] == []
        index_tables.repair(db, BusinessRow, 'w', state, report)
        assert index_reads.ready(db, BusinessRow, row) is True
        assert index_tables.reconcile(db, BusinessRow, 'w', state)['healthy'] is True
    engine.dispose()
