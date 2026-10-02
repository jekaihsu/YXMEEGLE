import json
from datetime import datetime,timezone
from copy import deepcopy
import pytest
from .test_source_sync import harness
from .test_input_registration import Fake,is_write
from .input_registration import make_plan,FIELD_NAMES
from .operations import queue
from .jobs import Worker
from . import storage


@pytest.mark.parametrize('unknown',[False,True])
def test_formal_worker_uses_append_registration_and_preserves_unknown(harness,tmp_path,unknown):
    h=harness;state,_=h.read();p=state['projects'][0];n=p['nodes'][0];p['execution_system']='workbench'
    fields={k:{'field_id':'fld'+k,'field_name':v} for k,v in FIELD_NAMES.items()}
    destination={'base_token':'dedicated','table_id':'table','fields':fields}
    state['settings'].update(external_enabled=True,input_base='dedicated',input_table='table')
    revision={'id':'i','mapping_id':'m','project_id':p['id'],'node_id':n['id'],'actor_id':'u-manager',
              'created_at':'2026-09-29','value':'成果','status':'queued'}
    revision['registration_plan']=make_plan(h.wid,p,n,revision,destination)
    state['input_revisions']=[revision]
    state['input_mappings']=[dict(id='m',project_id=p['id'],node_id=n['id'],enabled=True,
        verified=False,mode='append_registration',**destination)]
    actor=next(u for u in state['users'] if u['id']=='u-manager')
    p['pm_id']=actor['id']; n['owner_id']=actor['id']
    actor.update(directory_status='employed',directory_missing=False,
        directory_source={'app_id':h.cfg['LARK_APP_ID'],'record_id':'input-worker-roster'},
        directory_last_seen_at=datetime.now(timezone.utc).isoformat())
    queue(state,'input',actor,{'input_id':'i','mapping_id':'m','project_id':p['id']},'input:i')
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);row.data=storage.save(db,h.B,h.wid,state)
        db.get(h.P,(h.wid,actor['id'])).data=deepcopy(actor)
    h.cfg.update(LARK_INPUT_BASE_TOKEN='dedicated',LARK_INPUT_TABLE_ID='table',
                 LARK_INPUT_REGISTRATION_FIELDS_JSON=json.dumps(fields))
    fake=Fake(revision['registration_plan']);fake.timeout=unknown;fake.lost=unknown
    class Client:
        def close(self):pass
    fake.client=Client()
    worker=Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path,adapter_factory=lambda cfg:fake)
    worker.run_one(h.wid)
    result=h.read()[0];saved=result['input_revisions'][0]
    assert saved['status']==('outcome_unknown' if unknown else 'succeeded')
    assert sum(map(is_write,fake.calls))==1 and all(c[0]!='PUT' for c in fake.calls)
    if not unknown:assert saved['receipt']['operation']=='append_registration'
    else:
        previous=deepcopy(fake.calls);worker.run_one(h.wid)
        assert fake.calls==previous
