"""Read-only diagnostics of the one existing joint QA run; no instance mutation."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.native_qa import QAStore,QAError,policy
from backend.native_approval import digest,verify_definition,verify_instance
from backend.lark_adapter import RemoteFailure
from backend.sources import API

RUN='qa-joint-20260930'
INSTANCE='2D9E52F7-298A-4FE2-A1CF-C9403B5B551E'
APP='cli_aa3cab98b2789e17'
DEFINITION='E1DEFC43-3E29-4238-AD9D-91ACF8E29091'


def read_inputs(saved_config):
    directory=ROOT/'.runtime/native-qa'
    manifest=json.loads((directory/'config.json').read_text(encoding='utf-8-sig'))
    raw=json.loads(Path(saved_config).read_text(encoding='utf-8-sig'))
    cfg=dict(raw.get('variables',{}).get('data',raw))
    cfg.update({k:v for k,v in os.environ.items() if k.startswith('LARK_')})
    expected=policy(manifest,cfg)
    if cfg.get('LARK_APP_ID')!=APP or manifest['mapping']['approval_code']!=DEFINITION:raise QAError('fixed_target_mismatch')
    with sqlite3.connect((directory/'attempts.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        record=QAStore.unpack(db.execute('SELECT * FROM qa_runs WHERE run_id=?',(RUN,)).fetchone())
    binding=record['binding']
    immutable={k:binding[k] for k in ('purpose','identity','policy','kind','mapping','definition_hash','approvers','payload')}
    if not record['attempted'] or binding.get('instance_code')!=INSTANCE:raise QAError('existing_instance_required')
    if binding.get('qa_binding_hash')!=digest(immutable) or binding['policy']!=expected:raise QAError('qa_policy_or_binding_changed')
    return cfg,manifest,record


def request(client,stage,method,path,steps,**kwargs):
    try:response=client.request(method,API+path,**kwargs)
    except httpx.HTTPError as exc:
        steps.append({'stage':stage,'ok':False,'transport_error':type(exc).__name__})
        return None
    try:body=response.json()
    except (ValueError,TypeError):body=None
    code=body.get('code') if isinstance(body,dict) else None
    valid=isinstance(body,dict) and response.status_code==200 and body.get('code',0)==0
    steps.append({'stage':stage,'ok':valid,'http_status':response.status_code,
                  'api_code':code if type(code) is int else None,'json_object':isinstance(body,dict)})
    return body if valid else None


def diagnose(cfg,manifest,record,client):
    steps=[]
    result={'run_id':RUN,'checked_at':datetime.now(timezone.utc).isoformat(),'read_only':True,
            'instance_mutations':0,'journal_mutations':0,'steps':steps,'verified':False}
    body=request(client,'application_token','POST','/auth/v3/tenant_access_token/internal',steps,
                 json={'app_id':cfg['LARK_APP_ID'],'app_secret':cfg['LARK_APP_SECRET']})
    if body is None:return result
    token=body.get('tenant_access_token')
    if not isinstance(token,str) or not token:
        steps[-1].update(ok=False,missing_token=True);return result
    headers={'Authorization':'Bearer '+token}
    body=request(client,'definition_read','GET','/approval/v4/approvals/'+DEFINITION,steps,
                 headers=headers,params={'user_id_type':'open_id'})
    if body is None:return result
    definition=body.get('data');binding=record['binding']
    try:
        if not isinstance(definition,dict) or definition.get('approval_name')!=manifest['definition_name']:raise ValueError()
        fingerprint=verify_definition(definition,manifest['mapping'])
        if fingerprint!=binding['definition_hash']:raise ValueError()
    except (RemoteFailure,ValueError,KeyError,TypeError):
        result['verification_failure']='definition_contract_or_fingerprint_changed';return result
    body=request(client,'existing_instance_read','GET','/approval/v4/instances/'+quote(binding['payload']['uuid'],safe=''),
                 steps,headers=headers,params={'user_id_type':'open_id'})
    if body is None:return result
    instance=body.get('data')
    try:receipt=verify_instance(binding,instance)
    except (RemoteFailure,ValueError,KeyError,TypeError,AttributeError):
        result['verification_failure']='existing_instance_receipt_mismatch';return result
    result.update(verified=True,external_status=receipt['external_status'],approved=receipt['approved'],
                  binding_verified=receipt['binding_verified'])
    counts=Counter(t.get('status') for t in instance.get('task_list',[]) if isinstance(t,dict))
    result['task_status_counts']={k:counts[k] for k in ('PENDING','APPROVED','REJECTED','TRANSFERRED','DONE') if counts[k]}
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved-config',default=str(ROOT/'.runtime/login-cutover/company-intended.json'))
    args=parser.parse_args(argv)
    try:
        cfg,manifest,record=read_inputs(args.saved_config)
        with httpx.Client(timeout=25,follow_redirects=False) as client:result=diagnose(cfg,manifest,record,client)
        (ROOT/'.runtime/native-qa/diagnostic.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result));return 0 if result['verified'] else 1
    except QAError as exc:code=str(exc)
    except Exception:code='local_diagnostic_input_invalid'
    print(json.dumps({'verified':False,'read_only':True,'error':code}));return 1


if __name__=='__main__':raise SystemExit(main())
