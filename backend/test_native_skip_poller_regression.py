import json
from .test_native_routes import api,operate
from .test_source_sync import harness
from .test_native_approval import fixture
from .node_skip import apply_skip,valid_waiver
from .native_poller import NativeApprovalPoller
from . import storage


def test_background_approved_poll_preserves_applied_skip_with_semantic_scope(api):
    h=api.h;h.cfg['LARK_NATIVE_APPROVAL_MAPPINGS_JSON']=json.dumps({'node_skip':fixture()[0]})
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        apply_skip(state,state['users'][0],{'action':'node_skip_create','project_id':api.pid,'node_id':api.nid,
            'payload':{'reason':'不適用','impact':'其他交付照常'}},False)
        state['node_skip_requests'][-1]['id']='request'
        row.data=storage.save(db,h.B,h.wid,state)
    assert operate(api,'prepare','node_skip').status_code==200
    api.external[0]='APPROVED'
    assert operate(api,'submit','node_skip').status_code==200
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        state['node_skip_requests'][0]['status']='applied'
        p=state['projects'][0];n=next(n for n in p['nodes'] if n['id']==api.nid)
        n.update(status='approved_skipped',skip_request_id='request')
        p['source_scope_hash']='unrelated costs changed'
        row.data=storage.save(db,h.B,h.wid,state)
    before=len(api.calls)
    poller=NativeApprovalPoller(h.sessions,h.W,h.B,h.P,h.cfg,api.adapter_factory)
    assert poller.run_due(h.wid)==[{'id':'request','status':'observed'}]
    state,_=h.read();p=state['projects'][0];n=next(n for n in p['nodes'] if n['id']==api.nid)
    assert state['node_skip_requests'][0]['status']=='applied'
    assert n['status']=='approved_skipped' and valid_waiver(state,p,n)
    assert all(method=='GET' for method,_ in api.calls[before:])
