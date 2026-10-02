from copy import deepcopy
import pytest
from .test_node_skip import ws,draft,node,approved
from .node_skip import current,fingerprint,refresh_skips,snapshot


def test_new_skip_ignores_unrelated_quote_cost_and_refresh_fields(ws):
    item=approved(ws);p=ws['projects'][0];n=node(ws)
    assert item['skip_scope_version']==3 and current(ws,p,n,item)
    p['quotes']=[{'id':'quote','fields':{'實際成本':999}}]
    p['source_records']=[{'id':'source','fields':{'主管檢核':True}}]
    p['source_scope_hash']='unrelated-source-change'
    n['tasks'][0]['source_fields']={'實際成本':999}
    n['tasks'][0]['source_changed_at']='2026-09-29T12:00:00'
    refresh_skips(ws,p)
    assert item['status']=='approved' and current(ws,p,n,item)


@pytest.mark.parametrize('field,value',[('title','Different work'),('owner_id','u-field'),
    ('due_date','2026-10-10'),('output','Changed result'),('status','completed')])
def test_new_skip_still_binds_actual_work_fields(ws,field,value):
    item=approved(ws);p=ws['projects'][0];n=node(ws)
    n['tasks'][0][field]=value
    assert not current(ws,p,n,item)
    refresh_skips(ws,p);assert item['status']=='invalidated'


def test_new_skip_quantity_and_work_relationship_are_semantic_scope(ws):
    p=ws['projects'][0];n=node(ws)
    n['tasks'][0]['source_fields']={'數量':5,'來源合約明細（日報關聯）':['recA'],'實際成本':10}
    item=approved(ws);n['tasks'][0]['source_fields']['實際成本']=20
    assert current(ws,p,n,item)
    n['tasks'][0]['source_fields']['數量']=6
    assert not current(ws,p,n,item)


@pytest.mark.parametrize('field,old,new',[
    ('確認範圍','原範圍','新增工程'),('工程內容','控制測量','控制及圖資'),
    ('數量',5,6),('合約數量',5,6),('單位','點','公頃'),
    ('合約工項',['recA'],['recB']),('所屬成案確認單',['recC'],['recD'])])
def test_quote_work_change_invalidates_approved_skip_without_task_revision(ws,field,old,new):
    p=ws['projects'][0];n=node(ws)
    p['quotes']=[{'id':'q1','fields':{field:old,'實際總成本':10}}]
    item=approved(ws);tasks=deepcopy(n['tasks']);revision=p['revision']
    p['quotes'][0]['fields']['實際總成本']=20
    assert current(ws,p,n,item)
    p['quotes'][0]['fields'][field]=new
    assert not current(ws,p,n,item)
    refresh_skips(ws,p)
    assert item['status']=='invalidated' and n['tasks']==tasks and p['revision']==revision


def test_quote_scope_add_remove_and_order_are_semantic(ws):
    p=ws['projects'][0];n=node(ws)
    p['quotes']=[{'id':'q1','fields':{'工程內容':'控制'}},
                 {'id':'q2','fields':{'工程內容':'圖資'}}]
    item=approved(ws)
    p['quotes'].reverse()
    assert current(ws,p,n,item)
    p['quotes'].append({'id':'cost','fields':{'實際成本':200}})
    assert current(ws,p,n,item)
    removed=p['quotes'].pop(0)
    assert not current(ws,p,n,item)
    p['quotes'].append(removed)
    assert current(ws,p,n,item)
    p['quotes'].append({'id':'q3','fields':{'確認範圍':'新增報告'}})
    assert not current(ws,p,n,item)


def test_legacy_scope_still_includes_cost_changes(ws):
    p=ws['projects'][0];n=node(ws)
    p['quotes']=[{'id':'q1','fields':{'實際成本':1}}]
    before=fingerprint(ws,p,n,scope_version=1)
    assert 'quote_work_scope' not in snapshot(ws,p,n,1)
    p['quotes'][0]['fields']['實際成本']=2
    assert fingerprint(ws,p,n,scope_version=1)!=before


def test_existing_bound_legacy_request_keeps_exact_old_hash_and_unknown_binding(ws):
    p=ws['projects'][0];n=node(ws);item=draft(ws)
    item.pop('skip_scope_version')
    item['snapshot']=snapshot(ws,p,n)
    item['content_hash']=fingerprint(ws,p,n,item['reason'],item['impact'])
    item['status']='pending'
    item['native_binding']={'attempted':True,'status':'outcome_unknown','binding_hash':'original',
                            'identity':{'scope_hash':item['content_hash']}}
    before=deepcopy(item['native_binding']);old_hash=item['content_hash']
    assert current(ws,p,n,item)
    p['source_scope_hash']='changed'
    assert not current(ws,p,n,item)
    refresh_skips(ws,p)
    assert item['status']=='invalidated' and item['content_hash']==old_hash
    assert 'skip_scope_version' not in item and item['native_binding']==before


def test_unknown_future_skip_scope_version_never_falls_back(ws):
    item=draft(ws);item['skip_scope_version']=99
    assert not current(ws,ws['projects'][0],node(ws),item)


@pytest.mark.parametrize('level,key,value',[
    ('project','source_missing',True),('node','source_missing',True),
    ('project','archived_at','2026-09-29'),('node','archived_at','2026-09-29'),
    ('project','migrated_to','other'),('node','migrated_to','other')])
def test_existence_changes_invalidate_new_skip(ws,level,key,value):
    item=draft(ws);p=ws['projects'][0];n=node(ws)
    assert current(ws,p,n,item)
    target=p if level=='project' else n;target[key]=value
    assert not current(ws,p,n,item)


def test_absent_false_and_none_existence_flags_are_equivalent(ws):
    item=draft(ws);p=ws['projects'][0];n=node(ws)
    p.update(source_missing=False,archived_at=None,migrated_to=None)
    n.update(source_missing=False,archived_at=None,migrated_to=None)
    assert current(ws,p,n,item)


def test_real_source_deletion_writer_invalidates_scope_without_losing_results(ws):
    from .source_projection import preserve_missing_sources
    from .approval_scope import task_scope
    p=ws['projects'][0];n=node(ws);task=n['tasks'][0]
    source={'base_token':'isolated','table_id':'work','record_id':'recWork'}
    task['source_identity']=source;task['output']='保留成果'
    before=task_scope(task);item=draft(ws)
    table={'base_token':'isolated','table_id':'work','status':'ready'}
    preserve_missing_sources(ws,[],[table],{})
    assert task['source_missing'] is True and task['output']=='保留成果'
    assert task_scope(task)!=before and not current(ws,p,n,item)
    preserve_missing_sources(ws,[source],[table],{})
    assert 'source_missing' not in task and task_scope(task)==before
