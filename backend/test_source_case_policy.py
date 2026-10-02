from copy import deepcopy
from datetime import datetime,timezone,timedelta
import pytest
from fastapi import HTTPException
from .source_case_policy import establish_baseline, partition_snapshot, identity, mark_imported_new, filter_visible_cases, visible_source_snapshot
from .case_cutover import assign_execution, execution_allowed
from .source_case_policy import apply_source_reference_policy,baseline_summary,visible_project


def test_all_lark_policy_exposes_verified_existing_closed_cases_without_execution_grant():
    verified=record('verified')
    state={'environment':'production','events':[], 'projects':[
        {'id':'shadow','source_identity':{k:verified[k] for k in ('base_token','table_id','record_id')},
         'case_visibility':'excluded_history','execution_system':'meegle','status':'completed'},
        {'id':'unverified','source_identity':{'base_token':'other','table_id':'table','record_id':'verified'}},
        {'id':'pure-meegle','source_kind':'meegle'},
        {'id':'legacy-v4-label','source_model':'v4','source_kind':'lark'}]}
    apply_source_reference_policy(state,snapshot([verified]),{'id':'sync'})
    assert visible_project(state,state['projects'][0])
    assert not execution_allowed(state,state['projects'][0])
    assert state['projects'][0]['execution_system']=='meegle'
    assert not visible_project(state,state['projects'][1])
    assert not visible_project(state,state['projects'][2])
    assert not visible_project(state,state['projects'][3])
    assert baseline_summary(state)['status']=='active'
    with pytest.raises(HTTPException):
        establish_baseline(state,{'id':'admin','role':'manager'},snapshot([verified]),
                           expected_sync_revision=1,reason='obsolete cutover')
    count=len(state['events'])
    apply_source_reference_policy(state,snapshot([verified]),{'id':'sync'})
    assert len(state['events'])==count


def test_new_source_projection_defaults_pending_and_preserves_explicit_workbench():
    row=record('verified');ident={k:row[k] for k in ('base_token','table_id','record_id')}
    state={'environment':'production','events':[], 'projects':[
        {'id':'shadow','source_identity':ident},
        {'id':'authorized','source_identity':ident,'execution_system':'workbench'}]}
    apply_source_reference_policy(state,snapshot([row]),{'id':'sync'})
    assert state['projects'][0]['execution_system']=='pending'
    assert not execution_allowed(state,state['projects'][0])
    assert execution_allowed(state,state['projects'][1])


def record(ident,kind='confirmation',code='C115001',created=None,fields=None):
    return {'base_token':'base','table_id':'table','record_id':ident,'kind':kind,
            'created_time':created,'fields':fields or {'工程確認單編號':code}}


def snapshot(records):
    return {'status':'ready','last_sync':'2026-09-01T00:00:00+00:00','message':'ok',
            'tables':[{'base_token':'base','table_id':'table','status':'ready','count':len(records)}], 'records':records}


def prepared():
    old=record('recOld'); snap=snapshot([old])
    state={'environment':'production','version':1,'projects':[{'id':'old','code':'C115001','nodes':[], 'execution_system':'workbench','comments':[{'body':'retain history'}]}],
           'events':[],'source_status':{'sync_revision':1,'last_sync':snap['last_sync']}}
    establish_baseline(state,{'id':'admin','role':'manager'},snap,expected_sync_revision=1,reason='approved cutover')
    # Deterministic old cutoff permits newly created records without clock sleeps.
    state['source_case_baseline']['cutover_at']='2026-09-01T00:00:00+00:00'
    return state,old


def test_baseline_excludes_existing_projects_without_deleting_history():
    state,_=prepared(); old=state['projects'][0]
    assert old['case_visibility']=='excluded_history' and not execution_allowed(state,old)
    assert old['comments']==[{'body':'retain history'}]
    with pytest.raises(HTTPException):assign_execution(state,{'id':'admin','role':'manager'},'old','workbench','restore as new')
    assert filter_visible_cases(deepcopy(state))['projects']==[]


def test_partition_without_baseline_is_nonmutating_and_admits_nothing():
    state,_=prepared();state.pop('source_case_baseline')
    state['projects'][0].pop('case_visibility')
    state['projects'][0]['execution_system']='workbench'
    state['source_case_review']=[{'reason':'preserve previous review'}]
    before=deepcopy(state)
    assert partition_snapshot(state,snapshot([record('fresh',created='2026-09-29T00:00:00+00:00')]))==([],set())
    assert state==before
    assert filter_visible_cases(deepcopy(state))['projects']==[]


@pytest.mark.parametrize('failure',['partial','generation','duplicate','table_error'])
def test_baseline_requires_complete_matching_snapshot(failure):
    snap=snapshot([record('rec')]); state={'environment':'production','projects':[],'events':[], 'source_status':{'sync_revision':1,'last_sync':snap['last_sync']}}
    if failure=='partial':snap['status']='partial'
    if failure=='duplicate':snap['records']*=2
    if failure=='table_error':snap['tables'][0]['status']='partial'
    with pytest.raises(HTTPException):establish_baseline(state,{'id':'a','role':'manager'},snap,expected_sync_revision=2 if failure=='generation' else 1,reason='test')
    assert 'source_case_baseline' not in state


def test_first_seen_and_changed_old_code_do_not_create_new_case():
    state,old=prepared(); changed=deepcopy(old);changed['fields']['工程確認單編號']='RENAMED'
    unknown=record('recUnknown',code='NEW-NO-PROOF')
    admitted,new=partition_snapshot(state,snapshot([changed,unknown]))
    assert admitted==[] and new==set()
    assert len(state['source_case_review'])==1 and state['source_case_review'][0]['reason']=='missing_created_time'


def test_new_quote_attached_to_old_case_stays_excluded():
    state,old=prepared()
    quote=record('recQuote','quote',created='2026-09-02T00:00:00+00:00',fields={'報價編號':'115999','此案確認單':['recOld']})
    admitted,new=partition_snapshot(state,snapshot([old,quote]))
    assert admitted==[] and new==set() and not state['source_case_review']


def test_new_quote_linked_to_deleted_baseline_case_stays_excluded():
    state,_=prepared()
    quote=record('recQuote','quote',created='2026-09-02T00:00:00+00:00',fields={'報價編號':'115999','此案確認單':['recOld']})
    admitted,new=partition_snapshot(state,snapshot([quote]))
    assert admitted==[] and not new and not state['source_case_review']


def test_proven_old_record_discovered_late_does_not_enter_review_or_cases():
    state,_=prepared()
    late=record('recLate',code='OLD-LATE',created='2026-08-01T00:00:00+00:00')
    admitted,new=partition_snapshot(state,snapshot([late]))
    assert admitted==[] and not new and not state['source_case_review']


def test_native_new_case_and_new_daily_admitted_old_daily_excluded():
    state,old=prepared()
    new=record('recNew',code='C115999',created='2026-09-02T00:00:00+00:00')
    daily=record('recDaily','daily',fields={'所屬案件':'C115999','工作內容':'new work'})
    olddaily=record('recOldDaily','daily',fields={'所屬案件':'C115001','工作內容':'old work'})
    rows,newids=partition_snapshot(state,snapshot([old,new,daily,olddaily]))
    assert {r['record_id'] for r in rows}=={'recNew','recDaily'}
    state['projects'].append({'id':'new','source_identity':{k:new[k] for k in ('base_token','table_id','record_id')}})
    mark_imported_new(state,newids)
    assert state['projects'][-1]['execution_system']=='workbench'
    assert state['projects'][-1]['case_visibility']=='new_case'


def test_missing_native_relation_is_minimal_review_not_case():
    state,old=prepared()
    quote=record('recQuote','quote',created='2026-09-02T00:00:00+00:00',fields={'報價編號':'115999','此案確認單':['recMissing']})
    rows,newids=partition_snapshot(state,snapshot([old,quote]))
    assert not rows and not newids
    assert set(state['source_case_review'][0])=={'identity','code','reason','source_kind'}


def test_public_filter_removes_old_associated_collections_and_raw_cache_counts():
    state,old=prepared()
    new=record('recNew',code='C115999',created='2026-09-02T00:00:00+00:00')
    state['projects'].append({'id':'new','case_visibility':'new_case'})
    state['approvals']=[{'id':'old-approval','project_id':'old'},{'id':'new-approval','project_id':'new'}]
    state['events']=[{'id':'old-event','project_id':'old'},{'id':'new-event','project_id':'new'}]
    state['source_visible_record_ids']=[identity(new)]
    public=filter_visible_cases(deepcopy(state))
    assert [p['id'] for p in public['projects']]==['new']
    assert [a['id'] for a in public['approvals']]==['new-approval']
    assert [a['id'] for a in public['events']]==['new-event']
    assert 'source_case_baseline' not in public and 'source_visible_record_ids' not in public
    cache=visible_source_snapshot(state,snapshot([old,new]))
    assert [r['record_id'] for r in cache['records']]==['recNew'] and cache['tables'][0]['count']==1


def test_old_source_sentinels_cannot_escape_through_orphan_or_multi_owner_collections():
    import json
    state,old=prepared(); new=record('recNew',code='C115999',created='2026-09-02T00:00:00+00:00')
    state['projects'].append({'id':'new','case_visibility':'new_case'})
    state['source_visible_record_ids']=[identity(new)]
    state['archived_projects']=[{'id':'old','name':'SECRET_OLD_CASE'}]
    for collection in ('source_quotes','source_confirmations','contract_items'):
        state[collection]=[
            {'id':'orphan','fields':{'name':'SECRET_OLD_CASE'},'source_identity':old},
            {'id':'mixed','fields':{'name':'SECRET_OLD_CASE'},'source_identity':new,'project_ids':['old','new']},
            {'id':'new','fields':{'name':'visible'},'source_identity':new,'project_id':'new'}]
    state['jobs']=[{'kind':'file','payload':{'project_id':'old'},'error':'SECRET_OLD_CASE'}]
    state['daily_reviews']=[{'id':'orphan','entry':{'description':'SECRET_OLD_CASE'}}]
    state['source_attachment_index']=[{'id':'orphan','name':'SECRET_OLD_CASE'}]
    public=filter_visible_cases(deepcopy(state))
    assert 'SECRET_OLD_CASE' not in json.dumps(public)
    assert all(len(public[key])==1 for key in ('source_quotes','source_confirmations','contract_items'))


def test_changed_source_tables_fail_closed_without_rebaselining():
    state,old=prepared(); snap=snapshot([old]);snap['tables'][0]['table_id']='other'
    with pytest.raises(HTTPException):partition_snapshot(state,snap)
    assert state['source_case_baseline']['source_tables']==[('base','table')]


def test_rebaseline_cannot_turn_new_cases_into_old():
    state,old=prepared()
    with pytest.raises(HTTPException):establish_baseline(state,{'id':'admin','role':'manager'},snapshot([old]),expected_sync_revision=1,reason='again')
