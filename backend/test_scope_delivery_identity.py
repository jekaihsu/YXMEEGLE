from copy import deepcopy
import pytest
from fastapi import HTTPException
from .test_node_skip import ws,draft,node
from .node_skip import current,refresh_skips,fingerprint
from .native_requests import scope_hash
from .test_native_scope_semantics import fixture


def test_remote_copy_metadata_preserves_new_skip_but_bytes_and_withdrawal_do_not(ws):
    p=ws['projects'][0];n=node(ws)
    document={'id':'f','node_id':n['id'],'version':'1','sha256':'abc','name':'survey.pdf'}
    p['files']=[document];item=draft(ws)
    document.update(remote_status='verified',remote_token='real',remote_url='https://company',verified_at='later')
    assert current(ws,p,n,item)
    document['sha256']='changed'
    assert not current(ws,p,n,item)
    document['sha256']='abc';document['withdrawn']=True
    assert not current(ws,p,n,item)


@pytest.mark.parametrize('field',['此報價之合約工項明細','合約工作項目','新欄位名稱'])
def test_unknown_work_fields_fail_closed(ws,field):
    p=ws['projects'][0];n=node(ws);p['quotes']=[{'id':'q','fields':{field:['a']}}]
    item=draft(ws);p['quotes'][0]['fields'][field]=['a','b']
    assert not current(ws,p,n,item)


def test_existing_v2_hash_is_not_rewritten(ws):
    p=ws['projects'][0];n=node(ws);p['files']=[{'id':'f','node_id':n['id'],'remote_status':'queued'}]
    before=fingerprint(ws,p,n,scope_version=2)
    p['files'][0]['remote_status']='verified'
    assert fingerprint(ws,p,n,scope_version=2)!=before


def test_native_extension_file_metadata_does_not_revoke_new_scope():
    state,p,n,item=fixture();p['files']=[{'id':'f','version':'1','sha256':'abc','remote_status':'queued'}]
    item['evidence_ids']=['f'];before=scope_hash(state,p,n,item)
    p['files'][0].update(remote_status='verified',remote_token='remote',verified_at='later')
    assert scope_hash(state,p,n,item)==before
    p['files'][0]['version']='2'
    assert scope_hash(state,p,n,item)!=before


def test_invalid_attempt_must_resolve_before_new_skip(ws):
    p=ws['projects'][0];n=node(ws);item=draft(ws)
    item.update(status='pending',native_binding={'attempted':True,'payload':{'uuid':'same'}})
    n['tasks'][0]['title']='new work';refresh_skips(ws,p)
    assert item['status']=='invalidated' and item['remote_resolution_required']
    with pytest.raises(HTTPException):draft(ws)
    assert len(ws['node_skip_requests'])==1
