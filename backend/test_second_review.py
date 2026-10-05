"""Second independent audit: local safety evidence and explicit known gaps."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from .seed import seed
from .policy import upgrade
from .sources import import_sources
from .test_source_identity import confirmation, record, quote
from .test_node_skip import applied, node
from .node_skip import valid_waiver
from .operations import apply_operation


def test_new_daily_replay_never_creates_case_or_completes_work():
    ws = seed(True)
    rows = [confirmation('recC1')]
    import_sources(ws, rows)
    before = [(p['id'], [(n['id'], n['status'], [(t['id'], t['status']) for t in n['tasks']])
                         for n in p['nodes']]) for p in ws['projects']]
    daily = record('daily', 'new-acceptance', {'所屬案件': ['recC1'], '日期': '2026-09-27',
                   '組別': '控制', '檢核狀態': '已通過', '工作內容': '新日報驗收'})
    for _ in range(3):
        result = import_sources(ws, rows + [daily])
        assert result['daily_imported'] == 1
        assert before == [(p['id'], [(n['id'], n['status'], [(t['id'], t['status']) for t in n['tasks']])
                                    for n in p['nodes']]) for p in ws['projects']]
        assert len(ws['projects'][0]['daily_reports']) == 1
    empty = seed(True)
    result = import_sources(empty, [daily])
    assert empty['projects'] == [] and result['daily_unmatched'] == 1


def test_daily_known_plus_unknown_native_reference_requires_review():
    ws = seed(True)
    result = import_sources(ws, [confirmation('recC1'), record('daily', 'd', {
        '所屬案件': ['recC1', 'recNotLoaded'], '日期': '2026-09-27', '組別': '控制'})])
    assert result['daily_imported'] == 0 and result['daily_unmatched'] == 1


def test_related_contract_remap_invalidates_previous_manual_daily_match():
    ws = seed(True)
    ws['environment']='test'
    ws['users'] = deepcopy(seed()['users'])
    rows = [confirmation('recC1'), confirmation('recC2', 'C115002'),
            record('contract', 'recContract1', {'所屬成案確認單（日報關聯）': ['recC1']}),
            record('reporting', 'recReport1', {'來源合約明細（日報關聯）': ['recContract1'], '工項類別': '控制'}),
            record('daily', 'd1', {'合約工項': ['recReport1'], '日期': '2026-09-27', '組別': '控制'})]
    import_sources(ws, rows)
    p = next(p for p in ws['projects'] if p['code'] == 'C115001')
    user = next(u for u in ws['users'] if u['role'] == 'manager')
    p['pm_id']=user['id']  # Explicit case assignment, not an implicit system privilege.
    daily_id = p['daily_reports'][0]['id']
    apply_operation(ws, user, {'action': 'daily_propose', 'project_id': p['id'],
                    'payload': {'daily_id': daily_id, 'reason': '已核對關聯'}}, True)
    review = ws['daily_reviews'][-1]
    apply_operation(ws, user, {'action': 'daily_approve', 'project_id': p['id'],
                    'payload': {'id': review['id']}}, True)
    rows[2]['fields']['所屬成案確認單（日報關聯）'] = ['recC2']
    import_sources(ws, rows)
    assert review['status'] != 'approved'
    assert not any(d['id'] == daily_id and d.get('match_basis') == 'manual_review'
                   for d in p['daily_reports'])


def test_quote_scope_change_invalidates_existing_waiver():
    ws = upgrade(seed()); ws['environment'] = 'test'
    p = ws['projects'][0]; p['supervisor_id'] = 'u-manager'
    p['quotes'] = [{'id': 'q1', 'fields': {'確認範圍': '原範圍'}}]
    applied(ws)
    p['quotes'][0]['fields']['確認範圍'] = '新增原跳過工項'
    assert not valid_waiver(ws, p, node(ws))


def test_cross_project_workspace_cas_blocks_stale_write_without_losing_either_action(tmp_path):
    from .app import create_app
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/cas.db', 'UPLOAD_DIR': str(tmp_path/'uploads'),
                      'SESSION_SECRET': 'review-cas-secret'*3, 'APP_ENV': 'development', 'DEMO_MODE': 'true'})
    client = TestClient(app)
    assert client.get('/api/session').status_code == 200
    before = client.get('/api/workspace').json()
    first = {'action': 'comment_add', 'version': before['version'], 'request_id': 'first-case',
             'project_id': 'p1', 'payload': {'body': 'case one'}}
    second = dict(first, request_id='second-case', project_id='p2', payload={'body': 'case two'})
    a = client.post('/api/actions', json=first)
    assert a.status_code == 200
    b = client.post('/api/actions', json=second)
    assert b.status_code == 409
    assert any(c['body'] == 'case one' for p in a.json()['projects'] if p['id'] == 'p1' for c in p['comments'])
    second['version'] = client.get('/api/workspace').json()['version']
    b = client.post('/api/actions', json=second)
    assert b.status_code == 200
    for pid, content in [('p1', 'case one'), ('p2', 'case two')]:
        assert sum(c['body'] == content for p in b.json()['projects'] if p['id'] == pid for c in p['comments']) == 1
    # Same request id replays despite old workspace version; no duplicate comment.
    assert client.post('/api/actions', json=first).status_code == 200


def test_learning_mapping_revoke_during_read_cannot_publish_verified_mapping(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from . import integration_routes, storage
    from . import features
    monkeypatch.setattr(features, 'FEATURE_LEARNING', True)  # Isolate guard; production remains disabled.
    from .app import create_app, WorkspaceRow, PersonRow, AuthRow, BusinessRow
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/revoke.db', 'UPLOAD_DIR': str(tmp_path/'uploads'),
                      'SESSION_SECRET': 'review-revoke-secret'*3, 'APP_ENV': 'development', 'DEMO_MODE': 'true'})
    wid = 'lark-review'; state = upgrade(seed()); state['environment'] = 'production'
    manager = next(u for u in state['users'] if u['id'] == 'u-manager')
    with app.state.sessions.begin() as db:
        db.add(WorkspaceRow(id=wid, version=1, data=state))
        db.add(PersonRow(organization_id=wid, person_id=manager['id'], data=deepcopy(manager)))
        db.add(AuthRow(id='audit-session', data={'wid': wid, 'expires': 9999999999}))

    def verify_mapping(_):
        with app.state.sessions.begin() as db:
            profile = db.get(PersonRow, (wid, manager['id']))
            profile.data = dict(profile.data, role='member', capabilities=[])
        return None

    fake = SimpleNamespace(client=SimpleNamespace(close=lambda: None), verify_training_mapping=verify_mapping)
    monkeypatch.setattr(integration_routes, 'application_adapter', lambda _: fake)
    client = TestClient(app)
    client.cookies.set('meegle_session', app.state.signer.dumps(
        {'mode': 'lark', 'uid': manager['id'], 'wid': wid, 'sid': 'audit-session'}))
    response = client.post('/api/learning/mappings/verify', json={
        'version': 1, 'mapping': {'id': 'audit-map', 'base_token': 'fake', 'table_id': 'fake', 'fields': {}}})
    with app.state.sessions() as db:
        saved = storage.load(db, BusinessRow, db.get(WorkspaceRow, wid))
    assert response.status_code == 403
    assert not saved.get('learning_mappings')


def test_upload_rechecks_live_manager_authority_after_file_read(tmp_path, monkeypatch):
    import time
    from datetime import datetime, timezone
    from pathlib import Path
    import json
    from sqlalchemy import select
    from . import storage
    from .app import WorkspaceRow, PersonRow, AuthRow, BusinessRow, AuditRow
    from .test_production_access import company

    app, client = company(tmp_path)
    app.state.cfg['LARK_COMPANY_ADMIN_GRANTS_JSON']=json.dumps([{
        'open_id':'u-manager','app_id':'app1','tenant':'company','grant_id':'test-grant',
        'reason':'regression test','authorized_by':'owner','decision_ref':'test-decision',
        'authorized_at':datetime.now(timezone.utc).isoformat(),'enabled':True,'role':'manager',
        'scopes':['company:ordinary_business_backup']}])
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,'test-lark-company')
        state=storage.load(db,BusinessRow,row)
        manager=next(u for u in state['users'] if u['id']=='u-manager')
        manager['role']='manager'
        manager['oauth_identity']={'source':'oauth_user_info','app_id':'app1','tenant':'company',
                                   'open_id':'u-manager','verified_at':datetime.now(timezone.utc).isoformat()}
        manager['directory_last_seen_at']=datetime.now(timezone.utc).isoformat()
        manager['directory_status']='employed'
        manager['directory_missing']=False
        manager['directory_source']={'app_id':'app1','record_id':'manager'}
        row.data=storage.save(db,BusinessRow,row.id,state)
        db.add(AuthRow(id='sid-upload',data={'wid':'test-lark-company','expires':time.time()+3600}))
    client.cookies.set('meegle_session',app.state.signer.dumps(
        {'mode':'lark','sid':'sid-upload','wid':'test-lark-company','organization':'lark-company','uid':'u-manager'}))

    original_open=Path.open
    class RevokingFile:
        def __init__(self,handle): self.handle=handle
        def __enter__(self): return self
        def __exit__(self,*args): return self.handle.__exit__(*args)
        def write(self,content):
            result=self.handle.write(content)
            with app.state.sessions.begin() as db:
                profile=db.get(PersonRow,('lark-company','u-manager'))
                profile.data={**profile.data,'role':'member','capabilities':[],'manager_revoked':True}
            return result
        def __getattr__(self,name): return getattr(self.handle,name)
    def open_and_revoke(self,mode='r',*args,**kwargs):
        handle=original_open(self,mode,*args,**kwargs)
        if mode=='xb' and self.parent.parent==app.state.upload_dir:
            return RevokingFile(handle)
        return handle
    monkeypatch.setattr(Path,'open',open_and_revoke)
    before=client.get('/api/workspace').json()
    project=before['projects'][0]; node=project['nodes'][0]
    response=client.post('/api/files',data={'project_id':project['id'],'node_id':node['id'],
        'direction':'input','version':before['version'],'category_id':'evidence'},
        files={'file':('evidence.txt',b'company evidence','text/plain')})
    assert response.status_code==403,response.text
    with app.state.sessions() as db:
        row=db.get(WorkspaceRow,'test-lark-company')
        saved=storage.load(db,BusinessRow,row)
        audits=list(db.scalars(select(AuditRow).where(AuditRow.workspace_id=='test-lark-company')))
    assert not any(f.get('name')=='evidence.txt' for p in saved['projects'] for f in p['files'])
    assert not any(j.get('kind')=='file' for j in saved.get('jobs',[]))
    assert not any(a.data.get('action')=='file_upload' and a.data.get('result','success')=='success' for a in audits)
    upload_root=app.state.upload_dir
    assert not any(upload_root.rglob('*'))


@pytest.mark.parametrize('coverage', [None, [], [{'base_token': 'v4', 'table_id': 'daily', 'kind': 'daily', 'status': 'partial', 'count': 0}],
                                    [{'base_token': 'other', 'table_id': 'daily', 'kind': 'daily', 'status': 'ready', 'count': 0}]])
def test_incremental_or_other_table_absence_does_not_remove_daily(coverage):
    ws=seed(True); rows=[confirmation('recC1'),record('daily','recD',{'所屬案件':['recC1'],'日期':'2026-09-27','組別':'控制'})]
    import_sources(ws,rows); before=deepcopy(ws['projects'][0]['daily_reports'])
    import_sources(ws,rows[:1],complete_tables=coverage)
    assert ws['projects'][0]['daily_reports']==before


def test_complete_empty_daily_snapshot_retains_missing_history_and_blocks_reapproval():
    ws=seed(True); ws['users']=deepcopy(seed()['users'])
    ws['environment']='test'
    rows=[confirmation('recC1'),record('daily','recD',{'所屬案件':['recC1'],'日期':'2026-09-27','組別':'控制'})]
    import_sources(ws,rows); p=ws['projects'][0]; daily=p['daily_reports'][0]
    # Existing deployed rows predate source_identity; URL + exact source hash is sufficient.
    daily.pop('source_identity')
    actor=next(u for u in ws['users'] if u['role']=='manager')
    p['pm_id']=actor['id']  # Explicit case assignment for the mapping proposal.
    apply_operation(ws,actor,{'action':'daily_propose','project_id':p['id'],'payload':{'daily_id':daily['id'],'reason':'核對'}},True)
    review=ws['daily_reviews'][-1]
    apply_operation(ws,actor,{'action':'daily_approve','payload':{'id':review['id']}},True)
    coverage=[{'base_token':'v4','table_id':'daily','kind':'daily','status':'ready','count':0}]
    for _ in range(2):
        stats=import_sources(ws,rows[:1],complete_tables=coverage)
        assert not p['daily_reports'] and stats['daily_source_missing']==1
        assert len(ws['daily_unmatched'])==1 and ws['daily_unmatched'][0]['source_missing'] is True
        assert review['status']=='invalidated'
        assert ws['daily_unmatched'][0]['source_fields']==rows[1]['fields']
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        apply_operation(ws,actor,{'action':'daily_propose','project_id':p['id'],'payload':{'daily_id':daily['id'],'reason':'錯誤重新採用'}},True)
    # A real reappearance restores source data, not the old review approval.
    stats=import_sources(ws,rows,complete_tables=[dict(coverage[0],count=1)])
    assert stats['daily_imported']==1 and stats['daily_source_missing']==0
    assert len(p['daily_reports'])==1 and not p['daily_reports'][0].get('source_missing')
    assert review['status']=='invalidated'


@pytest.mark.parametrize('level', ['daily_table', 'contract_partial', 'reporting_partial'])
def test_relationship_wrong_table_or_partial_upstream_blocks_pairing(level):
    ws=seed(True)
    rows=[confirmation('recC1'),
          record('contract','recContract',{'所屬成案確認單（日報關聯）':['recC1']}),
          record('reporting','recReport',{'來源合約明細（日報關聯）':['recContract'],'工項類別':'控制'}),
          record('daily','recD',{'合約工項':['recReport'],'日期':'2026-09-27','組別':'控制'})]
    if level=='daily_table': rows[-1]['fields']['合約工項']=[{'table_id':'wrong','record_ids':['recReport']}]
    elif level=='contract_partial': rows[1]['fields']['所屬成案確認單（日報關聯）'].append('recUnknown')
    else: rows[2]['fields']['來源合約明細（日報關聯）'].append('recUnknown')
    stats=import_sources(ws,rows)
    assert stats['daily_imported']==0 and stats['daily_unmatched_unresolved_reference']==1


def test_pending_daily_review_rejects_upstream_cost_change():
    from fastapi import HTTPException
    ws=seed(True); ws['users']=deepcopy(seed()['users'])
    ws['environment']='test'
    rows=[confirmation('recC1'), record('cost','recCost',{'工作日期':'2026-09-27'}),
          record('daily','recD',{'所屬案件':['recC1'],'所屬成本單':['recCost'],'組別':'控制'})]
    import_sources(ws,rows); p=ws['projects'][0]
    actor=next(u for u in ws['users'] if u['role']=='manager')
    p['pm_id']=actor['id']  # Explicit case assignment for the mapping proposal.
    apply_operation(ws,actor,{'action':'daily_propose','project_id':p['id'],
                    'payload':{'daily_id':p['daily_reports'][0]['id'],'reason':'核對'}},True)
    review=ws['daily_reviews'][-1]; rows[1]['fields']['工作日期']='2026-09-28'
    import_sources(ws,rows)
    assert review['status']=='invalidated'
    with pytest.raises(HTTPException):
        apply_operation(ws,actor,{'action':'daily_approve','payload':{'id':review['id']}},True)
