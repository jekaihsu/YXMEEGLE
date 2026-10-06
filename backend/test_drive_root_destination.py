"""Issue #35: production Drive uploads must target the server-approved root, never the test root."""
import hashlib
from copy import deepcopy
from datetime import datetime,timezone
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from .policy import defaults
from .remote_policy import connection_policy
from .lark_adapter import RemoteFailure
from .test_source_sync import harness
from .operations import queue,apply_operation
from .jobs import Worker
from . import storage

APPROVED='approved-root'
TEST_ROOT='test-root'


def configured(root=APPROVED):
    state={'environment':'production','settings':dict(defaults(),external_enabled=True,drive_root=root,test_drive_root=TEST_ROOT)}
    cfg={'LARK_WORKER_ORGANIZATION':'company','LARK_WORKER_IDENTITY':'application',
         'LARK_DRIVE_ROOT':APPROVED,'LARK_TEST_DRIVE_ROOT':TEST_ROOT}
    return state,cfg


@pytest.mark.parametrize('root',['','   ',None,'unapproved-root',TEST_ROOT])
@pytest.mark.parametrize('verify',[False,True])
def test_policy_rejects_blank_unapproved_and_test_roots(root,verify):
    state,cfg=configured(root)
    with pytest.raises(RemoteFailure):connection_policy('lark-company',state,cfg,'file',for_verification=verify)


def test_policy_rejects_when_server_has_no_approved_root():
    state,cfg=configured();cfg.pop('LARK_DRIVE_ROOT')
    with pytest.raises(RemoteFailure):connection_policy('lark-company',state,cfg,'file')


def test_policy_rejects_when_approved_root_equals_test_root():
    state,cfg=configured(TEST_ROOT);cfg['LARK_DRIVE_ROOT']=TEST_ROOT
    with pytest.raises(RemoteFailure):connection_policy('lark-company',state,cfg,'file')


def test_policy_accepts_approved_root_and_ignores_it_for_other_kinds():
    state,cfg=configured()
    assert connection_policy('lark-company',state,cfg,'file')['drive_root']==APPROVED
    state['settings']['drive_root']='unapproved-root'
    assert connection_policy('lark-company',state,cfg,'notification')['drive_root'] is None


def test_settings_save_rejects_unapproved_and_test_roots_only_when_checked_against_server(harness):
    h=harness;state,_=h.read();actor=next(u for u in state['users'] if u['role']=='manager')
    cfg={'LARK_DRIVE_ROOT':APPROVED,'LARK_TEST_DRIVE_ROOT':TEST_ROOT}
    for root in ('unapproved-root',TEST_ROOT):
        with pytest.raises(HTTPException) as error:
            apply_operation(state,actor,{'action':'admin_settings','payload':{'drive_root':root}},False,cfg)
        assert error.value.status_code==422
        assert state['settings']['drive_root']!=root
    apply_operation(state,actor,{'action':'admin_settings','payload':{'drive_root':APPROVED}},False,cfg)
    assert state['settings']['drive_root']==APPROVED


def prepare(h,root,tmp_path,receipt=None):
    state,_=h.read();p=state['projects'][0];n=p['nodes'][0]
    p['execution_system']='workbench'
    actor=next(u for u in state['users'] if u['id']=='u-manager')
    p['pm_id']=actor['id'];n['owner_id']=actor['id']
    actor.update(directory_status='employed',directory_missing=False,
        directory_source={'app_id':h.cfg['LARK_APP_ID'],'record_id':'drive-root-roster'},
        directory_last_seen_at=datetime.now(timezone.utc).isoformat())
    state['settings'].update(external_enabled=True,drive_root=root,test_drive_root=TEST_ROOT)
    h.cfg.update(LARK_DRIVE_ROOT=APPROVED,LARK_TEST_DRIVE_ROOT=TEST_ROOT)
    p['files']=[{'id':'proof-file','name':'survey.txt','node_id':n['id'],'direction':'evidence','storage':'local','size':8}]
    job=queue(state,'file',actor,{'project_id':p['id'],'file_id':'proof-file'},'file:proof-file')
    if receipt: job['steps'].append({'key':'upload','receipt':receipt,'at':'2026-10-01T00:00:00+08:00'})
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);row.data=storage.save(db,h.B,h.wid,state)
        db.get(h.P,(h.wid,actor['id'])).data=deepcopy(actor)
    folder=tmp_path/hashlib.sha256(h.wid.encode()).hexdigest();folder.mkdir()
    (folder/'proof-file').write_bytes(b'evidence')
    return job


def counting_worker(h,tmp_path):
    calls=[];made=[]
    class Adapter:
        client=SimpleNamespace(close=lambda:None)
        def folder(self,parent,name):
            calls.append(('folder',parent,name));return 'folder'
        def upload(self,path,parent,name):
            calls.append(('upload',parent,name))
            return {'file_token':'remote-file','sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        def verify_file(self,token,digest):
            calls.append(('verify',token));return {'verified':True}
    def factory(cfg):
        made.append(True);return Adapter()
    return Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path,factory),calls,made


def result_of(h,job):
    return next(j for j in h.read()[0]['jobs'] if j['id']==job['id'])


@pytest.mark.parametrize('root',['','unapproved-root',TEST_ROOT])
def test_worker_rejects_bad_roots_before_any_remote_io(harness,tmp_path,root):
    h=harness;job=prepare(h,root,tmp_path)
    worker,calls,made=counting_worker(h,tmp_path)
    worker.run_one(h.wid)
    assert calls==[] and made==[]
    assert result_of(h,job)['status']!='succeeded'


def test_worker_uploads_under_approved_root(harness,tmp_path):
    h=harness;job=prepare(h,APPROVED,tmp_path)
    worker,calls,_=counting_worker(h,tmp_path)
    worker.run_one(h.wid)
    result=result_of(h,job)
    assert result['status']=='succeeded'
    assert calls[0]==('folder',APPROVED,calls[0][2])
    assert next(s for s in result['steps'] if s['key']=='upload')['receipt']['destination_root']==APPROVED


def test_existing_receipt_destination_is_rechecked_after_config_change(harness,tmp_path):
    h=harness
    receipt={'file_token':'remote-file','sha256':hashlib.sha256(b'evidence').hexdigest(),
        'simulated':False,'remote_mode':'production','destination_root':'previous-approved-root'}
    # Server and workspace both moved to a new approved root; the old receipt must not be accepted as the new destination.
    job=prepare(h,APPROVED,tmp_path,receipt)
    worker,calls,_=counting_worker(h,tmp_path)
    worker.run_one(h.wid)
    result=result_of(h,job)
    assert calls==[] and result['status']!='succeeded'


def test_existing_receipt_for_current_approved_root_verifies_without_reupload(harness,tmp_path):
    h=harness
    receipt={'file_token':'remote-file','sha256':hashlib.sha256(b'evidence').hexdigest(),
        'simulated':False,'remote_mode':'production','destination_root':APPROVED}
    job=prepare(h,APPROVED,tmp_path,receipt)
    worker,calls,_=counting_worker(h,tmp_path)
    worker.run_one(h.wid)
    assert result_of(h,job)['status']=='succeeded'
    assert [c[0] for c in calls]==['verify']
