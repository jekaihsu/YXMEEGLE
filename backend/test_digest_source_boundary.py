"""Queued digests retain exact case provenance and recheck it at every send."""
from copy import deepcopy
from datetime import datetime,timezone
from types import SimpleNamespace
import pytest
from . import storage
from .jobs import Worker
from .operations import queue
from .test_source_sync import harness


@pytest.mark.parametrize('scenario',['allowed','legacy','baseline','mixed','unknown','pending','mid_send'])
def test_production_digest_source_gate(harness,tmp_path,scenario):
    h=harness;state,_=h.read();p=state['projects'][0]
    p.update(case_visibility='new_case',execution_system='workbench')
    actor=next(u for u in state['users'] if u['id']=='u-manager')
    actor.update(identity_app_id=h.cfg['LARK_APP_ID'],directory_status='employed',directory_missing=False,
        directory_source={'app_id':h.cfg['LARK_APP_ID'],'record_id':'digest-roster'},
        directory_last_seen_at=datetime.now(timezone.utc).isoformat())
    state['settings']['external_enabled']=True
    payload={'recipients':[actor['id']],'text':'digest','source_scope':'case_digest_v1','source_project_ids':[p['id']]}
    if scenario=='legacy':payload.pop('source_project_ids')
    if scenario=='unknown':payload['source_project_ids'].append('unknown-case')
    if scenario=='mixed':
        other=deepcopy(p);other.update(id='historic-other',case_visibility='excluded_history')
        def reid(v):  # child ids must stay unique per kind within a workspace
            for k,x in v.items():
                if isinstance(x,list):
                    for i in x:
                        if isinstance(i,dict):
                            if 'id' in i:i['id']='other-'+str(i['id'])
                            reid(i)
        reid(other)
        state['projects'].append(other);payload['source_project_ids'].append(other['id'])
    job=queue(state,'digest',actor,payload,'source-boundary')
    if scenario=='baseline':p['case_visibility']='excluded_history'
    if scenario=='pending':p['execution_system']='pending'
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);row.data=storage.save(db,h.B,h.wid,state)
        db.get(h.P,(h.wid,actor['id'])).data=deepcopy(actor)
    calls=[]
    class Client:
        def request(self,*args,**kwargs):calls.append(True);return {}
        def close(self):pass
    class Adapter:
        client=Client()
        def message(self,*args):
            if scenario=='mid_send':
                with h.sessions.begin() as db:
                    row=db.get(h.W,h.wid);latest=storage.load(db,h.B,row)
                    next(x for x in latest['projects'] if x['id']==p['id'])['case_visibility']='excluded_history'
                    row.data=storage.save(db,h.B,h.wid,latest)
            self.client.request('POST','/messages')
            return {'message_id':'sent'}
    worker=Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path,lambda cfg:Adapter())
    worker.run_one(h.wid)
    result=next(x for x in h.read()[0]['jobs'] if x['id']==job['id'])
    assert result['status']==('succeeded' if scenario=='allowed' else 'blocked')
    assert len(calls)==(1 if scenario=='allowed' else 0)
