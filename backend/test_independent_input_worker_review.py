"""Independent safety regressions from the 2026-09-30 release review."""
import hashlib
from copy import deepcopy
from datetime import datetime,timezone
from types import SimpleNamespace
import pytest
from fastapi import FastAPI,Request
from fastapi.testclient import TestClient
from .request_limits import JsonRequestLimit
from .input_registration import RegistrationAdapter
from .test_input_registration import fixture,Fake,is_write
from .test_source_sync import harness
from .operations import queue
from .jobs import Worker
from . import storage


@pytest.mark.parametrize('headers',[{}, {'Content-Type':'text/plain'}])
def test_json_body_limit_cannot_be_bypassed_by_content_type(headers):
    app=FastAPI();app.add_middleware(JsonRequestLimit,limit=64)
    @app.post('/api/probe')
    async def probe(request:Request):
        return {'length':len((await request.json())['text'])}
    client=TestClient(app)
    response=client.post('/api/probe',content=b'{"text":"'+b'x'*128+b'"}',headers=headers)
    assert response.status_code==413


def test_incomplete_search_metadata_never_authorizes_duplicate_append():
    plan,policy=fixture()
    expected={plan['destination']['fields'][key]['field_name']:value for key,value in plan['values'].items()}
    class PartialSearch(Fake):
        first=True
        def request(self,method,path,**kwargs):
            result=super().request(method,path,**kwargs)
            if path.endswith('/fields'):result['has_more']=False
            if path.endswith('/records/search') and self.first:
                self.first=False
                return {'items':[]}  # No proof the complete filter result was returned.
            return result
    fake=PartialSearch(plan);fake.rows=[{'record_id':'already-present','fields':expected}]
    try:RegistrationAdapter(fake).submit(plan,policy)
    except Exception:pass
    assert not any(map(is_write,fake.calls))
    assert len(fake.rows)==1


@pytest.mark.parametrize('failure',['folder_checkpoint','upload_checkpoint','folder_remote_unknown','upload_remote_unknown','verify_read','verify_final_checkpoint'])
def test_drive_side_effect_recovery_never_reuploads(harness,tmp_path,monkeypatch,failure):
    h=harness;state,_=h.read();p=state['projects'][0];n=p['nodes'][0]
    p['execution_system']='workbench'
    actor=next(u for u in state['users'] if u['id']=='u-manager')
    p['pm_id']=actor['id'];n['owner_id']=actor['id']
    actor.update(directory_status='employed',directory_missing=False,
        directory_source={'app_id':h.cfg['LARK_APP_ID'],'record_id':'file-worker-roster'},
        directory_last_seen_at=datetime.now(timezone.utc).isoformat())
    state['settings'].update(external_enabled=True,drive_root='formal-drive-root')
    h.cfg['LARK_DRIVE_ROOT']='formal-drive-root'
    p['files']=[{'id':'proof-file','name':'survey.txt','node_id':n['id'],'direction':'evidence','storage':'local','size':8}]
    job=queue(state,'file',actor,{'project_id':p['id'],'file_id':'proof-file'},'file:proof-file')
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);row.data=storage.save(db,h.B,h.wid,state)
        db.get(h.P,(h.wid,actor['id'])).data=deepcopy(actor)
    folder=tmp_path/hashlib.sha256(h.wid.encode()).hexdigest();folder.mkdir()
    (folder/'proof-file').write_bytes(b'evidence')
    uploads=[];folders=[];verified=[]
    class Adapter:
        client=SimpleNamespace(close=lambda:None)
        def folder(self,parent,name):
            folders.append(name)
            if failure=='folder_remote_unknown':raise TimeoutError('remote folder response lost')
            return 'folder'
        def upload(self,path,parent,name):
            uploads.append(name)
            if failure=='upload_remote_unknown':raise TimeoutError('remote upload response lost')
            return {'file_token':'remote-file','sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        def verify_file(self,token,digest):
            verified.append(token)
            if failure=='verify_read' and len(verified)==1:
                from .lark_adapter import RemoteFailure
                raise RemoteFailure('download temporarily unavailable')
            return {'verified':True}
    worker=Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path,lambda cfg:Adapter())
    original=worker.checkpoint;failed=[]
    def transient_failure(*args,**kwargs):
        fail_now=(failure=='folder_checkpoint' and folders or failure=='upload_checkpoint' and uploads
                  or failure=='verify_final_checkpoint' and verified)
        if fail_now and not failed:
            failed.append(True)
            raise RuntimeError('temporary commit failure after actual upload')
        return original(*args,**kwargs)
    monkeypatch.setattr(worker,'checkpoint',transient_failure)
    worker.run_one(h.wid)
    result=next(j for j in h.read()[0]['jobs'] if j['id']==job['id'])
    if failure in ('folder_checkpoint','upload_checkpoint','folder_remote_unknown','upload_remote_unknown'):
        assert len(uploads)==(0 if failure.startswith('folder_') else 1)
        assert result['status']=='outcome_unknown'
        previous_calls=(len(folders),len(uploads))
        # A later worker pass must leave the uncertain effect quarantined.
        worker.run_one(h.wid)
        assert (len(folders),len(uploads))==previous_calls
    else:
        assert result['status']=='failed' and result['retry_only']=='verify_file'
        assert any(step['key']=='upload' for step in result['steps'])
        # Simulate authorized retry. Even loss of the local file must not
        # replace a remotely saved file when an exact receipt is available.
        (folder/'proof-file').unlink()
        with h.sessions.begin() as db:
            row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
            current=next(j for j in state['jobs'] if j['id']==job['id'])
            current.update(status='queued',next_attempt_at='')
            row.data=storage.save(db,h.B,h.wid,state)
        worker.run_one(h.wid)
        result=next(j for j in h.read()[0]['jobs'] if j['id']==job['id'])
        assert result['status']=='succeeded'
        assert len(uploads)==1 and len(folders)==3 and len(verified)==2


def test_multipart_limit_runs_before_upload_parser_or_handler():
    app=FastAPI();app.add_middleware(JsonRequestLimit,limit=64,upload_limit=100)
    reached=[]
    @app.post('/api/files')
    async def files(request:Request):
        reached.append(True)
        return {'ok':True}
    client=TestClient(app)
    response=client.post('/api/files',content=b'x'*101,headers={'Content-Type':'multipart/form-data; boundary=test'})
    assert response.status_code==413 and not reached
