from copy import deepcopy
from datetime import datetime,timezone
import pytest
from .policy import defaults
from .remote_policy import connection_policy,FORMAL_BASES
from .lark_adapter import RemoteFailure
from .test_source_sync import harness


def configured():
    state={'environment':'production','settings':dict(defaults(),external_enabled=True,input_base='registrationBase',input_table='registrationTable')}
    cfg={'LARK_WORKER_ORGANIZATION':'company','LARK_WORKER_IDENTITY':'application',
         'LARK_INPUT_BASE_TOKEN':'registrationBase','LARK_INPUT_TABLE_ID':'registrationTable'}
    return state,cfg


@pytest.mark.parametrize('target',list(FORMAL_BASES))
def test_formal_source_bases_never_become_input_destinations_even_if_configured(target):
    state,cfg=configured();state['settings']['input_base']=target;cfg['LARK_INPUT_BASE_TOKEN']=target
    with pytest.raises(RemoteFailure):connection_policy('lark-company',state,cfg,'input')


@pytest.mark.parametrize('key',['LARK_INPUT_BASE_TOKEN','LARK_INPUT_TABLE_ID'])
def test_registration_requires_server_and_workspace_agreement(key):
    state,cfg=configured();cfg[key]='another'
    with pytest.raises(RemoteFailure):connection_policy('lark-company',state,cfg,'input',for_verification=True)


def test_registration_destination_is_explicit_table_not_v4_fallback():
    state,cfg=configured();policy=connection_policy('lark-company',state,cfg,'input')
    assert policy['base_token']=='registrationBase' and policy['table_id']=='registrationTable'
    state['settings'].pop('input_base')
    with pytest.raises(RemoteFailure):connection_policy('lark-company',state,cfg,'input')


def test_test_workspace_cannot_target_formal_registration_base():
    state,cfg=configured();state['environment']='test'
    state['settings'].update(test_connection_mode='isolated_live',test_base='registrationBase')
    cfg['LARK_TEST_BASE_TOKEN']='registrationBase'
    with pytest.raises(RemoteFailure):connection_policy('test-lark-company',state,cfg,'input')


def test_wrong_registration_table_blocks_worker_before_remote_factory(harness,tmp_path):
    from . import storage
    from .operations import queue
    from .jobs import Worker
    h=harness;state,_=h.read();p=state['projects'][0];n=p['nodes'][0]
    p['execution_system']='workbench'
    state['settings'].update(external_enabled=True,input_base='registrationBase',input_table='approvedTable')
    state['input_mappings']=[{'id':'m','project_id':p['id'],'node_id':n['id'],'enabled':True,
        'verified':True,'mode':'append_registration','base_token':'registrationBase','table_id':'otherTable'}]
    state['input_revisions']=[{'id':'i','mapping_id':'m','project_id':p['id'],'node_id':n['id'],'status':'queued','actor_id':'u-manager','created_at':'2026-09-29'}]
    from .input_registration import make_plan,FIELD_NAMES
    state['input_revisions'][0]['registration_plan']=make_plan(h.wid,p,n,state['input_revisions'][0],
        {'base_token':'registrationBase','table_id':'otherTable','fields':{k:{'field_id':'fld'+k,'field_name':v} for k,v in FIELD_NAMES.items()}})
    actor=next(u for u in state['users'] if u['id']=='u-manager')
    p['pm_id']=actor['id']; n['owner_id']=actor['id']
    actor.update(directory_status='employed',directory_missing=False,
        directory_source={'app_id':h.cfg['LARK_APP_ID'],'record_id':'input-destination-roster'},
        directory_last_seen_at=datetime.now(timezone.utc).isoformat())
    queue(state,'input',actor,{'input_id':'i','project_id':p['id']},'input:i')
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);row.data=storage.save(db,h.B,h.wid,state)
        db.get(h.P,(h.wid,actor['id'])).data=deepcopy(actor)
    h.cfg.update(LARK_INPUT_BASE_TOKEN='registrationBase',LARK_INPUT_TABLE_ID='approvedTable')
    import json
    h.cfg['LARK_INPUT_REGISTRATION_FIELDS_JSON']=json.dumps(state['input_revisions'][0]['registration_plan']['destination']['fields'])
    calls=[]
    def factory(cfg):calls.append('called');raise AssertionError('Remote factory must not run')
    worker=Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path,adapter_factory=factory)
    worker.run_one(h.wid)
    job=next(j for j in h.read()[0]['jobs'] if j['kind']=='input' and j['payload']['input_id']=='i')
    assert job['status']=='blocked' and '登錄' in job['error'] and not calls
