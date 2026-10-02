from copy import deepcopy
import json
from datetime import datetime,timezone
from types import SimpleNamespace
import pytest
from scripts import workbench_backup_setup as setup

@pytest.fixture
def operator(tmp_path,monkeypatch):
    monkeypatch.setattr(setup,'STATE',tmp_path)
    state={'app_id':setup.APP,'folder':setup.FOLDER,'bot_open_id':'ou_backup',
           'members':[{'member_type':'openid','member_id':'ou_owner','perm':'full_access'}],
           'public':{'external_access_entity':'closed','link_share_entity':'closed'}}
    monkeypatch.setattr(setup,'facts',lambda:deepcopy(state))
    calls=[]
    def call(args,backup=False):
        calls.append(args)
        if 'create' in args:
            assert (tmp_path/'grant-attempt.json').exists()
            state['members'].append({'member_type':'openid','member_id':'ou_backup','perm':'full_access'})
            return {}
        return {'files':[]}
    monkeypatch.setattr(setup,'call',call)
    return state,calls

def test_compare_grant_readback_and_repeated_grant_no_duplicate(operator):
    state,calls=operator
    setup.run('inspect');assert setup.run('grant')['status']=='pending_ui_readback'
    setup.save('ui-acl.json',{'observed_at':datetime.now(timezone.utc).isoformat()})
    setup.run('grant')
    assert sum('create' in c for c in calls)==1
    assert state['members'][0]['member_id']=='ou_owner'

def test_drift_stops_before_write(operator):
    state,calls=operator;setup.run('inspect');state['public']['extra']='changed'
    with pytest.raises(ValueError):setup.run('grant')
    assert not calls

def test_unknown_attempt_never_reposts(operator):
    state,calls=operator;setup.run('inspect');setup.save('grant-attempt.json',{'attempted':True},True)
    with pytest.raises(FileExistsError):setup.run('grant')
    assert not calls

@pytest.mark.parametrize('status,body,valid',[(200,{'code':0,'bot':{'open_id':'ou_backup'}},True),
    (200,{'code':0,'data':{}},False),(403,{'code':0,'bot':{'open_id':'ou_backup'}},False),
    (200,{'code':1,'bot':{'open_id':'ou_backup'}},False)])
def test_bot_info_reads_top_level_only(tmp_path,monkeypatch,status,body,valid):
    from scripts import backup_offsite
    monkeypatch.setattr(setup,'ROOT',tmp_path);monkeypatch.setattr(setup,'STATE',tmp_path/'state')
    (tmp_path/'.runtime').mkdir()
    (tmp_path/'.runtime/backup-independent-app-private.json').write_text(json.dumps({'BACKUP_LARK_APP_ID':setup.APP}))
    calls=[]
    def get(url,headers):
        calls.append(url);return SimpleNamespace(status_code=status,json=lambda:body)
    adapter=SimpleNamespace(token='test-only',client=SimpleNamespace(get=get,close=lambda:calls.append('closed')))
    monkeypatch.setattr(backup_offsite,'backup_adapter',lambda cfg:adapter)
    if valid:assert setup.backup_bot_identity()=='ou_backup'
    else:
        with pytest.raises(ValueError):setup.backup_bot_identity()
    assert calls[-1]=='closed' and calls[0].endswith('/bot/v3/info')

@pytest.mark.parametrize('problem',['valid','missing','incomplete','stale','name_only','wrong_folder'])
def test_ui_acl_proof_required_without_memberlist(tmp_path,monkeypatch,problem):
    from datetime import timedelta
    monkeypatch.setattr(setup,'STATE',tmp_path)
    monkeypatch.setattr(setup,'backup_bot_identity',lambda:'ou_backup')
    calls=[]
    def call(args,backup=False):
        calls.append(args)
        assert '+member-list' not in args
        return {'permission_public':{'external_access_entity':'closed','link_share_entity':'closed'}}
    monkeypatch.setattr(setup,'call',call)
    proof={'folder':setup.FOLDER,'observed_at':datetime.now(timezone.utc).isoformat(),'list_complete':True,
           'members':[{'member_type':'openid','member_id':'ou_owner','perm':'owner'}]}
    if problem=='incomplete':proof['list_complete']=False
    if problem=='stale':proof['observed_at']=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    if problem=='name_only':proof['members'][0]['member_id']='jekai'
    if problem=='wrong_folder':proof['folder']='other'
    if problem!='missing':setup.save('ui-acl.json',proof)
    if problem=='valid':assert setup.facts()['members']==proof['members']
    else:
        with pytest.raises((ValueError,FileNotFoundError)):setup.facts()
