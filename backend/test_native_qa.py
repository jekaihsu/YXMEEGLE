from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from types import SimpleNamespace

import pytest

from .native_qa import QAError, QAStore, QARunner, policy
from .native_approval import prepare_binding
from .lark_adapter import RemoteFailure
from .test_native_approval import fixture


@pytest.fixture
def qa(tmp_path):
    mapping, definition, *_ = fixture()
    mapping.update(kind='extension', approval_code='dedicated-qa-definition')
    mapping['nodes'][0]['seats']=['supervisor']
    definition['approval_name']='QA extension transport acceptance'
    manifest={'schema_version':1,'purpose':'native_qa_transport_only','app_id':'app','tenant':'company',
              'definition_name':definition['approval_name'],'mapping':mapping,
              'participants':{'applicant':'ou_applicant','approvers':{'supervisor':'ou_staff'},
                              'allowlist':['ou_applicant','ou_staff']},
              'authorization':{'decision_ref':'explicit QA authorization','authorized_by':'user',
                               'reason':'isolated test only','expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}}
    credentials={'LARK_APP_ID':'app','LARK_APP_SECRET':'secret-must-never-print',
                 'LARK_WORKER_ORGANIZATION':'company','LARK_ALLOWED_TENANTS':'company',
                 'LARK_WORKER_IDENTITY':'application',
                 'LARK_NATIVE_APPROVAL_MAPPINGS_JSON':json.dumps({kind:{'approval_code':'production-'+kind}
                    for kind in ('financial','change','extension','node_skip')})}
    store=QAStore(tmp_path/'qa.sqlite');calls=[];payload={};external=['PENDING'];failure=[None];before_post=[]
    class Adapter:
        client=SimpleNamespace(close=lambda:None)
        def request(self,method,path,**kwargs):
            calls.append((method,path))
            if '/approvals/' in path:
                return deepcopy(definition)
            if method=='POST':
                before_post.append(store.get('qa-one')['attempted'])
                payload.update(deepcopy(kwargs['json']))
                if failure[0] in ('timeout','unavailable'):raise RemoteFailure('remote token detail','outcome_unknown')
                if failure[0]=='crash':raise RuntimeError('process crashed')
                return {'instance_code':'instance-qa'}
            if failure[0]=='unavailable':raise RemoteFailure('not visible','failed')
            if failure[0]=='malformed':return None
            assert path.endswith(payload['uuid'])
            votes=[(node['key'],ident) for node in payload['node_approver_open_id_list'] for ident in node['value']]
            return {'approval_code':payload['approval_code'],'open_id':payload['open_id'],
                    'uuid':payload['uuid'],'instance_code':'instance-qa','form':payload['form'],'status':external[0],
                    'task_list':[{'id':'task-'+ident,'node_id':node,'open_id':ident,'type':'AND','status':'APPROVED'} for node,ident in votes],
                    'timeline':[{'type':'PASS','task_id':'task-'+ident,'open_id':ident} for _,ident in votes]}
    factory=lambda _:Adapter()
    runner=QARunner(store,lambda:(deepcopy(manifest),deepcopy(credentials)),factory)
    return SimpleNamespace(runner=runner,store=store,manifest=manifest,credentials=credentials,definition=definition,
                           calls=calls,payload=payload,external=external,failure=failure,before_post=before_post,factory=factory)


def test_prepare_is_get_only_and_qa_namespace_cannot_be_a_production_binding(qa):
    result=qa.runner.prepare('qa-one')
    assert not result['attempted'] and not result['business_apply_allowed']
    assert len(qa.calls)==1 and qa.calls[0][0]=='GET'
    binding=qa.store.get('qa-one')['binding']
    assert 'workspace_id' not in binding['identity'] and 'project_id' not in binding['identity']
    with pytest.raises(RemoteFailure):
        prepare_binding(mapping=binding['mapping'],definition=qa.definition,context=binding['identity'],
                        applicant='ou_applicant',approvers=binding['approvers'],content={'test':'only'})
    assert 'secret-must-never-print' not in json.dumps(result)


def test_explicit_create_and_durable_checkpoint_then_human_receipt_only(qa):
    first=qa.runner.prepare('qa-one')
    with pytest.raises(QAError,match='explicit_allow_create_required'):qa.runner.create('qa-one')
    result=qa.runner.create('qa-one',allow_create=True)
    assert result['status']=='pending' and qa.before_post==[1]
    assert not result['approved'] and not result['business_apply_allowed']
    qa.external[0]='APPROVED'
    approved=qa.runner.poll('qa-one')
    assert approved['approved'] and approved['binding_verified'] and not approved['business_apply_allowed']
    assert approved['uuid']==first['uuid']
    assert all(path=='/approval/v4/instances' for method,path in qa.calls if method=='POST')
    assert 'APPROVAL' not in qa.payload  # no auto-approval or voting payload
    assert not any('approve' in key or 'auto' in key for key in qa.payload if key!='node_approver_open_id_list')


@pytest.mark.parametrize('failure',['timeout','unavailable','crash'])
def test_uncertain_post_and_restart_never_post_again(qa,failure):
    initial=qa.runner.prepare('qa-one');qa.failure[0]=failure
    if failure=='crash':
        with pytest.raises(RuntimeError):qa.runner.create('qa-one',allow_create=True)
    else:
        qa.runner.create('qa-one',allow_create=True)
    assert qa.store.get('qa-one')['attempted']==1
    qa.failure[0]=None
    restarted=QARunner(QAStore(qa.store.path),qa.runner.load_config,qa.factory)
    recovered=restarted.create('qa-one',allow_create=True)
    assert recovered['uuid']==initial['uuid'] and recovered['status']=='pending'
    assert sum(method=='POST' for method,_ in qa.calls)==1


def test_parallel_attempt_claim_is_single_and_stale_receipt_cannot_overwrite(qa):
    qa.runner.prepare('qa-one');version=qa.store.get('qa-one')['version']
    first,claimed=qa.store.claim('qa-one',version)
    second,claimed_again=QAStore(qa.store.path).claim('qa-one',version)
    assert claimed and not claimed_again and second['attempted']
    qa.store.save(first,'pending')
    with pytest.raises(QAError,match='qa_concurrent_update'):qa.store.save(second,'approved')


@pytest.mark.parametrize('change',['definition','name','policy','allowlist'])
def test_drift_blocks_create_before_attempt(qa,change):
    qa.runner.prepare('qa-one')
    if change=='definition':qa.definition['status']='DELETED'
    if change=='name':qa.definition['approval_name']='Production work'
    if change=='policy':qa.credentials['LARK_APP_ID']='other'
    if change=='allowlist':qa.manifest['participants']['allowlist'].append('ou_extra')
    with pytest.raises((QAError,RemoteFailure)):qa.runner.create('qa-one',allow_create=True)
    assert not qa.store.get('qa-one')['attempted'] and not any(method=='POST' for method,_ in qa.calls)


def test_failed_poll_invalidates_old_approved_receipt(qa):
    qa.runner.prepare('qa-one');qa.external[0]='APPROVED'
    assert qa.runner.create('qa-one',allow_create=True)['approved']
    qa.failure[0]='malformed'
    result=qa.runner.poll('qa-one')
    assert not result['approved'] and result['status']=='outcome_unknown'
    assert not qa.store.get('qa-one')['receipt']


def test_repeated_prepare_preserves_uuid_and_attempt(qa):
    first=qa.runner.prepare('qa-one');qa.runner.create('qa-one',allow_create=True)
    again=qa.runner.prepare('qa-one')
    assert again['uuid']==first['uuid'] and again['attempted']
    assert sum(method=='POST' for method,_ in qa.calls)==1


@pytest.mark.parametrize('change',['production','unknown_kind','wrong_seats','same_approver','missing_allowlist','expired','missing_inventory'])
def test_local_manifest_rejects_unsafe_policy(qa,change):
    m=qa.manifest;c=qa.credentials
    if change=='production':m['mapping']['approval_code']='production-extension'
    if change=='unknown_kind':m['mapping']['kind']='custom'
    if change=='wrong_seats':m['mapping']['nodes'][0]['seats']=['pm']
    if change=='same_approver':
        m['mapping']['kind']='node_skip';m['mapping']['nodes'][0]['seats']=['pm','supervisor']
        m['participants']['approvers']={'pm':'ou_staff','supervisor':'ou_staff'}
    if change=='missing_allowlist':m['participants'].pop('allowlist')
    if change=='expired':m['authorization']['expires_at']='2020-01-01T00:00:00+00:00'
    if change=='missing_inventory':c['LARK_NATIVE_APPROVAL_MAPPINGS_JSON']='{}'
    with pytest.raises(QAError):policy(m,c)
    assert not qa.calls


def test_existing_non_qa_database_is_not_modified(tmp_path):
    path=tmp_path/'company.sqlite'
    with sqlite3.connect(path) as db:db.execute('CREATE TABLE workspaces (id TEXT)')
    before=path.read_bytes()
    with pytest.raises(QAError,match='not_a_qa_database'):QAStore(path)
    assert path.read_bytes()==before


def test_binding_tamper_blocks_before_io(qa):
    qa.runner.prepare('qa-one');record=qa.store.get('qa-one')
    record['binding']['payload']['open_id']='ou_intruder'
    with qa.store.connect() as db:
        db.execute('UPDATE qa_runs SET binding=? WHERE run_id=?',(json.dumps(record['binding']),'qa-one'))
    before=len(qa.calls)
    with pytest.raises(QAError,match='qa_binding_tampered'):qa.runner.create('qa-one',allow_create=True)
    assert len(qa.calls)==before


def test_attempt_checkpoint_failure_prevents_post(qa,monkeypatch):
    qa.runner.prepare('qa-one')
    def fail(*args,**kwargs):raise sqlite3.OperationalError('cannot commit')
    monkeypatch.setattr(qa.store,'claim',fail)
    with pytest.raises(sqlite3.OperationalError):qa.runner.create('qa-one',allow_create=True)
    assert not qa.store.get('qa-one')['attempted'] and not any(m=='POST' for m,_ in qa.calls)


def test_participant_revocation_during_definition_get_prevents_post(qa):
    qa.runner.prepare('qa-one')
    original=qa.runner.adapter_factory
    def factory(cfg):
        adapter=original(cfg);request=adapter.request
        def changed(*args,**kwargs):
            result=request(*args,**kwargs)
            qa.manifest['participants']['allowlist']=[]
            return result
        adapter.request=changed
        return adapter
    qa.runner.adapter_factory=factory
    with pytest.raises(QAError):qa.runner.create('qa-one',allow_create=True)
    assert not qa.store.get('qa-one')['attempted'] and not any(m=='POST' for m,_ in qa.calls)


def test_approved_without_actual_human_pass_is_never_verified(qa):
    qa.runner.prepare('qa-one');qa.external[0]='APPROVED'
    original=qa.runner.adapter_factory
    def factory(cfg):
        adapter=original(cfg);request=adapter.request
        def automatic(method,path,**kwargs):
            result=request(method,path,**kwargs)
            if method=='GET' and '/instances/' in path:result['timeline']=[{'type':'AUTO_PASS'}]
            return result
        adapter.request=automatic
        return adapter
    qa.runner.adapter_factory=factory
    result=qa.runner.create('qa-one',allow_create=True)
    assert not result['approved'] and not result['binding_verified']
    assert result['status']=='outcome_unknown'


def test_cli_doctor_is_offline_and_output_never_contains_credentials(qa,tmp_path,monkeypatch,capsys):
    from scripts import native_qa_runner
    config=tmp_path/'manifest.json';credentials=tmp_path/'credentials.json'
    config.write_text(json.dumps(qa.manifest),encoding='utf-8')
    credentials.write_text(json.dumps(qa.credentials),encoding='utf-8')
    import os
    for key in list(os.environ):
        if key.startswith('LARK_'):monkeypatch.delenv(key)
    def forbidden(*args,**kwargs):raise AssertionError('doctor must not access network')
    monkeypatch.setattr(native_qa_runner,'application_adapter',forbidden)
    args=['--config',str(config),'--saved-config',str(credentials),'doctor']
    assert native_qa_runner.main(args)==0
    result=capsys.readouterr().out
    assert json.loads(result)['result']['network_accessed'] is False
    assert 'secret-must-never-print' not in result and 'ou_staff' not in result
    qa.manifest['participants']['allowlist']=[]
    config.write_text(json.dumps(qa.manifest),encoding='utf-8')
    assert native_qa_runner.main(args)==1
    assert 'secret-must-never-print' not in capsys.readouterr().out
