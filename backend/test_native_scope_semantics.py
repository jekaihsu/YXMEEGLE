from copy import deepcopy
from .seed import seed
from .policy import upgrade
from .native_requests import scope_hash


def fixture():
    ws=upgrade(seed());p=ws['projects'][0];n=p['nodes'][3]
    item={'id':'request','type':'extension','project_revision':p['revision'],
          'task_ids':[n['tasks'][0]['id']],'dates':['2026-10-01'],'reason':'date change'}
    return ws,p,n,item


def test_unrelated_source_finance_and_read_timestamps_do_not_change_new_scope():
    ws,p,n,item=fixture();original=scope_hash(ws,p,n,item)
    p.update(source_scope_hash='different-cost-total',source_records=[{'id':'source','fields':{'actual_cost':500}}])
    task=n['tasks'][0];task.update(source_changed_at='later',source_fields={'實際總成本':500},points=900)
    assert scope_hash(ws,p,n,item)==original


def test_actual_task_scope_and_role_changes_still_invalidate():
    ws,p,n,item=fixture();original=scope_hash(ws,p,n,item)
    n['tasks'][0]['due_date']='2026-10-03'
    assert scope_hash(ws,p,n,item)!=original
    ws,p,n,item=fixture();original=scope_hash(ws,p,n,item)
    p['pm_id']='different-pm'
    assert scope_hash(ws,p,n,item)!=original


def test_legacy_bound_scope_is_not_silently_reinterpreted():
    ws,p,n,item=fixture();item['native_binding']={'identity':{}}
    original=scope_hash(ws,p,n,item)
    p['source_records']=[{'id':'source','fields':{'actual_cost':500}}]
    assert scope_hash(ws,p,n,item)!=original


def test_v2_binding_keeps_same_scope_before_and_after_checkpoint():
    ws,p,n,item=fixture();original=scope_hash(ws,p,n,item)
    item.update(approval_scope_version=2,native_binding={'identity':{}})
    assert scope_hash(ws,p,n,item)==original


def test_source_removal_and_project_archival_invalidate_semantic_scope():
    for target,key in (('task','source_missing'),('project','source_missing'),
                       ('project','archived_at'),('project','migrated_to'),('node','archived_at')):
        ws,p,n,item=fixture();original=scope_hash(ws,p,n,item)
        record={'task':n['tasks'][0],'project':p,'node':n}[target]
        record[key]=True
        assert scope_hash(ws,p,n,item)!=original


def test_absent_and_false_source_missing_are_equivalent():
    ws,p,n,item=fixture();original=scope_hash(ws,p,n,item)
    n['tasks'][0]['source_missing']=False;p['source_missing']=False
    assert scope_hash(ws,p,n,item)==original
