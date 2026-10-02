"""Only explicit isolated Input/Drive targets can cross the test boundary."""
from copy import deepcopy
from types import SimpleNamespace
import hashlib
import json
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from . import storage, integration_routes
from .jobs import Worker
from .lark_adapter import LarkAdapter, RemoteFailure
from .operations import queue
from .remote_policy import connection_policy, FORMAL_BASES
from .test_source_sync import harness
from .workflow import now


@pytest.fixture
def isolated(harness,tmp_path):
    h=harness; state,_=h.read(); wid='test-'+h.wid; state['environment']='test'
    state['settings'].update(external_enabled=True,test_connection_mode='isolated_live',test_base='isolatedBase',test_input_table='tblInput',test_drive_root='isolatedDrive',drive_root='formalDrive')
    cfg={**h.cfg,'LARK_WORKER_IDENTITY':'application','LARK_WORKER_ORGANIZATION':'tenant','LARK_TEST_BASE_TOKEN':'isolatedBase','LARK_TEST_INPUT_TABLE_ID':'tblInput','LARK_TEST_DRIVE_ROOT':'isolatedDrive'}
    actor=next(u for u in state['users'] if u['id']=='u-manager')
    actor.update(identity_app_id='app1',directory_status='employed',directory_missing=False,
                 directory_source={'app_id':'app1','record_id':'verified-manager'},directory_last_seen_at=now())
    p=state['projects'][0]; n=p['nodes'][0]
    # System administration alone grants no delivery authority.
    p['pm_id']=actor['id']; n['owner_id']=actor['id']
    mapping={'id':'map1','project_id':p['id'],'node_id':n['id'],'base_token':'isolatedBase','table_id':'tblInput','record_id':'recInput','field_id':'fldInput','field_name':'Input','type':'text','enabled':True,'verified':True,'remote_value':'before'}
    state['input_mappings']=[mapping]
    state['input_revisions']=[{'id':'input1','mapping_id':'map1','project_id':p['id'],'node_id':n['id'],'value':'after','base_value':'before','status':'queued'}]
    blob=b'isolated-test-file'; folder=tmp_path/hashlib.sha256(wid.encode()).hexdigest(); folder.mkdir(); (folder/'file1').write_bytes(blob)
    p['files']=[{'id':'file1','node_id':n['id'],'storage':'local','direction':'output','name':'result.txt','remote_status':'queued'}]
    with h.sessions.begin() as db:
        db.get(h.P,(h.wid,actor['id'])).data=deepcopy(actor)
        row=h.W(id=wid,version=state['version'],data={}); db.add(row); db.flush(); row.data=storage.save(db,h.B,wid,state)
    remote={'value':'before','requests':[],'folders':{},'uploads':0,'factory_calls':0,'after_folder':None,'after_input_read':None}
    def handler(request):
        path=request.url.path; remote['requests'].append((request.method,path))
        if '/bitable/' in path:
            assert '/apps/isolatedBase/' in path
            if path.endswith('/fields'): data={'items':[{'field_id':'fldInput','field_name':'Input','type':1}],'has_more':False}
            else:
                if request.method=='PUT': remote['value']=json.loads(request.content)['fields']['Input']
                data={'record':{'record_id':'recInput','fields':{'Input':remote['value']}}}
                if request.method=='GET' and remote['after_input_read']: remote['after_input_read']()
            return httpx.Response(200,json={'code':0,'data':data})
        if path.endswith('/drive/v1/files'):
            parent=request.url.params['folder_token']
            return httpx.Response(200,json={'data':{'files':remote['folders'].get(parent,[]),'has_more':False}})
        if path.endswith('/drive/v1/files/create_folder'):
            body=json.loads(request.content); parent=body['folder_token']; token='folder'+str(sum(map(len,remote['folders'].values()))+1)
            remote['folders'].setdefault(parent,[]).append({'token':token,'name':body['name'],'type':'folder'})
            if remote['after_folder']: remote['after_folder']()
            return httpx.Response(200,json={'data':{'token':token}})
        if path.endswith('/drive/v1/files/upload_all'):
            remote['uploads']+=1
            return httpx.Response(200,json={'data':{'file_token':'isolatedFile'}})
        if path.endswith('/drive/v1/files/isolatedFile/download'): return httpx.Response(200,content=blob)
        pytest.fail('Unexpected request: '+request.method+' '+path)
    def factory(_cfg):
        remote['factory_calls']+=1
        return LarkAdapter('fake',httpx.Client(transport=httpx.MockTransport(handler)))
    def read():
        with h.sessions() as db: return storage.load(db,h.B,db.get(h.W,wid))
    def save(updated):
        with h.sessions.begin() as db:
            row=db.get(h.W,wid); row.data=storage.save(db,h.B,wid,updated); row.version=updated['version']
    def enqueue(kind):
        state=read(); actor=next(u for u in state['users'] if u['id']=='u-manager')
        payload={'input_id':'input1','project_id':p['id']} if kind=='input' else {'project_id':p['id'],'file_id':'file1'}
        queue(state,kind,actor,payload,kind+'1'); save(state)
    worker=Worker(h.sessions,h.W,h.B,h.P,cfg,tmp_path,adapter_factory=factory)
    return SimpleNamespace(h=h,wid=wid,cfg=cfg,worker=worker,read=read,save=save,enqueue=enqueue,remote=remote,factory=factory,uploads=tmp_path)


def test_isolated_legacy_input_cannot_overwrite_even_an_approved_test_base(isolated):
    x=isolated; x.enqueue('input'); x.worker.run_one(x.wid); state=x.read(); job=state['jobs'][0]
    assert job['status']=='blocked' and '獨立登錄' in job['error']
    assert x.remote['value']=='before' and not x.remote['requests']
    assert x.remote['factory_calls']==0


def test_isolated_file_upload_starts_at_test_root_and_checks_bytes(isolated):
    x=isolated; x.enqueue('file'); x.worker.run_one(x.wid); state=x.read(); item=state['projects'][0]['files'][0]
    assert item['remote_status']=='verified' and item['remote_receipt']['simulated'] is False
    assert item['remote_receipt']['destination_root']=='isolatedDrive'
    assert 'isolatedDrive' in x.remote['folders'] and 'formalDrive' not in x.remote['folders']
    assert x.remote['uploads']==1 and x.remote['requests'][-1][1].endswith('/download')


@pytest.mark.parametrize('kind',['input','file'])
def test_simulation_mode_never_creates_adapter_even_with_test_destinations(isolated,kind):
    x=isolated; state=x.read(); state['settings']['test_connection_mode']='simulation'; x.save(state)
    x.enqueue(kind); x.worker.run_one(x.wid); state=x.read()
    assert state['jobs'][0]['simulated'] is True and x.remote['factory_calls']==0


@pytest.mark.parametrize('mutation',[
    'wrong_tenant','wrong_environment','disabled','missing_config','mismatch_config','wrong_identity','unknown_mode','formal_mapping','unverified_mapping',
])
def test_unsafe_isolated_input_setup_is_blocked_before_remote_io(isolated,mutation):
    x=isolated; state=x.read()
    if mutation=='wrong_tenant': x.cfg['LARK_WORKER_ORGANIZATION']='other'
    elif mutation=='wrong_environment': state['environment']='production'
    elif mutation=='disabled': state['settings']['external_enabled']=False
    elif mutation=='missing_config': x.cfg.pop('LARK_TEST_BASE_TOKEN')
    elif mutation=='mismatch_config': x.cfg['LARK_TEST_BASE_TOKEN']='anotherIsolatedBase'
    elif mutation=='wrong_identity': x.cfg['LARK_WORKER_IDENTITY']='user'
    elif mutation=='unknown_mode': state['settings']['test_connection_mode']='live'
    elif mutation=='formal_mapping': state['input_mappings'][0]['base_token']=next(iter(FORMAL_BASES))
    elif mutation=='unverified_mapping': state['input_mappings'][0]['verified']=False
    x.save(state); x.enqueue('input')
    if mutation in ('wrong_environment','wrong_tenant'):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as error:x.worker.run_one(x.wid)
        assert error.value.status_code==(409 if mutation=='wrong_environment' else 403) and x.remote['requests']==[]
        return
    x.worker.run_one(x.wid)
    assert x.read()['jobs'][0]['status']=='blocked' and x.remote['requests']==[]


@pytest.mark.parametrize('base',sorted(FORMAL_BASES))
def test_all_known_company_bases_are_denied_even_if_both_settings_agree(isolated,base):
    x=isolated; state=x.read(); state['settings']['test_base']=base; x.cfg['LARK_TEST_BASE_TOKEN']=base
    with pytest.raises(RemoteFailure): connection_policy(x.wid,state,x.cfg,'input')


def test_formal_drive_root_is_denied_even_if_both_settings_agree(isolated):
    x=isolated; state=x.read(); state['settings']['test_drive_root']='formalDrive'; x.cfg['LARK_TEST_DRIVE_ROOT']='formalDrive'; x.save(state)
    x.enqueue('file'); x.worker.run_one(x.wid)
    assert x.read()['jobs'][0]['status']=='blocked' and not x.remote['requests']


def test_changed_server_destination_after_token_acquisition_stops_write(isolated):
    x=isolated; x.enqueue('input')
    def factory(cfg):
        adapter=x.factory(cfg); cfg['LARK_TEST_BASE_TOKEN']='changedAfterAuthentication'; return adapter
    x.worker.adapter_factory=factory; x.worker.run_one(x.wid)
    assert x.read()['jobs'][0]['status']=='blocked' and x.remote['requests']==[]


def test_changed_drive_destination_during_folder_creation_stops_remaining_effects(isolated):
    x=isolated; x.enqueue('file')
    def change():
        state=x.read(); state['settings']['test_drive_root']='otherRoot'; x.save(state)
    x.remote['after_folder']=change; x.worker.run_one(x.wid)
    assert x.read()['jobs'][0]['status']=='blocked' and x.remote['uploads']==0
    assert sum(method=='POST' for method,path in x.remote['requests'])==1


def test_revocation_between_input_read_and_write_blocks_actual_put(isolated):
    x=isolated; x.enqueue('input')
    def revoke():
        state=x.read(); state['input_mappings'][0]['enabled']=False; x.save(state)
    x.remote['after_input_read']=revoke; x.worker.run_one(x.wid)
    assert x.read()['jobs'][0]['status']=='blocked'
    assert x.remote['value']=='before' and not any(method=='PUT' for method,path in x.remote['requests'])


@pytest.mark.parametrize('kind',['confirmation','digest'])
def test_non_file_input_test_jobs_are_always_simulated(isolated,kind):
    x=isolated
    assert connection_policy(x.wid,x.read(),x.cfg,kind)['simulated'] is True


def test_demo_never_uses_isolated_live_connection(isolated):
    x=isolated; state=x.read(); state['environment']='demo'
    assert connection_policy('demo-user',state,x.cfg,'input')['simulated'] is True
    assert connection_policy('demo-user',state,x.cfg,'file')['simulated'] is True


def test_test_digest_worker_never_sends_real_notification(isolated):
    x=isolated; state=x.read(); actor=next(u for u in state['users'] if u['id']=='u-manager')
    queue(state,'digest',actor,{'recipients':[actor['id']],'text':'mock-only'},'digest-test'); x.save(state)
    x.worker.run_one(x.wid)
    assert x.read()['jobs'][0]['simulated'] is True and x.remote['factory_calls']==0


def make_client(x,monkeypatch):
    app=FastAPI(); h=x.h
    def identity(request): return {'wid':x.wid},next(u for u in x.read()['users'] if u['id']=='u-manager')
    def load(db,row): return storage.load(db,h.B,row)
    def persist(wid,version,mutate,actor_id=None,project_versions=None):
        state=x.read()
        if project_versions:
            assert all(next(p for p in state['projects'] if p['id']==pid).get('concurrency_version',0)==v
                       for pid,v in project_versions.items())
        else:
            assert state['version']==version
        mutate(state); state['version']+=1; x.save(state); return state
    monkeypatch.setattr(integration_routes,'application_adapter',x.factory)
    integration_routes.register(app,identity,load,persist,h.sessions,h.W,h.B,h.P,x.cfg,x.uploads)
    return TestClient(app)


def test_input_verify_endpoint_allows_only_explicit_test_mapping(isolated,monkeypatch):
    x=isolated; state=x.read(); state['input_mappings'][0]['verified']=False; x.save(state)
    with make_client(x,monkeypatch) as client:
        response=client.post('/api/input-mappings/map1/verify',json={'version':state['version']})
    assert response.status_code==200, response.text
    mapping=x.read()['input_mappings'][0]
    assert mapping['verified'] is True and mapping['verified_mode']=='isolated_live'
    assert mapping['remote_value']=='before' and all(method=='GET' for method,path in x.remote['requests'])


def test_input_verify_endpoint_denies_simulation_without_remote_read(isolated,monkeypatch):
    x=isolated; state=x.read(); state['settings']['test_connection_mode']='simulation'; x.save(state)
    with make_client(x,monkeypatch) as client:
        response=client.post('/api/input-mappings/map1/verify',json={'version':state['version']})
    assert response.status_code==409 and x.remote['requests']==[]


def test_input_verify_does_not_commit_mapping_if_destination_changes_after_readback(isolated,monkeypatch):
    x=isolated; state=x.read(); state['input_mappings'][0]['verified']=False; x.save(state)
    x.remote['after_input_read']=lambda:x.cfg.update(LARK_TEST_BASE_TOKEN='changed')
    with make_client(x,monkeypatch) as client:
        response=client.post('/api/input-mappings/map1/verify',json={'version':state['version']})
    assert response.status_code==409 and x.read()['input_mappings'][0]['verified'] is False
