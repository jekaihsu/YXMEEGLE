from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from . import storage
from .approval_capabilities import approval_connection
from .lark_adapter import RemoteFailure
from .native_approval import digest
from .test_native_routes import api
from .test_source_sync import harness
from .test_native_approval import fixture
from .workflow import now


def setup_manager(api):
    h=api.h
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        actor=next(u for u in state['users'] if u['id']==api.actor[0])
        actor.update(role='manager',directory_last_seen_at=now())
        row.data=storage.save(db,h.B,h.wid,state)
    mappings={}
    for kind in ('change','extension','node_skip','financial'):
        mapping=deepcopy(fixture()[0]);mapping['kind']=kind
        mapping['nodes'][0]['seats']=['pm','admin'] if kind=='financial' else ['supervisor'] if kind=='extension' else ['pm','supervisor']
        mappings[kind]=mapping
    h.cfg['LARK_NATIVE_APPROVAL_MAPPINGS_JSON']=json.dumps(mappings)
    return mappings


def verify(api,version=None):
    return api.client.post('/api/native-approvals/definitions/verify',json={
        'version':api.h.read()[0]['version'] if version is None else version})


def test_normal_manager_reads_all_four_and_persists_health_without_cases_or_submissions(api):
    setup_manager(api)
    api.h.cfg.update(DEMO_MODE='true',LARK_NATIVE_APPROVAL_SUBMIT_ENABLED='false')
    before=api.h.read()[0]
    response=verify(api)
    assert response.status_code==200,response.text
    state=response.json();evidence=state['native_definition_verification']
    assert len(api.calls)==4 and all(method=='GET' and '/approvals/' in path for method,path in api.calls)
    assert all(p['status']=='verified' for p in evidence['by_type'].values())
    assert state['projects']==before['projects'] and state['approvals']==before['approvals']
    assert state['version']==before['version']+1
    assert state['events'][0]['action']=='native_definitions_verify'
    public=approval_connection(api.h.cfg,definition_verification=evidence)
    assert public['definition_mapping_verified'] and not public['native_submit']['enabled']
    assert not public['trusted_result_binding']
    assert all(v['verified_at'] for v in public['native_submit']['by_type'].values())
    assert evidence['checked_by'] not in json.dumps(public)
    assert evidence['mapping_set_hash'] not in json.dumps(public)
    assert 'definition_mapping_unverified' not in {b['code'] for b in public['native_submit']['blockers']}
    assert {'submission_disabled','end_to_end_unverified','result_binding_unverified'} <= {b['code'] for b in public['native_submit']['blockers']}


@pytest.mark.parametrize('change',['member','inactive','stale','recovery'])
def test_only_normal_manager_can_check_definitions(api,change):
    setup_manager(api);h=api.h
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        actor=state['users'][0]
        if change=='member':actor['role']='member'
        if change=='inactive':actor['active']=False
        if change in ('stale','recovery'):actor['directory_last_seen_at']='2020-01-01T00:00:00+00:00'
        if change=='recovery':actor['bootstrap_admin']=True
        row.data=storage.save(db,h.B,h.wid,state)
    assert verify(api).status_code==403 and not api.calls
    assert 'native_definition_verification' not in h.read()[0]


def test_stale_version_stops_before_remote_io(api):
    setup_manager(api)
    assert verify(api,0).status_code==409 and not api.calls


@pytest.mark.parametrize('change',['actor','policy','version'])
def test_change_during_get_prevents_health_commit(api,change):
    setup_manager(api);h=api.h
    service=api.client.app.state.native_approval_service
    original=service.adapter_factory
    def factory(cfg):
        adapter=original(cfg);request=adapter.request
        def changed(method,path,**kwargs):
            result=request(method,path,**kwargs)
            if change=='policy':h.cfg['LARK_ALLOWED_TENANTS']='other'
            else:
                with h.sessions.begin() as db:
                    row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
                    if change=='actor':state['users'][0]['active']=False
                    else:row.version+=1;state['version']=row.version
                    row.data=storage.save(db,h.B,h.wid,state)
            return result
        adapter.request=changed
        return adapter
    service.adapter_factory=factory
    assert verify(api).status_code in (403,409)
    assert 'native_definition_verification' not in h.read()[0]
    assert all(method=='GET' for method,_ in api.calls)


@pytest.mark.parametrize('failure',['network','drift','malformed'])
def test_failed_recheck_replaces_old_verified_health(api,failure):
    setup_manager(api)
    assert verify(api).status_code==200
    service=api.client.app.state.native_approval_service
    original=service.adapter_factory
    def factory(cfg):
        adapter=original(cfg)
        def unavailable(*args,**kwargs):
            if failure=='drift':return {'status':'DELETED'}
            if failure=='malformed':return None
            raise RemoteFailure('private remote detail','failed')
        adapter.request=unavailable
        return adapter
    service.adapter_factory=factory
    response=verify(api)
    assert response.status_code==200,response.text
    evidence=response.json()['native_definition_verification']
    assert all(p['status']=='unverified' for p in evidence['by_type'].values())
    assert 'private remote detail' not in response.text
    assert not approval_connection(api.h.cfg,definition_verification=evidence)['definition_mapping_verified']


@pytest.mark.parametrize('change',['app','tenant','mapping','expired','future','malformed','simulation'])
def test_health_evidence_invalidated_by_context_drift_and_age(api,change):
    mappings=setup_manager(api)
    evidence=verify(api).json()['native_definition_verification']
    cfg=deepcopy(api.h.cfg)
    if change=='app':cfg['LARK_APP_ID']='rotated'
    if change=='tenant':cfg['LARK_WORKER_ORGANIZATION']='other'
    if change=='mapping':
        mappings['extension']['approval_code']='other';cfg['LARK_NATIVE_APPROVAL_MAPPINGS_JSON']=json.dumps(mappings)
    if change in ('expired','future','malformed'):
        stamp=(datetime.now(timezone.utc)+timedelta(hours=-1 if change=='expired' else 1)).isoformat()
        if change=='malformed':stamp='not-a-date'
        for proof in evidence['by_type'].values():proof['verified_at']=stamp
    public=approval_connection(cfg,definition_verification=evidence,simulation_available=change=='simulation')
    assert not public['definition_mapping_verified']
    assert all(not p['definition_mapping_verified'] for p in public['native_submit']['by_type'].values())


def test_unknown_or_missing_mapping_is_unverified_not_fake_success(api):
    setup_manager(api)
    api.h.cfg['LARK_NATIVE_APPROVAL_MAPPINGS_JSON']='{}'
    response=verify(api)
    assert response.status_code==200 and not api.calls
    assert all(p['status']=='unverified' for p in response.json()['native_definition_verification']['by_type'].values())
