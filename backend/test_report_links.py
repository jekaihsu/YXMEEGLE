from copy import deepcopy
from pathlib import Path
from collections import Counter
import json
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from .report_links import resolve_daily, identity, can_review_links, reviewed_item, link_summary
from .report_bridge import reconcile_bridges, accepted_cases, save_bridges, load_bridges
from .report_link_review import apply_review
from .models import Base, ReportCaseBridge
from .project_progress import ReportsView, build_project_progress
from .reports.compute import attach_local_bridges
from .reports.snapshot import SnapshotStore
from .test_project_progress import RawReader
from .test_operations import ws, record, call
from .sources import import_sources,source_id
from .v4_sources import daily_mapping_version


def project(pid='a', code='C115238-01', **extra):
    return dict(id=pid,code=code,pm_id='pm',source_identity=dict(base_token='B',table_id='T',record_id=pid),daily_reports=[],**extra)


def daily(code='', **extra):
    return dict(source_fields={'可能的確認單工編(若暫無確認單才需填寫)':code}, **extra)


@pytest.mark.parametrize('code,projects,expected',[
    (' C115238-01 ',[project()],('a',None)),
    ('C115238',[project()],(None,'unresolved_reference')),
    ('',[project(code='')],(None,'missing_reference')),
    ('C115238-01',[project(),project('b')],(None,'ambiguous_reference')),
    ('ALIAS',[project(report_link_aliases=[{'code':'ALIAS','status':'pending'}])],(None,'unresolved_reference')),
    ('ALIAS',[project(report_link_aliases=[{'code':'ALIAS','status':'reviewed'}])],('a',None)),
    ('C115238-0',[project()],(None,'unresolved_reference')),
])
def test_exact_rule_table(code, projects, expected):
    found=resolve_daily(daily(code),projects)
    assert (found.project_id,found.reason)==expected


def test_native_identity_beats_unknown_text_but_conflicting_exact_text_is_ambiguous():
    a,b=project(),project('b','OTHER')
    native=dict(identity=a['source_identity'],project_id='a',work_item_id='item')
    found=resolve_daily(daily('unknown'),[a,b],native_targets=[native])
    assert (found.project_id,found.basis,found.work_item_id)==('a','source_case_or_link','item')
    conflict=resolve_daily(daily('OTHER'),[a,b],native_targets=[native])
    assert conflict.reason=='ambiguous_reference' and [c['rank'] for c in conflict.candidates]==[0,1]
    assert resolve_daily(daily(a['code']),[a],native_targets=[native],unresolved_native=True).project_id is None
    assert resolve_daily(daily(a['code']),[a],native_targets=[{**native,'identity':{'record_id':'a'}}]).reason=='unresolved_reference'


def test_typed_identity_never_joins_ids_across_bases_or_tables():
    a=project()
    for field in ('base_token','table_id'):
        ref={**a['source_identity'],field:'different'}
        assert resolve_daily(daily(native_references=[ref]),[a]).reason=='unresolved_reference'
    assert resolve_daily(daily(native_references=[a['source_identity']]),[a]).project_id=='a'


def test_multiple_items_never_split_or_choose_one():
    a=project()
    targets=[dict(identity=a['source_identity'],project_id='a',work_item_id=i) for i in ('i1','i2')]
    assert resolve_daily(daily(),[a],native_targets=targets).work_item_id is None
    state={'source_work_items':[{'id':'one','project_id':'a','reviewed_item_key':'K'},{'id':'two','project_id':'a','reviewed_item_key':'K'}]}
    assert reviewed_item(state,'a','K') is None and reviewed_item(state,'b','one') is None


@pytest.mark.parametrize('user,expected',[
    ({'id':'boss','role':'manager'},True),({'id':'pm','role':'member'},True),
    ({'id':'other','role':'pm'},False),({'id':'employee','role':'member','capabilities':['review_mapping']},False),
    ({'id':'pm','role':'pm','active':False},False),({'id':'boss','role':'manager','manager_revoked':True},False),
])
def test_authority_matrix(user,expected):
    assert can_review_links(user,project()) is expected


def test_server_derived_admin_authority():
    from .business_policy import ORDINARY_BACKUP_SCOPE
    proof=dict(open_id='webadmin',app_id='app',tenant='tenant',source='oauth_user_info')
    user=dict(id='webadmin',role='member',identity_app_id='app',oauth_identity=proof,
              _business_authority=dict(source='server_company_admin_grant',open_id='webadmin',app_id='app',tenant='tenant',grant_id='g',decision_ref='r',scopes=[ORDINARY_BACKUP_SCOPE]))
    assert can_review_links(user,project())
    user['_business_authority']['open_id']='someone'
    assert not can_review_links(user,project())


def add_daily(ws, code='MISSING', ident='recDaily'):
    records=[record('confirmation','rec1',{'工程確認單編號':'C001'}),record('daily',ident,{'可能的確認單工編(若暫無確認單才需填寫)':code,'日期':'2026-10-20'})]
    import_sources(ws,records)
    return records,next(d for d in ws['daily_unmatched'] if d['id']==source_id(records[-1]))


@pytest.mark.parametrize('system',['pending','meegle','workbench'])
def test_link_administration_works_for_all_execution_systems(ws,system):
    _,row=add_daily(ws);p=ws['projects'][0];p['execution_system']=system
    for actor in ('u-manager','u-pm'):
        call(ws,'daily_link',{'daily_id':row['id'],'reason':'確認來源'},user=actor)
        assert p['daily_reports'][0]['match_basis']=='manual_review'
    assert len([e for e in ws['events'] if e.get('daily_id')==row['id']])==2
    assert len([r for r in ws['daily_reviews'] if r['status']=='invalidated'])==1


def test_employee_proposes_but_cannot_approve_or_direct_link(ws):
    _,row=add_daily(ws);row['source_actor_ids']=['u-control']
    call(ws,'daily_propose',{'daily_id':row['id'],'reason':'來源提案'},user='u-control')
    review=ws['daily_reviews'][-1]
    for action,data in [('daily_link',{'daily_id':row['id'],'reason':'x'}),('daily_approve',{'id':review['id']})]:
        with pytest.raises(HTTPException) as e: call(ws,action,data,user='u-control')
        assert e.value.status_code==403
    call(ws,'daily_approve',{'id':review['id']},user='u-pm')
    assert ws['projects'][0]['daily_reports'][0]['id']==row['id']


def test_reimport_preserves_manual_and_source_change_invalidates(ws):
    records,row=add_daily(ws)
    call(ws,'daily_link',{'daily_id':row['id'],'reason':'明確核對'})
    import_sources(ws,records)
    assert ws['projects'][0]['daily_reports'][0]['match_basis']=='manual_review'
    assert ws['daily_reviews'][-1]['status']=='approved'
    records[-1]['fields']['可能的確認單工編(若暫無確認單才需填寫)']='CHANGED'
    import_sources(ws,records)
    assert ws['daily_reviews'][-1]['status']=='invalidated' and ws['daily_unmatched'][0]['id']==row['id']


def test_relink_unlink_require_reason_and_invalidate_old_approvals(ws):
    records,row=add_daily(ws)
    call(ws,'daily_link',{'daily_id':row['id'],'reason':'第一次'})
    for action in ('daily_link','daily_unlink'):
        with pytest.raises(HTTPException) as e: call(ws,action,{'daily_id':row['id'],'reason':'  '})
        assert e.value.status_code==422
    call(ws,'daily_unlink',{'daily_id':row['id'],'reason':'原案不正確'},user='u-pm')
    assert not ws['projects'][0]['daily_reports'] and ws['daily_reviews'][-2]['status']=='invalidated'
    import_sources(ws,records)
    assert ws['daily_unmatched'][0]['manual_unlinked'] is True and not ws['projects'][0]['daily_reports']


def test_item_picker_rejects_other_case_and_reimport_keeps_reviewed_item(ws):
    _,row=add_daily(ws);p=ws['projects'][0]
    ws['source_work_items']=[dict(id='item',project_id=p['id']),dict(id='other',project_id='elsewhere')]
    with pytest.raises(HTTPException):call(ws,'daily_link',{'daily_id':row['id'],'reason':'x','work_item_id':'other'})
    call(ws,'daily_link',{'daily_id':row['id'],'reason':'核對唯一工項','work_item_id':'item'})
    assert p['daily_reports'][0]['work_item_id']=='item'


def test_bulk_same_code_has_one_audit_per_row_and_stale_confirmation_refuses(ws):
    records,row=add_daily(ws)
    records.append(record('daily','recDaily2',deepcopy(records[-1]['fields'])))
    import_sources(ws,records);rows=list(ws['daily_unmatched'])
    data=dict(provisional_code='MISSING',confirmed=True,daily_ids=[r['id'] for r in rows],reason='同案號一次確認')
    with pytest.raises(HTTPException) as e:call(ws,'daily_bulk_link',{**data,'daily_ids':data['daily_ids'][:1]})
    assert e.value.status_code==409
    call(ws,'daily_bulk_link',data)
    assert len(ws['projects'][0]['daily_reports'])==2
    events=[e for e in ws['events'] if e['action']=='daily_link_reviewed']
    assert len(events)==2 and {e['daily_id'] for e in events}==set(data['daily_ids'])


def reports(cases):
    store=SnapshotStore(RawReader(cases));store.get()
    return store,ReportsView(store,warm=False)


def test_bridge_unique_ambiguous_missing_reviewed_rejected_and_idempotent():
    store,view=reports([('rec1','C1','未填',1),('rec2','Q1','未填',2)])
    try:
        state={'projects':[project('unique','C1'),project('two','C1',quotes=[{'quote_code':'Q1'}]),project('zero','NO')]}
        bridges=reconcile_bridges(state,view);before=deepcopy(bridges);reconcile_bridges(state,view)
        assert bridges==before
        assert {k:b['status'] for k,b in bridges.items()}=={'unique':'auto_exact','two':'pending','zero':'pending'}
        assert accepted_cases(state['projects'][1],view,bridges['two'])==[]
        bridges['two'].update(status='reviewed',codes=['Q1']);bridges['zero'].update(status='rejected')
        reconcile_bridges(state,view)
        assert accepted_cases(state['projects'][1],view,bridges['two'])[0]['bridge_status']=='reviewed'
        assert bridges['zero']['status']=='rejected'
    finally:store.close()


def test_bridge_table_roundtrip_is_idempotent(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'bridges.db'));Base.metadata.create_all(engine);Base.metadata.create_all(engine)
    store,view=reports([('rec1','C1','未填',1)])
    try:
        state={'projects':[project(code='C1')]};reconcile_bridges(state,view)
        with Session(engine) as db:
            save_bridges(db,'w',state);db.commit();save_bridges(db,'w',state);db.commit()
            assert len(list(db.scalars(select(ReportCaseBridge))))==1
            assert load_bridges(db,'w')==state['report_case_bridges']
    finally:store.close();engine.dispose()


def test_progress_and_pm_summary_use_reviewed_bridge_not_current_text():
    store,view=reports([('rec1','C1','未填',1),('rec2','Q1','未填',2)])
    try:
        p=project(code='C1',quotes=[{'quote_code':'Q1'}]);state={'projects':[p]};reconcile_bridges(state,view)
        assert build_project_progress(state,'a',reports=view)['production']['field']['actual']['known'] is False
        state['report_case_bridges']['a'].update(status='reviewed',codes=['Q1'])
        result=build_project_progress(state,'a',reports=view)
        assert result['production']['field']['actual']['value']=='2'
        annotated=attach_local_bridges({'items':[{'case_code':'C1'},{'case_code':'Q1'},{'case_code':''}]},state['report_case_bridges'])
        assert [r['local_cases'] for r in annotated['items']]==[[],[{'project_id':'a','status':'reviewed'}],[]]
    finally:store.close()


def test_unknown_provenance_and_case_only_links_never_invent_item_quantity():
    p=project();p['daily_reports']=[dict(id='unknown',date='2026-10-22',department='外業組',points=9),dict(id='linked',date='2026-10-20',department='外業組',points=1,match_basis='manual_review',case_mapping_status='matched')]
    state={'projects':[p],'daily_unmatched':[]}
    result=build_project_progress(state,'a')
    assert result['production']['field']['work_orders']['latest_date']=='2026-10-20'
    assert result['production']['field']['actual']['unit_note'].endswith('非合約數量）')
    assert result['daily_links']['linked']==1 and result['daily_links']['unlinked']==1


def snapshot_measurement():
    root=Path(__file__).resolve().parents[1]/'.runtime/progress-map'
    if not all((root/name).exists() for name in ('joined.json','field.ndjson','inner.ndjson','v3case.ndjson')): pytest.skip('saved read-only snapshot is absent')
    def rows(name):return [json.loads(line) for line in (root/(name+'.ndjson')).read_text().splitlines()]
    joined=json.loads((root/'joined.json').read_text())
    projects=[project(j['confirmation_id'],j['code'],quotes=[{'quote_code':q.get('報價編號')} for q in j['quotes']],report_link_aliases=[{'code':a,'status':'reviewed'} for a in j['aliases']]) for j in joined]
    decisions=[resolve_daily({'fields':r},projects) for key in ('field','inner') for r in rows(key)]
    raw={'case':{'status':'ok','records':[{'record_id':r['record_id'],'fields':{k:v for k,v in r.items() if k!='record_id'}} for r in rows('v3case')]}}
    class Reader:
        def read(self):return raw
    store=SnapshotStore(Reader());store.get();view=ReportsView(store,warm=False)
    state={'projects':projects};bridges=reconcile_bridges(state,view);store.close()
    return dict(daily_total=len(decisions),daily_linked=sum(d.project_id is not None for d in decisions),daily_reasons=dict(Counter(d.reason for d in decisions)),bridge_total=len(bridges),bridge_statuses=dict(Counter(b['status'] for b in bridges.values())),bridge_candidate_counts=dict(Counter(len(b['candidates']) for b in bridges.values())))


def test_saved_snapshot_read_only_counts():
    measured=snapshot_measurement()
    assert measured['daily_total']==535 and measured['daily_linked']==0
    assert measured['daily_reasons']=={'missing_reference':403,'unresolved_reference':132}
    assert measured['bridge_total']==16 and measured['bridge_candidate_counts']=={1:11,2:2,0:3}


def test_concurrent_http_queue_initialization_and_reviewed_bridge_survives_reads(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from .app import create_app,WorkspaceRow,BusinessRow
    from . import storage
    app=create_app({'APP_ENV':'development','DEMO_MODE':'true','DATABASE_URL':'sqlite:///'+str(tmp_path/'http.db'),'UPLOAD_DIR':str(tmp_path/'uploads'),'SESSION_SECRET':'link-tests'*5})
    store,view=reports([('rec1','C1','未填',1),('rec2','Q1','未填',2)])
    app.state.reports=store
    try:
        with TestClient(app) as client:
            client.get('/api/session');client.post('/api/demo/session',json={'user_id':'u-manager'})
            wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
            with app.state.sessions.begin() as db:
                row=db.get(WorkspaceRow,wid);state=storage.load(db,BusinessRow,row)
                state['projects'][0].update(code='C1',quotes=[{'quote_code':'Q1'}],execution_system='pending')
                row.data=storage.save(db,BusinessRow,wid,state)
            with ThreadPoolExecutor(max_workers=4) as pool:
                responses=list(pool.map(lambda _:client.get('/api/report-links'),range(8)))
            assert all(r.status_code==200 for r in responses)
            result=responses[0].json();bridge=next(b for b in result['bridges'] if b['project_id']=='p1')
            assert bridge['status']=='pending' and len(bridge['candidates'])==2
            version=client.get('/api/workspace').json()['version']
            review=client.post('/api/actions',json=dict(action='report_bridge_review',project_id='p1',version=version,request_id='bridge-review',payload=dict(status='reviewed',codes=['Q1'],reason='明確核對')))
            assert review.status_code==200,review.text
            assert next(b for b in client.get('/api/report-links').json()['bridges'] if b['project_id']=='p1')['codes']==['Q1']
            with app.state.sessions() as db:
                persisted=db.get(ReportCaseBridge,(wid,'p1'))
                assert persisted.status=='reviewed' and persisted.actor_id=='u-manager'
    finally:store.close()


def test_duplicate_v3_codes_refuse_auto_bridge_and_blank_never_links():
    store,view=reports([('rec1','C1','未填',1),('rec2','C1','未填',2),('recBlank','','未填',99)])
    try:
        state={'projects':[project('dupe','C1'),project('blank','')]}
        result=reconcile_bridges(state,view)
        assert len(result['dupe']['candidates'])==2 and result['dupe']['status']=='pending'
        assert result['blank']['status']=='pending' and result['blank']['candidates']==[]
        assert view.case('C1') is None and view.case('') is None
    finally:store.close()


def test_raw_native_envelope_requires_complete_typed_identity():
    p=project();p['source_identity']['record_id']='recA'
    row={'base_token':'B','linked_tables':{'所屬案件':'T'},'fields':{'所屬案件':[{'id':'recA'}]}}
    assert resolve_daily(row,[p]).project_id=='a'
    row['linked_tables']={}
    assert resolve_daily(row,[p]).reason=='unresolved_reference'


def test_native_item_id_matches_canonical_progress_item_identity():
    from .test_new_daily_acceptance import setup,daily,link
    from .source_entities import entity_id
    state,records=setup()
    row=daily(**{'內業工項':link('reporting','recReportingA')});import_sources(state,records+[row])
    entry=next(d for p in state['projects'] for d in p['daily_reports'] if d['id']==source_id(row))
    assert entry['work_item_id']==entity_id(records[-1]) and entry['item_match_basis']=='native'


def test_item_source_reassignment_invalidates_manual_review(ws):
    from .report_link_review import reconcile_item_reviews
    _,row=add_daily(ws);p=ws['projects'][0]
    ws['source_work_items']=[dict(id='item',project_id=p['id'])]
    call(ws,'daily_link',dict(daily_id=row['id'],work_item_id='item',reason='核對工項'))
    ws['source_work_items'][0]['project_id']='different-case'
    assert reconcile_item_reviews(ws)==[row['id']]
    assert ws['daily_reviews'][-1]['status']=='invalidated' and not p['daily_reports']
    assert ws['daily_unmatched'][0]['case_mapping_status']=='unresolved_reference'


def test_demo_containment_with_unknown_provenance_is_review_evidence_only():
    from .report_link_review import review_queue
    p=project();p['daily_reports']=[dict(id='old',description='unknown origin')]
    state={'projects':[p],'daily_unmatched':[],'environment':'demo'}
    summary=link_summary(state)
    queue=review_queue(state,{'id':'boss','role':'manager'})
    assert summary['linked']==0 and summary['reasons']['missing_reference']==1
    row=queue['rows'][0]
    assert row['project_id'] is None and row['case_mapping_status']=='missing_reference'
    assert row['candidate_evidence'][0]['reasons']==['legacy_containment_unknown_provenance']
    assert queue['reasons']['missing_reference']==1


def test_native_item_chain_cannot_smuggle_an_unreviewed_quote_alias(ws):
    rows=[record('confirmation','rec1',{'工程確認單編號':'C001','所屬案件':'QUOTE'}),
          record('reporting','recItem',{'所屬案件':'QUOTE','工項類別':'控制'}),
          record('daily','recD',{'內業工項':[{'table_id':'reporting','record_ids':['recItem']}]})]
    import_sources(ws,rows)
    assert any(d['id']==source_id(rows[-1]) for d in ws['daily_unmatched'])
    p=next(p for p in ws['projects'] if p['code']=='C001')
    p['report_link_aliases']=[dict(code='QUOTE',status='reviewed')]
    import_sources(ws,rows)
    assert any(d['id']==source_id(rows[-1]) for d in p['daily_reports'])
