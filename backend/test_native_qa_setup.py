from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
import pytest
from scripts.native_qa_setup import APP,CODE,NAME,inspect_definition,manifest_from_report
from .native_qa import QAError
from .lark_adapter import RemoteFailure


def definition():
    return {'approval_name':NAME,'status':'ACTIVE','form':json.dumps([
      {'id':'actual-binding','name':'驗收識別','type':'textarea'},
      {'id':'actual-content','name':'驗收測試內容','type':'textarea'}]),
      'node_list':[{'node_id':'actual-'+name,'name':name,'need_approver':False,
                   'node_type':'AND','empty_assignee_list':[],'require_signature':False}
                   for name in ('Submit','End')]+[
      {'node_id':'actual-joint','name':'Approval','need_approver':True,'node_type':'AND','approver_chosen_multi':True}]}


def test_definition_ids_are_observed_not_fabricated_and_sensitive_extras_removed():
    source=definition();source['admin_ids']=['private-user']
    safe,mapping=inspect_definition(source)
    assert mapping['nodes']==[{'id':'actual-joint','seats':['pm','supervisor']}]
    assert mapping['fields']['binding']['id']=='actual-binding'
    assert 'private-user' not in json.dumps(safe)
    assert mapping['approval_code']==CODE


@pytest.mark.parametrize('change',['wrong_name','extra_field','OR','single','extra_node'])
def test_unreviewed_definition_is_rejected(change):
    source=definition()
    if change=='wrong_name':source['approval_name']='other QA'
    if change=='extra_field':
        fields=json.loads(source['form']);fields.append({'id':'extra','name':'extra','type':'textarea'});source['form']=json.dumps(fields)
    if change=='OR':source['node_list'][-1]['node_type']='OR'
    if change=='single':source['node_list'][-1]['approver_chosen_multi']=False
    if change=='extra_node':source['node_list'].append(dict(source['node_list'][-1],node_id='other'))
    with pytest.raises((QAError,RemoteFailure)):inspect_definition(source)


def test_manifest_needs_fresh_same_app_distinct_humans_and_existing_definition():
    cfg={'LARK_APP_ID':APP,'LARK_APP_SECRET':'test','LARK_WORKER_IDENTITY':'application',
         'LARK_WORKER_ORGANIZATION':'company','LARK_ALLOWED_TENANTS':'company',
         'LARK_NATIVE_APPROVAL_MAPPINGS_JSON':json.dumps({k:{'approval_code':'production-'+k}
          for k in ('node_skip','financial','change','extension')})}
    report={'app_id':APP,'tenant':'company','definition_code':CODE,'definition':definition()}
    identities={'app_id':APP,'tenant':'company','verified_at':datetime.now(timezone.utc).isoformat(),
      'evidence_ref':'.runtime/verified-participants.json',
      'participants':{'applicant':'ou_first','approvers':{'pm':'ou_first','supervisor':'ou_second'},'allowlist':['ou_first','ou_second']},
      'authorization':{'decision_ref':'test authorization','authorized_by':'user','reason':'QA only',
                       'expires_at':(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()}}
    assert manifest_from_report(report,identities,cfg)['mapping']['nodes'][0]['seats']==['pm','supervisor']
    for field,value in [('app_id','other-app'),('verified_at',(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat())]:
        bad=deepcopy(identities);bad[field]=value
        with pytest.raises(QAError):manifest_from_report(report,bad,cfg)
    bad=deepcopy(identities);bad['participants']['approvers']['supervisor']='ou_first'
    with pytest.raises(QAError):manifest_from_report(report,bad,cfg)


def test_people_selection_requires_same_app_complete_roster_and_known_workbench_id():
    from scripts.native_qa_setup import inspect_people,KNOWN_WEN
    from .people_directory import BASE,TABLE_ID
    snapshot={'complete':True,'app_id':APP,'base_token':BASE,'table_id':TABLE_ID,
              'fetched_at':datetime.now(timezone.utc).isoformat(),'source_count':2,
              'selected_fields':['姓名','人員','在職','內外勤'],
              'people':[{'id':KNOWN_WEN,'name':'文乃毅','record_id':'r1','employment_status':'employed'},
                        {'id':'ou_zhong','name':'鍾智偉','record_id':'r2','employment_status':'employed'}]}
    cfg={'LARK_WORKER_ORGANIZATION':'company'}
    result=inspect_people(snapshot,cfg)
    assert result['qa_seats_only'] and not result['formal_role_assignment']
    assert result['candidates']['supervisor']['id']=='ou_zhong'
    for change in ('other_app','wrong_wen','left','duplicate'):
        bad=deepcopy(snapshot)
        if change=='other_app':bad['app_id']='other'
        if change=='wrong_wen':bad['people'][0]['id']='ou_other_application'
        if change=='left':bad['people'][1]['employment_status']='left'
        if change=='duplicate':bad['people'].append(deepcopy(bad['people'][1]))
        with pytest.raises(QAError):inspect_people(bad,cfg)
