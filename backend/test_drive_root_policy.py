"""Issue #35: formal Drive uploads must target the server-approved root."""
import hashlib
from copy import deepcopy
from datetime import datetime,timezone
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from . import storage
from .jobs import Worker
from .lark_adapter import RemoteFailure
from .operations import apply_operation,queue
from .policy import defaults
from .remote_policy import connection_policy
from .test_source_sync import harness


def configured(**settings):
    state={'environment':'production','settings':dict(defaults(),external_enabled=True,drive_root='approved-root',test_drive_root='',**settings)}
    cfg={'LARK_WORKER_ORGANIZATION':'company','LARK_WORKER_IDENTITY':'application','LARK_DRIVE_ROOT':'approved-root','LARK_TEST_DRIVE_ROOT':'test-root'}
    return state,cfg


def test_approved_root_is_accepted_and_receipt_destination_follows_it():
    state,cfg=configured()
    assert connection_policy('lark-company',state,cfg,'file')['drive_root']=='approved-root'
    assert connection_policy('lark-company',state,cfg,'file',for_verification=True)['drive_root']=='approved-root'


@pytest.mark.parametrize('root',['unapproved-root','test-root','',None])
def test_unapproved_blank_or_test_root_is_rejected(root):
    state,cfg=configured();state['settings']['drive_root']=root
    with pytest.raises(RemoteFailure):connection_policy('lark-company',state,cfg,'file')


@pytest.mark.parametrize('missing',['LARK_DRIVE_ROOT'])
def test_server_without_approved_root_rejects_workspace_root(missing):
    state,cfg=configured();cfg.pop(missing)
    with pytest.raises(RemoteFailure):connection_policy('lark-company',state,cfg,'file')


def test_root_switch_changes_policy_so_old_receipt_destination_no_longer_matches():
    state,cfg=configured();old=connection_policy('lark-company',state,cfg,'file')
    cfg['LARK_DRIVE_ROOT']=state['settings']['drive_root']='rotated-root'
    assert connection_policy('lark-company',state,cfg,'file')['drive_root']!=old['drive_root']


def manager(state):return next(u for u in state['users'] if u['role']=='manager')


def save(state,cfg,**data):
    apply_operation(state,manager(state),{'action':'admin_settings','payload':data},False,cfg)


def test_settings_save_persists_approved_root_and_rejects_invalid_values(harness):
    state,_=harness.read();cfg={'LARK_DRIVE_ROOT':'approved-root','LARK_TEST_DRIVE_ROOT':'test-root'}
    save(state,cfg,drive_root='approved-root');assert state['settings']['drive_root']=='approved-root'
    for bad in ({'drive_root':'unapproved-root'},{'drive_root':'test-root'},{'drive_root':7},{'test_drive_root':'approved-root'}):
        with pytest.raises(HTTPException) as caught:save(state,cfg,**bad)
        assert caught.value.status_code==422
    assert state['settings']['drive_root']=='approved-root' and not state['settings']['test_drive_root']
    save(state,cfg,test_drive_root='test-root');assert state['settings']['test_drive_root']=='test-root'


def run_file_job(h,tmp_path,root):
    state,_=h.read();p=state['projects'][0];n=p['nodes'][0];p['execution_system']='workbench'
    actor=next(u for u in state['users'] if u['id']=='u-manager');p['pm_id']=actor['id'];n['owner_id']=actor['id']
    actor.update(directory_status='employed',directory_missing=False,directory_source={'app_id':h.cfg['LARK_APP_ID'],'record_id':'r'},
        directory_last_seen_at=datetime.now(timezone.utc).isoformat())
    state['settings'].update(external_enabled=True,drive_root=root)
    h.cfg.update(LARK_DRIVE_ROOT='approved-root',LARK_TEST_DRIVE_ROOT='test-root')
    p['files']=[{'id':'f1','name':'a.txt','node_id':n['id'],'direction':'evidence','storage':'local','size':8}]
    job=queue(state,'file',actor,{'project_id':p['id'],'file_id':'f1'},'file:f1')
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);row.data=storage.save(db,h.B,h.wid,state);db.get(h.P,(h.wid,actor['id'])).data=deepcopy(actor)
    folder=tmp_path/hashlib.sha256(h.wid.encode()).hexdigest();folder.mkdir();(folder/'f1').write_bytes(b'evidence')
    calls=[]
    class Adapter:
        client=SimpleNamespace(close=lambda:None)
        def folder(self,parent,name):calls.append(('folder',parent));return 'folder'
        def upload(self,path,parent,name):calls.append(('upload',parent));return {'file_token':'t','sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        def verify_file(self,token,digest):calls.append(('verify',token));return {'verified':True}
    Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path,lambda cfg:Adapter()).run_one(h.wid)
    return next(j for j in h.read()[0]['jobs'] if j['id']==job['id']),calls


@pytest.mark.parametrize('root',['unapproved-root','test-root',''])
def test_worker_blocks_before_any_remote_write_on_root_mismatch(harness,tmp_path,root):
    job,calls=run_file_job(harness,tmp_path,root)
    assert job['status']=='blocked' and calls==[]


def test_worker_uploads_under_approved_root(harness,tmp_path):
    job,calls=run_file_job(harness,tmp_path,'approved-root')
    assert job['status']=='succeeded' and calls[0]==('folder','approved-root')
    assert next(s for s in job['steps'] if s['key']=='upload')['receipt']['destination_root']=='approved-root'
