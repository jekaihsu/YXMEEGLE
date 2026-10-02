from copy import deepcopy
from types import SimpleNamespace
import json
import httpx
from scripts.native_qa_diagnose import diagnose
from .test_native_approval import fixture
from .native_approval import digest


def test_token_failure_is_distinguished_without_leaking_secret_or_response():
    calls=[]
    class Client:
        def request(self,method,path,**kwargs):
            calls.append((method,path))
            return httpx.Response(200,json={'code':10014,'msg':'private-secret-details'})
    report=diagnose({'LARK_APP_ID':'app','LARK_APP_SECRET':'hidden-secret'},{},{},Client())
    assert report['steps']==[{'stage':'application_token','ok':False,'http_status':200,'api_code':10014,'json_object':True}]
    assert len(calls)==1 and 'secret' not in json.dumps(report)


def test_pending_existing_instance_is_read_only_and_journal_untouched():
    mapping,definition,_,binding,instance=fixture()
    definition['approval_name']='QA';binding['definition_hash']=digest(definition)
    instance['status']='PENDING'
    original=deepcopy(binding);calls=[]
    class Client:
        def request(self,method,path,**kwargs):
            calls.append((method,path))
            data={'tenant_access_token':'hidden-token'} if method=='POST' else {'code':0,'data':definition if '/approvals/' in path else instance}
            return httpx.Response(200,json=data)
    report=diagnose({'LARK_APP_ID':'app','LARK_APP_SECRET':'hidden-secret'},
                    {'definition_name':'QA','mapping':mapping},{'binding':binding},Client())
    assert report['verified'] and report['external_status']=='PENDING' and not report['approved']
    assert [m for m,_ in calls]==['POST','GET','GET']
    assert calls[0][1].endswith('/auth/v3/tenant_access_token/internal')
    assert binding==original and report['journal_mutations']==report['instance_mutations']==0
    assert 'hidden-' not in json.dumps(report)


def test_connection_failure_is_safe_stage_specific_result():
    class Client:
        def request(self,*args,**kwargs):raise httpx.ConnectError('secret URL or token')
    result=diagnose({'LARK_APP_ID':'app','LARK_APP_SECRET':'secret'},{},{},Client())
    assert result['steps']==[{'stage':'application_token','ok':False,'transport_error':'ConnectError'}]
    assert 'secret' not in json.dumps(result)
